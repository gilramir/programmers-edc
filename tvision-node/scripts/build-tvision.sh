#!/bin/bash
# Build libtvision.a for linking into a .node.
#
# Two things differ from tvision's own build/ directory and both are required:
#   -DCMAKE_POSITION_INDEPENDENT_CODE=ON  -- a non-PIC archive cannot be linked
#      into a shared object, which is what a .node is.
#   built inside devbox -- the addon is compiled by devbox's nix gcc against
#      nix glibc, and static archives cannot be mixed across toolchains.
set -e
cd "$(dirname "$0")/../.."

# Patches, if any are still needed. The `tvision/` checkout tracks upstream
# master rather than a pinned revision, so this is the exception and not the
# arrangement: a patch is here only while an upstream bug is open, and each
# file says what it is for and when to delete it. Applied with `git apply -R
# --check` first, so a checkout that already has one -- a rebuild, or a
# revision where the fix has landed and the patch no longer applies -- is left
# alone rather than failing the build.
for patch in tvision-node/patches/*.patch; do
    [ -e "$patch" ] || continue
    if git -C tvision apply -R --check "../$patch" 2>/dev/null; then
        echo "already applied: $(basename "$patch")"
    elif git -C tvision apply "../$patch" 2>/dev/null; then
        echo "applied: $(basename "$patch")"
    else
        echo "SKIPPED (does not apply -- fixed upstream? delete it): $(basename "$patch")" >&2
    fi
done

cmake -S tvision -B build-tvision \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DTV_BUILD_EXAMPLES=OFF \
    -DTV_BUILD_USING_GPM=OFF

cmake --build build-tvision -j"$(nproc)"
echo "built: $(pwd)/build-tvision/libtvision.a"
