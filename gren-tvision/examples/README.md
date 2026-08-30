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
| `watch` | *(ours)* | not a port: a subscription from outside the program, several children at once, and a run that can be killed. It found a name the binding was silently swallowing |

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

## What the watcher changed

`watch` is the only example here that is not a port, and it is the one that
says what the difference is. Point it at a directory and some commands and it
runs them when anything in there changes:

    ../run.sh watch src 'npm test' 'npm run lint'

Three things in it have no Turbo Vision counterpart at all, and the first is
the whole argument.

**The outside world can send this program a message.** `TProgram`'s loop is
`getEvent`, and `getEvent` reads a keyboard and a mouse. Nothing in
`tvision/examples/` reacts to anything else, because there is nothing else to
react to: a Borland-era program that wanted to know something had to go and ask
in a call that returned when it had the answer, which is exactly why `tvdir`
scans in a constructor behind a "Please Wait" window. Here
`FileSystem.watchRecursive` is an ordinary `Sub` and inotify events arrive next
to the keyboard's on equal terms. `test/drive_watch.py` proves it the only way
that means anything: **the test writes a file and the application does
something.**

**Several children run at once, and one of them can be taken back.**
`ChildProcess.spawn` hands the model a `Process.Id`; `Process.kill` on it kills
the child. So a change arriving mid-run kills that run and starts again, which
is the difference between a watcher and a demo. It is also the same move this
API has made thirteen times already — state C++ keeps somewhere the model
cannot see becomes a field — applied to a thing Turbo Vision never had one of.

**The API did not have to change, and one thing in it did.** No new view type,
no new event: three windows, three canvases, three scroll bars. What the
example found instead was a hole in the documentation with teeth in it.

### The built-in command names are a reserved vocabulary

`Tui`'s docs listed nine command names Turbo Vision handles itself. The binding
interns fourteen. The five that were missing are `"help"`, `"ok"`, `"cancel"`,
`"yes"` and `"no"` — and a watcher wants a command called `cancel`.

The symptom is the same silence `"tile"` and `"cascade"` produced, arriving
from the opposite direction. There it was a name the docs promised and the
binding did not intern, so it reached the model as an ordinary event and the
desktop sat still. Here it is a name the binding *does* intern and the docs
never mentioned, so Turbo Vision takes it and the model is never told: the menu
entry draws, `Alt-C` works, `cmCancel` outside a dialog does nothing, and there
is no error anywhere to say why.

`tools/check_consistency.py` compared those two lists in one direction only.
It now compares both, which is the half that would have caught this one.

### Two things a watcher has to do, which are not obvious until it does not

**Editors do not save a file once.** A save is a write, a rename and a chmod,
so inotify reports a burst and an undebounced watcher runs everything three or
four times per keystroke. A generation counter fixes it: a change bumps it and
schedules a `Process.sleep`, and the sleep starts a run only if its generation
is still current. The test writes five files in a row and checks that exactly
one run happened and all five were seen.

**A killed child goes on talking.** Kill is not instant and the pipe still has
bytes in it, so output from an abandoned run arrives after its replacement has
started. Every job carries the number of the run its child belongs to and drops
anything tagged with another. `dir` has the same hazard in one comment — two
listings in flight, and the late one must not overwrite the recent one — and
this is that shape at full size.

**Every window this binding makes is grey, so half the palette is unusable in
it.** `JsWindow` derives from `TDialog`, which means a window's background is
the light grey a dialog has rather than Turbo Vision's blue — and the eight
*bright* hues are exactly the ones a light background eats. The first version
of this example painted a passing job `LightGreen`, a failing one `LightRed`
and a running one `LightGray`, which is respectively hard to read, hard to
read, and invisible. They are `Green`, `Red`, `DarkGray` and — for a job with
nothing to say — no colour at all, which is `Tui.plain` and stays right if the
palette ever moves. `drive_watch.py` asserts on the two colour codes, because
nothing else on screen would notice.

And one that is about the API rather than about watching: **a scroll bar the
model moves and the user moves needs a rule for who wins.** `mouse` had a bar
the user moves; `dir` had one the model moves; this is the first with both.
The rule is the one every log viewer arrives at — follow the bottom until the
user leaves it, follow again when they come back — and it lives in the model,
which is the only place that knows both numbers.

### What it cost the test suite

Under `test:asan` the sanitizer is preloaded with `LD_PRELOAD` and children
inherit it, so a spawned command runs instrumented. That is mostly free, and
once it is not: node's `shell: true` runs `/bin/sh` by name, the distribution's
`/bin/sh` is linked against the distribution's glibc, and the preloaded
`libasan.so` comes from the nix store and brings nix's glibc with it. Every
child then dies before `main`. The example takes `--shell=`, the test passes
`--shell=bash` under ASAN, and a shell off `PATH` is the toolchain's own.
Nothing about this reaches a user; it takes an `LD_PRELOAD` from one libc and a
program from another.

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
| `tvdir` | **done**, less its Change Dir dialog | `examples/dir` — and it turned out to need no new widget at all; see above. `TChDirDialog` is a coverage gap, listed at the end |
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

Two things learned since this paragraph was written narrow it considerably;
they are at the end, under **And what is not a gap**.

**The help system.** `THelpFile` reads a binary format produced by `tvhc`.
Porting the compiler buys nothing a Gren program wants; help screens are just
windows.

## Where that leaves it

Every C++ example is ported except `tvedit`, and everything in `tvdemo` except
the help system. `tvhc` and `avscolor` are not Turbo Vision applications.

`tvedit` is the one left, and it is a milestone rather than a port — see the
note above. Nothing else in the list is blocked on it.

### The widget set is complete; what is left is not widgets

Every `TView` subclass in `tvision/include/tvision/*.h` has been walked against
the four layers, and the stock controls are all there: `TStaticText`, `TLabel`,
`TButton`, `TInputLine`, `TCluster` with `TCheckBoxes` and `TRadioButtons`,
`TListViewer` with `TListBox`, `TScrollBar`, `TMenuBar`/`TMenuBox`/`TSubMenu`,
`TStatusLine`, `TWindow`/`TDialog`/`TFrame`, and the
`TGroup`/`TProgram`/`TApplication`/`TDeskTop` scaffolding underneath. `Canvas`
is the escape hatch for anything the set does not have.

Five more were left out on purpose and each has its reason written up above:
`TScroller` (`viewer`), `TOutlineViewer` and `TOutline` (`dir`), the
`TCollection` family and `opstream` resource streaming (`tvforms`), the three
levels of palette indirection (`palette`), and `TTerminal`/`TTextDevice` —
which is the C++ scrolling output view, and which `watch` replaced with a
canvas and a model for the same reason `TScroller` went.

**And the mouse wheel already works**, which is worth knowing because nothing
here does anything to make it. `TScrollBar` puts `evMouseWheel` in its own
event mask, so a wheel turn scrolls the bar and arrives in the model as an
ordinary `Scrolled`. One caveat inherited from Turbo Vision: `positionalEvents`
excludes `evMouseWheel` (`views.h`), so a wheel event goes to whatever has
*focus* rather than to whatever is under the pointer.

### The coverage gaps left

Ten, in the order I would attack them. Each says what it would take, because
"not done", "not decided" and "not needed" are three different problems.

Four of them are now reported by `tools/check_consistency.py` on every run,
which is where the fourth came from: the port is the only way into the binding,
so an exported function no runtime call site reaches is a capability no Gren
program can use. It names `focus`, `screenSize`, `messageBox` and `getValue`.
When a gap below is closed, its note disappears on its own.

The first two are one design with two symptoms, and they are the only gaps on
this list that touch *every* program written with the API rather than one kind
of program.

**1. The model does not know how big the terminal is.** Every example here
hardcodes 80x25 — `dir` stops its window at column 78, `watch` divides an
assumed 23-row desktop by the number of jobs. Run any of them in a 120x40
terminal and Turbo Vision uses the whole screen while the windows sit in an
80x23 box in the corner with fifteen rows of empty desktop below them.

The binding has had `screenSize()` since milestone 2 and Gren cannot call it:
the Gren-to-runtime protocol is five messages (`render`, `dialog`,
`setEnabled`, `doubleClickDelay`, `quit`) and there is no sixth. Nor is there a
resize event, so a terminal that changes size mid-run is never mentioned to the
model either.

What it would take is a decision rather than plumbing. The size could arrive in
`init` and again as an event, which is the smallest change and makes every
`view` function do arithmetic. Or rectangles could stop being absolute — see
the next one.

**2. Child views do not grow with their window.** A window can be zoomed,
resized and tiled, and the views inside it keep the rectangles the model gave
them, so a tiled window shows a clipped canvas rather than a stretched one.

This has been called deliberate, on the grounds that growing a view would put
its size somewhere the model cannot see. That reasoning is sound and the
conclusion is probably wrong, because it is the same problem as the one above:
both are asking the model to know a number that Turbo Vision owns. The
alternative worth considering is that a `Rect` stops being the only way to
place a view — a declarative `fill`/`fixed` layout describes intent rather than
coordinates, the runtime resolves it against whatever size the window actually
is, and nobody has to be told a number. That would close both gaps at once and
is a prerequisite for anything editor-shaped.

**3. The model cannot move focus.** `tv.focus(id)` is in the binding and, like
`screenSize`, has no message to carry it. So a program can decide who gets
focus when a window opens — the order of `views` does that — and can never
change its mind: no "put the caret in the field the error was in", no "raise
that window". `ListBox`'s `focused` field is a different thing; it moves a
highlight, not the caret. This one is plumbing rather than design, and it is
the cheapest item on the list.

**4. The standard file and directory dialogs.** `TFileDialog` and
`TChDirDialog` (`stddlg.h`) are how a Turbo Vision program asks for a path, and
there is no way to ask for one here — which is why `examples/dir` and
`examples/viewer` both take theirs on the command line, and why `tvdir`'s
Change Dir half is the one part of it not ported.

The interesting thing is that neither looks like a class worth wrapping.
`TFileDialog` *is* a `TDialog` full of stock controls — an input line, two
buttons, a history — around a `TFileList`, which is a `TSortedListBox` over
`FileSystem.listDirectory`. Following `TOutline` and `TScroller`, the answer is
probably a dialog the model builds and a helper that produces its `views`,
shipped in the package rather than in the binding. That is a design decision
nobody has made yet, not a missing widget. It wants (6) first, for the history.

**5. A message box.** `tv.messageBox()` exists in the JavaScript binding, built
there rather than in C++ because Turbo Vision's own `messageBox()` calls
`execView` — the nested loop milestone 2.5 removed. Gren cannot reach it. A
message box *is* a dialog, so nothing is impossible, but every program will
write the same fifteen lines. The same package-helper shape as (4), and small
enough to be the thing that establishes it.

**6. `THistory` — the drop-down beside an input line.** `THistory`,
`THistoryViewer` and `THistoryWindow` are the stock control that remembers what
was typed into a field before, and it is in every `TFileDialog`. It is a real
widget with real state, and the state is a list of strings the model would
rather own — which makes it the same question `TOutline` answered, one size
down: is this a widget to wrap, or a `ListBox` in a small window plus a field
on the model?

**7. `TMenuPopup` — context menus.** Right-click menus. The menu machinery is
all there; what is missing is the way to open one at a point in response to a
click. `TEditor::initContextMenu` returns one, so this is a soft prerequisite
for the editor.

**8. Validators on input lines, and clusters that hold unseen state.** Two
faces of one hole, which is why they are together now.

`TValidator` and its five subclasses vet a field *as it is typed* —
`TFilterValidator` rejects a keystroke outright, `TRangeValidator` and
`TPXPictureValidator` check on the way out. The model cannot do the first,
because it is never told about a keystroke that reached an input line.

And `forms` walked up to the other side: values are collected when a *dialog*
is answered and at no other moment, so a check box ticked in an ordinary window
is invisible until something asks. Turbo Vision programs are shaped that way —
data entry happens in modal forms — so it has not been in the way, but it is
the same hole the `Focused` event filled for list boxes. Fill it once, in both
directions, and validation becomes something the model does with the value it
now has.

**The read half of that is smaller than it looks, and this paragraph used to
have it wrong.** `tv.getValue(id)` already returns the text of a live input
line, the highlighted row of a list box, the bits of a check box cluster or the
selected radio button (`views.cc:683`), from an ordinary window and not a
dialog. It has never been reachable: like `screenSize` and `focus`, there is no
message that carries it. So "the model cannot see a check box that was ticked"
is one message wide, not a feature — and the design question that remains is
only whether the model *asks* (a query, which this protocol has never had) or
is *told* (a `Changed` event, which is the shape `Focused` already set). The
keystroke-level half — what a validator needs — is the part that is genuinely
missing.

**9. `TMultiCheckBoxes`.** A cluster whose items have more than two states.
Small, rarely wanted, and a hole in an area the API otherwise covers
completely. Listed so it stops being a surprise.

**10. A view on the application rather than the desktop.** `TClockView` and
`THeapView` sit beside the desktop, not on it, and `Ui` has a menu bar, a
status line and windows with nothing in between. `examples/demo` puts its clock
in the status line instead, which works and rebuilds the status line every
second; `watch` puts its counters there for the same reason. FINDINGS has the
note; it is why Borland made the clock a view.

### And what is not a gap

Said plainly, so nobody spends a day on one of these.

**The `TColorDialog` family** — `TColorSelector`, `TColorDisplay`,
`TColorGroupList`, `TColorItemList`, `TMonoSelector` — is an editor for the
palette indirection, and `examples/palette` argues at length that the
indirection has no Gren equivalent. A colour dialog here is a form, and what it
sets is a field, which is what `examples/demo` already does with five radio
buttons.

**`TParamText`** is `printf` for a static text. String interpolation is the
model's job by construction.

**The help system.** `THelpFile` reads a binary format produced by `tvhc`.
Porting the compiler buys nothing a Gren program wants; help screens are
windows.

**`TEditor` and its family** — `TFileEditor`, `TEditWindow`, `TMemo`,
`TIndicator` — are a milestone rather than a gap, and the note above says what
it would take. Two things learned since that note was written: wrap `TEditor`
rather than `TFileEditor`, because the file half is already a `Task` in Gren
and `editorDialog` is a replaceable function pointer, so it drags in neither
`TFileDialog` nor `.rsc`; and `TEditor` sets `growMode = gfGrowHiX | gfGrowHiY`
in its constructor (`teditor1.cpp:193`), so it wants gap (2) settled first.
`TMemo` is the cheap way in: a multi-line field in a form, collected when the
dialog is answered, which keeps the model-owns-the-state invariant intact.

The Gren-only example is done: `watch`, written up above. It is the answer to
"what does this have that Borland's did not", and the answer turned out to be
three things — a subscription, several children at once, and a handle on
something still running.
