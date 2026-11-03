---
name: tracker
description: Add or refresh a project's status tracker in the operator's Obsidian notes repository — a schema-2 JSON state rendered into one self-contained HTML/SVG mind map with six stage indicators per workstream and five acceptance gates — and deliver it as a PR to the notes repo. Use when the user says /tracker, update the tracker, add a tracker for this project, refresh my notes tracker, or asks where a project stands and wants it recorded in their notes. Infers the project from the current repository.
---

# /tracker — project tracker in the notes repo

One tracker per project lives at `Projects/<Name>/Tracker/` in the operator's
notes repository (default `~/Obsidian/Personal`, GitHub `JonathanPorta/notes-personal`).
The tracker directory holds **state, not code**:

```
Projects/<Name>/Tracker/
  config.json                    workstream_count, project, slug, ref_label, issues_label
  <slug>-project-state.json      the only thing you edit by hand (schema_version 2)
  README.md                      narrative snapshot + workstream table + refresh steps
  <slug>-project-mindmap.html    rendered; one file, works offline
  <slug>-project-mindmap.svg     rendered
  <slug>-project-mindmap.png     rendered (Inkscape)
```

The renderer, templates, colours and schema live in this skill
(`scripts/render_tracker.py`, `assets/`). Never copy them into a tracker
directory and never edit rendered files by hand. `assets/example/` is a complete
two-workstream state you can read as the reference for every field.

## Installation

The skill is used from its installed path, so tracker READMEs can name one
command that works from any checkout:

```bash
ln -s ~/devel/portaj/ai-skills/skills/tracker ~/.claude/skills/tracker   # once
python3 ~/.claude/skills/tracker/scripts/render_tracker.py --help
```

## Invocation

| Form | Does |
|---|---|
| `/tracker` | Refresh the tracker for the project of the current repository; scaffold one if none exists |
| `/tracker new <Name>` | Scaffold a tracker for `<Name>` even if the cwd is unrelated |
| `/tracker hub` | Only rebuild the combined TrackerHub viewer |
| `/tracker --no-push` | Stop at local commits in the worktree; print the push and PR commands |

Resolve the project name from `gh repo view --json name` (strip the owner), or
from the operator's words when they name it. Multi-repo projects (for example
`porta.codes`, which spans three repositories) use one tracker with workstreams
grouped by repository, each workstream's `repository` field naming its repo.

## The sequence

1. **Begin in a worktree, never the live vault.** The Obsidian git plugin
   auto-commits the live checkout every few minutes, so any in-place edit lands
   on `main` before a PR exists.
   ```bash
   eval "$(scripts/tracker-begin.sh --project "<Name>")"
   # prints TRACKER_BRANCH, TRACKER_WORKTREE, TRACKER_DIR, TRACKER_SLUG, TRACKER_EXISTS
   ```
   It creates `jp/d/<slug>-tracker-<date>` from `origin/main` in a scratch
   worktree, plus a detached sibling worktree of the work vault (at the path the
   hub's `config.json` names) so the hub build can verify both. Pass
   `--base main` when the vault's local `main` is ahead of `origin/main` — the
   Obsidian backup plugin does not always push — and tell the operator the
   branch cannot be PR'd until `main` is.

2. **Gather evidence before touching the state.** Pull live facts with `gh`:
   merged PRs (`gh pr list --state merged`), open PRs and issues, latest
   releases, recent workflow runs, and the default-branch SHA. For a refresh,
   read the existing state first and change only what the evidence changed.
   Every claim in the map must be traceable to a PR, issue, release, run or
   commit; "it works" is not evidence.

3. **Scaffold if needed** (`TRACKER_EXISTS=0`):
   ```bash
   scripts/new_tracker.py --tracker-dir "$TRACKER_DIR" --project "<Name>" --slug "$TRACKER_SLUG" \
     --repository owner/repo --commit <full-sha> --path docs/PLAN.md --date YYYY-MM-DD --workstreams N
   ```
   Every placeholder is literally `TODO`; `tracker-finish.sh` refuses a state
   that still contains one.

4. **Edit `<slug>-project-state.json`.** Rules that keep the maps comparable:
   - Six stages per workstream, each independently `complete`, `partial` or
     `pending`: scoping, discovery, issues, implementation, testing, delivery.
     They are not a progress bar. Delivery means the workstream's own result is
     delivered, not that the product launched. Testing is evidence, not
     acceptance.
   - **Issues ✓ means the remaining work has open issues linked**, not that they
     are closed. Shipped workstreams normally show issues `pending` because
     finished work needs no retrospective issue. If a project uses the third
     stage differently (Plato: Approval; Workroom: Review), set
     `issues_label` and `issues_note` in `config.json`; the state key stays
     `issues`.
   - `github_issues` entries are **issues only** (`/issues/N` URLs; the renderer
     rejects anything else). PRs, docs, releases and runs go in `evidence_url`.
     The first issue on a workstream or task becomes the card's click target.
   - `color_stage` on a task is the kind of work its evidence shows, not a
     percentage. A workstream card takes the colour of its furthest complete
     stage.
   - Keep text to one line per field; the renderer rejects control characters
     and the cards do not wrap. Center-panel lines fit about 45 characters.
   - Exactly five acceptance gates, three context panels and six callouts; the
     template fixes their shape. Edit values, not structure.
   - `snapshot.evidence_ref` is the short SHA the map was read at;
     `extracted_from` names a committed file in the anchor repository.
   - **Secrets:** binding names, presence booleans and public identifiers only.
     No values, URLs with tokens, or state excerpts — the notes repo is
     committed and shared.

5. **Update `README.md`** in the tracker directory: the `**Snapshot: <date>.**`
   paragraph, the "Next" line and the workstream table must agree with the map.

6. **Finish.** Renders, verifies with `--check`, rebuilds TrackerHub, commits,
   and — with operator authority for the notes repository — pushes and opens
   the PR. It refuses to run anywhere but a worktree `tracker-begin.sh`
   recorded; when the hub exists it requires the work-vault sibling and a
   passing hub build before anything is pushed; and it re-renders the PNG with
   Inkscape or refuses to ship one (no Inkscape and a PNG or a README reference
   to one is an error — the image must never contradict the state). After a
   push it removes only the worktrees it created, only if they are clean;
   `--keep` skips that.
   ```bash
   scripts/tracker-finish.sh --tracker-dir "$TRACKER_DIR" [--title "docs: ..."] [--no-push]
   ```
   Two commits are made on purpose: the tracker, then the hub rebuild, because
   the hub catalog pins the tracker's commit SHA. Ask for the PR to be merged
   with **rebase**, not squash, so those pins stay resolvable. Lead the reply
   with the PR URL.

## Publication authority

`tracker-finish.sh` pushes a docs branch and opens a PR against the notes
repository's default branch. It never pushes to `main`. Run it with `--no-push`
unless the operator has authorised pushes and PRs for the notes repo in this
session (or a standing grant such as `PRRQ_PUBLICATION=push-allowed` applies).
Merging is the operator's, through their review gate.

## Renderer reference

```bash
scripts/render_tracker.py --tracker-dir DIR            # HTML + SVG
scripts/render_tracker.py --tracker-dir DIR --png      # + PNG (Inkscape)
scripts/render_tracker.py --tracker-dir DIR --check    # exit 1 if outputs differ from state
```

`config.json` keys: `workstream_count` (required, must equal the number of
workstreams), `project` (display name; default: `project.heading` before the
first ` · `), `slug` (file stem; default: from the state filename), `ref_label`
(caption words before the ref, e.g. `kioskit main`; default `main`),
`issues_label` (third-stage display name; default `Issues`), `issues_note`
(legend sentence; default `<label> ✓ means linked, not closed.`).

## TrackerHub

`Projects/TrackerHub/build.py` in the notes repo bundles every rendered map into
one offline `tracker-mindmaps.html`. It refuses uncommitted sources and expects
the work vault as a sibling directory named `notes-work`; `tracker-begin.sh`
arranges both. New trackers are discovered automatically — nothing to register.
