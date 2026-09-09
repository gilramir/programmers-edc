#!/bin/bash
# Unpack a tarball tools/pack.sh made and run it on a machine that is not this
# one: an old distro, a bare Node image, nothing installed.
#
#   tools/pack-verify.sh                              # the newest tarball
#   tools/pack-verify.sh dist/predc-0.1.0-linux-x64.tar.gz
#   NODE_IMAGES="node:22-bookworm" tools/pack-verify.sh
#
# This exists because reading `ldd` output is not the same as starting the
# program, and the difference was not hypothetical: the first tarball had a
# clean `ldd`, loaded its addon on glibc 2.31, and then died on `--help`
# because Gren compiles `Array.prototype.toSpliced`, which is Node 20. The
# addon's floor is Node 18.17 and predc's is not the addon's.
#
# Debian 11 -- glibc 2.31, three releases back -- because the claim being
# checked is that the binary was built old enough. The full image rather than
# `-slim` because it has python3, and a Turbo Vision program has to be driven
# at a pty: `script` gives it one but no way to type into it after it starts.
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
OCI=$(command -v podman || command -v docker) || {
    echo "verify: needs podman or docker" >&2; exit 1; }

TARBALL=${1:-$(ls -t "$ROOT"/dist/*.tar.gz 2>/dev/null | head -1)}
[ -n "$TARBALL" ] && [ -f "$TARBALL" ] || {
    echo "verify: no tarball. run tools/pack.sh first" >&2; exit 1; }
NAME=$(basename "$TARBALL" .tar.gz)

# One that must work and one that must not, because a floor nobody has stood
# below is a guess. node:18 is expected to fail, and the run says so rather
# than treating it as a failure of the tarball.
IMAGES=${NODE_IMAGES:-"docker.io/library/node:20-bullseye docker.io/library/node:22-bookworm"}

for image in $IMAGES; do
    echo "== $image"
    "$OCI" run --rm \
        -v "$(dirname "$(readlink -f "$TARBALL")"):/dist:ro,z" \
        -v "$ROOT/tools/pack:/pack:ro,z" \
        -w /tmp "$image" bash -euo pipefail -c "
            echo -n '   '; . /etc/os-release 2>/dev/null && echo -n \"\$PRETTY_NAME, \"
            echo \"\$(ldd --version | head -1 | grep -o '[0-9]\\+\\.[0-9]\\+\$' | tail -1) glibc, node \$(node --version)\"
            tar xzf /dist/$NAME.tar.gz
            cd /tmp/$NAME
            addon=lib/node_modules/gren-tvision-runtime/node_modules/tvision-node/build/Release/tvision.node
            echo -n '   needs:'; ldd \"\$addon\" \
                | sed 's/^[[:space:]]*//;s/ =>.*//;s/ (0x.*//' \
                | grep -v '^linux-vdso\|^/lib64/ld-' | sed 's/^/ /' | tr -d '\\n'; echo
            ./predc --help >/dev/null && echo '   --help  ok'
            python3 /pack/drive.py ./predc
        "
done
