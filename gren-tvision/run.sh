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
exec node ../gren-tvision-runtime/bin/gren-tui.js "examples/$name/main.js" "$@"
