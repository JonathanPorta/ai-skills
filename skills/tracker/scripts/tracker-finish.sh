#!/usr/bin/env bash
# Finish a tracker change: render, verify, rebuild TrackerHub, commit, push, open the PR.
#
#   tracker-finish.sh --tracker-dir DIR [--title "..."] [--no-pr] [--no-push] [--keep]
#
# Two commits are made on the branch: the tracker itself, then the TrackerHub
# rebuild (its catalog pins the tracker's commit, so it cannot be the same
# commit). Push and PR creation happen only with explicit operator authority
# for the notes repository; pass --no-push to stop at the local commits.
#
# Guarantees:
#   - runs only in a worktree recorded by tracker-begin.sh, never the live vault;
#   - when TrackerHub exists, its work-vault sibling must be present and the hub
#     build and check must pass before anything is pushed;
#   - a PNG is either re-rendered by Inkscape or refused; a stale image never ships;
#   - cleanup removes only owned worktrees, only after a push, only when clean,
#     and never with --force.
set -euo pipefail

skill_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
render="$skill_dir/scripts/render_tracker.py"
tracker_dir=""
title=""
open_pr=1
push=1
keep=0
while [ $# -gt 0 ]; do
  case "$1" in
    --tracker-dir) tracker_dir="$2"; shift 2 ;;
    --title) title="$2"; shift 2 ;;
    --no-pr) open_pr=0; shift ;;
    --no-push) push=0; open_pr=0; shift ;;
    --keep) keep=1; shift ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done
[ -n "$tracker_dir" ] || { printf -- '--tracker-dir is required\n' >&2; exit 2; }
tracker_dir="$(cd "$tracker_dir" && pwd -P)"
worktree="$(git -C "$tracker_dir" rev-parse --show-toplevel)"
worktree="$(cd "$worktree" && pwd -P)"
task="$(dirname "$worktree")"
marker="$task/.tracker-worktrees"
owned() { [ -f "$marker" ] && grep -qxF -- "$1" "$marker"; }

if [ ! -f "$worktree/.git" ] || ! owned "$worktree"; then
  # A linked worktree has a .git file; the live checkout has a .git directory.
  # Either way, only a worktree tracker-begin.sh recorded may be finished.
  printf 'refusing: %s is not a worktree created by tracker-begin.sh\n' "$worktree" >&2
  exit 2
fi
branch="$(git -C "$worktree" rev-parse --abbrev-ref HEAD)"
default="$(git -C "$worktree" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')"
default="${default:-main}"
case "$branch" in
  "$default"|master|HEAD) printf 'refusing to finish on %s; run tracker-begin.sh first\n' "$branch" >&2; exit 2 ;;
esac

rel="${tracker_dir#"$worktree"/}"
project="$(basename "$(dirname "$tracker_dir")")"
state_file="$(ls "$tracker_dir"/*-project-state.json 2>/dev/null | head -1)"
[ -n "$state_file" ] || { printf 'no *-project-state.json in %s\n' "$tracker_dir" >&2; exit 1; }
if grep -q 'TODO' "$state_file"; then
  printf 'the state file still contains TODO placeholders\n' >&2
  exit 1
fi
stem="$(basename "$state_file" -project-state.json)-project-mindmap"

# When the hub exists, its sibling must be usable before anything is committed.
hub="$worktree/Projects/TrackerHub/build.py"
sibling=""
if [ -f "$hub" ]; then
  sibling="$(python3 - "$worktree/Projects/TrackerHub/config.json" "$worktree" <<'PY'
import json, os, sys
config, worktree = sys.argv[1], sys.argv[2]
for repo in json.load(open(config))['repositories']:
    if repo['repository'].endswith('/notes-work'):
        print(os.path.normpath(os.path.join(worktree, 'Projects', 'TrackerHub', repo['root'])))
        break
PY
)"
  if [ -z "$sibling" ] || [ ! -d "$sibling" ] || ! owned "$sibling"; then
    printf 'TrackerHub exists but its work-vault sibling is missing or not owned (%s); run tracker-begin.sh again\n' "${sibling:-unset}" >&2
    exit 1
  fi
fi

# The PNG is part of what ships. Re-render it or refuse to publish a stale one.
inkscape=""
if [ -z "${TRACKER_NO_PNG:-}" ]; then
  inkscape="$(command -v inkscape || true)"
fi
if [ -n "$inkscape" ]; then
  python3 "$render" --tracker-dir "$tracker_dir" --png
  png_note="PNG rendered with $("$inkscape" --version 2>/dev/null | head -1 || printf 'Inkscape')."
else
  if [ -f "$tracker_dir/$stem.png" ]; then
    printf 'Inkscape is not available and %s.png exists; it cannot be refreshed, so it would ship stale. Install Inkscape or delete the PNG and its README references.\n' "$stem" >&2
    exit 1
  fi
  if grep -q "$stem.png" "$tracker_dir/README.md" 2>/dev/null; then
    printf 'README.md references %s.png but no PNG can be rendered here; remove the reference or install Inkscape.\n' "$stem" >&2
    exit 1
  fi
  python3 "$render" --tracker-dir "$tracker_dir"
  png_note="No PNG shipped (Inkscape unavailable)."
fi
python3 "$render" --tracker-dir "$tracker_dir" --check
if ! grep -q 'Snapshot' "$tracker_dir/README.md"; then
  printf 'README.md has no Snapshot line; update the narrative with the map\n' >&2
  exit 1
fi

git -C "$worktree" add -A -- "$rel"
: "${title:=docs: Update The $project Project Tracker}"
if git -C "$worktree" diff --cached --quiet; then
  # Resuming after an earlier failure: the tracker commit may already be HEAD.
  if git -C "$worktree" diff --quiet "HEAD~1" HEAD -- "$rel" 2>/dev/null; then
    printf 'nothing changed under %s\n' "$rel" >&2
    exit 1
  fi
  printf 'tracker already committed at HEAD; continuing\n' >&2
else
  git -C "$worktree" commit -q -m "$title" -m "HTML and SVG verified against the state with render_tracker.py --check. $png_note"
fi
tracker_commit="$(git -C "$worktree" rev-parse --short HEAD)"

hub_commit=""
if [ -f "$hub" ]; then
  (cd "$worktree" && python3 "$hub")
  (cd "$worktree" && python3 "$hub" --check)
  git -C "$worktree" add -A -- Projects/TrackerHub/catalog.json tracker-mindmaps.html
  if ! git -C "$worktree" diff --cached --quiet; then
    git -C "$worktree" commit -q -m "docs: Rebuild TrackerHub With The $project Tracker"
    hub_commit="$(git -C "$worktree" rev-parse --short HEAD)"
  fi
fi

printf 'TRACKER_COMMIT=%s\n' "$tracker_commit"
[ -n "$hub_commit" ] && printf 'HUB_COMMIT=%s\n' "$hub_commit"
if [ "$push" -eq 1 ]; then
  git -C "$worktree" push -q -u origin "$branch"
  if [ "$open_pr" -eq 1 ]; then
    existing="$(gh pr list --repo "$(git -C "$worktree" remote get-url origin)" --head "$branch" --json url --jq '.[0].url' 2>/dev/null || true)"
    if [ -n "$existing" ]; then
      printf 'PR_URL=%s\n' "$existing"
    else
      body_file="$(mktemp)"
      {
        printf '## Tracker\n\n- `%s` rendered; HTML and SVG verified with `render_tracker.py --check`. %s\n' "$rel" "$png_note"
        if [ -n "$hub_commit" ]; then
          printf -- '- TrackerHub rebuilt (`build.py --check` passes).\n'
        fi
        printf '\n🤖 Generated with [Claude Code](https://claude.com/claude-code)\n'
      } > "$body_file"
      url="$(cd "$worktree" && gh pr create --base "$default" --head "$branch" --title "$title" --body-file "$body_file")"
      rm -f "$body_file"
      printf 'PR_URL=%s\n' "$url"
    fi
  fi
fi

# Cleanup is opt-out, post-push only, owned worktrees only, clean only, never forced.
if [ "$keep" -eq 0 ] && [ "$push" -eq 1 ]; then
  kept=0
  task_real="$(cd "$task" && pwd -P)"
  while IFS= read -r wt; do
    [ -d "$wt" ] || continue
    wt_real="$(cd "$wt" && pwd -P)"
    case "$wt_real" in
      "$task_real"/*) ;;
      *) printf 'keeping %s: it resolves outside the task directory\n' "$wt" >&2; kept=1; continue ;;
    esac
    if [ -n "$(git -C "$wt" status --porcelain 2>/dev/null)" ]; then
      printf 'keeping %s: it has uncommitted or untracked changes\n' "$wt" >&2
      kept=1
      continue
    fi
    repo="$(dirname "$(git -C "$wt" rev-parse --path-format=absolute --git-common-dir)")"
    if ! git -C "$repo" worktree remove "$wt" 2>/dev/null; then
      printf 'keeping %s: git refused to remove it\n' "$wt" >&2
      kept=1
    fi
  done < "$marker"
  if [ "$kept" -eq 0 ]; then
    rm -f "$marker"
    rmdir "$task" 2>/dev/null || true
  fi
fi
exit 0
