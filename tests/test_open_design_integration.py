from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "package-design-handoff"
OPEN_DESIGN_COMMIT = "517f39acde402c1a7af2189167a8d6957a3dac71"


class OpenDesignIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("OPEN_DESIGN_REPO"), "OPEN_DESIGN_REPO is not set")
    def test_production_discovery_stages_prototype_skill_and_emits_zip(self) -> None:
        open_design = Path(os.environ["OPEN_DESIGN_REPO"]).resolve()
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=open_design,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(revision, OPEN_DESIGN_COMMIT)

        tsx = open_design / "node_modules" / "tsx" / "package.json"
        self.assertTrue(
            tsx.is_file(),
            "pinned Open Design dependencies are not installed; run its frozen pnpm install",
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skills_root = root / "skills"
            skills_root.mkdir()
            (skills_root / "package-design-handoff").symlink_to(
                SKILL_DIR,
                target_is_directory=True,
            )
            project = root / "project"
            project.mkdir()
            (project / "design.fig").write_text("design\n", encoding="utf-8")

            harness = root / "open-design-production-contract.ts"
            skills_module = (open_design / "apps" / "daemon" / "src" / "skills.ts").as_uri()
            staging_module = (
                open_design / "apps" / "daemon" / "src" / "cwd-aliases.ts"
            ).as_uri()
            harness.write_text(
                f"""
import {{ findSkillById, listSkills }} from {json.dumps(skills_module)};
import {{ skillCwdAliasSegment, stageActiveSkill }} from {json.dumps(staging_module)};

async function main() {{
  const [skillsRoot, projectRoot] = process.argv.slice(2);
  const skills = await listSkills(skillsRoot);
  const skill = findSkillById(skills, "package-design-handoff");
  if (!skill) throw new Error("production listSkills did not discover package-design-handoff");
  const staging = await stageActiveSkill(
    projectRoot,
    skillCwdAliasSegment(skill.dir),
    skill.dir,
  );
  if (!staging.staged || !staging.stagedPath) {{
    throw new Error(`production stageActiveSkill failed: ${{staging.reason ?? "unknown"}}`);
  }}
  process.stdout.write(JSON.stringify({{
    listedIds: skills.map((candidate) => candidate.id),
    id: skill.id,
    mode: skill.mode,
    sourceDir: skill.dir,
    stagedPath: staging.stagedPath,
  }}));
}}

main().catch((error) => {{
  console.error(error);
  process.exitCode = 1;
}});
""".lstrip(),
                encoding="utf-8",
            )

            discovery = subprocess.run(
                [
                    "node",
                    "--import",
                    "tsx",
                    str(harness),
                    str(skills_root),
                    str(project),
                ],
                cwd=open_design,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(discovery.returncode, 0, discovery.stderr)
            discovered = json.loads(discovery.stdout)
            self.assertIn("package-design-handoff", discovered["listedIds"])
            self.assertEqual(discovered["id"], "package-design-handoff")
            self.assertEqual(discovered["mode"], "prototype")
            self.assertEqual(Path(discovered["sourceDir"]).resolve(), SKILL_DIR.resolve())

            staged_path = Path(discovered["stagedPath"])
            self.assertTrue(staged_path.is_relative_to(project / ".od-skills"))
            staged_packager = staged_path / "scripts" / "package_handoff.py"
            self.assertTrue(staged_packager.is_file())

            packaging = subprocess.run(
                [
                    sys.executable,
                    str(staged_packager),
                    str(project),
                    "--project-name",
                    "Open Design Contract",
                    "--bump-reason",
                    "Verify pinned production discovery and staging",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(packaging.returncode, 0, packaging.stderr)
            with zipfile.ZipFile(project / "open-design-contract-0.1.0.zip") as archive:
                names = archive.namelist()
                self.assertIn("design.fig", names)
                self.assertFalse(any(name.startswith(".od-skills/") for name in names))


if __name__ == "__main__":
    unittest.main()
