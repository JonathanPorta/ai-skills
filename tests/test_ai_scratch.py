"""Behavioural tests for the ai-scratch skill's destructive boundary.

Every case here corresponds to a way the first implementation could destroy work:
a filename that split a delete list, a keep guard that could not see nested
activity, an apply that re-derived its own candidate set. They run the real
scripts against disposable fixtures.
"""

from __future__ import annotations

import hashlib
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
    if "AI_SCRATCH_CONFIG_DIR" not in env:
        cfg = tempfile.mkdtemp(prefix="scratch-cfg-")
        # Isolate from the operator's real ownership records (default ~/devel/worktrees/.owners).
        (Path(cfg) / "config").write_text(f"AI_SCRATCH_OWNERS = {cfg}/no-owners\n")
        env["AI_SCRATCH_CONFIG_DIR"] = cfg
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
        # Every fixture gets its own config and ownership directory. Nothing is
        # reclaimable without a released record, so tests that expect an entry
        # to be offered call release() for it; the operator's real records
        # (default ~/devel/worktrees/.owners) are never consulted.
        self.owners = self.tmp / "owners"
        self.owners.mkdir()
        self.cfg = tempfile.mkdtemp(prefix="scratch-cfg-")
        self.write_config()
        self.env = {"AI_SCRATCH_CONFIG_DIR": self.cfg}

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfg, ignore_errors=True)

    def write_config(self, extra: str = "") -> None:
        (Path(self.cfg) / "config").write_text(f"AI_SCRATCH_OWNERS = {self.owners}\n{extra}")

    def release(self, *names: str, complete: bool = True, released: bool = True,
                record: str | None = None) -> None:
        """Write a complete + released ownership record for each root entry."""
        for name in names:
            real = os.path.realpath(self.root / name)
            text = record if record is not None else (
                '{\n  "worktree": "%s",\n  "complete": %s,\n  "released": %s\n}\n'
                % (real.replace("\\", "\\\\").replace('"', '\\"'),
                   "true" if complete else "false", "true" if released else "false"))
            (self.owners / f"{abs(hash(name))}.json").write_text(text)

    def sweep(self, *args: str):
        return run(SWEEP, "--root", str(self.root), *args, env_extra=self.env)

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
        self.release("reclaimable")

        manifest = self.manifest_from_dry_run()
        self.sweep("--apply", "--manifest", manifest)

        self.assertTrue((self.root / ".prrq" / "queue.json").exists(),
                        "the protected queue directory was destroyed")

    def test_awkward_names_are_each_represented_once(self):
        for name in ["tab\tname", "glob*name", "space name", "..prefix", "plain"]:
            (self.root / name).mkdir()
        backdate(self.root)
        self.release("glob*name", "space name", "plain")

        out = self.sweep("--verbose").stdout
        # Hidden entries are kept; every name is listed exactly once, rendered
        # inert. (A name with a control character can never carry a release
        # record, so it is kept and shown on a KEEP line.)
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
        self.release("pushed")

        self.assertIn("FREE  pushed", self.sweep().stdout)


class TestApplyIsBoundToApproval(ScratchFixture):
    """Apply may only remove the exact set a human reviewed."""

    def setUp(self) -> None:
        super().setUp()
        (self.root / "old-one").mkdir()
        (self.root / "old-two").mkdir()
        backdate(self.root)
        self.release("old-one", "old-two")

    def test_apply_requires_a_manifest(self):
        result = self.sweep("--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires --manifest", result.stderr)

    def test_candidate_added_after_approval_aborts_everything(self):
        manifest = self.manifest_from_dry_run()
        (self.root / "snuck-in").mkdir()
        subprocess.run(["touch", "-t", OLD, str(self.root / "snuck-in")], capture_output=True)
        self.release("snuck-in")

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

    def test_read_only_tree_is_removed_on_a_clean_apply(self):
        # A Go module cache makes every file and directory read-only, and an
        # entry cannot be unlinked from a read-only directory. rm -rf alone
        # failed partway and left the approved entry staged.
        module = self.root / "old-one" / "go-mod" / "example.com" / "m@v1.0.0"
        module.mkdir(parents=True)
        (module / "m.go").write_text("package m\n")
        backdate(self.root)
        self.addCleanup(subprocess.run, ["chmod", "-R", "u+w", str(self.tmp)],
                        capture_output=True)
        subprocess.run(["chmod", "-R", "a-w", str(self.root / "old-one" / "go-mod")],
                       check=True, capture_output=True)

        manifest = self.manifest_from_dry_run()
        result = self.sweep("--apply", "--manifest", manifest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "old-one").exists())
        self.assertNotIn("staging directory is not empty", result.stderr)


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
        self.release("normal")

        out = self.sweep("--verbose").stdout
        lines = [ln for ln in out.splitlines() if ln.startswith("  FREE  ")]
        self.assertEqual(len(lines), 1, "a name forged an extra proposal line")
        self.assertIn("reclaim       1", out)
        self.assertIn("forged\\x0aFREE  fake-entry", out)
        self.assertNotIn("\x1b[31m", out, "an escape sequence reached the terminal raw")

    def test_manifest_records_are_structurally_exact(self):
        (self.root / "weird\nname").mkdir()
        (self.root / "plain").mkdir()
        (self.root / "space name").mkdir()
        backdate(self.root)
        self.release("plain", "space name")

        manifest = Path(self.manifest_from_dry_run()).read_text()
        records = [ln for ln in manifest.splitlines() if ln.startswith("candidate\t")]
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertRegex(record, r"^candidate\t[0-9a-f]+\t[0-9]+:[0-9]+:[0-9]+(\.[0-9]+)?\t[0-9]+$")

    def test_malformed_manifest_record_is_refused(self):
        (self.root / "old").mkdir()
        backdate(self.root)
        self.release("old")
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
        out = self.sweep("--verbose").stdout
        self.assertIn("a\\x0abc", out)
        self.assertIn("ab\\x0ac", out)

    def test_valid_manifest_is_accepted_and_applied(self):
        # The Linux failure: `grep -E '\t'` reads GNU's \t as a literal "t",
        # so every valid manifest was rejected as malformed.
        (self.root / "idle-a").mkdir()
        (self.root / "idle-b").mkdir()
        backdate(self.root)
        self.release("idle-a", "idle-b")
        manifest = self.manifest_from_dry_run()
        result = self.sweep("--apply", "--manifest", manifest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "idle-a").exists())

    def test_malformed_record_inside_the_checksummed_body_is_refused(self):
        (self.root / "old").mkdir()
        backdate(self.root)
        self.release("old")
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

    def test_name_with_trailing_whitespace_round_trips(self):
        # A name ending in a space survives the hex round trip and the record
        # match; a name ending in a newline can never carry a release record
        # (control characters are refused), so it is kept, never mistargeted.
        (self.root / "trailing ").mkdir()
        (self.root / "trailing\n").mkdir()
        (self.root / "other").mkdir()
        backdate(self.root)
        self.release("trailing ", "other")
        out = self.sweep("--verbose").stdout
        self.assertRegex(out, r"KEEP\s+trailing\\x0a\s.*no ownership record")
        manifest = self.manifest_from_dry_run()
        self.sweep("--apply", "--manifest", manifest)
        self.assertFalse((self.root / "trailing ").exists(),
                         "a trailing space was lost, so apply targeted the wrong path")
        self.assertTrue((self.root / "trailing\n").exists())


class TestStagingIsExclusive(ScratchFixture):
    """Staging must never adopt, or destroy, state it did not create."""

    def test_preexisting_hidden_directory_is_not_adopted_or_deleted(self):
        stale = self.root / ".scratch-sweep-quarantine.999" / "precious"
        stale.mkdir(parents=True)
        (stale / "data").write_text("unapproved\n")
        (self.root / "idle").mkdir()
        backdate(self.root)
        self.release("idle")

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
        self.release("busy", "idle")

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
        self.release("one", "two")
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
        # CI runners may default to "master"; the push below creates "main", so point HEAD there
        # or the clone has nothing to check out.
        git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
        repo = self.root / name
        new_repo(repo)
        git(repo, "remote", "add", "origin", str(remote))
        git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")
        git(repo, "fetch", "-q", "origin")
        self.release(name)
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
        # CI runners may default to "master"; the push below creates "main", so point HEAD there
        # or the clone has nothing to check out.
        git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
        repo = self.root / name
        new_repo(repo)
        git(repo, "remote", "add", "origin", str(remote))
        git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")
        git(repo, "fetch", "-q", "origin")
        self.release(name)
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
        self.release("decoy")
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
        self.release("decoy")
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


class TestTheBoundaryFailsClosed(ScratchFixture):
    """A check that could not RUN is not a check that passed.

    The removal gate marks a window with `touch` and compares against it with
    `find -newercm`. Both were called with their failures discarded, and the
    comparison was judged on its stdout alone -- so a missing reference or an
    unreadable subtree produced no output and was read as "nothing changed",
    which authorized a recursive delete. Every one of these injects a failure
    into exactly one of those four operations and requires the entry to survive.
    """

    def _shim_dir(self, name: str, guard: str) -> str:
        """A PATH shim that fails `name` only when `guard` says so."""
        real = shutil.which(name)
        assert real, f"{name} not found on PATH"
        d = self.tmp / f"shim-{name}-{len(guard)}"
        d.mkdir(exist_ok=True)
        prog = d / name
        prog.write_text(f'#!/bin/sh\n{guard}\nexec {real} "$@"\n')
        prog.chmod(0o755)
        return str(d)

    def _reclaimable_entry(self):
        entry = self.root / "victim"
        entry.mkdir()
        (entry / "data").write_text("the only copy\n")
        backdate(self.root)
        self.release("victim")
        return entry

    def _apply_under_shim(self, shim: str):
        entry = self._reclaimable_entry()
        manifest = self.manifest_from_dry_run()
        result = run(SWEEP, "--root", str(self.root), "--apply", "--manifest", manifest,
                     env_extra={**self.env, "PATH": shim + os.pathsep + os.environ["PATH"]})
        return entry, result

    # -- the two marker writes ------------------------------------------------

    def test_a_failed_child_marker_does_not_authorize_deletion(self):
        shim = self._shim_dir(
            "touch", 'for a in "$@"; do case "$a" in */window) exit 1;; esac; done')
        entry, result = self._apply_under_shim(shim)
        self.assertTrue(entry.exists(), "deleted after the window mark failed")
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_a_failed_root_marker_does_not_authorize_deletion(self):
        shim = self._shim_dir(
            "touch", 'for a in "$@"; do case "$a" in */window-root) exit 1;; esac; done')
        entry, result = self._apply_under_shim(shim)
        self.assertTrue(entry.exists(), "deleted after the root mark failed")
        self.assertNotEqual(result.returncode, 0, result.stdout)

    # -- the two comparisons --------------------------------------------------

    def test_a_failed_child_comparison_does_not_authorize_deletion(self):
        # Keyed on the mark path, not on -mindepth: the startup capability
        # probe also passes -newercm, and failing that would abort before the
        # gate is ever reached, proving nothing about the gate.
        shim = self._shim_dir("find", (
            'for a in "$@"; do case "$a" in */window) exit 1;; esac; done'))
        entry, result = self._apply_under_shim(shim)
        self.assertTrue(entry.exists(), "deleted after the child comparison failed")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("could not verify", result.stdout)

    def test_a_failed_root_comparison_does_not_authorize_deletion(self):
        shim = self._shim_dir("find", (
            'for a in "$@"; do case "$a" in */window-root) exit 1;; esac; done'))
        entry, result = self._apply_under_shim(shim)
        self.assertTrue(entry.exists(), "deleted after the root comparison failed")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("could not verify", result.stdout)

    # -- the control: with nothing failing, it still deletes -------------------

    def test_an_untouched_entry_is_still_removed(self):
        """Guards against closing the hole by refusing everything."""
        entry = self._reclaimable_entry()
        manifest = self.manifest_from_dry_run()
        result = self.sweep("--apply", "--manifest", manifest)
        self.assertFalse(entry.exists(), "the fail-closed path now refuses everything")
        self.assertEqual(result.returncode, 0, result.stdout)




class TestHoldAndDependencyGuards(ScratchFixture):
    """A hold refuses every apply; object lenders and worktree hosts are never reclaimable."""

    def test_hold_refuses_apply_but_dry_run_still_reports(self):
        (self.root / "old-one").mkdir()
        backdate(self.root)
        self.release("old-one")
        manifest = self.manifest_from_dry_run()
        setup = run(SETUP, "--hold", "recovery in progress", env_extra=self.env)
        self.assertEqual(setup.returncode, 0, setup.stderr)
        self.assertIn("HOLD", setup.stdout)

        dry = run(SWEEP, "--root", str(self.root), env_extra=self.env)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn("HOLD ACTIVE: recovery in progress", dry.stdout)
        self.assertIn("FREE", dry.stdout)

        result = run(SWEEP, "--root", str(self.root), "--apply", "--manifest", manifest, env_extra=self.env)
        self.assertEqual(result.returncode, 3)
        self.assertIn("on hold", result.stderr)
        self.assertTrue((self.root / "old-one").exists())

    def test_hold_refuses_apply_even_with_a_bad_manifest_path(self):
        run(SETUP, "--hold", "hold", env_extra=self.env)
        result = run(SWEEP, "--root", str(self.root), "--apply", "--manifest", "/nonexistent", env_extra=self.env)
        self.assertEqual(result.returncode, 3)
        self.assertIn("on hold", result.stderr)

    def test_release_lifts_the_hold(self):
        (self.root / "old-one").mkdir()
        backdate(self.root)
        self.release("old-one")
        run(SETUP, "--hold", "hold", env_extra=self.env)
        released = run(SETUP, "--release", env_extra=self.env)
        self.assertEqual(released.returncode, 0, released.stderr)
        self.assertNotIn("HOLD", released.stdout)
        manifest = re.search(r"--manifest (\S+)", run(SWEEP, "--root", str(self.root), env_extra=self.env).stdout).group(1)
        result = run(SWEEP, "--root", str(self.root), "--apply", "--manifest", manifest, env_extra=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "old-one").exists())

    def _pushed_clone(self, name: str) -> Path:
        remote = self.tmp / f"{name}.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        # CI runners may default to "master"; the push below creates "main", so point HEAD there
        # or the clone has nothing to check out.
        git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
        src = self.tmp / f"{name}-src"
        new_repo(src)
        git(src, "remote", "add", "origin", str(remote))
        git(src, "push", "-q", "origin", "HEAD:main")
        clone = self.root / name
        subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True)
        return clone

    def test_alternates_lender_is_kept_even_when_clean_pushed_and_idle(self):
        lender = self._pushed_clone("lender")
        borrower = self.root / "borrower"
        subprocess.run(["git", "clone", "-q", "--shared", str(lender), str(borrower)], check=True, capture_output=True)
        self.assertTrue((borrower / ".git" / "objects" / "info" / "alternates").exists())
        backdate(self.root)
        out = self.sweep("--verbose").stdout
        self.assertRegex(out, r"KEEP\s+lender\s.*another repository depends on it")
        self.assertNotRegex(out, r"FREE\s+lender\b")

    def test_lender_outside_the_root_does_not_pin_root_entries(self):
        clone = self._pushed_clone("plain")
        backdate(self.root)
        self.release("plain")
        out = self.sweep().stdout
        self.assertRegex(out, r"FREE\s+plain\b")

    def test_primary_hosting_a_linked_worktree_elsewhere_is_kept(self):
        primary = self._pushed_clone("primary")
        outside = self.tmp / "elsewhere-wt"
        git(primary, "worktree", "add", "-q", "--detach", str(outside))
        backdate(self.root)
        out = self.sweep("--verbose").stdout
        self.assertRegex(out, r"KEEP\s+primary\s.*hosts a linked worktree outside itself")

    def test_idle_alone_never_authorizes_deletion(self):
        # Idle for a year, but with an unpushed commit: idle is a filter, the keep rules decide.
        repo = self.root / "idle-but-unpushed"
        new_repo(repo)
        backdate(self.root)
        out = self.sweep("--verbose", "--older-than", "1").stdout
        self.assertRegex(out, r"KEEP\s+idle-but-unpushed\s.*unpushed commits")
        self.assertNotRegex(out, r"FREE\s+idle-but-unpushed\b")


class TestDependencyCoverage(ScratchFixture):
    """Every way one repository can depend on another's objects or metadata keeps the dependency."""

    def pushed(self, where: Path, name: str) -> Path:
        remote = self.tmp / f"{name}.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        # CI runners may default to "master"; the push below creates "main", so point HEAD there
        # or the clone has nothing to check out.
        git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
        src = self.tmp / f"{name}-src"
        new_repo(src)
        git(src, "remote", "add", "origin", str(remote))
        git(src, "push", "-q", "origin", "HEAD:main")
        clone = where / name
        subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True)
        return clone

    def shared(self, lender: Path, where: Path) -> Path:
        subprocess.run(["git", "clone", "-q", "--shared", str(lender), str(where)], check=True, capture_output=True)
        return where

    def sweep_env(self, *args: str):
        return run(SWEEP, "--root", str(self.root), *args, env_extra=self.env)

    def test_nested_borrower_deep_inside_a_root_entry_keeps_the_lender(self):
        lender = self.pushed(self.root, "lender")
        self.shared(lender, self.root / "task" / "sub" / "deeper" / "borrower")
        backdate(self.root)
        out = self.sweep_env("--verbose").stdout
        self.assertRegex(out, r"KEEP\s+lender\s.*another repository depends on it")

    def test_chained_lenders_are_all_kept(self):
        a = self.pushed(self.root, "a")
        b = self.shared(a, self.root / "b")
        self.shared(b, self.root / "c")
        backdate(self.root)
        out = self.sweep_env("--verbose").stdout
        self.assertRegex(out, r"KEEP\s+a\s.*another repository depends on it")
        self.assertRegex(out, r"KEEP\s+b\s.*another repository depends on it")

    def test_relative_alternates_path_is_resolved(self):
        lender = self.pushed(self.root, "lender")
        borrower = self.pushed(self.root, "borrower")
        (borrower / ".git" / "objects" / "info" / "alternates").write_text("../../../lender/.git/objects\n")
        backdate(self.root)
        out = self.sweep_env("--verbose").stdout
        self.assertRegex(out, r"KEEP\s+lender\s.*another repository depends on it")

    def test_alternates_through_a_symlink_resolves_to_the_real_lender(self):
        lender = self.pushed(self.root, "lender")
        link = self.tmp / "link-to-lender"
        link.symlink_to(lender)
        borrower = self.pushed(self.root, "borrower")
        (borrower / ".git" / "objects" / "info" / "alternates").write_text(f"{link}/.git/objects\n")
        backdate(self.root)
        out = self.sweep_env("--verbose").stdout
        self.assertRegex(out, r"KEEP\s+lender\s.*another repository depends on it")

    def test_borrower_outside_the_root_is_seen_only_where_the_scan_is_told_to_look(self):
        lender = self.pushed(self.root, "lender")
        outside = self.tmp / "far" / "away"
        outside.mkdir(parents=True)
        self.shared(lender, outside / "borrower")
        backdate(self.root)
        self.release("lender")
        self.assertRegex(self.sweep_env().stdout, r"FREE\s+lender\b")  # documented limit
        self.write_config(f"AI_SCRATCH_LENDER_SCAN = {outside}\n")
        self.assertRegex(self.sweep_env("--verbose").stdout, r"KEEP\s+lender\s.*another repository depends on it")

    def test_worktree_outside_the_root_keeps_its_primary(self):
        primary = self.pushed(self.root, "primary")
        outside = self.tmp / "wt-home"
        outside.mkdir()
        git(primary, "worktree", "add", "-q", "--detach", str(outside / "wt"))
        backdate(self.root)
        out = self.sweep_env("--verbose").stdout
        self.assertRegex(out, r"KEEP\s+primary\s.*(another repository depends on it|hosts a linked worktree)")

    def test_environment_alternates_keep_the_named_repository(self):
        lender = self.pushed(self.root, "lender")
        backdate(self.root)
        env = dict(self.env, GIT_ALTERNATE_OBJECT_DIRECTORIES=str(lender / ".git" / "objects"))
        out = run(SWEEP, "--root", str(self.root), "--verbose", env_extra=env).stdout
        self.assertRegex(out, r"KEEP\s+lender\s.*another repository depends on it")

    def test_unreadable_alternates_file_keeps_everything_and_refuses_apply(self):
        lender = self.pushed(self.root, "lender")
        borrower = self.shared(lender, self.root / "borrower")
        (self.root / "plain").mkdir()
        backdate(self.root)
        self.release("plain")
        alt = borrower / ".git" / "objects" / "info" / "alternates"
        self.addCleanup(subprocess.run, ["chmod", "u+r", str(alt)], capture_output=True)
        subprocess.run(["chmod", "000", str(alt)], check=True)
        dry = self.sweep_env("--verbose")
        self.assertIn("dependency scan incomplete", dry.stderr)
        self.assertRegex(dry.stdout, r"KEEP\s+plain\s.*dependency scan failed")
        self.assertNotIn("FREE", dry.stdout)
        subprocess.run(["chmod", "u+r", str(alt)], check=True)
        manifest = re.search(r"--manifest (\S+)", self.sweep_env().stdout).group(1)
        subprocess.run(["chmod", "000", str(alt)], check=True)
        result = self.sweep_env("--apply", "--manifest", manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dependency scan failed", result.stderr)
        self.assertTrue((self.root / "plain").exists())

    def test_new_borrower_between_dry_run_and_apply_aborts(self):
        lender = self.pushed(self.root, "lender")
        (self.root / "plain").mkdir()
        backdate(self.root)
        self.release("plain")
        manifest = re.search(r"--manifest (\S+)", self.sweep_env().stdout).group(1)
        self.shared(lender, self.tmp / "late-borrower")
        self.write_config(f"AI_SCRATCH_LENDER_SCAN = {self.tmp / 'late-borrower'}\n")
        result = self.sweep_env("--apply", "--manifest", manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dependency evidence changed", result.stderr)
        self.assertTrue((self.root / "plain").exists())
        self.assertTrue(lender.exists())

    def test_manifest_without_a_dependency_digest_is_refused(self):
        (self.root / "plain").mkdir()
        backdate(self.root)
        self.release("plain")
        manifest = re.search(r"--manifest (\S+)", self.sweep_env().stdout).group(1)
        body = [l for l in Path(manifest).read_text().splitlines() if not l.startswith("deps\t") and not l.startswith("sum\t")]
        tmp = Path(manifest + ".stripped")
        tmp.write_text("\n".join(body) + "\n")
        digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
        tmp.write_text("\n".join(body) + f"\nsum\t{digest}\n")
        result = self.sweep_env("--apply", "--manifest", str(tmp))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no dependency digest", result.stderr)
        self.assertTrue((self.root / "plain").exists())

    def test_unreleased_owner_record_keeps_the_entry(self):
        repo = self.pushed(self.root, "owned")
        backdate(self.root)
        owners = self.owners / "repo"
        owners.mkdir(parents=True)
        real = subprocess.run(["bash", "-c", f'cd "{repo}" && pwd -P'], capture_output=True, text=True).stdout.strip()
        (owners / "owned.json").write_text(f'{{\n"worktree": "{real}",\n"complete": true,\n"released": false\n}}\n')
        self.assertRegex(self.sweep_env("--verbose").stdout, r"KEEP\s+owned\s.*owner record not released")
        (owners / "owned.json").write_text(f'{{\n"worktree": "{real}",\n"complete": true,\n"released": true\n}}\n')
        self.assertRegex(self.sweep_env().stdout, r"FREE\s+owned\b")

    def test_dependents_inside_the_entry_do_not_pin_it(self):
        entry = self.pushed(self.root, "with-internal-deps")
        git(entry, "worktree", "add", "-q", "--detach", str(entry / "inner-wt"))
        lender = self.pushed(entry, "inner-lender")
        self.shared(lender, entry / "inner-borrower")
        git(entry, "add", "-A")  # keep the entry clean for the status rule
        git(entry, "-c", "user.email=t@example.invalid", "-c", "user.name=Test", "commit", "-qm", "inner")
        git(entry, "push", "-q", "origin", "HEAD:main")
        backdate(self.root)
        self.release("with-internal-deps")
        out = self.sweep_env("--verbose").stdout
        self.assertNotRegex(out, r"KEEP\s+with-internal-deps\s.*another repository depends on it")
        self.assertRegex(out, r"FREE\s+with-internal-deps\b")

    def test_sibling_clone_next_to_the_root_is_a_seen_borrower(self):
        lender = self.pushed(self.root, "lender")
        sibling = self.root.parent / "sibling-borrower"      # parent/<repo>/.git/objects/info/alternates
        self.shared(lender, sibling)
        backdate(self.root)
        out = self.sweep_env("--verbose").stdout
        self.assertRegex(out, r"KEEP\s+lender\s.*another repository depends on it")


class TestOwnershipRecords(ScratchFixture):
    """Only a well-formed record that says complete and released can let an entry go.

    Missing, malformed, ambiguous and unreleased records all keep the entry.
    Age, cleanliness and a pushed history say an entry is probably safe; only
    its owner can say it is done with, and the absence of a record is not a
    statement (2026-11-03: ai-usage-16 was reclaimed from under a session that
    still depended on it; no record existed to say so).
    """

    def _pushed(self, name: str) -> Path:
        remote = self.tmp / f"{name}.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
        repo = self.root / name
        new_repo(repo)
        git(repo, "remote", "add", "origin", str(remote))
        git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")
        git(repo, "fetch", "-q", "origin")
        return repo

    def _reason(self, name: str) -> str:
        for ln in self.sweep("--verbose").stdout.splitlines():
            if ln.startswith("  KEEP  ") and ln.split()[1] == name:
                return ln.split("  ")[-1].strip()
        return ""

    def test_an_entry_without_a_record_is_kept_however_clean_idle_and_pushed(self):
        self._pushed("unrecorded")
        (self.root / "plain").mkdir()
        backdate(self.root)
        out = self.sweep("--verbose")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertRegex(out.stdout, r"KEEP\s+unrecorded\s.*no ownership record")
        self.assertRegex(out.stdout, r"KEEP\s+plain\s.*no ownership record")
        self.assertNotIn("FREE", out.stdout)
        self.assertIn("reclaim       0", out.stdout)

    def test_a_complete_released_record_is_the_only_way_to_be_offered(self):
        self._pushed("done")
        backdate(self.root)
        self.release("done")
        self.assertRegex(self.sweep().stdout, r"FREE\s+done\b")

    def test_released_but_not_complete_is_kept(self):
        self._pushed("half")
        backdate(self.root)
        self.release("half", complete=False, released=True)
        self.assertIn("owner record not released", self._reason("half"))

    def test_complete_but_not_released_is_kept(self):
        self._pushed("mine")
        backdate(self.root)
        self.release("mine", complete=True, released=False)
        self.assertIn("owner record not released", self._reason("mine"))

    def test_the_record_must_name_this_exact_entry(self):
        self._pushed("task")
        self._pushed("task-2")
        backdate(self.root)
        self.release("task-2")
        out = self.sweep("--verbose").stdout
        self.assertRegex(out, r"FREE\s+task-2\b")
        self.assertRegex(out, r"KEEP\s+task\s.*no ownership record")

    def test_two_records_for_one_entry_are_ambiguous_and_keep_it(self):
        self._pushed("disputed")
        backdate(self.root)
        self.release("disputed")
        real = os.path.realpath(self.root / "disputed")
        (self.owners / "second.json").write_text(
            '{\n  "worktree": "%s",\n  "owner_session": "someone-else",\n  "complete": true,\n  "released": true\n}\n' % real)
        self.assertIn("ambiguous ownership (2 records)", self._reason("disputed"))

    def test_an_unreleased_record_inside_the_entry_keeps_the_entry(self):
        entry = self._pushed("host")
        backdate(self.root)
        self.release("host")
        inner = os.path.realpath(entry / "sub" / "inner-task")
        (self.owners / "inner.json").write_text(
            '{\n  "worktree": "%s",\n  "complete": false,\n  "released": false\n}\n' % inner)
        self.assertIn("contains an owned worktree not released", self._reason("host"))

    def test_a_malformed_record_keeps_everything_and_refuses_apply(self):
        self._pushed("fine")
        (self.root / "plain").mkdir()
        backdate(self.root)
        self.release("fine", "plain")
        manifest = self.manifest_from_dry_run()
        for text in ('{"worktree": "%s", "released": true}\n' % os.path.realpath(self.root / "fine"),  # one line
                     '{\n  "worktree": "relative/path",\n  "released": true\n}\n',
                     '{\n  "released": true\n}\n',
                     '{\n  "worktree": {"nested": true},\n  "released": true\n}\n',
                     '{\n  "worktree": "%s",\n  "released": true,\n' % os.path.realpath(self.root / "fine"),  # unterminated
                     'not json at all\n',
                     ''):
            with self.subTest(text=text[:30]):
                (self.owners / "broken.json").write_text(text)
                dry = self.sweep("--verbose")
                self.assertIn("ownership records unreadable or malformed", dry.stderr)
                self.assertIn("broken.json", dry.stderr)
                self.assertRegex(dry.stdout, r"KEEP\s+fine\s.*ownership records unreadable")
                self.assertNotIn("FREE", dry.stdout)
                result = self.sweep("--apply", "--manifest", manifest)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ownership records unreadable", result.stderr)
                self.assertTrue((self.root / "fine").exists())
                self.assertTrue((self.root / "plain").exists())
        (self.owners / "broken.json").unlink()
        result = self.sweep("--apply", "--manifest", manifest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "plain").exists())

    def test_an_unreadable_record_file_fails_closed(self):
        (self.root / "plain").mkdir()
        backdate(self.root)
        self.release("plain")
        secret = self.owners / "unreadable.json"
        secret.write_text('{\n  "worktree": "/elsewhere",\n  "released": true\n}\n')
        self.addCleanup(subprocess.run, ["chmod", "u+r", str(secret)], capture_output=True)
        subprocess.run(["chmod", "000", str(secret)], check=True)
        dry = self.sweep("--verbose")
        self.assertIn("unreadable.json", dry.stderr)
        self.assertNotIn("FREE", dry.stdout)

    def test_a_record_withdrawn_between_dry_run_and_apply_aborts(self):
        (self.root / "plain").mkdir()
        (self.root / "other").mkdir()
        backdate(self.root)
        self.release("plain", "other")
        manifest = self.manifest_from_dry_run()
        self.release("plain", released=False)   # the owner takes it back
        result = self.sweep("--apply", "--manifest", manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changed since the dry run", result.stderr)
        self.assertTrue((self.root / "plain").exists())
        self.assertTrue((self.root / "other").exists())

    def test_no_owners_directory_at_all_keeps_everything(self):
        (self.root / "plain").mkdir()
        backdate(self.root)
        shutil.rmtree(self.owners)
        out = self.sweep("--verbose")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertRegex(out.stdout, r"KEEP\s+plain\s.*no ownership record")
        self.assertNotIn("FREE", out.stdout)

    def test_a_record_written_through_a_symlink_matches_the_physical_entry(self):
        (self.root / "plain").mkdir()
        link = self.tmp / "link-to-root"
        link.symlink_to(self.root)
        backdate(self.root)
        (self.owners / "via-link.json").write_text(
            '{\n  "worktree": "%s/",\n  "complete": true,\n  "released": true\n}\n' % (link / "plain"))
        self.assertRegex(self.sweep().stdout, r"FREE\s+plain\b")

    def test_a_tab_in_a_record_path_cannot_release_a_neighbouring_entry(self):
        # The index is tab-delimited; a path carrying a tab must not split into
        # "/root/tab" + "name" and release the entry called "tab".
        (self.root / "tab").mkdir()
        (self.root / "tab\tname").mkdir()
        backdate(self.root)
        real = os.path.realpath(self.root / "tab\tname")
        (self.owners / "tabbed.json").write_text(
            '{\n  "worktree": "%s",\n  "complete": true,\n  "released": true\n}\n' % real)
        dry = self.sweep("--verbose")
        self.assertNotIn("FREE", dry.stdout)
        self.assertIn("malformed", dry.stderr)
        self.assertNotEqual(self.sweep("--apply", "--manifest", "/nonexistent").returncode, 0)
        self.assertTrue((self.root / "tab").exists())

    def test_a_record_through_a_symlink_to_a_newline_named_entry_releases_nothing(self):
        # The typed path is clean; the physical path has a newline. The index
        # must not split on it and release the entry called "a".
        (self.root / "a").mkdir()
        (self.root / "a\nb").mkdir()
        link = self.tmp / "lnk"
        link.symlink_to(self.root / "a\nb")
        backdate(self.root)
        (self.owners / "lnk.json").write_text(
            '{\n  "worktree": "%s",\n  "complete": true,\n  "released": true\n}\n' % link)
        dry = self.sweep("--verbose")
        self.assertNotRegex(dry.stdout, r"FREE\s+a\b")
        self.assertNotIn("FREE", dry.stdout)
        self.assertIn("malformed", dry.stderr)

    def test_an_unreadable_subdirectory_of_records_fails_closed(self):
        # A hidden unreleased record could make the entry ambiguous; an index
        # that could not enumerate everything proves nothing.
        (self.root / "plain").mkdir()
        backdate(self.root)
        self.release("plain")
        sub = self.owners / "sub"
        sub.mkdir()
        (sub / "other.json").write_text('{\n  "worktree": "/elsewhere",\n  "released": true\n}\n')
        self.addCleanup(subprocess.run, ["chmod", "u+rwx", str(sub)], capture_output=True)
        subprocess.run(["chmod", "000", str(sub)], check=True)
        dry = self.sweep("--verbose")
        self.assertNotIn("FREE", dry.stdout)
        self.assertIn("malformed", dry.stderr)
        self.assertNotEqual(self.sweep("--apply", "--manifest", "/nonexistent").returncode, 0)

    def test_an_unreadable_owners_directory_fails_closed(self):
        (self.root / "plain").mkdir()
        backdate(self.root)
        self.release("plain")
        self.addCleanup(subprocess.run, ["chmod", "u+rwx", str(self.owners)], capture_output=True)
        subprocess.run(["chmod", "000", str(self.owners)], check=True)
        dry = self.sweep("--verbose")
        self.assertNotIn("FREE", dry.stdout)
        self.assertRegex(dry.stdout, r"KEEP\s+plain\s.*ownership records unreadable")
        setup = run(SETUP, env_extra=self.env)
        self.assertIn("MALFORMED", setup.stdout)

    def test_symlinked_and_directory_records_are_malformed(self):
        (self.root / "plain").mkdir()
        backdate(self.root)
        self.release("plain")
        target = self.tmp / "real-record.json"
        target.write_text('{\n  "worktree": "/elsewhere",\n  "released": false\n}\n')
        for make in ("symlink", "directory"):
            with self.subTest(kind=make):
                odd = self.owners / "odd.json"
                if make == "symlink":
                    odd.symlink_to(target)
                else:
                    odd.mkdir()
                try:
                    dry = self.sweep("--verbose")
                    self.assertNotIn("FREE", dry.stdout)
                    self.assertIn("odd.json", dry.stderr)
                finally:
                    odd.unlink() if odd.is_symlink() else odd.rmdir()
        self.assertRegex(self.sweep().stdout, r"FREE\s+plain\b")

    def test_record_value_shapes(self):
        self._pushed("shape")
        backdate(self.root)
        real = os.path.realpath(self.root / "shape")
        cases = {
            # released as a STRING is not a boolean true
            '{\n  "worktree": "%s",\n  "complete": true,\n  "released": "true"\n}\n' % real: "owner record not released",
            # duplicate keys are ambiguous within one file
            '{\n  "worktree": "%s",\n  "released": true,\n  "released": false,\n  "complete": true\n}\n' % real: "ownership records unreadable",
            # a control byte inside a value
            '{\n  "worktree": "%s",\n  "note": "x\x01y",\n  "complete": true,\n  "released": true\n}\n' % real: "ownership records unreadable",
            # CRLF line endings parse (the writer never emits them, a hand-written file may)
            '{\r\n  "worktree": "%s",\r\n  "complete": true,\r\n  "released": true\r\n}\r\n' % real: "FREE",
            # a \u escape is refused rather than guessed at
            '{\n  "worktree": "%s\\u0041",\n  "complete": true,\n  "released": true\n}\n' % real: "ownership records unreadable",
        }
        for text, expect in cases.items():
            with self.subTest(text=text[:40]):
                self.release("shape", record=text)
                out = self.sweep("--verbose").stdout
                if expect == "FREE":
                    self.assertRegex(out, r"FREE\s+shape\b")
                else:
                    self.assertRegex(out, r"KEEP\s+shape\s.*" + expect)

    def test_an_ancestor_record_releases_no_child_and_a_released_inner_record_does_not_pin(self):
        entry = self._pushed("outer")
        backdate(self.root)
        # A record for the root itself (or its parent) says nothing about entries inside it.
        (self.owners / "root.json").write_text(
            '{\n  "worktree": "%s",\n  "complete": true,\n  "released": true\n}\n' % os.path.realpath(self.root))
        self.assertRegex(self.sweep("--verbose").stdout, r"KEEP\s+outer\s.*no ownership record")
        (self.owners / "root.json").unlink()
        # A released record for something inside the entry does not keep the entry.
        self.release("outer")
        (self.owners / "inner.json").write_text(
            '{\n  "worktree": "%s",\n  "complete": true,\n  "released": true\n}\n' % os.path.realpath(entry / "sub"))
        self.assertRegex(self.sweep().stdout, r"FREE\s+outer\b")

    def test_tilde_in_the_configured_owners_directory_is_expanded(self):
        (self.root / "plain").mkdir()
        backdate(self.root)
        home = self.tmp / "home"
        owners = home / "records"
        owners.mkdir(parents=True)
        real = os.path.realpath(self.root / "plain")
        (owners / "plain.json").write_text('{\n  "worktree": "%s",\n  "complete": true,\n  "released": true\n}\n' % real)
        (Path(self.cfg) / "config").write_text("AI_SCRATCH_OWNERS = ~/records\n")
        out = run(SWEEP, "--root", str(self.root), env_extra={**self.env, "HOME": str(home)}).stdout
        self.assertRegex(out, r"FREE\s+plain\b")
        self.assertIn(str(owners), run(SETUP, env_extra={**self.env, "HOME": str(home)}).stdout)

    def test_setup_reports_the_ownership_directory(self):
        self.release("plain")
        out = run(SETUP, env_extra=self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(str(self.owners), out.stdout)
        self.assertIn("1 record", out.stdout)


if __name__ == "__main__":
    unittest.main()
