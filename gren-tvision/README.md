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
| **API reference** | the doc comments in [`src/Tui.gren`](src/Tui.gren), published with the package. Everything you need while writing code, including the Turbo Vision behaviours that will surprise you. |
| **[`doc/`](doc/index.md)** | the two long-form documents. [Turbo Vision, from Gren](doc/widgets.md) is the guided tour — the programming model, the anatomy of the screen and every widget, for people who have never used Turbo Vision. [How a Gren program ends up on Turbo Vision](doc/architecture.md) is the technical half: the four layers, and the event loop that shaped them. |
| **This file** | what the thing is, how to install it, and a first program. |
| **[`examples/`](examples/)** | one runnable application per feature, each with a test. Its README is the plan of record for what gets ported next. |
| **[`../FINDINGS.md`](../FINDINGS.md)** | why the design is the way it is — the archaeology, not user documentation. |

## Installing

Three pieces, because a Gren package may not declare ports and cannot contain
JavaScript:

```sh
gren package install gilramir/gren-tvision   # the Gren API
npm install gren-tvision                     # the runtime, and the binding it pulls in
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

then `Tui.defineProgram tui { init, update, subscriptions, view, onEvent, menuBar, statusLine }`.
The full version is in the module docs and in [`examples/hello`](examples/hello).

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
rather write it yourself, `require('gren-tvision')(require('./main.js'))` is the
whole of it.

## Examples

```sh
./build.sh          # compile them all
./run.sh hello      # run one
./run.sh entries
./run.sh forms
./run.sh ascii
./run.sh calendar
./run.sh puzzle
./run.sh calc
./run.sh palette
./run.sh mouse
./run.sh dir        # takes a path
./run.sh demo
./run.sh viewer     # takes a path
```

Every one of them is a port of a `tvision/examples/` program, and each was
chosen because it forced something into the API. `examples/README.md` says what
each one forced.

They build against this working copy rather than a published version — each
example's `gren.json` lists `"../../src"` as a source directory, which is how
you develop against a Gren package without path dependencies.

## Tests

```sh
(cd tests && ./run.sh)                   # the package's own unit tests
python3 test/drive_hello.py              # an example, driven through a pty
```

The unit tests cover the pure parts. The pty drivers type at a real terminal
and assert on what was drawn, which is the only honest way to test a TUI — and
is what has caught most of the bugs in this project.
