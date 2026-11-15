#!/usr/bin/env bash
# Build an actual Bash 3.2 interpreter without requiring a macOS runner.
set -euo pipefail

dest=${1:?usage: setup-bash32.sh INSTALL_DIRECTORY}
mkdir -p "$dest/bin"
dest=$(cd "$dest" && pwd -P)
build=$(mktemp -d)
trap 'rm -rf "$build"' EXIT

archive=bash-3.2.57.tar.gz
curl --fail --location --silent --show-error \
  "https://ftp.gnu.org/gnu/bash/$archive" -o "$build/$archive"
printf '%s  %s\n' \
  3fa9daf85ebf35068f090ce51283ddeeb3c75eb5bc70b1a4a7cb05868bfe06a4 \
  "$build/$archive" | sha256sum --check --status
tar -xzf "$build/$archive" -C "$build"
cd "$build/bash-3.2.57"
# The old configure probes rely on signed integer wraparound.
CFLAGS='-O2 -fwrapv -std=gnu89' CFLAGS_FOR_BUILD='-O2 -fwrapv -std=gnu89' \
  ./configure --without-bash-malloc --disable-nls
make -j2 bash YACC='bison -y'
install -m 755 bash "$dest/bin/bash"
"$dest/bin/bash" --version
