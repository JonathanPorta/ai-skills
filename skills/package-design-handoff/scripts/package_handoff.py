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
IGNORE_CONTROL_FILE = ".opendesign-handoffignore"

EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".od-skills",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "env",
    "venv",
    "__pycache__",
    "node_modules",
}
EXCLUDED_FILE_NAMES = {".DS_Store", "Thumbs.db", ".git", ".hg", ".svn"}
EXCLUDED_DIR_NAMES_CASEFOLD = {name.casefold() for name in EXCLUDED_DIR_NAMES}
EXCLUDED_FILE_NAMES_CASEFOLD = {name.casefold() for name in EXCLUDED_FILE_NAMES}
SENSITIVE_EXACT_NAMES = {
    ".env",
    ".envrc",
    ".git-credentials",
    ".netrc",
    ".npmrc",
    ".pnpmrc",
    ".pypirc",
    ".yarnrc",
    "_netrc",
    "application_default_credentials.json",
    "auth.json",
    "auth.yaml",
    "auth.yml",
    "client_secret.json",
    "credentials",
    "credentials.json",
    "credentials.yaml",
    "credentials.yml",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
    "token.json",
}
SENSITIVE_SUFFIXES = (".key", ".p12", ".pfx", ".pem")
COMMON_CREDENTIAL_STEMS = {
    "auth",
    "credential",
    "credentials",
    "password",
    "passwords",
    "secret",
    "secrets",
    "token",
}
COMMON_CREDENTIAL_COMPOUNDS = {
    "accesskey",
    "apikey",
    "privatekey",
    "serviceaccount",
    "signingkey",
}
COMMON_CREDENTIAL_SEQUENCES = {
    ("access", "key"),
    ("api", "key"),
    ("private", "key"),
    ("service", "account"),
    ("signing", "key"),
}
COMMON_CREDENTIAL_QUALIFIERS = {
    "bak",
    "backup",
    "copy",
    "dev",
    "development",
    "example",
    "local",
    "old",
    "orig",
    "original",
    "prod",
    "production",
    "sample",
    "stage",
    "staging",
    "test",
}
# Generalized name heuristics intentionally stop at text/config artifacts.
# Authored code, HTML mockups, and media remain normal package payload.
COMMON_CREDENTIAL_TEXT_CONFIG_SUFFIXES = {
    "cfg",
    "cnf",
    "conf",
    "config",
    "csv",
    "env",
    "ini",
    "json",
    "plist",
    "properties",
    "text",
    "toml",
    "tsv",
    "txt",
    "xml",
    "yaml",
    "yml",
}
COMMON_CREDENTIAL_DOC_SUFFIXES = {"log", "markdown", "md", "rst"}
SENSITIVE_PATH_SUFFIXES = {
    (".aws", "credentials"),
    (".cargo", "credentials"),
    (".cargo", "credentials.toml"),
    (".config", "gcloud", "application_default_credentials.json"),
    (".config", "gh", "hosts.yml"),
    (".docker", "config.json"),
    (".gem", "credentials"),
    (".kube", "config"),
}
WINDOWS_RESERVED_COMPONENTS = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


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
    source_root: Path
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


def open_project_file(source: Path, relative_path: str):
    """Open a project file without following a symlink in any path component."""
    parts = PurePosixPath(relative_path).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"invalid project-relative path '{relative_path}'")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    try:
        current = os.open(source, directory_flags)
        descriptors.append(current)
        for part in parts[:-1]:
            current = os.open(part, directory_flags | no_follow, dir_fd=current)
            descriptors.append(current)
        file_descriptor = os.open(parts[-1], os.O_RDONLY | no_follow, dir_fd=current)
        file_stat = os.fstat(file_descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            os.close(file_descriptor)
            raise ValueError(f"unsupported non-regular file '{relative_path}'")
        return os.fdopen(file_descriptor, "rb")
    except OSError as error:
        if error.errno in {getattr(os, "ELOOP", 40), 40}:
            raise ValueError(f"project path contains a symlink: '{relative_path}'") from error
        raise
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def hash_project_file(source: Path, relative_path: str) -> tuple[str, os.stat_result]:
    with open_project_file(source, relative_path) as handle:
        file_stat = os.fstat(handle.fileno())
        return hash_stream(handle), file_stat


def load_ignore_patterns(source: Path, cli_patterns: list[str]) -> list[str]:
    patterns = list(cli_patterns)
    ignore_file = source / IGNORE_CONTROL_FILE
    try:
        ignore_stat = ignore_file.lstat()
    except FileNotFoundError:
        return patterns
    if stat.S_ISLNK(ignore_stat.st_mode) or not stat.S_ISREG(ignore_stat.st_mode):
        raise ValueError(
            f"ignore control file '{IGNORE_CONTROL_FILE}' must be an in-project regular file, not a symlink"
        )
    try:
        with open_project_file(source, IGNORE_CONTROL_FILE) as handle:
            ignore_text = handle.read().decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"ignore control file '{IGNORE_CONTROL_FILE}' must be UTF-8") from error
    for raw_line in ignore_text.splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def normalize_exact_review_path(value: str) -> str:
    candidate = value.strip().replace("\\", "/")
    if candidate.startswith("/") or re.match(r"^[A-Za-z]:", candidate):
        raise ValueError(f"reviewed sensitive path must stay inside the project: '{value}'")
    if not candidate or any(character in candidate for character in "*?["):
        raise ValueError(f"reviewed sensitive path must be exact, not a glob: '{value}'")
    path = PurePosixPath(candidate)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"reviewed sensitive path must stay inside the project: '{value}'")
    return path.as_posix()


def exact_exclusion_paths(patterns: list[str]) -> set[str]:
    exact: set[str] = set()
    for pattern in patterns:
        candidate = pattern.strip()
        if candidate.endswith("/") or any(character in candidate for character in "*?["):
            continue
        try:
            exact.add(normalize_exact_review_path(candidate.lstrip("/")))
        except ValueError:
            continue
    return exact


def credential_like_path(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    parts = tuple(unicodedata.normalize("NFKC", part).casefold() for part in path.parts)
    raw_name = unicodedata.normalize("NFKC", path.name)
    name = parts[-1]
    normalized_name = name.replace("_", "-")
    structured_suffixes = (".json", ".yaml", ".yml", ".toml")
    structured_stem = normalized_name.rsplit(".", 1)[0]
    ordered_qualifiers = sorted(
        COMMON_CREDENTIAL_QUALIFIERS, key=len, reverse=True
    )

    def normalize_credential_token(token: str) -> str:
        normalized = token.casefold()
        while normalized:
            previous = normalized
            normalized = re.sub(r"(?:v)?\d+$", "", normalized)
            for qualifier in ordered_qualifiers:
                if normalized.endswith(qualifier) and len(normalized) > len(qualifier):
                    normalized = normalized[: -len(qualifier)]
                    break
            if normalized == previous:
                break
        return normalized

    def credential_name_tokens(value: str) -> list[str]:
        camel_source = re.sub(r"oauth", "oauth", value, flags=re.IGNORECASE)
        camel_separated = re.sub(
            r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])",
            " ",
            camel_source,
        )
        return [
            normalized
            for token in re.findall(r"[^\W_]+", camel_separated)
            if (normalized := normalize_credential_token(token))
        ]

    def credential_token(token: str) -> bool:
        if token.endswith("oauth"):
            return False
        if token in COMMON_CREDENTIAL_STEMS:
            return True
        return any(
            token.endswith(marker) and len(token) - len(marker) >= 2
            for marker in COMMON_CREDENTIAL_STEMS
        )

    def credential_compound(token: str) -> bool:
        return any(
            token == compound
            or (token.endswith(compound) and len(token) - len(compound) >= 2)
            for compound in COMMON_CREDENTIAL_COMPOUNDS
        )

    def credential_tokens_match(tokens: list[str]) -> bool:
        return (
            any(credential_token(token) for token in tokens)
            or any(credential_compound(token) for token in tokens)
            or any(
                tuple(tokens[index : index + len(sequence)]) == sequence
                for sequence in COMMON_CREDENTIAL_SEQUENCES
                for index in range(len(tokens) - len(sequence) + 1)
            )
        )

    def terminal_credential_tokens_match(tokens: list[str]) -> bool:
        effective = list(tokens)
        while effective and effective[-1] in COMMON_CREDENTIAL_QUALIFIERS:
            effective.pop()
        if not effective:
            return False
        if credential_token(effective[-1]) or credential_compound(effective[-1]):
            return True
        return any(
            len(effective) >= len(sequence)
            and tuple(effective[-len(sequence) :]) == sequence
            for sequence in COMMON_CREDENTIAL_SEQUENCES
        )

    def qualifier_component(value: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]+", "", value.casefold())
        if re.fullmatch(r"v?\d+", normalized):
            return True
        remainder = normalized
        while remainder:
            remainder = re.sub(r"(?:v)?\d+$", "", remainder)
            for qualifier in ordered_qualifiers:
                if remainder.endswith(qualifier):
                    remainder = remainder[: -len(qualifier)]
                    break
            else:
                return False
        return bool(normalized)

    def generalized_name_context(value: str) -> tuple[str, list[str]]:
        components = [
            component
            for component in value.rstrip("~").lstrip(".").split(".")
            if component
        ]
        while len(components) > 1 and qualifier_component(components[-1]):
            components.pop()
        all_tokens = credential_name_tokens(".".join(components))
        if len(components) <= 1:
            return "bare", all_tokens
        suffix = re.sub(r"[^a-z0-9]+", "", components[-1].casefold())
        stem_tokens = credential_name_tokens(".".join(components[:-1]))
        if suffix in COMMON_CREDENTIAL_TEXT_CONFIG_SUFFIXES:
            return "config", stem_tokens
        if suffix in COMMON_CREDENTIAL_DOC_SUFFIXES:
            return "doc", stem_tokens
        if terminal_credential_tokens_match(all_tokens):
            return "bare", all_tokens
        return "none", []

    name_kind, scoped_tokens = generalized_name_context(raw_name)
    common_credential_name = (
        credential_tokens_match(scoped_tokens)
        if name_kind == "config"
        else name_kind in {"bare", "doc"}
        and terminal_credential_tokens_match(scoped_tokens)
    )
    return (
        name in SENSITIVE_EXACT_NAMES
        or name.startswith(".env.")
        or name.startswith((".npmrc.", ".pypirc."))
        or name.endswith(SENSITIVE_SUFFIXES)
        or any(
            len(parts) >= len(suffix) and parts[-len(suffix) :] == suffix
            for suffix in SENSITIVE_PATH_SUFFIXES
        )
        or common_credential_name
        or (
            name.endswith(structured_suffixes)
            and (
                structured_stem in {"auth", "credential", "credentials", "secret", "secrets", "token"}
                or any(
                    marker in structured_stem
                    for marker in (
                        "access-token",
                        "auth-token",
                        "client-secret",
                        "credentials",
                        "refresh-token",
                        "service-account",
                    )
                )
            )
        )
    )


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


def checkpoint_archive_pattern(slug: str) -> re.Pattern[str]:
    return re.compile(
        rf"^{re.escape(slug)}-checkpoint-(?:v)?"
        r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.zip$"
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
    source: Path,
    slug: str,
    ignore_patterns: list[str],
    reviewed_sensitive_inclusions: list[str] | None = None,
) -> tuple[list[PayloadFile], list[str]]:
    archive_pattern = version_pattern(slug)
    checkpoint_pattern = checkpoint_archive_pattern(slug)
    any_checkpoint_pattern = re.compile(
        r"^.+-checkpoint-(?:v)?(?:0|[1-9]\d*)\."
        r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.zip$"
    )
    exact_exclusions = exact_exclusion_paths(ignore_patterns)
    reviewed_inclusions = {
        normalize_exact_review_path(path) for path in (reviewed_sensitive_inclusions or [])
    }
    found_reviewed_inclusions: set[str] = set()
    payload: list[PayloadFile] = []
    automatically_excluded: list[str] = []
    unresolved_links: list[str] = []

    for current_root, dir_names, file_names in os.walk(source, topdown=True, followlinks=False):
        current = Path(current_root)
        kept_dirs: list[str] = []
        for name in sorted(dir_names):
            path = current / name
            relative = path.relative_to(source).as_posix()
            if name.casefold() in EXCLUDED_DIR_NAMES_CASEFOLD or excluded(
                relative, ignore_patterns
            ):
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
            reviewed_sensitive = False
            if relative == IGNORE_CONTROL_FILE:
                automatically_excluded.append(relative)
                continue
            if credential_like_path(relative):
                if relative in reviewed_inclusions:
                    found_reviewed_inclusions.add(relative)
                    reviewed_sensitive = True
                elif relative in exact_exclusions:
                    automatically_excluded.append(relative)
                    continue
                else:
                    raise ValueError(
                        f"credential-like file '{relative}' requires an exact --exclude path "
                        "or an exact --include-sensitive review"
                    )
            if (
                name.casefold() in EXCLUDED_FILE_NAMES_CASEFOLD
                or archive_pattern.fullmatch(name)
                or checkpoint_pattern.fullmatch(name)
                or any_checkpoint_pattern.fullmatch(name)
                or (excluded(relative, ignore_patterns) and not reviewed_sensitive)
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
            digest, file_stat = hash_project_file(source, relative)
            payload.append(
                PayloadFile(
                    source_root=source,
                    absolute_path=path,
                    archive_path=relative,
                    size=file_stat.st_size,
                    sha256=digest,
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
    missing_reviews = reviewed_inclusions - found_reviewed_inclusions
    if missing_reviews:
        raise ValueError(
            "reviewed sensitive inclusion does not name a credential-like regular file: "
            + ", ".join(sorted(missing_reviews))
        )
    payload.sort(key=lambda item: item.archive_path)
    if not payload:
        raise ValueError("project contains no payload files after exclusions")
    validate_portable_namespace([item.archive_path for item in payload] + sorted(RESERVED_NAMES))
    return payload, sorted(set(automatically_excluded))


def portable_archive_key(name: str) -> str:
    if not name or name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name):
        raise ValueError(f"ZIP entry is absolute or drive-qualified: '{name}'")
    if "\\" in name:
        raise ValueError(f"ZIP entry uses a non-portable backslash separator: '{name}'")
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise ValueError(f"ZIP entry contains a control character: '{name}'")
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"ZIP entry contains an empty or traversal component: '{name}'")
    normalized_parts: list[str] = []
    for component in parts:
        normalized_component = unicodedata.normalize("NFKC", component)
        if "/" in normalized_component or "\\" in normalized_component:
            raise ValueError(
                f"ZIP entry normalization introduces a path separator: '{name}'"
            )
        if normalized_component in {"", ".", ".."}:
            raise ValueError(f"ZIP entry normalizes to a traversal component: '{name}'")
        if any(
            ord(character) < 32 or ord(character) == 127
            for character in normalized_component
        ):
            raise ValueError(f"ZIP entry normalizes to a control character: '{name}'")
        if normalized_component.endswith((" ", ".")):
            raise ValueError(f"ZIP entry has a Windows-ambiguous component: '{name}'")
        basename = normalized_component.split(".", 1)[0].casefold()
        if basename in WINDOWS_RESERVED_COMPONENTS:
            raise ValueError(f"ZIP entry uses a Windows-reserved component: '{name}'")
        if any(character in '<>:"|?*' for character in normalized_component):
            raise ValueError(f"ZIP entry contains a Windows-invalid character: '{name}'")
        normalized_parts.append(normalized_component)
    normalized_name = "/".join(normalized_parts)
    if normalized_name.startswith("/") or re.match(r"^[A-Za-z]:", normalized_name):
        raise ValueError(f"ZIP entry normalizes to an absolute or drive-qualified path: '{name}'")
    return normalized_name.casefold()


def validate_portable_namespace(names: list[str]) -> None:
    by_key: dict[str, str] = {}
    for name in names:
        key = portable_archive_key(name)
        previous = by_key.get(key)
        if previous is not None and previous != name:
            raise ValueError(
                f"portable ZIP namespace collision: '{previous}' and '{name}'"
            )
        by_key[key] = name


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
    reviewed_sensitive_inclusions: list[str],
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
        "reviewed_sensitive_inclusions": reviewed_sensitive_inclusions,
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
                with open_project_file(item.source_root, item.archive_path) as source_handle:
                    with archive.open(zip_info(item.archive_path, item.mode), "w") as zip_handle:
                        shutil.copyfileobj(source_handle, zip_handle, length=1024 * 1024)

        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        validate_zip(temporary, payload)
        try:
            os.link(temporary, destination)
        except FileExistsError:
            raise ValueError(f"destination already exists and will not be overwritten: {destination}")
        fsync_directory(destination.parent)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_zip(destination: Path, payload: list[PayloadFile]) -> None:
    expected_names = {item.archive_path for item in payload} | RESERVED_NAMES
    with zipfile.ZipFile(destination, mode="r") as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise ValueError(f"ZIP CRC validation failed for '{corrupt}'")
        actual_names = set(archive.namelist())
        validate_portable_namespace(archive.namelist())
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
        "--include-sensitive",
        action="append",
        default=[],
        metavar="EXACT_PATH",
        help=(
            "Include one credential-like file after exact-path review; repeat as needed. "
            "Globs and paths outside the project are rejected."
        ),
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
        reviewed_sensitive_inclusions = sorted(
            normalize_exact_review_path(path) for path in args.include_sensitive
        )
        payload, automatic_exclusions = inventory_payload(
            source,
            slug,
            ignore_patterns,
            reviewed_sensitive_inclusions=reviewed_sensitive_inclusions,
        )
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
            "reviewed_sensitive_inclusions": reviewed_sensitive_inclusions,
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
            reviewed_sensitive_inclusions=reviewed_sensitive_inclusions,
        )
        build_zip(destination, payload, readme_data, manifest_data, checksums_data)
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
