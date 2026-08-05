from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from xml.etree import ElementTree


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
        (skill / "open-design.json").write_text(
            json.dumps(
                {
                    "$schema": "https://open-design.ai/schemas/plugin.v1.json",
                    "specVersion": "1.0.0",
                    "name": "demo-skill",
                    "title": "Demo Skill",
                    "version": "0.1.0",
                    "description": "Run the demo workflow.",
                    "compat": {"agentSkills": [{"path": "./SKILL.md"}]},
                    "od": {
                        "kind": "scenario",
                        "taskKind": "tune-collab",
                        "mode": "export",
                        "context": {"skills": [{"path": "./SKILL.md"}]},
                        "capabilities": ["prompt:inject"],
                    },
                },
                indent=2,
            )
            + "\n",
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

    def test_paired_icons_keep_checkpoint_open_and_handoff_uniformly_closed(self) -> None:
        checkpoint_file = ROOT / "skills/package-design-checkpoint/assets/icon.svg"
        handoff_file = ROOT / "skills/package-design-handoff/assets/icon.svg"
        checkpoint = ElementTree.parse(checkpoint_file).getroot()
        handoff = ElementTree.parse(handoff_file).getroot()

        self.assertEqual(checkpoint.attrib["viewBox"], "0 0 128 128")
        self.assertEqual(handoff.attrib["viewBox"], checkpoint.attrib["viewBox"])

        checkpoint_paths = [element.attrib for element in checkpoint if element.tag.endswith("path")]
        handoff_paths = [element.attrib for element in handoff if element.tag.endswith("path")]
        amber = {"d": "M56 55h38v14H70v16H56z", "fill": "#f5c96a"}
        mint_ring = {
            "d": "M34 29h74v70H34zM48 43v42h46V43z",
            "fill": "#8ad8c8",
            "fill-rule": "evenodd",
            "clip-rule": "evenodd",
        }

        self.assertIn(amber, checkpoint_paths)
        self.assertIn(amber, handoff_paths)
        self.assertIn(mint_ring, handoff_paths)
        self.assertTrue(any(element.tag.endswith("circle") for element in checkpoint))
        self.assertFalse(any(element.tag.endswith("circle") for element in handoff))

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

    def test_open_design_manifest_identity_and_runtime_binding_are_required(self) -> None:
        controls = (
            (("name", "wrong-name"), "must match skill directory"),
            (("version", "main"), "stable SemVer"),
        )
        for (field, value), message in controls:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as temporary:
                    repository, skill = self.make_repository(Path(temporary))
                    manifest_file = skill / "open-design.json"
                    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                    manifest[field] = value
                    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

                    result = self.validate(repository)

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(message, result.stderr)

        for missing_path in ("compat", "context"):
            with self.subTest(missing_path=missing_path):
                with tempfile.TemporaryDirectory() as temporary:
                    repository, skill = self.make_repository(Path(temporary))
                    manifest_file = skill / "open-design.json"
                    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                    if missing_path == "compat":
                        manifest["compat"]["agentSkills"] = []
                    else:
                        manifest["od"]["context"]["skills"] = []
                    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

                    result = self.validate(repository)

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("./SKILL.md", result.stderr)

    def test_open_design_manifest_local_paths_must_resolve_inside_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, skill = self.make_repository(Path(temporary))
            manifest_file = skill / "open-design.json"
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            manifest["od"]["context"]["skills"] = [{"path": "../outside/SKILL.md"}]
            manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

            result = self.validate(repository)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("inside the skill", result.stderr)

    def test_open_design_compat_agent_skill_entries_require_a_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, skill = self.make_repository(Path(temporary))
            manifest_file = skill / "open-design.json"
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            manifest["compat"]["agentSkills"].append({"ref": "phantom-skill"})
            manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

            result = self.validate(repository)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("compat.agentSkills[1].path is required", result.stderr)

    def test_executable_and_code_resources_reject_hidden_format_controls(self) -> None:
        controls = (
            ("run-bidi", "\u202e", True),
            ("run-word-joiner", "\u2060", True),
            ("soft-hyphen.py", "\u00ad", False),
            ("library.rs", "\u2060", False),
        )
        for filename, control, executable_bit in controls:
            with self.subTest(filename=filename, codepoint=f"U+{ord(control):04X}"):
                with tempfile.TemporaryDirectory() as temporary:
                    repository, skill = self.make_repository(Path(temporary))
                    resource = skill / "scripts" / filename
                    if resource.suffix == ".py":
                        contents = f"print('safe')\n# hidden{control}\n"
                    else:
                        contents = f"#!/bin/sh\nprintf 'safe'{control}\n"
                    resource.write_text(contents, encoding="utf-8")
                    if executable_bit:
                        resource.chmod(0o755)

                    result = self.validate(repository)

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"U+{ord(control):04X}", result.stderr)
                    self.assertIn("hidden Unicode", result.stderr)

    def test_executable_and_code_resources_allow_ordinary_unicode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, skill = self.make_repository(Path(temporary))
            executable = skill / "scripts" / "run"
            executable.write_text(
                "#!/bin/sh\nprintf 'café 日本語'\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            (skill / "scripts" / "message.py").write_text(
                "print('Привет, κόσμε')\n",
                encoding="utf-8",
            )

            result = self.validate(repository)

            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
