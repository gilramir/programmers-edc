# Releasing a fix

The procedure, for the next time something needs publishing. `publishing.md`
is the record of *why* things are shaped this way; this file is meant to be
followed without reading it.

Everything that publishes goes through devbox. The system npm on this machine
is 9.2.0 and it ships 98 files that the `files` list excludes;
`tools/prepare-publish.sh` refuses to run under it, but `npm publish` will not.

## 1. Decide what moves

Four artifacts version independently. Move only the ones whose contents change.

| Artifact | Version lives in | Notes |
|---|---|---|
| `programmers-edc` (npm) | `programmers-edc/package.json` **and** `programmers-edc/src/Cli.gren` | Both, or the publish is refused. The command is `predc`; the package name is not. |
| `gren-tvision-runtime` (npm) | `gren-tvision-runtime/package.json` | |
| `tvision-node` (npm) | `tvision-node/package.json` | |
| `gilramir/gren-tvision` (Gren) | `gren-tvision/gren.json` | Use `gren package bump` — it reads the published docs and picks major/minor/patch. |

Dependencies point up this list: predc needs the runtime, the runtime needs the
addon. If you bump a lower one and want consumers to get it, bump the range in
the dependant's `package.json` too.

A fix in `gren-tvision/src/` affects **both** the Gren package and predc, since
predc builds against `local:../gren-tvision`.

## 2. Fix it, with a test that fails first

`devbox run check` constantly, `devbox run test` before committing,
`devbox run test:asan` as well if any C++ moved.

If the bug came from a user, ask for a tape: `predc --record FILE` (see predc's
README). A tape replays with no terminal and usually reproduces in seconds.

## 3. Bump

For predc, edit both files — `package.json`, then the `version` constant in
`Cli.gren` — and rebuild so `main.js` carries it:

```sh
devbox run -- programmers-edc/build.sh
```

For the Gren package:

```sh
devbox run -- bash -c "cd gren-tvision && gren package bump"
```

Nothing needs editing in the tests: `drive_cli.py` and `drive_help.py` read the
expected version out of `package.json`.

Then `devbox run test`, and commit.

## 4. Stage and publish

```sh
devbox run -- tools/prepare-publish.sh
```

Two minutes — it rebuilds the addon in the manylinux container, copies the pty
harness into the runtime, and checks the version agreement and the file lists.
Read its output: it prints `GLIBC_2.28`, the two versions agreeing, three
package lines, and no `MISSING`.

Then publish, lowest first, only what moved:

```sh
devbox run -- npm publish -w tvision-node
devbox run -- npm publish -w gren-tvision-runtime
devbox run -- npm publish -w programmers-edc
```

`npm login` first if it has been a while; the token expires.

## 5. The tarball and the GitHub release

Only if predc moved.

```sh
tools/pack.sh                                     # dist/predc-<version>-linux-x64.tar.gz
tools/pack-verify.sh                              # runs it on Debian 11 and Debian 12
git tag predc/<version> && git push origin predc/<version>
gh release create predc/<version> dist/predc-<version>-linux-x64.tar.gz \
   --title "predc <version>" --notes-file <notes>
```

Tags are namespaced per artifact — `predc/1.0.1`, `tvision-node/1.0.0` — so
four things can be released from one history. Tag whatever you published, at
the commit you published it from.

`dist/` is gitignored. Keep the tarball you released and delete the rest.

## 6. The Gren package, last

Tagging it is what tells `packages.gren-lang.org` a new version exists, which
notifies the Gren Discord. Do it when everything else is live.

```sh
tools/export-gren-tvision.sh --tag           # subtree split, push, tag bare
git tag gren-tvision/<version> && git push origin gren-tvision/<version>
```

The export's tag must be bare — `1.0.2`, not `v1.0.2`. Anything else parses as
*no versions at all* and nothing says why. The script checks.

**Never amend or rebase a commit under `gren-tvision/` that has been
exported.** It changes the split hash and orphans everything after it. A
rewrite anywhere else in the repo is invisible to the export.

`gren package validate` does not work from this checkout — it wants a bare tag
and this repo namespaces them. Skip it; step 7 is a better test.

## 7. Verify from outside

This is the part that keeps finding real bugs, and it takes ten minutes. Every
problem on release day was invisible from inside the repo, where everything
resolves locally.

```sh
# npm, as a stranger
mkdir /tmp/t && cd /tmp/t && npm install programmers-edc
./node_modules/.bin/predc --version

# the repository, as a stranger
git clone --recurse-submodules --depth 1 https://github.com/gilramir/programmers-edc
cd programmers-edc && npm install        # compiles from source, ~40s

# the Gren package, as a stranger: an empty app, its README's own commands
gren package install gren-lang/node
gren package install gilramir/gren-tvision
npm install gren-tvision-runtime
gren make Main --output=main.js
```

CI does the second of these on every push, on Node 20 and 24.

## What will bite

- **Publishing outside devbox.** npm 9 ignores the `files` list inside
  `tvision/`. Check the file count: `tvision-node` is 309, not 407.
- **`tools/prepare-publish.sh --here`.** It stages this machine's own addon,
  which runs nowhere else. `prepublishOnly` now refuses it, but do not publish
  after a `--here` run without re-staging.
- **A submodule commit that was never pushed.** The pin must exist on
  `gilramir/tvision` or every `--recurse-submodules` clone fails. Pushing the
  submodule is a separate `git push` inside `tvision-node/tvision`, and it
  needs your ssh key.
- **Your GitHub PAT.** Fine-grained, and it needs *Contents: read and write*
  for releases and *Actions: read and write* to re-run CI.
- **A published README cannot be changed.** It comes from that version's
  tarball. Getting it right is worth a minute before publishing, and a patch
  release afterwards.
- **`predc --version` and the About box** both come from `Cli.version`. If they
  disagree with `package.json` the publish is refused, which is the point.
