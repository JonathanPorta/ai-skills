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
CHECKPOINT_DIR = ROOT / "skills" / "package-design-checkpoint"
HANDOFF_DIR = ROOT / "skills" / "package-design-handoff"
OPEN_DESIGN_COMMIT = "fe1231eed69a2312e56c4e155e06781981fff068"


class OpenDesignIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("OPEN_DESIGN_REPO"), "OPEN_DESIGN_REPO is not set")
    def test_production_plugin_loader_injects_and_stages_both_helpers(self) -> None:
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
        for built_package in (
            open_design / "packages" / "contracts" / "dist" / "index.mjs",
            open_design / "packages" / "plugin-runtime" / "dist" / "index.mjs",
        ):
            self.assertTrue(
                built_package.is_file(),
                f"pinned Open Design runtime package is not built: {built_package}",
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            (project / "primary.html").write_text(
                "<!doctype html><title>Primary</title>\n", encoding="utf-8"
            )
            (project / "notes.md").write_text(
                "Current design state.\n", encoding="utf-8"
            )

            harness = root / "open-design-plugin-contract.ts"
            registry_module = (
                open_design / "apps" / "daemon" / "src" / "plugins" / "registry.ts"
            ).as_uri()
            local_skill_module = (
                open_design / "apps" / "daemon" / "src" / "plugins" / "local-skill.ts"
            ).as_uri()
            apply_module = (
                open_design / "apps" / "daemon" / "src" / "plugins" / "apply.ts"
            ).as_uri()
            staging_module = (
                open_design / "apps" / "daemon" / "src" / "cwd-aliases.ts"
            ).as_uri()
            harness.write_text(
                f"""
import {{ resolvePluginFolder }} from {json.dumps(registry_module)};
import {{ loadPluginLocalSkill }} from {json.dumps(local_skill_module)};
import {{ applyPlugin }} from {json.dumps(apply_module)};
import {{ skillCwdAliasSegment, stageActiveSkill }} from {json.dumps(staging_module)};

async function resolveAndStage(folder, projectRoot) {{
  const folderId = folder.split(/[\\\\/]/).filter(Boolean).at(-1);
  const resolved = await resolvePluginFolder({{
    folder,
    folderId,
    sourceKind: "github",
    trust: "restricted",
  }});
  if (!resolved.ok) throw new Error(resolved.errors.join("; "));
  const applied = applyPlugin({{
    plugin: resolved.record,
    inputs: {{}},
    registry: {{ skills: [], designSystems: [], craft: [], atoms: [], scenarios: [] }},
  }});
  const local = await loadPluginLocalSkill(resolved.record);
  if (!local) throw new Error(`plugin-local SKILL.md did not load for ${{folderId}}`);
  const staging = await stageActiveSkill(
    projectRoot,
    skillCwdAliasSegment(local.dir),
    local.dir,
  );
  if (!staging.staged || !staging.stagedPath) {{
    throw new Error(`stageActiveSkill failed for ${{folderId}}: ${{staging.reason ?? "unknown"}}`);
  }}
  return {{
    id: resolved.record.id,
    version: resolved.record.version,
    kind: resolved.record.manifest.od?.kind,
    capabilities: resolved.record.capabilitiesGranted,
    appliedCapabilities: applied.result.capabilitiesGranted,
    appliedQuery: applied.result.query,
    appliedPipeline: applied.result.pipeline ?? null,
    projectSkillId: applied.result.projectMetadata.skillId ?? null,
    applyWarnings: applied.warnings,
    localBody: local.body,
    localDir: local.dir,
    stagedPath: staging.stagedPath,
  }};
}}

async function main() {{
  const [projectRoot, ...folders] = process.argv.slice(2);
  const results = [];
  for (const folder of folders) results.push(await resolveAndStage(folder, projectRoot));
  process.stdout.write(JSON.stringify(results));
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
                    str(project),
                    str(CHECKPOINT_DIR),
                    str(HANDOFF_DIR),
                ],
                cwd=open_design,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(discovery.returncode, 0, discovery.stderr)
            records = {record["id"]: record for record in json.loads(discovery.stdout)}
            self.assertEqual(
                set(records),
                {"package-design-checkpoint", "package-design-handoff"},
            )

            expected = {
                "package-design-checkpoint": (
                    CHECKPOINT_DIR,
                    "scripts/package_checkpoint.py",
                    "Package Design Checkpoint",
                ),
                "package-design-handoff": (
                    HANDOFF_DIR,
                    "scripts/package_handoff.py",
                    "Package Design Handoff",
                ),
            }
            for plugin_id, (skill_dir, helper_path, body_heading) in expected.items():
                with self.subTest(plugin_id=plugin_id):
                    record = records[plugin_id]
                    self.assertEqual(record["version"], "0.1.0")
                    self.assertEqual(record["kind"], "scenario")
                    self.assertEqual(record["capabilities"], ["prompt:inject"])
                    self.assertEqual(record["appliedCapabilities"], ["prompt:inject"])
                    self.assertIsInstance(record["appliedQuery"], str)
                    self.assertTrue(record["appliedQuery"])
                    self.assertIsNone(record["appliedPipeline"])
                    self.assertIsNone(record["projectSkillId"])
                    self.assertIsInstance(record["applyWarnings"], list)
                    self.assertIn(body_heading, record["localBody"])
                    self.assertEqual(Path(record["localDir"]).resolve(), skill_dir.resolve())
                    staged_path = Path(record["stagedPath"])
                    self.assertTrue(staged_path.is_relative_to(project / ".od-skills"))
                    self.assertTrue((staged_path / helper_path).is_file())

            checkpoint_helper = (
                Path(records["package-design-checkpoint"]["stagedPath"])
                / "scripts"
                / "package_checkpoint.py"
            )
            checkpoint = subprocess.run(
                [
                    sys.executable,
                    str(checkpoint_helper),
                    str(project),
                    "--project-name",
                    "Open Design Contract",
                    "--index",
                    "index.html",
                    "--primary",
                    "primary.html",
                    "Current primary design state",
                    "--change",
                    "Verify plugin-local checkpoint loading and staging",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr)
            checkpoint_zip = project / "open-design-contract-checkpoint-0.1.0.zip"
            with zipfile.ZipFile(checkpoint_zip) as archive:
                names = set(archive.namelist())
                self.assertIn("index.html", names)
                self.assertIn("_checkpoint/CHANGELOG.md", names)
                self.assertFalse(any(name.startswith(".od-skills/") for name in names))

            handoff_helper = (
                Path(records["package-design-handoff"]["stagedPath"])
                / "scripts"
                / "package_handoff.py"
            )
            handoff = subprocess.run(
                [
                    sys.executable,
                    str(handoff_helper),
                    str(project),
                    "--project-name",
                    "Open Design Contract",
                    "--bump-reason",
                    "Verify plugin-local final-handoff loading and staging",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(handoff.returncode, 0, handoff.stderr)
            with zipfile.ZipFile(project / "open-design-contract-0.1.0.zip") as archive:
                names = set(archive.namelist())
                self.assertIn("_handoff/MANIFEST.json", names)
                self.assertNotIn(checkpoint_zip.name, names)
                self.assertFalse(any(name.startswith(".od-skills/") for name in names))


if __name__ == "__main__":
    unittest.main()
