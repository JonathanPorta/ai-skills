#!/usr/bin/env bash
#
# scratch-sweep.sh — report or reclaim disk in the designated AI scratch root.
#
#   scratch-sweep.sh                       # dry run: what is reclaimable and why
#   scratch-sweep.sh --dry-run             # same thing, said explicitly
#   scratch-sweep.sh --verbose             # list every kept entry, not a summary
#   scratch-sweep.sh --older-than 14       # only consider entries idle 14+ days
#   scratch-sweep.sh --apply --manifest F  # delete exactly what manifest F approved
#
# A dry run writes a manifest. --apply consumes one and refuses if reality has
# drifted from it, so the thing deleted is the thing that was approved.
#
set -uo pipefail

SELF_DIR="$(CDPATH= cd -P -- "$(dirname -- "$0")" && pwd -P)"
# shellcheck source=lib-scratch.sh
. "$SELF_DIR/lib-scratch.sh"

EXPLICIT_ROOT=""; OLDER_THAN=""; APPLY=0; VERBOSE=0; MANIFEST=""; OUT_MANIFEST=""

while [ $# -gt 0 ]; do
  case "$1" in
    --root)        scratch_need_value $# "--root";        EXPLICIT_ROOT="$2"; shift 2;;
    --root=*)      EXPLICIT_ROOT="${1#*=}"; shift;;
    --older-than)  scratch_need_value $# "--older-than";  OLDER_THAN="$2"; shift 2;;
    --older-than=*) OLDER_THAN="${1#*=}"; shift;;
    --manifest)    scratch_need_value $# "--manifest";    MANIFEST="$2"; shift 2;;
    --manifest=*)  MANIFEST="${1#*=}"; shift;;
    --apply)       APPLY=1; shift;;
    -n|--dry-run)  APPLY=0; shift;;
    -v|--verbose)  VERBOSE=1; shift;;
    -h|--help)     sed -n '3,14p' "$0"; exit 0;;
    *) scratch_die "unknown option: $1" 2;;
  esac
done

[ -z "$OLDER_THAN" ] && OLDER_THAN="$(scratch_config_get AI_SCRATCH_IDLE_DAYS)"
[ -z "$OLDER_THAN" ] && OLDER_THAN=7
case "$OLDER_THAN" in ''|*[!0-9]*) scratch_die "--older-than needs a whole number of days" 2;; esac

scratch_resolve_root "$EXPLICIT_ROOT"
ROOT_REAL="$(scratch_canonical "$SCRATCH_ROOT_RAW")" || exit 1
if reason="$(scratch_root_unsafe_reason "$ROOT_REAL")"; then
  scratch_die "refusing to operate on $ROOT_REAL — that is $reason"
fi
ROOT_ID="$(scratch_devino "$ROOT_REAL")" || scratch_die "cannot identify $ROOT_REAL"

# Extra names the operator wants pinned, beyond the dot-entry convention.
PROTECT_EXTRA="$(scratch_config_get AI_SCRATCH_PROTECT)"

human() { awk -v k="$1" 'BEGIN{split("KB MB GB TB",u," ");i=1;while(k>=1024&&i<4){k/=1024;i++}printf "%.1f%s",k,u[i]}'; }

# --- classification ---------------------------------------------------------
# Returns the keep reason on stdout, or nothing when the entry is reclaimable.
classify() {  # <abs-path> <base-name>
  local path="$1" base="$2" r

  # Hidden entries at the root are state, not task output. Tools keep queues,
  # caches, locks, and claim files here; task output is named <repo>-<pr>. This
  # is a convention, not a list of tool names, so it covers tools we know
  # nothing about.
  case "$base" in .*) printf 'hidden entry (state by convention)'; return 0;; esac

  for p in $PROTECT_EXTRA; do
    [ "$base" = "$p" ] && { printf 'pinned by AI_SCRATCH_PROTECT'; return 0; }
  done

  [ -L "$path" ] && { printf 'symlink'; return 0; }
  [ -d "$path" ] || { printf 'not a directory'; return 0; }

  # Activity anywhere inside, not just the directory inode. Editing a file in
  # place leaves the parent directory's mtime untouched, so -maxdepth 0 would
  # call an actively edited tree idle.
  if [ -n "$(find "$path" -mtime -"$OLDER_THAN" -print -quit 2>/dev/null)" ]; then
    printf 'active within %sd' "$OLDER_THAN"; return 0
  fi

  # Every repository inside the candidate, not just one at the top. .git is a
  # directory in a clone and a FILE in a linked worktree; both count.
  local gits found=0
  gits="$(find "$path" -name .git -maxdepth 6 -print 2>/dev/null)"
  [ -d "$path/.git" ] || [ -f "$path/.git" ] || [ -n "$gits" ] || { printf ''; return 1; }

  local g repo
  while IFS= read -r g; do
    [ -n "$g" ] || continue
    found=1
    repo="$(dirname -- "$g")"
    # Fail closed: a repository we cannot interrogate is a repository we cannot
    # declare safe to delete.
    if ! git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
      printf 'unreadable git repo (fail closed)'; return 0
    fi
    if [ -n "$(git -C "$repo" status --porcelain 2>/dev/null)" ]; then
      printf 'uncommitted changes'; return 0
    fi
    # Local commits not reachable from any remote. --all covers branches and
    # tags; HEAD is added explicitly so a detached HEAD is not invisible.
    local unpushed
    unpushed="$(git -C "$repo" rev-list --count --all HEAD --not --remotes 2>/dev/null)"
    if [ -z "$unpushed" ]; then printf 'git rev-list failed (fail closed)'; return 0; fi
    if [ "$unpushed" -gt 0 ]; then printf 'unpushed commits'; return 0; fi
  done <<EOF
$gits
EOF
  [ "$found" = 1 ] && { printf ''; return 1; }
  printf ''; return 1
}

printf '\n=== disk before ===\n'
df -h "$ROOT_REAL" | sed -n '1p;2p'
printf '\nScratch root: %s  (%s)\n' "$ROOT_REAL" "$SCRATCH_ROOT_SRC"
printf 'Idle threshold: %s days\n\n' "$OLDER_THAN"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/scratch-sweep.XXXXXX")" || exit 1
trap 'rm -rf "$WORK"' EXIT
: >"$WORK/candidates"   # hex-name<TAB>devino<TAB>kb
: >"$WORK/keeps"        # reason<TAB>kb

# NUL-delimited enumeration: no filename can split a record.
while IFS= read -r -d '' path; do
  base="${path##*/}"
  [ "$base" = "." ] || [ "$base" = ".." ] && continue

  # The parent of a real candidate is the root itself, by identity not string.
  parent_id="$(scratch_devino "$(dirname -- "$path")" 2>/dev/null)"
  [ "$parent_id" = "$ROOT_ID" ] || continue

  reason="$(classify "$path" "$base")"
  kb="$(du -sk "$path" 2>/dev/null | awk '{print $1}')"; kb="${kb:-0}"

  if [ -n "$reason" ]; then
    printf '%s\t%s\n' "$reason" "$kb" >>"$WORK/keeps"
    [ "$VERBOSE" = 1 ] && printf '  KEEP  %-44s %-10s %s\n' "$base" "$(human "$kb")" "$reason"
  else
    devino="$(scratch_devino "$path")" || continue
    printf '%s\t%s\t%s\n' "$(scratch_hex_encode "$base")" "$devino" "$kb" >>"$WORK/candidates"
    printf '  FREE  %-44s %s\n' "$base" "$(human "$kb")"
  fi
done < <(find "$ROOT_REAL" -mindepth 1 -maxdepth 1 -print0 2>/dev/null)

keep_n="$(wc -l <"$WORK/keeps" | tr -d ' ')"
keep_kb="$(awk -F'\t' '{s+=$2} END{print s+0}' "$WORK/keeps")"
free_n="$(wc -l <"$WORK/candidates" | tr -d ' ')"
free_kb="$(awk -F'\t' '{s+=$3} END{print s+0}' "$WORK/candidates")"

printf '\n=== kept, by reason ===\n'
awk -F'\t' '{n[$1]++; kb[$1]+=$2} END{for(r in n){k=kb[r];split("KB MB GB TB",u," ");i=1;
  while(k>=1024&&i<4){k/=1024;i++}printf "  %-32s %5d entries  %.1f%s\n", r, n[r], k, u[i]}}' "$WORK/keeps" | sort -k2 -rn
[ "$VERBOSE" = 1 ] || printf '  (run with --verbose to list every kept entry)\n'

printf '\n=== proposal ===\n'
printf 'keep      %5s entries  %s\n' "$keep_n" "$(human "$keep_kb")"
printf 'reclaim   %5s entries  %s\n' "$free_n" "$(human "$free_kb")"

if [ "$APPLY" != 1 ]; then
  OUT_MANIFEST="${TMPDIR:-/tmp}/scratch-sweep-manifest.$$"
  { printf '# scratch-sweep manifest v1\n'
    printf 'root\t%s\n' "$(scratch_hex_encode "$ROOT_REAL")"
    printf 'rootid\t%s\n' "$ROOT_ID"
    printf 'idle\t%s\n' "$OLDER_THAN"
    sort "$WORK/candidates" | sed 's/^/candidate\t/'
  } >"$OUT_MANIFEST"
  printf 'sum\t%s\n' "$(scratch_sha256 "$OUT_MANIFEST")" >>"$OUT_MANIFEST"
  printf '\nDry run — nothing was deleted.\n'
  [ "$free_n" -gt 0 ] && printf 'To delete exactly this set:\n  %s --apply --manifest %s\n' "$0" "$OUT_MANIFEST"
  exit 0
fi

# --- apply ------------------------------------------------------------------
[ -n "$MANIFEST" ] || scratch_die "--apply requires --manifest <file> from a dry run" 2
[ -f "$MANIFEST" ] || scratch_die "manifest not found: $MANIFEST"

claimed_sum="$(sed -n 's/^sum\t//p' "$MANIFEST" | tail -1)"
body="$WORK/manifest.body"; grep -v '^sum	' "$MANIFEST" >"$body"
[ "$(scratch_sha256 "$body")" = "$claimed_sum" ] || scratch_die "manifest checksum mismatch — it was modified after the dry run"

m_rootid="$(sed -n 's/^rootid\t//p' "$MANIFEST" | tail -1)"
[ "$m_rootid" = "$ROOT_ID" ] || scratch_die "manifest was written for a different directory (root identity changed)"

# Set drift: the approved candidates must equal what classification finds now.
sed -n 's/^candidate\t//p' "$MANIFEST" | sort >"$WORK/approved"
sort "$WORK/candidates" >"$WORK/current"
if ! diff -q "$WORK/approved" "$WORK/current" >/dev/null 2>&1; then
  printf '\nABORT — the reclaimable set changed since the dry run.\n' >&2
  printf 'Approved %s entries, found %s now. Re-run the dry run and review it again.\n' \
    "$(wc -l <"$WORK/approved" | tr -d ' ')" "$(wc -l <"$WORK/current" | tr -d ' ')" >&2
  exit 1
fi

printf '\n=== deleting ===\n'
removed=0
while IFS="$(printf '\t')" read -r hexname devino kb; do
  [ -n "$hexname" ] || continue
  name="$(scratch_hex_decode "$hexname")"
  target="$ROOT_REAL/$name"

  # Revalidate immediately before removal: identity, parentage, and every keep
  # rule. A same-path replacement or fresh activity aborts this entry.
  now_id="$(scratch_devino "$target" 2>/dev/null)" || { printf '  SKIP  %s (vanished)\n' "$name"; continue; }
  [ "$now_id" = "$devino" ] || { printf '  SKIP  %s (replaced since approval)\n' "$name"; continue; }
  [ "$(scratch_devino "$(dirname -- "$target")")" = "$ROOT_ID" ] || { printf '  SKIP  %s (not a child of the root)\n' "$name"; continue; }
  late="$(classify "$target" "$name")"
  [ -z "$late" ] || { printf '  SKIP  %s (%s)\n' "$name" "$late"; continue; }

  rm -rf -- "$target" && { printf '  removed %s\n' "$name"; removed=$((removed+1)); }
done <"$WORK/approved"

printf '\nRemoved %s of %s approved entries.\n' "$removed" "$(wc -l <"$WORK/approved" | tr -d ' ')"
printf '\n=== disk after ===\n'
df -h "$ROOT_REAL" | sed -n '1p;2p'
