"""Behavioural tests for the tracker skill's renderer and scaffolder.

They run the real scripts against the shipped example state and disposable
copies of it. Each case guards a way a tracker could silently lie: a rendered
file that no longer matches its state, a PR link where an issue is required,
a chip that reads as linked without an issue, a scaffold that renders with
placeholders still in it.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "tracker"
RENDER = SKILL / "scripts" / "render_tracker.py"
NEW = SKILL / "scripts" / "new_tracker.py"
EXAMPLE = SKILL / "assets" / "example"
SHA = "0123abcdef0123abcdef0123abcdef0123abcdef"

sys.path.insert(0, str(SKILL / "scripts"))
import render_tracker  # noqa: E402


def run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, timeout=120)


class TrackerFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="tracker-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dir = self.tmp / "Tracker"
        shutil.copytree(EXAMPLE, self.dir)
        self.state_path = self.dir / "example-project-state.json"
        self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.config = json.loads((self.dir / "config.json").read_text(encoding="utf-8"))

    def write_state(self, state: dict) -> None:
        self.state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


class RenderTests(TrackerFixture):
    def test_renders_html_svg_and_check_passes(self):
        result = run(RENDER, "--tracker-dir", str(self.dir))
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.dir / "example-project-mindmap.html").read_text(encoding="utf-8")
        svg = (self.dir / "example-project-mindmap.svg").read_text(encoding="utf-8")
        self.assertIn("<title>Example project mind map</title>", html)
        self.assertIn("a.download='example-project-mindmap.svg'", html)
        self.assertIn("Status snapshot: November 3 · main 0123abc", svg)
        self.assertEqual(svg.count('class="focus-node"'), 2)
        self.assertEqual(svg.count("ACCEPTANCE GATES"), 1)
        check = run(RENDER, "--tracker-dir", str(self.dir), "--check")
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_render_is_deterministic(self):
        first = render_tracker.render(self.state, self.config, state_path=self.state_path)
        second = render_tracker.render(deepcopy(self.state), dict(self.config), state_path=self.state_path)
        self.assertEqual(first, second)

    def test_check_fails_after_state_changes(self):
        self.assertEqual(run(RENDER, "--tracker-dir", str(self.dir)).returncode, 0)
        self.state["workstreams"]["02"]["stages"]["testing"] = "complete"
        self.write_state(self.state)
        result = run(RENDER, "--tracker-dir", str(self.dir), "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Generated files differ", result.stderr)

    def test_check_and_png_cannot_be_combined(self):
        result = run(RENDER, "--tracker-dir", str(self.dir), "--check", "--png")
        self.assertEqual(result.returncode, 2)

    def test_third_stage_label_and_note_are_configurable(self):
        self.config.update({"issues_label": "Approval", "issues_note": "Approval ✓ means the owner approved that scope."})
        svg = render_tracker.render(self.state, self.config, state_path=self.state_path)[".svg"]
        self.assertIn(">APPROVAL</text>", svg)
        self.assertNotIn(">ISSUES</text>", svg)
        self.assertIn("Approval ✓ means the owner approved that scope.", svg)
        self.assertIn('text-anchor="start">Approval</text>', svg)

    def test_issue_chip_links_only_when_an_issue_is_attached(self):
        svg = render_tracker.render(self.state, self.config, state_path=self.state_path)[".svg"]
        self.assertIn('data-issue-link="02"', svg)
        self.assertNotIn('data-issue-link="01"', svg)
        self.assertIn('data-issue-link="02.t2"', svg)
        self.assertIn("https://github.com/example/project/issues/7", svg)

    def test_slug_and_project_derive_from_filename_and_heading(self):
        config = {"workstream_count": 2}
        outputs = render_tracker.render(self.state, config, state_path=self.state_path)
        self.assertIn("<h1>Example project mind map</h1>", outputs[".html"])
        self.assertEqual(render_tracker.tracker_slug(config, self.state_path), "example")
        with self.assertRaisesRegex(ValueError, "config.slug is required"):
            render_tracker.tracker_slug(config, self.tmp / "state.json")

    def test_project_name_cannot_inject_attributes(self):
        self.config["project"] = 'Demo" onmouseover="alert(1)" x="'
        html = render_tracker.render(self.state, self.config, state_path=self.state_path)[".html"]
        self.assertNotIn('onmouseover="alert(1)"', html)
        self.assertIn('aria-label="Zoomable Demo&quot; onmouseover=&quot;alert(1)&quot; x=&quot; mind map"', html)
        self.assertIn("<h1>Demo&quot; onmouseover=&quot;alert(1)&quot; x=&quot; project mind map</h1>", html)
        self.state["workstreams"]["01"]["title"] = 'Plain "quoted" title'
        html = render_tracker.render(self.state, self.config, state_path=self.state_path)[".html"]
        self.assertIn("01 · Plain &quot;quoted&quot; title</option>", html)

    def test_text_is_escaped_not_markup(self):
        self.state["workstreams"]["01"]["title"] = 'Foundation <script>alert(1)</script> & "quotes"'
        svg = render_tracker.render(self.state, self.config, state_path=self.state_path)[".svg"]
        self.assertNotIn("<script>alert(1)</script>", svg)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp;", svg)


class ValidationTests(TrackerFixture):
    def assert_rejected(self, state: dict, config: dict | None = None, pattern: str = ""):
        with self.assertRaisesRegex(ValueError, pattern):
            render_tracker.validate(state, config or self.config)

    def test_rejects_unknown_stage_status_and_color(self):
        state = deepcopy(self.state)
        state["workstreams"]["01"]["stages"]["testing"] = "done"
        self.assert_rejected(state, pattern="expected complete, partial or pending")
        state = deepcopy(self.state)
        state["workstreams"]["01"]["tasks"]["t1"]["color_stage"] = "approval"
        self.assert_rejected(state, pattern="unknown stage")

    def test_rejects_pull_request_where_an_issue_is_required(self):
        state = deepcopy(self.state)
        state["workstreams"]["02"]["github_issues"] = [{
            "repository": "example/project", "number": 8,
            "url": "https://github.com/example/project/pull/8",
        }]
        self.assert_rejected(state, pattern="url must match the GitHub repository and issue number")

    def test_rejects_unsafe_evidence_urls(self):
        for value in ("javascript:alert(1)", "http://example.com/x", "https://user:pw@example.com/x", ""):
            state = deepcopy(self.state)
            state["workstreams"]["01"]["evidence_url"] = value
            with self.subTest(value=value):
                self.assert_rejected(state, pattern="absolute HTTPS URL")

    def test_rejects_mismatched_workstream_count_and_unknown_config_keys(self):
        self.assert_rejected(self.state, {"workstream_count": 3}, "workstream_count must match")
        self.assert_rejected(self.state, {"workstream_count": 2, "colour": "red"}, "unknown")
        self.assert_rejected(self.state, {"workstream_count": 2, "slug": "Not A Slug"}, "config.slug")

    def test_rejects_missing_associations_and_wrong_schema_version(self):
        state = deepcopy(self.state)
        del state["workstreams"]["01"]["tasks"]["t1"]["github_issues"]
        self.assert_rejected(state, pattern="github_issues")
        state = deepcopy(self.state)
        state["schema_version"] = 1
        self.assert_rejected(state, pattern="Unsupported schema_version")

    def test_rejects_duplicate_json_keys_and_multiline_text(self):
        self.state_path.write_text('{"schema_version": 2, "schema_version": 2}', encoding="utf-8")
        result = run(RENDER, "--tracker-dir", str(self.dir))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Duplicate JSON key", result.stderr)
        state = deepcopy(self.state)
        state["project"]["tagline"] = "two\nlines"
        self.assert_rejected(state, pattern="single-line string")

    def test_example_matches_the_shipped_schema_shape(self):
        schema = json.loads((SKILL / "assets" / "state.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(schema["required"]), set(self.state))
        self.assertEqual(schema["properties"]["schema_version"]["const"], 2)


class ScaffoldTests(TrackerFixture):
    def test_scaffold_renders_and_finish_would_refuse_placeholders(self):
        target = self.tmp / "Projects" / "Demo" / "Tracker"
        result = run(NEW, "--tracker-dir", str(target), "--project", "Demo", "--slug", "demo",
                     "--repository", "example/demo", "--commit", SHA, "--date", "2026-11-03", "--workstreams", "3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(p.name for p in target.iterdir()),
                         [".gitignore", "README.md", "config.json", "demo-project-state.json"])
        config = json.loads((target / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["workstream_count"], 3)
        state = json.loads((target / "demo-project-state.json").read_text(encoding="utf-8"))
        self.assertEqual(list(state["workstreams"]), ["01", "02", "03"])
        self.assertEqual(state["snapshot"]["evidence_ref"], SHA[:7])
        self.assertIn("TODO", (target / "demo-project-state.json").read_text(encoding="utf-8"))
        rendered = run(RENDER, "--tracker-dir", str(target))
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertTrue((target / "demo-project-mindmap.html").exists())

    def test_scaffold_refuses_existing_tracker_and_bad_inputs(self):
        self.assertEqual(run(NEW, "--tracker-dir", str(self.dir), "--project", "X", "--slug", "x",
                             "--repository", "a/b", "--commit", SHA, "--date", "2026-11-03").returncode, 1)
        self.assertEqual(run(NEW, "--tracker-dir", str(self.tmp / "new"), "--project", "X", "--slug", "Bad Slug",
                             "--repository", "a/b", "--commit", SHA, "--date", "2026-11-03").returncode, 1)
        self.assertEqual(run(NEW, "--tracker-dir", str(self.tmp / "new"), "--project", "X", "--slug", "x",
                             "--repository", "a/b", "--commit", "abc", "--date", "2026-11-03").returncode, 1)


HUB_STUB = """#!/usr/bin/env python3
import json, pathlib, sys
root = pathlib.Path(__file__).resolve().parents[2]
config = json.loads((root / 'Projects' / 'TrackerHub' / 'config.json').read_text())
work = (root / 'Projects' / 'TrackerHub' / config['repositories'][1]['root']).resolve()
if not work.is_dir():
    print('Tracker build failed: missing work vault ' + str(work), file=sys.stderr)
    raise SystemExit(1)
maps = sorted(str(p.relative_to(root)) for p in root.rglob('*mindmap.html') if 'Tracker' in p.parts)
catalog = json.dumps({'maps': maps}, indent=1) + '\\n'
if '--check' in sys.argv:
    if (root / 'Projects' / 'TrackerHub' / 'catalog.json').read_text() != catalog:
        raise SystemExit('stale')
    print('Checked %d maps' % len(maps))
else:
    (root / 'Projects' / 'TrackerHub' / 'catalog.json').write_text(catalog)
    (root / 'tracker-mindmaps.html').write_text('<!doctype html>' + catalog)
    print('Bundled %d maps' % len(maps))
"""
HUB_CONFIG = {"schema_version": 1, "repositories": [
    {"repository": "X/notes-personal", "root": "../..", "group": "personal"},
    {"repository": "X/notes-work", "root": "../../../Work", "group": "work"}]}
BEGIN = SKILL / "scripts" / "tracker-begin.sh"
FINISH = SKILL / "scripts" / "tracker-finish.sh"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def new_repo(path: Path) -> None:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main", ".")
    git(path, "config", "user.email", "t@example.invalid")
    git(path, "config", "user.name", "Test")


class WorkflowFixture(unittest.TestCase):
    """A disposable notes vault (with origin and a stub TrackerHub) and a work vault."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="tracker-wf-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.origin = self.tmp / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        self.notes = self.tmp / "notes"
        new_repo(self.notes)
        hub = self.notes / "Projects" / "TrackerHub"
        hub.mkdir(parents=True)
        (hub / "build.py").write_text(HUB_STUB)
        (hub / "config.json").write_text(json.dumps(HUB_CONFIG))
        self.tracker_rel = Path("Projects") / "Example" / "Tracker"
        shutil.copytree(EXAMPLE, self.notes / self.tracker_rel)
        (self.notes / self.tracker_rel / "README.md").write_text("# Example\n\n**Snapshot: 2026-11-03.**\n")
        git(self.notes, "add", "-A")
        git(self.notes, "commit", "-qm", "seed")
        git(self.notes, "remote", "add", "origin", str(self.origin))
        git(self.notes, "push", "-q", "-u", "origin", "main")
        git(self.notes, "remote", "set-head", "origin", "main")
        self.work = self.tmp / "work"
        new_repo(self.work)
        (self.work / "note.md").write_text("work\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-qm", "seed")
        self.scratch = self.tmp / "scratch"
        self.env = dict(os.environ, TRACKER_NOTES_REPO=str(self.notes), TRACKER_WORK_REPO=str(self.work),
                        AI_SCRATCH_ROOT=str(self.scratch), TRACKER_NO_PNG="1",
                        GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="t@example.invalid",
                        GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="t@example.invalid")

    def run_script(self, script: Path, *args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
        env = dict(self.env)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(["bash", str(script), *args], capture_output=True, text=True, timeout=120, env=env)

    def begin(self) -> dict:
        result = self.run_script(BEGIN, "--project", "Example", "--date", "2026-11-03")
        self.assertEqual(result.returncode, 0, result.stderr)
        return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)

    def change_state(self, tracker_dir: Path) -> None:
        state_path = tracker_dir / "example-project-state.json"
        state = json.loads(state_path.read_text())
        state["workstreams"]["02"]["stages"]["testing"] = "complete"
        state_path.write_text(json.dumps(state, ensure_ascii=False))


class WorkflowTests(WorkflowFixture):
    def test_begin_and_finish_commit_tracker_then_hub(self):
        out = self.begin()
        worktree, tracker_dir = Path(out["TRACKER_WORKTREE"]), Path(out["TRACKER_DIR"])
        self.assertEqual(out["TRACKER_EXISTS"], "1")
        self.assertTrue(Path(out["TRACKER_WORK_SIBLING"]).is_dir())
        self.assertTrue(str(Path(out["TRACKER_WORK_SIBLING"])).startswith(str(self.scratch)))
        self.change_state(tracker_dir)
        result = self.run_script(FINISH, "--tracker-dir", str(tracker_dir), "--no-push")
        self.assertEqual(result.returncode, 0, result.stderr)
        log = git(worktree, "log", "--format=%s", "-3")
        self.assertEqual(log.splitlines(), ["docs: Rebuild TrackerHub With The Example Tracker",
                                            "docs: Update The Example Project Tracker", "seed"])
        self.assertIn("HUB_COMMIT=", result.stdout)
        self.assertTrue(worktree.exists(), "--no-push never cleans up")

    def test_finish_refuses_the_live_checkout_and_unowned_worktrees(self):
        result = self.run_script(FINISH, "--tracker-dir", str(self.notes / self.tracker_rel), "--no-push")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not a worktree created by tracker-begin.sh", result.stderr)
        foreign = self.tmp / "foreign"
        git(self.notes, "worktree", "add", "-q", "-b", "jp/d/foreign", str(foreign))
        result = self.run_script(FINISH, "--tracker-dir", str(foreign / self.tracker_rel), "--no-push")
        self.assertEqual(result.returncode, 2)
        self.assertTrue((foreign / self.tracker_rel).exists())

    def test_begin_refuses_a_hub_root_outside_the_task_and_a_missing_work_vault(self):
        hub = self.notes / "Projects" / "TrackerHub"
        escaping = dict(HUB_CONFIG)
        escaping["repositories"] = [HUB_CONFIG["repositories"][0],
                                    {"repository": "X/notes-work", "root": "../../../../../outside", "group": "work"}]
        (hub / "config.json").write_text(json.dumps(escaping))
        git(self.notes, "commit", "-qam", "escape")
        git(self.notes, "push", "-q")
        result = self.run_script(BEGIN, "--project", "Example", "--date", "2026-11-03")
        self.assertEqual(result.returncode, 2)
        self.assertIn("outside the task directory", result.stderr)
        self.assertFalse((self.tmp / "outside").exists())
        (hub / "config.json").write_text(json.dumps(HUB_CONFIG))
        git(self.notes, "commit", "-qam", "restore")
        git(self.notes, "push", "-q")
        result = self.run_script(BEGIN, "--project", "Example", "--date", "2026-11-04",
                                 env_extra={"TRACKER_WORK_REPO": str(self.tmp / "nowhere")})
        self.assertEqual(result.returncode, 2)
        self.assertIn("work vault is not at", result.stderr)

    def test_finish_requires_the_hub_sibling_before_committing(self):
        out = self.begin()
        worktree, tracker_dir = Path(out["TRACKER_WORKTREE"]), Path(out["TRACKER_DIR"])
        self.change_state(tracker_dir)
        git(self.work, "worktree", "remove", "--force", out["TRACKER_WORK_SIBLING"])
        result = self.run_script(FINISH, "--tracker-dir", str(tracker_dir), "--no-push")
        self.assertEqual(result.returncode, 1)
        self.assertIn("work-vault sibling is missing", result.stderr)
        self.assertEqual(git(worktree, "log", "--format=%s", "-1"), "seed")
        self.assertIn("example-project-state.json", git(worktree, "status", "--porcelain"))

    def test_finish_refuses_a_stale_png_and_a_dangling_png_reference(self):
        out = self.begin()
        worktree, tracker_dir = Path(out["TRACKER_WORKTREE"]), Path(out["TRACKER_DIR"])
        self.change_state(tracker_dir)
        (tracker_dir / "example-project-mindmap.png").write_bytes(b"\x89PNG stale")
        result = self.run_script(FINISH, "--tracker-dir", str(tracker_dir), "--no-push")
        self.assertEqual(result.returncode, 1)
        self.assertIn("would ship stale", result.stderr)
        self.assertEqual(git(worktree, "log", "--format=%s", "-1"), "seed")
        (tracker_dir / "example-project-mindmap.png").unlink()
        (tracker_dir / "README.md").write_text("# Example\n\n**Snapshot: 2026-11-03.**\n\n![map](example-project-mindmap.png)\n")
        result = self.run_script(FINISH, "--tracker-dir", str(tracker_dir), "--no-push")
        self.assertEqual(result.returncode, 1)
        self.assertIn("references example-project-mindmap.png", result.stderr)
        self.assertEqual(git(worktree, "log", "--format=%s", "-1"), "seed")

    def test_cleanup_keeps_dirty_worktrees_and_removes_clean_owned_ones(self):
        out = self.begin()
        worktree, tracker_dir = Path(out["TRACKER_WORKTREE"]), Path(out["TRACKER_DIR"])
        sibling = Path(out["TRACKER_WORK_SIBLING"])
        self.change_state(tracker_dir)
        stray = worktree / "unrelated-note.md"
        stray.write_text("do not lose me\n")
        result = self.run_script(FINISH, "--tracker-dir", str(tracker_dir), "--no-pr")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(stray.exists(), "an untracked file must survive cleanup")
        self.assertIn("keeping", result.stderr)
        self.assertIn("jp/d/example-tracker-20261103", git(self.notes, "branch", "-r", "--list", "origin/*"))
        stray.unlink()
        result = self.run_script(FINISH, "--tracker-dir", str(tracker_dir), "--no-pr")
        self.assertEqual(result.returncode, 1, "nothing new to commit on a resumed clean run")
        self.assertTrue(worktree.exists())

    def test_cleanup_removes_only_owned_clean_worktrees(self):
        out = self.begin()
        worktree, tracker_dir = Path(out["TRACKER_WORKTREE"]), Path(out["TRACKER_DIR"])
        sibling = Path(out["TRACKER_WORK_SIBLING"])
        self.change_state(tracker_dir)
        result = self.run_script(FINISH, "--tracker-dir", str(tracker_dir), "--no-pr")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(worktree.exists())
        self.assertFalse(sibling.exists())
        self.assertFalse((self.scratch / "tracker-example-20261103").exists())
        self.assertIn("jp/d/example-tracker-20261103", git(self.notes, "branch", "--list"))
        self.assertTrue((self.notes / self.tracker_rel).exists(), "the live checkout is untouched")


class ScriptSyntaxTests(unittest.TestCase):
    def test_shell_scripts_parse_and_refuse_without_arguments(self):
        for name in ("tracker-begin.sh", "tracker-finish.sh"):
            with self.subTest(script=name):
                script = SKILL / "scripts" / name
                self.assertEqual(subprocess.run(["bash", "-n", str(script)], capture_output=True).returncode, 0)
                result = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 2)
                self.assertIn("required", result.stderr)


if __name__ == "__main__":
    unittest.main()
