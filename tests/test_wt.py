"""wt.sh: task worktrees that the scratch sweep can trust.

Every case runs against disposable fixtures: a bare remote, a primary checkout
that sits on a human branch, a worktree root, and an ownership directory that
the sweep reads through AI_SCRATCH_OWNERS. The helper must never switch the
primary's branch, never adopt another session's directory, never escape the
worktree root, never delete anything, and must write records in exactly the
shape scratch-sweep.sh consumes.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "ai-scratch" / "scripts"
WT = SCRIPTS / "wt.sh"
SWEEP = SCRIPTS / "scratch-sweep.sh"
OLD = "202601010000"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


class WtFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wt-test-"))
        self.cfg = self.tmp / "cfg"
        self.cfg.mkdir()
        self.owners = self.tmp / "owners"
        (self.cfg / "config").write_text(f"AI_SCRATCH_OWNERS = {self.owners}\n")
        self.primaries = self.tmp / "portaj"
        self.primaries.mkdir()
        self.wt_root = self.tmp / "worktrees" / "portaj"
        self.remote = self.tmp / "demo.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")
        self.primary = self.primaries / "demo"
        self.primary.mkdir()
        git(self.primary, "init", "-q")
        git(self.primary, "config", "user.email", "t@example.invalid")
        git(self.primary, "config", "user.name", "Test")
        (self.primary / "f").write_text("a\n")
        git(self.primary, "add", "f")
        git(self.primary, "commit", "-qm", "init")
        git(self.primary, "remote", "add", "origin", str(self.remote))
        git(self.primary, "push", "-q", "origin", "HEAD:refs/heads/main")
        git(self.primary, "fetch", "-q", "origin")
        git(self.primary, "checkout", "-q", "-b", "human-branch")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wt(self, *args: str, owner: str = "session-A"):
        env = dict(os.environ, AI_SCRATCH_CONFIG_DIR=str(self.cfg), WT_ROOT=str(self.wt_root),
                   WT_PRIMARIES=str(self.primaries), WT_OWNER=owner)
        env.pop("AI_SCRATCH_ROOT", None)
        return subprocess.run(["bash", str(WT), *args], capture_output=True, text=True, env=env, timeout=60)

    def start(self, task: str = "task1", *extra: str, owner: str = "session-A"):
        r = self.wt("start", "demo", task, "--no-fetch", *extra, owner=owner)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        path = re.search(r"^WT_PATH=(.*)$", r.stdout, re.M).group(1)
        return Path(path), r

    def record(self, task: str = "task1") -> str:
        return (self.owners / "demo" / f"{task}.json").read_text()

    def commit_in(self, wt: Path, name: str = "g") -> None:
        (wt / name).write_text("work\n")
        git(wt, "add", name)
        git(wt, "-c", "user.email=t@example.invalid", "-c", "user.name=Test", "commit", "-qm", "work")


class TestStart(WtFixture):
    def test_start_creates_a_registered_worktree_and_leaves_the_primary_branch_alone(self):
        path, r = self.start()
        self.assertEqual(path, (self.wt_root / "demo" / "task1").resolve())
        self.assertTrue((path / ".git").is_file())
        self.assertIn(f"worktree {path}", git(self.primary, "worktree", "list", "--porcelain"))
        self.assertEqual(git(self.primary, "branch", "--show-current"), "human-branch")
        self.assertEqual(git(path, "branch", "--show-current"), "jp/f/task1")
        self.assertIn("WT_RECORD=", r.stdout)
        rec = self.record()
        self.assertIn(f'"worktree": "{path}"', rec)
        self.assertIn('"owner_session": "session-A"', rec)
        self.assertIn('"complete": false', rec)
        self.assertIn('"released": false', rec)

    def test_same_owner_resumes_instead_of_duplicating(self):
        path, _ = self.start()
        r = self.wt("start", "demo", "task1", "--no-fetch")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("resumed demo/task1", r.stdout)
        self.assertEqual(len(re.findall(r"^worktree ", git(self.primary, "worktree", "list", "--porcelain"), re.M)), 2)

    def test_another_session_cannot_resume_or_take_over(self):
        self.start()
        r = self.wt("start", "demo", "task1", "--no-fetch", owner="session-B")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("owned by 'session-A'", r.stderr)
        self.assertIn('"owner_session": "session-A"', self.record())

    def test_a_released_task_name_is_not_reused(self):
        path, _ = self.start()
        self.commit_in(path)
        git(path, "push", "-q", "-u", "origin", "HEAD")
        self.assertEqual(self.wt("finish", "demo", "task1", "--release").returncode, 0)
        r = self.wt("start", "demo", "task1", "--no-fetch")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("released", r.stderr)

    def test_path_escapes_and_odd_names_are_refused(self):
        for bad in ["../x", "a/b", "..", ".", ".git", ".hidden", "-flag", "with space", "nl\nname", "x\\y"]:
            with self.subTest(task=bad):
                r = self.wt("start", "demo", bad, "--no-fetch")
                self.assertNotEqual(r.returncode, 0)
                self.assertFalse((self.wt_root / "demo").exists() and any((self.wt_root / "demo").iterdir()))
        r = self.wt("start", "../demo", "task1", "--no-fetch")
        self.assertNotEqual(r.returncode, 0)

    def test_an_existing_directory_without_a_record_is_not_adopted(self):
        stray = self.wt_root / "demo" / "task1"
        stray.mkdir(parents=True)
        (stray / "someone-elses").write_text("x\n")
        r = self.wt("start", "demo", "task1", "--no-fetch")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("without an ownership record", r.stderr)
        self.assertTrue((stray / "someone-elses").exists())
        self.assertFalse((self.owners / "demo" / "task1.json").exists())

    def test_a_record_that_names_another_path_blocks_the_task_name(self):
        (self.owners / "demo").mkdir(parents=True)
        (self.owners / "demo" / "task1.json").write_text(
            '{\n  "worktree": "/elsewhere/task1",\n  "owner_session": "session-A",\n  "complete": false,\n  "released": false\n}\n')
        r = self.wt("start", "demo", "task1", "--no-fetch")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("different worktree", r.stderr)

    def test_a_malformed_record_is_refused_not_overwritten(self):
        (self.owners / "demo").mkdir(parents=True)
        (self.owners / "demo" / "task1.json").write_text("not json\n")
        r = self.wt("start", "demo", "task1", "--no-fetch")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("malformed", r.stderr)
        self.assertEqual((self.owners / "demo" / "task1.json").read_text(), "not json\n")

    def test_a_borrowing_primary_is_refused(self):
        alt = self.primary / ".git" / "objects" / "info" / "alternates"
        alt.write_text(f"{self.tmp}/somewhere/objects\n")
        r = self.wt("start", "demo", "task1", "--no-fetch")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("borrows objects", r.stderr)

    def test_missing_primary_is_an_error_not_a_clone(self):
        r = self.wt("start", "nope", "task1", "--no-fetch")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.wt_root / "nope").exists() and any((self.wt_root / "nope").iterdir()))

    def test_explicit_branch_and_base(self):
        path, r = self.start("task2", "--branch", "jp/b/custom", "--base", "origin/main")
        self.assertEqual(git(path, "branch", "--show-current"), "jp/b/custom")
        self.assertIn('"base": "origin/main"', self.record("task2"))


class TestListAndFinish(WtFixture):
    def test_list_shows_owner_branch_state_and_blockers(self):
        path, _ = self.start()
        (path / "dirty").write_text("x\n")
        out = self.wt("list").stdout
        self.assertRegex(out, r"demo/task1\s+session-A\s+jp/f/task1\s+.*ACTIVE\s+.*dirty \(1\)")
        out = self.wt("list", "other").stdout
        self.assertNotIn("demo/task1", out)

    def test_finish_records_completion_but_refuses_release_while_work_is_unpreserved(self):
        path, _ = self.start()
        self.commit_in(path)          # on no remote
        r = self.wt("finish", "demo", "task1", "--release")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("NOT released", r.stderr)
        rec = self.record()
        self.assertIn('"complete": true', rec)
        self.assertIn('"released": false', rec)
        self.assertIn('"unpushed_at_finish": 1', rec)
        self.assertTrue(path.exists(), "finish deleted a worktree")

    def test_finish_releases_once_everything_is_on_a_remote_and_prints_a_plan_without_executing_it(self):
        path, _ = self.start()
        self.commit_in(path)
        git(path, "push", "-q", "-u", "origin", "HEAD")
        r = self.wt("finish", "demo", "task1", "--release", "--note", "shipped")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("NOTHING below was executed", r.stdout)
        self.assertIn(f"worktree remove '{path}'", r.stdout)
        for line in r.stdout.splitlines():
            if "worktree remove" in line and not line.startswith("#"):
                self.assertNotIn("--force", line)
        rec = self.record()
        self.assertIn('"released": true', rec)
        self.assertIn('"complete": true', rec)
        self.assertIn('"note": "shipped"', rec)
        self.assertIn('"head_at_finish": "', rec)
        self.assertTrue(path.exists(), "finish deleted a worktree")
        self.assertIn(f"worktree {path}", git(self.primary, "worktree", "list", "--porcelain"))

    def test_finish_by_another_session_is_refused(self):
        self.start()
        r = self.wt("finish", "demo", "task1", "--release", owner="session-B")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("owned by 'session-A'", r.stderr)
        self.assertIn('"complete": false', self.record())

    def test_a_private_reflog_commit_blocks_release(self):
        path, _ = self.start()
        self.commit_in(path)
        git(path, "reset", "-q", "--hard", "origin/main")   # the commit now lives only in the worktree's reflog
        r = self.wt("finish", "demo", "task1", "--release")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("private-reflog", r.stderr)
        self.assertIn('"released": false', self.record())

    def test_a_merged_pr_whose_head_is_this_head_counts_as_preserved(self):
        # After a squash merge the remote branch is gone, so "on no remote" is
        # true, but refs/pull/N/head keeps the commits; a gh shim reports the
        # merged PR head and finish --release must accept it.
        path, _ = self.start()
        self.commit_in(path)
        head = git(path, "rev-parse", "HEAD")
        shim = self.tmp / "shim"
        shim.mkdir()
        (shim / "gh").write_text('#!/bin/sh\necho "$@" >> "%s"\nprintf \'closed merged=true head=%s\\n\'\n' % (self.tmp / "gh-args", head))
        (shim / "gh").chmod(0o755)
        env = dict(os.environ, AI_SCRATCH_CONFIG_DIR=str(self.cfg), WT_ROOT=str(self.wt_root),
                   WT_PRIMARIES=str(self.primaries), WT_OWNER="session-A", PATH=f"{shim}{os.pathsep}{os.environ['PATH']}")
        r = subprocess.run(["bash", str(WT), "finish", "demo", "task1", "--pr", "https://github.com/x/y/pull/7", "--release"],
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        rec = self.record()
        self.assertIn('"released": true', rec)
        self.assertIn('"preserved_by": "HEAD is the merged head of https://github.com/x/y/pull/7', rec)
        self.assertIn('"pr_state": "closed merged=true head=%s"' % head, rec)
        self.assertIn("api repos/x/y/pulls/7 --jq", (self.tmp / "gh-args").read_text())
        self.assertIn("fetch origin \"+refs/pull/7/head:refs/remotes/origin/pull/7/head\"", r.stdout)
        # A different merged head does not count.
        (shim / "gh").write_text('#!/bin/sh\nprintf \'closed merged=true head=0000000\\n\'\n')
        rec_path = self.owners / "demo" / "task1.json"
        rec_path.write_text(rec_path.read_text().replace('"released": true', '"released": false'))   # reset the record
        r = subprocess.run(["bash", str(WT), "finish", "demo", "task1", "--pr", "https://github.com/x/y/pull/7", "--release"],
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("NOT released", r.stderr)

    def test_a_later_finish_that_finds_unpreserved_work_withdraws_the_release(self):
        path, _ = self.start()
        self.commit_in(path)
        git(path, "push", "-q", "-u", "origin", "HEAD")
        self.assertEqual(self.wt("finish", "demo", "task1", "--release").returncode, 0)
        self.assertIn('"released": true', self.record())
        self.commit_in(path, "h")
        git(path, "reset", "-q", "--hard", "origin/jp/f/task1")   # the commit survives only in the private reflog
        r = self.wt("finish", "demo", "task1", "--release")
        self.assertNotEqual(r.returncode, 0)
        rec = self.record()
        self.assertIn('"released": false', rec)
        self.assertIn('"released_at": ""', rec)
        self.assertIn('"private_reflog_unreachable_at_finish": 1', rec)

    def test_a_failing_probe_does_not_destroy_the_record(self):
        path, _ = self.start()
        before = self.record()
        # A dangling remote-tracking ref makes `rev-list --not --remotes` fail.
        (self.primary / ".git" / "refs" / "remotes" / "origin" / "broken").write_text("0" * 40 + "\n")
        r = self.wt("finish", "demo", "task1", "--release")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cannot count", r.stderr)
        self.assertEqual(self.record(), before)
        self.assertEqual(self.wt("list").returncode, 0)

    def test_the_reflog_check_does_not_depend_on_the_record_naming_the_primary(self):
        path, _ = self.start()
        self.commit_in(path)
        git(path, "push", "-q", "-u", "origin", "HEAD")
        self.commit_in(path, "h")
        git(path, "reset", "-q", "--hard", "origin/jp/f/task1")
        rec_path = self.owners / "demo" / "task1.json"
        rec_path.write_text("\n".join(l for l in rec_path.read_text().splitlines() if '"primary"' not in l) + "\n")
        r = self.wt("finish", "demo", "task1", "--release")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("private-reflog", r.stderr)
        self.assertIn('"released": false', self.record())

    def test_a_never_pushed_branch_records_no_upstream(self):
        path, _ = self.start()
        self.commit_in(path)
        r = self.wt("finish", "demo", "task1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"upstream": ""', self.record())
        self.assertIn('"unpushed_at_finish": 1', self.record())

    def test_the_worktree_root_may_not_be_the_primaries_directory(self):
        env = dict(os.environ, AI_SCRATCH_CONFIG_DIR=str(self.cfg), WT_ROOT=str(self.primaries),
                   WT_PRIMARIES=str(self.primaries), WT_OWNER="session-A")
        r = subprocess.run(["bash", str(WT), "start", "demo", "tf", "--no-fetch"], capture_output=True, text=True, env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.primary / "tf").exists())
        self.assertEqual(git(self.primary, "status", "--porcelain"), "")

    def test_a_missing_but_registered_worktree_is_reported_not_recreated(self):
        path, _ = self.start()
        shutil.rmtree(path)
        r = self.wt("start", "demo", "task1", "--no-fetch")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("still registered", r.stderr)
        self.assertIn("worktree remove", r.stderr)
        self.assertFalse(path.exists())

    def test_list_names_a_malformed_record(self):
        (self.owners / "demo").mkdir(parents=True)
        (self.owners / "demo" / "broken.json").write_text("not json\n")
        out = self.wt("list").stdout
        self.assertRegex(out, r"demo/broken\s.*MALFORMED\s+fix .*broken\.json")

    def test_tilde_and_relative_roots_from_config(self):
        home = self.tmp / "home"
        home.mkdir()
        (self.cfg / "config").write_text(f"AI_SCRATCH_OWNERS = {self.owners}\nWT_ROOT = ~/wtroot\n")
        env = dict(os.environ, AI_SCRATCH_CONFIG_DIR=str(self.cfg), WT_PRIMARIES=str(self.primaries),
                   WT_OWNER="session-A", HOME=str(home))
        env.pop("WT_ROOT", None)
        r = subprocess.run(["bash", str(WT), "start", "demo", "t1", "--no-fetch"], capture_output=True, text=True, env=env, cwd=str(self.tmp))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((home / "wtroot" / "demo" / "t1" / ".git").exists())
        self.assertFalse((self.tmp / "~").exists())
        (self.cfg / "config").write_text(f"AI_SCRATCH_OWNERS = {self.owners}\nWT_ROOT = relative/root\n")
        r = subprocess.run(["bash", str(WT), "start", "demo", "t2", "--no-fetch"], capture_output=True, text=True, env=env, cwd=str(self.tmp))
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.tmp / "relative").exists())

    def _plan_checks(self, stdout: str) -> str:
        """The printed plan minus comments and the removal line, runnable under set -e."""
        lines = [l for l in stdout.splitlines() if l and not l.startswith("#") and "worktree remove" not in l
                 and not l.startswith("recorded") and not l.startswith("  ")]
        return "set -e\n" + "\n".join(lines) + "\n"

    def test_the_printed_plan_runs_and_stops_on_a_lock_or_a_quote_in_the_branch(self):
        path, _ = self.start("quoted", "--branch", "jp/f/it's")
        self.commit_in(path)
        git(path, "push", "-q", "-u", "origin", "HEAD")
        r = self.wt("finish", "demo", "quoted", "--release")
        self.assertEqual(r.returncode, 0, r.stderr)
        plan = self._plan_checks(r.stdout)
        self.assertEqual(subprocess.run(["bash", "-c", plan], capture_output=True, text=True).returncode, 0, plan)
        git(self.primary, "worktree", "lock", "--reason", "in use", str(path))
        self.assertNotEqual(subprocess.run(["bash", "-c", plan], capture_output=True, text=True).returncode, 0,
                            "a locked worktree passed the plan's first check")
        git(self.primary, "worktree", "unlock", str(path))
        self.assertTrue(path.exists())

    def test_a_plain_finish_after_a_release_withdraws_it_and_says_so(self):
        path, _ = self.start()
        self.commit_in(path)
        git(path, "push", "-q", "-u", "origin", "HEAD")
        self.assertEqual(self.wt("finish", "demo", "task1", "--release").returncode, 0)
        r = self.wt("finish", "demo", "task1", "--note", "again")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("WITHDRAWN", r.stderr)
        self.assertIn('"released": false', self.record())

    def test_the_sweep_consumes_the_records_wt_writes(self):
        done, _ = self.start("done")
        self.commit_in(done)
        git(done, "push", "-q", "-u", "origin", "HEAD")
        self.assertEqual(self.wt("finish", "demo", "done", "--release").returncode, 0)
        busy, _ = self.start("busy")
        subprocess.run(["find", str(self.wt_root), "-exec", "touch", "-t", OLD, "{}", ";"], capture_output=True)
        env = dict(os.environ, AI_SCRATCH_CONFIG_DIR=str(self.cfg))
        env.pop("AI_SCRATCH_ROOT", None)
        out = subprocess.run(["bash", str(SWEEP), "--root", str(self.wt_root / "demo"), "--verbose"],
                             capture_output=True, text=True, env=env, timeout=120).stdout
        self.assertRegex(out, r"FREE\s+done\b")
        self.assertRegex(out, r"KEEP\s+busy\s.*owner record not released")


if __name__ == "__main__":
    unittest.main()
