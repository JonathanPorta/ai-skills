from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "package-design-checkpoint"
SCRIPT = SKILL_DIR / "scripts" / "package_checkpoint.py"


def load_checkpoint_module():
    if not SCRIPT.is_file():
        return None
    spec = importlib.util.spec_from_file_location("package_checkpoint", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PACKAGE = load_checkpoint_module()


class PackageCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertIsNotNone(PACKAGE, f"checkpoint helper is missing: {SCRIPT}")

    def make_project(self, root: Path) -> Path:
        project = root / "filesystem-name-must-not-be-identity"
        (project / "mockups").mkdir(parents=True)
        (project / "assets").mkdir()
        (project / "node_modules" / "ignored").mkdir(parents=True)
        (project / ".git").mkdir()
        (project / "mockups" / "primary.html").write_text(
            "<!doctype html><title>Primary</title>\n", encoding="utf-8"
        )
        (project / "mockups" / "mobile-error.html").write_text(
            "<!doctype html><title>Mobile error</title>\n", encoding="utf-8"
        )
        (project / "assets" / "brand.svg").write_text("<svg/>\n", encoding="utf-8")
        (project / "notes.md").write_text("State exploration notes.\n", encoding="utf-8")
        (project / "node_modules" / "ignored" / "dependency.js").write_text(
            "ignored\n", encoding="utf-8"
        )
        (project / ".git" / "config").write_text("ignored\n", encoding="utf-8")
        return project

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
                "Actual OpenDesign Project",
                "--namespace",
                "release-stable",
                "--index",
                "index.html",
                "--primary",
                "mockups/primary.html",
                "Primary comparison canvas",
                "--alternative",
                "mockups/mobile-error.html",
                "Mobile validation-error state",
                "--change",
                "Refined the comparison hierarchy and mobile validation state",
                *extra_arguments,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if expect_success and result.returncode != 0:
            self.fail(
                f"checkpoint helper failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    def test_initial_checkpoint_uses_explicit_identity_and_minimal_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))

            result = self.run_packager(project)
            archive_path = project / "actual-opendesign-project-checkpoint-0.1.0.zip"

            self.assertTrue(archive_path.is_file())
            self.assertNotIn("SHA-256:", result.stdout)
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                self.assertIn("index.html", names)
                self.assertIn("_checkpoint/CHANGELOG.md", names)
                self.assertIn("mockups/primary.html", names)
                self.assertIn("mockups/mobile-error.html", names)
                self.assertIn("assets/brand.svg", names)
                self.assertIn("notes.md", names)
                self.assertNotIn("node_modules/ignored/dependency.js", names)
                self.assertNotIn(".git/config", names)
                self.assertFalse(any(name.startswith("_handoff/") for name in names))
                self.assertNotIn("_checkpoint/MANIFEST.json", names)
                self.assertNotIn("_checkpoint/CHECKSUMS.sha256", names)
                changelog = archive.read("_checkpoint/CHANGELOG.md").decode("utf-8")
                self.assertIn("Actual OpenDesign Project", changelog)
                self.assertIn("Namespace: `release-stable`", changelog)
                self.assertIn("Primary comparison canvas", changelog)
                self.assertIn("Mobile validation-error state", changelog)
                index = archive.read("index.html").decode("utf-8")
                self.assertIn('href="mockups/primary.html"', index)
                self.assertIn('href="mockups/mobile-error.html"', index)

    def test_default_increment_is_patch_and_version_stream_is_independent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            handoff = project / "actual-opendesign-project-9.8.7.zip"
            handoff.write_bytes(b"unrelated handoff archive")

            self.run_packager(project)
            first = project / "actual-opendesign-project-checkpoint-0.1.0.zip"
            first_bytes = first.read_bytes()
            self.run_packager(project)
            second = project / "actual-opendesign-project-checkpoint-0.1.1.zip"

            self.assertEqual(first.read_bytes(), first_bytes)
            self.assertTrue(second.is_file())
            with zipfile.ZipFile(second) as archive:
                names = set(archive.namelist())
                self.assertNotIn(first.name, names)
                self.assertNotIn(handoff.name, names)

    def test_markdown_index_is_allowed_for_nonbrowser_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            (project / "mockups" / "mobile-error.html").unlink()
            (project / "mockups" / "primary.html").unlink()
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(project),
                    "--project-name",
                    "Research Notes",
                    "--index",
                    "index.md",
                    "--primary",
                    "notes.md",
                    "Primary [review] state-exploration notes",
                    "--change",
                    "Captured the current research and state exploration",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(project / "research-notes-checkpoint-0.1.0.zip") as archive:
                self.assertIn("index.md", archive.namelist())
                self.assertNotIn("index.html", archive.namelist())
                self.assertIn(
                    "Primary \\[review\\] state-exploration notes",
                    archive.read("index.md").decode("utf-8"),
                )

    def test_multiple_html_mockups_require_html_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            result = self.run_packager(
                project,
                "--index",
                "index.md",
                expect_success=False,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("multiple browsable", result.stderr)
            self.assertFalse(
                (project / "actual-opendesign-project-checkpoint-0.1.0.zip").exists()
            )

    def test_mixed_targets_still_require_html_index_for_multiple_html_mockups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            result = self.run_packager(
                project,
                "--index",
                "index.md",
                "--alternative",
                "notes.md",
                "Review and state-exploration notes",
                expect_success=False,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("multiple browsable", result.stderr)

    def test_every_browsable_html_mockup_must_be_declared_or_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            (project / "mockups" / "tablet-review.html").write_text(
                "<!doctype html><title>Tablet review</title>\n", encoding="utf-8"
            )

            result = self.run_packager(project, expect_success=False)

            self.assertEqual(result.returncode, 2)
            self.assertIn("every browsable HTML mockup", result.stderr)
            self.assertIn("mockups/tablet-review.html", result.stderr)

            self.run_packager(project, "--exclude", "mockups/tablet-review.html")
            self.assertTrue(
                (project / "actual-opendesign-project-checkpoint-0.1.0.zip").is_file()
            )

    def test_missing_or_duplicate_targets_and_generic_labels_fail(self) -> None:
        controls = (
            (
                ("--alternative", "mockups/missing.html", "Missing state"),
                "does not exist",
            ),
            (
                ("--alternative", "mockups/primary.html", "Duplicate primary"),
                "duplicate target",
            ),
            (
                ("--alternative", "mockups/mobile-error.html", "Alternative 1"),
                "functional label",
            ),
            (
                ("--alternative", "notes.md", "Option A"),
                "functional label",
            ),
        )
        for arguments, message in controls:
            with self.subTest(arguments=arguments):
                with tempfile.TemporaryDirectory() as temporary:
                    project = self.make_project(Path(temporary))
                    result = self.run_packager(
                        project,
                        *arguments,
                        expect_success=False,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(message, result.stderr)

    def test_positional_role_only_labels_are_not_functional(self) -> None:
        generic_labels = (
            "Primary",
            "Alternative",
            "Alternate",
            "Option",
            "Direction",
            "Variant",
            "Primary 1",
            "Alternative #2",
            "Option: 03",
            "Direction-4",
            "Variant5",
            "Primary A",
            "Alternative b",
            "Option #C",
            "Direction: d",
            "Variant-E",
            "Primary II",
            "Alternative III",
            "Option IV",
            "Direction XII",
            "Variant-IX",
            "Primary state",
            "Alternative screen B",
            "Option A.",
            "Option A:",
            "Option (A).",
            "Primary:",
            "Direction (IV)",
            "Option A!",
            "Option A,",
            "Option [A]",
            "Option {A}",
            "Option “A”",
            "Option A?",
            "Option A—",
            "OptionA",
            "Option A1",
            "Option 1A",
            "OptionA1",
            "Variant1A",
            "Option 1st",
            "Alternative 2nd",
            "Direction 3rd",
            "Variant 4th",
            "Option 11TH",
            "Option1st",
            "Option Ａ",
            "OptionＡ",
            "Option Ａ１",
            "Option １Ａ",
            "Option １ｓｔ",
            "Option Ⓐ",
            "Option Ⓐ①",
            "Option ①ˢᵗ",
            "Ｏｐｔｉｏｎ Ａ",
            "Ⓞⓟⓣⓘⓞⓝ Ⓐ",
            "Option α",
            "Variant ５",
            "Variant ①",
            "Variant ⑴",
            "Variant ㊿",
            "Variant ٢",
            "Variant ٢ND",
            "Direction Ⅳ",
            "Direction ⅳ",
            "Direction Ⅻ",
            "Direction CC",
            "Direction CXLII",
            "Option MM",
            "Option ＭＭ",
            "Variant MMMCMXCIX",
        )
        for label in generic_labels:
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, "not a functional label"):
                    PACKAGE.functional_label(label, "mockups/review.html")

    def test_descriptive_state_and_role_labels_are_functional(self) -> None:
        descriptive_labels = (
            "Primary comparison canvas",
            "Alternative mobile validation-error state",
            "Option optimized for keyboard navigation",
            "Direction high-density navigation",
            "Variant destructive-action confirmation",
            "Mobile validation-error state",
            "State 404 error recovery",
            "Direction RTL layout",
            "Variant XL breakpoint",
            "Option Mix",
            "Direction Civil",
            "State DIM",
            "Option A11y",
            "Option B2B",
            "Option A1 accessibility review",
            "Option 1A mobile state",
            "Option 1st accessibility review",
            "Direction 2nd mobile state",
            "Variant 3rd-pass comparison",
            "State 404th error recovery",
            "Option first-pass review",
            "Variant ＸＬ breakpoint",
            "Option Ⓐ accessibility review",
        )
        for label in descriptive_labels:
            with self.subTest(label=label):
                self.assertEqual(
                    PACKAGE.functional_label(label, "mockups/review.html"),
                    label,
                )

    def test_existing_index_must_name_labels_and_resolve_every_local_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            (project / "index.html").write_text(
                "<!doctype html><a href='mockups/primary.html'>Primary comparison canvas</a>"
                "<a href='mockups/missing.html'>Mobile validation-error state</a>\n",
                encoding="utf-8",
            )

            result = self.run_packager(project, expect_success=False)

            self.assertEqual(result.returncode, 2)
            self.assertIn("index target does not exist", result.stderr)
            self.assertFalse(
                (project / "actual-opendesign-project-checkpoint-0.1.0.zip").exists()
            )

    def test_existing_index_labels_must_belong_to_their_declared_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            (project / "index.html").write_text(
                "<!doctype html>"
                "<p>Primary comparison canvas</p>"
                "<a href='mockups/primary.html'>Unlabeled destination</a>"
                "<a href='mockups/mobile-error.html'>Mobile validation-error state</a>\n",
                encoding="utf-8",
            )

            result = self.run_packager(project, expect_success=False)

            self.assertEqual(result.returncode, 2)
            self.assertIn("does not functionally label its link", result.stderr)

    def test_existing_index_validates_srcset_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            (project / "index.html").write_text(
                "<!doctype html>"
                "<a href='mockups/primary.html'>Primary comparison canvas</a>"
                "<a href='mockups/mobile-error.html'>Mobile validation-error state</a>"
                "<img srcset='assets/brand.svg 1x, assets/missing.svg 2x'>\n",
                encoding="utf-8",
            )

            result = self.run_packager(project, expect_success=False)

            self.assertEqual(result.returncode, 2)
            self.assertIn("assets/missing.svg", result.stderr)

    def test_existing_index_rejects_unsafe_local_urls(self) -> None:
        unsafe_targets = (
            "../outside.html",
            "/absolute.html",
            "file:///tmp/secret",
            "javascript:alert(1)",
            "mockups%2f..%2foutside.html",
            "mockups\\primary.html",
        )
        for target in unsafe_targets:
            with self.subTest(target=target):
                with tempfile.TemporaryDirectory() as temporary:
                    project = self.make_project(Path(temporary))
                    (project / "index.html").write_text(
                        "<!doctype html>"
                        "<a href='mockups/primary.html'>Primary comparison canvas</a>"
                        "<a href='mockups/mobile-error.html'>Mobile validation-error state</a>"
                        f"<a href='{target}'>Unsafe target</a>\n",
                        encoding="utf-8",
                    )
                    result = self.run_packager(project, expect_success=False)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("unsafe index target", result.stderr)

    def test_credential_like_files_fail_closed_or_allow_exact_exclusion(self) -> None:
        for relative_path in (
            ".env",
            ".envrc",
            "secrets.yaml",
            "credentials.yml",
            "token.json",
            "client_secret.yaml",
            "service-account.yml",
            "credentials.toml",
            "secrets.toml",
            "token.yaml",
        ):
            with self.subTest(relative_path=relative_path):
                with tempfile.TemporaryDirectory() as temporary:
                    project = self.make_project(Path(temporary))
                    (project / relative_path).write_text(
                        "TOKEN=do-not-ship\n", encoding="utf-8"
                    )
                    result = self.run_packager(project, expect_success=False)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("credential-like", result.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            (project / ".env").write_text("TOKEN=do-not-ship\n", encoding="utf-8")
            self.run_packager(project, "--exclude", ".env")
            with zipfile.ZipFile(
                project / "actual-opendesign-project-checkpoint-0.1.0.zip"
            ) as archive:
                self.assertNotIn(".env", archive.namelist())

    def test_common_credential_filename_forms_fail_closed(self) -> None:
        sensitive_names = (
            "token",
            "api-token.txt",
            "github_token.txt",
            "password.txt",
            "PASSWORD.conf",
            "db-password.cfg",
            "db_password.ini",
            "secret",
            "CLIENT-SECRET.config",
            "client_secret.properties",
            "auth",
            "DEPLOY-AUTH.env",
            "deploy_auth.cnf",
            "credential",
            "USER-CREDENTIAL.txt",
            "user_credentials.conf",
            ".token",
            "api.token.txt",
            "api_token.env.local",
            "token.txt.bak",
            "credentials.csv",
            "client-secret.plist",
            "passwords.txt",
            "GitHubToken.txt",
            "clientSecret.json",
            "AWSCredentials.ini",
            "API Token.txt",
            "credentials~",
            "token~",
            "github-token (backup).txt",
            "githubtoken.txt",
            "clientsecret.json",
            "awscredentials.ini",
            "dbpassword.txt",
            "apitoken.txt",
            "serviceAccount.json",
            "ServiceAccount.yml",
            "apiToken2.txt",
            "token2026.txt",
            "passwords2026.txt",
            "tokenprod.txt",
            "passwordbackup.txt",
            "secretcopy.txt",
            "authlocal.ini",
            "credentialold.json",
            "serviceaccount2.json",
            "serviceAccount2.json",
            "serviceaccountbackup.json",
            "apikey.json",
            "accesskey.txt",
            "awsaccesskey.txt",
            "openaiapikey.txt",
            "password.md",
            "credentials.markdown",
            "client-secret.rst",
            "auth.log",
            "api-token.md",
            "githubtoken.md",
            "private-key.json",
            "private_key.yaml",
            "private.key.toml",
            "privateKey.txt",
            "privatekey.md",
            "signing-key.json",
            "signing_key.yaml",
            "signing.key.toml",
            "signingKey.txt",
            "signingkey.md",
            "api-token.txt.backup2",
            "api-token.txt.bak1",
            "api-token.txt.backup-copy",
            "api-token.txt.backup_copy",
            "credentials.json.old3",
            "ｐａｓｓｗｏｒｄ.md",
        )
        for relative_path in sensitive_names:
            with self.subTest(relative_path=relative_path):
                with tempfile.TemporaryDirectory() as temporary:
                    project = self.make_project(Path(temporary))
                    (project / relative_path).write_text(
                        "do-not-ship\n", encoding="utf-8"
                    )

                    result = self.run_packager(project, expect_success=False)

                    self.assertEqual(result.returncode, 2)
                    self.assertIn("credential-like", result.stderr)
                    self.assertFalse(
                        (
                            project
                            / "actual-opendesign-project-checkpoint-0.1.0.zip"
                        ).exists()
                    )

    def test_common_credential_filename_allows_exact_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            sensitive = project / "api-token.txt"
            sensitive.write_text("do-not-ship\n", encoding="utf-8")

            self.run_packager(project, "--exclude", "api-token.txt")

            with zipfile.ZipFile(
                project / "actual-opendesign-project-checkpoint-0.1.0.zip"
            ) as archive:
                self.assertNotIn("api-token.txt", archive.namelist())

    def test_bounded_noncredential_filename_words_remain_allowed(self) -> None:
        safe_names = (
            "authorization.txt",
            "secretary.txt",
            "tokenizer.txt",
            "design-tokens.json",
            "authentication-flow.txt",
            "OAuthFlow.md",
            "OAuthClient.ts",
            "GitHubOAuthCallback.html",
            "AuthClient.ts",
            "auth.js",
            "TokenStore.ts",
            "CredentialForm.tsx",
            "PasswordField.vue",
            "SecretEditor.py",
            "serviceAccount.ts",
            "ApiKeyInput.tsx",
            "AccessKeyIcon.svg",
            "DesignToken.ts",
            "SecretIcon.svg",
            "PasswordField.svg",
            "auth-screen.html",
            "PasswordField.md",
            "SecretEditor.md",
            "AuthFlow.md",
            "api-token-guide.md",
            "PrivateKeyParser.ts",
            "SigningKeyIcon.svg",
            "private-key-guide.md",
            "signing-key-help.rst",
            "PrivateKeyField.md",
            "private-key-screen.html",
            "ＰａｓｓｗｏｒｄＳｕｍｍａｒｙ.md",
            "api-token-guide.md.backup-copy",
            "PasswordField.md.backup_copy",
        )
        for name in safe_names:
            with self.subTest(name=name):
                self.assertFalse(PACKAGE.credential_like_path(name))

        packaged_names = tuple(
            name for name in safe_names if not name.casefold().endswith(".html")
        )
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            for name in packaged_names:
                (project / name).write_text("safe design content\n", encoding="utf-8")

            self.run_packager(project)

            with zipfile.ZipFile(
                project / "actual-opendesign-project-checkpoint-0.1.0.zip"
            ) as archive:
                self.assertTrue(set(packaged_names).issubset(archive.namelist()))

    def test_vcs_control_files_and_case_variant_dependencies_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            for path in (project / ".git").iterdir():
                path.unlink()
            (project / ".git").rmdir()
            (project / ".git").write_text("gitdir: ../outside/.git/worktrees/project\n")
            shutil.rmtree(project / "node_modules")
            (project / "NODE_MODULES" / "ignored").mkdir(parents=True)
            (project / "NODE_MODULES" / "ignored" / "dependency.js").write_text(
                "ignored\n", encoding="utf-8"
            )

            self.run_packager(project)

            with zipfile.ZipFile(
                project / "actual-opendesign-project-checkpoint-0.1.0.zip"
            ) as archive:
                names = set(archive.namelist())
                self.assertNotIn(".git", names)
                self.assertNotIn("NODE_MODULES/ignored/dependency.js", names)

    def test_generated_html_url_encodes_reserved_characters_in_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            (project / "mockups" / "comparison#draft.html").write_text(
                "<!doctype html><title>Draft</title>\n", encoding="utf-8"
            )
            (project / "mockups" / "primary%20state.html").write_text(
                "<!doctype html><title>Percent-encoded name</title>\n", encoding="utf-8"
            )

            self.run_packager(
                project,
                "--alternative",
                "mockups/comparison#draft.html",
                "Draft comparison awaiting review",
                "--alternative",
                "mockups/primary%20state.html",
                "Literal percent-encoded filename state",
            )

            with zipfile.ZipFile(
                project / "actual-opendesign-project-checkpoint-0.1.0.zip"
            ) as archive:
                index = archive.read("index.html").decode("utf-8")
                self.assertIn("mockups/comparison%23draft.html", index)
                self.assertIn("mockups/primary%2520state.html", index)

    def test_sha256_is_reported_only_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            result = self.run_packager(project, "--report-sha256")
            rows = [line for line in result.stdout.splitlines() if line.startswith("SHA-256:")]
            self.assertEqual(len(rows), 1)
            self.assertRegex(rows[0], r"^SHA-256: [0-9a-f]{64}$")

    def test_project_name_is_never_inferred_and_slug_collisions_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            missing_name = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(project),
                    "--index",
                    "index.md",
                    "--primary",
                    "notes.md",
                    "Primary research notes",
                    "--change",
                    "Captured the current research",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(missing_name.returncode, 0)
            self.assertIn("--project-name", missing_name.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            self.run_packager(project)
            collision = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(project),
                    "--project-name",
                    "Actual OpenDesign Pröject",
                    "--index",
                    "index.html",
                    "--primary",
                    "mockups/primary.html",
                    "Primary comparison canvas",
                    "--alternative",
                    "mockups/mobile-error.html",
                    "Mobile validation-error state",
                    "--change",
                    "Attempted a colliding identity",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(collision.returncode, 2)
            self.assertIn("slug collision", collision.stderr)

    def test_symlinks_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self.make_project(root)
            outside = root / "outside.txt"
            outside.write_text("outside\n", encoding="utf-8")
            (project / "assets" / "linked.txt").symlink_to(outside)

            result = self.run_packager(project, expect_success=False)

            self.assertEqual(result.returncode, 2)
            self.assertIn("symlinks", result.stderr)
            self.assertFalse(
                (project / "actual-opendesign-project-checkpoint-0.1.0.zip").exists()
            )

    def test_private_zip_validation_happens_before_publication(self) -> None:
        assert PACKAGE is not None
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "primary.html"
            source.write_text("<!doctype html>\n", encoding="utf-8")
            item = PACKAGE.PayloadFile(
                source_root=root,
                absolute_path=source,
                archive_path="primary.html",
                size=source.stat().st_size,
                sha256=PACKAGE.hash_file(source),
                mode=0o644,
            )
            targets = [
                PACKAGE.CheckpointTarget(
                    path="primary.html",
                    label="Primary comparison canvas",
                    primary=True,
                )
            ]
            generated = {
                "index.html": PACKAGE.generated_index_bytes(
                    "index.html", "Project", None, targets
                ),
                "_checkpoint/CHANGELOG.md": b"checkpoint\n",
            }
            destination = root / "project-checkpoint-0.1.0.zip"
            with mock.patch.object(
                PACKAGE,
                "validate_zip",
                side_effect=ValueError("injected private validation failure"),
            ):
                with self.assertRaisesRegex(ValueError, "private validation failure"):
                    PACKAGE.build_zip(
                        destination,
                        [item],
                        generated,
                        "index.html",
                        targets,
                    )
            self.assertFalse(destination.exists())

    def test_existing_index_allows_external_links_when_local_targets_are_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary))
            (project / "index.html").write_text(
                "<!doctype html>"
                "<a href='https://example.test/reference'>External reference</a>"
                "<a href='mockups/primary.html'>Primary comparison canvas</a>"
                "<a href='mockups/mobile-error.html'>Mobile validation-error state</a>\n",
                encoding="utf-8",
            )

            self.run_packager(project)

            self.assertTrue(
                (project / "actual-opendesign-project-checkpoint-0.1.0.zip").is_file()
            )

    def test_manifest_declares_plugin_local_skill_runtime_binding(self) -> None:
        manifest = json.loads((SKILL_DIR / "open-design.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "package-design-checkpoint")
        self.assertEqual(manifest["version"], "0.1.0")
        self.assertEqual(manifest["compat"]["agentSkills"], [{"path": "./SKILL.md"}])
        self.assertEqual(manifest["od"]["context"]["skills"], [{"path": "./SKILL.md"}])
        self.assertEqual(manifest["od"]["capabilities"], ["prompt:inject"])

    def test_docs_define_checkpoint_boundary_and_plugin_picker_invocation(self) -> None:
        readme = (SKILL_DIR / "README.md").read_text(encoding="utf-8")
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("in-progress review or resumption", readme)
        self.assertIn("accepted, complete, implementation-ready", readme)
        self.assertIn("**+ → Plugins**", readme)
        self.assertIn("does not attach it", readme)
        self.assertIn("not a literal Open Design slash command", skill)
        self.assertIn("package-design-handoff", skill)
        self.assertIn("Do not generate `_handoff/` metadata", skill)


if __name__ == "__main__":
    unittest.main()
