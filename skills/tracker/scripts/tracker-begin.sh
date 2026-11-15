#!/usr/bin/env bash
# Start an owned tracker task worktree. Paths come from explicit options,
# environment overrides or the notes repository's .tracker-workflow.json.
# The live notes checkout and any hub companion checkout are never edited.
# Set WT_OWNER to the session id first (see the ai-scratch wt.sh helper).
set -euo pipefail

skill_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
wt="${TRACKER_WT:-$skill_dir/../ai-scratch/scripts/wt.sh}"
notes="${TRACKER_NOTES_REPO:-}"
work="${TRACKER_WORK_REPO:-}"
config=""
project=""
base=""
date_tag="$(date +%Y%m%d)"
while [ $# -gt 0 ]; do
  case "$1" in
    --project) project="$2"; shift 2 ;;
    --notes) notes="$2"; shift 2 ;;
    --work) work="$2"; shift 2 ;;
    --config) config="$2"; shift 2 ;;
    --date) date_tag="${2//-/}"; shift 2 ;;
    --base) base="$2"; shift 2 ;;
    --scratch) printf -- '--scratch is gone: tracker worktrees come from wt.sh under its configured worktree root\n' >&2; exit 2 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done
[ -n "$project" ] || { printf -- '--project is required\n' >&2; exit 2; }
notes="${notes:-$(git rev-parse --show-toplevel 2>/dev/null || true)}"
[ -n "$notes" ] || { printf 'set TRACKER_NOTES_REPO or pass --notes DIR\n' >&2; exit 2; }
[ -d "$notes/.git" ] || [ -f "$notes/.git" ] || { printf 'notes checkout not found: %s\n' "$notes" >&2; exit 2; }
[ -x "$wt" ] || { printf 'wt.sh not found at %s; install the ai-scratch skill or set TRACKER_WT\n' "$wt" >&2; exit 2; }
[ -n "${WT_OWNER:-}" ] || { printf 'set WT_OWNER to this session id first, so the ownership records tell sessions apart\n' >&2; exit 2; }
case "$project" in */*|.*|*..*) printf 'project name must be a plain directory name\n' >&2; exit 2 ;; esac

slug="$(printf '%s' "$project" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
[ -n "$slug" ] || { printf 'could not derive a slug from %s\n' "$project" >&2; exit 2; }
work_override="$work"
settings=(--repo "$notes" --project "$project")
[ -n "$config" ] && settings+=(--config "$config")
settings_shell="$(python3 "$skill_dir/scripts/workflow_config.py" "${settings[@]}")" || exit 2
eval "$settings_shell"
work="${work:-$tracker_companion_checkout}"
branch="${TRACKER_BRANCH_PREFIX:-$tracker_branch_prefix}/${slug}-tracker-${date_tag}"
git check-ref-format --branch "$branch" >/dev/null || exit 2
task="tracker-${slug}-${date_tag}"

# wt_start <vault> <branch> <base> <purpose>: prints the worktree path wt.sh created or resumed.
wt_start() {
  local vault parent out
  vault="$(cd "$1" && pwd -P)"; parent="$(dirname "$vault")"
  out="$(WT_PRIMARIES="$parent" "$wt" start "$(basename "$vault")" "$task" --branch "$2" --base "$3" --purpose "$4")" || exit 2
  printf '%s\n' "$out" | sed -n 's/^WT_PATH=//p'
}

git -C "$notes" fetch -q origin
default="$(git -C "$notes" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')"
default="${default:-main}"
personal="$(wt_start "$notes" "$branch" "${base:-origin/$default}" "$project tracker update")"
[ -n "$personal" ] || { printf 'wt.sh did not report a worktree path\n' >&2; exit 2; }

# Recheck paths against the actual selected worktree, including its symlinks.
settings=(--repo "$personal" --checkout-root "$(cd "$notes" && pwd -P)" --project "$project")
[ -n "$config" ] && settings+=(--config "$config")
settings_shell="$(python3 "$skill_dir/scripts/workflow_config.py" "${settings[@]}")" || exit 2
eval "$settings_shell"
work="${work_override:-$tracker_companion_checkout}"
hub="$personal/$tracker_hub_script"
sibling=""
if [ -f "$hub" ]; then
  work_repo="$(python3 "$skill_dir/scripts/workflow_config.py" --repo "$personal" --hub-repository "$tracker_companion_repository" --hub-config "$tracker_hub_config")"
  if [ -n "$work_repo" ]; then
    if [ ! -d "$work/.git" ] && [ ! -f "$work/.git" ]; then
      printf 'TrackerHub exists but the work vault is not at %s; set TRACKER_WORK_REPO or --work\n' "$work" >&2
      exit 2
    fi
    # The hub must verify the work vault's maps as published, not as the local
    # checkout happens to be. wt.sh always checks out a branch, so the work-vault
    # worktree gets its own local <branch>-hub-input branch at origin's default
    # (local HEAD without a remote). Nothing commits to it or pushes it; on a
    # resumed task it is fast-forwarded, and a branch that cannot fast-forward is refused.
    work_ref="HEAD"
    if git -C "$work" fetch -q origin 2>/dev/null; then
      work_default="$(git -C "$work" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')"
      work_ref="origin/${work_default:-main}"
      git -C "$work" rev-parse -q --verify "$work_ref^{commit}" >/dev/null 2>&1 || work_ref="HEAD"
    fi
    # Resolve in the primary: inside the work worktree, HEAD would mean its own HEAD.
    work_ref="$(git -C "$work" rev-parse "$work_ref^{commit}")"
    sibling="$(wt_start "$work" "$branch-hub-input" "$work_ref" "TrackerHub build input for the $project tracker (never committed to or pushed)")"
    [ -n "$sibling" ] || { printf 'wt.sh did not report the work-vault worktree path\n' >&2; exit 2; }
    git -C "$sibling" merge -q --ff-only "$work_ref" >/dev/null 2>&1 \
      || { printf 'the work-vault worktree %s cannot fast-forward to %s; refusing to verify stale work maps\n' "$sibling" "$work_ref" >&2; exit 2; }
  fi
fi

tracker_dir="$personal/$tracker_projects_dir/$project/Tracker"
printf 'TRACKER_BRANCH=%s\n' "$branch"
printf 'TRACKER_TASK=%s\n' "$task"
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
