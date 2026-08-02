#!/usr/bin/env python3
"""Validate the repository's Agent Skills without third-party dependencies."""

from __future__ import annotations

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SUSPICIOUS_CODEPOINTS = (
    set(range(0x202A, 0x202F))
    | set(range(0x2066, 0x206A))
    | {0x200B, 0x200C, 0x200D, 0xFEFF}
    | set(range(0xE0000, 0xE0080))
)


def read_utf8(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{path.relative_to(ROOT)} is not valid UTF-8") from error
    if text.startswith("\ufeff"):
        raise ValueError(f"{path.relative_to(ROOT)} starts with a UTF-8 BOM")
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


def scalar(metadata: str, key: str, relative_path: Path) -> str:
    matches = re.findall(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", metadata)
    if len(matches) != 1:
        raise ValueError(f"{relative_path} must define exactly one non-empty '{key}'")
    return matches[0].strip().strip("'\"")


def validate_text_safety(path: Path, text: str) -> None:
    for offset, character in enumerate(text):
        if ord(character) not in SUSPICIOUS_CODEPOINTS:
            continue
        line = text.count("\n", 0, offset) + 1
        raise ValueError(
            f"{path.relative_to(ROOT)}:{line} contains hidden Unicode U+{ord(character):04X}"
        )


def validate_python(path: Path, text: str) -> None:
    try:
        compile(text, str(path), "exec")
    except SyntaxError as error:
        raise ValueError(f"{path.relative_to(ROOT)} does not compile: {error}") from error


def validate_skill(skill_dir: Path) -> str:
    if skill_dir.is_symlink():
        raise ValueError(f"{skill_dir.relative_to(ROOT)} must not be a symlink")
    readme_file = skill_dir / "README.md"
    if not readme_file.is_file():
        raise ValueError(f"{readme_file.relative_to(ROOT)} is required")
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        raise ValueError(f"{skill_file.relative_to(ROOT)} is required")

    skill_text = read_utf8(skill_file)
    metadata = frontmatter(skill_text, skill_file.relative_to(ROOT))
    name = scalar(metadata, "name", skill_file.relative_to(ROOT))
    description = scalar(metadata, "description", skill_file.relative_to(ROOT))
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError(f"{skill_file.relative_to(ROOT)} has invalid skill name '{name}'")
    if name != skill_dir.name:
        raise ValueError(
            f"{skill_file.relative_to(ROOT)} names '{name}', but its directory is '{skill_dir.name}'"
        )
    if len(description) < 20:
        raise ValueError(f"{skill_file.relative_to(ROOT)} description is too short")

    for path in sorted(skill_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"{path.relative_to(ROOT)} must not be a symlink")
        if not path.is_file() or path.suffix.lower() not in {
            ".md",
            ".py",
            ".svg",
            ".txt",
            ".yaml",
            ".yml",
            ".json",
        }:
            continue
        text = read_utf8(path)
        validate_text_safety(path, text)
        if path.suffix.lower() == ".py":
            validate_python(path, text)

    openai_metadata = skill_dir / "agents" / "openai.yaml"
    if openai_metadata.exists():
        metadata_text = read_utf8(openai_metadata)
        for required_key in ("display_name", "short_description", "default_prompt"):
            if not re.search(rf"(?m)^\s+{required_key}:\s*\S", metadata_text):
                raise ValueError(
                    f"{openai_metadata.relative_to(ROOT)} must define '{required_key}'"
                )
    return name


def main() -> int:
    try:
        if not SKILLS_DIR.is_dir():
            raise ValueError("skills/ is required and must contain at least one skill")
        skill_dirs = sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir())
        if not skill_dirs:
            raise ValueError("skills/ must contain at least one skill")
        names = [validate_skill(path) for path in skill_dirs]
        if len(names) != len(set(names)):
            raise ValueError("skill names must be unique")
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Validated {len(names)} skill(s): {', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
