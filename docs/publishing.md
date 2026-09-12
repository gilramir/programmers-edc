# Publishing

Two npm packages and a Gren package, one of which contains a compiled shared
library and one of which is not on a registry at all. This is what that costs, what it does *not* cost, and how to build for
the platforms this machine is not.

Written down because the answers took a morning to establish and would take
another one to establish again. **Steps 1 to 4 of the order at the end are
done** (2026-09-08) and are marked below. What is left is the prebuild
container and dropping `"private": true`.

## Decided, 2026-09-05

Not publishing yet -- Gilbert wants more of predc first -- but the shape is
settled and these are the answers, so that starting does not mean deciding
again.

| | |
|---|---|
| **linux-x64-gnu** | the only prebuilt binary that matters. Built in a manylinux container, everything but glibc and terminfo linked statically. |
| **arm64** | no prebuild. No hardware here and no demand; source build covers anybody who has it. |
| **macOS** | no Mac owned, and none needed: GitHub Actions runners. Documented below, built when somebody wants it. |
| **Windows** | the box exists but has no toolchain on it. CI runner first; set the box up only to debug something a log cannot explain. |
| **delivery** | prebuildify, binary inside the tarball, source build as the fallback. Not postinstall downloads. |

The order at the end of this file stands. Steps 1 and 2 -- `NAPI_VERSION` and
the LICENSE files -- are worth doing whenever, because neither depends on
anything else and both are things a reader checks first.

## The good news first: the user's `node` does not matter

The addon is written against **Node-API** (`node-addon-api` 8.x, `Napi::` in
`src/*.cc`), which is ABI-stable across Node major versions by contract. One
`.node` file works on Node 18, 20, 22, 24 and everything after. There is no
build-per-Node-version, which is the cost most people remember native addons
for and the one this project does not pay.

**~~One gap to close before shipping.~~ Done, 2026-09-08.** `binding.gyp` used
not to set `NAPI_VERSION`, so the addon compiled against whatever the installed
headers offered and the real minimum Node version was an accident rather than a
decision. It is level 9 now, in `binding.gyp`:

```python
"defines": [ "NAPI_CPP_EXCEPTIONS", "NAPI_VERSION=9" ],
```

with `"engines": { "node": ">=18.17" }` in both packages' `package.json` saying
the same thing to npm. Node-API 9 is Node 18.17+; level 8 reaches back to Node
12 and buys nothing this project needs.

## What does matter

```
$ ldd tvision-node/build/Release/tvision.node
    libncursesw.so.6      hard requirement: TVision's CMake is FATAL_ERROR without it
    libstdc++.so.6        C++ ABI
    libgcc_s.so.1
    libc.so.6 (2.42)      the one that will bite
```

**glibc is the constraint, and building on this machine is the wrong way to
get a prebuild.** glibc symbol versioning is forward-only: a binary linked
against 2.42 refuses to load on Ubuntu 22.04 (2.35) or Debian 12 (2.36). The
answer is to build against an old baseline in a container, not to build where
the code is written.

**ncurses needs saying too, because this is a TUI.** `source/platform/ncurdisp.cpp`
calls `newterm()`, so the library is needed at link time *and* a terminfo
database at run time. Static-linking `libncursesw.a` removes the shared-object
dependency; terminfo is data on the filesystem and cannot be linked in, but
every machine with a terminal has it, so that half is not a problem.

## Linux x64 — the one target that matters now

Build in a container with an old glibc, and make everything else static:

```dockerfile
FROM quay.io/pypa/manylinux_2_28_x86_64      # glibc 2.28, gcc toolchain
RUN yum install -y ncurses-static ncurses-devel cmake
```

and link with:

```
-static-libstdc++ -static-libgcc          # drop libstdc++.so.6, libgcc_s.so.1
libncursesw.a instead of -lncursesw       # drop libncursesw.so.6
```

which leaves **glibc 2.28 and terminfo** as the entire runtime surface — that
is CentOS 7-era and older than anything anybody is running.

Check the result rather than assuming it:

```sh
ldd tvision.node                 # expect only libc, libm, libdl, ld-linux
objdump -T tvision.node | grep GLIBC_ | sed 's/.*GLIBC_/GLIBC_/' | sort -u | tail -1
```

The last line is the highest glibc symbol version required, and it is the real
answer to "how old a distro does this run on".

## macOS — you cannot do this on Linux, and should not try

Two routes exist and both are wrong:

  - **A macOS VM on non-Apple hardware breaks Apple's license.** Not a
    technicality worth arguing about; it is the license.
  - **osxcross** cross-compiles from Linux using the macOS SDK, which has to be
    extracted from Xcode — the same license problem, plus a toolchain that
    breaks on every SDK bump.

**Use GitHub Actions' `macos-latest` runners.** They are Apple hardware, they
are free for public repositories, and they are how essentially every native npm
package builds its macOS artifacts. You do not need to own a Mac.

What changes in the build, beyond the runner:

  - **`libncurses`, not `libncursesw`.** macOS ships ncurses without the wide
    suffix; `source/CMakeLists.txt:95` already falls back to it, and
    `binding.gyp` needs the same fallback because it asks `pkg-config` for
    `ncursesw` by name.
  - **`pkg-config` may not be installed.** Homebrew has it; a bare runner may
    not. Either `brew install pkg-config` in the workflow or stop using
    pkg-config in `binding.gyp` (see below).
  - **The deployment target** decides how old a macOS the binary runs on:
    `MACOSX_DEPLOYMENT_TARGET=11.0` is a reasonable floor.
  - **arm64 and x64 are different binaries.** The runners are arm64 now, so an
    x64 build needs `-arch x86_64` and cross-compilation, or a universal binary
    with `-arch arm64 -arch x86_64`.

## What the conditionals say, and how far they were checked

Written 2026-09-08 from `tvision/CMakeLists.txt` and
`tvision/source/CMakeLists.txt`, which do support all three platforms. They are
in the file rather than on a branch because a CI matrix cannot be started
without them. **Neither arm has ever been compiled.**

What each platform gets:

| | Linux | macOS | Windows |
|---|---|---|---|
| sources | all 206 | all 206 | all 206 |
| `HAVE_NCURSES` | yes | yes | no |
| `compat/windows` | yes | yes | **no** |
| `compat/malloc` | no | **yes** | no |
| ncurses | `pkg-config ncursesw` | `-lncurses` | none |
| `_CRT_*`, `_WIN32_WINNT` | no | no | yes |
| sanitizer | yes | no | no |

Two of those are easy to get wrong by reading the cmake carelessly.
`compat/windows` is the shim *for* Windows headers, so it goes everywhere
except Windows; and `compat/malloc` is included when not Windows and not
Linux or Android, which in practice means macOS and is one `malloc.h`.

**All 206 sources on every platform** is cmake's own rule -- it globs with no
filtering -- and it works because the platform files guard themselves:
`win32con.cpp` is `#ifdef _WIN32` from its second line to its last, and
`ncurdisp.cpp` and `ncursinp.cpp` are `#ifdef HAVE_NCURSES` the same way. Each
compiles to an empty object where it does not belong. So there is one flat
source list, which is also what makes `tvision-sources.gypi` portable.

### What was actually verified

Running `gyp_main.py` directly with `-DOS=mac` and `-DOS=win` -- the same
arguments node-gyp passes, with the OS overridden -- loads the file and
generates makefiles for both. That is not a compile, but it evaluates every
condition and prints the resulting flags, which confirmed the table above:
macOS gets `compat/malloc` and `-lncurses`, Windows gets neither
`HAVE_NCURSES` nor `compat/windows` and does get `_WIN32_WINNT=0x0600`.

**And it found a bug that reading would not have.** Node's own `common.gypi`
defines `_HAS_EXCEPTIONS=0` on Windows, which switches exceptions off inside
MSVC's standard library. Turbo Vision throws and this addon relies on it, and
`ExceptionHandling: 1` does not undo a define. Both Windows arms now carry
`"defines!": [ "_HAS_EXCEPTIONS=0" ]`, which is the documented pattern for a
node-addon-api addon using C++ exceptions on Windows.

**What is still unverified.** The `msvs_settings` blocks -- `ExceptionHandling`,
the `/Zc:` options, the `/wd` list -- are invisible to the make generator, and
gyp's msvs generator hangs on Linux probing for a Visual Studio install, so
nothing here has checked their spelling. Likewise `xcode_settings`: the make
generator only translates those when the *host* is a Mac, so
`MACOSX_DEPLOYMENT_TARGET`, `CLANG_CXX_LANGUAGE_STANDARD` and
`GCC_ENABLE_CPP_EXCEPTIONS` are written from convention. Both are cheap to fix
on the first CI run and are the first thing to suspect there.

And the Linux arm was checked for a regression the same way it should be: the
generated `CFLAGS_CC`, `DEFS` and `INCS` are identical to what the single
unconditional target produced, line for line once sorted.

## Windows — your own box works, CI is less work

TVision supports Windows through `source/platform/win32con.cpp` and the Win32
console API. There is no ncurses on Windows at all.

You have a Windows machine, and setting it up is the documented path:
**Visual Studio Build Tools** (the C++ workload), **Python 3**, then
`npm install` runs node-gyp against MSVC. That is the ordinary Node native
addon story and it works.

**But GitHub Actions' `windows-latest` runner already has all of it**, so the
only reason to set up the local machine is to debug a failure interactively.
Start with CI; set the box up when CI tells you something you cannot read from
a log.

Do not cross-compile from Linux with MinGW. Node-API is a C ABI so it can be
made to work, but `node.exe` is built with MSVC and every deviation from that
path is one you will be debugging alone.

`binding.gyp` used to shell out to `pkg-config` and to
`sh scripts/asan-flags.sh` unconditionally, so the build failed on Windows
before compiling anything. Both are inside `OS=='linux'` now.

Two guesses in the sketch this section used to carry turned out to be wrong,
and are worth recording as such. `"sources": [ ... win32con.cpp ... ]` is not
needed -- the source list is the same 206 everywhere, see above.
`"libraries": [ "user32.lib" ]` is not needed either: Turbo Vision's own
CMakeLists names no Windows libraries, and gyp's msvs generator already links
the default set, which has `kernel32` and `user32` in it.

## arm64 — deliberately not now

No arm64 hardware here and no demand, so no prebuild. What it costs when that
changes: `linux-arm64-gnu` is another container (`manylinux_2_28_aarch64`) and
either a runner with the architecture or `docker buildx` under QEMU, which is
slow but works. macOS arm64 comes free with the runners. Nothing about the code
needs to change; it is entirely a build-matrix question.

Users on arm64 fall through to building from source, which is why the source
path has to keep working even once prebuilds exist.

## Delivering the binary

| | |
|---|---|
| **prebuildify + node-gyp-build** | every platform's binary inside one tarball, picked at `require` time. No postinstall, so it survives `npm ci --ignore-scripts`. Bigger tarball. |
| **per-platform optional deps** | `tvision-node-linux-x64-gnu` and friends, selected by the `os`/`cpu` fields. What esbuild and swc converged on. Smaller installs, more packages to publish and version together. |
| **prebuild-install / node-pre-gyp** | downloads from GitHub releases in a postinstall. Needs network at install time and a postinstall script, both of which are increasingly turned off. |

**Use prebuildify** for one or two platforms. The optional-dependency split
earns its complexity somewhere around five targets, and this is not there.

Keep the source build as the fallback in every case: `node-gyp-build` tries the
prebuild, then `node-gyp rebuild`, which is exactly the behavior wanted.

## The blockers that are not about binaries

**~~The tvision submodule does not travel.~~ It does, and this section was
wrong.** The claim here was that `npm publish` packs a gitlink and the tarball
would contain an empty `tvision/`, so the sources would have to be vendored at
pack time. npm does not read git: `npm-packlist` walks the *filesystem*, where
a checked-out submodule is a directory of ordinary files. Tested directly --
a package with a submodule at `vend/` and `"files": ["vend"]` packs
`vend/a.cpp` and `vend/include/h.h`, and excludes only the submodule's `.git`.

So the submodule moved **into** `tvision-node` (2026-09-08) rather than being
vendored beside it, and a source build works for anybody who installs the
package. `npm pack --dry-run` in `tvision-node` now lists 630 files under
`tvision/source` and 76 under `tvision/include`.

**And it found the one that does not travel, which is the worst possible
one.** `tvision/COPYRIGHT` is not in that tarball. The fork's own `.gitignore`
opens with `*` and re-includes by pattern, and the re-include for files is
`!*.*` -- which means *files with an extension*. `CMakeLists.txt` and
`README.md` come back; `COPYRIGHT` has no dot in it and stays excluded. Git
does not care, because the file is tracked and `.gitignore` only governs
untracked files. **npm-packlist applies the same rules as a filter regardless
of tracking**, including `.gitignore` files nested inside the package. So the
file whose entire purpose is to travel with the binary is the one npm silently
leaves behind, and nothing about the failure is visible from this end.

Naming it in `files` fixes it -- verified on a scratch package reproducing the
rule, where `vend/COPYRIGHT` is absent by default and present the moment
`files` lists it. So `files` is not merely an optimisation to keep the fork's
examples and tests out of the tarball; **it is what makes the package legal.**
The entries the build and the license need are `tvision/source`,
`tvision/include`, `tvision/COPYRIGHT` and `tvision-sources.gypi`.

One more consequence: `--recurse-submodules` on the clone is a publishing
requirement now and not a convenience, since an uninitialized submodule packs
an empty directory and the failure lands at the consumer's `npm install`.

**~~And that raises the cmake question.~~ Done, the same day.** `binding.gyp`
has two targets now: `tvision_lib`, a `static_library` of the 206 sources from
a generated `tvision-sources.gypi`, and `tvision`, the addon, which
`dependencies` it. cmake is gone from the build and from `devbox.json`. The
flags on the library target are the ones cmake was generating, copied over and
commented in place. Three things worth knowing:

  - The list is **committed and checked**, not globbed.
    `scripts/gen-tvision-sources.py` writes it and `--check` fails `devbox run
    check` when it is stale. A `<!@(find ...)` would have run on the user's
    machine.
  - **`-fPIC` is not a default for a gyp `static_library`** and has to be
    named. cmake had `-DCMAKE_POSITION_INDEPENDENT_CODE=ON` for the same
    reason.
  - `TVISION_NO_STL` is **private to the library target**. It was `PRIVATE` in
    cmake too; `src/*.cc` include `<string>` and `<vector>` and mean them.

The prize is that the source fallback needs **only node-gyp**, which every npm
user already has.

It also killed a documented trap: `node-gyp build` used not to relink when only
`libtvision.a` had changed, because the archive was outside gyp's dependency
graph. A `dependencies` edge is that graph.

**The `files` lists are written (2026-09-08), and the tarball was built from
rather than read.** `tvision-node` ships `index.js`, `binding.gyp`,
`tvision-sources.gypi`, `src/`, `scripts/`, `tvision/source`, `tvision/include`
and `tvision/COPYRIGHT` -- 307 files, 372 KB, against 858 with no list at all.
Two entries are less obvious than they look:

  - **`scripts/` is not optional.** `binding.gyp` shells out to
    `scripts/asan-flags.sh` at *configure* time, so leaving the directory out
    breaks `npm install` for every consumer rather than only the sanitizer
    build. (It is also why the file has to become conditional before Windows
    can work -- there is no `sh` there.)
  - **`tvision/COPYRIGHT` has to be named**, for the reason two sections up.

The check that matters is not reading the list. It is `npm pack`, unpack
somewhere else, and build there: 307 files, `node-gyp rebuild` green with no
cmake and no sibling checkout, and the addon loads and exports `start`. `ldd`
on the result is `libncursesw.so.6`, `libstdc++.so.6`, `libgcc_s.so.1`,
`libm`, `libpthread`, `libc` -- and nix's `ld-linux`, which is the whole
argument for building prebuilds in a container and not here.

`gren-tvision-runtime` already had a list and it is complete: the five modules,
the three `bin/` scripts, LICENSE and README.

**Both npm packages are still `"private": true`** and the runtime depends on
`"tvision-node": "file:../tvision-node"`. Those become a real version range on
the day of the first publish.

**The names are decided (2026-09-08).** The runtime's npm name is
`gren-tvision-runtime`, matching its directory. It used to be `gren-tvision`,
which is also the Gren package's name -- two registries, so nothing collided,
but explaining which artifact somebody meant cost a sentence every time and a
name is the one thing that cannot be changed after 1.0.0. `tvision-node` keeps
its name, subject to it being free on npm, which has not been checked. The Gren
package keeps `gilramir/gren-tvision`, which is not a name on a registry but
the GitHub repository it is exported to -- see below.

**~~There is no LICENSE file anywhere.~~ Done.** ISC, at the root and beside
each package meant to be published. What is still outstanding is Turbo
Vision's own: `tvision-node` compiles Turbo Vision into the addon, so
`tvision/COPYRIGHT` -- Borland's 1994 disclaimer, magiblot's MIT, and the MIT
notices of the pieces vendored into it -- has to be in the tarball. It is one
entry in `files`, and as the section above found, it is **excluded by default**
and will not get there on its own.

**"How does a consumer pty-test their own TUI app?"** predc borrows
`harness.py` and `tools/run_tests.py` from the repo it happens to sit in. An
independent application would have neither, and the answer is not "copy the
file". This is a publishing blocker in the sense that it is the first question
anybody who likes the package will ask.

## The Gren half: a package is a repository, and this one is a subdirectory

Everything above is about npm. The third artifact is not on npm and not on any
registry at all, which is the thing to know before planning its release:

```
Gren packages are "just" git repositories hosted on github. As long as you've
tagged your repository with semver formatted tags, anyone can add your package
as a dependency.                            -- gren package validate --help
```

There is nothing to upload. `gren package install gilramir/gren-tvision` reads
the tags of `github.com/gilramir/gren-tvision` and clones one, and the root of
that repository is what a consumer gets -- so it must contain `gren.json`,
`src/Tui.gren` and a README. **A subdirectory of a monorepo cannot be a Gren
dependency**, and no flag makes it one.

So `gren-tvision/` has to exist twice: here, where it is written and where the
examples and the drivers can reach the rest of the repo, and at
`gilramir/gren-tvision`, where it is a repository whose root is that directory.
This one is the master copy. The other is an export, it is written to only by
the export, and nothing is ever committed to it by hand.

### The export

`git subtree split` is the mechanism, because it is repeatable, it carries the
subdirectory's own history, and it is in git rather than in a script somebody
has to maintain:

```sh
tools/export-gren-tvision.sh             # push main
tools/export-gren-tvision.sh --tag       # ...and tag it, from gren.json
tools/export-gren-tvision.sh --dry-run
```

which is `git subtree split --prefix=gren-tvision` and a push of the commit it
prints, with the checks that are easy to skip by hand: a dirty tree (the split
is of *committed* history, so anything uncommitted silently would not go), a
version that gren cannot read, a tag already on the remote, and a remote that
has moved out from under this one.

**Nothing is ever checked out.** `git push <remote> <sha>:refs/heads/main`
pushes straight from this repository, so the export has no working copy, no
temporary directory and no second clone -- it is a remote in `.git/config` and
nothing else. The only footprint is `.git/subtree-cache/`, 1.5 MB. Use only
`git subtree split`: `add`, `pull` and `push` want the remote in this
repository's history and make merge commits here.

Measured rather than sketched. The split takes 1.3s over 173 commits, of which
84 touch the directory, and it is the same cold as warm. Its tree is `src docs
examples test tests gren.json build.sh run.sh README.md LICENSE .gitignore` --
the directory and nothing above it. Two runs back to back give the identical
hash, so a second export is a fast-forward carrying only what changed, and a
commit that touched nothing in `gren-tvision/` becomes no commit at all: a
test export with two new commits, one of them to `FINDINGS.md`, added exactly
one.

**What breaks it is rewriting a commit that has already gone out.** Amending
one in a test moved its split hash from `e73917f` to `0dd5139`, everything
after it was orphaned, and the push was rejected as not a fast-forward. A
rewrite *outside* `gren-tvision/` is invisible to the export -- amending the
`FINDINGS.md` commit did not move the hash at all. So the rule is only about
this directory, and it is: never amend or rebase a commit that has been
exported.

### The tag

**Tag the export.** That is the only tag gren reads, and the version in
`gren-tvision/gren.json` has to agree with it. `gren package bump` moves the
one in the file -- it reads the published docs, compares them with the current
ones and works out whether the change is major, minor or patch -- so run it
here, commit, then export with `--tag`.

**The tag has to be bare `1.0.1`.** `Git.gren` takes the last `/`-separated
segment of `refs/tags/<tag>` and hands it to `SemanticVersion.fromString`,
which splits on `.`, keeps the parts that are integers, and accepts the result
only if there are exactly three. So `v1.0.1` is two parts and `1.0.1-beta` is
three of which one is not a number, and **neither is an error**: `Git.gren`
drops what does not parse with `mapAndKeepJust`, so the package quietly has no
versions and nothing says why. The script checks the shape before pushing.

Other tags in that repository are harmless for the same reason -- gren ignores
what it cannot parse.

**Tag this repository too, under a name of its own** -- `gren-tvision/1.0.1`.
A split commit carries **no** back-pointer: same message, same author and
dates, different tree and parent, and nothing whatever linking it to the commit
it came from. Today's is `4a4c58f` here and `56b83e0` there. Without a tag on
this side there is no way to answer "what was the repository when 1.0.1 went
out", and a name of its own leaves room for `tvision-node` and `predc` to be
released out of the same history.

### `gren package validate` needs a tag before it will run

It is the pre-flight check -- docs, README, version -- and it is the thing you
would want to run *before* the first tag. It will not:

```
-- FAILED TO FETCH VERSIONS FOR PACKAGE ---------------------------------------
I couldn't find any semver compatible tags in this repo.
```

Before the repository existed it said it could not find the repo; now that it
exists and is empty it says this. So the first `1.0.0` goes up unvalidated and
is checked afterwards -- a tag can be moved right up until somebody depends on
it. From the second release on it works normally.

### What does not survive the trip

The exported repository is the directory and nothing above it, so anything in
`gren-tvision/` that reaches outside it is broken there. Three do:

  - **`test/drive_*.py`** put `../tvision-node/test` on `sys.path` for
    `harness.py`. The pty drivers do not run in the export. That is the same
    hole as "how does a consumer pty-test their own TUI app?" below, and it
    should be answered once, for both.
  - **`run.sh`** execs `../gren-tvision-runtime/bin/gren-tui.js`. In the export
    that is the installed `gren-tui`, so the line wants to become one that
    prefers a sibling checkout and falls back to the npm bin.
  - ~~**Links out of `docs/` and `README.md`**~~ -- fixed, and they point at
    this repository by URL now.

A fourth is fixed rather than listed: the ignore rules for this directory were
all in the repository root's `.gitignore`, so none of them traveled and a
clone of the export that ran `./build.sh` showed fifteen untracked `main.js`
files. They are in `gren-tvision/.gitignore` now, which still applies here --
a nested `.gitignore` works either way round.

**And a link that works in both repositories can still be broken where it is
read.** `packages.gren-lang.org` renders a package's README and the
documentation generated from `src/` -- nothing else. So `docs/widgets.md` and
`examples/` are not there to be linked to relatively, however right the link
looks on either GitHub page, and `gren-tvision/README.md`'s links into them are
absolute URLs at `github.com/gilramir/gren-tvision`. The module documentation
needs nothing: its links are all `#Anchor`s within the page.

None of these stops the package working -- a consumer gets `src/`, `gren.json`
and the prose, which is the whole of what they install. They are what makes the
exported repository look abandoned to somebody who clones it, which is a
different and slower kind of damage.

## Suggested order

1. `NAPI_VERSION` and `engines`. **Done, 2026-09-08.**
2. LICENSE files. **Done**, `tvision/COPYRIGHT` included.
3. ~~Vendor tvision at pack time;~~ move the build into `binding.gyp` so cmake
   stops being a requirement. **Done, 2026-09-08** -- and no vendoring was
   needed, see above. The `files` lists are done too; **dropping
   `"private": true` is what is left**, and it is deliberately last, because
   until it goes there is no way to publish either package by accident.
4. `binding.gyp` conditionals for Windows and macOS. **Written, 2026-09-08 --
   and never compiled.** See the section below for what that means and what
   was checked instead.
5. prebuildify for `linux-x64-gnu` in a manylinux container, with the
   `objdump` check in CI so a glibc regression fails the build rather than a
   user's install. **The container is built and works, 2026-09-08** --
   `tools/pack/Containerfile` and `tools/pack.sh`, see below. What is left is
   prebuildify's own layout and the CI job; the compiling half is done and the
   `objdump` line is in the script.
6. Add `macos-latest` and `windows-latest` to the matrix when there is somebody
   on either.
7. Export `gren-tvision` to `gilramir/gren-tvision` and tag it. Independent of
   everything above -- it needs no binary and no container -- but the empty
   repository has to be created before `gren package validate` will run at all.
   See the section above.


## The tarball before the package, 2026-09-08

`tools/pack.sh` builds `dist/predc-<version>-linux-x64.tar.gz`: untar it, run
`./predc`, and that is all. It is not the published package and does not want
to be -- it is the thing to hand a colleague while the package is still being
decided -- but it is the same compiling problem, so it was built out of this
file rather than beside it.

```sh
tools/pack.sh            # ~2 min: container build, then assemble
tools/pack-verify.sh     # run the result on Debian 11 and Debian 12
```

**The container is the whole of it, and it is now real rather than a plan.**
`tools/pack/Containerfile` is manylinux_2_28 -- AlmaLinux 8, glibc 2.28 -- plus
node for node-gyp and a static wide ncurses built from source. `TVNODE_PORTABLE=1`
turns on `-static-libstdc++ -static-libgcc` through
`tvision-node/scripts/portable-flags.sh`, which is the same env-var-and-shell-
script shape `asan-flags.sh` uses and for the same reason.

What comes out needs **libc, libm, libpthread and a terminfo database**, and
its highest glibc symbol is `GLIBC_2.28`. That is the number this file
predicted; it is now measured.

Three things the doing turned up that the planning had not.

**AlmaLinux 8 has no `ncurses-static` package.** The section above assumes
`yum install ncurses-static` and there is no such thing in its repositories, so
the Containerfile builds ncurses 6.5 from source. Two flags in that build are
not optional and neither is obvious:

  - **`CFLAGS=-fPIC`.** A `.node` is a shared object and an archive of non-PIC
    objects cannot go into one. The link fails with `relocation R_X86_64_32S
    against .rodata ... recompile with -fPIC`, which is at least an error
    message that says what to do.
  - **`--with-default-terminfo-dir` and `--with-terminfo-dirs`.** Terminfo is
    data on the filesystem and cannot be linked in, so a static ncurses carries
    the compiled-in search path *of the machine that built it* -- which would
    have been `/opt/ncurses/share/terminfo`, a directory that exists nowhere
    else. The build points them at `/etc/terminfo:/lib/terminfo:/usr/share/terminfo`,
    which is Debian's list and Red Hat's between them.

**Static ncurses is worth more than the shared-object count suggests.**
AlmaLinux builds ncurses *without* versioned symbols and Debian builds it
*with* them. Linking against Alma's shared library leaves unversioned
references, and those do bind against Debian's versioned library -- but that is
the dynamic loader being forgiving rather than a promise anybody made, and it
is the kind of thing that works on four machines and fails on the fifth. A
static `libncursesw.a` has no opinion about any of it.

## The Node floor is 20, and it is not the addon's

`NAPI_VERSION=9` makes the addon load on Node 18.17 and up, and that number is
correct and is still in `engines` for both npm packages. **It is not the floor
for a Gren application**, which is a different question that nobody had asked:
Gren compiles `Array.prototype.toSpliced`, `toSorted` and `toReversed`, and all
three are Node 20. On Node 18 the addon loads, the tarball unpacks, and predc
dies on its first array operation with `array.toSpliced is not a function`.

`programmers-edc/package.json` says `"engines": { "node": ">=20" }` now. The
general form of it is worth keeping in mind for the package's documentation:
**the runtime's floor and the application's floor are set by different things**,
and the higher of the two is whatever the Gren compiler currently emits.

This was found by running the tarball, not by reading it. `ldd` was clean and
the addon loaded; `./predc --help` is what failed. That is the argument for
`tools/pack-verify.sh` existing at all -- it starts the program at a real pty
in a stock Node image and greps what it drew, and the escapes have to be
stripped first, because a menu title is two runs in two colors and a search
for `File` otherwise finds nothing while everything is working.
