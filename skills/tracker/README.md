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
- `scripts/tracker-begin.sh` — scratch worktrees for the notes and work vaults and a
  `jp/d/<slug>-tracker-<date>` branch; never touches the live vault. Records every
  worktree it creates in `<task>/.tracker-worktrees` and refuses a hub config whose
  work-vault path resolves outside the task directory.
- `scripts/tracker-finish.sh` — render, verify, rebuild TrackerHub, commit twice,
  push and open the PR (or stop at local commits with `--no-push`). Runs only in an
  owned worktree; when the hub exists its sibling must be present and the hub build
  and check must pass before any push; a PNG is re-rendered by Inkscape or refused;
  cleanup removes only owned, clean worktrees, after a push, never with `--force`.
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
repositories with a stub TrackerHub: tracker then hub commits; refusal of the live
checkout, of unowned worktrees, of a hub root outside the task directory, of a
missing work vault, of a missing hub sibling (before any commit), and of a stale or
dangling PNG; and cleanup that keeps a dirty worktree's untracked file and removes
only owned, clean worktrees. The renderer was also diffed against the existing
Kioskit and porta.codes trackers: SVG identical apart from quote escaping, HTML
differing only in the configurable snapshot caption.
