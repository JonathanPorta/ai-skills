#!/usr/bin/env python3
"""Build and validate an immutable, SemVer design-handoff ZIP."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import unicodedata
import zipfile


METADATA_DIR = "_handoff"
METADATA_README = f"{METADATA_DIR}/README.md"
METADATA_MANIFEST = f"{METADATA_DIR}/MANIFEST.json"
METADATA_CHECKSUMS = f"{METADATA_DIR}/CHECKSUMS.sha256"
RESERVED_NAMES = {METADATA_README, METADATA_MANIFEST, METADATA_CHECKSUMS}
HANDOFF_ARCHIVE_PATTERN = re.compile(
    r"^.+-(?:v)?(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.zip$"
)

EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
}
EXCLUDED_FILE_NAMES = {".DS_Store", "Thumbs.db"}


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> "Version":
        match = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value)
        if not match:
            raise ValueError(f"invalid stable SemVer '{value}'; expected X.Y.Z")
        return cls(*(int(part) for part in match.groups()))

    def bump(self, kind: str) -> "Version":
        if kind == "patch":
            return Version(self.major, self.minor, self.patch + 1)
        if kind == "minor":
            return Version(self.major, self.minor + 1, 0)
        if kind == "major":
            return Version(self.major + 1, 0, 0)
        raise ValueError(f"unsupported bump '{kind}'")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class PayloadFile:
    absolute_path: Path
    archive_path: str
    size: int
    sha256: str
    mode: int


def slugify(project_name: str) -> str:
    normalized = unicodedata.normalize("NFKD", project_name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise ValueError("project name does not contain characters usable in an ASCII slug")
    return slug


def hash_stream(stream) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def hash_file(path: Path) -> str:
    with path.open("rb") as handle:
        return hash_stream(handle)


def load_ignore_patterns(source: Path, cli_patterns: list[str]) -> list[str]:
    patterns = list(cli_patterns)
    ignore_file = source / ".opendesign-handoffignore"
    if ignore_file.is_file():
        for raw_line in ignore_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
    return patterns


def matches_pattern(relative_path: str, pattern: str) -> bool:
    relative_path = relative_path.strip("/")
    pattern = pattern.strip().replace("\\", "/")
    if not pattern:
        return False
    anchored = pattern.startswith("/")
    pattern = pattern.lstrip("/")
    if pattern.endswith("/"):
        prefix = pattern.rstrip("/")
        return relative_path == prefix or relative_path.startswith(prefix + "/")
    if anchored:
        return fnmatch.fnmatchcase(relative_path, pattern)
    if fnmatch.fnmatchcase(relative_path, pattern) or PurePosixPath(relative_path).match(pattern):
        return True
    if "/" not in pattern:
        return any(fnmatch.fnmatchcase(part, pattern) for part in relative_path.split("/"))
    return False


def excluded(relative_path: str, patterns: list[str]) -> bool:
    return any(matches_pattern(relative_path, pattern) for pattern in patterns)


def version_pattern(slug: str) -> re.Pattern[str]:
    return re.compile(
        rf"^{re.escape(slug)}-(?:v)?((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))\.zip$"
    )


def discover_versions(output_dir: Path, slug: str) -> list[tuple[Version, Path]]:
    pattern = version_pattern(slug)
    found: list[tuple[Version, Path]] = []
    for candidate in output_dir.iterdir():
        if not candidate.is_file():
            continue
        match = pattern.fullmatch(candidate.name)
        if match:
            found.append((Version.parse(match.group(1)), candidate))
    return sorted(found)


def select_version(
    existing: list[tuple[Version, Path]], requested_version: str | None, bump: str
) -> tuple[Version | None, Version, str]:
    previous = existing[-1][0] if existing else None
    if requested_version is not None:
        selected = Version.parse(requested_version)
        if previous is not None and selected <= previous:
            raise ValueError(
                f"requested version {selected} must be greater than existing version {previous}"
            )
        return previous, selected, "explicit"
    if previous is None:
        return None, Version(0, 1, 0), "initial"
    return previous, previous.bump(bump), bump


def inventory_payload(
    source: Path, slug: str, ignore_patterns: list[str]
) -> tuple[list[PayloadFile], list[str]]:
    archive_pattern = version_pattern(slug)
    payload: list[PayloadFile] = []
    automatically_excluded: list[str] = []
    unresolved_links: list[str] = []

    for current_root, dir_names, file_names in os.walk(source, topdown=True, followlinks=False):
        current = Path(current_root)
        kept_dirs: list[str] = []
        for name in sorted(dir_names):
            path = current / name
            relative = path.relative_to(source).as_posix()
            if name in EXCLUDED_DIR_NAMES or excluded(relative, ignore_patterns):
                automatically_excluded.append(relative + "/")
            elif relative == METADATA_DIR or relative.startswith(METADATA_DIR + "/"):
                raise ValueError(
                    f"source contains reserved metadata path '{relative}'; rename or remove it"
                )
            elif path.is_symlink():
                unresolved_links.append(relative + "/")
            else:
                kept_dirs.append(name)
        dir_names[:] = kept_dirs

        for name in sorted(file_names):
            path = current / name
            relative = path.relative_to(source).as_posix()
            if (
                name in EXCLUDED_FILE_NAMES
                or archive_pattern.fullmatch(name)
                or (current == source and HANDOFF_ARCHIVE_PATTERN.fullmatch(name))
                or excluded(relative, ignore_patterns)
            ):
                automatically_excluded.append(relative)
                continue
            if relative in RESERVED_NAMES or relative.startswith(METADATA_DIR + "/"):
                raise ValueError(
                    f"source contains reserved metadata path '{relative}'; rename or remove it"
                )
            if path.is_symlink():
                unresolved_links.append(relative)
                continue
            file_stat = path.stat()
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValueError(f"unsupported non-regular file '{relative}'")
            payload.append(
                PayloadFile(
                    absolute_path=path,
                    archive_path=relative,
                    size=file_stat.st_size,
                    sha256=hash_file(path),
                    mode=stat.S_IMODE(file_stat.st_mode),
                )
            )

    if unresolved_links:
        listed = ", ".join(sorted(unresolved_links)[:5])
        suffix = " ..." if len(unresolved_links) > 5 else ""
        raise ValueError(
            f"unresolved symlinks would make the handoff ambiguous: {listed}{suffix}; "
            "replace them with files or intentionally exclude them"
        )
    payload.sort(key=lambda item: item.archive_path)
    if not payload:
        raise ValueError("project contains no payload files after exclusions")
    return payload, sorted(set(automatically_excluded))


def zip_info(name: str, mode: int = 0o644) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = ((stat.S_IFREG | mode) & 0xFFFF) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def metadata_bytes(
    project_name: str,
    slug: str,
    version: Version,
    previous: Version | None,
    bump_type: str,
    bump_reason: str,
    archive_name: str,
    payload: list[PayloadFile],
    exclusions: list[str],
) -> tuple[bytes, bytes, bytes]:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    manifest = {
        "schema_version": 1,
        "project_name": project_name,
        "project_slug": slug,
        "version": str(version),
        "archive_name": archive_name,
        "generated_at": generated_at,
        "source_root": ".",
        "version_change": {
            "previous_version": str(previous) if previous else None,
            "type": bump_type,
            "reason": bump_reason,
        },
        "payload_file_count": len(payload),
        "payload_bytes": sum(item.size for item in payload),
        "exclusions": exclusions,
        "files": [
            {"path": item.archive_path, "size": item.size, "sha256": item.sha256}
            for item in payload
        ],
    }
    manifest_data = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    readme_data = (
        f"# {project_name} design handoff\n\n"
        f"- Version: `{version}`\n"
        f"- Previous version: `{previous if previous else 'none'}`\n"
        f"- Version change: `{bump_type}` — {bump_reason}\n"
        f"- Payload files: `{len(payload)}`\n"
        f"- Payload root: archive root (`.`)\n\n"
        "`MANIFEST.json` inventories every payload file. "
        "`CHECKSUMS.sha256` verifies the payload and handoff metadata.\n"
    ).encode("utf-8")
    checksum_rows = [f"{item.sha256}  {item.archive_path}" for item in payload]
    checksum_rows.extend(
        [
            f"{hashlib.sha256(readme_data).hexdigest()}  {METADATA_README}",
            f"{hashlib.sha256(manifest_data).hexdigest()}  {METADATA_MANIFEST}",
        ]
    )
    checksums_data = ("\n".join(checksum_rows) + "\n").encode("utf-8")
    return readme_data, manifest_data, checksums_data


def build_zip(
    destination: Path,
    payload: list[PayloadFile],
    readme_data: bytes,
    manifest_data: bytes,
    checksums_data: bytes,
) -> Path:
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(file_descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            payload_by_name = {item.archive_path: item for item in payload}
            metadata_by_name = {
                METADATA_README: readme_data,
                METADATA_MANIFEST: manifest_data,
                METADATA_CHECKSUMS: checksums_data,
            }
            for archive_name in sorted(set(payload_by_name) | set(metadata_by_name)):
                if archive_name in metadata_by_name:
                    archive.writestr(zip_info(archive_name), metadata_by_name[archive_name])
                    continue
                item = payload_by_name[archive_name]
                with item.absolute_path.open("rb") as source_handle:
                    with archive.open(zip_info(item.archive_path, item.mode), "w") as zip_handle:
                        shutil.copyfileobj(source_handle, zip_handle, length=1024 * 1024)

        try:
            os.link(temporary, destination)
        except FileExistsError:
            raise ValueError(f"destination already exists and will not be overwritten: {destination}")
        except OSError:
            try:
                with temporary.open("rb") as source_handle, destination.open("xb") as target_handle:
                    shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
            except FileExistsError:
                raise ValueError(
                    f"destination already exists and will not be overwritten: {destination}"
                )
            except Exception:
                destination.unlink(missing_ok=True)
                raise
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def validate_zip(destination: Path, payload: list[PayloadFile]) -> None:
    expected_names = {item.archive_path for item in payload} | RESERVED_NAMES
    with zipfile.ZipFile(destination, mode="r") as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise ValueError(f"ZIP CRC validation failed for '{corrupt}'")
        actual_names = set(archive.namelist())
        if len(archive.namelist()) != len(actual_names):
            raise ValueError("ZIP contains duplicate entry names")
        if actual_names != expected_names:
            missing = sorted(expected_names - actual_names)
            extra = sorted(actual_names - expected_names)
            raise ValueError(f"ZIP entry mismatch; missing={missing}, extra={extra}")

        manifest = json.loads(archive.read(METADATA_MANIFEST))
        manifest_files = {entry["path"]: entry for entry in manifest["files"]}
        if set(manifest_files) != {item.archive_path for item in payload}:
            raise ValueError("manifest payload inventory does not match ZIP payload")
        for item in payload:
            with archive.open(item.archive_path) as handle:
                archived_hash = hash_stream(handle)
            if archived_hash != item.sha256:
                raise ValueError(f"archived bytes changed for '{item.archive_path}'")
            entry = manifest_files[item.archive_path]
            if entry["sha256"] != item.sha256 or entry["size"] != item.size:
                raise ValueError(f"manifest metadata mismatch for '{item.archive_path}'")

        checksum_entries: dict[str, str] = {}
        for line in archive.read(METADATA_CHECKSUMS).decode("utf-8").splitlines():
            digest, name = line.split("  ", 1)
            checksum_entries[name] = digest
        expected_checksum_names = {item.archive_path for item in payload} | {
            METADATA_README,
            METADATA_MANIFEST,
        }
        if set(checksum_entries) != expected_checksum_names:
            raise ValueError("checksum inventory does not match payload and metadata")
        for name, expected_hash in checksum_entries.items():
            with archive.open(name) as handle:
                actual_hash = hash_stream(handle)
            if actual_hash != expected_hash:
                raise ValueError(f"checksum mismatch for '{name}'")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package a complete design project as an immutable SemVer handoff ZIP."
    )
    parser.add_argument("source", help="Project root to package")
    parser.add_argument("--project-name", required=True, help="Human-readable project name")
    parser.add_argument(
        "--output-dir",
        help="Archive directory; defaults to the project root",
    )
    versioning = parser.add_mutually_exclusive_group()
    versioning.add_argument("--version", help="Explicit stable SemVer X.Y.Z")
    versioning.add_argument(
        "--bump",
        choices=("patch", "minor", "major"),
        default="patch",
        help="Increment from the highest existing archive; default: patch",
    )
    parser.add_argument(
        "--bump-reason",
        required=True,
        help="Brief changelog explaining the selected version",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="Intentional exclusion glob; repeat as needed",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the packaging plan without creating an archive",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        source = Path(args.source).expanduser().resolve(strict=True)
        if not source.is_dir():
            raise ValueError(f"source is not a directory: {source}")
        project_name = args.project_name.strip()
        if not project_name:
            raise ValueError("project name cannot be empty")
        bump_reason = args.bump_reason.strip()
        if not bump_reason:
            raise ValueError("bump reason cannot be empty")

        output_dir = (
            Path(args.output_dir).expanduser().resolve()
            if args.output_dir
            else source
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        slug = slugify(project_name)
        existing = discover_versions(output_dir, slug)
        previous, version, bump_type = select_version(existing, args.version, args.bump)
        archive_name = f"{slug}-{version}.zip"
        destination = output_dir / archive_name
        if destination.exists():
            raise ValueError(f"destination already exists and will not be overwritten: {destination}")

        ignore_patterns = load_ignore_patterns(source, args.exclude)
        payload, automatic_exclusions = inventory_payload(source, slug, ignore_patterns)
        all_exclusions = sorted(set(ignore_patterns + automatic_exclusions))
        plan = {
            "archive": str(destination),
            "project_name": project_name,
            "project_slug": slug,
            "previous_version": str(previous) if previous else None,
            "version": str(version),
            "version_change": bump_type,
            "bump_reason": bump_reason,
            "payload_file_count": len(payload),
            "payload_bytes": sum(item.size for item in payload),
            "exclusions": all_exclusions,
        }
        if args.dry_run:
            print(json.dumps(plan, indent=2, sort_keys=True))
            return 0

        readme_data, manifest_data, checksums_data = metadata_bytes(
            project_name=project_name,
            slug=slug,
            version=version,
            previous=previous,
            bump_type=bump_type,
            bump_reason=bump_reason,
            archive_name=archive_name,
            payload=payload,
            exclusions=all_exclusions,
        )
        build_zip(destination, payload, readme_data, manifest_data, checksums_data)
        try:
            validate_zip(destination, payload)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        archive_hash = hash_file(destination)

        print(f"Created: {destination}")
        print(f"Version: {previous if previous else 'none'} -> {version} ({bump_type})")
        print(f"Payload: {len(payload)} files, {sum(item.size for item in payload)} bytes")
        print(f"SHA-256: {archive_hash}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
