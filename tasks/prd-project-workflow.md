# Portable project workflow and tracker

## Goal and scope

Make project tracking and numbered assignments reusable across notes repositories.
An operator can create or refresh a tracker, prepare the next assignment for PR
review, execute an approved assignment, and independently review its results.
Examples, fixtures, and documentation in this repository are entirely generic.
Repository-specific configuration and operational evidence stay in the consuming
repository. This change prepares reviewable source; it does not install skills or
authorize merging, deployment, or messaging.

## Codebase analysis

- `skills/tracker/scripts/` already scaffolds, migrates, renders, and checks schema-2 trackers.
- The renderer records six independent work stages and fixed acceptance gates.
- `tracker-begin.sh` and `tracker-finish.sh` use owned task worktrees and PR publication.
- Existing path and companion-vault assumptions make reuse unnecessarily difficult.
- `scripts/check_skills.py` validates portable skills and required plugin sidecars.
- `Makefile` exposes `make test` and `make check`; CI uses the same command surface.
- A numbered assignment lifecycle and measurable handoff review are currently missing.

## Acceptance criteria

1. Tracker operations resolve configured notes paths without changing tracker design,
   independent stage meanings, worktree ownership, or publication boundaries.
2. A self-contained project-workflow skill defines initialization, prompt creation,
   execution, independent review, completion, supersession, and reconciliation.
3. One authoritative registry generates the prompt index; ordinals never reset or
   reuse published identities. Allocation considers legacy files and supplied
   concurrent reservations, with explicit limits on local concurrency guarantees.
4. Results identify the executed instructions, attempt, deliverables, criteria,
   checks actually run, and remaining gaps. Completion requires review evidence.
5. Automated checks reject inconsistent identities/statuses, missing required
   records, unowned gaps, bad supersession, and stale generated indexes.
6. Evaluation separates structural checks from observed usefulness. Record real
   handoff time, correction frequency, and remaining defects over five runs;
   report an unknown baseline honestly.
7. Existing projects can adopt incrementally without rewriting historical prompts,
   inferring acceptance, or redesigning trackers. Generic instructions remain usable
   by agents without harness-specific installation paths.

## Validation plan and independent tasks

| Task | Criteria | Pre-implementation validation |
|---|---|---|
| Portable tracker | 1, 7 | Run existing tracker regressions; add custom-layout and invalid-config cases, including paths with spaces. |
| Assignment lifecycle | 2–5, 7 | Exercise CLI against temporary fictional projects; prove invalid duplicate IDs, unsupported closure, changed instructions, escaped paths, and stale index are detected. |
| Evaluation and adoption | 6, 7 | Run a fresh-context generic handoff; inspect all documented commands and notes adapters; preserve unknown real-use metrics. |
| Integration | All | Run `make check`; review diff, generic-content boundary, and cross-file consistency before creating PRs. |

The first two tasks are independent and own disjoint files. Integration follows
both. No hosted service or production project execution is needed for validation.
