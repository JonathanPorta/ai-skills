from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "check_skills.py"


class SkillValidatorTests(unittest.TestCase):
    def make_repository(self, root: Path) -> tuple[Path, Path]:
        repository = root / "repository"
        skill = repository / "skills" / "demo-skill"
        (skill / "agents").mkdir(parents=True)
        (skill / "assets").mkdir()
        (skill / "scripts").mkdir()
        (skill / "README.md").write_text("# Demo skill\n", encoding="utf-8")
        (skill / "assets" / "icon.svg").write_text("<svg/>\n", encoding="utf-8")
        (skill / "SKILL.md").write_text(
            "---\n"
            "name: demo-skill\n"
            "description: A sufficiently detailed description for this demo skill.\n"
            "---\n\n"
            "# Demo\n\nRun the workflow.\n",
            encoding="utf-8",
        )
        (skill / "agents" / "openai.yaml").write_text(
            "interface:\n"
            "  display_name: Demo Skill\n"
            "  short_description: Run the demo workflow\n"
            "  default_prompt: Use $demo-skill for this task.\n"
            "  icon_small: assets/icon.svg\n"
            "policy:\n"
            "  allow_implicit_invocation: true\n",
            encoding="utf-8",
        )
        return repository, skill

    def validate(self, repository: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), "--root", str(repository)],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_valid_repository_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, _skill = self.make_repository(Path(temporary))
            result = self.validate(repository)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_agent_skill_field_limits_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, skill = self.make_repository(Path(temporary))
            long_name = "a" * 65
            replacement = skill.parent / long_name
            skill.rename(replacement)
            skill_file = replacement / "SKILL.md"
            skill_file.write_text(
                skill_file.read_text(encoding="utf-8").replace("demo-skill", long_name, 1),
                encoding="utf-8",
            )
            result = self.validate(repository)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("at most 64", result.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            repository, skill = self.make_repository(Path(temporary))
            skill_file = skill / "SKILL.md"
            skill_file.write_text(
                "---\nname: demo-skill\ndescription: " + ("x" * 1025) + "\n---\n# Demo\n",
                encoding="utf-8",
            )
            result = self.validate(repository)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("at most 1024", result.stderr)

    def test_malformed_skill_yaml_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, skill = self.make_repository(Path(temporary))
            (skill / "SKILL.md").write_text(
                "---\nname: demo-skill\nname: duplicate\ndescription: Valid description text.\n---\n# Demo\n",
                encoding="utf-8",
            )
            result = self.validate(repository)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate YAML key", result.stderr)

    def test_openai_schema_and_icon_paths_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, skill = self.make_repository(Path(temporary))
            metadata = skill / "agents" / "openai.yaml"
            metadata.write_text(metadata.read_text(encoding="utf-8") + "unknown: true\n", encoding="utf-8")
            result = self.validate(repository)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown field", result.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            repository, skill = self.make_repository(Path(temporary))
            metadata = skill / "agents" / "openai.yaml"
            metadata.write_text(
                metadata.read_text(encoding="utf-8").replace("assets/icon.svg", "../secret.svg"),
                encoding="utf-8",
            )
            result = self.validate(repository)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("relative asset path", result.stderr)

    def test_extensionless_executable_is_scanned_for_hidden_unicode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, skill = self.make_repository(Path(temporary))
            executable = skill / "scripts" / "run"
            executable.write_text("#!/bin/sh\nprintf 'safe'\u202e\n", encoding="utf-8")
            executable.chmod(0o755)

            result = self.validate(repository)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("hidden Unicode", result.stderr)


if __name__ == "__main__":
    unittest.main()
