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
# device:inode:ctime. The inode alone is NOT sufficient: on Linux an rmdir
# followed by mkdir frequently REUSES the inode number, so a replaced directory
# presented an identical dev:ino and was accepted as the approved object. ctime
# changes whenever the inode is re-created or its metadata altered, which closes
# that hole. macOS happened to allocate fresh inodes and hid this entirely --
# Linux CI is what surfaced it. Whole-second ctime was still not enough: a
# reused inode plus a replacement made inside the same second is byte-identical,
# so the ctime is captured at NANOSECOND resolution on both platforms (GNU
# exposes it through %z, BSD through %Fc; %Z and %c are seconds only).
# The ctime field is deliberately kept free of colons: callers split this string
# with `cut -d: -f1,2` and `${id%:*}` to compare dev:inode alone, and a colon in
# the last field would silently shift those boundaries.
scratch_devino() {  # <path>
  local out
  out="$(stat -c '%d %i %Z %z' -- "$1" 2>/dev/null)" && {
    printf '%s' "$out" | awk '{n=index($5,"."); print $1":"$2":"$3"."(n?substr($5,n+1):"0")}'
    return 0
  }
  out="$(stat -f '%d:%i:%Fc' -- "$1" 2>/dev/null)" && { printf '%s' "$out"; return 0; }
  return 1
}

# Once the object has been renamed into quarantine it no longer has a published
# path, so nothing can open it afresh. The set of processes able to write to it
# can therefore only SHRINK, and it is exactly the set already holding a
# descriptor or a working directory inside it from before the rename. That set
# is enumerable, which is what makes this a closure rather than a best-effort
# scan -- a lock is not available to us and is not needed.
#
# This asks who CAN still write. The mtime rescan that follows asks what HAS
# been written. Both are required: a writer that closed its descriptor before
# this scan is invisible here but its writes already landed, so the rescan sees
# them; a writer still holding a descriptor has written nothing yet, so the
# rescan is blind to it but this scan is not.
#
# Not covered, and deliberately so: a writer that mapped the file and then
# closed its descriptor leaves nothing to enumerate, and a process that goes
# looking for the quarantine directory by reading the root can defeat any
# scheme short of a lock. Neither is the in-flight editor or parked shell this
# is meant to protect.
#
# Descriptors belonging to another user's processes are not readable on Linux
# and are not reported. The scratch root is a single-user workspace, so this
# scan is authoritative there.
scratch_live_writers() {  # <dir>; 0 none, 1 writers present, 2 cannot determine
  local dir="$1" link p f
  if [ -d /proc/self/fd ]; then
    for p in /proc/[0-9]*; do
      [ "${p##*/}" = "$$" ] && continue
      for f in "$p"/fd/* "$p"/cwd; do
        link="$(readlink "$f" 2>/dev/null)" || continue
        [ "$link" = "$dir" ] && return 1
        case "$link" in "$dir"/*) return 1;; esac
      done
    done
    return 0
  fi
  if command -v lsof >/dev/null 2>&1; then
    # lsof exits 1 when it simply finds nothing open, so this keys on whether
    # it printed a pid, never on its exit status.
    [ -n "$(lsof -t +D "$dir" 2>/dev/null)" ] && return 1
    return 0
  fi
  return 2
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

# Render a filename byte-accurately for review. Every byte is either printed or
# shown as \xNN AT ITS ACTUAL POSITION, so distinct names cannot collide: an
# earlier version escaped only the first line, rendering "a\nbc" and "ab\nc"
# identically. No GNU-only awk features (no strtonum): the hex table is built in
# BEGIN so this behaves the same under BSD and GNU awk.
scratch_display_name() {  # <name>
  printf '%s' "$1" | od -An -v -tx1 | LC_ALL=C awk '
    BEGIN { for (i = 0; i < 16; i++) H[sprintf("%x", i)] = i }
    {
      for (f = 1; f <= NF; f++) {
        v = H[substr($f, 1, 1)] * 16 + H[substr($f, 2, 2)]
        if (v == 92) printf "\\\\"
        else if (v >= 32 && v < 127) printf "%c", v
        else printf "\\x%02x", v
      }
    }'
}

# Decode without losing a trailing newline. Command substitution strips them, so
# a sentinel byte is appended inside the substitution and removed after; without
# this, a name ending in a newline decodes short and apply targets the wrong
# path.
scratch_hex_decode_exact() {  # <hex> -> assigns to SCRATCH_DECODED
  SCRATCH_DECODED="$(scratch_hex_decode "$1"; printf 'X')"
  SCRATCH_DECODED="${SCRATCH_DECODED%X}"
}

# Count structurally invalid candidate records. awk -F'\t' splits on a real tab
# on every platform; `grep -E '\t'` does not -- GNU reads it as a literal "t",
# which rejected every valid manifest on Linux while passing on macOS.
scratch_manifest_bad_records() {  # <file>
  LC_ALL=C awk -F'\t' '
    $1 == "candidate" {
      if (NF != 4 || $2 !~ /^[0-9a-f]+$/ || $3 !~ /^[0-9]+:[0-9]+:[0-9]+(\.[0-9]+)?$/ || $4 !~ /^[0-9]+$/) bad++
    }
    END { print bad + 0 }' "$1"
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
