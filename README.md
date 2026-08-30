# tvision-experiment

Binding [magiblot/tvision](https://github.com/magiblot/tvision) — a modern port of
Borland's Turbo Vision — into Node, and eventually into
[Gren](https://gren-lang.org).

The `tvision/` checkout is not part of this repo (it is gitignored); clone it in
next to these directories.

## Milestones

| | | |
|---|---|---|
| **0** | Does a Node addon built here load, and can it reach a system library? | done |
| **1** | `hello.cpp` as a Node app, with the menus and dialog described in JS | done |
| **2** | A larger demo on a non-blocking event pump, with addressable views | done |
| **2.5** | Modal dialogs that do not stop Node, and more ported demos | done |
| **3** | Gren on top, through ports | done |

See [FINDINGS.md](FINDINGS.md) for what we learned doing it, including the
things that were not what we expected.

## Layout

```
devbox.json        node 22, gren, cmake, ncurses (with its dev output)
m0-load-test/      milestone 0: a two-function addon that calls into ncursesw
tvision-node/      the binding
  src/tvnode.h       shared declarations, widgets, the id registry
  src/keys.h         "Alt-X" -> TVision key codes
  src/app.cc         application, event pump, module entry
  src/views.cc       widgets, the id registry, mutation
  examples/hello.js  hello.cpp, with the C++ moved to JS
  examples/demo.js   a clock and a directory browser driven by Node
  examples/ascii.js  tvdemo's ASCII chart: a view painted from JavaScript
  examples/form.js   tvforms/mmenu: clusters, nested submenus, command enabling
  test/harness.py    pty driver + a small terminal emulator
  test/drive*.py     type at the app, assert on what it drew
  test/asan.sh       run node with AddressSanitizer preloaded
gren-tvision/      the Gren package: gilramir/gren-tvision
  src/Tui.gren       Ui types, encoders, the program wrapper. Pure Gren.
  examples/          one directory per example, each its own application
  test/              a pty driver per example
gren-tvision-runtime/  the npm half: the diff layer + the `gren-tui` bin
build-tvision/     libtvision.a, built PIC (generated)
```

The split is forced: **Gren packages may not declare ports**, so the package
can describe a UI but cannot reach a terminal. The application declares the two
ports and hands them over; the npm runtime takes the description off the port
and drives the binding. See FINDINGS.

## Running it

Everything happens inside devbox — the addon must be compiled by the same
toolchain that will load it (see FINDINGS.md).

```sh
devbox run build    # libtvision.a (PIC) + the addon
devbox run test     # pty-driven checks, no terminal needed
devbox run test:asan  # the same, plus memory checks under AddressSanitizer
devbox run hello    # each of these runs one example in your terminal
devbox run demo
devbox run ascii
devbox run form
devbox run gren           # the entries example, in Gren
devbox run gren -- hello  # or any other example
```

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
`Clear` are greyed out until there is something to list.

In `gren`: `Alt-A` adds an entry through a modal dialog, the clock is a
`Time.every` subscription, and closing the entries window tells the Gren model
so it stays closed until `Alt-L` puts it back.

[`gren-tvision/examples/README.md`](gren-tvision/examples/README.md) is the plan
of record for what gets ported next and what API each one needs.

`Enter` does not press buttons, select list items, or tick check boxes in Turbo
Vision; `Space` does. See FINDINGS.
