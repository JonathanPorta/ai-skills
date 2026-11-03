# Plan: consolidate the notes trackers onto the `tracker` skill

Status: proposed 2026-11-03 with the skill's first PR. Owner of the tracker PRs:
the review.porta.codes session (`review-porta-codes-63`) until handed off.

## What exists today (notes-personal, 2026-11-03)

Fifteen `Projects/<Name>/Tracker/` directories (as of the 12:00 vault backup; sessions are still adding them), each carrying its own copy of a
renderer, templates and tests. Five lineages:

| Lineage | Trackers | Renderer | State | Third stage |
|---|---|---|---|---|
| A — canonical | Kioskit, MainsKeeper, Nits Up, Slack Router, porta.codes, PMCP (self-converted from D on 11-03), Broadwater Center (new, unverified) | 367 lines, identical except the caption string | schema 2 | `issues` |
| A′ — renamed stage | Plato (`approval`), Workroom (`review`) | A with the stage key renamed; Workroom also dropped URL validation | schema 2 | key renamed |
| B — older | AI Usage, CommsCore | 353 lines, `planning` stage | schema 1 | `planning` |
| C — fork | DocSort | 645 lines; computes its own layout; `evidence_urls` lists | schema 2 | `issues` |
| D — shared loader | Cleankeys, ProofGlass, Park Patrol | 305–315 lines; HTML fetches its SVG + `tracker-state.json` at runtime | `cleankeys-tracker/v1` ("areas") | n/a |

Plus `Projects/TrackerHub/` (the combined offline viewer: 13 → 15 → 18 maps across the
2026-11-03 rebuilds; its `config.json` now expects the work vault at `../../../Work`,
which `tracker-begin.sh` reads rather than assumes) and the work vault's EBCD tracker (the original design, A's
ancestor).

The skill renderer reproduces lineage A byte for byte (Kioskit and porta.codes
SVGs identical; HTML differs only in the now-configurable caption) and A′ with
`issues_label`/`issues_note` set (Plato: 16 diff lines, all the renamed label and
the sentence it configures).

## Target

- One renderer, in the skill. Tracker directories hold `config.json`,
  `<slug>-project-state.json`, `README.md`, the three rendered files and
  `.gitignore`. No `render_tracker.py`, `test_*.py`, `templates/`,
  `*.schema.json`, `__pycache__`.
- One state schema (schema 2) and one stage vocabulary (`issues` as the key;
  display label per project).
- Every tracker in TrackerHub; the hub pins resolvable on GitHub.
- Every tracker produced or refreshed through `/tracker`, in a worktree, by PR.

## Phases

### Phase 0 — land the skill (this PR)

ai-skills PR adds `skills/tracker/`. Install it beside the others
(`~/.claude/skills/tracker -> ai-skills/skills/tracker`). No tracker changes.

### Phase 1 — lineage A and A′ (9 trackers, mechanical)

One notes PR per tracker, each from `/tracker` with `--base` on the current
main, containing:

1. delete `render_tracker.py`, `test_tracker.py`, `templates/`, `*.schema.json`,
   `__pycache__/`;
2. add `project`, `slug`, `ref_label` (and for Plato/Workroom `issues_label`,
   `issues_note`) to `config.json`;
3. Plato/Workroom only: rename the stage key `approval`/`review` → `issues` in
   the state (stage dict and task `color_stage`); labels stay as they were;
4. re-render with the skill; the SVG must be byte-identical for A (prove it in
   the PR body with `cmp`), label-only diffs for A′;
5. rewrite the README "Refresh" section to the skill command;
6. rebuild the hub.

Order: porta.codes first — done as the rehearsal: local branch
`jp/d/porta-codes-tracker-20261103` in notes-personal (two commits, SVG identical
but for the configurable caption, hub rebuilt at 18 maps), awaiting push once the
vault's own `main` is pushed — then Kioskit, Nits Up, MainsKeeper, Slack Router,
PMCP, Broadwater Center, Plato, Workroom. Each is rebase-merged.

### Phase 2 — lineage B (AI Usage, CommsCore)

Write `scripts/migrate_state.py` in the skill: schema 1 → 2. Expected mapping:
`planning` → `issues` (label "Planning"), task/issue field renames, and whatever
B's templates carried that A's do not (diff the two template sets first; the
353-line renderer predates the issue-link and evidence-link blocks). Render,
compare PNGs side by side, PR per tracker. Anything B's map showed that A's
cannot is either added to the skill templates (if the other maps benefit) or
dropped with a note in the PR.

### Phase 3 — lineage C (DocSort)

DocSort's renderer computes its own geometry and allows `evidence_urls` lists.
Decide with the operator: (a) migrate to A, collapsing `evidence_urls` to the
first URL plus the rest in the README table, or (b) adopt the list form into the
skill (render the first, link the rest in the card title). Recommendation: (a);
no other tracker asked for lists.

### Phase 4 — lineage D (Cleankeys, ProofGlass, Park Patrol, PMCP)

These are a different design: `areas` with per-card evidence panels, loaded at
runtime from adjacent files (which is why TrackerHub needs the bundling adapter).
Three trackers; PMCP already moved itself to A, so a conversion script
(`areas` → `workstreams`, evidence panel text → task `description` +
`evidence_url`) is worth writing. Convert after the owning sessions finish their
current work; coordinate through the sessions list. Once none remain, remove the
`LOCAL_LOADER` adapter from `TrackerHub/build.py`.

### Phase 5 — TrackerHub

- Fix the sibling-path assumption: `config.json` roots become configurable via
  env (`TRACKER_WORK_REPO`) with the sibling as the fallback.
- Pin resolution: when a map's HEAD commit is not on `origin/main`, retain the
  previous pin if the blob matches, else record `pending` and let the next
  post-merge rebuild pin it. Removes the rebase-merge requirement.
- Hub rebuild becomes a step in `/tracker hub` and a scheduled post-merge job.
- README counts generated from the catalog.

### Phase 6 — retire the copies

Delete the per-tracker renderers from git once Phases 1–4 are merged; add a
notes-repo check (`make check` or a CI job) that fails if any `Tracker/` holds a
`.py` file.

## Rules while this runs

- Tracker PRs to notes-personal are owned by one session at a time; other
  sessions keep creating trackers with the skill from Phase 0 on, not by copying
  a sibling directory.
- Never edit the live vault checkout; the Obsidian git plugin auto-commits it.
- Rebase-merge tracker PRs until Phase 5 lands.
- Binding names, numbers and booleans only in any tracker; no secret values.
