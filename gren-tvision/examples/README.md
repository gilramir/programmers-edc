# Examples, and the API coverage they buy

Every example here is also a test (`../test/drive_<name>.py`). That is
deliberate: driving the real thing through a pty has caught every bug in this
project so far, and a demo nobody runs rots.

Build them all with `../build.sh`, run one with `../run.sh <name>`.

## Ported

| example | from | what it forced into the API |
|---|---|---|
| `hello` | `tvision/hello.cpp` | menus, status line, modal dialog as a `Cmd`, dialog result as a `Msg` |
| `mmenu` | `tvision/examples/mmenu` | a menu bar that changes at runtime, and menu bar entries that are commands rather than pull-downs |
| `entries` | *(ours)* | list boxes, `Time.every` behind a modal dialog, `WindowClosed`, mutable window titles |

## What mmenu changed

It was expected to be the cheap one. It turned out to be about swapping the
whole menu bar at runtime, which the API had documented as impossible — Turbo
Vision builds the menu bar in the application constructor, so that looked
settled. It is not: `TMenuView` keeps its menu in a member a subclass can
replace, which is exactly what Borland's `TMultiMenu` does.

So the menu bar and the status line moved out of the program's configuration
and into `Ui`, next to the windows. The C++ original needed a `TMenuBar`
subclass, an array of menus, a new broadcast command and a `handleEvent`
override; the Gren version is `menuBar = menuBarFor model.current`.

It also turned the menu bar into an `Array MenuItem` rather than an array of
pull-downs, because the original puts a plain command ("Next menu") directly on
the bar and the API could not say that.

Both were API improvements that no amount of staring at the binding would have
produced. Which is the argument for porting the rest.

## The C++ examples, triaged

`tvision/examples/` has eight entries. Two of them are not Turbo Vision
applications at all, and one of them is really eight applications.

| C++ example | verdict | what it needs |
|---|---|---|
| `hello` | **done** | — |
| `mmenu` | **done** | it was not about nested menus at all — see above |
| `palette` | cheap | per-view palette selection; the example is really an essay on how Turbo Vision palettes work |
| `tvdemo` | split it up | see below |
| `tvforms` | port the UI, skip the rest | check boxes and radio buttons (in the binding, not yet in the Gren types). Its other half is `.rsc` resource streaming — `opstream`/`ipstream` serialising views to disk — which has no Gren meaning |
| `tvdir` | needs a new widget | `TOutline`, a tree view, plus `TChDirDialog` |
| `tvedit` | a milestone of its own | `TEditor`/`TFileEditor`: a stateful text buffer with undo and clipboard. See the note below |
| `tvhc` | **no** | a command-line help *compiler*, not a TUI |
| `avscolor` | **no** | an AviSynth plugin |

### tvdemo is eight demos

| part | needs |
|---|---|
| ASCII chart | canvas + keys — **already ported to JS**, trivial to redo in Gren |
| calendar | canvas + keys |
| puzzle | canvas + keys |
| calculator | canvas + buttons |
| event viewer | canvas |
| mouse settings | check boxes, radio buttons, a scroll bar as a first-class view |
| colours | `TColorDialog` — wrap as a command that answers with the chosen palette |
| tile / cascade | `cmTile` and `cmCascade` are built-in command names already |
| help | `.hlp` files compiled by `tvhc`. Reimplementing help as ordinary windows from the model is a better use of the time than porting a binary format |

### The two genuinely hard ones

**`TEditor`.** A text editor is a stateful buffer with undo, clipboard and
search. Sending the whole buffer over a port on every keystroke is the Elm
answer and probably fine for real files, but the diff is per-view, not
per-character, so every keystroke would resend the document. The pragmatic
first move is an opaque editor view that owns its buffer, reports changes as
events, and takes `setText`/`getText` commands — less pure, and it can be
tightened later if the naive version turns out to be fast enough.

**The help system.** `THelpFile` reads a binary format produced by `tvhc`.
Porting the compiler buys nothing a Gren program wants; help screens are just
windows.

## After that

When the C++ examples run out, the coverage gaps left are roughly: scroll bars
as first-class views, `TOutline`, the standard file and directory dialogs,
per-view palettes, and validators on input lines. Then a Gren-only example that
does something the C++ examples never could — the obvious candidate is
something asynchronous, since that is the thing this binding has that Borland's
never did.
