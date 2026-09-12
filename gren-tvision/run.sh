#!/bin/bash
# Build and run one example:  ./run.sh entries
#
# Anything after the name is passed to the program, which is how `dir` and
# `viewer` are pointed at a path and how `puzzle` takes --seed and --scramble.
set -e
cd "$(dirname "$0")"
name="${1:-entries}"
[ -d "examples/$name" ] || { echo "no such example: $name"; ls examples; exit 2; }
shift || true
(cd "examples/$name" && gren make Main --output=main.js >/dev/null)
# The runtime is a sibling directory here and an installed npm package in the
# exported repository (gilramir/gren-tvision), which is the whole of this
# directory and nothing above it. Prefer the sibling: in this repository that
# is the copy being worked on, and running the installed one instead would
# test the last release against the current package.
for runtime in ../gren-tvision-runtime/bin/gren-tui.js \
               node_modules/gren-tvision-runtime/bin/gren-tui.js \
               ../node_modules/gren-tvision-runtime/bin/gren-tui.js; do
    [ -f "$runtime" ] && exec node "$runtime" "examples/$name/main.js" "$@"
done
command -v gren-tui >/dev/null 2>&1 && exec gren-tui "examples/$name/main.js" "$@"
echo "no gren-tvision-runtime found. Install it here with" >&2
echo "    npm install gren-tvision-runtime" >&2
exit 1
