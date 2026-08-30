#!/bin/bash
# Run node with AddressSanitizer's runtime preloaded, so an addon built with
# TVNODE_ASAN=1 actually reports. Node itself is not instrumented; preloading
# is what lets the checks compiled into our code see allocations made by node
# and by libtvision.
#
#   TVNODE_ASAN=1 npx node-gyp rebuild
#   test/asan.sh node examples/hello.js
#
# Reports go to build/asan.<pid> rather than stderr: stderr here is a terminal
# that TVision has in raw mode and is actively repainting, which shreds a
# multi-line report into confetti.
set -e
cd "$(dirname "$0")/.."
mkdir -p build
export LD_PRELOAD="$(gcc -print-file-name=libasan.so)"
# The addon is never unloaded and node leaks by design at exit; we are hunting
# overflows, not leaks.
export ASAN_OPTIONS="detect_leaks=0:log_path=$PWD/build/asan${ASAN_OPTIONS:+:$ASAN_OPTIONS}"
exec "$@"
