# gren-tvision

Terminal user interfaces in [Gren][gren], drawn by [Turbo Vision][tv] — the
framework Borland shipped in 1990, ported to modern Unix and Windows by
[magiblot][tv], and driven here by the Elm architecture (TEA)-style
node applications.

You write an ordinary TEA program — `init`, `update`,
`subscriptions` and `view : Model -> Ui` — and the C++ library owns the screen.
Your `view` describes the windows, menus, dialogs, list boxes and mouse handling
you want; Turbo Vision draws them, runs its own event loop over them, and sends
back what the user did as messages your `update` sees. Nothing you write calls
into C++, and nothing blocks — including modal dialogs, which take all the
keyboard input without stopping your subscriptions.

[gren]: https://gren-lang.org
[tv]: https://github.com/magiblot/tvision

## Where the documentation is

The long-form documents are in [`docs/`][docs]:

- [Turbo Vision, from Gren][widgets] — the guided tour: the programming model,
  the anatomy of the screen and every widget, for people who have never used
  Turbo Vision.
- [How a Gren program ends up on Turbo Vision][architecture] — the technical
  half: the four layers, and the event loop that shaped them.
- [Driving a C or C++ library from Gren][native] — the same problem in general,
  for a reader with some other library in mind.
- [The clipboard, from a terminal program][clipboard] — the one every consumer
  eventually needs: why a copy reaches the rest of the machine sometimes and
  not others.

And [`examples/`][examples] has one runnable application per feature. Its
README says what each one was ported for and what it forced into the API.

[docs]: https://github.com/gilramir/gren-tvision/blob/main/docs/index.md
[widgets]: https://github.com/gilramir/gren-tvision/blob/main/docs/widgets.md
[architecture]: https://github.com/gilramir/gren-tvision/blob/main/docs/architecture.md
[native]: https://github.com/gilramir/gren-tvision/blob/main/docs/native.md
[clipboard]: https://github.com/gilramir/gren-tvision/blob/main/docs/clipboard.md
[examples]: https://github.com/gilramir/gren-tvision/tree/main/examples

## Installing

Three pieces, because a Gren package may not declare ports and cannot contain
JavaScript:

```sh
gren package install gren-lang/node          # first -- see below
gren package install gilramir/gren-tvision   # the Gren API
npm install gren-tvision-runtime             # the runtime, and the binding it pulls in
```

**`gren-lang/node` goes first, and that is not a style preference.** This
package depends on it, so installing this one into an application that does not
already have it stops with a list of packages to "try adding to your gren.json"
-- and it stops *after* printing a tick beside the download, having written
nothing to `gren.json`, which reads like success. Install `gren-lang/node`
first and both steps go through.

You need it as a **direct** dependency in any case, whatever the order: your
own `Main` imports `Node` and `Init` by name, and a module a program imports
has to be one of that program's own direct dependencies rather than something
it inherits. Without it the first program below stops at `MODULE NOT FOUND` on
its own import list.

Your `gren.json` also needs `"platform": "node"`. `gren init` writes
`"browser"`, and a terminal program is not that.

The npm half brings `tvision-node`, the native addon. On **linux-x64** that is
a prebuilt binary -- built against glibc 2.28, so it runs on anything from
CentOS 7's era onward -- and nothing is compiled. Everywhere else npm compiles
Turbo Vision from source at install time, which takes about a minute and needs
node-gyp's usual C++ toolchain plus ncurses headers, and no cmake.

Node 20 or newer. The addon itself goes back to 18.17, but the Gren compiler
emits `Array.prototype.toSpliced`, which is 20.

## A first program

Your application declares the two ports — this package cannot — and hands them
over:

```gren
port module Main exposing (main)

import Json.Decode as Decode
import Json.Encode as Encode
import Node
import Tui exposing (Event(..), View(..))

port tuiOut : Encode.Value -> Cmd msg
port tuiIn : (Decode.Value -> msg) -> Sub msg

tui : Tui.Ports Msg
tui =
    { toJs = tuiOut, fromJs = tuiIn }
```

then `Tui.defineProgram tui { init, update, subscriptions, view, onEvent }`. The
full version, with a picture of it running, is at the top of the module docs;
[`examples/hello`][hello] is the next size up.

[hello]: https://github.com/gilramir/gren-tvision/tree/main/examples/hello

An application with a command line wants `Tui.defineProgramOrExit` instead,
whose `init` answers `Tui.Start model` or `Tui.Exit`. `Exit` sends no render,
and since the first render is what starts Turbo Vision, a `--help` prints and
the terminal is left exactly as it was found. Everything else about the two is
the same.

Build and run:

```sh
gren make Main --output=main.js
gren-tui main.js
```

`gren-tui` comes from the npm package. It is a three-line script; if you would
rather write it yourself, `require('gren-tvision-runtime')(require('./main.js'))`
is the whole of it. An installed application usually should: it gets its own
name on the command line, finds `main.js` next to itself rather than in the
working directory, and can subscribe ports of its own to the app `run()` hands
back.

## Examples

Fifteen of them, each a port of a program from the C++ code in  `tvision/examples/`, and each
chosen because it forced something into the API that staring at the binding did
not. [`examples/README.md`][examples-readme] says what each one forced.

[examples-readme]: https://github.com/gilramir/gren-tvision/blob/main/examples/README.md

```sh
./build.sh          # compile them all
./run.sh hello      # run one
./run.sh mmenu
./run.sh entries
./run.sh forms
./run.sh ascii
./run.sh calendar
./run.sh puzzle
./run.sh calc
./run.sh palette
./run.sh mouse
./run.sh watch
./run.sh dir        # takes a path
./run.sh edit       # takes a path
./run.sh viewer     # takes a path
./run.sh demo
```

They build against this working copy rather than a published version — each
example's `gren.json` lists `"../../src"` as a source directory, which is how
you develop against a Gren package without path dependencies.

## Tests

```sh
(cd tests && ./run.sh)                   # the package's own unit tests
```

The unit tests cover the pure parts and need nothing but `gren`.

`test/drive_*.py` is the other half: one driver per example, typing at a real
terminal and asserting on what was drawn, which is the best way to test
a TUI and is what has caught most of the bugs in this project. They import a
pty harness that lives in the repository this package is developed in, so they
run there and not from a clone of this one.

## Where this package is developed

The master copy lives in [gilramir/programmers-edc][mono], alongside the npm
runtime, the native binding and an application built on all three. This
repository is an export of one directory of it, published because a Gren
package has to be a repository of its own. Issues and changes belong upstream;
nothing is committed here by hand.

`FINDINGS.md` there is the running record of what turned out to be true —
archaeology rather than user documentation, but it is where the answer to "why
is it like that" actually is.

[mono]: https://github.com/gilramir/programmers-edc
