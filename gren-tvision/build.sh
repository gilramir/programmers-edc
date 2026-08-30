#!/bin/bash
# Compile every example against the package source next door.
#
# Each example's gren.json lists "../../src" as a source directory, so they
# build against this working copy rather than a published version. The output
# extension matters: `gren make Main` would produce a self-running executable
# with no handle to attach ports to, and `--output=main.js` produces a module
# that exports Gren.Main.init.
set -e
cd "$(dirname "$0")"

for dir in examples/*/; do
    name=$(basename "$dir")
    printf '%-12s ' "$name"
    (cd "$dir" && gren make Main --output=main.js >/dev/null)
    echo "-> $dir/main.js"
done
