from __future__ import annotations

from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import quote
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/inspect-opendesign/scripts/opendesign.py"


def zip_bytes(*names: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, "{}" if name.endswith(".json") else "fixture\n")
    return output.getvalue()


def file_record(path: str, mtime: int = 1, size: int = 123) -> dict:
    return {"name": path, "path": path, "type": "file", "size": size, "mtime": mtime}


@contextmanager
def api_server(routes: dict):
    requests: list[tuple[str, dict]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, {key.lower(): value for key, value in self.headers.items()}))
            status, content_type, body, headers = routes.get(
                self.path, (404, "application/json", {"error": "unexpected request"}, {})
            )
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def json_response(value, status: int = 200):
    return status, "application/json", value, {}


class InspectOpenDesignTests(unittest.TestCase):
    def invoke(self, url: str | None, *arguments: str, env: dict | None = None):
        environment = {key: value for key, value in os.environ.items() if not key.startswith("OD_")}
        environment.update(env or {})
        command = [sys.executable, str(SCRIPT)]
        if url is not None:
            command.extend(["--url", url])
        return subprocess.run(
            [*command, *arguments], env=environment, capture_output=True, text=True,
            check=False, timeout=10,
        )

    def parsed(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_health_and_workspace_directory(self):
        directory = {"items": [{"workspaceId": "workspace", "workspaceMemberId": "member"}]}
        with api_server({
            "/api/health": json_response({"ok": True, "version": "0.25.0"}),
            "/api/workspace/directory": json_response(directory),
        }) as (url, requests):
            self.assertEqual(self.parsed(self.invoke(url, "health"))["version"], "0.25.0")
            self.assertEqual(self.parsed(self.invoke(url, "workspaces")), directory)
            self.assertEqual([path for path, _ in requests], ["/api/health", "/api/workspace/directory"])

    def test_nextjs_html_is_not_a_healthy_daemon(self):
        with api_server({"/api/health": (200, "text/html", b"<!doctype html><title>OpenDesign</title>", {})}) as (url, _):
            result = self.invoke(url, "health")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(result.stdout.strip())

    def test_http_error_preserves_explanatory_json(self):
        error = {"error": "AMR_AUTH_REQUIRED", "message": "Sign in again"}
        with api_server({"/api/workspace/directory": json_response(error, 401)}) as (url, _):
            result = self.invoke(url, "workspaces")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("401", result.stderr)
        self.assertIn("AMR_AUTH_REQUIRED", result.stderr)

    def test_scoped_projects_use_matching_headers_and_route(self):
        payload = {"projects": [{"id": "p", "name": "Demo", "resourceState": "active"}]}
        with api_server({"/api/workspaces/workspace/projects": json_response(payload)}) as (url, requests):
            result = self.invoke(url, "--workspace-id", "workspace", "--member-id", "member", "projects")
        self.assertEqual(self.parsed(result), payload)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0][1]["x-od-workspace-id"], "workspace")
        self.assertEqual(requests[0][1]["x-od-workspace-member-id"], "member")

    def test_scope_errors_do_not_silently_list_unbound_projects(self):
        with api_server({}) as (url, requests):
            for arguments in [("projects",), ("--workspace-id", "workspace", "projects"),
                              ("--member-id", "member", "projects")]:
                with self.subTest(arguments=arguments):
                    self.assertNotEqual(self.invoke(url, *arguments).returncode, 0)
            self.assertEqual(requests, [])

    def test_explicit_unbound_list_and_environment_configuration(self):
        with api_server({"/api/projects": json_response({"projects": []}),
                         "/api/workspaces/workspace/projects": json_response({"projects": [{"id": "p"}]})}) as (url, requests):
            self.assertEqual(self.parsed(self.invoke(url, "projects", "--unbound")), {"projects": []})
            result = self.invoke(None, "projects", env={"OD_URL": url, "OD_WORKSPACE_ID": "workspace", "OD_MEMBER_ID": "member"})
            self.assertEqual(self.parsed(result)["projects"][0]["id"], "p")
            self.assertEqual(requests[-1][1]["x-od-workspace-member-id"], "member")

    def test_project_and_run_reads_preserve_status_evidence(self):
        runs = {"runs": [{"id": "r", "status": "succeeded", "endedWithUnfinishedWork": True}],
                "awaitingInputProjectIds": ["p"]}
        detail = {"id": "r", "status": "succeeded", "deliverableValid": False}
        with api_server({"/api/projects/p": json_response({"project": {"id": "p"}, "resolvedDir": "/demo"}),
                         "/api/runs?projectId=p": json_response(runs),
                         "/api/runs/r": json_response(detail)}) as (url, requests):
            scope = ("--workspace-id", "workspace", "--member-id", "member")
            self.assertEqual(self.parsed(self.invoke(url, *scope, "project", "p"))["resolvedDir"], "/demo")
            self.assertEqual(self.parsed(self.invoke(url, *scope, "runs", "p")), runs)
            self.assertEqual(self.parsed(self.invoke(url, *scope, "run", "r")), detail)
            self.assertTrue(all(headers["x-od-workspace-id"] == "workspace" for _, headers in requests))
            self.assertFalse(any("ensureDir" in path for path, _ in requests))

    def test_archive_candidates_have_independent_numeric_version_streams(self):
        paths = ["demo-0.9.0.zip", "demo-checkpoint-0.10.0.zip", "demo-v0.11.0.zip",
                 "demo-0.10.0.ZIP", "demo-checkpoint-0.9.0.zip", "misc.zip", "preview.png"]
        with api_server({"/api/projects/p/files": json_response({"files": [file_record(p) for p in paths]})}) as (url, _):
            files = self.parsed(self.invoke(url, "files", "p", "--ext", ".zip"))["files"]
        handoffs = [f for f in files if f["packageKind"] == "handoff"]
        checkpoints = [f for f in files if f["packageKind"] == "checkpoint"]
        self.assertEqual([f["version"] for f in handoffs], ["0.11.0", "0.10.0", "0.9.0"])
        self.assertEqual([f["version"] for f in checkpoints], ["0.10.0", "0.9.0"])
        self.assertTrue(all(f["projectSlug"] == "demo" for f in handoffs + checkpoints))
        self.assertTrue(all(f["classification"] == "filename" for f in files))
        self.assertEqual(next(f for f in files if f["path"] == "misc.zip")["packageKind"], "archive")
        self.assertNotIn("preview.png", [f["path"] for f in files])

    def test_kind_filter_and_mtime_sort(self):
        files = [file_record("demo-checkpoint-0.1.0.zip", 500), file_record("demo-checkpoint-0.2.0.zip", 100),
                 file_record("demo-2.0.0.zip", 900)]
        with api_server({"/api/projects/p/files": json_response({"files": files})}) as (url, _):
            result = self.parsed(self.invoke(url, "files", "p", "--kind", "checkpoint", "--sort", "mtime"))
        self.assertEqual([f["version"] for f in result["files"]], ["0.1.0", "0.2.0"])

    def test_binary_download_preserves_nested_path_and_identifies_handoff(self):
        path = "exports/review #1/demo-0.10.0.zip"
        body = zip_bytes("index.html", "_handoff/README.md", "_handoff/MANIFEST.json", "_handoff/CHECKSUMS.sha256")
        route = "/api/projects/p/files/" + quote(path, safe="/")
        with tempfile.TemporaryDirectory() as temporary, api_server({
            "/api/projects/p/files": json_response({"files": [file_record(path, size=len(body))]}),
            route: (200, "application/zip", body, {}),
        }) as (url, requests):
            destination = Path(temporary) / "copy.zip"
            result = self.parsed(self.invoke(url, "download", "p", path, "--output", str(destination)))
            self.assertEqual(destination.read_bytes(), body)
            self.assertEqual(result["sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(result["bytes"], len(body))
            self.assertEqual(result["packageKind"], "handoff")
            self.assertEqual([p for p, _ in requests], ["/api/projects/p/files", route])
            self.assertEqual(list(Path(temporary).iterdir()), [destination])

    def test_download_classifies_contents_instead_of_trusting_filename(self):
        path = "demo-1.0.0.zip"
        for expected, body in [("checkpoint", zip_bytes("index.html", "_checkpoint/CHANGELOG.md")),
                               ("archive", zip_bytes("notes.txt"))]:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temporary, api_server({
                "/api/projects/p/files": json_response({"files": [file_record(path, size=len(body))]}),
                "/api/projects/p/files/" + path: (200, "application/zip", body, {}),
            }) as (url, _):
                result = self.parsed(self.invoke(url, "download", "p", path, "--output", str(Path(temporary) / path)))
                self.assertEqual(result["packageKind"], expected)

    def test_mixed_checkpoint_and_handoff_metadata_remains_unclassified(self):
        path = "demo-checkpoint-1.0.0.zip"
        for handoff_names in [("_handoff/MANIFEST.json",),
                              ("_handoff/MANIFEST.json", "_handoff/README.md", "_handoff/CHECKSUMS.sha256")]:
            body = zip_bytes("index.html", "_checkpoint/CHANGELOG.md", *handoff_names)
            with self.subTest(handoff_names=handoff_names), tempfile.TemporaryDirectory() as temporary, api_server({
                "/api/projects/p/files": json_response({"files": [file_record(path, size=len(body))]}),
                "/api/projects/p/files/" + path: (200, "application/zip", body, {}),
            }) as (url, _):
                destination = Path(temporary) / path
                result = self.parsed(self.invoke(url, "download", "p", path, "--output", str(destination)))
                self.assertEqual(result["packageKind"], "archive")
                self.assertEqual(destination.read_bytes(), body)

    def test_unlisted_and_unsafe_paths_are_not_downloaded(self):
        with tempfile.TemporaryDirectory() as temporary, api_server({
            "/api/projects/p/files": json_response({"files": []}),
        }) as (url, requests):
            for path in ["missing.zip", "../outside.zip", "/absolute.zip", "a/../outside.zip", "a\\outside.zip"]:
                with self.subTest(path=path):
                    result = self.invoke(url, "download", "p", path, "--output", str(Path(temporary) / "copy.zip"))
                    self.assertNotEqual(result.returncode, 0)
            self.assertTrue(all(path == "/api/projects/p/files" for path, _ in requests))
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_html_and_json_artifacts_can_be_downloaded_as_themselves(self):
        for path, mime, body in [("preview.html", "text/html", b"<!doctype html><title>Preview</title>"),
                                 ("tokens.json", "application/json", b'{"accent":"red"}')]:
            with self.subTest(path=path), tempfile.TemporaryDirectory() as temporary, api_server({
                "/api/projects/p/files": json_response({"files": [file_record(path, size=len(body))]}),
                "/api/projects/p/files/" + path: (200, mime, body, {}),
            }) as (url, _):
                destination = Path(temporary) / path
                self.parsed(self.invoke(url, "download", "p", path, "--output", str(destination)))
                self.assertEqual(destination.read_bytes(), body)

    def test_existing_destination_is_never_overwritten(self):
        path = "demo-1.0.0.zip"
        with tempfile.TemporaryDirectory() as temporary, api_server({
            "/api/projects/p/files": json_response({"files": [file_record(path)]}),
            "/api/projects/p/files/" + path: (200, "application/zip", zip_bytes("notes.txt"), {}),
        }) as (url, _):
            destination = Path(temporary) / path
            destination.write_bytes(b"keep existing bytes")
            result = self.invoke(url, "download", "p", path, "--output", str(destination))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(destination.read_bytes(), b"keep existing bytes")
            self.assertEqual(list(Path(temporary).iterdir()), [destination])

    def test_failed_downloads_leave_no_archive_or_temporary_file(self):
        path = "demo-1.0.0.zip"
        for content_type, body, advertised_size in [
                ("application/zip", b"not a zip", None),
                ("text/html", b"<!doctype html><h1>Sign in</h1>", None),
                ("application/json", b'{"error":"denied"}', None),
                ("application/zip", zip_bytes("notes.txt"), 1)]:
            with self.subTest(content_type=content_type), tempfile.TemporaryDirectory() as temporary, api_server({
                "/api/projects/p/files": json_response({"files": [file_record(
                    path, size=len(body) if advertised_size is None else advertised_size)]}),
                "/api/projects/p/files/" + path: (200, content_type, body, {}),
            }) as (url, _):
                result = self.invoke(url, "download", "p", path, "--output", str(Path(temporary) / path))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_nonlocal_urls_and_redirects_are_rejected(self):
        for url in ["https://example.com", "http://192.168.1.1", "http://localhost.example.com", "file:///tmp/data"]:
            with self.subTest(url=url):
                self.assertNotEqual(self.invoke(url, "health").returncode, 0)
        with api_server({"/api/health": (302, "text/plain", b"redirect", {"Location": "/leak"}),
                         "/leak": json_response({"ok": True, "version": "0.25.0"})}) as (url, requests):
            self.assertNotEqual(self.invoke(url, "health").returncode, 0)
            self.assertEqual([path for path, _ in requests], ["/api/health"])


if __name__ == "__main__":
    unittest.main()
