from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "package-design-handoff" / "scripts" / "package_handoff.py"


class PackageHandoffTests(unittest.TestCase):
    def run_packager(
        self,
        project: Path,
        *extra_arguments: str,
        expect_success: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(project),
                "--project-name",
                "Sample Design",
                "--bump-reason",
                "Exercise repository packaging behavior",
                *extra_arguments,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if expect_success and result.returncode != 0:
            self.fail(f"packager failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def make_project(self, root: Path) -> Path:
        project = root / "project"
        (project / "assets").mkdir(parents=True)
        (project / "node_modules" / "ignored").mkdir(parents=True)
        (project / ".git").mkdir()
        (project / "design.fig").write_text("editable design\n", encoding="utf-8")
        (project / "assets" / "screen.svg").write_text("<svg/>\n", encoding="utf-8")
        (project / "node_modules" / "ignored" / "dependency.js").write_text(
            "ignored\n", encoding="utf-8"
        )
        (project / ".git" / "config").write_text("ignored\n", encoding="utf-8")
        return project

    def test_initial_archive_is_complete_and_excludes_disposable_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            result = self.run_packager(project)
            archive_path = project / "sample-design-0.1.0.zip"

            self.assertTrue(archive_path.is_file())
            self.assertIn("Version: none -> 0.1.0 (initial)", result.stdout)
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                self.assertEqual(
                    names,
                    {
                        "design.fig",
                        "assets/screen.svg",
                        "_handoff/README.md",
                        "_handoff/MANIFEST.json",
                        "_handoff/CHECKSUMS.sha256",
                    },
                )
                manifest = json.loads(archive.read("_handoff/MANIFEST.json"))
                self.assertEqual(manifest["version"], "0.1.0")
                self.assertEqual(manifest["payload_file_count"], 2)

    def test_legacy_archive_advances_to_next_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            (project / "sample-design-v0.2.3.zip").write_bytes(b"legacy archive marker")

            self.run_packager(project, "--bump", "patch")

            self.assertTrue((project / "sample-design-0.2.4.zip").is_file())

    def test_non_monotonic_explicit_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            self.run_packager(project)

            result = self.run_packager(
                project,
                "--version",
                "0.1.0",
                expect_success=False,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("must be greater than existing version 0.1.0", result.stderr)


if __name__ == "__main__":
    unittest.main()
