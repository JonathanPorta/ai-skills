from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "package-design-handoff"
PACKAGER = SKILL_DIR / "scripts" / "package_handoff.py"
VALIDATOR_PATH = ROOT / "scripts" / "check_skills.py"
OPEN_DESIGN_COMMIT = "517f39acde402c1a7af2189167a8d6957a3dac71"


def infer_pinned_open_design_mode(description: str, body: str) -> str:
    haystack = f"{description}\n{body}".lower()
    checks = (
        (r"\bimage|poster|illustration|photography|图片|海报|插画", "image"),
        (r"\bvideo|motion|shortform|animation|视频|动效|短片", "video"),
        (r"\baudio|music|jingle|tts|sound|音频|音乐|配音|音效", "audio"),
        (r"\bppt|deck|slide|presentation|幻灯|投影", "deck"),
        (r"\bdesign[- ]system|\bdesign\.md|\bdesign tokens", "design-system"),
        (r"\btemplate\b", "template"),
    )
    for pattern, mode in checks:
        if re.search(pattern, haystack):
            return mode
    return "prototype"


class OpenDesignIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("OPEN_DESIGN_REPO"), "OPEN_DESIGN_REPO is not set")
    def test_pinned_contract_discovers_non_image_skill_and_emits_zip(self) -> None:
        open_design = Path(os.environ["OPEN_DESIGN_REPO"]).resolve()
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=open_design,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(revision, OPEN_DESIGN_COMMIT)

        protocol = (open_design / "docs" / "skills-protocol.md").read_text(encoding="utf-8")
        runtime = (open_design / "apps" / "daemon" / "src" / "skills.ts").read_text(
            encoding="utf-8"
        )
        self.assertIn("od skills list", protocol)
        self.assertIn("od skills show", protocol)
        self.assertIn('value === "prototype"', runtime)

        spec = importlib.util.spec_from_file_location("skill_validator", VALIDATOR_PATH)
        assert spec and spec.loader
        validator = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = validator
        spec.loader.exec_module(validator)
        skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        metadata_text = validator.frontmatter(skill_text, Path("skills/package-design-handoff/SKILL.md"))
        metadata = validator.parse_yaml(metadata_text, Path("skills/package-design-handoff/SKILL.md"))
        body = skill_text.split("---", 2)[2]
        self.assertNotIn("od", metadata)
        self.assertEqual(infer_pinned_open_design_mode(metadata["description"], body), "prototype")

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            project.mkdir()
            (project / "design.fig").write_text("design\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(PACKAGER),
                    str(project),
                    "--project-name",
                    "Open Design Contract",
                    "--bump-reason",
                    "Verify pinned Open Design integration",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(project / "open-design-contract-0.1.0.zip") as archive:
                self.assertIn("design.fig", archive.namelist())


if __name__ == "__main__":
    unittest.main()
