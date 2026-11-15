# Project record contract

## Contents

- [Folders and authority](#folders-and-authority)
- [Ledger](#ledger)
- [Run and review records](#run-and-review-records)
- [Lifecycle and adoption](#lifecycle-and-adoption)
- [Allocation and publication](#allocation-and-publication)

## Folders and authority

Keep the existing project README, `Tracker/`, `adr/`, `reference/` and
project-specific deliverable folders. Create only the missing folders needed for
the task. The default helper paths are `implementation/prompts/`,
`implementation/runs/` and `implementation/evidence/`; configure alternate paths
in the ledger when adopting an established project.

`workflow.json` is authoritative for **assignment lifecycle**, dependencies and
run/review references. Prompt Markdown is authoritative for executed instructions.
The tracker state remains authoritative for **project stage progress**. Neither
record substitutes for the other. Generate the prompt index from the ledger.
Keep the project README brief: goal, current evidence, next action, key links.

## Ledger

`init` creates this shape at the project root:

```json
{
  "schema_version": 1,
  "project": "Sample Project",
  "next_ordinal": 1,
  "paths": {
    "prompts": "implementation/prompts",
    "runs": "implementation/runs",
    "evidence": "implementation/evidence",
    "index": "implementation/prompts/README.md"
  },
  "prompts": [],
  "reservations": [],
  "excluded_files": []
}
```

Create a prompt with `new`, then fill the instruction body and edit its record:

```json
{
  "ordinal": 1,
  "title": "Inspect sample records",
  "path": "implementation/prompts/open/001-inspect-records.md",
  "status": "draft",
  "updated_at": "2026-01-01T10:00:00Z",
  "depends_on": [],
  "acceptance_criteria": ["AC-1"],
  "runs": [],
  "reviews": [],
  "gaps": [],
  "superseded_by": null
}
```

All paths are relative to the project root and must stay inside it. References
may be existing local files (optionally `#anchor`) or HTTPS URLs without embedded
credentials. URL reachability and anchor meaning are reviewed separately. Never
store secret values, token-bearing links or private samples in a public skill.

Use `acceptance_criteria` for stable IDs; write their complete observable meaning
in the immutable prompt. Add an `approval` reference when setting `ready` so a
reader can find authorization; the helper cannot determine user authority from
repository text. Set `updated_at` on real status changes, not merely to clear a
staleness warning. Additional metadata is allowed; helpers do not infer behavior
from unknown keys.

Each open gap needs `id`, `summary`, `status: "open"`, `owner` and `destination`.
The destination is an active `prompt:002`, an existing local task/dependency file
or an HTTPS issue/reference. A resolved gap uses `status: "resolved"` and an
`evidence` list. Follow the destination during review: existence alone does not
prove that the owner accepted it or that the tracked task actually preserves the
remaining work. A cancelled or superseded prompt must not discard unresolved work.

## Run and review records

Use a new attempt ID for each correction/rerun. Keep result packets and supporting
evidence immutable; append new files for later attempts. The run record contains:

| Field | Meaning |
|---|---|
| `attempt` | Consecutive integer starting at 1 |
| `executor` | Stable executor/session identity |
| `source_revision` | Full 40-character commit SHA containing the executed instructions |
| `prompt_sha256` | SHA-256 of the exact instruction file bytes captured before execution |
| `recorded_at` | ISO timestamp including timezone |
| `result` | Existing attempt packet path |
| `criteria` | Every prompt criterion: `id`, `status` (`met`, `unmet`, `untested`), `evidence` list |
| `validations` | Actual `command`, `outcome` (`pass`, `fail`, `blocked`), `evidence` list |
| `artifacts` | Existing local paths or HTTPS references; empty when no artifact was produced |

`met` requires evidence. Unmet/untested criteria may have an empty evidence list;
explain the reason in the packet. Record blocked validations explicitly with a
linked explanation. Failed checks cannot be reworded as passes. A result can be
ready for independent review while criteria remain unmet; it cannot be completed.

A review record contains `attempt`, `reviewer`, `decision` (`accepted` or
`changes_requested`), `recorded_at`, `result`, `evidence`, and `run_sha256`.
`reviewer` must differ from that attempt's executor. The timestamp cannot precede
the run. The newest review of the latest attempt controls completion.

Run `report` after inspecting the packet. Copy the appropriate
`run_fingerprints["001/1"]` value into `run_sha256`. The digest is
SHA-256 of canonical run JSON (`sort_keys=True`, separators `(',', ':')`), a newline,
and exact result packet bytes. This binds the review to the run metadata and packet.
The checker also verifies the unchanged prompt hash. The digest is an integrity
check, not an electronic signature: independent review and source-control history
are still required. It does not hash every external artifact or authenticate the
claimed reviewer. Pin mutable artifact references when the task requires it.

For optional effectiveness measurements, add a run `measurement` object with
all four nonnegative numbers: `handoff_minutes`, `status_corrections`,
`repeated_discovery_minutes`, `bookkeeping_minutes`. Omit the object for unknown
measurements; never use zero as a substitute for missing data. Record these values
before review, because review binds the full run record.

## Lifecycle and adoption

| Status | Folder | Meaning |
|---|---|---|
| `draft` | `open/` | Proposed, not yet approved for execution |
| `ready` | `open/` | Execution authorized; dependencies understood |
| `running` | `open/` | Work underway |
| `blocked` | `open/` | Precise blocker and continuation recorded |
| `needs_review` | `open/` | Attempt packet ready for independent review |
| `completed` | `closed/` | Latest attempt fully meets the bounded criteria and is independently accepted |
| `superseded` | `superseded/` | Replaced by a later ordinal, with `reason` and `superseded_by` |
| `cancelled` | `closed/` | Intentionally stopped, with `reason` and gap disposition |

`new` reserves an ordinal and creates a draft; it does not mark it executable.
Move instruction files without editing their bytes when changing folders. Amend
an unexecuted draft in place. Change materially different executed instructions
through a successor prompt; keep correction attempts under the same unchanged
instructions. Never overwrite a result or review packet.

For an existing project, make a read-only baseline of files, actual status claims,
known results, missing reviews and duplicate forwarding stubs. Import only
supported state. Do not invent review records for historically closed prompts.
If historical acceptance cannot be reconstructed, document that boundary and
start enforcing the contract prospectively rather than relabeling old work as
verified. `excluded_files` may name a legacy file or compatibility redirect with
an explicit `path` and `reason`; checks warn about these exclusions and allocation
still reserves their numbers. Exclude neither the active canonical prompt nor
new work to make a failure disappear. Preserve old review evidence in place.

Initialization refuses an existing ledger or index. Use
`init --index implementation/prompts/workflow-index.md` if preserving a legacy
index, then reconcile the two entry points deliberately. The helper does not
rewrite arbitrary backlinks or Markdown prose; review those in the PR.

## Allocation and publication

`next_ordinal` is a high-water mark, not the number of prompts. Allocation scans
all numbered Markdown beneath the configured prompts directory, including
closed, superseded and explicitly excluded legacy files. Ordinal `000` is valid
for import; newly initialized projects start at `001`. Never lower the mark.

Supply pending remote reservations explicitly with repeated `--reserved-ordinal`
arguments and `--reservation-source`. Existing reservations remain in the ledger
until their published record is imported; remove the reservation only in the same
change that imports that prompt. Never reclaim a published abandoned number:
retain a cancellation or reservation tombstone.

The local exclusive lock prevents two processes allocating in the same project
directory. It cannot coordinate separate worktrees or remote branches. Before
opening and before merging a prompt PR, fetch the default branch and inspect
other open prompt PRs. Serialize reservation merges or change the unexecuted,
unpublished conflicting draft to the next free ordinal. Re-run checks after
rebase. If a conflicting ordinal was already published, preserve that history
and allocate a new successor; do not silently rewrite an executed identity.

`render` regenerates only the configured prompt index, and refuses invalid
records. `check` returns nonzero for errors. `report` prints JSON with the same
findings, metrics and run fingerprints; it also returns nonzero on errors. No
command connects to GitHub, submits a PR, executes an assignment or changes the
tracker. Publication authority remains the user's explicit request and the
repository's established policy.
