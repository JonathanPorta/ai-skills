"""Behavioural tests for the ai-scratch skill's destructive boundary.

Every case here corresponds to a way the first implementation could destroy work:
a filename that split a delete list, a keep guard that could not see nested
activity, an apply that re-derived its own candidate set. They run the real
scripts against disposable fixtures.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "ai-scratch" / "scripts"
SWEEP = SCRIPTS / "scratch-sweep.sh"
SETUP = SCRIPTS / "scratch-setup.sh"
OLD = "202601010000"


def run(script: Path, *args: str, env_extra: dict | None = None, timeout: int = 60):
    env = dict(os.environ)
    env.setdefault("AI_SCRATCH_CONFIG_DIR", tempfile.mkdtemp(prefix="scratch-cfg-"))
    env.pop("AI_SCRATCH_ROOT", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True, text=True, timeout=timeout, env=env,
    )


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def new_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", ".")
    git(path, "config", "user.email", "t@example.invalid")
    git(path, "config", "user.name", "Test")
    (path / "f").write_text("a\n")
    git(path, "add", "f")
    git(path, "commit", "-qm", "init")


def backdate(root: Path) -> None:
    subprocess.run(["find", str(root), "-exec", "touch", "-t", OLD, "{}", ";"],
                   capture_output=True)


class ScratchFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="scratch-test-"))
        # Two levels deep so the root passes the component-count safety rule.
        self.root = self.tmp / "a" / "b" / "root"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sweep(self, *args: str):
        return run(SWEEP, "--root", str(self.root), *args)

    def manifest_from_dry_run(self) -> str:
        out = self.sweep().stdout
        match = re.search(r"--manifest (\S+)", out)
        self.assertIsNotNone(match, f"dry run offered no manifest:\n{out}")
        return match.group(1)


class TestFilenameSafety(ScratchFixture):
    """A legal filename must never redirect or split a deletion."""

    def test_protected_entry_survives_newline_named_sibling(self):
        # The original bug: a child literally named ".prrq\n+0" split the
        # newline-delimited delete list, and apply removed the real .prrq.
        (self.root / ".prrq").mkdir()
        (self.root / ".prrq" / "queue.json").write_text("{}")
        (self.root / ".prrq\n+0").mkdir()
        (self.root / "reclaimable").mkdir()
        backdate(self.root)

        manifest = self.manifest_from_dry_run()
        self.sweep("--apply", "--manifest", manifest)

        self.assertTrue((self.root / ".prrq" / "queue.json").exists(),
                        "the protected queue directory was destroyed")

    def test_awkward_names_are_each_represented_once(self):
        for name in ["tab\tname", "glob*name", "space name", "..prefix", "plain"]:
            (self.root / name).mkdir()
        backdate(self.root)

        out = self.sweep().stdout
        # Hidden entries are kept; the rest are offered exactly once each.
        self.assertIn("tab\\x09name", out)   # rendered inert, not raw
        self.assertIn("glob*name", out)
        self.assertIn("space name", out)
        self.assertEqual(out.count("FREE  plain"), 1)

    def test_hidden_entries_are_always_kept(self):
        (self.root / ".pnpm-store").mkdir()
        (self.root / ".some-tool-claim").write_text("x")
        backdate(self.root)

        out = self.sweep("--verbose").stdout
        self.assertNotIn("FREE  .pnpm-store", out)
        self.assertNotIn("FREE  .some-tool-claim", out)


class TestKeepGuards(ScratchFixture):
    """Work that exists only in scratch must never be classified reclaimable."""

    def test_recent_edit_deep_inside_an_old_directory(self):
        deep = self.root / "old-tree" / "deep"
        deep.mkdir(parents=True)
        (deep / "f").write_text("old\n")
        backdate(self.root)
        (deep / "f").write_text("edited just now\n")

        self.assertIn("active within", self.sweep("--verbose").stdout)
        self.assertNotIn("FREE  old-tree", self.sweep().stdout)

    def test_dirty_linked_worktree_where_dot_git_is_a_file(self):
        parent = self.root / "wt-parent"
        new_repo(parent)
        git(parent, "worktree", "add", "-q", str(self.root / "linked"), "-b", "wtb")
        backdate(self.root)
        (self.root / "linked" / "f").write_text("dirty\n")

        out = self.sweep("--verbose").stdout
        self.assertNotIn("FREE  linked", out)

    def test_detached_head_commit_reachable_from_no_branch(self):
        remote = self.tmp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        repo = self.root / "detached"
        new_repo(repo)
        git(repo, "remote", "add", "origin", str(remote))
        git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")
        git(repo, "checkout", "-q", "--detach")
        git(repo, "commit", "-q", "--allow-empty", "-m", "exists only here")
        backdate(self.root)

        self.assertIn("unpushed commits", self.sweep("--verbose").stdout)

    def test_repository_nested_below_the_candidate(self):
        inner = self.root / "outer" / "inner"
        new_repo(inner)
        backdate(self.root)

        out = self.sweep("--verbose").stdout
        self.assertNotIn("FREE  outer", out)

    def test_fully_pushed_clone_is_still_reclaimable(self):
        # The guards must not degenerate into keeping everything.
        remote = self.tmp / "remote2.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        repo = self.root / "pushed"
        new_repo(repo)
        git(repo, "remote", "add", "origin", str(remote))
        git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")
        backdate(self.root)

        self.assertIn("FREE  pushed", self.sweep().stdout)


class TestApplyIsBoundToApproval(ScratchFixture):
    """Apply may only remove the exact set a human reviewed."""

    def setUp(self) -> None:
        super().setUp()
        (self.root / "old-one").mkdir()
        (self.root / "old-two").mkdir()
        backdate(self.root)

    def test_apply_requires_a_manifest(self):
        result = self.sweep("--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires --manifest", result.stderr)

    def test_candidate_added_after_approval_aborts_everything(self):
        manifest = self.manifest_from_dry_run()
        (self.root / "snuck-in").mkdir()
        subprocess.run(["touch", "-t", OLD, str(self.root / "snuck-in")], capture_output=True)

        result = self.sweep("--apply", "--manifest", manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changed since the dry run", result.stderr)
        self.assertTrue((self.root / "snuck-in").exists())
        self.assertTrue((self.root / "old-one").exists())

    def test_tampered_manifest_is_refused(self):
        manifest = Path(self.manifest_from_dry_run())
        manifest.write_text(manifest.read_text().replace("idle\t7", "idle\t999"))

        result = self.sweep("--apply", "--manifest", str(manifest))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum mismatch", result.stderr)

    def test_same_path_replacement_is_not_deleted(self):
        manifest = self.manifest_from_dry_run()
        shutil.rmtree(self.root / "old-two")
        (self.root / "old-two").mkdir()
        (self.root / "old-two" / "important").write_text("new work\n")
        backdate(self.root)

        self.sweep("--apply", "--manifest", manifest)
        self.assertTrue((self.root / "old-two" / "important").exists(),
                        "a directory replaced after approval was deleted")

    def test_approved_set_is_removed_on_a_clean_apply(self):
        manifest = self.manifest_from_dry_run()
        result = self.sweep("--apply", "--manifest", manifest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "old-one").exists())
        self.assertFalse((self.root / "old-two").exists())


class TestRootIdentityAndOptions(ScratchFixture):
    """One definition of a safe root, and no option that can hang."""

    def test_relative_root_is_rejected(self):
        result = run(SETUP, "--set", "foo/bar/baz")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("absolute path", result.stderr)

    def test_canonical_form_is_persisted_not_the_input(self):
        cfg_dir = tempfile.mkdtemp(prefix="scratch-cfg-")
        target = self.tmp / "link-target"
        target.mkdir()
        link = self.tmp / "via-link"
        link.symlink_to(target)

        run(SETUP, "--set", str(link / "inner"), env_extra={"AI_SCRATCH_CONFIG_DIR": cfg_dir})
        stored = (Path(cfg_dir) / "config").read_text()
        self.assertIn("link-target", stored,
                      "config kept the symlinked path instead of the physical one")

    def test_unsafe_roots_are_refused_by_both_scripts(self):
        for unsafe in ["/", os.path.expanduser("~"), "/tmp"]:
            with self.subTest(root=unsafe):
                self.assertNotEqual(run(SETUP, "--set", unsafe).returncode, 0)
                self.assertNotEqual(run(SWEEP, "--root", unsafe).returncode, 0)

    def test_missing_option_values_exit_instead_of_looping(self):
        for script, flag in [
            (SETUP, "--set"), (SETUP, "--root"), (SETUP, "--idle-days"), (SETUP, "--protect"),
            (SWEEP, "--root"), (SWEEP, "--older-than"), (SWEEP, "--manifest"),
        ]:
            with self.subTest(script=script.name, flag=flag):
                result = run(script, flag, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("requires a value", result.stderr)

    def test_dry_run_is_the_default_and_deletes_nothing(self):
        (self.root / "old").mkdir()
        backdate(self.root)
        for args in ([], ["--dry-run"], ["-n"]):
            with self.subTest(args=args):
                self.sweep(*args)
                self.assertTrue((self.root / "old").exists())


class TestFailClosedDiscovery(ScratchFixture):
    """Round two: discovery and Git failures must not fail open."""

    def test_repository_deeper_than_any_fixed_search_cap(self):
        deep = self.root / "deep" / "1" / "2" / "3" / "4" / "5" / "6" / "7" / "repo"
        new_repo(deep)
        backdate(self.root)
        self.assertNotIn("FREE  deep", self.sweep().stdout)

    def test_repository_with_a_corrupt_index_is_kept(self):
        # git status exits 128 with EMPTY stdout here. Testing only the output
        # reads that as "clean" and deletes work nobody can see.
        remote = self.tmp / "rem.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        repo = self.root / "corrupt"
        new_repo(repo)
        git(repo, "remote", "add", "origin", str(remote))
        git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")
        (repo / ".git" / "index").write_text("garbage")
        backdate(self.root)

        out = self.sweep("--verbose").stdout
        self.assertNotIn("FREE  corrupt", out)
        self.assertIn("fail closed", out)

    def test_bare_repository_is_kept(self):
        subprocess.run(["git", "init", "-q", "--bare", str(self.root / "bare")], check=True)
        backdate(self.root)
        self.assertNotIn("FREE  bare", self.sweep().stdout)

    def test_protected_name_containing_a_space_is_honoured(self):
        cfg = tempfile.mkdtemp(prefix="scratch-cfg-")
        (self.root / "space name").mkdir()
        backdate(self.root)
        run(SETUP, "--protect", "space name", env_extra={"AI_SCRATCH_CONFIG_DIR": cfg})

        out = run(SWEEP, "--root", str(self.root), "--verbose",
                  env_extra={"AI_SCRATCH_CONFIG_DIR": cfg}).stdout
        self.assertIn("pinned by", out)
        self.assertNotIn("FREE  space name", out)


class TestReviewSurfaceIntegrity(ScratchFixture):
    """The operator must be able to trust what the proposal shows."""

    def test_hostile_names_cannot_forge_or_inflate_the_proposal(self):
        (self.root / "forged\nFREE  fake-entry").mkdir()
        (self.root / "esc\x1b[31mred").mkdir()
        (self.root / "normal").mkdir()
        backdate(self.root)

        out = self.sweep().stdout
        lines = [ln for ln in out.splitlines() if ln.startswith("  FREE  ")]
        self.assertEqual(len(lines), 3, "a name forged an extra proposal line")
        self.assertIn("reclaim       3", out)
        self.assertNotIn("\x1b[31m", out, "an escape sequence reached the terminal raw")

    def test_manifest_records_are_structurally_exact(self):
        (self.root / "weird\nname").mkdir()
        (self.root / "plain").mkdir()
        backdate(self.root)

        manifest = Path(self.manifest_from_dry_run()).read_text()
        records = [ln for ln in manifest.splitlines() if ln.startswith("candidate\t")]
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertRegex(record, r"^candidate\t[0-9a-f]+\t[0-9]+:[0-9]+\t[0-9]+$")

    def test_malformed_manifest_record_is_refused(self):
        (self.root / "old").mkdir()
        backdate(self.root)
        manifest = Path(self.manifest_from_dry_run())
        manifest.write_text(manifest.read_text() + "candidate\tnothex\tbad\tx\n")

        result = self.sweep("--apply", "--manifest", str(manifest))
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.root / "old").exists())


class TestObjectIdentity(unittest.TestCase):
    """Inode identity must distinguish objects on this platform."""

    def test_two_files_have_different_identities(self):
        lib = SCRIPTS / "lib-scratch.sh"
        with tempfile.NamedTemporaryFile() as a, tempfile.NamedTemporaryFile() as b:
            script = f'. "{lib}"; printf "%s %s" "$(scratch_devino {a.name})" "$(scratch_devino {b.name})"'
            out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout
            first, second = out.split()
            self.assertNotEqual(first, second,
                                "stat reported filesystem identity, not object identity")


class TestPortabilityAndFraming(ScratchFixture):
    """Round three: the failures that only appeared on Linux, or under
    filenames that shell tooling cannot frame."""

    def test_repository_below_a_newline_bearing_path_is_found(self):
        deep = self.root / "weird\npath" / "repo"
        new_repo(deep)
        backdate(self.root)
        out = self.sweep("--verbose").stdout
        self.assertIn("unpushed commits", out)
        self.assertNotIn("FREE  weird", out)

    def test_distinct_names_do_not_render_identically(self):
        (self.root / "a\nbc").mkdir()
        (self.root / "ab\nc").mkdir()
        backdate(self.root)
        out = self.sweep().stdout
        self.assertIn("a\\x0abc", out)
        self.assertIn("ab\\x0ac", out)

    def test_valid_manifest_is_accepted_and_applied(self):
        # The Linux failure: `grep -E '\t'` reads GNU's \t as a literal "t",
        # so every valid manifest was rejected as malformed.
        (self.root / "idle-a").mkdir()
        (self.root / "idle-b").mkdir()
        backdate(self.root)
        manifest = self.manifest_from_dry_run()
        result = self.sweep("--apply", "--manifest", manifest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "idle-a").exists())

    def test_malformed_record_inside_the_checksummed_body_is_refused(self):
        (self.root / "old").mkdir()
        backdate(self.root)
        manifest = Path(self.manifest_from_dry_run())
        lines = manifest.read_text().splitlines()
        body = [ln for ln in lines if not ln.startswith("sum\t")]
        body.append("candidate\tNOTHEX\tbad\tx")
        tmp = manifest.parent / (manifest.name + ".body")
        tmp.write_text("\n".join(body) + "\n")
        digest = subprocess.run(["shasum", "-a", "256", str(tmp)],
                                capture_output=True, text=True).stdout.split()[0]
        manifest.write_text("\n".join(body) + f"\nsum\t{digest}\n")

        result = self.sweep("--apply", "--manifest", str(manifest))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("malformed", result.stderr)
        self.assertTrue((self.root / "old").exists())

    def test_name_with_a_trailing_newline_round_trips(self):
        (self.root / "trailing\n").mkdir()
        (self.root / "other").mkdir()
        backdate(self.root)
        manifest = self.manifest_from_dry_run()
        self.sweep("--apply", "--manifest", manifest)
        self.assertFalse((self.root / "trailing\n").exists(),
                         "a trailing newline was lost, so apply targeted the wrong path")


class TestStagingIsExclusive(ScratchFixture):
    """Staging must never adopt, or destroy, state it did not create."""

    def test_preexisting_hidden_directory_is_not_adopted_or_deleted(self):
        stale = self.root / ".scratch-sweep-quarantine.999" / "precious"
        stale.mkdir(parents=True)
        (stale / "data").write_text("unapproved\n")
        (self.root / "idle").mkdir()
        backdate(self.root)

        manifest = self.manifest_from_dry_run()
        self.sweep("--apply", "--manifest", manifest)

        self.assertTrue((stale / "data").exists(),
                        "cleanup destroyed a pre-existing hidden directory")
        self.assertFalse((self.root / "idle").exists())

    def test_apply_reports_incomplete_and_nonzero_when_an_entry_is_skipped(self):
        (self.root / "one").mkdir()
        (self.root / "two").mkdir()
        backdate(self.root)
        manifest = self.manifest_from_dry_run()
        # Replace one approved object so it must be skipped.
        shutil.rmtree(self.root / "two")
        (self.root / "two").mkdir()
        backdate(self.root)

        result = self.sweep("--apply", "--manifest", manifest)
        # Set drift is detected first; either way nothing may be silently lost.
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.root / "two").exists())


if __name__ == "__main__":
    unittest.main()
