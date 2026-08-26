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

# `git status` is not a read-only operation: it refreshes the index stat cache
# and writes it back, which updates the mtime of .git and .git/index. Those live
# INSIDE the entry being examined, so inspecting a repository marked it as
# modified, and the next run classified it as active work rather than
# reclaimable. One dry run over a real workspace re-dated 1217 of 1551
# repositories and cut the reclaimable set from 816 entries to 99 -- the tool
# disabled itself by looking. This is what GIT_OPTIONAL_LOCKS exists for; it is
# exported once here so it also covers any call site added later.
export GIT_OPTIONAL_LOCKS=0

EXPLICIT_ROOT=""; OLDER_THAN=""; APPLY=0; VERBOSE=0; MANIFEST=""; OUT_MANIFEST=""

while [ $# -gt 0 ]; do
  case "$1" in
    --root)        scratch_need_value $# "--root";        EXPLICIT_ROOT="$2"; shift 2;;
    --root=*)      EXPLICIT_ROOT="${1#*=}"; [ -n "$EXPLICIT_ROOT" ] || scratch_die "--root requires a value" 2; shift;;
    --older-than)  scratch_need_value $# "--older-than";  OLDER_THAN="$2"; shift 2;;
    --older-than=*) OLDER_THAN="${1#*=}"; [ -n "$OLDER_THAN" ] || scratch_die "--older-than requires a value" 2; shift;;
    --manifest)    scratch_need_value $# "--manifest";    MANIFEST="$2"; shift 2;;
    --manifest=*)  MANIFEST="${1#*=}"; [ -n "$MANIFEST" ] || scratch_die "--manifest requires a value" 2; shift;;
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

  if scratch_protect_matches "$base" "$PROTECT_EXTRA"; then
    printf 'pinned by AI_SCRATCH_PROTECT'; return 0
  fi

  [ -L "$path" ] && { printf 'symlink'; return 0; }
  [ -d "$path" ] || { printf 'not a directory'; return 0; }

  # Activity anywhere inside, not just the directory inode. Editing a file in
  # place leaves the parent directory's mtime untouched, so -maxdepth 0 would
  # call an actively edited tree idle.
  #
  # Git's own metadata is not activity. A fetch, a gc, or an index refresh
  # re-dates .git without anyone having done work, and a local commit re-dates
  # it while the thing actually worth protecting -- the commit -- is caught
  # precisely by the unpushed and uncommitted checks below. Counting it meant
  # routine repository housekeeping pinned an entry for a whole idle window:
  # on a real workspace 1364 of 1477 entries had seen no non-git change in
  # seven days while only about 100 were reported reclaimable. .git is matched
  # as a name so this prunes the directory in a clone and the file in a linked
  # worktree alike.
  if scratch_recently_active "$path" "$OLDER_THAN"; then
    printf 'active within %sd' "$OLDER_THAN"; return 0
  fi

  # Every repository inside the candidate, at ANY depth, enumerated NUL-delimited.
  # A newline-delimited list splits a repository living under a newline-bearing
  # path into nonexistent fragments, and a silent `continue` on the resulting
  # failure is indistinguishable from "no repository here".
  #
  # Two shapes are searched. A working tree has .git -- a directory in a clone,
  # a FILE in a linked worktree. A bare repository has neither, so directories
  # holding HEAD + objects + refs count too. Paths inside a .git are skipped:
  # matching .git/HEAD and .git/logs/HEAD would run `git status` where it cannot
  # work and fail every ordinary clone closed.
  local markers="$SCRATCH_WORK/markers.$$"
  : >"$markers"
  find "$path" -name .git -print0 >>"$markers" 2>/dev/null \
    || { printf 'repository discovery failed (fail closed)'; rm -f "$markers"; return 0; }
  find "$path" -type d -name objects -print0 >>"$markers" 2>/dev/null \
    || { printf 'repository discovery failed (fail closed)'; rm -f "$markers"; return 0; }

  local marker repo seen="" out rc
  while IFS= read -r -d '' marker; do
    [ -n "$marker" ] || continue
    case "$marker" in */.git/*) continue;; esac
    repo="$(dirname -- "$marker")"
    case "$marker" in
      */objects) [ -f "$repo/HEAD" ] && [ -d "$repo/refs" ] || continue;;
    esac
    case "$seen" in *"[$repo]"*) continue;; esac
    seen="$seen[$repo]"

    # A marker was found. From here every failure is KEEP, never a skip: an
    # unreadable repository is precisely the case where deletion is unsafe.
    if ! git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
      rm -f "$markers"; printf 'git repo present but unreadable (fail closed)'; return 0
    fi

    out="$(git -C "$repo" status --porcelain 2>/dev/null)"; rc=$?
    [ "$rc" -eq 0 ] || { rm -f "$markers"; printf 'git status failed (fail closed)'; return 0; }
    [ -n "$out" ] && { rm -f "$markers"; printf 'uncommitted changes'; return 0; }

    out="$(git -C "$repo" rev-list --count --all HEAD --not --remotes 2>/dev/null)"; rc=$?
    [ "$rc" -eq 0 ] || { rm -f "$markers"; printf 'git rev-list failed (fail closed)'; return 0; }
    case "$out" in ''|*[!0-9]*) rm -f "$markers"; printf 'git rev-list unreadable (fail closed)'; return 0;; esac
    [ "$out" -gt 0 ] && { rm -f "$markers"; printf 'unpushed commits'; return 0; }
  done <"$markers"
  rm -f "$markers"
  printf ''; return 1
}

printf '\n=== disk before ===\n'
df -h "$ROOT_REAL" | sed -n '1p;2p'
printf '\nScratch root: %s  (%s)\n' "$ROOT_REAL" "$SCRATCH_ROOT_SRC"
printf 'Idle threshold: %s days\n\n' "$OLDER_THAN"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/scratch-sweep.XXXXXX")" || exit 1
SCRATCH_WORK="$WORK"
trap 'rm -rf "$WORK"' EXIT
: >"$WORK/candidates"   # hex-name<TAB>devino<TAB>kb
: >"$WORK/keeps"        # reason<TAB>kb

# NUL-delimited enumeration: no filename can split a record.
while IFS= read -r -d '' path; do
  base="${path##*/}"
  [ "$base" = "." ] || [ "$base" = ".." ] && continue

  # The parent of a real candidate is the root itself, by identity not string.
  parent_id="$(scratch_devino "$(dirname -- "$path")" 2>/dev/null | cut -d: -f1,2)"
  [ "$parent_id" = "${ROOT_ID%:*}" ] || continue

  reason="$(classify "$path" "$base")"
  kb="$(scratch_size_kb "$path")"; kb="${kb:-0}"

  if [ -n "$reason" ]; then
    printf '%s\t%s\n' "$reason" "$kb" >>"$WORK/keeps"
    [ "$VERBOSE" = 1 ] && printf '  KEEP  %-44s %-10s %s\n' "$(scratch_display_name "$base")" "$(human "$kb")" "$reason"
  else
    devino="$(scratch_devino "$path")" || continue
    printf '%s\t%s\t%s\n' "$(scratch_hex_encode "$base")" "$devino" "$kb" >>"$WORK/candidates"
    printf '  FREE  %-44s %s\n' "$(scratch_display_name "$base")" "$(human "$kb")"
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

# Every record must be structurally exact before it is trusted: hex name, a
# dev:inode, and a size. A malformed line means the manifest is not the artifact
# the dry run produced.
bad="$(scratch_manifest_bad_records "$body")"
[ "${bad:-0}" -eq 0 ] || scratch_die "manifest contains $bad malformed candidate record(s)"

m_rootid="$(sed -n 's/^rootid\t//p' "$MANIFEST" | tail -1)"
# dev:inode only: the root's ctime moves whenever anything is created or removed
# inside it, which is exactly what a sweep does.
[ "${m_rootid%:*}" = "${ROOT_ID%:*}" ] || scratch_die "manifest was written for a different directory (root identity changed)"

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
# Quarantine, then verify, then delete. Checking identity and immediately calling
# rm -rf leaves a window in which the pathname can be replaced between the check
# and the removal; the replacement is what gets deleted, and apply still reports
# success. Renaming into a staging directory is atomic with respect to the name,
# so whatever was moved is exactly what is then identified and removed -- and if
# the moved object is not the approved one, it is put straight back.
# Exclusive by construction. `mkdir -p` succeeds against a pre-existing
# directory, which meant an unrelated hidden directory could be adopted as
# staging -- and then recursively deleted by the cleanup below along with
# contents nobody approved.
QUAR="$(mktemp -d "$ROOT_REAL/.scratch-sweep-XXXXXX")" || scratch_die "cannot stage removals in $ROOT_REAL"
case "$QUAR" in "$ROOT_REAL"/.scratch-sweep-*) : ;; *) scratch_die "staging directory landed outside the root";; esac
removed=0; skipped=0

while IFS="$(printf '\t')" read -r hexname devino kb; do
  [ -n "$hexname" ] || continue
  scratch_hex_decode_exact "$hexname"; name="$SCRATCH_DECODED"
  shown="$(scratch_display_name "$name")"
  target="$ROOT_REAL/$name"

  now_id="$(scratch_devino "$target" 2>/dev/null)" || { printf '  SKIP  %s (vanished)\n' "$shown"; skipped=$((skipped+1)); continue; }
  [ "$now_id" = "$devino" ] || { printf '  SKIP  %s (replaced since approval)\n' "$shown"; skipped=$((skipped+1)); continue; }
  # dev:inode only: creating the staging directory inside the root updates the
  # ROOT's ctime, so comparing the full triple would reject every candidate.
  [ "$(scratch_devino "$(dirname -- "$target")" | cut -d: -f1,2)" = "${ROOT_ID%:*}" ] || { printf '  SKIP  %s (not a child of the root)\n' "$shown"; skipped=$((skipped+1)); continue; }
  late="$(classify "$target" "$name")"
  [ -z "$late" ] || { printf '  SKIP  %s (%s)\n' "$shown" "$late"; skipped=$((skipped+1)); continue; }

  staged="$QUAR/$hexname"
  mv -- "$target" "$staged" 2>/dev/null || { printf '  SKIP  %s (could not stage)\n' "$shown"; skipped=$((skipped+1)); continue; }

  # The decisive check, after the object can no longer be swapped under us.
  # Compare dev:inode only here: renaming an object legitimately updates its
  # ctime, so the full triple would mismatch on every successful stage.
  staged_id="$(scratch_devino "$staged" 2>/dev/null)"
  if [ "${staged_id%:*}" != "${devino%:*}" ]; then
    mv -- "$staged" "$target" 2>/dev/null || printf '  WARN  %s could not be restored; it is in %s\n' "$shown" "$QUAR" >&2
    printf '  SKIP  %s (identity changed at the deletion boundary)\n' "$shown"; skipped=$((skipped+1)); continue
  fi

  # Capability before activity: ask who can still write BEFORE asking what has
  # been written. Reversing these two leaves a hole -- a writer could append
  # after the activity scan and close before this one, and be missed by both.
  lw=0; scratch_live_writers "$staged" || lw=$?
  if [ "$lw" -ne 0 ]; then
    mv -- "$staged" "$target" 2>/dev/null || printf '  WARN  %s could not be restored; it is in %s\n' "$shown" "$QUAR" >&2
    if [ "$lw" -eq 1 ]; then
      printf '  SKIP  %s (a process still holds it open)\n' "$shown"
    else
      printf '  SKIP  %s (open descriptors cannot be enumerated on this system)\n' "$shown"
    fi
    skipped=$((skipped+1)); continue
  fi

  # Now that no one can still be writing, confirm no one already did.
  if scratch_recently_active "$staged" "$OLDER_THAN"; then
    mv -- "$staged" "$target" 2>/dev/null || printf '  WARN  %s could not be restored; it is in %s\n' "$shown" "$QUAR" >&2
    printf '  SKIP  %s (written to after staging)\n' "$shown"; skipped=$((skipped+1)); continue
  fi

  # Every removal is accounted for. A silent failure here previously left the
  # object to be swept up by a blanket cleanup, reporting "Removed 0 of 1" and
  # exiting 0 while the object was in fact gone.
  if rm -rf -- "$staged" 2>/dev/null && [ ! -e "$staged" ]; then
    printf '  removed %s\n' "$shown"; removed=$((removed+1))
  else
    printf '  FAIL  %s could not be removed and is staged in %s\n' "$shown" "$QUAR" >&2
    skipped=$((skipped+1))
  fi
done <"$WORK/approved"

# rmdir only: it fails on a non-empty directory rather than destroying whatever
# is inside. Anything left is reported, never silently swept.
if ! rmdir "$QUAR" 2>/dev/null; then
  printf '\nWARNING — staging directory is not empty and was left in place:\n  %s\n' "$QUAR" >&2
  skipped=$((skipped+1))
fi
[ "$skipped" -gt 0 ] && printf '\nINCOMPLETE — %s approved entries were skipped or failed and remain on disk.\n' "$skipped"

printf '\nRemoved %s of %s approved entries.\n' "$removed" "$(wc -l <"$WORK/approved" | tr -d ' ')"
[ "$skipped" -gt 0 ] && EXIT_CODE=1 || EXIT_CODE=0
printf '\n=== disk after ===\n'
df -h "$ROOT_REAL" | sed -n '1p;2p'
exit "${EXIT_CODE:-0}"
