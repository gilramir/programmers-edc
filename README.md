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
| **4** | Every C++ example ported, one at a time, each forcing an API change | done except `tvedit` |

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
                     hello, mmenu, entries, forms, ascii, calendar, puzzle,
                     calc, palette, mouse, dir, demo, viewer -- and a README
                     that is the plan of record for what gets ported next
  test/              a pty driver per example
gren-tvision-runtime/  the npm half: the diff layer + the `gren-tui` bin
  diff.js            one UI description -> calls on the binding (unit tested)
  test/              node:test, against a fake binding
tools/             cross-language consistency checks
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
devbox run check    # fast: consistency, docs, unit tests. No terminal, ~5s
devbox run test     # the above plus the pty drivers
devbox run test:asan  # the pty drivers under AddressSanitizer
devbox run hello    # each of these runs one example in your terminal
devbox run demo
devbox run ascii
devbox run form
devbox run gren           # the entries example, in Gren
devbox run gren -- hello  # or any other example
devbox run gren -- forms
devbox run gren -- ascii
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

In `gren -- forms` (tvision's `tvforms`): arrow keys move through a sorted
collection of records and the window on the right follows, because the model is
told where the highlight is. `F3` edits the highlighted record in a form with
labelled fields, check boxes and radio buttons; `F2` adds one; `F8` deletes one,
and with none left both `F3` and its menu entry go grey. Saving a renamed record
re-sorts the list and the highlight follows it there.

In `gren -- ascii` (tvdemo's chart): the same chart as `devbox run ascii`, but
the eight rows of code page 437 come out of a Gren array and the selected cell
is `cursor = Just { x, y }` on the canvas. Arrows and Home/End move it, any
printable key jumps to that character, and a click lands where you clicked.

The rest of the Gren examples are every remaining C++ one:

| | |
|---|---|
| `gren -- calendar` | tvdemo's calendar. Up/Down change the month; today is the one thing on the canvas painted in a colour of its own |
| `gren -- puzzle` | tvdemo's sliding puzzle. `--seed=` and `--scramble=` make the board a pure function of two numbers, which is how the test wins the game |
| `gren -- calc` | tvdemo's calculator. Type at it or click the keys — the keypad can be pressed but never holds the caret |
| `gren -- palette` | tvision's palette example, whose entire subject the port removes |
| `gren -- mouse` | tvdemo's mouse dialog. The scroll bar sets the double-click delay; double-click the strip to feel where the boundary is |
| `gren -- dir` | tvdir. A directory tree with no tree widget: the rows are a fold over the model |
| `gren -- demo` | tvdemo's shell. `Windows ▸ Tile` and `Cascade` are Turbo Vision's; the event viewer lists what crosses the port |
| `gren -- viewer` | tvdemo's file viewer, with both scroll bars. Takes a path |

[`gren-tvision/examples/README.md`](gren-tvision/examples/README.md) is the plan
of record: what each port forced into the API, and what is left.

`Enter` does not press buttons, select list items, or tick check boxes in Turbo
Vision; `Space` does. See FINDINGS.
