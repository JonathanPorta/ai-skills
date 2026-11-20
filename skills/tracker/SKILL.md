---
name: tracker
description: "Create or refresh a project's evidence-backed status tracker in a notes repository, preserving its design and six independent work stages, validate rendered views, rebuild an optional tracker hub, and prepare a reviewable change. Use for create or update the tracker, refresh my notes tracker, or record where this project stands. Resolve the project and notes location from the request and repository configuration."
---

# Project tracker

Keep one tracker per project in `<projects_dir>/<Name>/Tracker/`. Read repository
instructions and project entry points before making changes. Preserve existing
project structure, state schema, rendering design, task IDs and historical evidence.
The tracker directory holds state and generated views; the renderer stays in this
skill. Read `assets/example/` for a complete generic schema-2 example.

## Resolve locations

Resolve the notes checkout from `--notes DIR`, `TRACKER_NOTES_REPO`, or the current
Git repository root, in that order. When invoked from a product repository, supply
the notes path explicitly rather than assuming the current repository is a vault.
Find the skill's actual installed path; use `TRACKER_SKILL` in commands below.
Do not assume a particular agent, home directory or installation layout.

Read `<notes>/.tracker-workflow.json` when present. See
[configuration](references/configuration.md) for defaults, overrides and hub support.
Resolve the project from the user's selected folder or current project repository.
Use one tracker for a multi-repository project; retain repository fields per
workstream. If several existing trackers plausibly match, inspect their metadata
before asking a narrowly scoped question.

## Update sequence

1. **Use an isolated owned worktree.** Set `WT_OWNER` to the current session ID.
   Run `bash "$TRACKER_SKILL/scripts/tracker-begin.sh" --notes "$NOTES" --project
   "Example Project"`. The helper uses the sibling `ai-scratch` skill's `wt.sh`,
   or `TRACKER_WT`, and prints `TRACKER_WORKTREE`, `TRACKER_DIR`, the branch and
   optional hub input worktree. Treat output as key/value data; do not shell-evaluate
   it. Read or assign the reported paths directly, preserving spaces. It never
   edits the live notes checkout. If local default-branch changes are unpublished,
   inspect them and use `--base REF` only deliberately; a PR needs that base
   published first. Do not silently discard local context.

2. **Gather current evidence.** Read existing state, plan, source repository
   revisions, relevant issues, PRs, tests, release and installation evidence.
   Read the project's `workflow.json`, prompt runs and review decisions when
   present; use [project-workflow](../project-workflow/SKILL.md) for that lifecycle.
   Record observation dates, source revisions, unavailable sources, conflicts,
   and remaining gaps in the tracker README. Distinguish historical facts from
   newly verified observations. An unavailable source is unknown, not a failure
   or a completed stage. Never erase stronger evidence because a later run did
   not repeat it; resolve actual contradictions explicitly.

3. **Create only when missing.** Run `python3 "$TRACKER_SKILL/scripts/new_tracker.py" --tracker-dir DIR
   --project NAME --slug SLUG --repository owner/repository --commit FULL_SHA
   --path docs/PLAN.md --date YYYY-MM-DD --workstreams N`. Replace all `TODO`
   placeholders with evidence before publication. If a tracker exists, update it
   instead of generating a second copy.

4. **Edit the structured state.** Keep these independent stage values:
   `scoping`, `discovery`, `issues`, `implementation`, `testing`, `delivery`, each
   `complete`, `partial` or `pending`. Completion of one does not set the others.
   A completed prompt proves its bounded deliverable only; merged code, passing
   checks, remote installation and accepted delivery require their own evidence.
   Do not derive a percentage from the six indicators. Preserve unsupported
   statuses and flag missing evidence rather than inventing progress.
   - `issues` complete means remaining work has linked open issues, not that
     issues are closed. A different third-stage label uses `issues_label` and
     `issues_note` in `config.json`; the state key stays `issues`.
   - `github_issues` contains `/issues/N` associations only. PRs, releases,
     documents and runs belong in `evidence_url`.
   - Preserve six indicators, five acceptance gates, three context panels and
     six callouts. Edit content, not geometry. Use single-line text per field.
   - Use `snapshot.evidence_ref` for the inspected revision and
     `extracted_from` for a committed source file. If sources differ, record the
     per-source revisions in the README; do not imply one SHA covers them all.
   - Keep secrets out of the state, rendered output and evidence records.

5. **Reconcile the narrative.** Update the README snapshot, workstream table,
   next action, evidence coverage and gaps to agree with state. Give each gap an
   owner or explicit external dependency and a destination. Link the workflow
   ledger rather than copying prompt statuses into a second authority. When the
   workflow ledger exists, run its `check --project-dir DIR` before publication;
   record known legacy exceptions without treating them as new verification.

6. **Render and verify.** Use `python3 "$TRACKER_SKILL/scripts/render_tracker.py" --tracker-dir DIR`, then
   `--check`; add `--png` only when `rsvg-convert` (librsvg) is installed. Never
   start Inkscape to export it: its command line launches the desktop
   application. Review the generated view for legibility and compare state,
   view and summary. `--check` detects rendering drift, not truth of project
   claims. Never edit rendered views by hand.

7. **Prepare the PR.** With publication authority, run
   `bash "$TRACKER_SKILL/scripts/tracker-finish.sh" --tracker-dir DIR`; otherwise add `--no-push`.
   The helper verifies ownership, renders, checks, optionally rebuilds the hub,
   and commits. A PNG is refreshed or refused, never silently left stale. Hub
   catalogs pin tracker commits, so tracker and hub are separate commits. Preserve
   their exact SHAs with a merge commit, or regenerate the catalog pins after any
   rebase or squash that rewrites them. The helper never
   merges. If a central viewer lives in another repository, prepare its separate
   rebuild/PR after the tracker revision is published; report any pending refresh.
   Report the PR, changed statuses and evidence, validations, unknowns,
   and next action. Preserve worktrees until the reviewed change is merged;
   follow the printed `wt.sh finish` and `check --for-removal` instructions.

## Migration and evaluation

Migrate an old self-contained tracker only when needed, with
`python3 "$TRACKER_SKILL/scripts/migrate_tracker.py" --tracker-dir DIR --project NAME --slug SLUG --dry-run`
first. It preserves recoverable evidence; review the diff before applying.

Use [evaluation](references/evaluation.md) to assess the next five real updates.
A successful render is a structural check. Judge whether a fresh reader can find
what changed, its evidence, unresolved work, and the next action without another
broad discovery pass.
