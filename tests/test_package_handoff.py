from __future__ import annotations

import json
import errno
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "package-design-handoff"
SCRIPT = ROOT / "skills" / "package-design-handoff" / "scripts" / "package_handoff.py"

SPEC = importlib.util.spec_from_file_location("package_handoff", SCRIPT)
assert SPEC and SPEC.loader
PACKAGE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PACKAGE
SPEC.loader.exec_module(PACKAGE)


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

    def test_credential_like_files_fail_closed_without_exact_review(self) -> None:
        sensitive_files = {
            ".env": "TOKEN=do-not-ship\n",
            "signing-key.pem": "-----BEGIN PRIVATE KEY-----\nsecret\n",
        }
        for relative_path, contents in sensitive_files.items():
            with self.subTest(relative_path=relative_path):
                with tempfile.TemporaryDirectory() as temporary:
                    project = self.make_project(Path(temporary))
                    (project / relative_path).write_text(contents, encoding="utf-8")

                    result = self.run_packager(project, expect_success=False)

                    self.assertEqual(result.returncode, 2)
                    self.assertIn("credential-like", result.stderr)
                    self.assertFalse((project / "sample-design-0.1.0.zip").exists())

    def test_sensitive_file_requires_exact_exclusion_or_inclusion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            (project / ".env").write_text("PUBLIC_EXAMPLE=true\n", encoding="utf-8")

            self.run_packager(project, "--exclude", ".env")

            with zipfile.ZipFile(project / "sample-design-0.1.0.zip") as archive:
                self.assertNotIn(".env", archive.namelist())

        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            (project / "docs").mkdir()
            reviewed = project / "docs" / "example-signing-key.pem"
            reviewed.write_text("public training fixture\n", encoding="utf-8")

            self.run_packager(
                project,
                "--include-sensitive",
                "docs/example-signing-key.pem",
            )

            with zipfile.ZipFile(project / "sample-design-0.1.0.zip") as archive:
                self.assertIn("docs/example-signing-key.pem", archive.namelist())
                manifest = json.loads(archive.read("_handoff/MANIFEST.json"))
                self.assertEqual(
                    manifest["reviewed_sensitive_inclusions"],
                    ["docs/example-signing-key.pem"],
                )

    def test_ignore_control_file_must_be_an_in_project_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self.make_project(root)
            outside = root / "outside-ignore"
            outside.write_text(".env\n", encoding="utf-8")
            (project / ".opendesign-handoffignore").symlink_to(outside)

            result = self.run_packager(project, expect_success=False)

            self.assertEqual(result.returncode, 2)
            self.assertIn("ignore control file", result.stderr)
            self.assertFalse((project / "sample-design-0.1.0.zip").exists())

    def test_unrelated_semver_zip_is_payload_and_dependency_trees_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            (project / "licensed-assets-1.0.0.zip").write_bytes(b"licensed assets")
            (project / ".venv" / "lib").mkdir(parents=True)
            (project / ".venv" / "lib" / "dependency.py").write_text(
                "ignored = True\n", encoding="utf-8"
            )

            self.run_packager(project)

            with zipfile.ZipFile(project / "sample-design-0.1.0.zip") as archive:
                names = set(archive.namelist())
                self.assertIn("licensed-assets-1.0.0.zip", names)
                self.assertNotIn(".venv/lib/dependency.py", names)

    def test_portable_zip_namespace_rejects_separator_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            (project / "docs").mkdir()
            (project / "docs" / "file.txt").write_text("slash\n", encoding="utf-8")
            (project / "docs\\file.txt").write_text("backslash\n", encoding="utf-8")

            result = self.run_packager(project, expect_success=False)

            self.assertEqual(result.returncode, 2)
            self.assertIn("portable ZIP namespace collision", result.stderr)
            self.assertFalse((project / "sample-design-0.1.0.zip").exists())

    def test_portable_namespace_rejects_case_unicode_reserved_and_traversal_names(self) -> None:
        controls = (
            (["Logo.svg", "logo.svg"], "collision"),
            (["caf\u00e9.txt", "cafe\u0301.txt"], "collision"),
            (["CON.txt"], "Windows-reserved"),
            (["../escape.txt"], "traversal"),
            (["/absolute.txt"], "absolute"),
        )
        for names, message in controls:
            with self.subTest(names=names):
                with self.assertRaisesRegex(ValueError, message):
                    PACKAGE.validate_portable_namespace(names)

    def test_private_archive_is_validated_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("payload\n", encoding="utf-8")
            payload = [
                PACKAGE.PayloadFile(
                    source_root=root,
                    absolute_path=source,
                    archive_path="source.txt",
                    size=source.stat().st_size,
                    sha256=PACKAGE.hash_file(source),
                    mode=0o644,
                )
            ]
            destination = root / "handoff-0.1.0.zip"
            with mock.patch.object(PACKAGE, "validate_zip", side_effect=ValueError("bad zip")):
                with self.assertRaisesRegex(ValueError, "bad zip"):
                    PACKAGE.build_zip(destination, payload, b"readme", b"{}", b"")
            self.assertFalse(destination.exists())

    def test_validation_failure_never_deletes_a_competing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("payload\n", encoding="utf-8")
            payload = [
                PACKAGE.PayloadFile(
                    source_root=root,
                    absolute_path=source,
                    archive_path="source.txt",
                    size=source.stat().st_size,
                    sha256=PACKAGE.hash_file(source),
                    mode=0o644,
                )
            ]
            destination = root / "handoff-0.1.0.zip"

            def replace_then_fail(*_args: object) -> None:
                destination.write_bytes(b"belongs to another process")
                raise ValueError("injected validation failure")

            with mock.patch.object(PACKAGE, "validate_zip", side_effect=replace_then_fail):
                with self.assertRaisesRegex(ValueError, "injected validation failure"):
                    PACKAGE.build_zip(destination, payload, b"readme", b"{}", b"")
            self.assertEqual(destination.read_bytes(), b"belongs to another process")

    def test_publish_failure_never_exposes_a_partial_fallback_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("payload\n", encoding="utf-8")
            payload = [
                PACKAGE.PayloadFile(
                    source_root=root,
                    absolute_path=source,
                    archive_path="source.txt",
                    size=source.stat().st_size,
                    sha256=PACKAGE.hash_file(source),
                    mode=0o644,
                )
            ]
            destination = root / "handoff-0.1.0.zip"
            with (
                mock.patch.object(PACKAGE, "validate_zip"),
                mock.patch.object(PACKAGE.os, "link", side_effect=OSError(errno.EXDEV, "cross-device")),
            ):
                with self.assertRaises(OSError):
                    PACKAGE.build_zip(destination, payload, b"readme", b"{}", b"")
            self.assertFalse(destination.exists())

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

    def test_open_design_and_codex_installation_is_documented(self) -> None:
        readme = (SKILL_DIR / "README.md").read_text(encoding="utf-8")
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn('"$OPEN_DESIGN_REPO/skills/package-design-handoff"', readme)
        self.assertIn('"$HOME/.agents/skills/package-design-handoff"', readme)
        self.assertIn("od skills list", readme)
        self.assertNotIn("od skill add", readme)
        self.assertIn("517f39acde402c1a7af2189167a8d6957a3dac71", readme)
        self.assertNotIn("\nod:", skill)
        self.assertIn("Package a completed OpenDesign", skill)


if __name__ == "__main__":
    unittest.main()
