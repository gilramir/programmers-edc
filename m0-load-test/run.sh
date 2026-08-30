#!/bin/bash
# Build inside the devbox shell. NOTE: devbox puts a nix gcc-wrapper on PATH,
# so this is a fully nix-native build -- see FINDINGS.md.
set -e
cd "$(dirname "$0")"
echo "== toolchain =="
echo "node:  $(node -v)  $(command -v node)"
echo "g++:   $(g++ --version | head -1)  $(command -v g++)"
echo
npm install --no-audit --no-fund
npx node-gyp rebuild
echo
echo "== ldd =="
ldd build/Release/m0.node | grep -E 'libc\.|libstdc|ncurses' || true
echo
echo "== test =="
node test.js
