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
| `forms` | `tvision/examples/tvforms` | check boxes, radio buttons, labels, and a list box highlight the model can both read and move |
| `ascii` | `tvision/examples/tvdemo` (ascii.cpp) | the canvas, from Gren: a view the model paints itself, and a cursor to select with |
| `calendar` | `tvision/examples/tvdemo` (calendar.cpp) | colour on a canvas, as spans; and today as a field, because `Time.now` is a task |
| `puzzle` | `tvision/examples/tvdemo` (puzzle.cpp) | nothing in the API -- but the random seed had to move into the model, which is what let a test win the game |
| `calc` | `tvision/examples/tvdemo` (calc.cpp) | `takesFocus` on a button: a keypad that can be pressed but never holds the caret |
| `palette` | `tvision/examples/palette` | nothing -- it is the example whose entire subject the port removes, and the write-up says what that costs |
| `mouse` | `tvision/examples/tvdemo` (mousedlg.cpp) | the scroll bar as a view of its own, `isDouble` on a click, `setDoubleClickDelay`, and `takesFocus` on a canvas |
| `dir` | `tvision/examples/tvdir` | no widget at all — but it found a real bug in the diff, moved a list box's scroll bar, and is the first example to use the file system |
| `demo` | `tvision/examples/tvdemo` (the shell) | real windows: zoom, resize, tile and cascade, which every window had silently been unable to do |
| `viewer` | `tvision/examples/tvdemo` (fileview.cpp) | nothing — `TScroller` went the way of `TOutline`; but it is the first horizontal scroll bar doing its own job |

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

## What tvforms changed

The widgets were the expected part: check boxes, radio buttons and labels were
already in the binding and only had to reach `Ui`. Two things were not
expected.

**A label makes the order of `views` mean something.** A label names another
view by id, and the binding has to have built that view already, so a control
has to come before the label that names it. Until this port the order of the
array decided one thing only — who gets focus when the window opens.

**The model could watch the highlight but not move it.** `listdlg.cpp` reads
`list->focused` at the moment Edit is pressed. Gren cannot: it has no way to
ask, and the only thing a list box reported was `Selected`, which fires on
`Space` and not on the arrow keys. Edit would have opened whatever record was
last committed rather than the one the user is looking at.

The answer runs in both directions, and both halves are load-bearing:

  - a `Focused` event as the highlight moves, so the model can act on it;
  - `focused` as a field on `ListBox`, so the model can put the highlight
    somewhere — which matters because the collection is *sorted*. Rename a
    record and it moves; rebuilding a list box drops the highlight back to row
    zero, and the model needs the last word about where it lands.

Neither is visible when a list box is a menu of choices, which is all `entries`
asks of one. Porting an example that treats a list as a cursor over a
collection is what exposed it.

## What the ASCII chart changed

The canvas was in the API from the start and no Gren example used one, which
turned out to be hiding something: the chart shows which character is selected
with the terminal's own cursor, and there was no way to say where it should
go.

So a canvas takes `cursor : Maybe { x : Int, y : Int }`, patched in place like
its lines. What made it more than a one-line addition is *when* it can be
applied. Turbo Vision moves the hardware cursor when a view is focused, and a
view being built is not yet inserted, let alone focused — so setting the cursor
during construction leaves the position on the C++ object and never on the
terminal. It has to be applied after the window is on the desktop, which is a
second pass in the binding rather than part of building the views.

The test is worth a look for a different reason: a canvas has no highlight and
no selection bar, so the only evidence of the model on screen is where the
cursor is. `test/drive_ascii.py` asserts on that directly, which the pty
harness can now report.

## What the calendar and the puzzle changed

Both needed the same thing, and it is the first API change since `ascii` that
the binding had to make in C++: **a canvas line is an array of coloured spans
rather than a string.**

    type alias Span =
        { text : String, fg : Maybe Hue, bg : Maybe Hue }

The two halves are separate because naming one is the common case -- today on a
calendar is a foreground on whatever the window is already using, and a
highlight that had to name its own background would stop matching the program
the moment anyone changed the theme. `Tui.line` makes the shape every canvas
had before colour existed, so `ascii` changed by one word.

`FINDINGS.md` has the rest of it, including why a span with no colour has to
encode to exactly what a string used to.

Beyond the API, each of these ports made the same point from a different
direction: **state the C++ hides in a constructor has to become a field, and
the field is worth more than the hiding was.**

`TCalendarView`'s constructor calls `localtime()`, so the view *is* today and
cannot be asked about any other month. In Gren `Time.now` is a task, so today
becomes data that arrives after the first render -- and `drive_calendar.py` can
walk a year back and check that today stops being highlighted when you leave
its month.

`TPuzzleView`'s constructor calls `srand(time(0))` and shuffles five hundred
times. In Gren the generator has to live in the model, so the board is a pure
function of a seed and a depth; `--seed=` and `--scramble=` follow for free,
and `drive_puzzle.py` reproduces the shuffle in Python, searches for the answer
and **wins the game** -- which is not a test the original could have.

## What the calculator changed

`TCalculator` makes twenty buttons and clears `ofSelectable` on every one of
them, with no comment. The reason is the window's other child: `TCalcDisplay`
reads the keyboard, and a keypad whose buttons could take focus would eat every
digit typed at it -- `7` would move the caret to the button captioned 7.

So `Button` grew `takesFocus`. It is the first field added here for a reason
that is invisible until a window has two kinds of input in it, and it is not
calculator-shaped: a toolbar wants the same thing, and so does anything with a
canvas doing the reading.

## What the palette example changed

Nothing, and that is the point worth writing down.

`palette.cpp` is an essay on Turbo Vision's three levels of palette
indirection. A `Span` names its colour outright, so the essay collapses into a
six-row table of what those three levels resolve to, and the original's last
line -- the one that "bypasses the palettes" -- becomes indistinguishable from
the six above it.

The port says what that costs rather than claiming a win. The indirection
exists so one edit restyles every view in the program; naming the colour gives
that up. What comes back is that the colour is in the model, next to the branch
that decides what to draw -- which is how the calendar marks today and the
puzzle shows a tile out of place, and neither of those is a question a palette
can answer.

## What the mouse dialog changed

Three things, and the third was a surprise.

**A scroll bar the model owns.** A list box has always made one for itself, but
nothing could put one in a window and ask what it says. `ScrollBar` is a view
now, reporting a `Scrolled` event however it moves. Which way it points is not
a field: `TScrollBar` decides from its own rectangle, and a second way to say
the same thing would only be a way for the two to disagree.

**A click that knows it is the second one.** `TClickTester` reacts to
`meDoubleClick`, so `Clicked` grew `isDouble`, and `setDoubleClickDelay` is the
command that makes the dialog mean anything.

**`takesFocus` was not a button thing.** The tester strip is a canvas, a canvas
is selectable, and a selected canvas consumes every key it is given -- `Tab`
included -- so the scroll bar underneath it could not be reached from the
keyboard at all. `Canvas` has `takesFocus` too now, and it earns more there
than on a button.

One thing worth knowing before writing anything else with a scroll bar in it:
**magiblot's does not page on a click.** Borland's steps by `pgStep` when you
click past the thumb; this one takes the thumb to the pointer. `pageStep` is
reached only from the keyboard, and on a horizontal bar that is `Ctrl-Left` and
`Ctrl-Right`.

## What tvdir changed

This entry said "needs a new widget: `TOutline`". It does not, and that was
settled in about ten minutes.

A tree view is a widget in C++ because it has to be: `TOutlineViewer` owns a
`TNode` chain, works out which rows are visible, draws the box graphics, and
keeps an index into a list only it can compute. A model that re-renders owns
the structure already — the tree is a `type Node` and the visible rows are a
fold over it, which a plain `ListBox` then displays with its scrolling and its
highlight. `TScroller` went the same way, and for the same reason: what a
scroller does is decide which slice to draw, and the model knows.

Same shape as `mmenu`, in the other direction. There the documentation said
something was impossible and it was not; here it said something was needed and
it was not.

**It found a real bug.** Expanding a branch collapsed the whole tree.
`setItems` puts a list box's highlight back on row zero, so `diff.js` re-sent
`focused` afterwards — but only when `focused` had *changed*, and expanding a
branch changes the items and leaves the highlight where it is. The list sat on
row zero, reported that as a move, and the model believed it. `focused` is now
re-sent whenever the items changed, and `setItems` no longer reports the
intermediate zero it has to pass through. `FINDINGS.md` has the long version;
the short one is that the tvforms port wrote this hazard down and it took a
tree to produce a case that hit it.

**And it moved a scroll bar.** `TWindow::standardScrollBar` puts a list's bar
on the window frame, which is right for a window that is a list and nothing
else and wrong for two panes side by side. A list box's scroll bar now occupies
the column immediately to the right of the list, so leave one.

There is no "Please Wait" window, either. The original scans the whole drive in
a constructor and has to put one up; `FileSystem.listDirectory` is a task, a
directory is read when it is opened, and nothing blocks. It is also the first
example to use the file system, which is what `init` being a full `Init.Task`
was for.

## What finishing tvdemo changed

**Every window was a dialog.** `JsWindow` derives from `TDialog`, which sets
`growMode = 0` and `flags = wfMove | wfClose` — so no window this binding made
could be zoomed, resized or grown with the terminal, and `ofTileable` (set by
exactly one class in all of Turbo Vision) was never set at all, so `Tile` and
`Cascade` had nothing to arrange. A non-modal window now puts all four back.

Their child views still do not grow with the window, because their rectangles
are what the model said they are. That is a known gap rather than an oversight:
growing a view would put its size somewhere the model cannot see.

**`"tile"` and `"cascade"` were documented and not implemented.** Both have
been on `Tui`'s built-in list since the first commit and neither was interned,
so they arrived in the model as ordinary events while the desktop sat still.
They are the two `TApplication` handles; everything else on that list is
`TProgram`'s. `check_consistency.py` now compares the documented list against
the table in the binding, because an unknown name is a *valid* command and its
only symptom is that nothing happens.

**The first click is spent twice.** The docs said an inactive window spends the
first click being activated. `TView` applies the same rule one level down: a
control that can take focus and has not got it spends the first click taking
it. A scroll bar beside a focused canvas therefore needs two clicks, which
looks exactly like a scroll bar that has stopped working.

The other two findings are about where the line is. A Gren event viewer sees
what crossed the port and nothing Turbo Vision handled itself — which is the
bargain, and the viewer window is a fair way to show it. And the clock is a
status item because `TClockView` is a view on the *application* and `Ui` has
nowhere to put one; it works, at the cost of rebuilding the status line every
second, which is precisely why Borland made it a view.

## The C++ examples, triaged

`tvision/examples/` has eight entries. Two of them are not Turbo Vision
applications at all, and one of them is really eight applications.

| C++ example | verdict | what it needs |
|---|---|---|
| `hello` | **done** | — |
| `mmenu` | **done** | it was not about nested menus at all — see above |
| `palette` | **done** | `examples/palette`; the essay it is written to explain has no Gren equivalent — see above |
| `tvdemo` | **done** except the help system | `examples/demo` is its shell; the demos inside it are `ascii`, `calendar`, `puzzle`, `calc`, `mouse` and `viewer` |
| `tvforms` | **done** (the UI half) | see above. Its other half is `.rsc` resource streaming — `opstream`/`ipstream` serialising views to disk — which has no Gren meaning |
| `tvdir` | **done** | `examples/dir` — and it turned out to need no new widget at all; see above |
| `tvedit` | a milestone of its own | `TEditor`/`TFileEditor`: a stateful text buffer with undo and clipboard. See the note below |
| `tvhc` | **no** | a command-line help *compiler*, not a TUI |
| `avscolor` | **no** | an AviSynth plugin |

### tvdemo is eight demos

| part | needs |
|---|---|
| ASCII chart | **done** — `examples/ascii`; it wanted a cursor, see above |
| calendar | **done** — `examples/calendar`; it wanted colour, see above |
| puzzle | **done** — `examples/puzzle` |
| calculator | **done** — `examples/calc`; it wanted `takesFocus`, see above |
| event viewer | **done** — part of `examples/demo`; it sees what crosses the port and nothing else |
| mouse settings | **done** — `examples/mouse`; it wanted the scroll bar, see above |
| file viewer | **done** — `examples/viewer`; `TScroller` went the way of `TOutline` |
| colours | **done** — part of `examples/demo`, as five radio buttons. A colour dialog is a form, and what it sets is a field |
| tile / cascade | **done** — part of `examples/demo`. They were built-in command *names* and not built-in commands; see above |
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

## Where that leaves it

Every C++ example is ported except `tvedit`, and everything in `tvdemo` except
the help system. `tvhc` and `avscolor` are not Turbo Vision applications.

`tvedit` is the one left, and it is a milestone rather than a port — see the
note above. Nothing else in the list is blocked on it.

The coverage gaps left are: the standard file and directory dialogs,
validators on input lines, a view on the application rather than the desktop
(`TClockView`'s slot), and child views that grow with their window.

One gap is worth naming on its own, because `forms` walked right up to it: **a
cluster or an input line in a plain window holds state the model never sees.**
Values are collected when a *dialog* is answered and at no other moment, so a
check box ticked in an ordinary window is invisible until something asks. Turbo
Vision programs are shaped that way — data entry happens in modal forms — so it
was not in the way here, but it is the same hole the `Focused` event just
filled for list boxes, and clusters will want the same treatment.

Then a Gren-only example that does something the C++ examples never could — the
obvious candidate is something asynchronous, since that is the thing this
binding has that Borland's never did.
