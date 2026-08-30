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

cmake -S tvision -B build-tvision \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DTV_BUILD_EXAMPLES=OFF \
    -DTV_BUILD_USING_GPM=OFF

cmake --build build-tvision -j"$(nproc)"
echo "built: $(pwd)/build-tvision/libtvision.a"
