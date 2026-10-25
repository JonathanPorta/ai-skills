#!/usr/bin/env python3
"""Inspect a local OpenDesign daemon and copy existing artifacts (GET only)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import zipfile


class InspectionError(Exception):
    """An actionable API, selection, or download error."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, url, workspace_id=None, member_id=None, timeout=15):
        parsed = urlsplit(url or "")
        if (parsed.scheme != "http" or parsed.hostname not in
                {"localhost", "127.0.0.1", "::1"} or parsed.username or
                parsed.password or parsed.path not in {"", "/"} or
                parsed.query or parsed.fragment):
            raise InspectionError("Set OD_URL or --url to the local API origin, e.g. http://127.0.0.1:PORT")
        try:
            parsed.port
        except ValueError as error:
            raise InspectionError(str(error)) from error
        if bool(workspace_id) != bool(member_id):
            raise InspectionError("Supply both workspace ID and member ID from the same directory entry")
        self.url = url.rstrip("/")
        self.workspace_id = workspace_id
        self.timeout = timeout
        self.headers = {}
        if workspace_id:
            self.headers = {"x-od-workspace-id": workspace_id,
                            "x-od-workspace-member-id": member_id}
        # Keep localhost traffic local even when the environment defines a proxy.
        self.opener = build_opener(ProxyHandler({}), NoRedirects())

    def get(self, path):
        try:
            return self.opener.open(Request(self.url + path, headers=self.headers),
                                    timeout=self.timeout)
        except HTTPError as error:
            body = error.read(8192).decode("utf-8", errors="replace")
            raise InspectionError(f"HTTP {error.code} {path}: {body}") from error
        except (URLError, OSError) as error:
            raise InspectionError(f"Cannot reach {self.url}: {error}") from error

    def json(self, path):
        with self.get(path) as response:
            if response.headers.get_content_type() != "application/json":
                raise InspectionError(f"Expected JSON from {path}; check the daemon port (the Next.js UI returns HTML)")
            try:
                result = json.load(response)
            except (ValueError, UnicodeError) as error:
                raise InspectionError(f"Invalid JSON from {path}") from error
        if not isinstance(result, dict):
            raise InspectionError(f"Expected a JSON object from {path}")
        return result


def segment(value):
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise InspectionError("Invalid project, run, or workspace identifier")
    return quote(value, safe="")


def file_path(value):
    if (not value or value.startswith("/") or "\\" in value or
            any(part in {"", ".", ".."} for part in value.split("/")) or
            any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise InspectionError("Artifact path must be a safe project-relative path")
    return quote(value, safe="/")


def project_route(project_id):
    return "/api/projects/" + segment(project_id)


def array_field(body, key):
    value = body.get(key)
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise InspectionError(f"Unexpected API shape: expected {key} array of objects")
    return value


VERSION = r"((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))"
SLUG = r"([a-z0-9]+(?:-[a-z0-9]+)*)"
CHECKPOINT = re.compile(SLUG + r"-checkpoint-" + VERSION + r"\.zip", re.IGNORECASE)
HANDOFF = re.compile(SLUG + r"-v?" + VERSION + r"\.zip", re.IGNORECASE)


def classify_name(path):
    name = PurePosixPath(path).name
    for kind, pattern in (("checkpoint", CHECKPOINT), ("handoff", HANDOFF)):
        match = pattern.fullmatch(name)
        if match:
            return {"packageKind": kind, "projectSlug": match[1], "version": match[2],
                    "classification": "filename"}
    return {"packageKind": "archive" if name.lower().endswith(".zip") else "file",
            "projectSlug": None, "version": None, "classification": "filename"}


def artifact_inventory(client, project_id):
    body = client.json(project_route(project_id) + "/files")
    files = array_field(body, "files")
    result = []
    for item in files:
        path = item.get("path") or item.get("name")
        if not isinstance(path, str):
            raise InspectionError("File inventory entry lacks a path")
        file_path(path)
        result.append({**item, "path": path, **classify_name(path)})
    return result


def number(value):
    return value if isinstance(value, (float, int)) else 0


def version_key(item):
    version = tuple(int(n) for n in item["version"].split(".")) if item["version"] else (-1, -1, -1)
    return ((item["projectSlug"] or "").casefold(), item["packageKind"],
            tuple(-n for n in version), -number(item.get("mtime")), item["path"])


def archive_kind(path):
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError) as error:
        raise InspectionError("Downloaded file is not a readable ZIP archive") from error
    handoff_markers = {"_handoff/MANIFEST.json", "_handoff/README.md", "_handoff/CHECKSUMS.sha256"}
    handoff = handoff_markers <= names
    checkpoint = "_checkpoint/CHANGELOG.md" in names
    if handoff and not checkpoint:
        return "handoff"
    if checkpoint and not (handoff_markers & names):
        return "checkpoint"
    return "archive"


def download(client, project_id, path, output):
    encoded = file_path(path)
    destination = Path(output).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise InspectionError(f"Destination already exists: {destination}")
    if not destination.parent.is_dir():
        raise InspectionError(f"Destination directory does not exist: {destination.parent}")
    inventory = artifact_inventory(client, project_id)
    selected = next((item for item in inventory if item["path"] == path), None)
    if selected is None:
        raise InspectionError("Artifact is not in this project's file inventory; refresh it or inspect the confirmed project directory")
    temporary = None
    try:
        with client.get(project_route(project_id) + "/files/" + encoded) as response:
            mime = response.headers.get_content_type()
            suffix = PurePosixPath(path).suffix.lower()
            # Text artifacts are legitimate; HTML/JSON cannot masquerade as a ZIP.
            if suffix == ".zip" and mime in {"text/html", "application/json"}:
                raise InspectionError(f"Expected ZIP bytes, received {mime}")
            digest = hashlib.sha256()
            size = 0
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".od-download-", delete=False) as target:
                temporary = Path(target.name)
                while chunk := response.read(1024 * 1024):
                    target.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                target.flush()
                os.fsync(target.fileno())
            expected = selected.get("size")
            if isinstance(expected, int) and size != expected:
                raise InspectionError("Artifact size changed or download is incomplete; refresh inventory and retry")
            kind = archive_kind(temporary) if suffix == ".zip" else "file"
            # Atomic, fail-if-exists publication, including races and dangling links.
            os.link(temporary, destination)
            return {"path": str(destination), "bytes": size, "sha256": digest.hexdigest(),
                    "packageKind": kind, "classification": "zip-metadata" if suffix == ".zip" else "file",
                    "validation": "ZIP directory and metadata markers only; payload checksums and completeness not verified" if suffix == ".zip" else "downloaded bytes"}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("OD_URL"))
    parser.add_argument("--workspace-id", default=os.environ.get("OD_WORKSPACE_ID"))
    parser.add_argument("--member-id", default=os.environ.get("OD_MEMBER_ID"))
    parser.add_argument("--timeout", type=float, default=15)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("health")
    commands.add_parser("workspaces")
    projects = commands.add_parser("projects")
    projects.add_argument("--unbound", action="store_true")
    for name in ("project", "runs"):
        commands.add_parser(name).add_argument("project_id")
    commands.add_parser("run").add_argument("run_id")
    files = commands.add_parser("files")
    files.add_argument("project_id")
    files.add_argument("--ext", help="File extension, e.g. .zip or .png")
    files.add_argument("--kind", choices=("handoff", "checkpoint", "archive"))
    files.add_argument("--sort", choices=("version", "mtime"), default="version")
    fetch = commands.add_parser("download")
    fetch.add_argument("project_id")
    fetch.add_argument("file_path")
    fetch.add_argument("--output", required=True)
    return parser.parse_args()


def execute(args):
    if args.timeout <= 0:
        raise InspectionError("Timeout must be positive")
    client = Client(args.url, args.workspace_id, args.member_id, args.timeout)
    if args.command == "health":
        body = client.json("/api/health")
        if body.get("ok") is not True or not isinstance(body.get("version"), str):
            raise InspectionError("Health response lacks ok:true and version; check the OpenDesign daemon port")
        return body
    if args.command == "workspaces":
        return client.json("/api/workspace/directory")
    if args.command == "projects":
        if args.unbound:
            route = "/api/projects"
        elif client.workspace_id:
            route = "/api/workspaces/" + segment(client.workspace_id) + "/projects"
        else:
            raise InspectionError("Select workspace ID and member ID from workspaces, or use projects --unbound")
        body = client.json(route)
        array_field(body, "projects")
        return body
    if args.command == "project":
        return client.json(project_route(args.project_id))
    if args.command == "runs":
        return client.json("/api/runs?" + urlencode({"projectId": args.project_id}))
    if args.command == "run":
        return client.json("/api/runs/" + segment(args.run_id))
    if args.command == "files":
        files = artifact_inventory(client, args.project_id)
        if args.ext:
            extension = "." + args.ext.lower().lstrip(".")
            files = [item for item in files if item["path"].lower().endswith(extension)]
        if args.kind:
            files = [item for item in files if item["packageKind"] == args.kind]
        key = version_key if args.sort == "version" else lambda item: (-number(item.get("mtime")), item["path"])
        return {"files": sorted(files, key=key)}
    return download(client, args.project_id, args.file_path, args.output)


def main():
    try:
        print(json.dumps(execute(arguments()), indent=2, ensure_ascii=False))
        return 0
    except (InspectionError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
