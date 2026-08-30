#!/bin/bash
# Unit tests for the package's pure logic. The pty drivers in ../test cover
# everything that needs a terminal.
#
# Note `gren make Main` and not `--output=...js`: the plain form produces a
# self-running executable, which is what a test runner wants. The .js form
# produces a module that exports init and runs nothing, which is what the
# examples want. Getting these the wrong way round produces a program that
# exits 0 in silence.
set -e
cd "$(dirname "$0")"
gren make Main >/dev/null
exec node app "$@"
