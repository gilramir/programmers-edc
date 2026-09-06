#!/bin/bash
# Unit tests for predc's pure logic. The pty drivers in ../test cover
# everything that needs a terminal, and they are two orders of magnitude
# slower: what belongs here is anything whose answer is a value rather than a
# screen.
#
# `gren make Main` and not `--output=...js`: the plain form produces a
# self-running executable, which is what a test runner wants. The `.js` form
# produces a module that exports init and runs nothing -- see ../build.sh,
# which wants the other one.
#
# `Tests` and not `Main`: ../src is on the source path and predc has a Main.
# See the note in src/Tests.gren.
set -e
cd "$(dirname "$0")"
gren make Tests >/dev/null
exec node app "$@"
