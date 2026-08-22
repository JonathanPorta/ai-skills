#!/usr/bin/env bash
#
# scratch-setup.sh — show or set where the AI scratch directory lives.
#
#   scratch-setup.sh                     # show the resolved root and its source
#   scratch-setup.sh --set ~/work/scratch  # write it to the config file
#   scratch-setup.sh --idle-days 14      # change the default idle window
#
# Resolution order, highest first:
#   1. --root on the command line
#   2. $AI_SCRATCH_ROOT
#   3. ~/.ai-scratch/config
#   4. /tmp/ai-scratch
#
set -uo pipefail

CONFIG_DIR="${AI_SCRATCH_CONFIG_DIR:-$HOME/.ai-scratch}"
CONFIG="$CONFIG_DIR/config"
DEFAULT_ROOT="/tmp/ai-scratch"

set_root=""; set_idle=""
while [ $# -gt 0 ]; do
  case "$1" in
    --set) set_root="${2:-}"; shift 2;;
    --set=*) set_root="${1#*=}"; shift;;
    --idle-days) set_idle="${2:-}"; shift 2;;
    --idle-days=*) set_idle="${1#*=}"; shift;;
    -h|--help) sed -n '3,15p' "$0"; exit 0;;
    *) printf 'scratch-setup: unknown option: %s\n' "$1" >&2; exit 2;;
  esac
done

read_config_key() {   # <KEY>
  [ -f "$CONFIG" ] || return 0
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$CONFIG" | tail -1
}

if [ -n "$set_root" ]; then
  case "$set_root" in "~/"*) set_root="$HOME/${set_root#\~/}";; esac
  # Refuse to enshrine a root the sweep would rightly refuse to run against.
  case "$set_root" in
    / | "$HOME" | /tmp | /var/tmp | /private/tmp)
      printf 'scratch-setup: refusing to set the scratch root to %s.\n' "$set_root" >&2
      printf '  That directory holds files this tool did not create. Use a subdirectory.\n' >&2
      exit 1;;
  esac
  [ "$(printf '%s' "$set_root" | tr -cd / | wc -c)" -ge 2 ] || {
    printf 'scratch-setup: %s is too shallow to be a safe scratch root\n' "$set_root" >&2; exit 1; }

  mkdir -p "$CONFIG_DIR" "$set_root" || exit 1
  touch "$CONFIG"
  tmp="$CONFIG.tmp.$$"
  { grep -v '^[[:space:]]*AI_SCRATCH_ROOT[[:space:]]*=' "$CONFIG" 2>/dev/null
    printf 'AI_SCRATCH_ROOT = %s\n' "$set_root"; } > "$tmp" && mv "$tmp" "$CONFIG"
  printf 'set AI_SCRATCH_ROOT = %s\n' "$set_root"
fi

if [ -n "$set_idle" ]; then
  case "$set_idle" in ''|*[!0-9]*) printf 'scratch-setup: --idle-days needs a whole number\n' >&2; exit 2;; esac
  mkdir -p "$CONFIG_DIR"; touch "$CONFIG"
  tmp="$CONFIG.tmp.$$"
  { grep -v '^[[:space:]]*AI_SCRATCH_IDLE_DAYS[[:space:]]*=' "$CONFIG" 2>/dev/null
    printf 'AI_SCRATCH_IDLE_DAYS = %s\n' "$set_idle"; } > "$tmp" && mv "$tmp" "$CONFIG"
  printf 'set AI_SCRATCH_IDLE_DAYS = %s\n' "$set_idle"
fi

# Recommend before asking. An existing directory that already looks like scratch
# beats a fresh one the operator then has to migrate into, so prefer a populated
# candidate; otherwise fall back to the ephemeral built-in.
recommend() {
  local c
  for c in "$HOME/devel/portaj/ai-scratch" "$HOME/ai-scratch" "$HOME/.local/share/ai-scratch"; do
    if [ -d "$c" ] && [ -n "$(ls -A "$c" 2>/dev/null)" ]; then
      printf '%s\t%s' "$c" "already exists and has content"; return
    fi
  done
  printf '%s\t%s' "$DEFAULT_ROOT" "ephemeral, cleared on reboot"
}

cfg_root="$(read_config_key AI_SCRATCH_ROOT)"
cfg_idle="$(read_config_key AI_SCRATCH_IDLE_DAYS)"

if [ -n "${AI_SCRATCH_ROOT:-}" ]; then root="$AI_SCRATCH_ROOT"; src="environment (AI_SCRATCH_ROOT)"
elif [ -n "$cfg_root" ];            then root="$cfg_root";      src="config ($CONFIG)"
else                                     root="$DEFAULT_ROOT";  src="built-in default"
fi

printf '\nscratch root : %s\n' "$root"
printf 'source       : %s\n' "$src"
printf 'idle window  : %s days (%s)\n' "${cfg_idle:-7}" "$([ -n "$cfg_idle" ] && echo config || echo default)"
printf 'config file  : %s%s\n' "$CONFIG" "$([ -f "$CONFIG" ] && echo '' || echo ' (not present)')"
if [ -d "$root" ]; then
  printf 'status       : exists\n'
else
  printf 'status       : DOES NOT EXIST — create it, or run --set to point elsewhere\n'
fi

# Nothing configured yet: recommend, and make clear this is a question.
if [ -z "${AI_SCRATCH_ROOT:-}" ] && [ -z "$cfg_root" ] && [ -z "$set_root" ]; then
  IFS=$'\t' read -r rec_path rec_why <<EOF
$(recommend)
EOF
  printf 'NOT CONFIGURED — recommendation:\n\n'
  printf '  %s\n' "$rec_path"
  printf '  (%s)\n\n' "$rec_why"
  printf 'Confirm this path, or supply a different one:\n'
  printf '  scratch-setup.sh --set %s\n\n' "$rec_path"
fi
