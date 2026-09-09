# gren-tvision

Terminal user interfaces in [Gren][gren], drawn by [Turbo Vision][tv] — the
framework Borland shipped in 1990, ported to modern Unix and Windows by
[magiblot][tv], and driven here by the Elm architecture.

You write `view : Model -> Ui` and get windows, menus, dialogs, list boxes and
a mouse. Nothing you write calls into C++, and nothing blocks — including modal
dialogs, which take all the keyboard input without stopping your subscriptions.

[gren]: https://gren-lang.org
[tv]: https://github.com/magiblot/tvision

## Where the documentation is

| | |
|---|---|
| **API reference** | the doc comments in [`src/Tui.gren`](src/Tui.gren), published with the package. Every type and function is in one table there before the reference itself, and the reference says of each what Turbo Vision will do that you did not expect. |
| **[`doc/`](doc/index.md)** | the long-form documents. [Turbo Vision, from Gren](doc/widgets.md) is the guided tour — the programming model, the anatomy of the screen and every widget, for people who have never used Turbo Vision. [How a Gren program ends up on Turbo Vision](doc/architecture.md) is the technical half: the four layers, and the event loop that shaped them. [Driving a C or C++ library from Gren](doc/native.md) is the same problem in general, for a reader with some other library in mind. [The clipboard, from a terminal program](doc/clipboard.md) is the one every consumer eventually needs: why a copy reaches the rest of the machine sometimes and not others. |
| **This file** | what the thing is, how to install it, and a first program. |
| **[`examples/`](examples/)** | one runnable application per feature. Its README says what each one was ported for and what it forced into the API. |

## Installing

Three pieces, because a Gren package may not declare ports and cannot contain
JavaScript:

```sh
gren package install gilramir/gren-tvision   # the Gren API
npm install gren-tvision-runtime             # the runtime, and the binding it pulls in
```

The npm half brings `tvision-node`, the native addon. On a supported platform
that is a prebuilt binary; otherwise it compiles Turbo Vision from source and
needs a C++ compiler and ncurses headers.

## A first program

Your application declares the two ports — the package cannot — and hands them
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

then `Tui.defineProgram tui { init, update, subscriptions, view, onEvent }` — the
menu bar and the status line are part of what `view` returns, not configuration
beside it. The full version, with a picture of it running, is at the top of the
module docs; [`examples/hello`](examples/hello) is the next size up.

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
is the whole of it.

## Examples

Fifteen of them, each a port of a program from `tvision/examples/`, and each
chosen because it forced something into the API that staring at the binding did
not. [`examples/README.md`](examples/README.md) says what each one forced.

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
terminal and asserting on what was drawn, which is the only honest way to test
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
