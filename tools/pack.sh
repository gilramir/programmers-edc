#!/bin/bash
# Build a redistributable predc tarball for linux-x64: untar, run, no npm, no
# compiler, no gren. The only thing the machine needs is node 20 or newer.
#
#   tools/pack.sh                 # -> dist/predc-<version>-linux-x64.tar.gz
#   tools/pack.sh --here          # quick and NOT redistributable; see below
#
# This is not the published package. It is the thing to hand a colleague before
# there is one -- doc/publishing.md has the real plan, and step 5 of it (the
# prebuild container) is what this script grew out of.
#
# THE ADDON IS BUILT IN A CONTAINER, AND THAT IS THE WHOLE POINT. A .node built
# in devbox links nix's glibc, libstdc++ and ncurses by absolute /nix/store
# path and needs GLIBC_2.38 besides; it runs on this machine and on nothing
# else. tools/pack/Containerfile is AlmaLinux 8 -- glibc 2.28 -- with a static
# wide ncurses in it, and `--portable` link flags take libstdc++ and libgcc out
# too, so what comes out needs glibc, libm, libdl and a terminfo database.
#
# `--here` skips the container and copies the addon this checkout already
# built. It is for checking the *packaging* -- that the tree unpacks and node
# resolves it -- in fifteen seconds instead of two minutes. The tarball it
# makes will not run anywhere but here, and it says so in its own README.
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
IMAGE=${PREDC_BUILD_IMAGE:-predc-build}
HERE_ONLY=0
[ "${1:-}" = "--here" ] && HERE_ONLY=1

VERSION=$(node -p "require('$ROOT/programmers-edc/package.json').version" 2>/dev/null \
          || sed -n 's/.*"version": "\([^"]*\)".*/\1/p' "$ROOT/programmers-edc/package.json" | head -1)
NAME="predc-$VERSION-linux-x64"
DIST="$ROOT/dist"
STAGE="$DIST/$NAME"

# The compiled Gren, which this script does not build: `gren` lives in devbox
# and nothing in this repo shells out to devbox. Saying which command is
# missing is more use than building it in a way that only works here.
if [ ! -f "$ROOT/programmers-edc/main.js" ]; then
    echo "pack: programmers-edc/main.js is not built." >&2
    echo "      run: devbox run -- programmers-edc/build.sh" >&2
    exit 1
fi

say() { printf '%s\n' "$*"; }


# --------------------------------------------------------------- the addon

ADDON=$ROOT/tvision-node/build/Release/tvision.node

if [ "$HERE_ONLY" = "1" ]; then
    [ -f "$ADDON" ] || { echo "pack: $ADDON is not built" >&2; exit 1; }
    say "addon: reusing this checkout's build (NOT redistributable)"
else
    command -v podman >/dev/null || command -v docker >/dev/null || {
        echo "pack: needs podman or docker to build a portable addon." >&2
        echo "      tools/pack.sh --here skips it, for a tarball that only runs here." >&2
        exit 1
    }
    OCI=$(command -v podman || command -v docker)

    if ! "$OCI" image exists "$IMAGE" 2>/dev/null && \
       ! "$OCI" image inspect "$IMAGE" >/dev/null 2>&1; then
        say "image: building $IMAGE (once, a few minutes)"
        "$OCI" build -t "$IMAGE" "$ROOT/tools/pack"
    fi

    # A scratch copy rather than the checkout itself: the container writes
    # build/ and node_modules/, and neither belongs in the working tree of the
    # machine that ran this. The submodule's sources come along because that is
    # what gets compiled -- everything else in tvision/ is tests and docs.
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
            npm install --no-audit --no-fund --silent node-addon-api node-gyp
            npx node-gyp configure --silent
            npx node-gyp build --silent
        '
    ADDON=$WORK/tvision-node/build/Release/tvision.node
fi

# What it ended up needing, printed rather than assumed. `ldd` here is the
# builder's, which is fine: the question is which sonames are in the file, not
# whether this machine can satisfy them.
say "addon: $(du -h "$ADDON" | cut -f1), needs$(
    readelf -d "$ADDON" | sed -n 's/.*Shared library: \[\(.*\)\]/ \1/p' | tr -d '\n')"
say "addon: highest glibc symbol $(
    objdump -T "$ADDON" | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)"


# --------------------------------------------------------------- the tree
#
# Laid out so that node's own resolution finds everything with no npm and no
# symlinks: lib/bin/predc.js requires 'gren-tvision-runtime', which is found by
# walking up to lib/node_modules, and that requires 'tvision-node', which is
# found in its own. Nothing here is a package that was installed; it is the
# shape npm would have left behind.

rm -rf "$STAGE"
RT=$STAGE/lib/node_modules/gren-tvision-runtime
TV=$RT/node_modules/tvision-node
mkdir -p "$STAGE/lib/bin" "$RT/bin" "$TV/build/Release" "$TV/tvision"

cp "$ROOT/programmers-edc"/{main.js,package.json,LICENSE} "$STAGE/lib/"
cp "$ROOT/programmers-edc/bin"/{predc.js,timezones.js}    "$STAGE/lib/bin/"

cp "$ROOT/gren-tvision-runtime"/{tui.js,diff.js,record.js,tape.js,replay.js} "$RT/"
cp "$ROOT/gren-tvision-runtime"/{package.json,LICENSE}                       "$RT/"
cp "$ROOT/gren-tvision-runtime/bin"/*.js                                     "$RT/bin/"

cp "$ROOT/tvision-node"/{index.js,package.json} "$TV/"
cp "$ROOT/tvision-node/LICENSE"                 "$TV/"
# Turbo Vision travels with the binary because its licence says so: Borland's
# 1994 disclaimer, magiblot's MIT, and the MIT notices of the pieces vendored
# into it, all in one 119-line file. Statically linked code does not stop being
# somebody else's.
cp "$ROOT/tvision-node/tvision/COPYRIGHT"       "$TV/tvision/"
cp "$ADDON"                                     "$TV/build/Release/"

cat > "$STAGE/predc" <<'WRAPPER'
#!/bin/sh
# predc, out of a tarball. Resolves its own directory rather than the working
# one, so this can be symlinked onto a PATH from anywhere.
here=$(cd -- "$(dirname -- "$0")" && pwd)
exec "${NODE:-node}" "$here/lib/bin/predc.js" "$@"
WRAPPER
chmod +x "$STAGE/predc"

{
    cat <<TXT
predc $VERSION -- the programmer's every-day carry, linux-x64.

    ./predc              the desktop, with everything on the Tools menu
    ./predc hex FILE     or straight into a tool
    ./predc --help       every command

Needs node 20 or newer on PATH, and nothing else -- no npm install, no
compiler. (20 and not 18: Gren compiles to Array.prototype.toSpliced, which
node 18 does not have. The native half goes back much further than that.)

To have it everywhere, put this directory somewhere it can stay and link the
launcher onto your PATH:

    ln -s "\$PWD/predc" ~/.local/bin/predc

Settings live in \$XDG_CONFIG_HOME/predc/config.toml, or
~/.config/predc/config.toml. It is TOML and yours to edit; predc keeps your
comments when it writes to it. Notes are files under
~/.local/share/predc/notes/.

TXT
    if [ "$HERE_ONLY" = "1" ]; then
        cat <<'TXT'
*** Built with --here: this binary is linked against the build machine's own
*** libraries and is NOT redistributable. It is for checking the packaging.

TXT
    else
        cat <<'TXT'
The native part is compiled against glibc 2.28, with libstdc++ and ncurses
linked in statically, so it runs on anything from CentOS 7's era onward -- it
wants glibc, libm and a terminfo database and nothing else. If it will not
start, run ldd over the .node under lib/node_modules/, which is the one file
here that is not text.

TXT
    fi
    cat "$ROOT/programmers-edc/LICENSE"
    cat <<'TXT'

Turbo Vision is statically linked into the addon and carries its own terms:
see lib/node_modules/gren-tvision-runtime/node_modules/tvision-node/tvision/COPYRIGHT.
TXT
} > "$STAGE/README.txt"

TARBALL="$DIST/$NAME.tar.gz"
rm -f "$TARBALL"
tar -czf "$TARBALL" -C "$DIST" "$NAME"

say "tarball: ${TARBALL#$ROOT/}  ($(du -h "$TARBALL" | cut -f1), $(tar -tzf "$TARBALL" | wc -l) entries)"
