#!/usr/bin/env bash
# Finish a tracker change: render, verify, rebuild TrackerHub, commit, push, open the PR.
#
#   tracker-finish.sh --tracker-dir DIR [--title "..."] [--no-pr] [--no-push] [--keep]
#
# Two commits are made on the branch: the tracker itself, then the TrackerHub
# rebuild (its catalog pins the tracker's commit, so it cannot be the same
# commit). Push and PR creation happen only with explicit operator authority
# for the notes repository; pass --no-push to stop at the local commits.
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
tracker_dir="$(cd "$tracker_dir" && pwd)"
worktree="$(git -C "$tracker_dir" rev-parse --show-toplevel)"
branch="$(git -C "$worktree" rev-parse --abbrev-ref HEAD)"
default="$(git -C "$worktree" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')"
default="${default:-main}"
case "$branch" in
  "$default"|master|HEAD) printf 'refusing to finish on %s; run tracker-begin.sh first\n' "$branch" >&2; exit 2 ;;
esac
if [ ! -f "$worktree/.git" ]; then
  # A linked worktree has a .git file; the live checkout has a .git directory.
  printf 'refusing to run in the live vault checkout; use the worktree from tracker-begin.sh\n' >&2
  exit 2
fi
main_repo="$(dirname "$(git -C "$worktree" rev-parse --path-format=absolute --git-common-dir)")"

rel="${tracker_dir#"$worktree"/}"
project="$(basename "$(dirname "$tracker_dir")")"
if grep -rq 'TODO' "$tracker_dir"/*-project-state.json; then
  printf 'the state file still contains TODO placeholders\n' >&2
  exit 1
fi
if command -v inkscape >/dev/null 2>&1; then
  python3 "$render" --tracker-dir "$tracker_dir" --png
else
  python3 "$render" --tracker-dir "$tracker_dir"
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
  git -C "$worktree" commit -q -m "$title" -m "Rendered with the tracker skill; outputs verified with --check."
fi
tracker_commit="$(git -C "$worktree" rev-parse --short HEAD)"

hub="$worktree/Projects/TrackerHub/build.py"
hub_commit=""
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
  if [ -n "$sibling" ] && [ -d "$sibling" ]; then
    (cd "$worktree" && python3 "$hub")
    (cd "$worktree" && python3 "$hub" --check)
    git -C "$worktree" add -A -- Projects/TrackerHub/catalog.json tracker-mindmaps.html
    if ! git -C "$worktree" diff --cached --quiet; then
      git -C "$worktree" commit -q -m "docs: Rebuild TrackerHub With The $project Tracker"
      hub_commit="$(git -C "$worktree" rev-parse --short HEAD)"
    fi
  else
    printf 'no sibling notes-work worktree; skipping the TrackerHub rebuild\n' >&2
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
        printf '## Tracker\n\n- `%s` rendered and verified with `render_tracker.py --check`.\n' "$rel"
        [ -n "$hub_commit" ] && printf -- '- TrackerHub rebuilt (`build.py --check` passes).\n'
        printf '\nMerge with **rebase** (not squash): the hub catalog pins the tracker commit by SHA.\n\n'
        printf '🤖 Generated with [Claude Code](https://claude.com/claude-code)\n'
      } > "$body_file"
      url="$(cd "$worktree" && gh pr create --base "$default" --head "$branch" --title "$title" --body-file "$body_file")"
      rm -f "$body_file"
      printf 'PR_URL=%s\n' "$url"
    fi
  fi
fi
if [ "$keep" -eq 0 ] && [ "$push" -eq 1 ]; then
  if [ -n "${sibling:-}" ] && [ -f "$sibling/.git" ]; then
    sibling_repo="$(dirname "$(git -C "$sibling" rev-parse --path-format=absolute --git-common-dir)")"
    git -C "$sibling_repo" worktree remove --force "$sibling" 2>/dev/null || true
  fi
  git -C "$main_repo" worktree remove --force "$worktree" 2>/dev/null || true
fi
