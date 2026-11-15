# Project workflow validation

## Independent handoff exercise

A fresh reviewer received only the reusable skill, a fictional project folder,
and the request to review its latest handoff. It did not receive the expected
answer or a hint that the deliverable was incomplete.

The assignment required a JSON summary to retain every source ID exactly once
and count all categories. The source was:

```csv
id,category
N01,lined
N02,plain
N03,lined
N04,grid
N05,plain
```

The submitted output contained IDs N01 through N04 and counts `lined=2`,
`plain=1`, `grid=1`. The executor packet claimed both criteria were met, with a
successful JSON syntax check as evidence. The workflow ledger and file references
were structurally valid before review.

Observed result on 2026-11-15:

- The independent reviewer found the missing N05 and incorrect plain count.
- It recorded `changes_requested`, preserved the submitted artifacts/instructions,
  retained the assignment in `open/`, and wrote two owned correction gaps.
- The next action explicitly requires a corrected attempt 02 and another review.
- The resulting lifecycle check reported zero errors and two open owned gaps.
- No remote publication or deployment was used for this exercise.

This exercises semantic review beyond structural checks. It is one synthetic
handoff, not proof of effectiveness on real projects. Handoff timing, repeated
work, and bookkeeping time were not measured. The five-run scorecard remains the
way to assess real use after adoption.

## Automated and integration checks

`make check` passed: seven skills validated; 348 tests ran in approximately 100
seconds, with 347 passing and one optional external-runtime integration test
skipped because its separate pinned checkout was not configured. The tracker
subset has 38 tests and the workflow subset has 29. Local link, JSON and whitespace
checks passed. The external runtime's live plugin-loading test was not rerun.

Behavioral coverage includes configurable tracker locations, worktree ownership, render drift,
monotonic prompt allocation, pending reservations, frozen instructions, missing
results, independent review, stale approvals, supersession and gap disposition.

## Publication review

Reusable content and examples were reviewed for private project context. The
tracker's older project-specific examples were replaced with generic material.
Repository-specific configuration and baseline observations belong only to their
consuming notes repositories. No history rewrite or live project migration is
part of this change.

## Phase-gate audit

Result: PASS WITH LIMITS. The implementation matches the scoped requirements;
checks and independent review are recorded above. No installation, project
migration, deployment, or real-use improvement is claimed. The optional external
runtime integration and five real workflow cycles remain unverified. The next
action is source review and the authorized PR publication; merge is separate.
