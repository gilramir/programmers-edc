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
| **3** | Gren on top, through ports | designed, not built |

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
  examples/hello.js  hello.cpp, with the C++ moved to JS (blocking)
  examples/demo.js   a clock and a directory browser driven by Node (pumped)
  test/harness.py    pty driver + a small terminal emulator
  test/drive*.py     type at the app, assert on what it drew
  test/asan.sh       run node with AddressSanitizer preloaded
build-tvision/     libtvision.a, built PIC (generated)
```

## Running it

Everything happens inside devbox — the addon must be compiled by the same
toolchain that will load it (see FINDINGS.md).

```sh
devbox run build    # libtvision.a (PIC) + the addon
devbox run test     # pty-driven checks, no terminal needed
devbox run test:asan  # the same, plus memory checks under AddressSanitizer
devbox run hello    # milestone 1, in your terminal
devbox run demo     # milestone 2, in your terminal
```

In `hello`: `Alt-G` or the Hello menu opens the greeting, `Tab` moves between
buttons, `Space` presses one, `Alt-X` quits.

In `demo`: `Alt-C` opens a clock painted by `setInterval`, `Alt-D` a directory
listing produced by `await fs.readdir()`; `Space` on an entry stats it
asynchronously, `../` walks up. `Alt-G` opens a *modal* dialog — watch the
clock stop dead while it is up, then start again when you dismiss it. That
freeze is the honest limitation milestone 3 has to design around.

`Enter` does not press buttons or select list items in Turbo Vision; `Space`
does. See FINDINGS.
