#!/usr/bin/env bash
# Start a tracker change: two sibling worktrees in scratch and a docs branch.
#
#   tracker-begin.sh --project <Name> [--notes DIR] [--work DIR] [--scratch DIR] [--date YYYY-MM-DD] [--base REF]
#
# Prints the paths to use. Never touches the operator's live vault checkout:
# the Obsidian git plugin auto-commits that checkout, so edits must happen in a
# worktree. The second worktree exists only so the TrackerHub build can verify
# the work vault's maps at the sibling path its config expects.
set -euo pipefail

notes="${TRACKER_NOTES_REPO:-$HOME/Obsidian/Personal}"
work="${TRACKER_WORK_REPO:-$HOME/Obsidian/Work}"
scratch="${AI_SCRATCH_ROOT:-/tmp/ai-scratch}"
project=""
base=""
date_tag="$(date +%Y%m%d)"
while [ $# -gt 0 ]; do
  case "$1" in
    --project) project="$2"; shift 2 ;;
    --notes) notes="$2"; shift 2 ;;
    --work) work="$2"; shift 2 ;;
    --scratch) scratch="$2"; shift 2 ;;
    --date) date_tag="${2//-/}"; shift 2 ;;
    --base) base="$2"; shift 2 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done
[ -n "$project" ] || { printf -- '--project is required\n' >&2; exit 2; }
[ -d "$notes/.git" ] || [ -f "$notes/.git" ] || { printf 'notes checkout not found: %s\n' "$notes" >&2; exit 2; }

slug="$(printf '%s' "$project" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
[ -n "$slug" ] || { printf 'could not derive a slug from %s\n' "$project" >&2; exit 2; }
branch="jp/d/${slug}-tracker-${date_tag}"
task="$scratch/tracker-${slug}-${date_tag}"
personal="$task/notes-personal"
sibling="$task/notes-work"

git -C "$notes" fetch -q origin
default="$(git -C "$notes" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')"
default="${default:-main}"
base="${base:-origin/$default}"
mkdir -p "$task"
if [ -e "$personal" ]; then
  printf 'reusing existing worktree %s\n' "$personal" >&2
else
  if git -C "$notes" show-ref -q --verify "refs/heads/$branch"; then
    git -C "$notes" worktree add -q "$personal" "$branch"
  else
    git -C "$notes" worktree add -q -b "$branch" "$personal" "$base"
  fi
fi
# TrackerHub's config names where it expects the work vault, relative to its own
# directory; honour that so the hub rebuild can verify both vaults.
hub_config="$personal/Projects/TrackerHub/config.json"
if [ -f "$hub_config" ]; then
  sibling="$(python3 - "$hub_config" "$task" <<'PY'
import json, os, sys
config, task = sys.argv[1], sys.argv[2]
hub_dir = os.path.join(task, 'notes-personal', 'Projects', 'TrackerHub')
for repo in json.load(open(config))['repositories']:
    if repo['repository'].endswith('/notes-work'):
        print(os.path.normpath(os.path.join(hub_dir, repo['root'])))
        break
PY
)"
  sibling="${sibling:-$task/notes-work}"
fi
if [ -d "$work/.git" ] || [ -f "$work/.git" ]; then
  if [ ! -e "$sibling" ]; then
    git -C "$work" worktree add -q --detach "$sibling" HEAD
  fi
else
  printf 'work vault not found at %s; TrackerHub rebuild will be skipped\n' "$work" >&2
fi

tracker_dir="$personal/Projects/$project/Tracker"
printf 'TRACKER_BRANCH=%s\n' "$branch"
printf 'TRACKER_WORKTREE=%s\n' "$personal"
printf 'TRACKER_DIR=%s\n' "$tracker_dir"
printf 'TRACKER_SLUG=%s\n' "$slug"
if [ -d "$tracker_dir" ]; then
  printf 'TRACKER_EXISTS=1\n'
else
  printf 'TRACKER_EXISTS=0\n'
fi
printf 'TRACKER_WORK_SIBLING=%s\n' "$sibling"
