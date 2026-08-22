#!/usr/bin/env bash
#
# scratch-sweep.sh — report or reclaim disk in the designated AI scratch root.
#
# Reports by default. Nothing is ever deleted without --apply, and even then
# only direct children of the scratch root that pass every keep rule below.
#
#   scratch-sweep.sh                 # report only: what is reclaimable and why
#   scratch-sweep.sh --older-than 14 # only consider entries idle 14+ days
#   scratch-sweep.sh --apply         # delete the reclaimable set
#
set -uo pipefail

ROOT="${AI_SCRATCH_ROOT:-$HOME/devel/portaj/ai-scratch}"
OLDER_THAN=7
APPLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --older-than) OLDER_THAN="${2:-}"; shift 2;;
    --older-than=*) OLDER_THAN="${1#*=}"; shift;;
    --root) ROOT="${2:-}"; shift 2;;
    --root=*) ROOT="${1#*=}"; shift;;
    --apply) APPLY=1; shift;;
    -h|--help) sed -n '3,12p' "$0"; exit 0;;
    *) printf 'scratch-sweep: unknown option: %s\n' "$1" >&2; exit 2;;
  esac
done

case "$OLDER_THAN" in ''|*[!0-9]*) printf 'scratch-sweep: --older-than needs a whole number of days\n' >&2; exit 2;; esac

# --- containment ------------------------------------------------------------
# Everything below operates on direct children of ROOT and nothing else. A
# resolved path that escapes ROOT, or a ROOT that is a symlink or a home/root
# directory, aborts before any classification happens.
[ -d "$ROOT" ] || { printf 'scratch-sweep: not a directory: %s\n' "$ROOT" >&2; exit 1; }
[ -L "$ROOT" ] && { printf 'scratch-sweep: scratch root must not be a symlink: %s\n' "$ROOT" >&2; exit 1; }
ROOT_REAL="$(cd "$ROOT" && pwd -P)" || exit 1
case "$ROOT_REAL" in
  / | "$HOME") printf 'scratch-sweep: refusing to operate on %s\n' "$ROOT_REAL" >&2; exit 1;;
esac
[ "$(printf '%s' "$ROOT_REAL" | tr -cd / | wc -c)" -ge 3 ] || {
  printf 'scratch-sweep: scratch root looks too shallow to be safe: %s\n' "$ROOT_REAL" >&2; exit 1; }

human() { awk -v k="$1" 'BEGIN{split("KB MB GB TB",u," ");i=1;while(k>=1024&&i<4){k/=1024;i++}printf "%.1f%s",k,u[i]}'; }

printf '\n=== disk before ===\n'
df -h "$ROOT_REAL" | sed -n '1p;2p'
printf '\nScratch root: %s\n' "$ROOT_REAL"
printf 'Idle threshold: %s days\n\n' "$OLDER_THAN"

reclaim_list=""; reclaim_kb=0; reclaim_n=0
keep_n=0; keep_kb=0

for entry in "$ROOT_REAL"/* "$ROOT_REAL"/.[!.]*; do
  [ -e "$entry" ] || continue
  base="${entry##*/}"

  # Never follow a symlink out of the root, and never delete the link target.
  if [ -L "$entry" ]; then keep_n=$((keep_n+1)); printf '  KEEP  %-44s symlink\n' "$base"; continue; fi

  real="$(cd "$(dirname "$entry")" && pwd -P)/$base"
  case "$real" in "$ROOT_REAL"/*) : ;; *) printf '  KEEP  %-44s outside scratch root\n' "$base"; keep_n=$((keep_n+1)); continue;; esac

  reason=""

  # 1. Live queue state. prrq keeps queue.json, events.jsonl, and its lock here;
  #    deleting it destroys claims, verdict history, and the audit log.
  case "$base" in .prrq) reason="live prrq queue state";; esac

  # 2. Recently touched. An active review, an in-flight clone, or anything the
  #    operator is still using shows up here long before it is safe to remove.
  if [ -z "$reason" ] && [ -n "$(find "$real" -maxdepth 0 -mtime -"$OLDER_THAN" 2>/dev/null)" ]; then
    reason="modified within ${OLDER_THAN}d"
  fi

  # 3. Unsaved git work. A scratch clone can hold commits that exist nowhere
  #    else; removing it would destroy them silently.
  if [ -z "$reason" ] && [ -d "$real/.git" ]; then
    if [ -n "$(git -C "$real" status --porcelain 2>/dev/null)" ]; then
      reason="uncommitted changes"
    elif [ -n "$(git -C "$real" log --branches --not --remotes --oneline 2>/dev/null | head -1)" ]; then
      reason="unpushed commits"
    fi
  fi

  kb="$(du -sk "$real" 2>/dev/null | awk '{print $1}')"; kb="${kb:-0}"

  if [ -n "$reason" ]; then
    keep_n=$((keep_n+1)); keep_kb=$((keep_kb+kb))
    printf '  KEEP  %-44s %-10s %s\n' "$base" "$(human "$kb")" "$reason"
  else
    reclaim_n=$((reclaim_n+1)); reclaim_kb=$((reclaim_kb+kb))
    reclaim_list="$reclaim_list$real"$'\n'
    printf '  FREE  %-44s %s\n' "$base" "$(human "$kb")"
  fi
done

printf '\n=== proposal ===\n'
printf 'keep      %5s entries  %s\n' "$keep_n" "$(human "$keep_kb")"
printf 'reclaim   %5s entries  %s\n' "$reclaim_n" "$(human "$reclaim_kb")"

if [ "$APPLY" != 1 ]; then
  printf '\nReport only. Re-run with --apply to delete the FREE entries.\n'
  exit 0
fi

[ "$reclaim_n" -gt 0 ] || { printf '\nNothing to reclaim.\n'; exit 0; }

printf '\n=== deleting ===\n'
printf '%s' "$reclaim_list" | while IFS= read -r target; do
  [ -n "$target" ] || continue
  case "$target" in "$ROOT_REAL"/*) : ;; *) printf '  SKIP  %s (containment)\n' "$target"; continue;; esac
  rm -rf -- "$target" && printf '  removed %s\n' "${target##*/}"
done

printf '\n=== disk after ===\n'
df -h "$ROOT_REAL" | sed -n '1p;2p'
