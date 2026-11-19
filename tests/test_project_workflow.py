"""Exercise the workflow CLI against isolated, fictional project histories.

These tests guard observable failures: reused ordinals, rewritten assignments,
unsupported completion claims, missing evidence, and generated index drift.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

try:
    from tests._fixtures import mkdtemp
except ImportError:
    from _fixtures import mkdtemp


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "project-workflow" / "scripts" / "workflow.py"


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(mkdtemp(prefix="workflow-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.project = self.tmp / "Sample Project"
        self.project.mkdir()
        self.success("init", "--name", "Sample Project")

    def run_cli(self, command, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), command,
             "--project-dir", str(self.project), *args],
            capture_output=True, text=True, timeout=30,
        )

    def success(self, command, *args):
        result = self.run_cli(command, *args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def rejected(self, command="check", *args, pattern=None):
        result = self.run_cli(command, *args)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        if pattern:
            self.assertRegex(result.stdout + result.stderr, pattern)
        return result

    def read(self):
        return json.loads((self.project / "workflow.json").read_text())

    def write(self, state):
        (self.project / "workflow.json").write_text(json.dumps(state, indent=2) + "\n")

    def add_prompt(self, title="Inspect input", slug="inspect-input", *args):
        self.success("new", "--title", title, "--slug", slug, *args)
        return self.read()["prompts"][-1]

    def test_new_project_and_prompt_are_checkable_and_index_is_deterministic(self):
        self.add_prompt()
        self.success("render")
        self.success("check")
        state = self.read()
        self.assertEqual(state["schema_version"], 1)
        self.assertEqual(state["prompts"][0]["ordinal"], 1)
        self.assertEqual(state["prompts"][0]["status"], "draft")
        index = self.project / state["paths"]["index"]
        first = index.read_bytes()
        self.success("render")
        self.assertEqual(index.read_bytes(), first)

    def test_allocator_skips_legacy_and_pending_reservations(self):
        legacy = self.project / "implementation/prompts/closed/009-old-task.md"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("# Historical assignment\n")
        prompt = self.add_prompt(
            "Inspect input", "inspect-input", "--reserved-ordinal", "12",
            "--reservation-source", "Pending prompt PR inspected at revision abc123",
        )
        self.assertEqual(prompt["ordinal"], 13)
        self.assertEqual(self.read()["next_ordinal"], 14)
        self.assertTrue(legacy.exists())

    def test_allocator_does_not_reset_when_prompt_moves(self):
        prompt = self.add_prompt()
        state = self.read()
        source = self.project / prompt["path"]
        destination = source.parent.parent / "closed" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        state["prompts"][0]["path"] = destination.relative_to(self.project).as_posix()
        state["prompts"][0]["status"] = "cancelled"
        state["prompts"][0]["reason"] = "The source is no longer needed."
        self.write(state)
        prompt2 = self.add_prompt("Inspect output", "inspect-output")
        self.assertEqual(prompt2["ordinal"], 2)

    def test_duplicate_ordinal_is_rejected(self):
        self.add_prompt()
        state = self.read()
        duplicate = deepcopy(state["prompts"][0])
        state["prompts"].append(duplicate)
        self.write(state)
        self.rejected(pattern="duplicate ordinal")

    def test_unknown_status_is_rejected(self):
        self.add_prompt()
        state = self.read()
        state["prompts"][0]["status"] = "probably-done"
        self.write(state)
        self.rejected(pattern="invalid status")

    def test_path_traversal_cannot_reference_external_assignment(self):
        self.add_prompt()
        sentinel = self.tmp / "outside.md"
        sentinel.write_text("outside\n")
        state = self.read()
        state["prompts"][0]["path"] = "../outside.md"
        self.write(state)
        self.rejected(pattern="path escapes")
        self.assertEqual(sentinel.read_text(), "outside\n")

    def test_symlink_cannot_reference_external_assignment(self):
        prompt = self.add_prompt()
        external = self.tmp / "outside.md"
        external.write_text("outside\n")
        path = self.project / prompt["path"]
        path.unlink()
        path.symlink_to(external)
        self.rejected(pattern="symlink")

    def test_stale_index_is_rejected_then_render_fixes_it(self):
        self.add_prompt()
        self.success("render")
        state = self.read()
        index = self.project / state["paths"]["index"]
        index.write_text("# An obsolete summary\n")
        self.rejected(pattern="index is stale")
        self.success("render")
        self.success("check")

    def test_completed_without_run_and_independent_review_is_rejected(self):
        prompt = self.add_prompt()
        state = self.read()
        state["prompts"][0]["status"] = "completed"
        source = self.project / prompt["path"]
        source.write_text(
            "# Inspect input\n\nProduce output.txt with three sample rows.\n\n"
            "## Acceptance criteria\n\n- AC-1: output.txt contains exactly three rows.\n"
        )
        target = source.parent.parent / "closed" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        state["prompts"][0]["path"] = target.relative_to(self.project).as_posix()
        self.write(state)
        self.rejected(pattern="recorded run|independent review")

    def test_supersession_requires_real_successor(self):
        self.add_prompt()
        state = self.read()
        state["prompts"][0]["status"] = "superseded"
        state["prompts"][0]["superseded_by"] = 999
        self.write(state)
        self.rejected(pattern="successor.*existing")

    def test_report_is_machine_readable_without_editing_project(self):
        self.add_prompt()
        self.success("render")
        before = {p.relative_to(self.project): p.read_bytes()
                  for p in self.project.rglob("*") if p.is_file()}
        report = json.loads(self.success("report").stdout)
        self.assertIsInstance(report["errors"], list)
        self.assertIsInstance(report["warnings"], list)
        self.assertIsInstance(report["metrics"], dict)
        after = {p.relative_to(self.project): p.read_bytes()
                 for p in self.project.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_init_does_not_overwrite_existing_notes(self):
        legacy_project = self.tmp / "Existing Project"
        index = legacy_project / "implementation/prompts/README.md"
        index.parent.mkdir(parents=True)
        index.write_text("# Existing prompt index\nKeep this historical record.\n")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "init", "--project-dir", str(legacy_project),
             "--name", "Existing Project"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to overwrite", result.stderr)
        self.assertEqual(index.read_text(), "# Existing prompt index\nKeep this historical record.\n")
        self.assertFalse((legacy_project / "workflow.json").exists())

    def test_init_index_cannot_overwrite_its_ledger(self):
        project = self.tmp / "Index Collision"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "init", "--project-dir", str(project),
             "--name", "Index Collision", "--index", "workflow.json"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        ledger = project / "workflow.json"
        if ledger.exists():
            self.assertIsInstance(json.loads(ledger.read_text()), dict)

    def test_render_index_cannot_overwrite_canonical_prompt(self):
        prompt = self.add_prompt()
        path = self.project / prompt["path"]
        original = path.read_bytes()
        state = self.read()
        state["paths"]["index"] = prompt["path"]
        self.write(state)
        self.rejected("render", pattern="index|collision|overlap")
        self.assertEqual(path.read_bytes(), original)

    def complete_fixture(self, *, completed=True):
        """Build a real result/evidence packet, then close the same prompt file."""
        prompt = self.add_prompt()
        state = self.read()
        prompt = state["prompts"][0]
        evidence = "implementation/evidence/check.txt"
        result = "implementation/runs/001/attempt-01.md"
        review = "implementation/runs/001/review-01.md"
        for name, body in (
            (evidence, "Observed expected output: 3 rows.\n"),
            (result, "# Run result\nAC-1 met; check returned 3 rows.\n"),
            (review, "# Independent review\nReproduced the 3-row result.\n"),
            ("output.txt", "alpha\nbeta\ngamma\n"),
        ):
            path = self.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        source = self.project / prompt["path"]
        source.write_text(
            "# Inspect input\n\nProduce output.txt with three sample rows.\n\n"
            "## Acceptance criteria\n\n- AC-1: output.txt contains exactly three rows.\n"
        )
        target = source
        if completed:
            target = source.parent.parent / "closed" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
        prompt["path"] = target.relative_to(self.project).as_posix()
        prompt["status"] = "completed" if completed else "needs_review"
        prompt["acceptance_criteria"] = ["AC-1"]
        prompt["runs"] = [{
            "attempt": 1, "executor": "execution-session-a",
            "source_revision": "a" * 40,
            "prompt_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "result": result, "recorded_at": "2026-01-01T12:00:00Z",
            "criteria": [{"id": "AC-1", "status": "met", "evidence": [evidence]}],
            "validations": [{"command": "python verify.py", "outcome": "pass", "evidence": [evidence]}],
            "artifacts": ["output.txt"],
        }]
        prompt["reviews"] = [{
            "attempt": 1, "reviewer": "review-session-b", "decision": "accepted",
            "recorded_at": "2026-01-01T13:00:00Z", "result": review,
            "evidence": [evidence],
            "run_sha256": hashlib.sha256(
                json.dumps(prompt["runs"][0], sort_keys=True, separators=(",", ":")).encode()
                + b"\n" + (self.project / result).read_bytes()
            ).hexdigest(),
        }] if completed else []
        self.write(state)
        self.success("render")
        self.success("check")
        return self.read()

    def test_independent_review_completes_prompt_with_concrete_evidence(self):
        self.complete_fixture()
        report = json.loads(self.success("report").stdout)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["metrics"]["completed_count"], 1)
        self.assertEqual(report["metrics"]["run_count"], 1)
        self.assertEqual(report["metrics"]["measured_run_count"], 0)
        self.assertEqual(report["metrics"]["unmeasured_run_count"], 1)
        self.assertIsNone(report["metrics"]["measurement_averages"])

    def test_successful_execution_waits_for_independent_review(self):
        state = self.complete_fixture(completed=False)
        report = json.loads(self.success("report").stdout)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["metrics"]["completed_count"], 0)
        self.assertEqual(report["metrics"]["needs_review_count"], 1)
        self.assertEqual(state["prompts"][0]["reviews"], [])

    def test_executor_cannot_accept_own_run(self):
        state = self.complete_fixture()
        state["prompts"][0]["reviews"][0]["reviewer"] = "execution-session-a"
        self.write(state)
        self.rejected(pattern="independent")

    def test_completed_requires_all_criteria_met(self):
        state = self.complete_fixture()
        state["prompts"][0]["runs"][0]["criteria"][0]["status"] = "unmet"
        self.write(state)
        self.rejected(pattern="all acceptance criteria met")

    def test_completed_cannot_use_earlier_accepted_review_after_rejection(self):
        state = self.complete_fixture()
        newer = deepcopy(state["prompts"][0]["reviews"][0])
        newer["decision"] = "changes_requested"
        newer["recorded_at"] = "2026-01-02T13:00:00Z"
        state["prompts"][0]["reviews"].append(newer)
        self.write(state)
        self.rejected(pattern="latest attempt")

    def test_completed_cannot_use_acceptance_of_prior_attempt(self):
        state = self.complete_fixture()
        newer = deepcopy(state["prompts"][0]["runs"][0])
        newer["attempt"] = 2
        newer["recorded_at"] = "2026-01-02T12:00:00Z"
        state["prompts"][0]["runs"].append(newer)
        self.write(state)
        self.rejected(pattern="latest attempt")

    def test_editing_executed_prompt_breaks_digest(self):
        state = self.complete_fixture()
        path = self.project / state["prompts"][0]["path"]
        path.write_text(path.read_text() + "\nAdditional requirement added later.\n")
        self.rejected(pattern="instructions hash mismatch")

    def test_missing_local_evidence_is_rejected(self):
        self.complete_fixture()
        (self.project / "implementation/evidence/check.txt").unlink()
        self.rejected(pattern="missing file.*check.txt")

    def test_missing_run_result_is_rejected(self):
        self.complete_fixture()
        (self.project / "implementation/runs/001/attempt-01.md").unlink()
        self.rejected(pattern="missing file.*attempt-01.md")

    def test_unresolved_gap_requires_owner_and_destination(self):
        state = self.complete_fixture()
        state["prompts"][0]["gaps"] = [{
            "id": "G-1", "summary": "Need an additional sample",
            "status": "open", "owner": "", "destination": "",
        }]
        self.write(state)
        self.rejected(pattern="open gap owner")

    def test_gap_destination_must_identify_existing_work(self):
        state = self.complete_fixture()
        state["prompts"][0]["gaps"] = [{
            "id": "G-1", "summary": "Need an additional sample",
            "status": "open", "owner": "maintainer", "destination": "prompt:999",
        }]
        self.write(state)
        self.rejected(pattern="destination prompt.*exist")

    def test_bounded_completion_can_carry_gap_to_active_successor(self):
        self.complete_fixture()
        self.add_prompt("Inspect more samples", "inspect-more-samples")
        state = self.read()
        state["prompts"][0]["gaps"] = [{
            "id": "G-1", "summary": "Inspect a larger sample later",
            "status": "open", "owner": "maintainer", "destination": "prompt:002",
        }]
        self.write(state)
        self.success("render")
        self.success("check")
        report = json.loads(self.success("report").stdout)
        self.assertEqual(report["metrics"]["completed_count"], 1)
        self.assertEqual(report["metrics"]["open_gap_count"], 1)
        self.assertEqual(report["metrics"]["unowned_gap_count"], 0)

    def test_supersession_cycle_is_rejected(self):
        self.add_prompt()
        self.add_prompt("Inspect output", "inspect-output")
        state = self.read()
        for prompt, successor in zip(state["prompts"], (2, 1)):
            source = self.project / prompt["path"]
            target = source.parent.parent / "superseded" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
            prompt.update({
                "path": target.relative_to(self.project).as_posix(),
                "status": "superseded", "superseded_by": successor,
                "reason": "Scope replaced by a successor.",
            })
        self.write(state)
        self.rejected(pattern="successor.*later|cycle")

    def test_accepted_result_bytes_cannot_change_silently(self):
        self.complete_fixture()
        path = self.project / "implementation/runs/001/attempt-01.md"
        path.write_text(path.read_text() + "\nActually observed four rows.\n")
        self.rejected(pattern="fingerprint|run_sha256|review.*hash")

    def test_accepted_run_metadata_cannot_change_silently(self):
        state = self.complete_fixture()
        state["prompts"][0]["runs"][0]["validations"][0]["command"] = "python different.py"
        self.write(state)
        self.rejected(pattern="fingerprint|run_sha256|review.*hash")


if __name__ == "__main__":
    unittest.main()
