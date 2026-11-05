#!/usr/bin/env bash
#
# scratch-setup.sh — show or set where the AI scratch directory lives.
#
#   scratch-setup.sh                      # show the resolved root and its source
#   scratch-setup.sh --set ~/work/scratch # persist it (creates the directory)
#   scratch-setup.sh --idle-days 14       # default idle window for the sweep
#   scratch-setup.sh --protect NAME       # pin an extra entry against cleanup
#   scratch-setup.sh --hold "REASON"      # refuse every --apply until --release
#   scratch-setup.sh --release            # lift the hold
#
# Resolution order, highest first: --root, $AI_SCRATCH_ROOT,
# ~/.ai-scratch/config, then /tmp/ai-scratch.
#
set -uo pipefail

SELF_DIR="$(CDPATH= cd -P -- "$(dirname -- "$0")" && pwd -P)"
# shellcheck source=lib-scratch.sh
. "$SELF_DIR/lib-scratch.sh"

set_root=""; set_idle=""; set_protect=""; explicit_root=""; set_hold=""; release=0
while [ $# -gt 0 ]; do
  case "$1" in
    --set)          scratch_need_value $# "--set";        set_root="$2"; shift 2;;
    --set=*) set_root="${1#*=}"; [ -n "$set_root" ] || scratch_die "--set requires a value" 2; shift;;
    --root)         scratch_need_value $# "--root";       explicit_root="$2"; shift 2;;
    --root=*) explicit_root="${1#*=}"; [ -n "$explicit_root" ] || scratch_die "--root requires a value" 2; shift;;
    --idle-days)    scratch_need_value $# "--idle-days";  set_idle="$2"; shift 2;;
    --idle-days=*) set_idle="${1#*=}"; [ -n "$set_idle" ] || scratch_die "--idle-days requires a value" 2; shift;;
    --protect)      scratch_need_value $# "--protect";    set_protect="$2"; shift 2;;
    --protect=*) set_protect="${1#*=}"; [ -n "$set_protect" ] || scratch_die "--protect requires a value" 2; shift;;
    --hold)         scratch_need_value $# "--hold";       set_hold="$2"; shift 2;;
    --hold=*) set_hold="${1#*=}"; [ -n "$set_hold" ] || scratch_die "--hold requires a reason" 2; shift;;
    --release)      release=1; shift;;
    -h|--help)      sed -n '3,15p' "$0"; exit 0;;
    *) scratch_die "unknown option: $1" 2;;
  esac
done

CONFIG="$(scratch_config_path)"
CONFIG_DIR="$(dirname -- "$CONFIG")"

config_put() {  # <KEY> <VALUE>
  mkdir -p "$CONFIG_DIR" || exit 1
  touch "$CONFIG"
  local tmp="$CONFIG.tmp.$$"
  { grep -v "^[[:space:]]*$1[[:space:]]*=" "$CONFIG" 2>/dev/null
    printf '%s = %s\n' "$1" "$2"; } >"$tmp" && mv "$tmp" "$CONFIG"
  printf 'set %s = %s\n' "$1" "$2"
}

if [ -n "$set_root" ]; then
  case "$set_root" in "~/"*) set_root="$HOME/${set_root#\~/}";; esac
  scratch_text_is_sane "$set_root" || scratch_die "that path contains control characters"
  case "$set_root" in /*) : ;; *) scratch_die "the scratch root must be an absolute path, got: $set_root";; esac

  # Create before canonicalizing: a path we cannot stat is a path we cannot
  # bind to a physical identity, and persisting an unresolvable root is how a
  # later sweep ends up pointed somewhere else.
  mkdir -p "$set_root" || scratch_die "cannot create $set_root"
  canon="$(scratch_canonical "$set_root")" || exit 1
  if reason="$(scratch_root_unsafe_reason "$canon")"; then
    scratch_die "refusing to set the scratch root to $canon — that is $reason. Use a subdirectory."
  fi
  config_put AI_SCRATCH_ROOT "$canon"   # persist the canonical form, never the input
fi

if [ -n "$set_idle" ]; then
  case "$set_idle" in ''|*[!0-9]*) scratch_die "--idle-days needs a whole number" 2;; esac
  config_put AI_SCRATCH_IDLE_DAYS "$set_idle"
fi

if [ -n "$set_protect" ]; then
  scratch_text_is_sane "$set_protect" || scratch_die "that name contains control characters"
  # Stored hex-encoded so a name containing a space or glob stays one exact
  # record instead of word-splitting into fragments that match nothing.
  existing="$(scratch_config_get AI_SCRATCH_PROTECT)"
  if scratch_protect_matches "$set_protect" "$existing"; then
    printf 'already protected: %s\n' "$(scratch_display_name "$set_protect")"
  else
    existing="$existing${existing:+ }$(scratch_hex_encode "$set_protect")"
    config_put AI_SCRATCH_PROTECT "$existing"
  fi
fi

if [ -n "$set_hold" ]; then
  scratch_text_is_sane "$set_hold" || scratch_die "that reason contains control characters"
  case "$set_hold" in *=*) scratch_die "the hold reason may not contain '='";; esac
  config_put AI_SCRATCH_HOLD "$set_hold"
fi
if [ "$release" -eq 1 ]; then
  mkdir -p "$CONFIG_DIR" && touch "$CONFIG"
  tmp="$CONFIG.tmp.$$"; grep -v "^[[:space:]]*AI_SCRATCH_HOLD[[:space:]]*=" "$CONFIG" >"$tmp"; mv "$tmp" "$CONFIG"
  printf 'released the hold\n'
fi

# --- report -----------------------------------------------------------------
scratch_resolve_root "$explicit_root"
idle="$(scratch_config_get AI_SCRATCH_IDLE_DAYS)"
protect="$(scratch_config_get AI_SCRATCH_PROTECT)"

printf '\nscratch root : %s\n' "$SCRATCH_ROOT_RAW"
printf 'source       : %s\n' "$SCRATCH_ROOT_SRC"
printf 'idle window  : %s days (%s)\n' "${idle:-7}" "$([ -n "$idle" ] && echo config || echo default)"
shown_protect=""
for h in $protect; do shown_protect="$shown_protect${shown_protect:+, }$(scratch_display_name "$(scratch_hex_decode "$h")")"; done
printf 'protected    : hidden entries%s\n' "${shown_protect:+, plus $shown_protect}"
hold="$(scratch_config_get AI_SCRATCH_HOLD)"
[ -z "$hold" ] || printf 'HOLD         : %s (every --apply refuses until --release)\n' "$hold"
owners="$(scratch_owners_dir)"
owners_idx="$(mktemp "${TMPDIR:-/tmp}/scratch-owners.XXXXXX")" || scratch_die "cannot create a temporary file"
if scratch_owner_index "$owners" "$owners_idx"; then
  n_rel="$(awk -F '\t' '$1 == "released"' "$owners_idx" | wc -l | tr -d ' ')"
  n_all="$(wc -l <"$owners_idx" | tr -d ' ')"
  printf 'ownership    : %s (%s record%s, %s released; entries without a complete + released record are never reclaimed)%s\n' \
    "$owners" "$n_all" "$([ "$n_all" = 1 ] || printf s)" "$n_rel" "$([ -d "$owners" ] || printf ' — directory does not exist, so nothing is released')"
else
  printf 'ownership    : %s — MALFORMED record(s); the sweep keeps everything and refuses --apply until fixed:\n' "$owners"
  scratch_owner_index_malformed "$owners_idx" | sed 's/^/               /'
fi
rm -f "$owners_idx"
printf 'config file  : %s%s\n' "$CONFIG" "$([ -f "$CONFIG" ] && printf '' || printf ' (not present)')"

if canon="$(scratch_canonical "$SCRATCH_ROOT_RAW" 2>/dev/null)"; then
  printf 'resolves to  : %s\n' "$canon"
  if reason="$(scratch_root_unsafe_reason "$canon")"; then
    printf 'status       : UNSAFE — %s; the sweep will refuse to run here\n' "$reason"
  else
    printf 'status       : ok\n'
  fi
else
  printf 'status       : DOES NOT EXIST — run --set to create and record one\n'
fi

# Nothing configured yet: recommend, and make clear this is a question.
if [ -z "${AI_SCRATCH_ROOT:-}" ] && [ -z "$(scratch_config_get AI_SCRATCH_ROOT)" ] && [ -z "$set_root" ]; then
  rec="$SCRATCH_DEFAULT_ROOT"; why="ephemeral, cleared on reboot"
  for c in "$HOME/devel/portaj/ai-scratch" "$HOME/ai-scratch" "$HOME/.local/share/ai-scratch"; do
    if [ -d "$c" ] && [ -n "$(ls -A "$c" 2>/dev/null)" ]; then rec="$c"; why="already exists and has content"; break; fi
  done
  printf '\nNOT CONFIGURED — recommendation:\n\n  %s\n  (%s)\n\n' "$rec" "$why"
  printf 'Confirm this path, or supply a different one:\n  %s --set %s\n' "$0" "$rec"
fi
printf '\n'
