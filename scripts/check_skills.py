#!/usr/bin/env python3
"""Validate this repository's Agent Skills without third-party dependencies."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
YAML_KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
SUSPICIOUS_CODEPOINTS = (
    set(range(0x202A, 0x202F))
    | set(range(0x2066, 0x206A))
    | {0x200B, 0x200C, 0x200D, 0xFEFF}
    | set(range(0xE0000, 0xE0080))
)
TEXT_SUFFIXES = {
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
# Prose can legitimately need language-shaping controls. High-risk code points
# are still rejected everywhere; executable, script, code, and machine-readable
# resources reject the complete Unicode Cf category.
FORMAT_CONTROL_ALLOWED_PROSE_SUFFIXES = {".md", ".txt"}
BINARY_ASSET_SUFFIXES = {
    ".avif",
    ".fig",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".ttf",
    ".wav",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
}
SKILL_FIELDS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}
OPENAI_FIELDS = {"interface", "policy", "dependencies"}
OPENAI_INTERFACE_FIELDS = {
    "display_name",
    "short_description",
    "icon_small",
    "icon_large",
    "brand_color",
    "default_prompt",
}
OPENAI_POLICY_FIELDS = {"allow_implicit_invocation"}
OPENAI_DEPENDENCY_FIELDS = {"tools"}
OPENAI_TOOL_FIELDS = {"type", "value", "description", "transport", "url"}


@dataclass(frozen=True)
class YamlToken:
    indent: int
    content: str
    line: int
    block_value: str | None = None


def label(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def read_utf8(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{label(path)} is not valid UTF-8") from error
    if text.startswith("\ufeff"):
        raise ValueError(f"{label(path)} starts with a UTF-8 BOM")
    return text


def frontmatter(text: str, relative_path: Path) -> str:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"{relative_path} must start with YAML frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise ValueError(f"{relative_path} has unterminated YAML frontmatter") from error
    if not any(line.strip() for line in lines[end + 1 :]):
        raise ValueError(f"{relative_path} must contain skill instructions")
    return "\n".join(lines[1:end])


def strip_yaml_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(value):
        if quote == '"' and escaped:
            escaped = False
            continue
        if quote == '"' and character == "\\":
            escaped = True
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            continue
        if character == "#" and quote is None and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    if quote is not None:
        raise ValueError("unterminated quoted YAML scalar")
    return value.rstrip()


def split_yaml_mapping(value: str, path: Path, line: int) -> tuple[str, str]:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(value):
        if quote == '"' and escaped:
            escaped = False
            continue
        if quote == '"' and character == "\\":
            escaped = True
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            continue
        if character == ":" and quote is None:
            key = value[:index].strip()
            remainder = value[index + 1 :].strip()
            if not YAML_KEY_PATTERN.fullmatch(key):
                raise ValueError(f"{path}:{line} has invalid YAML mapping key '{key}'")
            return key, remainder
    raise ValueError(f"{path}:{line} expected a YAML 'key: value' mapping")


def fold_block(lines: list[str], style: str) -> str:
    if style == "|":
        return "\n".join(lines).rstrip("\n") + "\n"
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if line:
            current.append(line)
        else:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            paragraphs.append("")
    if current:
        paragraphs.append(" ".join(current))
    return "\n".join(paragraphs).rstrip("\n") + "\n"


def tokenize_yaml(text: str, path: Path) -> list[YamlToken]:
    physical = text.splitlines()
    tokens: list[YamlToken] = []
    index = 0
    while index < len(physical):
        raw = physical[index]
        line_number = index + 1
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ValueError(f"{path}:{line_number} uses a tab for YAML indentation")
        if not raw.strip() or raw.lstrip().startswith("#"):
            index += 1
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        content = strip_yaml_comment(raw[indent:])
        if content in {"---", "..."} or content.startswith("%"):
            raise ValueError(f"{path}:{line_number} contains an unsupported YAML document marker")
        block_match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*):\s*([|>])[-+]?", content)
        if block_match:
            block_lines: list[tuple[int, str]] = []
            index += 1
            while index < len(physical):
                following = physical[index]
                following_indent = len(following) - len(following.lstrip(" "))
                if following.strip() and following_indent <= indent:
                    break
                block_lines.append((following_indent, following))
                index += 1
            non_empty_indents = [amount for amount, line in block_lines if line.strip()]
            if not non_empty_indents:
                block_value = ""
            else:
                content_indent = min(non_empty_indents)
                if content_indent <= indent:
                    raise ValueError(f"{path}:{line_number} has an invalid block scalar indent")
                normalized = [
                    line[content_indent:] if line.strip() else "" for _amount, line in block_lines
                ]
                block_value = fold_block(normalized, block_match.group(2))
            tokens.append(
                YamlToken(
                    indent=indent,
                    content=f"{block_match.group(1)}:",
                    line=line_number,
                    block_value=block_value,
                )
            )
            continue
        if not content:
            raise ValueError(f"{path}:{line_number} has an empty YAML token")
        tokens.append(YamlToken(indent=indent, content=content, line=line_number))
        index += 1
    return tokens


def parse_yaml_scalar(value: str, path: Path, line: int) -> Any:
    if not value:
        return None
    if value.startswith(("&", "*", "!", "<<:")):
        raise ValueError(f"{path}:{line} uses unsupported YAML anchors, aliases, or tags")
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line} has an invalid quoted YAML scalar") from error
        if not isinstance(parsed, str):
            raise ValueError(f"{path}:{line} expected a quoted string")
        return parsed
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise ValueError(f"{path}:{line} has an unterminated quoted YAML scalar")
        return value[1:-1].replace("''", "'")
    if value.startswith(("[", "{")):
        raise ValueError(f"{path}:{line} must use block-style YAML, not flow collections")
    lowered = value.casefold()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    if re.fullmatch(r"-?(?:0|[1-9]\d*)", value):
        return int(value)
    if re.fullmatch(r"-?(?:0|[1-9]\d*)\.\d+", value):
        return float(value)
    if value.startswith(("'", '"')) or value.endswith(("'", '"')):
        raise ValueError(f"{path}:{line} has malformed YAML quoting")
    return value


class YamlParser:
    def __init__(self, tokens: list[YamlToken], path: Path):
        self.tokens = tokens
        self.path = path
        self.index = 0

    def parse(self) -> Any:
        if not self.tokens:
            return {}
        if self.tokens[0].indent != 0:
            raise ValueError(f"{self.path}:{self.tokens[0].line} YAML must start at column 1")
        result = self.parse_node(0)
        if self.index != len(self.tokens):
            token = self.tokens[self.index]
            raise ValueError(f"{self.path}:{token.line} has inconsistent YAML indentation")
        return result

    def parse_node(self, indent: int) -> Any:
        token = self.tokens[self.index]
        if token.content == "-" or token.content.startswith("- "):
            return self.parse_sequence(indent)
        return self.parse_mapping(indent)

    def parse_mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while self.index < len(self.tokens):
            token = self.tokens[self.index]
            if token.indent < indent:
                break
            if token.indent > indent:
                raise ValueError(f"{self.path}:{token.line} has unexpected YAML indentation")
            if token.content == "-" or token.content.startswith("- "):
                break
            key, remainder = split_yaml_mapping(token.content, self.path, token.line)
            if key in result:
                raise ValueError(f"{self.path}:{token.line} has duplicate YAML key '{key}'")
            self.index += 1
            if token.block_value is not None:
                result[key] = token.block_value
            elif remainder:
                result[key] = parse_yaml_scalar(remainder, self.path, token.line)
            elif self.index < len(self.tokens) and self.tokens[self.index].indent > indent:
                result[key] = self.parse_node(self.tokens[self.index].indent)
            else:
                result[key] = None
        return result

    def parse_sequence(self, indent: int) -> list[Any]:
        result: list[Any] = []
        while self.index < len(self.tokens):
            token = self.tokens[self.index]
            if token.indent < indent:
                break
            if token.indent != indent or not (
                token.content == "-" or token.content.startswith("- ")
            ):
                break
            remainder = token.content[1:].strip()
            self.index += 1
            if not remainder:
                if self.index >= len(self.tokens) or self.tokens[self.index].indent <= indent:
                    result.append(None)
                else:
                    result.append(self.parse_node(self.tokens[self.index].indent))
                continue
            if ":" in remainder:
                key, value = split_yaml_mapping(remainder, self.path, token.line)
                item: dict[str, Any] = {key: parse_yaml_scalar(value, self.path, token.line)}
                if self.index < len(self.tokens) and self.tokens[self.index].indent > indent:
                    siblings = self.parse_mapping(self.tokens[self.index].indent)
                    duplicate = set(item) & set(siblings)
                    if duplicate:
                        name = sorted(duplicate)[0]
                        raise ValueError(f"{self.path}:{token.line} has duplicate YAML key '{name}'")
                    item.update(siblings)
                result.append(item)
            else:
                result.append(parse_yaml_scalar(remainder, self.path, token.line))
        return result


def parse_yaml(text: str, path: Path) -> Any:
    return YamlParser(tokenize_yaml(text, path), path).parse()


def require_mapping(value: Any, path: Path, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} field '{context}' must be a YAML mapping")
    return value


def reject_unknown_fields(mapping: dict[str, Any], allowed: set[str], path: Path, context: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ValueError(f"{path} {context} has unknown field '{unknown[0]}'")


def require_string(mapping: dict[str, Any], key: str, path: Path, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} {context} must define non-empty string '{key}'")
    return value.strip()


def validate_skill_schema(metadata: Any, skill_dir: Path, skill_file: Path) -> str:
    relative = Path(label(skill_file))
    mapping = require_mapping(metadata, relative, "frontmatter")
    reject_unknown_fields(mapping, SKILL_FIELDS, relative, "frontmatter")
    name = require_string(mapping, "name", relative, "frontmatter")
    description = require_string(mapping, "description", relative, "frontmatter")
    if len(name) > 64:
        raise ValueError(f"{relative} skill name must contain at most 64 characters")
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError(f"{relative} has invalid skill name '{name}'")
    if name != skill_dir.name:
        raise ValueError(f"{relative} names '{name}', but its directory is '{skill_dir.name}'")
    if len(description) > 1024:
        raise ValueError(f"{relative} description must contain at most 1024 characters")
    for key in ("license", "allowed-tools"):
        if key in mapping and not isinstance(mapping[key], str):
            raise ValueError(f"{relative} field '{key}' must be a string")
    if "compatibility" in mapping:
        compatibility = mapping["compatibility"]
        if not isinstance(compatibility, str) or len(compatibility) > 500:
            raise ValueError(f"{relative} compatibility must be a string of at most 500 characters")
    if "metadata" in mapping:
        custom = require_mapping(mapping["metadata"], relative, "metadata")
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in custom.items()):
            raise ValueError(f"{relative} metadata keys and values must all be strings")
    return name


def validate_relative_asset(skill_dir: Path, value: str, metadata_path: Path, key: str) -> None:
    if "\\" in value:
        raise ValueError(f"{metadata_path} {key} must use a relative asset path with '/' separators")
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"{metadata_path} {key} must be a relative asset path inside the skill")
    current = skill_dir
    for part in pure.parts:
        current = current / part
        try:
            file_stat = current.lstat()
        except FileNotFoundError as error:
            raise ValueError(f"{metadata_path} {key} does not exist: '{value}'") from error
        if stat.S_ISLNK(file_stat.st_mode):
            raise ValueError(f"{metadata_path} {key} must not reference a symlink: '{value}'")
    if not current.is_file():
        raise ValueError(f"{metadata_path} {key} must reference a file: '{value}'")


def validate_openai_schema(value: Any, skill_dir: Path, metadata_file: Path) -> None:
    relative = Path(label(metadata_file))
    mapping = require_mapping(value, relative, "document")
    reject_unknown_fields(mapping, OPENAI_FIELDS, relative, "document")
    interface = require_mapping(mapping.get("interface"), relative, "interface")
    reject_unknown_fields(interface, OPENAI_INTERFACE_FIELDS, relative, "interface")
    for key in ("display_name", "short_description", "default_prompt"):
        require_string(interface, key, relative, "interface")
    for key in ("icon_small", "icon_large"):
        if key in interface:
            asset = require_string(interface, key, relative, "interface")
            validate_relative_asset(skill_dir, asset, relative, key)
    if "brand_color" in interface:
        color = require_string(interface, "brand_color", relative, "interface")
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            raise ValueError(f"{relative} interface.brand_color must be a six-digit hex color")

    if "policy" in mapping:
        policy = require_mapping(mapping["policy"], relative, "policy")
        reject_unknown_fields(policy, OPENAI_POLICY_FIELDS, relative, "policy")
        if "allow_implicit_invocation" in policy and not isinstance(
            policy["allow_implicit_invocation"], bool
        ):
            raise ValueError(f"{relative} policy.allow_implicit_invocation must be a boolean")

    if "dependencies" in mapping:
        dependencies = require_mapping(mapping["dependencies"], relative, "dependencies")
        reject_unknown_fields(dependencies, OPENAI_DEPENDENCY_FIELDS, relative, "dependencies")
        tools = dependencies.get("tools")
        if not isinstance(tools, list):
            raise ValueError(f"{relative} dependencies.tools must be a list")
        for index, tool_value in enumerate(tools):
            tool = require_mapping(tool_value, relative, f"dependencies.tools[{index}]")
            reject_unknown_fields(tool, OPENAI_TOOL_FIELDS, relative, f"dependencies.tools[{index}]")
            require_string(tool, "type", relative, f"dependencies.tools[{index}]")
            require_string(tool, "value", relative, f"dependencies.tools[{index}]")
            for key in ("description", "transport", "url"):
                if key in tool and (not isinstance(tool[key], str) or not tool[key].strip()):
                    raise ValueError(f"{relative} dependencies.tools[{index}].{key} must be a string")


def validate_text_safety(path: Path, text: str, reject_format_controls: bool) -> None:
    for offset, character in enumerate(text):
        codepoint = ord(character)
        hidden_format_control = (
            reject_format_controls and unicodedata.category(character) == "Cf"
        )
        if codepoint not in SUSPICIOUS_CODEPOINTS and not hidden_format_control:
            continue
        line = text.count("\n", 0, offset) + 1
        raise ValueError(f"{label(path)}:{line} contains hidden Unicode U+{codepoint:04X}")


def validate_python(path: Path, text: str) -> None:
    try:
        compile(text, str(path), "exec")
    except SyntaxError as error:
        raise ValueError(f"{label(path)} does not compile: {error}") from error


def inspect_resource(path: Path, skill_dir: Path) -> None:
    data = path.read_bytes()
    executable = bool(path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    relative_to_skill = path.relative_to(skill_dir)
    binary_asset = (
        relative_to_skill.parts[0] == "assets" and path.suffix.casefold() in BINARY_ASSET_SUFFIXES
    )
    should_be_text = executable or path.suffix.casefold() in TEXT_SUFFIXES or b"\x00" not in data
    if not should_be_text:
        if binary_asset:
            return
        raise ValueError(f"{label(path)} is an unsupported binary resource")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        if binary_asset and not executable:
            return
        raise ValueError(f"{label(path)} is not valid UTF-8") from error
    if text.startswith("\ufeff"):
        raise ValueError(f"{label(path)} starts with a UTF-8 BOM")
    suffix = path.suffix.casefold()
    validate_text_safety(
        path,
        text,
        reject_format_controls=(
            executable
            or relative_to_skill.parts[0] == "scripts"
            or suffix not in FORMAT_CONTROL_ALLOWED_PROSE_SUFFIXES
        ),
    )
    if suffix == ".py":
        validate_python(path, text)
    elif suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(f"{label(path)} is not valid JSON: {error}") from error
    elif suffix in {".yaml", ".yml"}:
        parse_yaml(text, Path(label(path)))


def validate_skill(skill_dir: Path) -> str:
    if skill_dir.is_symlink():
        raise ValueError(f"{label(skill_dir)} must not be a symlink")
    readme_file = skill_dir / "README.md"
    if not readme_file.is_file():
        raise ValueError(f"{label(readme_file)} is required")
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        raise ValueError(f"{label(skill_file)} is required")

    skill_text = read_utf8(skill_file)
    metadata_text = frontmatter(skill_text, Path(label(skill_file)))
    metadata = parse_yaml(metadata_text, Path(label(skill_file)))
    name = validate_skill_schema(metadata, skill_dir, skill_file)

    for path in sorted(skill_dir.rglob("*")):
        if "__pycache__" in path.relative_to(skill_dir).parts:
            continue
        if path.is_symlink():
            raise ValueError(f"{label(path)} must not be a symlink")
        if path.is_file():
            inspect_resource(path, skill_dir)

    openai_metadata = skill_dir / "agents" / "openai.yaml"
    if openai_metadata.exists():
        metadata_document = parse_yaml(read_utf8(openai_metadata), Path(label(openai_metadata)))
        validate_openai_schema(metadata_document, skill_dir, openai_metadata)
    return name


def validate_repository(root: Path) -> list[str]:
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        raise ValueError("skills/ is required and must contain at least one skill")
    skill_dirs = sorted(path for path in skills_dir.iterdir() if path.is_dir())
    if not skill_dirs:
        raise ValueError("skills/ must contain at least one skill")
    names = [validate_skill(path) for path in skill_dirs]
    if len(names) != len(set(names)):
        raise ValueError("skill names must be unique")
    return names


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repository root to validate; defaults to the validator's parent repository",
    )
    return parser.parse_args()


def main() -> int:
    global ROOT
    args = parse_args()
    try:
        ROOT = args.root.expanduser().resolve(strict=True)
        names = validate_repository(ROOT)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Validated {len(names)} skill(s): {', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
