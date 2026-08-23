# shellcheck shell=bash
# Shared identity and safety rules for the ai-scratch scripts.
#
# Both setup and sweep source this so they cannot disagree about what a root is
# or which roots are safe. Written for bash 3.2 (the macOS system shell): no
# associative arrays, no mapfile, no ${var^^}.

scratch_die() { printf 'scratch: %s\n' "$1" >&2; exit "${2:-1}"; }

# Reject text that cannot survive being stored, displayed, and re-read. A
# newline in a path is the difference between one candidate and two.
scratch_text_is_sane() {  # <text>
  case "$1" in
    '' ) return 1;;
    *[[:cntrl:]]* ) return 1;;
  esac
  return 0
}

# Absolute physical path, symlinks resolved. Empty output means failure, and the
# reason is on stderr. Existence is required: a root we cannot stat is a root we
# cannot reason about.
scratch_canonical() {  # <path>
  local p="$1"
  case "$p" in "~/"*) p="$HOME/${p#\~/}";; esac
  scratch_text_is_sane "$p" || { printf 'scratch: path contains control characters or is empty\n' >&2; return 1; }
  case "$p" in
    /*) : ;;
    *)  printf 'scratch: root must be an absolute path, got: %s\n' "$p" >&2; return 1;;
  esac
  [ -d "$p" ] || { printf 'scratch: not a directory: %s\n' "$p" >&2; return 1; }
  ( CDPATH= cd -P -- "$p" 2>/dev/null && pwd -P ) || {
    printf 'scratch: cannot resolve: %s\n' "$p" >&2; return 1; }
}

# One definition of "unsafe root", used by setup before persisting and by sweep
# before classifying. Prints the reason when unsafe.
scratch_root_unsafe_reason() {  # <canonical-path>
  local r="$1" slashes
  case "$r" in
    /) printf 'the filesystem root'; return 0;;
    "$HOME") printf 'your home directory'; return 0;;
    /tmp|/private/tmp|/var/tmp|/private/var/tmp) printf 'a shared temp directory'; return 0;;
    /Users|/home|/var|/private/var|/usr|/etc|/opt|/Applications|/System|/Library)
      printf 'a shared system directory'; return 0;;
  esac
  # At least two path components, so a single top-level directory can never be
  # a scratch root. Compared on CANONICAL paths, so /tmp/ai-scratch (Linux, two
  # components) and /private/tmp/ai-scratch (macOS, three) both pass.
  slashes="$(printf '%s' "$r" | tr -cd '/' | wc -c | tr -d ' ')"
  [ "$slashes" -ge 2 ] || { printf 'too shallow to be a scratch root'; return 0; }
  return 1
}

# device:inode — object identity that survives a same-path replacement.
scratch_objid() {  # <path>
  ls -di -- "$1" 2>/dev/null | awk '{print $1}' | tr -d ' '
}

# GNU stat is tried FIRST and deliberately. GNU's -f means --file-system and
# takes no format argument, so a BSD-first probe SUCCEEDS on Linux while
# reporting filesystem identity -- identical for every path on one volume, which
# silently defeats the whole point of binding candidates to an inode. BSD stat
# rejects -c outright, so this order is correct on both.
scratch_devino() {  # <path>
  local out
  out="$(stat -c '%d:%i' -- "$1" 2>/dev/null)" && { printf '%s' "$out"; return 0; }
  out="$(stat -f '%d:%i' -- "$1" 2>/dev/null)" && { printf '%s' "$out"; return 0; }
  return 1
}

# Hex, not base64: encoding flags differ across platforms, hex does not. Used so
# candidate names with newlines, tabs, or globs survive a manifest round trip.
scratch_hex_encode() { printf '%s' "$1" | od -An -v -tx1 | tr -d ' \n'; }
scratch_hex_decode() {
  local h="$1" out=""
  while [ -n "$h" ]; do out="$out\\x${h%"${h#??}"}"; h="${h#??}"; done
  printf '%b' "$out"
}

scratch_sha256() {  # <file>
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  else printf 'nosum'; fi
}

# Names are stored hex-encoded and compared hex-to-hex, so a protected entry
# containing a space or glob is one exact record rather than several word-split
# fragments that match nothing.
scratch_protect_matches() {  # <name> <hex-list>
  local want h
  want="$(scratch_hex_encode "$1")"
  for h in $2; do [ "$h" = "$want" ] && return 0; done
  return 1
}

# Render a filename safely for a human to review. Control characters become
# visible escapes so a newline cannot forge a line and an ESC cannot move the
# cursor or colour the operator's terminal.
scratch_display_name() {  # <name>
  printf '%s' "$1" | LC_ALL=C awk '{
    out=""
    for (i = 1; i <= length($0); i++) {
      c = substr($0, i, 1); v = index(SAFE, c)
      if (c == "\\") out = out "\\\\"
      else if (v > 0) out = out c
      else out = out sprintf("\\x%02x", ord(c))
    }
    printf "%s", out
  }
  function ord(ch,   i) { for (i = 0; i < 256; i++) if (sprintf("%c", i) == ch) return i; return 63 }
  BEGIN { SAFE = " !\"#$%&'"'"'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_`abcdefghijklmnopqrstuvwxyz{|}~" }' 2>/dev/null
  # awk sees only the first line of a multi-line name, so say so explicitly.
  # The newline must come from a literal, not $(printf '\n') -- command
  # substitution strips trailing newlines, leaving a pattern that matches
  # everything and marks every name as multi-line.
  local _nl='
'
  case "$1" in *"$_nl"*) printf '\\n...' ;; esac
}

# Size without parsing a pathname. du prints "<size>\t<path>"; a newline inside
# the path spills onto further lines, so only the first line's first field is
# trustworthy.
scratch_size_kb() {  # <path>
  du -sk -- "$1" 2>/dev/null | head -1 | awk '{print $1+0}'
}

scratch_config_path() { printf '%s/config' "${AI_SCRATCH_CONFIG_DIR:-$HOME/.ai-scratch}"; }

scratch_config_get() {  # <KEY>
  local cfg; cfg="$(scratch_config_path)"
  [ -f "$cfg" ] || return 0
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$cfg" | tail -1
}

SCRATCH_DEFAULT_ROOT="/tmp/ai-scratch"

# Precedence: explicit argument, environment, config file, built-in default.
# Sets SCRATCH_ROOT_RAW and SCRATCH_ROOT_SRC.
scratch_resolve_root() {  # [explicit]
  if [ -n "${1:-}" ]; then SCRATCH_ROOT_RAW="$1"; SCRATCH_ROOT_SRC="--root"; return 0; fi
  if [ -n "${AI_SCRATCH_ROOT:-}" ]; then SCRATCH_ROOT_RAW="$AI_SCRATCH_ROOT"; SCRATCH_ROOT_SRC="environment"; return 0; fi
  local c; c="$(scratch_config_get AI_SCRATCH_ROOT)"
  if [ -n "$c" ]; then SCRATCH_ROOT_RAW="$c"; SCRATCH_ROOT_SRC="config"; return 0; fi
  SCRATCH_ROOT_RAW="$SCRATCH_DEFAULT_ROOT"; SCRATCH_ROOT_SRC="built-in default"
}

# Guard used by every option that consumes a value, so a missing value is a
# bounded error instead of a `shift 2` that silently fails and loops forever.
scratch_need_value() {  # <count> <flag>
  [ "$1" -ge 2 ] || scratch_die "$2 requires a value" 2
}
