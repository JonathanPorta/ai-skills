---
name: project-workflow
description: Establish or maintain a project notes workflow with numbered assignments, execution results, independent review, supersession, and measurable handoff quality. Use when asked to initialize project notes, prepare the next numbered prompt, execute an approved assignment, review results, close or supersede prompts, or reconcile stale project status. Pair with tracker when structured project progress or generated views need updating.
---

# Project workflow

Use one project ledger to connect instructions, results and review. Preserve the
project's existing folders and tracker design. Keep examples and reusable assets
generic; put private names, paths and decisions only in the destination notes.

## Resolve the project

Read repository instructions, the project README/checkpoint, existing prompt
index, tracker state and recent evidence before editing. Resolve the notes root,
project directory, repositories and publication convention from the request or
repository configuration; do not assume a user's home path or assistant runtime.
Use a review branch or isolated worktree rather than an auto-committing live vault.
Honor already granted publication scope; opening a PR does not authorize merging.

For a new project, read [the contract](references/contract.md), then initialize:

```bash
python3 "$WORKFLOW_SKILL/scripts/workflow.py" init \
  --project-dir "$PROJECT_DIR" --name "Sample Project"
```

`WORKFLOW_SKILL` is this skill's directory; `PROJECT_DIR` is the resolved project.
For an existing project, inventory its current files first. Import deliberately
using the contract; never run initialization over its index or rewrite history to
manufacture successful reviews. Adopt the convention on the next assignment if
historical review evidence is incomplete. Document the coverage boundary.

## Prepare the next assignment

1. Read the latest results and review; identify a bounded deliverable and its
   evidence requirements. Carry unresolved work into a successor, tracked task or
   named dependency. Avoid broad rediscovery of settled facts.
2. Read the default branch, open prompt PRs and remote reservations. Reserve the
   next ordinal above all historical files, ledger records and known pending
   assignments. Record every observed reservation source. Parallel assignments
   may coexist with explicit dependencies and disjoint ownership.
3. Run `new --project-dir "$PROJECT_DIR" --title "Review sources" --slug review-sources`.
   Supply `--reserved-ordinal N --reservation-source "PR URL or reservation record"`
   for pending ordinals not present locally. This is a **local allocation**, not a
   distributed lock: refresh and resolve collisions before publication and merge.
4. Replace every TODO with task-specific inputs, authority, output paths and
   measurable acceptance criteria. Keep their IDs in `workflow.json` aligned with
   the prompt. Prepare the PR; `draft` means proposed. Record approval provenance
   and set `ready` only when execution is authorized by the user or local policy.

Never reuse a published ordinal, even when cancelled; never renumber an executed
prompt. Keep one canonical instruction file. Use separate metadata for status.

## Execute and hand off

Read the approved instruction revision. Set `running` and capture the source
commit and prompt SHA-256 in the project checkpoint before working. A final run
record is required at handoff, not while work is still underway. Continue independent useful work when
an access path is blocked; do not substitute guesses for missing evidence.

Create one attempt packet using [the result template](references/result-template.md).
Populate every criterion, validation, artifact and remaining gap in the ledger.
Keep attempt IDs consecutive and result/evidence files append-only. Finish as
`needs_review`, or `blocked` with a precise continuation. Do not self-accept.
Passing a local check proves only that check; distinguish generated, tested,
installed, independently accepted and delivered states.

## Review and close

Use a different reviewer/session. Inspect actual artifacts and original criteria;
do not infer acceptance from a successful executor summary. Read [the review
template](references/review-template.md). Record the reviewed attempt, reviewer,
decision, timestamp, evidence and `run_sha256` from `report` **after** inspecting
that exact packet. The digest binds review to the run metadata and result bytes.
A correction creates a new attempt and requires a new review.

Mark `completed` only when the latest attempt meets every criterion and its latest
independent review accepts it. Move its unchanged instructions to `closed/` and
update the ledger path in the same change. `superseded` requires a reason, later
successor ordinal and explicit destinations for every open gap; move the original
to `superseded/`. `cancelled` requires a reason and gap disposition. Update inbound
links; do not leave duplicate executable copies in `open/`.

Use [tracker](../tracker/SKILL.md) to reconcile project stages separately.
Assignment completion never automatically marks implementation, testing,
acceptance or delivery complete. Regenerate its views from its existing state.

## Reconcile and measure

```bash
python3 "$WORKFLOW_SKILL/scripts/workflow.py" render --project-dir "$PROJECT_DIR"
python3 "$WORKFLOW_SKILL/scripts/workflow.py" check --project-dir "$PROJECT_DIR"
python3 "$WORKFLOW_SKILL/scripts/workflow.py" report --project-dir "$PROJECT_DIR"
```

Read [evaluation](references/evaluation.md) before claiming the workflow is
working well. Run checks after changes and before publication. Verify README,
tracker and prose claims separately; the helper checks ledger references and
index consistency, not semantic truth or arbitrary narrative links. Report the
actual static checks, observed handoff measurements and unmeasured outcomes.

Finish with artifacts or PR links, criteria met/unmet/untested, review state,
remaining owners/dependencies and the precise next action. Send no external
messages, execute no deployment and merge no PR unless independently authorized.
