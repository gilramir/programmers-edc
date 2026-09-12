// Refuse to publish tvision-node with a prebuilt addon that only runs here.
//
// `tools/prepare-publish.sh --here` copies this checkout's own build into
// prebuilds/ so that the file lists can be checked in fifteen seconds instead
// of two minutes. That binary links nix's ncurses, libstdc++ and libgcc by
// absolute /nix/store path and wants a glibc newer than most of the world's.
// It is the right thing for checking packaging and the worst possible thing
// to publish: it installs cleanly, loads on the machine that built it, and
// fails on every other one with a message about a missing shared object.
//
// Existence was already checked and is not the question. What separates the
// two builds is what they ask the loader for: the container's needs libc,
// libm, libpthread and a terminfo database, and nothing else. So the test is
// the sonames, read straight out of the file -- they are plain strings in the
// dynamic string table, so no ELF parser and no readelf is needed, which
// matters because this has to run wherever `npm publish` is run.
const fs = require('fs');

const PREBUILD = 'prebuilds/linux-x64/tvision.node';

// Any of these means the addon was linked against this machine's libraries
// rather than statically in the manylinux container.
const LOCAL_ONLY = ['libncursesw.so.6', 'libncurses.so.6', 'libstdc++.so.6', 'libgcc_s.so.1'];

if (!fs.existsSync(PREBUILD)) {
  console.error(`${PREBUILD} is missing -- run tools/prepare-publish.sh`);
  process.exit(1);
}

const buf = fs.readFileSync(PREBUILD);
const found = LOCAL_ONLY.filter((soname) => buf.includes(soname));

if (found.length > 0) {
  console.error(`${PREBUILD} is not portable: it needs ${found.join(', ')}.`);
  console.error('That is this checkout\'s own build -- the one `--here` copies in.');
  console.error('Rebuild it in the container before publishing:');
  console.error('    devbox run -- tools/prepare-publish.sh');
  process.exit(1);
}

console.log(`${PREBUILD}: portable (${(buf.length / 1024 / 1024).toFixed(1)} MB)`);
