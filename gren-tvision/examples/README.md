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
| `entries` | *(ours)* | list boxes, `Time.every` behind a modal dialog, `WindowClosed`, mutable window titles — and later `Tui.focus`, because "show me that window" is the thing a description of the UI cannot say, `Resized`, because it is the first example that does not assume 80x25, `Grows`, because a window that grows and a list box that does not is worse than neither, `Changed`, because a filter box is a control in an ordinary window, `messageBox`, because Clear should ask first, and `History`, because a filter box worth typing into is one worth remembering |
| `forms` | `tvision/examples/tvforms` | check boxes, radio buttons, labels, and a list box highlight the model can both read and move — later `allowed`, the filter on its phone field, and `MultiCheckBoxes`, the cluster the other two could not express |
| `ascii` | `tvision/examples/tvdemo` (ascii.cpp) | the canvas, from Gren: a view the model paints itself, and a cursor to select with |
| `calendar` | `tvision/examples/tvdemo` (calendar.cpp) | colour on a canvas, as spans; and today as a field, because `Time.now` is a task |
| `puzzle` | `tvision/examples/tvdemo` (puzzle.cpp) | nothing in the API -- but the random seed had to move into the model, which is what let a test win the game |
| `calc` | `tvision/examples/tvdemo` (calc.cpp) | `takesFocus` on a button: a keypad that can be pressed but never holds the caret |
| `palette` | `tvision/examples/palette` | nothing -- it is the example whose entire subject the port removes, and the write-up says what that costs |
| `mouse` | `tvision/examples/tvdemo` (mousedlg.cpp) | the scroll bar as a view of its own, `isDouble` on a click, `setDoubleClickDelay`, and `takesFocus` on a canvas |
| `dir` | `tvision/examples/tvdir` | no widget at all — but it found a real bug in the diff, moved a list box's scroll bar, and is the first example to use the file system; later `Tui.fileDialog`, which finished the port, the `History` on its field, and `for` on `ScrollBar`, because it is the only window here with two scrollable panes in it |
| `demo` | `tvision/examples/tvdemo` (the shell) | real windows: zoom, resize, tile and cascade, which every window had silently been unable to do — and later the first `Tui.messageBox`, which is its About box with fifteen lines taken out, `popupMenu`, whose right-click menu is three commands it already had, and `Ui.overlays`, which is where its clock finally belongs |
| `viewer` | `tvision/examples/tvdemo` (fileview.cpp) | nothing — `TScroller` went the way of `TOutline`; but it is the first horizontal scroll bar doing its own job |
| `edit` | `tvision/examples/tvedit` | the editor: the first view whose contents do not travel with the render, and the first time the state is not the model's — plus find and replace, where a command needs a string only the program can ask for |
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

**Two bugs in `calendar.cpp` came out of that port and are now fixed
upstream.** Its leap year rule was `year % 4 == 0`, wrong for 1900 and 2100 --
which matters only once today is data and a test can walk to either -- and its
two header arrows were backwards, so clicking the one pointing *up* moved
forward while the Up *key* moved back. Both were filed as
[magiblot/tvision#229](https://github.com/magiblot/tvision/issues/229) and
fixed in `e72d695`; this example, which had reproduced the arrow quirk
deliberately, turned round with it. The reason to copy a quirk is that it is
what the original does, and it expires the day that stops being true.

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
the column immediately to the right of the list, so leave one. That column is
also the bar's answer to the mouse wheel: it takes a turn over its own list and
over itself, and nowhere else.

**And, long afterwards, it wanted `for` on `ScrollBar`.** Two scrollable panes
in one window is the shape Turbo Vision's wheel routing gets wrong, and this is
the only example that has it: the file pane's bar was in front and took every
turn, so the tree could not be wheeled from anywhere on the screen. `for =
"files"` on that bar is the whole fix. See the wheel note under tvdemo.

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
| `tvdir` | **done** | `examples/dir` — and it turned out to need no new widget at all, Change Dir included; see above |
| `tvedit` | **ported** | `examples/edit`. `TEditor` is wrapped; `TFileEditor` is not, because reading a file is a `Task`. See the note below |
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

**~~`TEditor`.~~ Done — [`Editor`](#View), protocol 13, and it is
`examples/edit`.** This paragraph guessed "an opaque editor view that owns its
buffer, reports changes as events, and takes `setText`/`getText` commands", and
that is what it is. What the guess got wrong is which direction the problem
was in.

It said the trouble was that "every keystroke would resend the document" —
view to model. That is the smaller half. The bigger half is that **`view` runs
on every tick of every subscription**: a `text` field on an editor would put
the whole file in the render message once a second for as long as a clock is
running, whether anybody touched it or not. And a model that owned the buffer
would have to implement insert, delete, word-left, undo and a clipboard, which
is to say implement `TEditor`.

So the boundary moves exactly one step: **the editor owns the buffer and the
model owns the file.** The document crosses twice per file — in through
[`setEditorText`](#setEditorText), out through [`readEditor`](#readEditor) —
and in between the model gets an [`Edited`](#Event) event carrying
`isModified`, `line` and `column`. Three numbers per keystroke instead of a
file.

`readEditor` is not the query this protocol has always refused. What was
refused is a *synchronous read* — `tv.getValue()`, which `Changed` exists to
replace. This is a `Cmd` producing a `Msg`, the shape `dialog` established:
the message goes out, the program carries on, the document comes back as an
ordinary event.

**The one sharp edge**, and `drive_edit.py` caught it on the first run: a
view's rectangle is structural, so changing one rebuilds the window — and a
rebuilt editor is an *empty* one, because there is no copy of the document in
the render to put back. Give an editor a fixed rectangle and let
[`Grows`](#Grow) resize it, which is what `Grows` is for. FINDINGS says what it
would take to make that impossible rather than documented.

**And the reserved vocabulary reached its ceiling.** The editor's commands are
built-in command names, so `examples/edit`'s whole Edit menu has
no handler behind any of it. The first version of that list interned
bare `"cut"`, `"copy"`, `"clear"` and the rest — and broke `demo` and
`entries`, both of which have had a Clear of their own for months. Nothing
reported it: the button drew, the hotkey worked, and the event simply stopped
arriving. So they are `"editor.cut"`, `"editor.copy"` and so on, the only
prefixed names on the list, because everything else on it is a word a program
is unlikely to want and an editor's vocabulary is made of the most ordinary
words a menu can contain.

Two are absent for one reason: each needs something only the model has. There
is no `"editor.save"` because writing a file is a `Task`, and no
`"editor.find"` because `cmFind` does nothing without a search string —
`TEditor` asks for one through `editorDialog`, which is disabled here because
every prompt it raises is a `messageBox`, which is an `execView`.

So the Search menu is three commands that arrive in `update`, three dialogs,
and three `Cmd`s answered by a [`Searched`](#Event) event —
[`findInEditor`](#findInEditor) and [`replaceInEditor`](#replaceInEditor),
protocol 14. **That two-step shape has now happened four times**: `dir`'s
Change Dir (list, then show), `edit`'s Save (read, then write), `entries`'
Clear (ask, then throw away), and this. The rule behind all four is one rule —
when a command needs something only the model can produce, it is a command the
model handles and answers with a `Cmd` of its own, and a built-in name is for
the ones that need nothing.

One deliberate divergence, in FINDINGS: `all = True` replaces every match in
the *document* rather than from the caret, because Turbo Vision's Replace All
replaces nothing at all after a search that ran off the end, and that is not
what the word means.

Two more things worth knowing, both in FINDINGS. `TEditor::setBufSize` does
not grow the buffer — that is `TFileEditor`'s override and is most of what
that class is, so `JsEditor` has the same one with the file half left out. And
`editorDialog` defaults to doing nothing (`editstat.cpp:18` returns
`cmCancel`), which is the best possible default here: every prompt it would
otherwise raise is a `messageBox`, which is an `execView`, which is the nested
loop the menu bar already has too much of. Nothing had to be done to avoid it —
and it also means Find and Replace are inert until something hands the editor
a search string, which is the next piece of work rather than a bug.

**The help system.** `THelpFile` reads a binary format produced by `tvhc`.
Porting the compiler buys nothing a Gren program wants; help screens are just
windows.

## Where that leaves it

**Every C++ example is ported**, and everything in `tvdemo` except the help
system. `tvhc` and `avscolor` are not Turbo Vision applications.

`tvedit` was the last, and it was a milestone rather than a port — the note
above says what it turned out to be about.

### The widget set is complete; what is left is not widgets

Every `TView` subclass in `tvision/include/tvision/*.h` has been walked against
the four layers, and the stock controls are all there: `TStaticText`, `TLabel`,
`TButton`, `TInputLine`, `TCluster` with `TCheckBoxes` and `TRadioButtons`,
`TListViewer` with `TListBox`, `TScrollBar`, `TMenuBar`/`TMenuBox`/`TSubMenu`,
`TStatusLine`, `TWindow`/`TDialog`/`TFrame`,
`THistory`/`THistoryViewer`/`THistoryWindow`, `TMenuBox` as a context menu,
`TMultiCheckBoxes`, `TFilterValidator`, `TEditor`, and the
`TGroup`/`TProgram`/`TApplication`/`TDeskTop` scaffolding underneath. `Canvas`
is the escape hatch for anything the set does not have.

`TValidator`'s other four subclasses were left out with a reason of their own,
under gap (8) below.

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
excludes `evMouseWheel` (`views.h`), so a wheel turn is not delivered to the
view under the pointer — nor to the focused one. It is offered to every view in
z-order until one takes it, and a scroll bar is the only thing that ever does,
so the *frontmost* bar in a window used to answer for the whole window.

Since predc's time zone picker, that is no longer true. A bar a `ListBox` or an
`Editor` makes for itself takes a wheel turn only over its own pane, which is
what makes three lists side by side scroll independently, and a `ScrollBar` the
model owns takes one **`for`** field to do the same — the id of the view it
scrolls, listed before the bar, the rule `Label` already follows. `""` keeps
the window-wide behaviour, which is the right answer for a window whose only
scrollable thing is that bar's and is what four of the five say.

`dir` is the fifth and the reason the field exists: a tree list on the left and
a model-owned bar for the file pane on the right, the file bar listed last and
therefore in front, so every wheel turn in the window went to the files and no
pointer position could reach the tree.

### The coverage gaps, all closed

All ten, in the order they were listed, **all closed**. Each entry says what it
turned out to take, because "not done", "not decided" and "not needed" were
three different problems and the difference is most of what this list was for.

None of them is reported by `tools/check_consistency.py` any more, which is
what closing four of these looks like from that end. The port is the only way
into the binding, so an exported function no runtime call site reaches is a
capability no Gren program can use — and the check named four when it was
written. `focus` was carried by protocol 5. `screenSize`, `getValue` and
`messageBox` are in its exempt list now, one written reason each: the first two
superseded by `Resized` and `Changed`, the third deliberately a JavaScript-only
convenience because the Gren package builds its own.

The first two were listed here as one design with two symptoms. They were two,
and neither needed the new layout language this list proposed: the first is an
event, and the second is `growMode`, which Turbo Vision has always had and
which nothing here was switching on.

**1. ~~The model does not know how big the terminal is.~~ Done — the
[`Resized`](#Event) event, protocol 6.** It carries the **desktop's** size, not
the screen's, because that is the coordinate system a window's rectangle is
written in; it arrives once at startup and again on every change; and
`examples/entries` lays both its windows out against it. FINDINGS has the
write-up, including why it could not arrive in `init` and why the binding polls
for it at the pump rather than hooking `cmScreenChanged`.

`screenSize()` is superseded rather than missing — it reports the screen — and
is now in the consistency check's exempt list with that reason attached.

The other examples still hardcode 80x25 and are still correct at 80x25. `dir`
stopping its window at column 78 and `watch` dividing an assumed 23-row desktop
are now ordinary bugs with an ordinary fix, rather than things the API could
not express.

**2. ~~Child views do not grow with their window.~~ Done — [`Grows`](#View),
protocol 7.** It never needed a `fill`/`fixed` layout invented for it, which is
what this entry used to say: Turbo Vision already has the declarative layout.
`growMode` is one integer per view and `TGroup::changeBounds` resolves it.

A view opts in by being wrapped — `Grows { grow = Tui.stretch, view = ... }` —
so a view that does not care says nothing, which is most of them. `Grow` is
four booleans, one per edge, with `stretch`, `pinRight`, `pinBottom` and the
rest named for the combinations worth naming.

Two things had to be found out on the way, and the second is the one worth
knowing:

  - **Windows have always grown with the terminal.** `beWindow()` sets
    `growMode = gfGrowAll | gfGrowRel`, so every window is rescaled
    proportionally when the screen changes. Nobody had written that down.
  - **Wrapping the views changed nothing until the differ stopped rebuilding
    them.** `sameShape` treated a window's rectangle as structural, so a model
    laying out against the terminal size closed and rebuilt the window on
    every resize — and `changeBounds`, the only thing that resolves `growMode`,
    never ran. A window's rectangle is now patched with `tv.setBounds`, exactly
    as its title already was, which also stops a resize from throwing away the
    caret, the scroll position and the list highlight.

`drive_entries.py` checks both paths, because they are different mechanisms
with the same picture: the terminal resizing, where the model is told and
re-lays-out, and the frame's zoom box, which is Turbo Vision's own command and
never reaches the model at all. The second is the case this entry was written
about, and it is the one where `growMode` is the only mechanism there is.

This was the prerequisite for anything editor-shaped: `TEditor` sets
`gfGrowHiX | gfGrowHiY` in its own constructor.

**3. ~~The model cannot move focus.~~ Done — `Tui.focus`, protocol 5.** It was
the cheapest item on the list and it was not quite plumbing: two things had to
be decided and one C++ bug had to be fixed. `examples/entries` uses it in both
directions — Alt-L raises the list window, which is a menu entry that used to
do nothing at all when the window was already open, and adding an entry puts
the caret back on the list the entry went into. FINDINGS has the write-up.

**4. ~~The standard file and directory dialogs.~~ Done —
[`Tui.fileDialog`](#fileDialog), and no protocol change.** The guess this entry
used to make held: neither `TFileDialog` nor `TChDirDialog` is a class worth
wrapping, and the answer is a function returning a `DialogSpec` — the shape (5)
established. `examples/dir` now has the Change Dir half of `tvdir`, which was
the one part of it not ported.

`TFileDialog::readDirectory` runs inside the dialog; here `listDirectory` is a
`Task`, so the model reads and hands over what it found, and `Alt-C` is two
steps — read, then show. Which makes the helper a *layout* and almost nothing
else: what the entries say, whether `".."` is among them and what a name means
are the program's business. The same answer `TOutline` and `TScroller` got, for
the third time.

Two things it turned up, both in FINDINGS. **Navigating is a reopen**: a dialog
is a `Cmd`, not part of `view`, and nothing patches one while it is up, so
walking into a directory is a second listing and a second dialog — three lines
in `update`, and a blink on screen. And **only four button names close a
modal** — `ok`, `cancel`, `yes`, `no` — so a dialog gets at most four buttons,
and `dir` spends three of them with Open as `"yes"`.

`THistory` is in it now, under the fixed id `"fileHistory"`, taking its list
from a `history` field on the spec. Still missing and not blocking: a wildcard
filter, which is an `Array.keepIf` the model does before passing the entries
in.

**5. ~~A message box.~~ Done — [`Tui.messageBox`](#messageBox), and no protocol
change at all.** It is the one gap whose answer was "write it in Gren": a
message box *is* a dialog, and every part of one already crosses the port. The
helper returns a `DialogSpec`, the caller hands it to `dialog` like any other,
and the answer arrives as an ordinary `DialogClosed` carrying the id.

That establishes the package-helper shape (4) needs. It also could not have
been written before gap (1): a box centres itself, a dialog's rectangle is in
desktop coordinates, and `desktop` is a field on the spec that the model fills
in from what `Resized` told it.

`tv.messageBox()` stays reachable from JavaScript and not from Gren, on
purpose — `tvision-node` is a package people use from JavaScript and its own
examples call it — so it is the fourth name in the consistency check's exempt
list. The check now prints no coverage notes at all: every function the binding
exports is either reachable or deliberately not, and each of the four says why.

`examples/demo`'s About box was fifteen lines of hand-built dialog and is now
five lines of spec; `examples/entries` asks before Clear throws everything
away.

**6. ~~`THistory` — the drop-down beside an input line.~~ Done —
[`History`](#View), and no protocol change.** The question this entry asked
— a widget to wrap, or a `ListBox` in a small window plus a field on the
model? — got the opposite answer to the four before it, and the reason
generalises.

**A package helper works when the interaction begins in `update`.** A message
box and a file dialog both do: the model issues a `Cmd` and is answered with a
`Msg`. A history drop-down opens over a field that is very often inside a
dialog that is *already up*, where `update` is not driving the screen and there
is no moment for it to be asked. So it is a view, and it is the first thing on
this list that had to be.

The state stayed with the model anyway, which is the part worth having.
`historyAdd`/`historyStr` (`histlist.cpp`) are one process-wide buffer keyed by
a hand-picked `uchar`, silently dropping the oldest entries when it fills, and
written to behind the program's back when a field loses focus. None of it is
used: `items` arrives with the render like a list box's, and `recordHistory` is
overridden to do nothing. **The widget shows the list; the model decides what
goes into it** — so `dir` remembers the directories Chdir was answered with,
`entries` remembers a filter only when something was chosen out of it, and
either could be saved to a file, which Borland's never could.

It is the one view with no `rect`: it takes the three columns right of the
field it names, which is where every Turbo Vision dialog puts one.

Two things it forced, both in FINDINGS. **`THistory::handleEvent` calls
`owner->execView`** — the nested modal loop milestone 2.5 removed — which
would have stopped Node's event loop for as long as the drop-down was open. So
the modal stack gained a second way in: `openLocalModal`, a view pushed onto
the same stack `tv.dialog()` uses but answered with a C++ continuation instead
of a promise. `drive_entries.py` checks the clock keeps ticking with the list
open, which is the assertion that widget exists for. And **the model really is
still running behind it**, so it can close the window the field is in — the
continuation captures the view's id rather than `this` and looks it up when it
fires.

Choosing an entry arrives as an ordinary [`Changed`](#Event) event on the
*field*, because that is what happened, so the protocol is still at 8.

**7. ~~`TMenuPopup` — context menus.~~ Done — [`popupMenu`](#popupMenu) and
[`PopupItem`](#PopupItem), protocol 9.** This entry said the menu machinery was
all there and what was missing was a way to open one at a point. Both halves
were wrong. Opening one was the easy part, and the machinery is where the
problem is.

**`TMenuView::execute()` is a nested event loop, and the menu bar has always
run it.** Two hundred lines around a `getEvent` at the top of a `do ... while`,
reached from `TMenuBar::handleEvent` — so while a pull-down is open it is
spinning inside the pump's own `handleEvent` call and Node's loop is stopped.
Measured in `entries`, whose clock is a `Time.every` subscription: 1 → 5 ticks
in 3.5 seconds normally, 5 → 5 with a pull-down open, moving again the moment
`Esc` is pressed. Nothing is *lost* — the timers fire when the menu closes —
but every subscription, promise and render in the program is stopped for as
long as somebody is looking at a menu. **That is a known limitation and it is
not fixed**: undoing it means reimplementing `execute` as a state machine the
pump can step, five flags carried across iterations and a recursive `execView`
in the middle, in the least documented code in the library, to buy back a
one-second freeze. FINDINGS has the measurement and the argument.

What was done instead is that nothing new was built on top of it.
`TMenuPopup::execute()` *is* `TMenuView::execute()`, so the popup here is a
`TMenuBox` — kept for the drawing — with a `handleEvent` of its own, on the
same modal stack `dialog` and the history drop-down use. `drive_demo.py`
checks the clock keeps ticking with the context menu open, which is the
assertion the class exists for.

**A context menu is flat**, and that is the same fact seen from the other end:
a submenu is the recursive `execView` in the middle of that loop.
`PopupItem` is `Entry` and `Divider` and there is no `SubMenu`.
`TEditor::initContextMenu` — Cut, Copy, Paste, Undo — is flat too, so the
thing this gap is a prerequisite for does not want one.

**What comes back is an ordinary `Command` event**, because the chosen command
is put back on the event queue rather than reported specially. A built-in like
`"quit"` or `"zoom"` is handled by `TApplication` without reaching the model at
all; anything else arrives indistinguishable from the same entry on the menu
bar. `examples/demo`'s context menu is three of Turbo Vision's own window
commands and `update` handles none of them.

Protocol 9 is that message plus `isRight` on a [`Clicked`](#Event) event, which
go together: the model opens the menu, and a right click is how it learns it
was asked for one. Two other things fell out and are in FINDINGS — the pump was
casting every modal view to `TGroup *` and reading `TGroup::endState` off it,
which had been true of every modal until this one; and the first right click on
an inactive window is still spent activating it.

**8. ~~Validators on input lines~~ Done, in two halves —
[`Changed`](#Event) at protocol 8 and `allowed` at protocol 10.** This entry
was two faces of one hole and they were closed a long way apart.

`TValidator` and its five subclasses vet a field *as it is typed* —
`TFilterValidator` rejects a keystroke outright, `TRangeValidator` and
`TPXPictureValidator` check on the way out. The model cannot do the first,
because it is never told about a keystroke that reached an input line.

`forms` walked up to the other side of it: values were collected when a
*dialog* was answered and at no other moment, so a check box ticked in an
ordinary window was invisible until something asked. Turbo Vision programs are
shaped that way — data entry happens in modal forms — so it was never in the
way there, but it was the same hole the `Focused` event filled for list boxes.

**That half is done — the [`Changed`](#Event) event, protocol 8.** The
model is *told* when the user moves a value: typed into an input line, ticked a
check box, chose a radio button. Told rather than asked, which is what keeps
every message in this protocol one-way — a query would have been the first.
`tv.getValue()` is therefore superseded rather than plumbed, and is in the
consistency check's exempt list with that reason written down.

`examples/entries` has the demonstration: a filter box in an ordinary window
that narrows the list on every keystroke, which is the smallest honest thing
that could not be written before. Two things had to be got right and FINDINGS
has both — a burst of keystrokes must not outrun the renders that answer them,
and a value the *model* sets must not select the field the way an initial value
does, or the user's next keystroke replaces everything they typed.

**And so is the keystroke-level half — `allowed` on an
[`InputLine`](#View), protocol 10.** The entry used to say the model "is still
never offered that choice", and the framing was the mistake: offering it would
have been the first question-and-answer this protocol ever carried. `allowed`
is a *set of characters on the view*. The model says what the field takes, a
keystroke outside the set does not happen, and nothing is reported because
nothing happened — one-way by construction rather than by discipline.

The obvious alternative was an event carrying the keystroke and an answer
carrying yes or no, with the field sitting still until the model replied. It
would have worked and it would have made every keystroke a round trip through
Gren.

Half of `TFilterValidator` is overridden away, and FINDINGS says why:
`isValid` runs when the *dialog* is answered and calls `error()`, which is
`messageBox`, which is `execView`, which is a nested loop. It is also the wrong
policy — the only way a field can hold a character its own filter rejects is
for the model to have set it, and a value the model set is the model's to
validate.

`TRangeValidator` and `TPXPictureValidator` are not wrapped for the same
reason. A range validator's filtering half is `allowed = Just "+-0123456789"`
and its checking half is one `String.toInt` in `update`, which gets a message
the program wrote rather than Borland's in a box the model cannot see.
`examples/forms` has the demonstration: its phone field takes digits, spaces,
brackets, `+`, `-` and `.` and nothing else.

**9. ~~`TMultiCheckBoxes`.~~ Done — [`MultiCheckBoxes`](#View), protocol 11.**
A cluster whose boxes have more than two states. It was exactly as small as
this entry said, with one thing worth knowing.

`TMultiCheckBoxes` packs *every* box's state into the one 32-bit
`TCluster::value`, which is why its constructor takes two numbers nobody would
guess — `selRange`, and a `flags` word holding a bit mask and a bits-per-item
count. Both come from something the model was going to give anyway: `marks`,
one character per state, drawn between the brackets. So the Gren side says
`marks = " ?X"` and `states = [ 2, 0 ]` and never sees either number.

The packing is a real ceiling — *items* × *bits per state* must fit in 32,
so eight boxes of four states or sixteen of three — and the builder throws
with both numbers in the message rather than letting the shift drop the boxes
that do not fit.

[`Value`](#Value) gained a fourth shape, `Marks`, and [`marks`](#marks) reads
the same thing out of a dialog's answer beside `text`, `number` and `flags`.
`examples/forms` has a "Reach" cluster: two boxes, three states each, blank
`?` `X`.

**And it found an upstream bug** — the second thing this port has had to report
after [#229](https://github.com/magiblot/tvision/issues/229), and the first in
the library rather than in a demo. `TMultiCheckBoxes` allocates its `states`
string with `newStr()` — `new char[]` — and frees it with plain `delete`
(`tmulchkb.cpp:62`). ASAN does not warn about an alloc/dealloc mismatch, it
stops the process, so the first `test:asan` run failed at every check after the
dialog was closed while `test` stayed green throughout. The same shape turns up
in six more places in the library; FINDINGS lists them, and all seven are
reported as
[#230](https://github.com/magiblot/tvision/issues/230). The subclass passes a
null `states` and draws the marks itself, and goes on doing so until the fix
lands upstream — `tvision/` is gitignored, so a fresh checkout does not have
it.

**10. ~~A view on the application rather than the desktop.~~ Done —
[`Ui.overlays`](#Ui), protocol 12.** `TClockView` and `THeapView` are inserted
into `TProgram`, not into `TDeskTop`, and `Ui` had a menu bar, a status line
and windows with nothing in between. `overlays` is that place: an
`Array View` in **screen** coordinates, drawn above every window, uncoverable
by one, and never tiled or cascaded.

The binding is one function, because `buildItems` only ever needed the group
to be a `TGroup` rather than a `JsWindow` — it was already writing into one.

Three things fell out, all in FINDINGS. **The status line was the workaround
and it cost a repaint a second**: `examples/demo`'s clock was a status item,
and a status line is replaced *whole*, so it rebuilt the entire line every
second — precisely why Borland made the clock a view. It is now one
`StaticText` in `overlays`, patched. **Growing works because `Grows` already
did**: `TClockView` sets its own `growMode`, and here that is
`Grows { grow = Tui.pinRight, ... }` on a view that is not in a window, with
nothing added to make it work. And **screen coordinates are not desktop
coordinates** — the same width, two rows shorter, so row 0 is the menu bar's
row and that is where a clock goes.

`watch` still puts its counters in the status line, which is a fair place for
counters that are text; the point is that it is now a choice.

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

**`TFileEditor`, `TEditWindow`, `TMemo` and `TIndicator`.** `TEditor` itself is
wrapped — see `edit` above — and its family is not, each for its own reason.

`TFileEditor` is `TEditor` plus loading, saving and a growing buffer. Only the
third of those is wanted: reading and writing a file is a `Task` in Gren, so
`JsEditor` takes `setBufSize` from it and leaves the rest, which is also what
keeps `TFileDialog` and the `.rsc` prompts out of the picture.

`TEditWindow` is a window with an editor in it and a `TIndicator` on its
frame. A window is already a value here, and the indicator is better as a
`StaticText` the model fills in from the [`Edited`](#Event) event — what it
says is then the model's, like every other display in these examples.

`TMemo` is `TEditor` with `getData`/`setData`, so that a multi-line field can
be collected when a dialog is answered. That is the one piece of the family
still worth wanting, and it is not free: a dialog's answer is a small record
of what the user chose, and putting a document in one would make every
`DialogClosed` carry it. The honest version is an `Editor` in a dialog plus a
`readEditor` before it closes, which the API can already express.

The Gren-only example is done: `watch`, written up above. It is the answer to
"what does this have that Borland's did not", and the answer turned out to be
three things — a subscription, several children at once, and a handle on
something still running.

### Gap 11, which the list did not have: how big is *this* window?

Found from outside, by `programmers-edc`'s hex dump viewer, and it is the
mirror of gap 2. `Grows` (gap 2) makes a view follow its window's edges, and
`Resized` (gap 1) says how big the *desktop* is -- but nothing said how big one
window was. For a view that only draws itself that is fine, and it is why the
gap went unnoticed through fifteen examples: `entries` fills a window with
`Grows` and never counts anything. A view whose contents are the model's has
the other problem. A hex dump in a taller window was sixteen rows of dump and
blank space, because the canvas grew and the lines did not.

Two additions, and they are halves of one idea.

**`WindowResized`** carries a window's whole rectangle, in the same desktop
coordinates as `Window.rect`. It is found by polling, once per pump, exactly
as `Resized` is: a window's bounds can change five ways -- the resize handle,
the zoom box, `Tile`, `Cascade`, and `growMode` following the terminal -- with
no one call they share, and comparing the rectangle is true whichever route
was taken. The differ is deliberately told nothing, which is what leaves a
window where the user dragged it: what the differ compares against is the
*model's* rectangle, and a model that ignores this event renders the same one
and writes no `setBounds`.

**`Resize`** on a `Window` says which of its two dimensions the user may
change at all -- `Tui.resizable`, `Tui.resizeHeight`, `Tui.resizeWidth`,
`Tui.fixedSize`. It is `sizeLimits`, which is the single call `TFrame::
dragWindow`, `TWindow::zoom`, `TFrame::draw`, `TView::locate` and
`TView::calcBounds` all consult, so one override pins a dimension everywhere.
`examples/ascii` and `examples/forms` now say `fixedSize`, which is what both
of them always were: a 32x8 chart and two windows tiled to fill 80x25 exactly,
neither with anywhere to put extra space. The frame stops drawing a resize
handle and a zoom box for a window that has nothing to do with them.

It also turned up a gap in `TWindow::setState`, which only ever *enables* the
commands a window supports and leaves disabling them to whichever window was
selected before. A program whose first window is fixed-size therefore inherits
an enabled `cmZoom` from `initCommands()` and shows a lit `F5 Zoom` that does
nothing. `JsWindow` now disables it for a window that cannot zoom -- and not
`cmResize`, because a fixed-size window can still be moved.

The pair is what let the hex viewer stop apologising for sixteen bytes a row.
It is no longer "the model cannot know how wide the window is"; it is "sixteen
is what a hex dump is, and the window says so" -- `resize = Tui.resizeHeight`,
taller shows more file, wider is not offered. The full argument is in FINDINGS,
along with the rule this made concrete: a *view's* rectangle is structural, so
a layout must be written once and grown by `Grows`, never recomputed from the
new height.

### The windows were the wrong colour, and had been all along

Not a gap -- a bug, and one that had been on screen since the first window this
package drew. `JsWindow` derives from `TDialog`; `TDialog`'s constructor
overwrites the `wpBlueWindow` palette `TWindow`'s had just set with
`dpGrayDialog`; and `beWindow()`, which exists to put back what that
constructor takes out, put back four things and missed the fifth. So every
window on every desktop was painted in the *dialog* palette, white on light
grey, and it looked deliberate because it was uniform.

Windows are blue now and dialogs are still grey, which is the distinction Turbo
Vision has always drawn. The cost lands on the spans: `Hue` is an absolute
colour, so every `ink` in the repo had been chosen against a ground that was
grey by accident. `examples/calendar` marked today in yellow and
`examples/puzzle` drew its checkerboard in it, and yellow is what a blue
window's text already is; both are repainted, and both drivers caught it
because both assert that some cell differs from the body colour. The full
account, and the colour vocabulary that came out of it, is in FINDINGS.

### What the palette example changed, the second time

`examples/palette` was written as the one port whose whole subject disappears
in translation: three layers of indirection replaced by a span that names its
colour. `WindowPalette` is the piece that came back, and this is where it is
demonstrated, because the example is already an argument about exactly this.

`Alt-W` cycles the lower window through Turbo Vision's three colour sets. The
upper window does not move, because every line in it names both halves of its
colour; the lower one follows, because its lines name nothing. That is the
whole trade on one screen and a single keystroke -- say the colour and it is
yours to keep, say nothing and it is the window's to change.

`Alt-T` then changes what those three sets *are*. `Theme` on a `Ui` is the
application palette -- everything the package draws rather than the model -- in
seventeen fields rather than the hundred and thirty-five attributes Turbo
Vision keeps them in, which works because the 135 are not 135 decisions: one
desktop, one bar, and three coloured surfaces written into two blocks apiece.
`Tui.borland` is Turbo Vision's *look* rebuilt from those fields rather than
its table reproduced: compared byte for byte against `cpAppColor`, 82 of the
135 slots differ, almost all of them in blocks nothing reaches or in places
where the model deliberately treats a surface as one surface. The first version
of this paragraph claimed the expansion was proved correct because every colour
assertion in the suite passed against it, which proves much less -- the suite
asserts on a few dozen cells, and one genuinely wrong slot (the list viewer,
two off) survived exactly that argument.

The example's second theme is deliberately `Rgb` throughout where Borland's is
`Ansi`, because that is a real choice: `Ansi` inherits whatever sixteen colours
the person running the program has set and matches the rest of their machine,
`Rgb` pins the colour and looks the same everywhere. A dark scheme is the case
that needs the second -- `Black` and `DarkGray` is the only dark pair the
sixteen offer, and it is at once too far apart to read as one surface and too
close to be a border.

Two more things it taught. The three sets a window can have are the *dialog*
palettes and not the window ones -- a window here can hold a button, and a
button asks for entries past the eight a window palette has. And a `TGroup`
with a buffer draws by blitting it, so recolouring a window and calling
`drawView` paints the cached colours back and looks like nothing happened;
`redraw` is what asks the children for their colours again. Both are in
FINDINGS.

### What is left, now that the list is empty

**The one known bug is fixed, and it was ours.** `programmers-edc`'s hex dump
viewer -- written as an ordinary consumer of this package -- opened
`Tui.fileDialog`, typed a path into the `Name` field, and nothing happened. It
looked like a binding bug for a week: a modal dialog with a list in it opened
with the caret elsewhere and the field two Tabs away, `applyInitialFocus` works
for windows, and every distinguishing feature of the failing case pointed at
`TListViewer`. The cause was `Tui.fileDialog` building its `views` array with
`Array.append`, whose *first* argument is the postfix -- so it listed the
buttons first, and that array is both the initial focus and the tab order. One
word, `prepend`, fixes both. The story is in FINDINGS under "The dialog that
opened on the wrong view"; what is worth carrying away is that nine checks
drove that dialog past the fault without seeing it, because a pty test reads a
screen and a screen does not say where the caret is. `drive_dir.py` now types
into the field, which is the only kind of assertion that can.

**The clipboard is bound now**, in both directions:
[`copyToClipboard`](../src/Tui.gren) and `readClipboard`, with `Copied` and
`ClipboardText` events, protocol 19. It was the last unreached pair of
functions in the C++ API. Reading is a request answered by an event rather than
a getter, because a terminal that owns the clipboard is asked for it with an
escape sequence and replies through the input stream -- FINDINGS has the shape
and the reason `TClipboard` is skipped. `tvision-node/examples/clip.js` and
`test/drive_clip.py` are the demonstration, and the driver is worth reading for
how it answers OSC 52 with no clipboard anywhere near it.

**One gap a consumer walked into, and it is closed.** The binding forwarded
`evMouseDown` and no other mouse event, so a model could hear a click and not a
drag -- which predc's hex viewer wanted for extending a highlight and worked
around by making the far end of its mark the cursor, so that a click extends
it. It is `Tui.Dragged` now, protocol 21, and it is a forward of
motion-while-a-button-is-down rather than Turbo Vision's nested `mouseEvent`
loop. See "The drag, which is a capture and not a loop" at the end of this
file, and FINDINGS.

**One known limitation**, written up under gap (7) and in FINDINGS:
`TMenuView::execute` runs a nested event loop, so the *menu bar* stops the
program while a pull-down is open. Nothing in this package is built on it —
the history drop-down and the context menu both avoid it deliberately — and
undoing it means reimplementing the least documented code in the library to
buy back a one-second freeze. It is a decision, not an oversight, and it is
written where somebody would hit it: FINDINGS, this file, and
`Tui.MenuItem`'s doc comment.

## What predc's command line changed

The one API change since the list emptied, and it came from the application
rather than from an example: **a program built on this package can now decide,
in `init`, that it is not a program this time.**

`predc hex dump.bin` wanted a CLI, and a CLI has answers that are not a screen
-- `--help`, `--version`, a word that is not a command. `Tui.defineProgram`
renders after `init` unconditionally, and the first render is what starts Turbo
Vision, so a help text printed itself *and* switched the terminal to the
alternate screen. Racing `Node.exitWithCode` against the render was rejected:
the order of two effect managers is not a contract, and `exitWithCode` does not
wait for the write to reach a pipe -- which is where a help text usually goes.

```gren
type Startup model
    = Start model
    | Exit

defineProgramOrExit : Ports msg -> ProgramConfigurationOrExit model msg -> Program model msg
```

`Exit` sends no render, so the runtime never starts Turbo Vision at all, and
`view` is never called. It costs no protocol version, no C++ and no runtime
JavaScript: the whole of "do not paint" is *not sending a message*, which is
what a one-way protocol is good for.

Two things about the shape are worth copying elsewhere. The flag lives in the
model type rather than beside it -- an exiting program has no model and should
not have to invent one -- and `Tui.Program` absorbed the change because it is an
alias, so every `main : Tui.Program Model Msg` in these fifteen examples is
untouched. `defineProgram` is now four lines of `defineProgramOrExit` that wrap
the init in `Start`; two entry points where one would do, rather than changing
the `init` of every program ever written against this package for a capability
most of them will never use.

FINDINGS has the rest, including what an application has to do by hand because
`Argparse.Program` is a `Node.SimpleProgram` and cannot be the thing that paints.

## The scroll bar that had to be clicked twice

Reported from the application rather than found by a test, and fixed in the
binding: `JsScrollBar` set `options |= ofSelectable` so a model-owned bar would
be reachable by Tab, and `TView::handleEvent` swallows a mouse-down on a
selectable view that has not got the caret unless the view also says
`ofFirstClick`. So the first click on the bar took focus and moved nothing, and
whether the next one worked depended on where the caret was -- which no screen
shows. `options |= ofSelectable | ofFirstClick` is the whole fix.

**The rule: `ofSelectable` on a control whose purpose is to be clicked needs
`ofFirstClick` with it.** The two-click rule is right for a window and for a
canvas, and wrong for a widget.

The other half of the same report was not a bug. magiblot's `TScrollBar` takes
the thumb to the pointer on any click that is not an arrow, where Borland's
paged, so `pageStep` is keyboard-only and the bar's resolution is the number of
cells it is tall -- one cell of a sixteen-row bar is forty-six rows of a
nine-kilobyte file. Both are now in `Tui.View`'s doc comment, and FINDINGS has
the measurements.

## The double click in the file dialog

Also reported from the application, also not the binding: double-clicking a
name in `Tui.fileDialog` did nothing. The event was arriving all along --
`TListViewer::selectItem` fires and the model gets a `Selected` -- but a modal
dialog can only be ended by a command, so hearing about the double click and
being able to act on it are two different things. Turbo Vision's own
`TFileDialog` turns `cmFileDoubleClicked` into `cmOK` inside the dialog;
`fileDialog` is a layout built out of an `InputLine`, a `ListBox` and buttons,
so it never had that.

`ListBox` gained `chooses : String` -- the command a committed entry sends,
which `fileDialog` fills with the default button's -- and the C++ puts that
command back on the queue exactly as a button press would. Protocol 20. The
dialog then closes with the same `DialogClosed` and the same `values`, so
predc, which already preferred the highlighted row when the Name field was
empty, needed no changes.

**Fourth use of the declarative field**, after `allowed`, `takesFocus` and
`isDefault`, and the test for reaching for one is unchanged: could the model
state this at render time? The alternative here was a round trip whose second
half would have been the first message in this protocol able to dismiss a
window from the outside.

## The clipboard's boolean says less than it looks like

Reported from the application: "Copy copies only in-application; I can't paste
outside of predc." The copy was reaching the terminal all along --
`TermIO::setClipboardText` writes the `OSC 52` every time and returns
`hasFullOsc52`, which is set only by evidence that the terminal supports
*reading* the clipboard back. So `Copied.toSystem = False` means "nothing
confirmed taking it", never "nothing took it", and three doc comments plus one
status line said the stronger thing.

The other half of the chain is worth knowing when advising anyone: Turbo Vision
tries `wl-copy`/`xsel`/`xclip` only when `WAYLAND_DISPLAY` or `DISPLAY` is set,
so over ssh that half never runs -- `OSC 52` is the only route that can work,
and tmux's default `set-clipboard external` swallows it (measured; `on`
forwards). `copyToClipboard`'s doc comment now carries all of it, because the
program that has to explain this to a user is the one built on this package.

## `maxLen` was one short, and a four-digit year proved it

predc's time converter wanted a field four characters wide. It got three:
`2026` came out as `202`, and the same off-by-one shortened every field on the
window by one.

`TInputLine`'s constructor takes a **limit** and stores `maxLen = limit - 1`
(`tinputli.cpp`), with a buffer of `maxLen + 1` bytes. `views.cc` passed the
model's `maxLen` straight through as that limit, so the field held one fewer
character than the model asked for. Nothing had caught it because the only
`maxLen` in the package is `fileDialog`'s 255, where a filename losing its
254th character is invisible, and because the field still *looks* right until
the value is exactly as long as the field.

The fix is `maxLen + 1` at the one construction site, so the name on the Gren
side means what it says: how many characters the user may type.
`setInputText`'s write at `[maxLen]` is still the last byte of the buffer, so
the alloc-size reasoning in the comment above it is unchanged, and ASAN agrees.

No protocol bump -- the wire field kept its name and its meaning became
correct. **The general shape is worth remembering:** a C++ constructor whose
parameter is named for a limit rather than for a length is an off-by-one
waiting for the first caller who cares about the exact width. This one waited
through fifteen examples and three tools.

## A dialog cannot be redrawn while it is open

The zone picker wanted a filter box that narrows a list of 418 as you type.
That is not expressible: `Tui.dialog` is a `Cmd`, `tv.dialog()` builds the
views once and returns a promise, and the differ has no path into an open
modal. The established alternative is `Tool.Hex`'s -- close it and reopen it
one directory down -- which resets the caret and is fine for a directory and
useless for a keystroke.

predc's picker is therefore an **ordinary window** of the tool's. Nothing was
lost: a modal is for a question and this is a workspace, it blocks nothing, and
the converter behind it keeps working. But the gap is real and this is where it
is written down.

It has a Cancel now, and getting one is the interesting part of being a
workspace rather than a form. Every add, remove and reorder is applied to the
converter as it happens, so there is no draft to discard: Cancel is an *undo*,
to a list remembered when the window opened. A modal would have got the cheap
version of that for free and would have had to give up the live preview to do
it, which is the trade the whole design was making anyway.

If it is ever closed, the shape to reach for is the one `Tui.Ui` already has
for everything else -- a `modal : Maybe DialogSpec` field rendered every
update, patched by the differ like a window -- rather than a second message
that pushes new views into a live dialog. Modality without nesting is already
the invariant; this would be modality without *staleness*, which is the same
argument one layer up.

## A rebuilt window comes to the front, one update later than you think

The picker kept being buried by the converter behind it. `Tui.focus` was being
sent with the request that changed the zone list, and the runtime does
re-apply a pending focus after the render it came with -- but the render that
*rebuilds* the converter is not that one. It is the next one: adding a zone
does not make the table taller until the reply comes back with a row in it, an
update later, and a window whose view list changed is rebuilt rather than
patched, and a rebuilt window arrives on top.

So a tool with two windows has to ask for the focus **when the thing that
changes the layout lands**, not when the user's click happens. predc carries a
one-field flag for it and the port trace is what found it -- the screen alone
said only "wrong window in front".

This is not a defect to fix in the package, but it is a fact about it that
nothing wrote down: `Tui.focus` is a request about the render it accompanies,
and a render caused by a `Cmd`'s eventual answer is a different render.

## `Focused` is the list box's contract, not the area list's feature

predc's picker has three list boxes and handled `Focused` for one of them, and
the bug that came of it is worth this package's attention rather than only that
program's: **Add** added the first row of the zone list however far down the
highlight had been clicked, arrowed or wheeled.

The event's own doc comment has said the rule since the day it was added:

> `Focused` — the highlight in a list box moved, by arrow key, mouse or a
> render that replaced the list. **This is how the model learns which entry an
> "Edit" or "Delete" button should act on**; Turbo Vision's own examples read
> the list's `focused` member at the moment they need it, which a program that
> cannot call into C++ has no way to do.

So nothing here is wrong and nothing needs changing. What is worth writing down
is the *shape of the mistake*, because it will happen again to anyone with more
than one list in a window: the picker's area list needed `Focused` for a
visible and interesting reason — choosing an area writes its prefix into the
filter box — and that is exactly what made handling it look like an area-list
feature rather than the contract every list box has. `Selected` carries an
index of its own, so `Space` and a double click stayed right the whole time and
hid it.

The lesson for a driver, which cost more than the fix: **exercise a widget by
every route the user has, not by the one the model treats as canonical.** Every
picker check went through click-then-`Space`, which sends `Selected`, so the
stale copy was never read. One check that pressed the button instead would have
caught it on the day the picker was written.

## What a toggle in a window is, now that `Changed` exists

predc's converter grew a live-clock mode, and the widget question it asked has
a better answer than the one it was nearly given: **a `CheckBoxes` cluster in
an ordinary window reports a tick, through `Changed`.** That is exactly what
protocol 8 was for and the event's doc comment says so, but `diff.js` still
carried a comment describing the world before it — "a box the user ticks is
reported only when a dialog is answered" — attached to a write-back rule that
is still correct for an unrelated reason. A stale explanation on a right line
reads exactly like documentation. It is fixed.

Building it settled the fact rather than arguing it: a one-item cluster in the
converter's button row toggles the mode. predc keeps a button anyway, because
it sits in a row of buttons and a caption can say what pressing it *does* where
a tick can only say what is true — a design choice, which is what it should
have been all along.

Two smaller facts fell out of the same mode, both about swapping widgets rather
than about the clock:

**`InputLine` writes its text one column in.** Making fields read-only by
rendering `StaticText` in their place is the natural move for a model that
re-renders, and it slides the whole table one column left of its heading unless
the static text starts at `x1 + 1`: `TInputLine::draw` writes at offset 1
inside its own rectangle (`tinputli.cpp:144`), and the two spare columns an
input line's rectangle carries are its margins, which a static text has none
of. Worth knowing before anyone else swaps one for the other.

**A window's title is patched, not rebuilt.** `Time converter` becomes
`Time converter -- live` when the mode changes, and the differ handles it with
`setTitle` — the same reason a window's rectangle and palette are not
structural. A mode indicator in a title is therefore free, which is not obvious
from a package where a view's own rectangle is structural.

## The drag, which is a capture and not a loop

The consumer gap from the section above is closed. `Tui.Event` has
`Dragged { id, x, y, isDone }`, protocol **21**: the pointer moved on a canvas
with a button held, or the button came up and ended the gesture. It is always
preceded by the `Clicked` that began it, and always on that canvas.

**What made it worth doing is not the mouse.** `TGroup::handleEvent` routes a
positional event to `firstThat(hasMouse)` — the view under the pointer *now* —
so a selection dragged one column past its own canvas belongs to the frame, or
to the window underneath, or to nothing. Turbo Vision's stock views get round
that with `TView::mouseEvent` in a loop inside `handleEvent`, which is a nested
event loop: the shape this package refuses, and the reason the menu bar's
pull-downs are a known defect. The capture is written out instead — a pointer
set by the press, consulted by the pump before it routes, cleared by the
release, by `~JsCanvas`, and by any modal opening. **The loop was never the
point of `mouseEvent`; the capture was, and a capture is a variable.**

Four decisions in it are the reusable part.

**A plain click stays one event.** The press arms the capture and sends nothing
extra; the first cell the pointer *moves* to sends the first `Dragged`; the
release sends one only if there was motion to end. Reporting every release
would have made every click on every canvas two events, and clicking is what a
canvas is mostly for.

**The coordinates are not clamped.** A drag above a canvas reports row `-1` and
below it reports `rows`. A model that wants only the cells it owns clamps in one
line; a model that wants to scroll needs to know how far past. Nobody can
un-clamp a clamped coordinate. `examples/ascii` is the demonstration and needed
one line, because the `moveTo` that Home and End already went through clamps.

**Motion is collapsed per pass of the pump**, exactly like a scroll bar's
positions and for the same reason. The release wins any collapse it is part of,
so a whole gesture can arrive as one event with `isDone` set. The hazard that
came with it is generic and is worth remembering wherever a queued event meets
an immediate one: **a click is dispatched where it happens and a drag is
queued, so a press in the same pass as the end of the previous gesture would
overtake it.** `dispatchClick` flushes the drag notes first.

**`evMouseAuto` is deliberately not forwarded.** Turbo Vision fires it while a
button is held *still*, and it is what would buy "hold at the edge and keep
scrolling". Its whole job is to report a position that has not changed, which
is the one thing the collapse above throws away, so it needs a variant or a
flag of its own. Nothing has asked yet; predc's hex viewer stops at the edge
and says so.

**And one thing the capture cannot rescue**, found on the way and then decided
rather than left open. `TView::handleEvent` spends the first click on a
selectable view that does not hold the selection on *giving* it back, so a
`Canvas` with `takesFocus = True` does not hear that click — and since the press
is what creates a capture, a drag begun with it is a selection and not a drag.

The condition is `sfSelected` and not `sfFocused`: *current within its own
owner*. That is why no example here has ever met it — a window whose only
selectable view is the canvas has an always-selected canvas. It takes a second
selectable view in the same window, which is what predc's hex viewer has in its
scroll bar.

**It stays as it is: the first click brings the view back and does nothing
else.** `ofFirstClick` would make one click both move the selection and act,
inside a view the user had not been working in — and a window with a bar in it
has two things to be pointing at. Two clicks is the cheaper surprise. FINDINGS
has the measurement and `drive_hex.py` pins it, which is what keeps a decision
from being undone by an edit that meant well.

**What it bought the consumer.** predc's hex viewer marks by dragging, in one
small function, and `v`, `1`-`6`, the colour legend, `y` and the dump copy all
act on what the mouse drew without knowing a mouse was involved — because the
far end of a mark is the cursor and a drag moves the cursor. The mark's anchor
is set on the first motion rather than on the press, which is what leaves a
plain click free to go on meaning "put the cursor here".

`harness.py` grew `drag(path)`. SGR reports motion as the button code plus 32,
and `TEventQueue` — not the terminal — is what turns that into
`evMouseDown`/`evMouseMove`/`evMouseUp` by comparing against the buttons
already down. The check worth copying from `drive_ascii.py` is the drag to
screen (1, 1), the corner of the desktop: it arrives at the chart anyway, with
negative coordinates. Nothing else asserts that the capture is real.

## What the API audit found first: a view that cannot be turned off

`tools/audit_api.py` walks Turbo Vision's public surface rather than an
example's needs, and the first thing it said was the one nobody would have
gone looking for: **`setEnabled` greys a *command*, and a view without one
could not be greyed at all.** An `InputLine`, a `ListBox`, a `ScrollBar` and a
`Canvas` carry no command, so there was no way to say that a control is not
available — which is what every form does while it is waiting for something.

It is `Enabled` now, and it is a **wrapper** for the reason `Grows` is one:
being available is `sfDisabled`, which belongs to `TView`, so it is true of
every widget rather than of any one of them, and a view that is always
available should not have to say so. That also makes it the second wrapper, so
`encodeView` walks down through any nesting instead of matching one level, and
`check_consistency.py`'s exemption list is a set rather than a name.

**A disabled view is not a colour.** Turbo Vision draws it grey, and it also
skips it in the tab order and hands it no keystroke and no click — which is
what makes it different from drawing a note beside the control. `entries` puts
its filter box behind one (nothing to filter, nothing to type) and the check
that pins it types at the box rather than reading its colour, because the
colour is the palette's business and the refusal is what the model asked for.

Three more from the same pass, all of them members of classes that were already
wrapped and none of them reachable before:

**`available` on a cluster**, one flag per box. `sfDisabled` greys a whole
cluster, because a cluster is one view however many boxes it holds; this greys
one box, and `TCluster` then skips it for the arrow keys *and* refuses its
hotkey (`buttonState` gates both). `tvision-node/examples/form.js` greys
"Phone" for a record with no phone number, which is the rule every form has,
and `drive_form.py` checks the arrows stepping over it in both directions.

**`columns` on a `ListBox`.** `TListViewer` has taken a column count since 1990
and nothing here passed one. It divides the list's rectangle and fills each
column downwards, which is what a list too long for its window often wants
instead of a scroll bar. Structural, because a list cannot be re-divided in
place.

**`top` on a `ListBox`**, which is the one field in the package that lets a
model put the highlight out of sight. A list's scroll bar tracks `focused` and
not `topItem`, so Turbo Vision moves the top itself and offers no way to say
it; "scroll the list" and "move the highlight" are two sentences and a model
that says only the first means only the first. Written after `focused` at both
ends — the builder and the differ — because moving the highlight scrolls the
list, so a `top` written first is a `top` undone.

**One mistake worth keeping**, because it looks exactly like the feature not
working: a caption is `~P~hone`, and matching `phone` against it finds nothing.
The first version of the check greyed no box at all and the driver was right to
fail.
