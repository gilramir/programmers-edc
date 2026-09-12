#!/bin/bash
# Build tvision.node in the manylinux container and put it where told.
#
#   tools/portable-addon.sh path/to/tvision.node
#
# THE ADDON IS BUILT IN A CONTAINER, AND THAT IS THE WHOLE POINT. A .node built
# in devbox links nix's glibc, libstdc++ and ncurses by absolute /nix/store
# path and needs GLIBC_2.38 besides; it runs on this machine and on nothing
# else. tools/pack/Containerfile is AlmaLinux 8 -- glibc 2.28 -- with a static
# wide ncurses in it, and `--portable` link flags take libstdc++ and libgcc out
# too, so what comes out needs glibc, libm, libdl and a terminfo database.
#
# This was the middle of tools/pack.sh until the npm prebuild needed the same
# two minutes of work for a different destination. Both call it now.
set -euo pipefail

OUT=${1:?usage: portable-addon.sh <output .node path>}
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
IMAGE=${PREDC_BUILD_IMAGE:-predc-build}

say() { printf '%s\n' "$*" >&2; }

command -v podman >/dev/null || command -v docker >/dev/null || {
    echo "portable-addon: needs podman or docker." >&2
    exit 1
}
OCI=$(command -v podman || command -v docker)

if ! "$OCI" image exists "$IMAGE" 2>/dev/null && \
   ! "$OCI" image inspect "$IMAGE" >/dev/null 2>&1; then
    say "image: building $IMAGE (once, a few minutes)"
    "$OCI" build -t "$IMAGE" "$ROOT/tools/pack"
fi

# A scratch copy rather than the checkout itself: the container writes build/
# and node_modules/, and neither belongs in the working tree of the machine
# that ran this. The submodule's sources come along because that is what gets
# compiled -- everything else in tvision/ is tests and docs.
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/tvision-node/tvision"
cp "$ROOT/tvision-node"/{binding.gyp,tvision-sources.gypi,index.js,package.json} \
   "$WORK/tvision-node/"
cp -r "$ROOT/tvision-node"/{src,scripts} "$WORK/tvision-node/"
cp -r "$ROOT/tvision-node/tvision"/{source,include} "$WORK/tvision-node/tvision/"
cp "$ROOT/tvision-node/tvision/COPYRIGHT" "$WORK/tvision-node/tvision/"

say "addon: compiling in $IMAGE"
"$OCI" run --rm \
    -v "$WORK:/work:z" -w /work/tvision-node \
    -e HOME=/work -e TVNODE_PORTABLE=1 \
    --userns=keep-id --user "$(id -u):$(id -g)" \
    "$IMAGE" bash -euo pipefail -c '
        npm install --no-audit --no-fund --silent --ignore-scripts node-addon-api node-gyp
        npx node-gyp configure --silent
        npx node-gyp build --silent
    '
BUILT=$WORK/tvision-node/build/Release/tvision.node

# What it ended up needing, printed rather than assumed. `ldd` here is the
# builder's, which is fine: the question is which sonames are in the file, not
# whether this machine can satisfy them.
say "addon: $(du -h "$BUILT" | cut -f1), needs$(
    readelf -d "$BUILT" | sed -n 's/.*Shared library: \[\(.*\)\]/ \1/p' | tr -d '\n')"
HIGHEST=$(objdump -T "$BUILT" | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)
say "addon: highest glibc symbol $HIGHEST"

# The number this is all for, checked rather than admired. A regression here --
# a new call that pulls in a younger symbol -- is a binary that fails to load
# on a user's machine and nowhere before it.
case "$HIGHEST" in
    GLIBC_2.[0-9]|GLIBC_2.1[0-9]|GLIBC_2.2[0-8]) ;;
    *) echo "portable-addon: $HIGHEST is newer than the 2.28 baseline" >&2; exit 1 ;;
esac

mkdir -p "$(dirname "$OUT")"
cp "$BUILT" "$OUT"
say "addon: -> ${OUT#$ROOT/}"
