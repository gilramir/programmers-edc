#!/bin/bash
# Build and run one example:  ./run.sh entries
set -e
cd "$(dirname "$0")"
name="${1:-entries}"
[ -d "examples/$name" ] || { echo "no such example: $name"; ls examples; exit 2; }
(cd "examples/$name" && gren make Main --output=main.js >/dev/null)
exec node ../gren-tvision-runtime/bin/gren-tui.js "examples/$name/main.js"
