#!/bin/bash
# Build predc and run it.
set -e
cd "$(dirname "$0")"
./build.sh
exec node bin/predc.js "$@"
