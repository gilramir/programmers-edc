#!/bin/bash
# Compile predc.
#
# `--output=main.js` and not a plain `gren make`: the plain form produces a
# self-running executable with no handle to attach ports to, and the runtime
# needs the module that exports Gren.Main.init.
set -e
cd "$(dirname "$0")"
gren make Main --output=main.js "$@" >/dev/null
echo "predc -> $(pwd)/main.js"
