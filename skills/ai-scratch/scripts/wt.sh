#!/usr/bin/env bash
# wt.sh — the smallest task-worktree lifecycle that the scratch sweep can trust.
#
#   wt.sh start  <repo> <task> [--branch B] [--base REF] [--purpose TEXT] [--owner ID] [--no-fetch]
#   wt.sh list   [<repo>]
#   wt.sh finish <repo> <task> [--pr URL] [--note TEXT] [--release] [--owner ID]
#
# start   creates (or, for the same owner, resumes) ~/devel/worktrees/portaj/<repo>/<task>
#         from the canonical primary ~/devel/portaj/<repo> without touching the branch
#         that primary has checked out, and writes the ownership record the sweep reads.
# list    shows every recorded worktree: owner, branch, PR, activity, state, blockers.
# finish  records completion (and, with --release, release) plus the preservation
#         evidence, then prints the exact cleanup plan. It deletes NOTHING; removal
#         stays in the verified, non-forced `git worktree remove` flow.
#
# Ownership records are the flat JSON files scratch-sweep.sh consumes (see
# scratch_owner_record_parse in lib-scratch.sh); there is one format, not two.
# Owner identity: --owner, else $WT_OWNER, else user@host. Set WT_OWNER to the
# session id in every agent session so two sessions cannot look alike.
set -u
here="$(cd "$(dirname "$0")" && pwd -P)"
# shellcheck source=lib-scratch.sh
. "$here/lib-scratch.sh"

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-2}"; }
die() { printf 'wt: %s\n' "$1" >&2; exit "${2:-1}"; }

WT_ROOT="${WT_ROOT:-$(scratch_config_get WT_ROOT)}"; WT_ROOT="${WT_ROOT:-$HOME/devel/worktrees/portaj}"
WT_PRIMARIES="${WT_PRIMARIES:-$(scratch_config_get WT_PRIMARIES)}"; WT_PRIMARIES="${WT_PRIMARIES:-$HOME/devel/portaj}"
WT_BRANCH_PREFIX="${WT_BRANCH_PREFIX:-$(scratch_config_get WT_BRANCH_PREFIX)}"; WT_BRANCH_PREFIX="${WT_BRANCH_PREFIX:-jp/f/}"
OWNERS_DIR="$(scratch_owners_dir)"
export GIT_OPTIONAL_LOCKS=0 GIT_NO_LAZY_FETCH=1
g() { git -c core.fsmonitor=false -c gc.auto=0 "$@"; }

name_ok() {  # plain directory name: no separators, no dot-dirs, no leading dash, no control chars
  scratch_text_is_sane "$1" || return 1
  case "$1" in ''|.|..|-*|*/*|*\\*|*' '*) return 1;; esac
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
  } >"$tmp" && mv "$tmp" "$f"
  # Never leave a record the sweep would call malformed: that would freeze every apply.
  case "$(scratch_owner_record_parse "$f")" in malformed*) rm -f "$f"; die "refused to write a malformed record";; esac
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
  case "$parent" in "$primary"/*) die "worktree root $parent is inside the primary $primary";; esac
  case "$primary" in "$parent"/*) die "primary $primary is inside the worktree root $parent";; esac

  if load_record "$repo" "$task"; then
    case "$REC_STATUS" in malformed) die "ownership record $REC is malformed; fix or remove it before reusing the task name";; esac
    [ "$REC_WT" = "$target" ] || die "record $REC names a different worktree ($REC_WT); pick another task name"
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
    g -C "$primary" worktree add -q -b "$branch" "$target" "$base" 2>"$WT_TMP/err" || die "git worktree add failed: $(tr '\n' ' ' <"$WT_TMP/err")"
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
    # A worktree without a record is exactly what the sweep must never see; undo the add we just made.
    g -C "$primary" worktree remove "$target" >/dev/null 2>&1
    die "could not write the ownership record; the new worktree was removed again"
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
  n="$(g -C "$wt" rev-list --count HEAD --not --remotes 2>/dev/null)"; [ "${n:-0}" = 0 ] || add "unpushed ($n)"
  [ -d "$wt/.git/worktrees" ] && add "hosts worktrees"
  [ -f "$wt/.git/objects/info/alternates" ] && add "borrows objects"
  if LC_ALL=C grep -lsF "$wt" "$WT_PRIMARIES"/*/.git/objects/info/alternates "$WT_ROOT"/*/*/.git/objects/info/alternates 2>/dev/null | grep -q .; then add "lends objects"; fi
  [ "$status" = released ] && add "awaiting cleanup"
  printf '%s' "$out"
}

cmd_list() {
  local only="${1:-}"; [ -z "$only" ] || name_ok "$only" || die "repo must be a plain name" 2
  local idx="$WT_TMP/idx"
  scratch_owner_index "$OWNERS_DIR" "$idx" || printf 'wt: some records are malformed (the sweep keeps everything until they are fixed)\n' >&2
  printf '%-28s %-24s %-34s %-14s %-18s %-10s %s\n' "REPO/TASK" "OWNER" "BRANCH" "PR" "ACTIVITY" "STATE" "BLOCKERS"
  while IFS=$'\t' read -r status wthex filehex; do
    local wt file; wt="$(scratch_hex_decode "$wthex")"; file="$(scratch_hex_decode "$filehex")"
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

cmd_finish() {
  local repo="${1:-}" task="${2:-}"; shift 2 2>/dev/null || usage
  local pr="" note="" release=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --pr)    scratch_need_value $# "$1"; pr="$2"; shift 2;;
      --note)  scratch_need_value $# "$1"; note="$2"; shift 2;;
      --owner) scratch_need_value $# "$1"; OWNER_OPT="$2"; shift 2;;
      --release) release=1; shift;;
      *) die "unknown option: $1" 2;;
    esac
  done
  name_ok "$repo" && name_ok "$task" || die "repo and task must be plain names" 2
  scratch_text_is_sane "${pr:-x}" && scratch_text_is_sane "${note:-x}" || die "option values contain control characters" 2
  local me; me="$(owner_id)"
  load_record "$repo" "$task" || die "no ownership record for $repo/$task at $OWNERS_DIR/$repo/$task.json"
  [ "$REC_STATUS" = malformed ] && die "record $REC is malformed; fix it by hand"
  [ "$REC_OWNER" = "$me" ] || die "task $repo/$task is owned by '$REC_OWNER'; only the owner records completion or release"
  local wt="$REC_WT" primary; primary="$(scratch_owner_record_get "$REC" primary)"
  [ -d "$wt" ] || die "worktree $wt is missing; nothing to assess (record left as is)"
  local branch head upstream dirty unpushed reflog_unreach=0 adm="" s
  branch="$(g -C "$wt" symbolic-ref -q --short HEAD 2>/dev/null || printf '(detached)')"
  head="$(g -C "$wt" rev-parse HEAD 2>/dev/null)" || die "cannot read HEAD in $wt"
  upstream="$(g -C "$wt" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)" || upstream=""
  dirty="$(g -C "$wt" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  unpushed="$(g -C "$wt" rev-list --count HEAD --not --remotes 2>/dev/null || printf '?')"
  if [ -n "$primary" ] && [ -d "$primary/.git/worktrees" ]; then
    for s in "$primary"/.git/worktrees/*/gitdir; do [ "$(cat "$s" 2>/dev/null)" = "$wt/.git" ] && adm="$(dirname "$s")"; done
  fi
  if [ -n "$adm" ] && [ -f "$adm/logs/HEAD" ]; then
    for s in $(cut -d' ' -f2 "$adm/logs/HEAD" | sort -u); do
      [ -z "$(g -C "$primary" rev-list --max-count=1 "$s" --not --remotes 2>/dev/null)" ] || reflog_unreach=$((reflog_unreach + 1))
    done
  fi
  # A merged PR whose head is this HEAD preserves every commit of this branch on
  # GitHub (refs/pull/N/head keeps them retrievable after a squash merge deletes
  # the branch), so "on no remote-tracking ref" is not "unpreserved" in that case.
  local pr_state="" pr_head="" merged_here=0
  if [ -n "$pr" ] && command -v gh >/dev/null 2>&1; then
    case "$pr" in *github.com/*/pull/*)
      local slug num; slug="$(printf '%s' "$pr" | sed -E 's#.*github\.com/([^/]+/[^/]+)/pull/.*#\1#')"; num="${pr##*/}"
      pr_state="$(gh api "repos/$slug/pulls/$num" --jq '"\(.state) merged=\(.merged) head=\(.head.sha)"' 2>/dev/null)" || pr_state="lookup failed"
      case "$pr_state" in *"merged=true head=$head"*) merged_here=1; pr_head="$head";; esac;;
    esac
  fi
  if [ "$merged_here" = 1 ]; then
    unpushed=0
    # Private-reflog commits that are ancestors of the merged head are preserved with it.
    if [ -n "$adm" ] && [ -f "$adm/logs/HEAD" ]; then
      reflog_unreach=0
      for s in $(cut -d' ' -f2 "$adm/logs/HEAD" | sort -u); do
        [ -z "$(g -C "$primary" rev-list --max-count=1 "$s" --not --remotes 2>/dev/null)" ] && continue
        g -C "$primary" merge-base --is-ancestor "$s" "$pr_head" 2>/dev/null || reflog_unreach=$((reflog_unreach + 1))
      done
    fi
  fi
  local t; t="$(now)"
  {
    printf 'complete\tbool\ttrue\n'
    printf 'completed_at\tstring\t%s\n' "$t"
    printf 'last_used\tstring\t%s\n' "$t"
    [ -z "$pr" ] || printf 'pr\tstring\t%s\n' "$pr"
    [ -z "$pr_state" ] || printf 'pr_state\tstring\t%s\n' "$pr_state"
    [ -z "$note" ] || printf 'note\tstring\t%s\n' "$note"
    printf 'head_at_finish\tstring\t%s\n' "$head"
    printf 'branch\tstring\t%s\n' "$branch"
    printf 'upstream\tstring\t%s\n' "$upstream"
    printf 'dirty_at_finish\tnumber\t%s\n' "$dirty"
    printf 'unpushed_at_finish\tnumber\t%s\n' "${unpushed:-0}"
    [ "$merged_here" = 1 ] && printf 'preserved_by\tstring\tHEAD is the merged head of %s (retrievable through refs/pull/%s/head)\n' "$pr" "${pr##*/}"
    printf 'private_reflog_unreachable_at_finish\tnumber\t%s\n' "$reflog_unreach"
  } >"$WT_TMP/ov"
  local blockers=""
  [ "$dirty" = 0 ] || blockers="$blockers${blockers:+; }$dirty uncommitted change(s)"
  [ "${unpushed:-1}" = 0 ] || blockers="$blockers${blockers:+; }$unpushed commit(s) on no remote"
  [ "$reflog_unreach" = 0 ] || blockers="$blockers${blockers:+; }$reflog_unreach private-reflog commit(s) reachable from no remote (give them a ref or bundle first)"
  [ -n "$upstream" ] || [ "$merged_here" = 1 ] || blockers="$blockers${blockers:+; }no upstream branch (push it, or record the merged PR)"
  if [ "$release" = 1 ]; then
    if [ -n "$blockers" ]; then
      update_record "$REC" "$WT_TMP/ov"
      die "recorded completion, but NOT released: $blockers. Fix those and run finish --release again."
    fi
    printf 'released\tbool\ttrue\n' >>"$WT_TMP/ov"
    printf 'released_at\tstring\t%s\n' "$t" >>"$WT_TMP/ov"
  fi
  update_record "$REC" "$WT_TMP/ov"
  printf 'recorded %s for %s/%s (record %s)\n' "$([ "$release" = 1 ] && printf 'completion + release' || printf 'completion')" "$repo" "$task" "$REC"
  printf '  head %s  branch %s  upstream %s  dirty %s  unpushed %s  private-reflog unreachable %s%s\n' "${head:0:7}" "$branch" "${upstream:-none}" "$dirty" "$unpushed" "$reflog_unreach" "${pr_state:+  PR $pr_state}"
  [ -z "$blockers" ] || printf '  preservation blockers: %s\n' "$blockers"
  cat <<EOF

# Cleanup plan for $wt (NOTHING below was executed; wt never deletes)
# Re-check seconds before removal, in this order, and stop on the first failure:
git -C ${primary:-<primary>} worktree list --porcelain | grep -qxF 'worktree $wt'      # still registered, not locked
[ -z "\$(git -C '$wt' status --porcelain)" ]                                      # clean
[ "\$(git -C '$wt' rev-list --count HEAD --not --remotes)" = 0 ]                   # every commit on a remote
[ ! -d '$wt/.git/worktrees' ] && ! grep -lsF '$wt' $WT_PRIMARIES/*/.git/objects/info/alternates   # hosts nothing, lends nothing
grep -q '"released": true' '$REC'                                                  # the owner has released it
# then, and only then, the non-forced removal (never --force, never prune, never gc):
git -C ${primary:-<primary>} worktree remove '$wt'
# the branch '$branch' stays in the primary; delete it separately only after the PR is merged, by hand.
EOF
}

WT_TMP="$(mktemp -d "${TMPDIR:-/tmp}/wt.XXXXXX")" || die "no temp dir"
trap 'rm -rf "$WT_TMP"' EXIT
OWNER_OPT=""
cmd="${1:-}"; [ $# -gt 0 ] && shift
case "$cmd" in
  start)  cmd_start "$@";;
  list)   cmd_list "$@";;
  finish) cmd_finish "$@";;
  -h|--help|help|'') usage 0;;
  *) die "unknown command: $cmd" 2;;
esac
