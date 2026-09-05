# Publishing

Two npm packages and a Gren package, one of which contains a compiled shared
library. This is what that costs, what it does *not* cost, and how to build for
the platforms this machine is not.

Nothing here is done yet. It is written down because the answers took a
morning to establish and would take another one to establish again.

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

**One gap to close before shipping.** `binding.gyp` never sets `NAPI_VERSION`,
so the addon compiles against whatever the installed headers offer and the real
minimum Node version is an accident rather than a decision. Pick a level, define
it, and say so:

```python
"defines": [ "NAPI_CPP_EXCEPTIONS", "NAPI_VERSION=9" ],
```

and in `package.json`:

```json
"engines": { "node": ">=18.17" }
```

Node-API 9 is Node 18.17+; level 8 reaches back to Node 12 and buys nothing
this project needs.

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

  - **A macOS VM on non-Apple hardware breaks Apple's licence.** Not a
    technicality worth arguing about; it is the licence.
  - **osxcross** cross-compiles from Linux using the macOS SDK, which has to be
    extracted from Xcode — the same licence problem, plus a toolchain that
    breaks on every SDK bump.

**Use GitHub Actions' `macos-latest` runners.** They are Apple hardware, they
are free for public repositories, and they are how essentially every native npm
package builds its macOS artefacts. You do not need to own a Mac.

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

What changes in `binding.gyp`, which is currently Unix-only:

```python
"conditions": [
  ["OS=='win'", {
    "sources": [ ... win32con.cpp ... ],
    "libraries": [ "user32.lib" ],
    "msvs_settings": { "VCCLCompilerTool": { "ExceptionHandling": 1 } }
  }],
  ["OS!='win'", {
    "cflags_cc": [ "<!@(pkg-config --cflags ncursesw)" ],
    "libraries": [ "<!@(pkg-config --libs ncursesw)" ]
  }]
]
```

The current file shells out to `pkg-config` and to `sh scripts/asan-flags.sh`
unconditionally. Neither exists on Windows, so the build fails before it
compiles anything.

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
prebuild, then `node-gyp rebuild`, which is exactly the behaviour wanted.

## The blockers that are not about binaries

**The tvision submodule does not travel.** `npm publish` packs files, and a git
submodule is a gitlink — the tarball would contain an empty `tvision/`. The
sources have to be vendored at pack time, from the pin the submodule names.
This is what "the `binding.gyp` sibling-checkout blocker" actually is: the gyp
file reaches out to `../tvision/include` and `../build-tvision/libtvision.a`,
neither of which exists for anybody who installed the package.

**And that raises the cmake question.** Today `libtvision.a` is built by a
separate `cmake` invocation that `binding.gyp` then links. Two ways out:

  - **List TVision's sources in the gyp file** — 178 files in
    `source/tvision/` and 29 in `source/platform/`, some of them
    platform-specific. Generated into a committed `.gypi` by a script, because
    gyp has no globbing and `<!@(ls ...)` does not work on Windows. The prize
    is that the source fallback then needs **only node-gyp**, which every npm
    user already has, rather than cmake as well.
  - **Keep cmake, driven by `cmake-js`.** Less work now, and it makes cmake a
    hard install-time requirement for anybody without a prebuild.

The first is more work once and much better for anybody on a platform you do
not ship a binary for. Prefer it.

**Both npm packages are `"private": true`** and `gren-tvision` depends on
`"tvision-node": "file:../tvision-node"`. Those become a real version range on
the day of the first publish, and the names need deciding: `tvision-node` is
unscoped and probably taken; `gren-tvision` as an npm name collides with the
Gren package of the same name, which is a different registry but a confusing
pair of names to explain.

**There is no LICENSE file anywhere.** magiblot/tvision is MIT and Borland's
original was released under a permissive licence; predc, the binding and the
package need their own, and the fork carries tvision's. Nothing can be
published until this exists.

**"How does a consumer pty-test their own TUI app?"** predc borrows
`harness.py` and `tools/run_tests.py` from the repo it happens to sit in. An
independent application would have neither, and the answer is not "copy the
file". This is a publishing blocker in the sense that it is the first question
anybody who likes the package will ask.

## Suggested order

1. `NAPI_VERSION` and `engines`, which is ten minutes and decides the support
   floor.
2. LICENSE files.
3. Vendor tvision at pack time; move the build into `binding.gyp` so cmake
   stops being a requirement.
4. `binding.gyp` conditionals for Windows and macOS, even before either is
   built — they are what makes a CI matrix possible at all.
5. prebuildify for `linux-x64-gnu` in a manylinux container, with the
   `objdump` check in CI so a glibc regression fails the build rather than a
   user's install.
6. Add `macos-latest` and `windows-latest` to the matrix when there is somebody
   on either.
