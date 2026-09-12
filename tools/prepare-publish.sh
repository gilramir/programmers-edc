#!/bin/bash
# Stage the three npm packages and check what would go into each tarball.
# Publishes nothing -- the commands to do that are printed at the end.
#
#   tools/prepare-publish.sh            # the real thing: container prebuild
#   tools/prepare-publish.sh --here     # skip the container, for checking the
#                                       # file lists in fifteen seconds
#
# Two files in these tarballs are not in git and are put there by this script,
# for the same reason in both cases: they are copies of something the
# repository already has, and a stale copy committed beside the original is
# worse than no copy at all.
#
#   tvision-node/prebuilds/linux-x64/tvision.node   the container's addon
#   gren-tvision-runtime/pty/harness.py             the pty test harness
#
# Neither is a blocker for a consumer -- without the first they compile from
# source, without the second they write their own harness -- but a release
# missing either is a worse release, and nothing else would notice.
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
HERE_ONLY=0
[ "${1:-}" = "--here" ] && HERE_ONLY=1

say() { printf '\n== %s\n' "$*"; }

# --------------------------------------------------------- the prebuilt addon

say "the prebuilt addon"
PREBUILD=tvision-node/prebuilds/linux-x64/tvision.node
if [ "$HERE_ONLY" = "1" ]; then
    src=tvision-node/build/Release/tvision.node
    [ -f "$src" ] || { echo "prepare-publish: $src is not built" >&2; exit 1; }
    mkdir -p "$(dirname "$PREBUILD")"
    cp "$src" "$PREBUILD"
    echo "   --here: this checkout's addon, which is NOT redistributable."
else
    tools/portable-addon.sh "$PREBUILD"
fi

# --------------------------------------------------------------- the harness

say "the pty harness"
# The master copy stays in tvision-node/test, where forty drivers import it
# from and where `asan.sh` sits beside it. This is the consumer's copy: an
# application built on gren-tvision has node_modules and therefore has this,
# at node_modules/gren-tvision-runtime/pty/harness.py, which is the answer to
# "how do I pty-test my own TUI app" and was a publishing blocker.
mkdir -p gren-tvision-runtime/pty
cp tvision-node/test/harness.py gren-tvision-runtime/pty/harness.py
cmp -s tvision-node/test/harness.py gren-tvision-runtime/pty/harness.py \
    && echo "   pty/harness.py <- tvision-node/test/harness.py ($(wc -l < gren-tvision-runtime/pty/harness.py) lines)"

# ----------------------------------------------------------------- the app

say "predc's compiled Gren"
if [ ! -f programmers-edc/main.js ]; then
    echo "prepare-publish: programmers-edc/main.js is not built." >&2
    echo "      run: devbox run -- programmers-edc/build.sh" >&2
    exit 1
fi
echo "   main.js is $(du -h programmers-edc/main.js | cut -f1), built $(date -r programmers-edc/main.js '+%Y-%m-%d %H:%M')"

# ------------------------------------------------- the version predc reports

say "the version predc reports"
# `--version` is a literal in Cli.gren, because argparse wants one and there is
# nothing in a Gren program that can read package.json at build time. So it can
# disagree with the package, and the only symptom is a released binary claiming
# to be the release before it.
pkg_version=$(node -p "require('./programmers-edc/package.json').version")
cli_version=$(sed -n 's/^    , version = "\(.*\)"/\1/p' programmers-edc/src/Cli.gren)
if [ "$pkg_version" != "$cli_version" ]; then
    echo "   MISMATCH: package.json says $pkg_version, Cli.gren says $cli_version" >&2
    exit 1
fi
echo "   package.json and Cli.gren both say $pkg_version"

# ------------------------------------------------------------ what would ship

say "what would ship"
for pkg in tvision-node gren-tvision-runtime programmers-edc; do
    listing=$(cd "$pkg" && npm pack --dry-run --json 2>/dev/null)
    node -e '
        const p = JSON.parse(process.argv[1])[0];
        const files = p.files.map(f => f.path);
        console.log(`   ${p.name}@${p.version}  ${files.length} files, ${(p.unpackedSize/1024).toFixed(0)} KB`);
        // The three entries that have each been silently missing from a
        // tarball at some point, each for its own reason. Named rather than
        // counted, because a count going up says nothing about which.
        for (const [pkgName, want] of Object.entries({
            "tvision-node": ["tvision/COPYRIGHT", "prebuilds/linux-x64/tvision.node"],
            "gren-tvision-runtime": ["pty/harness.py"],
            "programmers-edc": ["main.js"],
        })) {
            if (pkgName !== p.name) continue;
            for (const f of want) {
                if (!files.includes(f)) {
                    console.error(`   MISSING: ${f}`);
                    process.exitCode = 1;
                }
            }
        }
    ' "$listing"
    # A file: dependency is the one thing npm ships verbatim and nobody can
    # install. It was the shape of this repo until the workspace root existed.
    if grep -q '"file:' "$pkg/package.json"; then
        echo "   MISSING: $pkg still has a file: dependency" >&2
        exit 1
    fi
    if grep -q '"private": true' "$pkg/package.json"; then
        echo "   $pkg is still private -- npm publish will refuse it" >&2
        exit 1
    fi
done

say "to publish, in this order"
cat <<'TXT'
   npm login                               # the token in ~/.npmrc is expired
   npm publish -w tvision-node
   npm publish -w gren-tvision-runtime
   npm publish -w programmers-edc

Each depends on the one above it by version range, so a consumer who installs
the third the moment it lands needs the first two already there.
TXT
