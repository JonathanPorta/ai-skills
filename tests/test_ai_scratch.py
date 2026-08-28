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
import sys
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
            self.assertRegex(record, r"^candidate\t[0-9a-f]+\t[0-9]+:[0-9]+:[0-9]+(\.[0-9]+)?\t[0-9]+$")

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

    def _apply_while_holding(self, hold: str):
        """Run apply while a child process holds `hold` open inside a candidate.

        The child is started BEFORE the dry run and held across the whole apply,
        so no timing window has to be hit: the descriptor is live for the entire
        removal transition.
        """
        cand = self.root / "busy"
        cand.mkdir()
        (cand / "work").write_text("original\n")
        (self.root / "idle").mkdir()
        backdate(self.root)

        if hold == "fd":
            code = ("import sys,time\n"
                    "f=open(sys.argv[1],'a')\n"
                    "sys.stdout.write('ready\\n');sys.stdout.flush()\n"
                    "sys.stdin.readline()\n"
                    "f.write('appended after staging\\n');f.close()\n")
            arg = str(cand / "work")
        else:
            code = ("import sys,os\n"
                    "os.chdir(sys.argv[1])\n"
                    "sys.stdout.write('ready\\n');sys.stdout.flush()\n"
                    "sys.stdin.readline()\n")
            arg = str(cand)

        child = subprocess.Popen([sys.executable, "-c", code, arg],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            manifest = self.manifest_from_dry_run()
            result = self.sweep("--apply", "--manifest", manifest)
        finally:
            child.stdin.write("go\n")
            child.stdin.close()
            child.wait(timeout=30)
            child.stdout.close()
        return cand, result

    def test_a_held_descriptor_prevents_removal_and_its_write_survives(self):
        cand, result = self._apply_while_holding("fd")

        self.assertTrue(cand.exists(), "a candidate held open was deleted")
        self.assertIn("appended after staging", (cand / "work").read_text(),
                      "a write made through a held descriptor was lost")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("INCOMPLETE", result.stdout)

    def test_a_shell_parked_inside_a_candidate_prevents_removal(self):
        cand, result = self._apply_while_holding("cwd")

        self.assertTrue(cand.exists(),
                        "a candidate someone was sitting in was deleted")
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_an_idle_candidate_is_still_removed_while_another_is_held(self):
        """The writer scan must not false-positive on unrelated candidates."""
        cand, _ = self._apply_while_holding("fd")

        self.assertTrue(cand.exists())
        self.assertFalse((self.root / "idle").exists(),
                         "an idle candidate was spared by an unrelated holder")

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


class TestReportingDoesNotDisturbWhatItReports(ScratchFixture):
    """A dry run reports on the workspace. It must not become part of it.

    `git status` refreshes the index stat cache and writes it back, so merely
    inspecting a repository re-dates .git and .git/index. Those are inside the
    entry, so the entry then looks like active work and the next run keeps it.
    On a real workspace one dry run re-dated 1217 of 1551 repositories and took
    the reclaimable set from 816 entries to 99.
    """

    def _snapshot(self) -> dict:
        snap = {}
        for path in [self.root, *self.root.rglob("*")]:
            try:
                snap[str(path)] = path.lstat().st_mtime_ns
            except OSError:
                pass
        return snap

    def _reclaimable(self, stdout: str) -> set:
        return {ln.split()[1] for ln in stdout.splitlines()
                if ln.startswith("  FREE  ")}

    def _pushed_repo(self, name: str):
        """A repo that is clean and fully pushed, so it IS reclaimable."""
        remote = self.tmp / f"{name}.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        repo = self.root / name
        new_repo(repo)
        git(repo, "remote", "add", "origin", str(remote))
        git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")
        git(repo, "fetch", "-q", "origin")
        return repo

    def test_a_dry_run_leaves_every_mtime_alone(self):
        self._pushed_repo("pushed")
        dirty = self.root / "dirty"
        new_repo(dirty)
        (dirty / "f").write_text("uncommitted\n")
        backdate(self.root)

        before = self._snapshot()
        self.sweep()
        after = self._snapshot()

        changed = sorted(k for k, v in before.items() if after.get(k) != v)
        self.assertEqual(changed, [], f"a dry run modified {len(changed)} path(s): {changed[:4]}")

    def test_two_dry_runs_in_a_row_agree(self):
        """The property an operator actually depends on: the proposal is stable
        long enough to read it and approve it."""
        self._pushed_repo("pushed")
        (self.root / "plain").mkdir()
        backdate(self.root)

        first = self._reclaimable(self.sweep().stdout)
        self.assertIn("pushed", first,
                      "precondition: a clean pushed repo should be reclaimable")

        second = self._reclaimable(self.sweep().stdout)
        self.assertEqual(first, second,
                         "the second dry run disagreed with the first, so the "
                         "manifest from the first could never be applied")


class TestGitMetadataIsNotUserActivity(ScratchFixture):
    """Repository housekeeping must not read as someone doing work.

    An index refresh re-dates .git while nothing of value was created. But most
    of what lives under .git IS worth keeping and is invisible to the other
    guards, so only two caches are ignored: the .git entry's own mtime and the
    index. A hand-written hook and a reflog-only commit must survive.
    """

    def _pushed_repo(self, name: str):
        remote = self.tmp / f"{name}.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        repo = self.root / name
        new_repo(repo)
        git(repo, "remote", "add", "origin", str(remote))
        git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")
        git(repo, "fetch", "-q", "origin")
        return repo

    def _reclaimable(self) -> set:
        return {ln.split()[1] for ln in self.sweep().stdout.splitlines()
                if ln.startswith("  FREE  ")}

    def _kept_reason(self, name: str) -> str:
        for ln in self.sweep("--verbose").stdout.splitlines():
            if ln.startswith("  KEEP  ") and ln.split()[1] == name:
                return ln.split("  ")[-1].strip()
        return ""

    def test_a_touched_git_directory_does_not_pin_a_clean_repo(self):
        repo = self._pushed_repo("housekeeping")
        backdate(self.root)
        # Exactly what `git fetch` or an index refresh leaves behind.
        for p in (repo / ".git", repo / ".git" / "index"):
            os.utime(p, None)

        self.assertIn("housekeeping", self._reclaimable(),
                      "git metadata alone pinned an otherwise idle clean repo")

    def test_a_touched_git_file_does_not_pin_a_linked_worktree(self):
        parent = self.tmp / "parent"
        new_repo(parent)
        git(parent, "worktree", "add", "-q", str(self.root / "linked"), "-b", "wtb")
        backdate(self.root)
        os.utime(self.root / "linked" / ".git", None)

        # It is kept for having unpushed work, never for the .git file's date.
        self.assertNotIn("active within", self._kept_reason("linked"))

    def test_what_the_dry_run_approves_is_what_apply_removes(self):
        """The classifier and the post-stage recheck must agree about idleness.

        They were separate copies of the same find. When only the classifier
        learned to ignore git metadata, apply refused 767 of the 949 entries it
        had itself just approved, reporting every one as written to after
        staging. Classification alone is not evidence the entry is removable.
        """
        repo = self._pushed_repo("housekeeping")
        backdate(self.root)
        for p in (repo / ".git", repo / ".git" / "index"):
            os.utime(p, None)

        manifest = self.manifest_from_dry_run()
        result = self.sweep("--apply", "--manifest", manifest)

        self.assertNotIn("written to after staging", result.stdout,
                         "the post-stage recheck disagreed with the classifier")
        self.assertFalse(repo.exists(), "apply refused what the dry run approved")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_a_local_hook_is_not_disposable(self):
        """A hook is user-authored, lives only in this clone, and neither
        `git status` nor `rev-list --not --remotes` can see it."""
        repo = self._pushed_repo("hooked")
        (self.root / "decoy").mkdir()   # so the dry run has something to offer
        backdate(self.root)
        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 0\n")

        manifest = self.manifest_from_dry_run()
        self.sweep("--apply", "--manifest", manifest)
        self.assertFalse((self.root / "decoy").exists(), "the decoy proves apply ran")
        self.assertTrue(hook.exists(), "a hand-written git hook was deleted")

    def test_a_commit_recoverable_only_through_the_reflog_is_not_disposable(self):
        """Reset away from every ref, so `rev-list --all --not --remotes` cannot
        see it. It survives only in .git/logs, and it is still recoverable."""
        repo = self._pushed_repo("reflog-only")
        git(repo, "commit", "-q", "--allow-empty", "-m", "reachable from nothing")
        git(repo, "reset", "-q", "--hard", "HEAD~1")
        (self.root / "decoy").mkdir()   # so the dry run has something to offer
        backdate(self.root)
        os.utime(repo / ".git" / "logs" / "HEAD", None)

        manifest = self.manifest_from_dry_run()
        self.sweep("--apply", "--manifest", manifest)
        self.assertFalse((self.root / "decoy").exists(), "the decoy proves apply ran")
        self.assertTrue(repo.exists(),
                        "a commit recoverable only through the reflog was deleted")

    def test_git_local_state_created_after_approval_is_not_deleted(self):
        """Git-local state created after approval must survive.

        The guard that fires here is the manifest, not the idle rule: each entry
        is recorded with its size, so a hook written after approval changes it
        and apply refuses the whole set rather than deleting something other
        than what was reviewed. Worth pinning precisely because it holds even
        when the idle rule is wrong -- it is the backstop, not the argument.
        """
        repo = self._pushed_repo("late-hook")
        backdate(self.root)
        manifest = self.manifest_from_dry_run()

        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 0\n")

        result = self.sweep("--apply", "--manifest", manifest)
        self.assertTrue(hook.exists(),
                        "state created after approval was deleted anyway")
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_an_index_write_during_the_removal_transition_is_not_lost(self):
        """The index is exempt from the AGE test, and must not be exempt from
        the CHANGE test.

        A writer that mutates the index after the final classification and then
        closes leaves nothing for the other guards to find: no descriptor to
        enumerate, and no recent file the idle rule is willing to look at. The
        writer here runs for the whole apply, so the mutation is guaranteed to
        land inside the removal window rather than depending on a race being
        won.
        """
        repo = self._pushed_repo("staged-write")
        backdate(self.root)
        manifest = self.manifest_from_dry_run()

        # The writer follows the entry INTO staging rather than touching the
        # path it was moved off, which is what made an earlier version of this
        # test pass only when it happened to win a race before the rename.
        stop = self.tmp / "stop"
        writer = subprocess.Popen(
            ["sh", "-c",
             f'while [ ! -f "{stop}" ]; do '
             f'for i in "{self.root}"/.scratch-sweep-*/*/.git/index; do '
             f'[ -f "$i" ] && touch "$i"; done; done'])
        try:
            result = self.sweep("--apply", "--manifest", manifest)
        finally:
            stop.write_text("")
            writer.wait(timeout=30)

        self.assertTrue(repo.exists(),
                        "an index mutation during the removal window was deleted")
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def _apply_with_writer(self, shell_body: str, name: str):
        """Run apply while a writer mutates the entry inside staging.

        The writer follows the entry into the quarantine directory rather than
        touching the path it was moved off, and runs for the whole apply, so the
        mutation lands inside the removal window by construction.
        """
        repo = self._pushed_repo(name)
        (repo / "script.sh").write_text("#!/bin/sh\necho hi\n")
        (repo / "script.sh").chmod(0o644)
        git(repo, "add", "script.sh")
        git(repo, "commit", "-qm", "add script")
        git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")
        git(repo, "fetch", "-q", "origin")
        backdate(self.root)
        manifest = self.manifest_from_dry_run()

        stop = self.tmp / "stop"
        writer = subprocess.Popen(
            ["sh", "-c",
             f'while [ ! -f "{stop}" ]; do '
             f'for d in "{self.root}"/.scratch-sweep-*/*; do {shell_body}; done; done'])
        try:
            result = self.sweep("--apply", "--manifest", manifest)
        finally:
            stop.write_text("")
            writer.wait(timeout=30)
        return repo, result

    def test_a_post_staging_mode_change_is_not_lost(self):
        """chmod moves mode and ctime but NOT mtime, so an mtime comparison
        called a permission change no change at all and deleted it."""
        repo, result = self._apply_with_writer(
            '[ -f "$d/script.sh" ] && chmod +x "$d/script.sh" 2>/dev/null', "moded")

        self.assertTrue(repo.exists(),
                        "a permission change during the removal window was deleted")
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_a_recent_working_tree_edit_still_pins_the_entry(self):
        repo = self._pushed_repo("edited")
        backdate(self.root)
        (repo / "f").write_text("someone is working here\n")

        self.assertNotIn("edited", self._reclaimable(),
                         "a real edit no longer counts as activity")

    def test_a_commit_that_is_not_on_a_remote_is_still_kept(self):
        """The safety-critical case: committing writes ONLY to .git, which this
        change stops treating as activity. The unpushed guard must still hold."""
        repo = self._pushed_repo("committed")
        git(repo, "commit", "-q", "--allow-empty", "-m", "exists only here")
        backdate(self.root)   # old, so only the unpushed guard can save it

        self.assertNotIn("committed", self._reclaimable(),
                         "a commit that exists nowhere else became reclaimable")
        self.assertIn("unpushed", self._kept_reason("committed"))


if __name__ == "__main__":
    unittest.main()
