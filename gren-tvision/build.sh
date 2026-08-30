#!/bin/bash
# Compile the Gren program to a plain CommonJS module.
#
# The --output extension matters. `gren make Main` produces an *executable*:
# a shebang, and a trailing `this.Gren.Main.init({})` that runs the program and
# throws the handle away -- so there is nothing to attach ports to.
# `--output=main.js` produces a module that exports `Gren.Main.init` and runs
# nothing, which is exactly what tui.js needs.
set -e
cd "$(dirname "$0")"
gren make Main --output=main.js
