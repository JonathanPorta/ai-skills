#!/usr/bin/env bash
# wt.sh — the smallest task-worktree lifecycle that the scratch sweep can trust.
#
#   wt.sh start  <repo> <task> [--branch B] [--base REF] [--purpose TEXT] [--owner ID] [--no-fetch]
#   wt.sh list   [<repo>]
#   wt.sh finish <repo> <task> [--pr URL] [--note TEXT] [--bundle FILE] [--release] [--owner ID] [--no-fetch]
#   wt.sh check  <repo> <task> [--for-removal] [--no-fetch]
#
# start   creates (or, for the same owner, resumes) ~/devel/worktrees/portaj/<repo>/<task>
#         from the canonical primary ~/devel/portaj/<repo> without touching the branch
#         that primary has checked out, and writes the ownership record the sweep reads.
# list    shows every recorded worktree: owner, branch, PR, activity, state, blockers.
# finish  records completion (and, with --release, release) plus the preservation
#         evidence, then prints the exact cleanup plan. It deletes NOTHING; removal
#         stays in the verified, non-forced `git worktree remove` flow.
# check   the validator the plan runs: ownership, dependency and preservation
#         checks against the current state (fetches origin's default branch into
#         the primary's remote-tracking ref — the only thing either command
#         writes besides the record — and restores the recorded bundle into an
#         empty repository offline). Preservation = reachable from the freshly
#         fetched remote default branch, or a local keep ref plus a
#         restore-tested bundle kept outside the worktree. A pushed task
#         branch's live tip, a merged PR's head ref, a stale remote-tracking ref
#         or a note is not enough. --no-fetch assesses offline: only keep refs
#         + bundle count. Preservation is not completion or owner release.
#
# Ownership records are the flat JSON files scratch-sweep.sh consumes (see
# scratch_owner_record_parse in lib-scratch.sh); there is one format, not two.
# Owner identity: --owner, else $WT_OWNER, else user@host. Set WT_OWNER to the
# session id in every agent session so two sessions cannot look alike.
set -u
here="$(cd "$(dirname "$0")" && pwd -P)"
# shellcheck source=lib-scratch.sh
. "$here/lib-scratch.sh"

usage() { sed -n '2,/^set -u/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit "${1:-2}"; }
die() { printf 'wt: %s\n' "$1" >&2; exit "${2:-1}"; }

expand_dir() {  # <value> <default>: tilde expanded, must be absolute
  local d="$1"; [ -n "$d" ] || d="$2"
  case "$d" in "~/"*) d="$HOME/${d#\~/}";; "~") d="$HOME";; esac
  case "$d" in /*) printf '%s' "$d";; *) printf 'wt: %s must be an absolute path, got: %s\n' "$3" "$d" >&2; exit 2;; esac
}
WT_ROOT="$(expand_dir "${WT_ROOT:-$(scratch_config_get WT_ROOT)}" "$HOME/devel/worktrees/portaj" WT_ROOT)" || exit 2
WT_PRIMARIES="$(expand_dir "${WT_PRIMARIES:-$(scratch_config_get WT_PRIMARIES)}" "$HOME/devel/portaj" WT_PRIMARIES)" || exit 2
WT_BRANCH_PREFIX="${WT_BRANCH_PREFIX:-$(scratch_config_get WT_BRANCH_PREFIX)}"; WT_BRANCH_PREFIX="${WT_BRANCH_PREFIX:-jp/f/}"
WT_BUNDLES="$(expand_dir "${WT_BUNDLES:-$(scratch_config_get WT_BUNDLES)}" "$HOME/devel/recovery/bundles" WT_BUNDLES)" || exit 2
OWNERS_DIR="$(scratch_owners_dir)"
export GIT_OPTIONAL_LOCKS=0 GIT_NO_LAZY_FETCH=1
g() { git -c core.fsmonitor=false -c gc.auto=0 "$@"; }

name_ok() {  # plain directory name: no separators, no dot-dirs, no leading dash, no control chars
  scratch_text_is_sane "$1" || return 1
  case "$1" in ''|.*|-*|*/*|*\\*|*' '*) return 1;; esac
  printf '%s' "$1" | LC_ALL=C grep -qE '^[A-Za-z0-9._-]+$'
}
now() { date +%Y-%m-%dT%H:%M:%S%z; }
owner_id() { printf '%s' "${OWNER_OPT:-${WT_OWNER:-$(id -un)@$(hostname -s 2>/dev/null || hostname)}}"; }

# Write a record from key<TAB>type<TAB>value lines on stdin (the dump format).
write_record() {  # <file>
  local f="$1" tmp key typ val first=1
  tmp="$(mktemp "$f.XXXXXX")" || die "cannot write $f"
  { printf '{\n'
    while IFS=$'\t' read -r key typ val; do
      [ -n "$key" ] || continue
      [ "$first" = 1 ] || printf ',\n'; first=0
      case "$typ" in
        string) if [ -n "$val" ]; then val="$(scratch_json_string "$val")" || die "value for $key contains control characters"; fi
                printf '  "%s": "%s"' "$key" "$val";;
        bool|number) printf '  "%s": %s' "$key" "$val";;
        *) printf '  "%s": null' "$key";;
      esac
    done
    printf '\n}\n'
  } >"$tmp" || { rm -f "$tmp"; die "cannot write $f"; }
  # Never land a record the sweep would call malformed (that would freeze every
  # apply), and never touch the live record until the new one is known good.
  case "$(scratch_owner_record_parse "$tmp")" in malformed*) rm -f "$tmp"; die "refused to write a malformed record; $f left as it was";; esac
  mv "$tmp" "$f" || { rm -f "$tmp"; die "cannot replace $f"; }
}

# dump + overrides (key<TAB>type<TAB>value, later wins) -> new record
update_record() {  # <file> <overrides-file>
  local f="$1" ov="$2"
  { scratch_owner_record_dump "$f"; cat "$ov"; } \
    | LC_ALL=C awk -F '\t' '{ if (!($1 in seen)) order[++n] = $1; seen[$1] = $0 } END { for (i = 1; i <= n; i++) print seen[order[i]] }' \
    | write_record "$f" || die "could not update $f"
}

load_record() {  # <repo> <task>; sets REC, REC_STATUS, REC_WT, REC_OWNER
  REC="$OWNERS_DIR/$1/$2.json"; REC_STATUS=""; REC_WT=""; REC_OWNER=""
  [ -e "$REC" ] || return 1
  local line; line="$(scratch_owner_record_parse "$REC")"
  REC_STATUS="${line%%	*}"; REC_WT="${line#*	}"
  REC_OWNER="$(scratch_owner_record_get "$REC" owner_session)"
  return 0
}

primary_for() {  # <repo> -> canonical primary path on stdout
  local p; p="$(scratch_canonical "$WT_PRIMARIES/$1" 2>/dev/null)" || die "no primary checkout at $WT_PRIMARIES/$1"
  g -C "$p" rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "$p is not a git working tree"
  [ "$(g -C "$p" rev-parse --git-common-dir 2>/dev/null)" = ".git" ] || [ "$(g -C "$p" rev-parse --git-common-dir 2>/dev/null)" = "$p/.git" ] \
    || die "$p is itself a linked worktree, not a primary"
  printf '%s' "$p"
}

cmd_start() {
  local repo="${1:-}" task="${2:-}"; shift 2 2>/dev/null || usage
  local branch="" base="" purpose="" fetch=1
  while [ $# -gt 0 ]; do
    case "$1" in
      --branch)  scratch_need_value $# "$1"; branch="$2"; shift 2;;
      --base)    scratch_need_value $# "$1"; base="$2"; shift 2;;
      --purpose) scratch_need_value $# "$1"; purpose="$2"; shift 2;;
      --owner)   scratch_need_value $# "$1"; OWNER_OPT="$2"; shift 2;;
      --no-fetch) fetch=0; shift;;
      *) die "unknown option: $1" 2;;
    esac
  done
  name_ok "$repo" || die "repo must be a plain directory name, got: $(scratch_display_name "$repo")" 2
  name_ok "$task" || die "task must be a plain directory name (letters, digits, . _ -), got: $(scratch_display_name "$task")" 2
  scratch_text_is_sane "${purpose:-x}" || die "purpose contains control characters" 2
  local me; me="$(owner_id)"; scratch_text_is_sane "$me" || die "owner id contains control characters" 2
  local primary; primary="$(primary_for "$repo")"
  [ -e "$primary/.git/objects/info/alternates" ] && die "$primary borrows objects (objects/info/alternates); refusing to build task worktrees on a borrower"

  mkdir -p "$WT_ROOT/$repo" "$OWNERS_DIR/$repo" || die "cannot create $WT_ROOT/$repo"
  local parent target; parent="$(scratch_canonical "$WT_ROOT/$repo")" || die "cannot resolve $WT_ROOT/$repo"
  target="$parent/$task"
  case "$target" in "$parent"/*) ;; *) die "path escape: $target is not under $parent";; esac
  [ -L "$target" ] && die "$target is a symlink; refusing"
  # The worktree root must not live inside the primary or vice versa.
  case "$parent" in "$primary"|"$primary"/*) die "worktree root $parent is the primary $primary or inside it";; esac
  case "$primary" in "$parent"/*) die "primary $primary is inside the worktree root $parent";; esac

  if load_record "$repo" "$task"; then
    case "$REC_STATUS" in malformed) die "ownership record $REC is malformed; fix or remove it before reusing the task name";; esac
    local rec_real; rec_real="$(scratch_canonical "$REC_WT" 2>/dev/null)" || rec_real="$REC_WT"
    [ "$rec_real" = "$target" ] || die "record $REC names a different worktree ($REC_WT); pick another task name"
    if [ "$REC_OWNER" != "$me" ]; then
      die "task $repo/$task is owned by '$REC_OWNER' (record $REC, $REC_STATUS); it is not yours to resume or take over. Pick another task name or have the owner release it."
    fi
    [ "$REC_STATUS" = released ] && die "task $repo/$task was finished and released; it is awaiting cleanup. Start a new task name instead of reusing a released one."
    # Resume: the worktree must still be the one the record names and be registered.
    if [ -d "$target" ]; then
      g -C "$primary" worktree list --porcelain | LC_ALL=C grep -qxF "worktree $target" || die "$target exists but is not a registered worktree of $primary"
      branch="$(g -C "$target" symbolic-ref -q --short HEAD 2>/dev/null || printf '(detached)')"
      printf 'last_used\tstring\t%s\n' "$(now)" >"$WT_TMP/ov"; update_record "$REC" "$WT_TMP/ov"
      printf 'resumed %s\nWT_PATH=%s\nWT_BRANCH=%s\nWT_RECORD=%s\n' "$repo/$task" "$target" "$branch" "$REC"
      return 0
    fi
    if g -C "$primary" worktree list --porcelain | LC_ALL=C grep -qxF "worktree $target"; then
      die "$target is gone but still registered in $primary. wt never removes registrations; run, as the owner, after checking nothing else needs it:  git -C '$primary' worktree remove '$target'   (then start again)"
    fi
    branch="${branch:-$(scratch_owner_record_get "$REC" branch)}"
    printf 'record exists but the worktree is gone; recreating it on %s\n' "$branch" >&2
  else
    [ -e "$target" ] && die "$target exists without an ownership record; it may be another session's work. Refusing to adopt it."
    # No other record may already name this path (ambiguity is a keep reason for the sweep, and a conflict here).
    local idx thex; idx="$WT_TMP/idx"; scratch_owner_index "$OWNERS_DIR" "$idx" || die "ownership records under $OWNERS_DIR are malformed; run scratch-setup.sh to see which"
    thex="$(scratch_hex_encode "$target")"
    if LC_ALL=C awk -F '\t' -v t="$thex" '$2 == t { f = 1 } END { exit !f }' "$idx"; then
      die "another record already names $target: $(scratch_hex_decode "$(LC_ALL=C awk -F '\t' -v t="$thex" '$2 == t { print $3 }' "$idx" | head -1)")"
    fi
  fi

  branch="${branch:-$WT_BRANCH_PREFIX$task}"
  scratch_text_is_sane "$branch" || die "branch name contains control characters" 2
  g check-ref-format --branch "$branch" >/dev/null 2>&1 || die "invalid branch name: $branch" 2
  if [ "$fetch" = 1 ]; then g -C "$primary" fetch -q origin 2>/dev/null || printf 'wt: fetch from origin failed; continuing with local refs\n' >&2; fi
  if [ -z "$base" ]; then
    local def; def="$(g -C "$primary" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')"
    base="origin/${def:-main}"
    g -C "$primary" rev-parse -q --verify "$base^{commit}" >/dev/null 2>&1 || base="${def:-main}"
  fi
  g -C "$primary" rev-parse -q --verify "$base^{commit}" >/dev/null 2>&1 || die "base $base does not resolve in $primary"
  local head_before; head_before="$(g -C "$primary" symbolic-ref -q HEAD 2>/dev/null || g -C "$primary" rev-parse HEAD)"
  if g -C "$primary" show-ref -q --verify "refs/heads/$branch"; then
    g -C "$primary" worktree add -q "$target" "$branch" 2>"$WT_TMP/err" || die "git worktree add failed: $(tr '\n' ' ' <"$WT_TMP/err")"
  else
    g -C "$primary" worktree add -q --no-track -b "$branch" "$target" "$base" 2>"$WT_TMP/err" || die "git worktree add failed: $(tr '\n' ' ' <"$WT_TMP/err")"
  fi
  [ "$(g -C "$primary" symbolic-ref -q HEAD 2>/dev/null || g -C "$primary" rev-parse HEAD)" = "$head_before" ] || die "the primary's checked-out branch changed; this must never happen"
  local url; url="$(g -C "$primary" remote get-url origin 2>/dev/null || printf '')"
  local repo_slug; repo_slug="$(printf '%s' "$url" | sed -E 's#\.git$##; s#.*[:/]([^/]+/[^/]+)$#\1#')"
  local t; t="$(now)"
  {
    printf 'repository\tstring\t%s\n' "${repo_slug:-$repo}"
    printf 'task\tstring\t%s\n' "$task"
    printf 'worktree\tstring\t%s\n' "$target"
    printf 'primary\tstring\t%s\n' "$primary"
    printf 'branch\tstring\t%s\n' "$branch"
    printf 'base\tstring\t%s\n' "$base"
    printf 'owner_session\tstring\t%s\n' "$me"
    printf 'purpose\tstring\t%s\n' "$purpose"
    printf 'created\tstring\t%s\n' "$t"
    printf 'last_used\tstring\t%s\n' "$t"
    printf 'pr\tstring\t\n'
    printf 'complete\tbool\tfalse\n'
    printf 'released\tbool\tfalse\n'
  } | write_record "$OWNERS_DIR/$repo/$task.json" || {
    # A worktree without a record is exactly what the sweep must never see; undo the add we just made
    # (non-forced; it is the empty worktree created a moment ago; the branch stays).
    if g -C "$primary" worktree remove "$target" >/dev/null 2>&1; then
      die "could not write the ownership record; the new worktree was removed again (branch $branch stays)"
    fi
    die "could not write the ownership record AND could not remove the new worktree $target; remove it by hand"
  }
  printf 'started %s\nWT_PATH=%s\nWT_BRANCH=%s\nWT_BASE=%s\nWT_RECORD=%s\n' "$repo/$task" "$target" "$branch" "$base" "$OWNERS_DIR/$repo/$task.json"
}

blockers_for() {  # <worktree> <primary> <status>; prints a comma list
  local wt="$1" primary="$2" status="$3" out=""
  add() { out="$out${out:+, }$1"; }
  if [ ! -d "$wt" ]; then add "worktree missing"; printf '%s' "$out"; return; fi
  if [ -n "$primary" ] && [ -d "$primary" ]; then
    g -C "$primary" worktree list --porcelain 2>/dev/null | LC_ALL=C grep -qxF "worktree $wt" || add "not registered in primary"
  fi
  local n
  n="$(g -C "$wt" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"; [ "${n:-0}" = 0 ] || add "dirty ($n)"
  n="$(g -C "$wt" rev-list --count HEAD --not --remotes 2>/dev/null)" || n="?"; [ "${n:-0}" = 0 ] || add "unpushed ($n)"
  [ -d "$wt/.git/worktrees" ] && add "hosts worktrees"
  [ -f "$wt/.git/objects/info/alternates" ] && add "borrows objects"
  if LC_ALL=C grep -lsxF -e "$wt/.git/objects" -e "$wt/.git/objects/" "$WT_PRIMARIES"/*/.git/objects/info/alternates "$WT_ROOT"/*/*/.git/objects/info/alternates 2>/dev/null | grep -q .; then add "lends objects"; fi
  [ "$status" = released ] && add "awaiting cleanup"
  printf '%s' "$out"
}

cmd_list() {
  local only="${1:-}"; [ -z "$only" ] || name_ok "$only" || die "repo must be a plain name" 2
  local idx="$WT_TMP/idx"
  scratch_owner_index "$OWNERS_DIR" "$idx" || printf 'wt: some records are malformed (the sweep keeps everything until they are fixed)\n' >&2
  printf '%-28s %-24s %-34s %-14s %-18s %-10s %s\n' "REPO/TASK" "OWNER" "BRANCH" "PR" "ACTIVITY" "STATE" "BLOCKERS"
  while IFS= read -r line; do
    local status wthex filehex wt file rest
    status="${line%%	*}"; rest="${line#*	}"; wthex="${rest%%	*}"; filehex="${rest#*	}"
    wt="$(scratch_hex_decode "$wthex")"; file="$(scratch_hex_decode "$filehex")"
    local repo task owner branch pr activity state blockers primary complete
    repo="$(basename "$(dirname "$file")")"; task="$(basename "$file" .json)"
    [ -z "$only" ] || [ "$repo" = "$only" ] || continue
    if [ "$status" = malformed ]; then
      printf '%-28s %-24s %-34s %-14s %-18s %-10s %s\n' "$repo/$task" "?" "?" "?" "?" "MALFORMED" "fix $(scratch_display_name "$file")"; continue
    fi
    owner="$(scratch_owner_record_get "$file" owner_session)"; branch="$(scratch_owner_record_get "$file" branch)"
    pr="$(scratch_owner_record_get "$file" pr)"; primary="$(scratch_owner_record_get "$file" primary)"
    complete="$(scratch_owner_record_dump "$file" | LC_ALL=C awk -F '\t' '$1 == "complete" { print $3 }')"
    case "$status" in released) state="RELEASED";; *) [ "$complete" = true ] && state="COMPLETE" || state="ACTIVE";; esac
    if [ -d "$wt" ]; then
      activity="$(g -C "$wt" log -1 --format=%cr 2>/dev/null || printf '?')"
      [ -n "$(find "$wt" -mtime -1 ! -path '*/.git/*' -type f -print -quit 2>/dev/null)" ] && activity="$activity, edited <1d"
    else activity="-"; fi
    blockers="$(blockers_for "$wt" "$primary" "$status")"
    printf '%-28s %-24s %-34s %-14s %-18s %-10s %s\n' "$repo/$task" "${owner:0:24}" "${branch:0:34}" "${pr##*/}" "${activity:0:18}" "$state" "${blockers:-none}"
  done <"$idx"
}

# --- preservation (one assessment, used by finish --release, check and the plan) ---
# Required history = HEAD plus every SHA in the worktree's private HEAD reflog.
# A SHA is preserved when ONE of these holds, verified against the CURRENT state:
#   1. it is reachable from the remote default branch, fetched now from origin
#      (refs/remotes/origin/<default> after an explicit fetch);
#   2. (none: a pushed task branch's live tip on origin is NOT a basis — the
#      branch can be deleted at any time, e.g. by a merge with --delete-branch,
#      leaving only a PR-head ref, which is not preservation either)
#   3. a local keep ref (refs/keep/*) in the common dir reaches it AND a bundle
#      named by the record contains it, which is proven by restoring that bundle
#      into an empty repository offline every time (never trusted from a note).
# A merged PR's head ref, a stale remote-tracking ref or a free-text note is not
# evidence. Sets ASSESS_* variables; nothing is written.
assess_preservation() {  # <wt> <primary> <bundle-path-or-empty> <recorded-bundle-sha-or-empty> <fetch 0/1>
  local wt="$1" primary="$2" bundle="$3" rec_sha="$4" fetch="$5" head branch adm s def
  ASSESS_REQUIRED=""; ASSESS_UNPRESERVED=""; ASSESS_BASIS=""; ASSESS_ERROR=""; ASSESS_NOTE=""; ASSESS_BUNDLE_SHA=""; ASSESS_BUNDLE_COMMITS=""; ASSESS_DEFAULT=""; ASSESS_BUNDLE_OK=0
  head="$(g -C "$wt" rev-parse HEAD 2>/dev/null)" || { ASSESS_ERROR="cannot read HEAD"; return 1; }
  branch="$(g -C "$wt" symbolic-ref -q --short HEAD 2>/dev/null || printf '')"
  adm="$(g -C "$wt" rev-parse --absolute-git-dir 2>/dev/null)" || adm=""
  ASSESS_REQUIRED="$head"
  if [ -n "$adm" ] && [ -f "$adm/logs/HEAD" ]; then
    [ -r "$adm/logs/HEAD" ] || { ASSESS_ERROR="cannot read the private reflog $adm/logs/HEAD"; return 1; }
    for s in $(cut -d' ' -f2 "$adm/logs/HEAD" | sort -u); do
      case " $ASSESS_REQUIRED " in *" $s "*) ;; *) ASSESS_REQUIRED="$ASSESS_REQUIRED $s";; esac
    done
  fi
  # Rules 1 and 2 need the CURRENT remote state, so they run only when a fetch
  # is allowed; offline (--no-fetch) only keep refs + a bundle count. A
  # remote-tracking ref that was not refreshed now is not evidence.
  if [ "$fetch" = 1 ]; then
    def="$(g -C "$primary" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')"
    [ -n "$def" ] || def="$(g -C "$primary" ls-remote --symref origin HEAD 2>/dev/null | sed -n 's|^ref: refs/heads/\([^[:space:]]*\)[[:space:]]*HEAD$|\1|p' | head -1)"
    def="${def:-main}"; ASSESS_DEFAULT="$def"
    g -C "$primary" fetch -q origin "+refs/heads/$def:refs/remotes/origin/$def" 2>/dev/null || { ASSESS_ERROR="cannot fetch origin/$def (origin unreachable, or no such branch on origin); run with --no-fetch to assess offline on keep refs + bundle only"; return 1; }
  else
    ASSESS_NOTE="offline: remote reachability not assessed"
  fi
  # 3. keep refs + bundle, restored offline into a fresh empty BARE repository
  # (bare, so a bundle carrying refs/heads/<default> cannot collide with a
  # checked-out branch). A bundle that is missing, changed, inside the worktree
  # the plan would remove, or that does not restore cleanly is unusable: the
  # commits that needed it are then unpreserved.
  local restore="$WT_TMP/restore" keeps="" breal
  keeps="$(g -C "$primary" for-each-ref --format='%(refname) %(objectname)' refs/keep 2>/dev/null)"
  if [ -n "$bundle" ]; then
    if [ ! -f "$bundle" ]; then ASSESS_NOTE="$ASSESS_NOTE${ASSESS_NOTE:+; }bundle $bundle is missing"
    elif [ -L "$bundle" ]; then ASSESS_NOTE="$ASSESS_NOTE${ASSESS_NOTE:+; }bundle $bundle is a symlink; name the file itself"
    else
      breal="$(cd -P -- "$(dirname -- "$bundle")" 2>/dev/null && pwd -P)/$(basename -- "$bundle")"
      local wtreal; wtreal="$(scratch_canonical "$wt" 2>/dev/null)" || wtreal="$wt"
      ASSESS_BUNDLE_SHA="$(scratch_sha256 "$bundle")"
      case "$ASSESS_BUNDLE_SHA" in *[!0-9a-f]*|'') ASSESS_ERROR="cannot compute sha256 of $bundle (no shasum/sha256sum)"; return 1;; esac
      [ "${#ASSESS_BUNDLE_SHA}" = 64 ] || { ASSESS_ERROR="cannot compute sha256 of $bundle"; return 1; }
      case "$breal" in "$wtreal"/*) ASSESS_NOTE="$ASSESS_NOTE${ASSESS_NOTE:+; }bundle $bundle lies inside the worktree that would be removed; keep bundles outside it";;
      *)
        if [ -n "$rec_sha" ] && [ "$rec_sha" != "$ASSESS_BUNDLE_SHA" ]; then ASSESS_NOTE="$ASSESS_NOTE${ASSESS_NOTE:+; }bundle $bundle changed since it was recorded (sha256 differs)"
        elif ! git init -q --bare "$restore" 2>/dev/null || ! GIT_NO_LAZY_FETCH=1 git -C "$restore" -c gc.auto=0 fetch -q "$bundle" '+refs/*:refs/*' 2>/dev/null; then ASSESS_NOTE="$ASSESS_NOTE${ASSESS_NOTE:+; }bundle $bundle does not restore into an empty repository"
        elif ! git -C "$restore" fsck --connectivity-only >/dev/null 2>&1; then ASSESS_NOTE="$ASSESS_NOTE${ASSESS_NOTE:+; }bundle $bundle restores with broken connectivity"
        else ASSESS_BUNDLE_OK=1; fi;;
      esac
    fi
  fi
  for s in $ASSESS_REQUIRED; do
    if [ "$fetch" = 1 ] && g -C "$primary" merge-base --is-ancestor "$s" "refs/remotes/origin/$def" 2>/dev/null; then
      ASSESS_BASIS="$ASSESS_BASIS${ASSESS_BASIS:+; }${s:0:7}: on origin/$def"; continue
    fi
    if [ "$ASSESS_BUNDLE_OK" = 1 ] && git -C "$restore" cat-file -e "$s^{commit}" 2>/dev/null; then
      local kept=""
      while read -r kref ksha; do
        [ -n "$kref" ] || continue
        if g -C "$primary" merge-base --is-ancestor "$s" "$ksha" 2>/dev/null; then kept="$kref"; break; fi
      done <<EOF2
$keeps
EOF2
      if [ -n "$kept" ]; then
        ASSESS_BASIS="$ASSESS_BASIS${ASSESS_BASIS:+; }${s:0:7}: $kept + bundle"; ASSESS_BUNDLE_COMMITS="$ASSESS_BUNDLE_COMMITS${ASSESS_BUNDLE_COMMITS:+ }$s"; continue
      fi
    fi
    ASSESS_UNPRESERVED="$ASSESS_UNPRESERVED${ASSESS_UNPRESERVED:+ }$s"
  done
  [ -z "$ASSESS_ERROR" ]
}

# The repository a worktree belongs to is what git says, never the record's
# text. Sets PRIMARY_REAL and PRIMARY_WHY (non-empty when the record disagrees
# or the common dir cannot be read). Called directly, never in a subshell.
primary_of() {  # <wt> <recorded-primary>
  local cd rec="$2" real
  PRIMARY_REAL=""; PRIMARY_WHY=""
  cd="$(g -C "$1" rev-parse --git-common-dir 2>/dev/null)" || { PRIMARY_WHY="cannot determine the common dir of $1"; return 1; }
  case "$cd" in /*) ;; *) cd="$1/$cd";; esac
  PRIMARY_REAL="$(scratch_canonical "${cd%/.git}" 2>/dev/null)" || PRIMARY_REAL="${cd%/.git}"
  [ -z "$rec" ] && return 0
  real="$(scratch_canonical "$rec" 2>/dev/null)" || real="$rec"
  [ "$real" = "$PRIMARY_REAL" ] && return 0
  PRIMARY_WHY="record names primary $rec but the worktree belongs to $PRIMARY_REAL"; return 1
}

# One gate list for finish --release and check: every line is PASS/FAIL,
# written to $WT_TMP/gates (not stdout: the caller needs the ASSESS_* and
# PRIMARY_REAL variables, which a command substitution would lose). Sets
# GATE_FAILS.
run_gates() {  # <wt> <recorded-primary> <bundle> <rec-sha> <fetch> <for-removal 0/1> <rec-status> <complete>
  local wt="$1" rec_primary="$2" bundle="$3" rec_sha="$4" fetch="$5" for_removal="$6" rec_status="$7" complete="$8"
  GATE_FAILS=0; : >"$WT_TMP/gates"
  gate() { if [ "$1" = 0 ]; then printf 'PASS  %s\n' "$2" >>"$WT_TMP/gates"; else printf 'FAIL  %s\n' "$2" >>"$WT_TMP/gates"; GATE_FAILS=$((GATE_FAILS + 1)); fi; }
  gate "$([ "$complete" = true ] && echo 0 || echo 1)" "record says complete"
  [ "$for_removal" = 1 ] && gate "$([ "$rec_status" = released ] && echo 0 || echo 1)" "record says released"
  if primary_of "$wt" "$rec_primary"; then gate 0 "repository is $PRIMARY_REAL"; else gate 1 "repository: $PRIMARY_WHY"; PRIMARY_REAL="${PRIMARY_REAL:-$rec_primary}"; fi
  local entry=""; [ -n "$PRIMARY_REAL" ] && entry="$(g -C "$PRIMARY_REAL" worktree list --porcelain 2>/dev/null | LC_ALL=C grep -A3 -xF "worktree $wt")"
  gate "$([ -n "$entry" ] && echo 0 || echo 1)" "registered in $PRIMARY_REAL"
  gate "$(printf '%s' "$entry" | grep -q '^locked' && echo 1 || echo 0)" "not locked"
  local dirty; dirty="$(g -C "$wt" status --porcelain 2>/dev/null | wc -l | tr -d ' ')" || dirty="?"
  g -C "$wt" status --porcelain >/dev/null 2>&1 || dirty="?"
  gate "$([ "$dirty" = 0 ] && echo 0 || echo 1)" "clean working tree and index ($dirty change(s))"
  gate "$([ ! -d "$wt/.git/worktrees" ] && echo 0 || echo 1)" "hosts no worktrees"
  gate "$([ -z "$(LC_ALL=C grep -lsxF -e "$wt/.git/objects" -e "$wt/.git/objects/" "$WT_PRIMARIES"/*/.git/objects/info/alternates "$WT_ROOT"/*/*/.git/objects/info/alternates 2>/dev/null)" ] && echo 0 || echo 1)" "lends no objects"
  gate "$([ -z "$(find "$wt" -mindepth 2 -name .git -not -path "$wt/.git/*" 2>/dev/null | head -1)" ] && echo 0 || echo 1)" "no nested repository"
  if assess_preservation "$wt" "$PRIMARY_REAL" "$bundle" "$rec_sha" "$fetch"; then
    gate "$([ -z "$ASSESS_UNPRESERVED" ] && echo 0 || echo 1)" "history preserved (${ASSESS_BASIS:-no basis}${ASSESS_UNPRESERVED:+; UNPRESERVED: $ASSESS_UNPRESERVED}${ASSESS_NOTE:+; $ASSESS_NOTE})"
  else
    gate 1 "history preserved (could not assess: $ASSESS_ERROR)"
  fi
}

# The validator behind finish --release and the printed plan: every gate that
# must hold before a non-forced `git worktree remove`, against the current state.
# Prints one line per gate; exit 0 only when all pass. Nothing is written.
cmd_check() {
  local repo="${1:-}" task="${2:-}"; shift 2 2>/dev/null || usage
  local for_removal=0 fetch=1
  while [ $# -gt 0 ]; do
    case "$1" in
      --for-removal) for_removal=1; shift;;
      --no-fetch) fetch=0; shift;;
      *) die "unknown option: $1" 2;;
    esac
  done
  name_ok "$repo" && name_ok "$task" || die "repo and task must be plain names" 2
  load_record "$repo" "$task" || die "no ownership record for $repo/$task at $OWNERS_DIR/$repo/$task.json"
  [ "$REC_STATUS" = malformed ] && die "record $REC is malformed; fix it by hand"
  local wt="$REC_WT"
  [ -d "$wt" ] || die "worktree $wt is missing"
  local complete; complete="$(scratch_owner_record_dump "$REC" | LC_ALL=C awk -F '\t' '$1 == "complete" { print $3 }')"
  run_gates "$wt" "$(scratch_owner_record_get "$REC" primary)" "$(scratch_owner_record_get "$REC" preserved_bundle)" "$(scratch_owner_record_get "$REC" preserved_bundle_sha256)" "$fetch" "$for_removal" "$REC_STATUS" "$complete"
  cat "$WT_TMP/gates"
  [ "$GATE_FAILS" = 0 ] && { printf 'OK  %s/%s passes every check%s\n' "$repo" "$task" "$([ "$for_removal" = 1 ] && printf ' for removal')"; return 0; }
  printf 'NOT OK  %s/%s: %s check(s) failed\n' "$repo" "$task" "$GATE_FAILS"; return 1
}

cmd_finish() {
  local repo="${1:-}" task="${2:-}"; shift 2 2>/dev/null || usage
  local pr="" note="" release=0 bundle_opt="" fetch=1
  while [ $# -gt 0 ]; do
    case "$1" in
      --pr)     scratch_need_value $# "$1"; pr="$2"; shift 2;;
      --note)   scratch_need_value $# "$1"; note="$2"; shift 2;;
      --owner)  scratch_need_value $# "$1"; OWNER_OPT="$2"; shift 2;;
      --bundle) scratch_need_value $# "$1"; bundle_opt="$2"; shift 2;;
      --release) release=1; shift;;
      --no-fetch) fetch=0; shift;;
      *) die "unknown option: $1" 2;;
    esac
  done
  name_ok "$repo" && name_ok "$task" || die "repo and task must be plain names" 2
  scratch_text_is_sane "${pr:-x}" && scratch_text_is_sane "${note:-x}" && scratch_text_is_sane "${bundle_opt:-x}" || die "option values contain control characters" 2
  local me; me="$(owner_id)"
  load_record "$repo" "$task" || die "no ownership record for $repo/$task at $OWNERS_DIR/$repo/$task.json"
  [ "$REC_STATUS" = malformed ] && die "record $REC is malformed; fix it by hand"
  [ "$REC_OWNER" = "$me" ] || die "task $repo/$task is owned by '$REC_OWNER'; only the owner records completion or release"
  local wt="$REC_WT" primary
  [ -d "$wt" ] || die "worktree $wt is missing; nothing to assess (record left as is)"
  local branch head upstream dirty
  branch="$(g -C "$wt" symbolic-ref -q --short HEAD 2>/dev/null || printf '(detached)')"
  head="$(g -C "$wt" rev-parse HEAD 2>/dev/null)" || die "cannot read HEAD in $wt"
  upstream="$(g -C "$wt" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)" || upstream=""
  if [ -n "$upstream" ] && ! g -C "$wt" merge-base --is-ancestor "$head" "$upstream" 2>/dev/null; then upstream=""; fi
  dirty="$(g -C "$wt" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  # The bundle: the one given now, else the one already recorded. Its sha256 is
  # recorded so a later run notices a replaced file.
  local bundle rec_sha
  if [ -n "$bundle_opt" ]; then
    case "$bundle_opt" in /*) bundle="$bundle_opt";; *) bundle="$PWD/$bundle_opt";; esac; rec_sha=""
  else
    bundle="$(scratch_owner_record_get "$REC" preserved_bundle)"; rec_sha="$(scratch_owner_record_get "$REC" preserved_bundle_sha256)"
  fi
  # The same gate list as `check`; the record the sweep reads must never come
  # from a weaker assessment than the plan's validator.
  run_gates "$wt" "$(scratch_owner_record_get "$REC" primary)" "$bundle" "$rec_sha" "$fetch" 0 "$REC_STATUS" true
  local gates; gates="$(cat "$WT_TMP/gates")"
  primary="$PRIMARY_REAL"
  case "$gates" in *"could not assess: "*) die "cannot assess preservation: ${gates##*could not assess: }; nothing recorded";; esac
  [ -n "$primary" ] || die "cannot determine the repository of $wt; nothing recorded"
  # PR state is informational: a PR head ref alone is not preservation.
  [ -n "$pr" ] || pr="$(scratch_owner_record_get "$REC" pr)"
  local pr_state=""
  if [ -n "$pr" ] && command -v gh >/dev/null 2>&1; then
    case "$pr" in *github.com/*/pull/*)
      local slug num; slug="$(printf '%s' "$pr" | sed -E 's#.*github\.com/([^/]+/[^/]+)/pull/.*#\1#')"; num="${pr##*/}"
      pr_state="$(gh api "repos/$slug/pulls/$num" --jq '"\(.state) merged=\(.merged) head=\(.head.sha)"' 2>/dev/null)" || pr_state="lookup failed";;
    esac
  fi
  local blockers="" n_unp=0
  # Every FAIL line of the shared gate list is a blocker (the "record says
  # complete" gate was given true: this run is what records completion).
  blockers="$(printf '%s\n' "$gates" | LC_ALL=C awk '/^FAIL  / { sub(/^FAIL  /, ""); b = b (b ? "; " : "") $0 } END { printf "%s", b }')"
  if [ -n "$ASSESS_UNPRESERVED" ]; then
    n_unp="$(printf '%s\n' $ASSESS_UNPRESERVED | wc -l | tr -d ' ')"
    blockers="$blockers${blockers:+; }$n_unp commit(s) with no preservation basis (listed above as UNPRESERVED)"
  fi
  local t; t="$(now)"
  {
    printf 'complete\tbool\ttrue\n'
    printf 'completed_at\tstring\t%s\n' "$t"
    printf 'last_used\tstring\t%s\n' "$t"
    printf 'pr\tstring\t%s\n' "$pr"
    printf 'pr_state\tstring\t%s\n' "$pr_state"
    [ -z "$note" ] || printf 'note\tstring\t%s\n' "$note"
    printf 'head_at_finish\tstring\t%s\n' "$head"
    printf 'branch\tstring\t%s\n' "$branch"
    printf 'upstream\tstring\t%s\n' "$upstream"
    printf 'dirty_at_finish\tnumber\t%s\n' "$dirty"
    printf 'required_commits\tstring\t%s\n' "$ASSESS_REQUIRED"
    printf 'preservation_basis\tstring\t%s\n' "$ASSESS_BASIS"
    printf 'unpreserved_at_finish\tnumber\t%s\n' "$n_unp"
    # The bundle is recorded only when it actually covers something required and
    # restored cleanly; the sha256 binds the record to that exact file.
    if [ "$ASSESS_BUNDLE_OK" = 1 ] && [ -n "$ASSESS_BUNDLE_COMMITS" ]; then
      printf 'preserved_bundle\tstring\t%s\n' "$bundle"
      printf 'preserved_bundle_sha256\tstring\t%s\n' "$ASSESS_BUNDLE_SHA"
      printf 'preserved_bundle_commits\tstring\t%s\n' "$ASSESS_BUNDLE_COMMITS"
      printf 'preserved_repository\tstring\t%s\n' "$(g -C "$primary" remote get-url origin 2>/dev/null || printf '%s' "$primary")"
    elif [ -n "$bundle_opt" ] || [ -z "$bundle" ]; then
      # A bundle given now that covers nothing, or no bundle at all: record none.
      printf 'preserved_bundle\tstring\t\n'; printf 'preserved_bundle_sha256\tstring\t\n'; printf 'preserved_bundle_commits\tstring\t\n'; printf 'preserved_repository\tstring\t\n'
    fi
    # (a recorded bundle that was merely unusable this run keeps its fields:
    # the evidence pointer is not lost, and the next check re-evaluates it)
  } >"$WT_TMP/ov"
  # Every finish states released explicitly: a stale "released": true from an
  # earlier run must never survive a later finish that found unpreserved work.
  if [ "$release" = 1 ] && [ -z "$blockers" ]; then
    printf 'released\tbool\ttrue\n' >>"$WT_TMP/ov"
    printf 'released_at\tstring\t%s\n' "$t" >>"$WT_TMP/ov"
  else
    printf 'released\tbool\tfalse\n' >>"$WT_TMP/ov"
    printf 'released_at\tstring\t\n' >>"$WT_TMP/ov"
  fi
  local was_released=0; [ "$REC_STATUS" = released ] && was_released=1
  update_record "$REC" "$WT_TMP/ov"
  if [ "$release" = 1 ] && [ -n "$blockers" ]; then
    [ "$was_released" = 1 ] && printf 'wt: the earlier release of %s/%s is WITHDRAWN\n' "$repo" "$task" >&2
    if [ -n "$ASSESS_UNPRESERVED" ]; then
      printf 'wt: to preserve the unpublished history locally (then run finish --bundle <file> --release):\n' >&2
      printf '  mkdir -p %s\n' "$(shq "$WT_BUNDLES")" >&2
      for s in $ASSESS_UNPRESERVED; do printf '  git -C %s update-ref refs/keep/%s-%s %s\n' "$(shq "$primary")" "$task" "${s:0:7}" "$s" >&2; done
      printf '  git -C %s bundle create %s $(git -C %s for-each-ref --format="%%(refname)" "refs/keep/%s-*")\n' "$(shq "$primary")" "$(shq "$WT_BUNDLES/$repo-$task-keeps.bundle")" "$(shq "$primary")" "$task" >&2
    fi
    die "recorded completion, but NOT released: $blockers. Fix those and run finish --release again."
  fi
  if [ "$release" != 1 ] && [ "$was_released" = 1 ]; then
    printf 'wt: the earlier release of %s/%s is WITHDRAWN (every finish states the release afresh; run finish --release again)\n' "$repo" "$task" >&2
  fi
  printf 'recorded %s for %s/%s (record %s)\n' "$([ "$release" = 1 ] && printf 'completion + release' || printf 'completion')" "$repo" "$task" "$REC"
  printf '  head %s  branch %s  upstream %s  dirty %s  required commits %s  unpreserved %s%s\n' "${head:0:7}" "$branch" "${upstream:-none}" "$dirty" "$(printf '%s\n' $ASSESS_REQUIRED | wc -l | tr -d ' ')" "$n_unp" "${pr_state:+  PR $pr_state}"
  [ -z "$ASSESS_BASIS$ASSESS_NOTE" ] || printf '  preservation: %s%s\n' "$ASSESS_BASIS" "${ASSESS_NOTE:+ ($ASSESS_NOTE)}"
  [ -z "$blockers" ] || printf '  blockers: %s\n' "$blockers"
  # The plan runs the SAME validator (ownership, dependency and preservation
  # checks, against the state at that moment), then the one non-forced removal.
  local envs=""
  [ -n "${AI_SCRATCH_CONFIG_DIR:-}" ] && envs="AI_SCRATCH_CONFIG_DIR=$(shq "$AI_SCRATCH_CONFIG_DIR") "
  envs="${envs}WT_ROOT=$(shq "$WT_ROOT") WT_PRIMARIES=$(shq "$WT_PRIMARIES")"
  printf '\n# Cleanup plan for %s (NOTHING below was executed; wt never deletes)\n' "$wt"
  printf '# Re-run the validator seconds before removal; stop if it is NOT OK:\n'
  printf '%s %s check %s %s --for-removal   # record complete + released, repository as git reports it, registered, not locked, clean, hosts/lends nothing, no nested repo, every required commit preserved (fetches the remote default branch%s and restores the recorded bundle offline; add --no-fetch only when origin is unreachable, then only keep refs + bundle count)\n' "$envs" "$(shq "$here/wt.sh")" "$(shq "$repo")" "$(shq "$task")" "${ASSESS_DEFAULT:+ origin/$ASSESS_DEFAULT}"
  printf '# then, and only then, the non-forced removal (never --force, never prune, never gc):\n'
  printf 'git -C %s worktree remove %s\n' "$(shq "$primary")" "$(shq "$wt")"
  printf '# the branch %s and any refs/keep/* stay in the primary; the record stays as history.\n' "$(shq "$branch")"
}

# Single-quote a value for a shell plan.
shq() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }

WT_TMP="$(mktemp -d "${TMPDIR:-/tmp}/wt.XXXXXX")" || die "no temp dir"
trap 'rm -rf "$WT_TMP"' EXIT
OWNER_OPT=""
cmd="${1:-}"; [ $# -gt 0 ] && shift
case "$cmd" in
  start)  cmd_start "$@";;
  list)   cmd_list "$@";;
  finish) cmd_finish "$@";;
  check)  cmd_check "$@";;
  -h|--help|help|'') usage 0;;
  *) die "unknown command: $cmd" 2;;
esac
