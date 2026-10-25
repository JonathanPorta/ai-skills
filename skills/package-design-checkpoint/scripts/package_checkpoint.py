#!/usr/bin/env python3
"""Build and validate an immutable, reviewable design-checkpoint ZIP."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import fnmatch
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import unicodedata
from urllib.parse import quote
import zipfile


def load_index_module():
    """Load the bundled renderer independently of the caller's sys.path."""
    path = Path(__file__).with_name("package_index.py")
    spec = importlib.util.spec_from_file_location("checkpoint_package_index", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load package index renderer: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PACKAGE_INDEX = load_index_module()
METADATA_DIR = "_checkpoint"
CHANGELOG_PATH = f"{METADATA_DIR}/CHANGELOG.md"
IGNORE_CONTROL_FILE = ".opendesign-checkpointignore"

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
    "_handoff",
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
GENERIC_ROLES = {
    "alternate",
    "alternative",
    "direction",
    "mockup",
    "option",
    "primary",
    "screen",
    "state",
    "variant",
}
GENERIC_ROMAN_POSITION = re.compile(
    r"(?=[IVXLCDM]+$)M{0,3}(?:CM|CD|D?C{0,3})"
    r"(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})"
)
GENERIC_POSITION_WORDS = {
    "and",
    "billion",
    "billionth",
    "eight",
    "eighteen",
    "eighteenth",
    "eighth",
    "eightieth",
    "eighty",
    "eleven",
    "eleventh",
    "fifteen",
    "fifteenth",
    "fifth",
    "fifty",
    "fiftieth",
    "first",
    "five",
    "fortieth",
    "forty",
    "four",
    "fourteen",
    "fourteenth",
    "fourth",
    "hundred",
    "hundredth",
    "million",
    "millionth",
    "nine",
    "nineteen",
    "nineteenth",
    "ninetieth",
    "ninety",
    "ninth",
    "one",
    "second",
    "seven",
    "seventeen",
    "seventeenth",
    "seventh",
    "seventieth",
    "seventy",
    "six",
    "sixteen",
    "sixteenth",
    "sixth",
    "sixtieth",
    "sixty",
    "ten",
    "tenth",
    "third",
    "thirteen",
    "thirteenth",
    "thirty",
    "thirtieth",
    "thousand",
    "thousandth",
    "three",
    "trillion",
    "trillionth",
    "twelve",
    "twelfth",
    "twentieth",
    "twenty",
    "two",
    "zero",
    "zeroth",
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

    @property
    def source_path(self) -> str:
        return self.absolute_path.relative_to(self.source_root).as_posix()


@dataclass(frozen=True)
class CheckpointTarget:
    path: str
    label: str
    primary: bool = False



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
    """Open a project file without following a symlink in any component."""
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


def normalize_exact_path(value: str, *, allow_glob: bool = False) -> str:
    candidate = value.strip().replace("\\", "/")
    if candidate.startswith("/") or re.match(r"^[A-Za-z]:", candidate):
        raise ValueError(f"path must stay inside the project: '{value}'")
    if not candidate or (not allow_glob and any(character in candidate for character in "*?[")):
        raise ValueError(f"path must be exact and project-relative: '{value}'")
    path = PurePosixPath(candidate)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"path must stay inside the project: '{value}'")
    return path.as_posix()


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


def exact_exclusion_paths(patterns: list[str]) -> set[str]:
    exact: set[str] = set()
    for pattern in patterns:
        candidate = pattern.strip()
        if candidate.endswith("/") or any(character in candidate for character in "*?["):
            continue
        try:
            exact.add(normalize_exact_path(candidate.lstrip("/")))
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


def semver_text_pattern() -> str:
    return r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"


def checkpoint_version_pattern(slug: str) -> re.Pattern[str]:
    return re.compile(
        rf"^{re.escape(slug)}-checkpoint-(?:v)?({semver_text_pattern()})\.zip$"
    )


def handoff_version_pattern(slug: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(slug)}-(?:v)?{semver_text_pattern()}\.zip$")


def discover_versions(output_dir: Path, slug: str) -> list[tuple[Version, Path]]:
    pattern = checkpoint_version_pattern(slug)
    found: list[tuple[Version, Path]] = []
    for candidate in output_dir.iterdir():
        if not candidate.is_file():
            continue
        match = pattern.fullmatch(candidate.name)
        if match:
            found.append((Version.parse(match.group(1)), candidate))
    return sorted(found)


def verify_existing_identity(existing: list[tuple[Version, Path]], project_name: str) -> None:
    for _version, archive_path in existing:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                changelog = archive.read(CHANGELOG_PATH).decode("utf-8")
        except (KeyError, OSError, UnicodeDecodeError, zipfile.BadZipFile) as error:
            raise ValueError(
                f"existing checkpoint '{archive_path.name}' cannot prove its canonical project identity"
            ) from error
        match = re.search(r"^- Project: `([^`]*)`$", changelog, re.MULTILINE)
        if not match:
            raise ValueError(
                f"existing checkpoint '{archive_path.name}' has no canonical project identity"
            )
        if match.group(1) != project_name:
            raise ValueError(
                f"checkpoint slug collision: existing '{match.group(1)}' is not exact project name "
                f"'{project_name}'"
            )


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
        raise ValueError(f"ZIP entry normalizes to an absolute path: '{name}'")
    return normalized_name.casefold()


def validate_portable_namespace(names: list[str]) -> None:
    by_key: dict[str, str] = {}
    for name in names:
        key = portable_archive_key(name)
        previous = by_key.get(key)
        if previous is not None and previous != name:
            raise ValueError(f"portable ZIP namespace collision: '{previous}' and '{name}'")
        by_key[key] = name


def inventory_payload(
    source: Path,
    slug: str,
    index_name: str,
    ignore_patterns: list[str],
) -> tuple[list[PayloadFile], list[str]]:
    checkpoint_pattern = checkpoint_version_pattern(slug)
    any_checkpoint_pattern = re.compile(
        rf"^.+-checkpoint-(?:v)?{semver_text_pattern()}\.zip$"
    )
    handoff_pattern = handoff_version_pattern(slug)
    exact_exclusions = exact_exclusion_paths(ignore_patterns)
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
                    f"source contains reserved checkpoint metadata path '{relative}'"
                )
            elif path.is_symlink():
                unresolved_links.append(relative + "/")
            else:
                kept_dirs.append(name)
        dir_names[:] = kept_dirs

        for name in sorted(file_names):
            path = current / name
            relative = path.relative_to(source).as_posix()
            if relative == IGNORE_CONTROL_FILE:
                automatically_excluded.append(relative)
                continue
            if credential_like_path(relative):
                if relative in exact_exclusions:
                    automatically_excluded.append(relative)
                    continue
                raise ValueError(
                    f"credential-like file '{relative}' requires an exact --exclude path"
                )
            if (
                name.casefold() in EXCLUDED_FILE_NAMES_CASEFOLD
                or checkpoint_pattern.fullmatch(name)
                or any_checkpoint_pattern.fullmatch(name)
                or handoff_pattern.fullmatch(name)
                or excluded(relative, ignore_patterns)
            ):
                automatically_excluded.append(relative)
                continue
            if relative == CHANGELOG_PATH or relative.startswith(METADATA_DIR + "/"):
                raise ValueError(
                    f"source contains reserved checkpoint metadata path '{relative}'"
                )
            if path.is_symlink():
                unresolved_links.append(relative)
                continue
            digest, file_stat = hash_project_file(source, relative)
            payload.append(
                PayloadFile(
                    source_root=source,
                    absolute_path=path,
                    archive_path=f"project/{relative}",
                    size=file_stat.st_size,
                    sha256=digest,
                    mode=stat.S_IMODE(file_stat.st_mode),
                )
            )

    if unresolved_links:
        listed = ", ".join(sorted(unresolved_links)[:5])
        suffix = " ..." if len(unresolved_links) > 5 else ""
        raise ValueError(
            f"unresolved symlinks would make the checkpoint ambiguous: {listed}{suffix}; "
            "replace them with files or intentionally exclude them"
        )
    payload.sort(key=lambda item: item.archive_path)
    if not payload:
        raise ValueError("project contains no checkpoint files after exclusions")
    names = [item.archive_path for item in payload]
    names.extend(["index.html", "README.md", "artifact-manifest.json",
                  "_package/verification.json", CHANGELOG_PATH])
    validate_portable_namespace(names)
    return payload, sorted(set(automatically_excluded))


def normalize_target_path(value: str) -> str:
    if "\\" in value:
        raise ValueError(f"target must use '/' separators: '{value}'")
    return normalize_exact_path(value)


def functional_label(value: str, target: str) -> str:
    label = " ".join(value.split())
    if not label or len(label) > 160:
        raise ValueError("every checkpoint target needs a concise functional label")
    classification_label = unicodedata.normalize("NFKC", label)
    label_tokens = re.findall(r"[^\W_]+", classification_label)

    def positional_marker(token: str) -> bool:
        folded_token = token.casefold()
        if folded_token in GENERIC_POSITION_WORDS:
            return True
        numeric_ordinal_position = any(
            folded_token.endswith(suffix)
            and folded_token[: -len(suffix)].isdecimal()
            for suffix in ("st", "nd", "rd", "th")
        )
        short_alphanumeric_position = (
            len(token) >= 2
            and (
                (token[0].isalpha() and token[1:].isdecimal())
                or (token[:-1].isdecimal() and token[-1].isalpha())
            )
        )
        if (
            token.isdecimal()
            or (len(token) == 1 and token.isalpha())
            or short_alphanumeric_position
            or numeric_ordinal_position
        ):
            return True
        if not (token.isupper() or token.islower()):
            return False
        return bool(GENERIC_ROMAN_POSITION.fullmatch(token.upper()))

    def generic_role_marker(token: str) -> bool:
        folded_token = token.casefold()
        if folded_token in GENERIC_ROLES:
            return True
        return any(
            folded_token.startswith(role) and positional_marker(token[len(role) :])
            for role in GENERIC_ROLES
        )

    generic_position_only = bool(label_tokens) and any(
        generic_role_marker(token) for token in label_tokens
    ) and all(
        generic_role_marker(token) or positional_marker(token)
        for token in label_tokens
    )
    if generic_position_only:
        raise ValueError(f"'{label}' is not a functional label")
    filename_label = re.sub(r"[-_]+", " ", PurePosixPath(target).stem).casefold()
    if label.casefold() == filename_label:
        raise ValueError(f"'{label}' repeats a filename instead of a functional label")
    return label


def validate_identity_text(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} cannot be empty")
    if "`" in cleaned or any(
        character in "\r\n\0" or ord(character) < 32 or ord(character) == 127
        for character in cleaned
    ):
        raise ValueError(f"{field} contains unsupported control or Markdown-delimiter text")
    return cleaned


def markdown_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def markdown_target(value: str) -> str:
    return quote(value, safe="/-._~")


def build_targets(
    primary_values: list[str],
    alternative_values: list[list[str]],
    payload_names: set[str],
    index_name: str,
) -> list[CheckpointTarget]:
    raw_targets = [(primary_values, True)] + [
        (values, False) for values in alternative_values
    ]
    targets: list[CheckpointTarget] = []
    seen_paths: set[str] = set()
    seen_labels: set[str] = set()
    for values, primary in raw_targets:
        target = normalize_target_path(values[0])
        label = functional_label(values[1], target)
        target_key = portable_archive_key(target)
        if target_key in seen_paths:
            raise ValueError(f"duplicate target in checkpoint inventory: '{target}'")
        if label.casefold() in seen_labels:
            raise ValueError(f"duplicate functional label in checkpoint inventory: '{label}'")
        if target not in payload_names:
            raise ValueError(f"declared checkpoint target does not exist in payload: '{target}'")
        seen_paths.add(target_key)
        seen_labels.add(label.casefold())
        targets.append(CheckpointTarget(path=target, label=label, primary=primary))

    undeclared_html = sorted(
        path
        for path in payload_names
        if PurePosixPath(path).suffix.casefold() in {".html", ".htm"}
        and portable_archive_key(path) not in seen_paths
    )
    if undeclared_html:
        raise ValueError(
            "every browsable HTML mockup must be declared as the primary or an alternative; "
            f"declare or exactly exclude: {', '.join(undeclared_html)}"
        )
    return targets


def changelog_bytes(
    project_name: str,
    namespace: str | None,
    version: Version,
    previous: Version | None,
    bump_type: str,
    change: str,
    targets: list[CheckpointTarget],
    created_at: str | None = None,
) -> bytes:
    generated_at = created_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    primary = targets[0]
    alternatives = targets[1:]
    lines = [
        f"# {project_name} — CHECKPOINT {version}",
        "",
        f"- Project: `{project_name}`",
        f"- Namespace: `{namespace if namespace else 'none'}`",
        f"- Version: `{version}`",
        f"- Previous version: `{previous if previous else 'none'}`",
        f"- Version change: `{bump_type}`",
        f"- Created: `{generated_at}`",
        f"- Change: {change}",
        f"- Primary: [{markdown_label(primary.label)}](../project/{markdown_target(primary.path)})",
    ]
    if alternatives:
        lines.extend(["", "## Alternatives", ""])
        lines.extend(
            f"- [{markdown_label(target.label)}](../project/{markdown_target(target.path)})"
            for target in alternatives
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def zip_info(name: str, mode: int = 0o644) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = ((stat.S_IFREG | mode) & 0xFFFF) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_zip(
    destination: Path,
    payload: list[PayloadFile],
    generated: dict[str, bytes],
    index_name: str,
    targets: list[CheckpointTarget],
) -> None:
    expected_names = {item.archive_path for item in payload} | set(generated)
    with zipfile.ZipFile(destination, mode="r") as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise ValueError(f"ZIP CRC validation failed for '{corrupt}'")
        archive_name_list = archive.namelist()
        actual_names = set(archive_name_list)
        validate_portable_namespace(archive_name_list)
        if len(archive_name_list) != len(actual_names):
            raise ValueError("ZIP contains duplicate entry names")
        if actual_names != expected_names:
            missing = sorted(expected_names - actual_names)
            extra = sorted(actual_names - expected_names)
            raise ValueError(f"ZIP entry mismatch; missing={missing}, extra={extra}")
        for item in payload:
            with archive.open(item.archive_path) as handle:
                archived_hash = hash_stream(handle)
            if archived_hash != item.sha256:
                raise ValueError(f"archived bytes changed for '{item.archive_path}'")
        for name, expected_data in generated.items():
            if archive.read(name) != expected_data:
                raise ValueError(f"generated checkpoint metadata changed for '{name}'")
        PACKAGE_INDEX.validate_index(
            {name: archive.read(name) for name in generated}, actual_names
        )
        forbidden = {
            "_checkpoint/MANIFEST.json",
            "_checkpoint/CHECKSUMS.sha256",
        }
        if forbidden & actual_names or any(name.startswith("_handoff/") for name in actual_names):
            raise ValueError("checkpoint ZIP contains forbidden full-handoff metadata")


def build_zip(
    destination: Path,
    payload: list[PayloadFile],
    generated: dict[str, bytes],
    index_name: str,
    targets: list[CheckpointTarget],
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
            for archive_name in sorted(set(payload_by_name) | set(generated)):
                if archive_name in generated:
                    archive.writestr(zip_info(archive_name), generated[archive_name])
                    continue
                item = payload_by_name[archive_name]
                with open_project_file(item.source_root, item.source_path) as source_handle:
                    with archive.open(zip_info(item.archive_path, item.mode), "w") as zip_handle:
                        shutil.copyfileobj(source_handle, zip_handle, length=1024 * 1024)

        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        validate_zip(temporary, payload, generated, index_name, targets)
        try:
            os.link(temporary, destination)
        except FileExistsError:
            raise ValueError(f"destination already exists and will not be overwritten: {destination}")
        fsync_directory(destination.parent)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package an in-progress design project as an immutable SemVer checkpoint ZIP."
    )
    parser.add_argument("source", help="Project root to checkpoint")
    parser.add_argument(
        "--project-name",
        required=True,
        help="Actual human-readable Open Design project name; never inferred",
    )
    parser.add_argument(
        "--namespace",
        help="Optional Open Design namespace, recorded separately from project identity",
    )
    parser.add_argument(
        "--index",
        default="index.html",
        choices=("index.html", "index.md"),
        help="Canonical root index (index.html); index.md is no longer supported",
    )
    parser.add_argument(
        "--package-metadata",
        help="Optional JSON package-guide metadata; paths are source-relative",
    )
    parser.add_argument(
        "--primary",
        nargs=2,
        metavar=("TARGET", "LABEL"),
        help="Primary target path and functional label; may instead be supplied in package metadata",
    )
    parser.add_argument(
        "--alternative",
        action="append",
        default=[],
        nargs=2,
        metavar=("TARGET", "LABEL"),
        help="Alternative target path and functional label; repeat as needed",
    )
    parser.add_argument(
        "--change",
        required=True,
        help="Concise checkpoint changelog entry",
    )
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
        help="Increment from the highest checkpoint version; default: patch",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="Intentional exclusion path or glob; repeat as needed",
    )
    parser.add_argument(
        "--report-sha256",
        action="store_true",
        help="Print one SHA-256 digest for the final ZIP",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the checkpoint plan without creating an archive",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.index != "index.html":
            raise ValueError("all packages now use root index.html; remove --index index.md and declare the Markdown file as a review target")
        metadata = PACKAGE_INDEX.load_metadata(args.package_metadata)
        source = Path(args.source).expanduser().resolve(strict=True)
        if not source.is_dir():
            raise ValueError(f"source is not a directory: {source}")
        project_name = validate_identity_text(args.project_name, "project name")
        namespace = (
            validate_identity_text(args.namespace, "namespace")
            if args.namespace is not None
            else None
        )
        change = " ".join(args.change.split())
        if not change:
            raise ValueError("change cannot be empty")
        if len(change) > 500:
            raise ValueError("change must be concise (500 characters or fewer)")

        output_dir = (
            Path(args.output_dir).expanduser().resolve()
            if args.output_dir
            else source
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        slug = slugify(project_name)
        existing = discover_versions(output_dir, slug)
        verify_existing_identity(existing, project_name)
        previous, version, bump_type = select_version(existing, args.version, args.bump)
        archive_name = f"{slug}-checkpoint-{version}.zip"
        destination = output_dir / archive_name
        if destination.exists():
            raise ValueError(f"destination already exists and will not be overwritten: {destination}")

        ignore_patterns = load_ignore_patterns(source, args.exclude)
        payload, automatic_exclusions = inventory_payload(
            source,
            slug,
            args.index,
            ignore_patterns,
        )
        payload_names = {item.source_path for item in payload}
        created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        generated = PACKAGE_INDEX.build_index(
            project_name=project_name,
            slug=slug,
            artifact_type="checkpoint",
            version=str(version),
            change=change,
            payload_paths=sorted(payload_names),
            primary={"path": args.primary[0], "label": args.primary[1]} if args.primary else None,
            review_targets=[{"path": values[0], "label": values[1]} for values in args.alternative],
            metadata=metadata,
            namespace=namespace,
            created_at=created_at,
            docs=[{"path": CHANGELOG_PATH, "label": "Checkpoint changelog",
                   "description": "Current version, change summary, and declared review targets."}],
        )
        # The renderer is the single metadata merge point. Validate the final
        # labels and exhaustive HTML inventory, then reuse those exact labels
        # in the changelog and dry-run plan so they cannot drift from the guide.
        guide = json.loads(generated["artifact-manifest.json"])
        primary = guide["primary"]
        targets = build_targets(
            [primary["path"].removeprefix("project/"), primary["label"]],
            [[target["path"].removeprefix("project/"), target["label"]]
             for target in guide["review_targets"]],
            payload_names, args.index,
        )
        generated[CHANGELOG_PATH] = changelog_bytes(
            project_name, namespace, version, previous, bump_type, change, targets, created_at,
        )
        final_names = {item.archive_path for item in payload} | set(generated)
        validate_portable_namespace(sorted(final_names))
        PACKAGE_INDEX.validate_index(generated, final_names)

        all_exclusions = sorted(set(ignore_patterns + automatic_exclusions))
        plan = {
            "archive": str(destination),
            "project_name": project_name,
            "namespace": namespace,
            "project_slug": slug,
            "previous_version": str(previous) if previous else None,
            "version": str(version),
            "version_change": bump_type,
            "change": change,
            "index": args.index,
            "primary": {"path": targets[0].path, "label": targets[0].label},
            "alternatives": [
                {"path": target.path, "label": target.label} for target in targets[1:]
            ],
            "payload_file_count": len(payload),
            "payload_bytes": sum(item.size for item in payload),
            "exclusions": all_exclusions,
        }
        if args.dry_run:
            print(json.dumps(plan, indent=2, sort_keys=True))
            return 0

        build_zip(destination, payload, generated, args.index, targets)
        print(f"Created: {destination}")
        print(f"Version: {previous if previous else 'none'} -> {version} ({bump_type})")
        print(f"Primary: {targets[0].label} ({targets[0].path})")
        print(f"Alternatives: {len(targets) - 1}")
        print(f"Payload: {len(payload)} files, {sum(item.size for item in payload)} bytes")
        if args.report_sha256:
            print(f"SHA-256: {hash_file(destination)}")
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
