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
| **2** | Something the size of `tvision/examples/`, on a non-blocking event pump | next |
| **3** | Gren on top, through ports | designed, not built |

See [FINDINGS.md](FINDINGS.md) for what we learned doing it, including the
things that were not what we expected.

## Layout

```
devbox.json        node 22, gren, cmake, ncurses (with its dev output)
m0-load-test/      milestone 0: a two-function addon that calls into ncursesw
tvision-node/      milestone 1: the actual binding
  src/tvnode.cc      the glue
  src/keys.h         "Alt-X" -> TVision key codes
  examples/hello.js  hello.cpp, with the C++ moved to JS
  test/drive.py      drives the TUI through a pty and asserts on the screen
build-tvision/     libtvision.a, built PIC (generated)
```

## Running it

Everything happens inside devbox — the addon must be compiled by the same
toolchain that will load it (see FINDINGS.md).

```sh
devbox run build    # libtvision.a (PIC) + the addon
devbox run test     # pty-driven checks, no terminal needed
devbox run hello    # the actual app, in your terminal
```

In `hello`: `Alt-G` or the Hello menu opens the greeting, `Tab` moves between
buttons, `Space` presses one (`Enter` does not — see FINDINGS), `Alt-X` quits.
