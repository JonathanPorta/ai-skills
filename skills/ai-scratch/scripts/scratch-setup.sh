#!/usr/bin/env bash
#
# scratch-setup.sh — show or set where the AI scratch directory lives.
#
#   scratch-setup.sh                      # show the resolved root and its source
#   scratch-setup.sh --set ~/work/scratch # persist it (creates the directory)
#   scratch-setup.sh --idle-days 14       # default idle window for the sweep
#   scratch-setup.sh --protect NAME       # pin an extra entry against cleanup
#
# Resolution order, highest first: --root, $AI_SCRATCH_ROOT,
# ~/.ai-scratch/config, then /tmp/ai-scratch.
#
set -uo pipefail

SELF_DIR="$(CDPATH= cd -P -- "$(dirname -- "$0")" && pwd -P)"
# shellcheck source=lib-scratch.sh
. "$SELF_DIR/lib-scratch.sh"

set_root=""; set_idle=""; set_protect=""; explicit_root=""
while [ $# -gt 0 ]; do
  case "$1" in
    --set)          scratch_need_value $# "--set";        set_root="$2"; shift 2;;
    --set=*)        set_root="${1#*=}"; shift;;
    --root)         scratch_need_value $# "--root";       explicit_root="$2"; shift 2;;
    --root=*)       explicit_root="${1#*=}"; shift;;
    --idle-days)    scratch_need_value $# "--idle-days";  set_idle="$2"; shift 2;;
    --idle-days=*)  set_idle="${1#*=}"; shift;;
    --protect)      scratch_need_value $# "--protect";    set_protect="$2"; shift 2;;
    --protect=*)    set_protect="${1#*=}"; shift;;
    -h|--help)      sed -n '3,13p' "$0"; exit 0;;
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
  existing="$(scratch_config_get AI_SCRATCH_PROTECT)"
  case " $existing " in *" $set_protect "*) : ;; *) existing="$existing${existing:+ }$set_protect";; esac
  config_put AI_SCRATCH_PROTECT "$existing"
fi

# --- report -----------------------------------------------------------------
scratch_resolve_root "$explicit_root"
idle="$(scratch_config_get AI_SCRATCH_IDLE_DAYS)"
protect="$(scratch_config_get AI_SCRATCH_PROTECT)"

printf '\nscratch root : %s\n' "$SCRATCH_ROOT_RAW"
printf 'source       : %s\n' "$SCRATCH_ROOT_SRC"
printf 'idle window  : %s days (%s)\n' "${idle:-7}" "$([ -n "$idle" ] && echo config || echo default)"
printf 'protected    : hidden entries, plus%s\n' "${protect:+ $protect}"
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
