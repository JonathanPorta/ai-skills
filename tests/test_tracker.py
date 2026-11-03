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
