#!/usr/bin/env bash
# Start a tracker change: owned worktrees in a scratch task directory and a docs branch.
#
#   tracker-begin.sh --project <Name> [--notes DIR] [--work DIR] [--scratch DIR] [--date YYYY-MM-DD] [--base REF]
#
# Prints the paths to use. Never touches the operator's live vault checkout:
# the Obsidian git plugin auto-commits that checkout, so edits must happen in a
# worktree. The second worktree exists only so the TrackerHub build can verify
# the work vault's maps at the path the hub's config names. Every worktree this
# script creates is recorded in <task>/.tracker-worktrees; tracker-finish.sh
# removes only those, and only when they are clean.
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
case "$project" in */*|.*|*..*) printf 'project name must be a plain directory name\n' >&2; exit 2 ;; esac

slug="$(printf '%s' "$project" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
[ -n "$slug" ] || { printf 'could not derive a slug from %s\n' "$project" >&2; exit 2; }
branch="jp/d/${slug}-tracker-${date_tag}"
mkdir -p "$scratch"
scratch="$(cd "$scratch" && pwd -P)"
task="$scratch/tracker-${slug}-${date_tag}"
personal="$task/notes-personal"
marker="$task/.tracker-worktrees"

owned() { [ -f "$marker" ] && grep -qxF -- "$1" "$marker"; }
record() { printf '%s\n' "$1" >> "$marker"; }

git -C "$notes" fetch -q origin
default="$(git -C "$notes" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')"
default="${default:-main}"
base="${base:-origin/$default}"
mkdir -p "$task"
if [ -e "$personal" ]; then
  if ! owned "$personal"; then
    printf '%s exists but was not created by tracker-begin.sh; refusing to reuse it\n' "$personal" >&2
    exit 2
  fi
  printf 'reusing owned worktree %s\n' "$personal" >&2
else
  if git -C "$notes" show-ref -q --verify "refs/heads/$branch"; then
    git -C "$notes" worktree add -q "$personal" "$branch"
  else
    git -C "$notes" worktree add -q -b "$branch" "$personal" "$base"
  fi
  record "$personal"
fi

# TrackerHub names where it expects the work vault, relative to its own
# directory. Honour that path, but only inside this task directory, so a config
# can never point cleanup at a worktree this script did not create.
hub="$personal/Projects/TrackerHub/build.py"
sibling=""
if [ -f "$hub" ]; then
  # Containment is checked on the resolved filesystem path: the nearest existing
  # ancestor is realpath'd so a symlinked parent cannot point the worktree (and
  # the later cleanup) outside the task directory.
  sibling="$(python3 - "$personal/Projects/TrackerHub/config.json" "$task" <<'PY'
import json, os, sys
config, task = sys.argv[1], os.path.realpath(sys.argv[2])
hub_dir = os.path.join(task, 'notes-personal', 'Projects', 'TrackerHub')
target = None
for repo in json.load(open(config))['repositories']:
    if repo['repository'].endswith('/notes-work'):
        target = os.path.normpath(os.path.join(hub_dir, repo['root']))
        break
if target is None:
    sys.exit(0)
existing = target
while not os.path.exists(existing):
    existing = os.path.dirname(existing)
resolved = os.path.realpath(existing)
if resolved != task and not resolved.startswith(task + os.sep):
    print('OUTSIDE ' + target)
    sys.exit(0)
print(target)
PY
)"
  [ -n "$sibling" ] || { printf 'TrackerHub config names no notes-work repository\n' >&2; exit 2; }
  case "$sibling" in
    OUTSIDE\ *) printf 'TrackerHub config resolves the work vault to %s, outside the task directory; refusing\n' "${sibling#OUTSIDE }" >&2; exit 2 ;;
  esac
  if [ ! -d "$work/.git" ] && [ ! -f "$work/.git" ]; then
    printf 'TrackerHub exists but the work vault is not at %s; set TRACKER_WORK_REPO or --work\n' "$work" >&2
    exit 2
  fi
  if [ -e "$sibling" ]; then
    if ! owned "$sibling"; then
      printf '%s exists but was not created by tracker-begin.sh; refusing\n' "$sibling" >&2
      exit 2
    fi
  else
    # The hub must verify the work vault's maps as published, not as the local
    # checkout happens to be, so the sibling is detached at origin's default
    # branch (falling back to the local HEAD when there is no remote).
    work_ref="HEAD"
    if git -C "$work" fetch -q origin 2>/dev/null; then
      work_default="$(git -C "$work" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')"
      work_ref="origin/${work_default:-main}"
      git -C "$work" rev-parse -q --verify "$work_ref^{commit}" >/dev/null 2>&1 || work_ref="HEAD"
    fi
    git -C "$work" worktree add -q --detach "$sibling" "$work_ref"
    record "$sibling"
  fi
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
[ -n "$sibling" ] && printf 'TRACKER_WORK_SIBLING=%s\n' "$sibling"
exit 0
