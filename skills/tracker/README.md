# Tracker

Keeps one status tracker per project in the operator's Obsidian notes repository:
a small JSON state file rendered into a single self-contained HTML mind map, with
six independent stage indicators per workstream and five acceptance gates, and
delivered as a PR to the notes repo.

## Why

Eleven trackers were built by eleven sessions, each carrying its own copy of the
renderer, templates and tests. They drifted: four stage vocabularies, two state
schemas, a second loader design. This skill owns the renderer once, so tracker
directories hold only state and rendered output, and every map reads the same way.

## Contents

- `SKILL.md` — the sequence: worktree, evidence, state edit, render, hub rebuild, PR.
- `scripts/render_tracker.py` — validates `<slug>-project-state.json` + `config.json`
  and renders HTML, SVG and (with Inkscape) PNG; `--check` proves outputs match.
- `scripts/new_tracker.py` — scaffolds a tracker directory with `TODO` placeholders.
- `scripts/migrate_tracker.py` — converts a tracker that carries its own renderer
  (schema 1, or schema 2 with renamed fields/stages) onto the shared one, recovering
  template-held text by coordinate and carrying dropped notes into the README.
- `scripts/tracker-begin.sh` — task worktrees for the notes and work vaults, made by
  the ai-scratch helper `wt.sh start` under `~/devel/worktrees/portaj/<vault>/<task>`
  with ownership records, and a `jp/d/<slug>-tracker-<date>` branch; never touches
  the live vault or its checked-out branch, and never writes under `/private/tmp`.
- `scripts/tracker-finish.sh` — render, verify, rebuild TrackerHub, commit twice,
  push and open the PR (or stop at local commits with `--no-push`). Runs only in a
  `wt.sh` worktree with an ownership record; when the hub exists the task's
  work-vault worktree must be present and the hub build and check (`--root`) must
  pass before any push; a PNG is re-rendered by Inkscape or refused. It removes
  nothing: after the merge, `wt.sh finish`/`check` handle release and removal.
- `assets/templates/` — the SVG and HTML templates; the design lives here.
- `assets/state.schema.json`, `assets/config.schema.json` — JSON Schemas.
- `assets/example/` — a complete two-workstream reference state.

## Design invariants

Stage colours, card geometry, the six-stage vocabulary (`scoping`, `discovery`,
`issues`, `implementation`, `testing`, `delivery`), five acceptance gates, three
context panels and six callouts are fixed by the templates. Projects that call the
third stage something else set `issues_label` / `issues_note` in `config.json`;
the state key does not change. `github_issues` holds issues only; everything else
is `evidence_url`.

## Verification

`tests/test_tracker.py` renders the example state, proves `--check` detects a
changed state, exercises the validation rejections (bad stage, bad URL, PR where an
issue is required, mismatched workstream count, duplicate JSON keys), confirms the
issue chip links only when an issue is attached, proves a project name cannot
inject an HTML attribute, and scaffolds a tracker end to end. The workflow tests
run `tracker-begin.sh` and `tracker-finish.sh` against disposable notes and work
repositories with a stub TrackerHub: worktrees under `WT_ROOT` with ownership
records, nothing in the scratch root, the primaries left on their branch; tracker
then hub commits; refusal of the live checkout, of worktrees without a record, of a
missing work vault, of a missing hub sibling (before any commit), and of a stale or
dangling PNG; nothing created at a config path that escapes; and a finish that
pushes but removes nothing and hands off to `wt.sh`. The renderer was also diffed against the existing
Kioskit and porta.codes trackers: SVG identical apart from quote escaping, HTML
differing only in the configurable snapshot caption.
