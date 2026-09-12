# Building and running

Everything happens inside [devbox](https://www.jetify.com/devbox), because the
addon has to be compiled by the same toolchain that will load it: Turbo Vision,
the `.node` and the `node` that loads it must agree on libc and libstdc++ (see
FINDINGS.md). It does not have to be devbox — nothing in the repo shells out to
`devbox`, and [Building without devbox](#building-without-devbox) below is the
same recipe with the same tools installed by hand.

Clone with `--recurse-submodules`, or run `git submodule update --init` in an
existing clone. `tvision-node/tvision/` is a git submodule pointing at
[gilramir/tvision](https://github.com/gilramir/tvision), and nothing builds
without it.

## The commands

```sh
devbox run build      # Turbo Vision, the addon, both Gren builds, predc
devbox run predc      # build and run the application
devbox run check      # consistency, docs, unit tests. No terminal, ~5s
devbox run test       # the above plus every pty driver
devbox run test:asan  # the pty drivers again under AddressSanitizer
```

`check` and `test` must both be green before a commit, and `test:asan` too for
anything that touches C++. After editing `tvision-node/src/`, rebuild the addon
with `(cd tvision-node && npx node-gyp build)`.

The pty drivers run several at a time through `tools/run_tests.py`, which can
also be run directly while working on one:

```sh
devbox run -- python3 tools/run_tests.py entries   # just this one
devbox run -- python3 tools/run_tests.py -j1       # one at a time
```

## Running the examples

```sh
devbox run gren           # the entries example, in Gren
devbox run gren -- hello  # or any other example
devbox run hello          # the plain-JavaScript examples, in tvision-node
devbox run demo
devbox run ascii
devbox run form
```

`Enter` does not press buttons, select list items, or tick check boxes in Turbo
Vision; `Space` does. See FINDINGS.

### The JavaScript examples

These live in `tvision-node/examples/` and know nothing about Gren.

In `hello`: `Alt-G` or the Hello menu opens the greeting, `Tab` moves between
buttons, `Space` presses one, `Alt-X` quits.

In `demo`: `Alt-C` opens a clock painted by `setInterval`, `Alt-D` a directory
listing produced by `await fs.readdir()`; `Space` on an entry stats it
asynchronously, `../` walks up. `Alt-G` opens a modal dialog — it takes all the
input, as a modal dialog should, but the clock behind it keeps ticking.
Modality was hoisted out of `execView`'s nested loop; see FINDINGS.

In `ascii`: arrows and Home/End move the selection, any printable key jumps to
that character — every keystroke is handled in JavaScript, and the chart itself
is painted from a JS array of strings.

In `form`: `Alt-N` opens a record form with check boxes and radio buttons;
`File ▸ Samples ▸ More` is a submenu inside a submenu; `List records` and
`Clear` are grayed out until there is something to list.

### The Gren examples

One directory each under `gren-tvision/examples/`, and every one of them is a
port of a C++ program from `tvision/examples/`.

In `gren`: `Alt-A` adds an entry through a modal dialog, the clock is a
`Time.every` subscription, and closing the entries window tells the Gren model
so it stays closed until `Alt-L` puts it back.

In `gren -- forms` (tvision's `tvforms`): arrow keys move through a sorted
collection of records and the window on the right follows, because the model is
told where the highlight is. `F3` edits the highlighted record in a form with
labeled fields, check boxes and radio buttons; `F2` adds one; `F8` deletes one,
and with none left both `F3` and its menu entry go gray. Saving a renamed record
re-sorts the list and the highlight follows it there.

In `gren -- ascii` (tvdemo's chart): the same chart as `devbox run ascii`, but
the eight rows of code page 437 come out of a Gren array and the selected cell
is `cursor = Just { x, y }` on the canvas. Arrows and Home/End move it, any
printable key jumps to that character, and a click lands where you clicked.

The rest:

| | |
|---|---|
| `gren -- calendar` | tvdemo's calendar. Up/Down change the month; today is the one thing on the canvas painted in a color of its own |
| `gren -- puzzle` | tvdemo's sliding puzzle. `--seed=` and `--scramble=` make the board a pure function of two numbers, which is how the test wins the game |
| `gren -- calc` | tvdemo's calculator. Type at it or click the keys — the keypad can be pressed but never holds the caret |
| `gren -- palette` | tvision's palette example, whose entire subject the port removes |
| `gren -- mouse` | tvdemo's mouse dialog. The scroll bar sets the double-click delay; double-click the strip to feel where the boundary is |
| `gren -- dir` | tvdir. A directory tree with no tree widget: the rows are a fold over the model |
| `gren -- demo` | tvdemo's shell. `Windows ▸ Tile` and `Cascade` are Turbo Vision's; the event viewer lists what crosses the port |
| `gren -- viewer` | tvdemo's file viewer, with both scroll bars. Takes a path |
| `gren -- edit` | tvedit. A text editor: takes a path, F2 saves. The one view whose contents do not travel with the render |

And one that is not a port at all. In `gren -- watch`: give it a directory and
some commands, and it runs them whenever anything in there changes --
`run.sh watch src 'npm test' 'npm run lint'`, one window per command. This is
the example that says what the binding is for. A Turbo Vision program has one
source of events and it is the user; `FileSystem.watchRecursive` is a `Sub`, so
the outside world can send this one a message. The children run at once and
none of them blocks, and a change arriving mid-run kills that run and starts
again -- `ChildProcess.spawn` hands the model a `Process.Id`. `Alt-R` runs now,
`Alt-C` stops.

[`gren-tvision/examples/README.md`](../gren-tvision/examples/README.md) says
what each port forced into the API.

## A redistributable predc

`tools/pack.sh` builds one for linux-x64 —
`dist/predc-<version>-linux-x64.tar.gz`, which untars and runs with nothing on
the machine but node 20. The addon in it is compiled in a container against
glibc 2.28 with libstdc++ and ncurses linked in statically, because a binary
built in devbox runs nowhere but here; `tools/pack-verify.sh` runs the result on
Debian 11 and 12 to say so. This is not the published package — see
[publishing.md](publishing.md) — it is what to hand somebody before there is
one.

## Building without devbox

devbox supplies four things and nothing else — **node 22**, **gren 0.6**,
**pkg-config** and **ncurses with its dev output**. Every script here (the two
`build.sh`, `run.sh`, `tools/run_tests.py`) is plain and only wants those on
`PATH`. (`graphviz` is the fifth package and is only needed to regenerate the
one diagram, with `devbox run docs:diagrams`.)

**cmake is not one of them.** Turbo Vision used to be a separate cmake build
producing `build-tvision/libtvision.a`; it is a target inside
`tvision-node/binding.gyp` now, so node-gyp is the whole build. That is for the
sake of whoever installs the published package on a platform with no prebuilt
binary: node-gyp they already have, cmake they may not.

| | |
|---|---|
| node 22 | what this is pinned to and developed against |
| `gren` 0.6.6 | `npm i -g gren-lang@0.6.6` — npm's `gren-lang` is that version and its bin is `gren` |
| a C++17 compiler and make | Turbo Vision and the addon, both through node-gyp |
| pkg-config and the ncursesw dev files | `binding.gyp` calls `pkg-config --cflags/--libs ncursesw` for both of its targets |
| python3 | node-gyp wants it, and every test driver is written in it — standard library only, nothing to `pip install` |

On Debian and Ubuntu the system half is
`build-essential pkg-config libncurses-dev python3`; `libncurses-dev` is
the package that ships `ncursesw.pc`.

```sh
git submodule update --init                        # fills tvision-node/tvision/
npm install                                        # one, at the root: see below
(cd tvision-node && npx node-gyp configure && npx node-gyp build)
gren-tvision/build.sh
programmers-edc/build.sh
```

**One `npm install`, at the root, and not one per package.** The three npm
directories are an npm workspace, so the root install is what creates
`node_modules/` and symlinks the three into it -- which is what makes
`gren-tvision-runtime`'s dependency on `tvision-node@^1.0.0` resolve to the
copy in this checkout instead of to the registry. Installing inside one of them
on its own does not do that.

The `npm install` also compiles the addon, through `node-gyp-build`, so the
`node-gyp` line after it is normally a no-op -- it is there because it is what
to run after editing `tvision-node/src/`, and because `configure && build` is
seconds where `rebuild` is 46 of them.

That is `devbox run build` with the nix part taken out. `check` and `test` are
the same:

```sh
python3 tools/check_consistency.py
(cd gren-tvision && gren docs --output=/dev/null)
(cd gren-tvision-runtime && node --test test/*.test.js)
(cd gren-tvision/tests && ./run.sh)
python3 tools/run_tests.py
```

`devbox run gren -- entries` is `gren-tvision/run.sh entries`, and
`devbox run predc` is `programmers-edc/run.sh`.

Four things that will bite:

**Do not copy `tvision-node/build/` from another machine.** Build it there. A
`.node` and the Turbo Vision objects linked into it have to come from one
toolchain and one libc, and inside devbox that is nix's gcc rather than the
system's. Either host is fine; mixing them is not — and a binary built inside
devbox links against nix's glibc and will not load anywhere else, which is why
[publishing.md](publishing.md) says prebuilds have to come out of a container.

**The `tvision-node/tvision/` checkout is a submodule, pinned to a revision** of
the `patches` branch of [gilramir/tvision](https://github.com/gilramir/tvision)
— upstream master plus the fixes that have not landed upstream yet, one commit
each. The pin is a fact recorded in this repo's history, which is the point:
"which tvision was this built against" has an answer afterwards. Moving it
forward is `git submodule update --remote tvision-node/tvision` and a commit
here — plus `tvision-node/scripts/gen-tvision-sources.py`, because the list of
files node-gyp compiles is committed rather than globbed and `check` fails if
it is stale. A clone that skipped `--init` fails in ways that look like this
repo's fault.

**The first build needs network twice**: `gren make` fills `~/.cache/gren` with
`gren-lang/core`, `gren-lang/node`, `gren-lang/url`, `gilramir/gren-argparse`
and `gilramir/gren-bignum`, and node-gyp downloads node's headers.

**The layout is load-bearing.** predc's `gren.json` names the package as
`local:../gren-tvision`, each example's lists `"../../src"`, and the two npm
packages depend on each other by `file:` path — so `programmers-edc/` cannot be
built on its own, and the directories have to keep their relative positions.

## The Turbo Vision fork

`tvision-node/tvision/` is a fork of [magiblot/tvision][tv], and these are its
branches:

| | |
|---|---|
| `master` | tracks `upstream/master` untouched |
| `patches` | what this repo builds — `master` plus every unlanded fix |
| `fix/…` | one per upstream issue, one commit off `master`, PR-shaped |

Inside `tvision/`, `origin` is the fork and `upstream` is
[magiblot/tvision][tv]. A fix starts as a `fix/…` branch off `master`, gets
cherry-picked onto `patches`, and both are deleted once it lands upstream and
`master` moves past it. There is no patch directory: what the submodule is
checked out at is what gets built. Note that `git submodule update` leaves the
checkout on a detached HEAD, which is a poor place to write the next fix —
`(cd tvision && git checkout patches)` first. `.gitmodules` uses the https URL
so a clone needs no key; the checkout's own `origin` is the ssh one, and
`git submodule sync` will overwrite that if you ever run it.

[tv]: https://github.com/magiblot/tvision

Five commits sit on `patches` today:

  - a `delete`/`delete[]` mismatch that kills any AddressSanitizer build
    ([#230][i230]);
  - a double-width character that TVision draws and then erases
    ([#233][i233]);
  - `TMenuView::findHotKey` following a null `subMenu`, which segfaults on
    the next keystroke after a menu gains an item with no command
    ([#234][i234]);
  - `TView::calcBounds` clamping a view's size against the desktop and
    never its origin, so shrinking a terminal and growing it back can leave a
    window hanging off the right or the bottom edge ([#235][i235]);
  - and `TWindow::zoom` restoring the rectangle it stored at zoom time without
    checking it against the desktop it is restoring onto, so a window zoomed on
    a wide terminal and un-zoomed on a narrow one comes back beside the desktop
    rather than on it — often entirely off the screen ([#239][i239]).

FINDINGS has the story of each.

**`tools/build-tvdemo.sh` builds the fork's own `examples/tvdemo`**, which
nothing else here does — node-gyp compiles the library into the addon and stops
there. It is for upstream reports: a bug is worth more to the maintainer as a
picture of his own demo than as a description of ours, and the script plus
`tvision-node/test/harness.py` and `tools/shot.py` is how the screenshots in
`#239` were made. Build in a worktree, and take the baseline from `patches~1`
rather than `master` so that the only difference is the commit being argued
about; the script's header has the rest.

The last two are the only ones with no pull request behind them. For `#235` the
issue went first on purpose: the fix has a judgment call in it — which views
the origin may be moved for — that the maintainer may want to make differently,
and a patch that presumes the answer is a worse way to ask. The same is true of
`#239`, where the call is *where* the clamp goes: `TView::locate` looks like
the obvious place and is the wrong one, because `moveGrow` and `dragView`'s Esc
path both depend on it leaving the origin alone. The port works around both, in
`JsWindow::calcBounds` and `JsWindow::zoom`; the first is redundant once
upstream settles on a shape, and the second stays until `#239` lands.

[i230]: https://github.com/magiblot/tvision/issues/230
[i233]: https://github.com/magiblot/tvision/issues/233
[i234]: https://github.com/magiblot/tvision/issues/234
[i235]: https://github.com/magiblot/tvision/issues/235
[i239]: https://github.com/magiblot/tvision/issues/239
