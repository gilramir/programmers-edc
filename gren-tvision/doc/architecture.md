# How a Gren program ends up on Turbo Vision

This is the technical half of the documentation: what the layers are, why
there are four of them, what it takes to reach a C++ library designed in 1994
from a language with no FFI, and why the event loop is the part that decided most of
the design. If you only want to write programs, read
[widgets.md](widgets.md) instead -- nothing here is needed to use the package.

## The four layers

```
Tui.gren                    pure Gren: types, encoders, decoders, defineProgram
   |  JSON over two ports (out: render/commands, in: events)
   v
gren-tvision (npm)          tui.js  -- reads the port, routes messages
                            diff.js -- one UI description -> calls on the binding
   |  ordinary JavaScript calls
   v
tvision-node (npm)          index.js -- the pump, in fifteen lines of JS
                            src/*.cc -- N-API addon: widgets, ids, modality
   |  C++
   v
libtvision.a                magiblot/tvision, built PIC inside devbox
```

Three published artifacts, and the split is forced rather than chosen:

| artifact | registry | contents |
|---|---|---|
| `gilramir/gren-tvision` | Gren | pure Gren: types, encoders, `defineProgram` |
| `gren-tvision` | npm | the diff layer and the `gren-tui` bin |
| `tvision-node` | npm | the native binding |

In this repository they are `gren-tvision/`, `gren-tvision-runtime/` and
`tvision-node/`; the middle directory publishes as the npm package
`gren-tvision`, which is why its name and its directory do not match.

**A Gren package may not declare ports.** The compiler refuses outright, with a
rationale about keeping the package ecosystem free of JavaScript, inherited
from Elm and not negotiable. So the package can describe a UI and cannot reach
a terminal: the *application* declares `tuiOut` and `tuiIn` and hands them to
`Tui.defineProgram` as a `Tui.Ports msg` record. That is eight lines of
boilerplate per program and there is no way around it.

The compile step matters for the same reason. `gren make Main` produces a
self-running executable with no handle to attach ports to; `gren make Main
--output=main.js` produces a CommonJS module that runs nothing and exports
`Gren.Main.init`. The runtime's `gren-tui` bin requires that module, calls
`init({flags})`, subscribes to `tuiOut` and sends on `tuiIn`. Commands issued
from `init` arrive after `init()` returns, so subscribing afterwards misses
nothing. No wrapper, no source rewriting, no kernel code.

## Reaching C++ from Gren, in general

Gren has no FFI. There is exactly one door out of a Gren program and it is a
port, which carries JSON, in one direction, asynchronously, with no return
value. Everything below follows from that sentence.

**Nothing can be asked, only told.** `tvforms`' Edit button reads
`list->focused` at the moment it is pressed. A Gren program cannot: there is no
call to make and no value to come back. So every piece of state that a C++
program would have queried had to become something the model is *told* --
`Focused` when a list highlight moves, `Changed` when the user moves a value,
`Resized` when the terminal changes size. Each of those is a protocol version,
and each replaced a query that would have been the first synchronous question
in the protocol.

**Anything that must be asked becomes two steps.** When the answer really does
have to come back -- a modal dialog, an editor's document, a search -- the
shape is a `Cmd` that produces a `Msg`, exactly like an HTTP request. In the
examples it has happened four times: `dir`'s Change Dir (list the directory,
then show it), `edit`'s Save (read the document, then write it), `entries`'
Clear (ask, then throw away), and `edit`'s Find (ask for the string, then
search). It is the same rule each time: **when a command needs
something only the model can produce, the model handles it and answers with a
`Cmd` of its own**, and a built-in command name is for the ones that need
nothing.

**Turbo Vision keeps state in objects; a Gren view is a description.** A
`TWindow` has focus, a z-order, a scroll position and a caret, none of which
appear in the model. Re-describing the UI on every update would throw all of it
away, so the description is *diffed* -- the same bargain `elm/browser` makes
with the DOM. That is what `diff.js` is, and it is why every window and every
view carries an `id`: the id is the identity that survives a render.

**Object lifetimes do not respect immutable descriptions.** Turbo Vision
destroys a window's children with it, and the user can close a window from its
frame without telling anybody. `JsWindow::~JsWindow` is the one place that
catches every path, and it drops the window and every id in it; `exists()` is
an ordinary thing to call rather than a paranoid one. The first version
dispatched the close notification *from* the destructor, which handed
JavaScript a half-destroyed window that the declarative layer promptly closed a
second time. Notifications are queued and drained at a safe point now, and that
fix broke its own suppression flag in an instructive way -- a synchronous flag
is useless for an asynchronous notification, so `diff.js` keeps a set of ids it
closed itself.

**The C++ side has its own constraints, and they leak into the design.**

  - `TProgInit` calls `initMenuBar` and `initStatusLine` from inside the
    `TApplication` constructor, and they are static functions with no user-data
    channel, so the description has to be parked in a global before the app is
    constructed. That, plus `TProgram::application`, `deskTop`, `menuBar` and
    `statusLine` all being statics, means **one application per process**. It
    is the shape of the library, not of the binding.
  - `napi.h` must be included before `<tvision/tv.h>`: the Borland
    compatibility headers define `Boolean`, `True`, `False` and a pile of
    macros that V8's headers do not enjoy meeting.
  - node-gyp compiles with `-fno-rtti`, so there is no `dynamic_cast` to
    recover a `JsMenuBar` from `TProgram::menuBar`. The binding keeps its own
    pointers to what it built.
  - `libtvision.a` has to be PIC, because a `.node` is a shared object -- and
    it has to be built by the *same* toolchain that will load it. Inside
    devbox everything is nix, and a static archive built by the system g++ is
    unusable there. This is also why `devbox run` is not optional.
  - Commands are strings on the Gren side and `ushort`s in Turbo Vision.
    `TView::commandEnabled` returns true unconditionally for any command above
    255, so **a command above 255 can never be greyed out**; user commands are
    interned from 110 upwards and only spill into the always-enabled range
    when 255 is used up.
  - It is manual memory management against a library from 1994, so there is an
    AddressSanitizer build (`devbox run test:asan`) and it has earned its keep
    twice -- once on a one-byte overrun in the binding's own input-line setup
    that aborted minutes later in an unrelated free, and once on an
    alloc/dealloc mismatch in the library itself.

**Four places have to agree, and no compiler checks three of them.** Adding a
view type means editing a Gren union, a Gren encoder, the JavaScript patcher
and the C++ builder. Miss one and nothing complains: the widget silently does
not appear, or appears and silently stops updating.
`tools/check_consistency.py` walks all four, plus the event names in both
directions, the callback names the runtime hands the binding, the built-in
command list, and the protocol version on both sides of the port. It is the
only thing that can. The callback check earned its place immediately --
`onFocussed` where `onFocus` was meant is valid JavaScript, is accepted by the
addon, and simply never fires.

**And the two halves version independently.** A Gren package and an npm package
are published separately and *will* skew, so every render message carries a
`protocol` integer that the runtime refuses if it does not recognise it. The
failure without that check is a UI that renders nothing, or -- worse -- one
that renders and quietly stops patching, which is what a new field looks like
to an older runtime.

## The event loop, and why the pump exists

This is the part that shaped everything else.

`TApplication::run()` is a blocking loop around `getEvent`. Under it Node's
event loop never runs: no timers, no promises, no I/O, no ports. A Gren program
under `run()` could not receive its own `Cmd`s, so a dialog would never resolve
and the first `await` would deadlock. Turbo Vision has to become a **guest**
inside Node's loop rather than the host.

Three facts, checked in the tvision source before a line was written, make that
possible:

  - `TProgram::eventTimeoutMs` is a public static. At `0`, `getEvent` stops
    blocking.
  - `TGroup::execute()` is four lines, and `TGroup::endState` is public, so one
    iteration of it can be hoisted out into the binding.
  - `THardwareInfo::waitForEvents` flushes the screen *before* polling, and
    that is on the path even at timeout 0 -- so the display still repaints.

So `tv.run()` is gone and `tv.start()` + `tv.step()` replaced it. `step()` is
one turn of the application's own loop, exported to JavaScript; the pump is
fifteen lines in `tvision-node/index.js`:

```js
const tick = () => {
  const handled = addon.step();
  if (handled < 0) return;              // quit; the terminal is already back
  if (handled > 0) setImmediate(tick);  // busy: a paste, a held-down key
  else setTimeout(tick, IDLE_MS);       // quiet: 8ms, cheaper than it sounds
};
```

`step()` drains up to 64 events per call rather than one, or input would be
rationed at the timer's rate. Node stays completely alive throughout: a clock
is a `Time.every` subscription, a directory listing is a `Task`, and
`FileSystem.watchRecursive` is a `Sub` that delivers inotify events next to the
keyboard's on equal terms. That last one is the whole argument for the binding
-- a Turbo Vision program has exactly one source of events and it is the user.

### Safe points

Callbacks into JavaScript cannot be made from anywhere. A callback can render,
and a render can close a window, and closing a window from inside the
`handleEvent` that is currently using it frees it under Turbo Vision's feet.
So notifications are *queued* in C++ and drained by the pump between events,
where nothing is mid-destruction:

| queue | drained | why there |
|---|---|---|
| focus notes | after each event | a highlight move can rebuild the list it moved in |
| scroll notes | after each event | a drag reports where it ended, not every pixel |
| closed windows | after each event | the notification used to come from a destructor |
| resize | after each event, and once per pump | polled by comparing `deskTop->size`, because Turbo Vision learns about a resize in three different places and they all end here |
| value changes | once per pump | a burst of keystrokes is one render, and the model wants the word rather than each letter |
| editor edits | once per pump | same rule: typing a word is one `Edited` event |

The differ has the same hazard from the other end -- a render can arrive while
one is being applied -- and answers it the same way: `apply` sets a flag,
stashes the newest render, and loops rather than recursing.

### Modality without the nested loop

`TGroup::execView` is twenty lines, of which exactly one is a problem:

```c++
saveOptions/saveOwner/saveTopView/saveCurrent/saveCommands...
TheTopView = p;  p->setState(sfModal, True);  setCurrent(p, enterSelect);
ushort retval = p->execute();          // <- the nested loop
...restore all of it...
```

**Modality in Turbo Vision is state, plus a loop.** The state is `sfModal`, the
global `TheTopView`, and some current-view and command-set bookkeeping. The
loop is the part the pump already knows how to replace. So `beginModal()` does
everything up to `p->execute()`, `finishModal()` does everything after it, and
the pump drives the dialog's events in between, keeping a stack so a dialog
opened from a dialog is ordinary. **No fork of tvision was needed.**

Three things had to be true and all three were: `TheTopView` is a plain global
with external linkage (declared in no header -- one `extern` line and it is
ours); it is read in exactly two places and by no drawing code, which is what
lets a window behind a modal dialog keep repainting; and `TWindow::handleEvent`
turns `cmClose` into `cmCancel` when `sfModal` is set, so closing a modal
window with the mouse never destroys the view under the session that owns it.

**Modal here means "input goes to this view and nowhere else". It does not mean
the process stops.** The clock behind a dialog keeps ticking, subscriptions
keep firing, and `tv.dialog()` returns a Promise -- which is exactly the shape
Gren needs, a `Cmd` that produces a `Msg`.

The modal stack gained a second way in later. `THistory::handleEvent` calls
`owner->execView` to put its drop-down over the field, so `openLocalModal`
pushes a view onto the same stack with a C++ continuation instead of a promise.
The context menu uses it too. Both would otherwise have re-introduced the
nested loop through the side door -- which is also why `messageBox` is built in
JavaScript and in Gren rather than called from `::messageBox()`, and why
`TEditor`'s `editorDialog` hook is left inert.

### The one nested loop that is still there

`TMenuView::execute()` is two hundred lines around a `getEvent` at the top of a
`do...while`, reached from `TMenuBar::handleEvent`. So **while a pull-down menu
is open, the whole program is stopped**: no timers, no subscriptions, no
renders. Measured with `entries`, whose clock is a `Time.every`: 1 -> 5 ticks
in three and a half seconds normally, 5 -> 5 with a pull-down open, moving
again the moment `Esc` is pressed. Nothing is lost -- the timers fire when the
menu closes -- and a menu is open for about a second at a time, which is why it
has never been in the way.

It is not fixed, deliberately. Undoing it means reimplementing `execute` as a
state machine the pump can step -- five flags carried across iterations and a
recursive `execView` in the middle, in the least documented code in the library
-- to buy back a one-second freeze. What was done instead is that nothing new
was built on top of it: the history drop-down and the context menu both avoid
it, and **a context menu is flat** because a submenu *is* the recursive
`execView` in the middle of that loop.

## What actually crosses the port

Out of Gren, as JSON on `tuiOut`:

| message | from | what it does |
|---|---|---|
| `render` | every update | the whole `Ui`, plus the protocol version |
| `dialog` | `Tui.dialog` | opens a modal; answered by `dialogClosed` |
| `popupMenu` | `Tui.popupMenu` | a context menu at a point in a view |
| `focus` | `Tui.focus` | the only message that names one view |
| `setEnabled` | `Tui.setEnabled` | greys a command everywhere it appears |
| `setEditorText` / `readEditor` | the editor | the only pair that carries a document |
| `searchEditor` | find/replace | answered by `searched` |
| `doubleClickDelay` | `Tui.setDoubleClickDelay` | in PC timer ticks, 1/18.2s |
| `quit` | `Tui.quit` | restores the terminal and exits |

Back into Gren on `tuiIn`: `command`, `select`, `focus`, `key`, `click`,
`scroll`, `resized`, `changed`, `edited`, `editorText`, `searched`,
`dialogClosed`, `windowClosed`. `Tui.Event` is that list, decoded, with
`Unknown` for anything a future runtime sends that this package does not know.

A `render` is the entire description every time. Working out what changed is
the runtime's job, so a `view` that rebuilds its whole `Ui` on every call costs
nothing beyond the JSON.

## The diff, and the rules in it

`diff.js` holds everything stateful about rendering, and takes the binding as
an argument so it can be tested against a fake one.

**Structural versus mutable.** A view's `id`, `type` and `rect`, and a button's
command, are structural: change one and the window is closed and rebuilt,
losing focus, z-order, scroll position and list highlight. A short list of
fields per view type is mutable and patched in place -- a static text's `text`,
an input line's `value`, a list box's `items` and `focused`, a canvas's `lines`
and `cursorAt`, a cluster's value, a scroll bar's range. A window's *title* and
*rectangle* are both patched, the second because rebuilding a window to move it
also skips `TGroup::changeBounds`, which is the only thing that resolves a
child view's `growMode`.

**Descriptions are compared against descriptions, never against the screen.**
The user types into a field and the model does not know. If the differ compared
the model's value with what is on screen it would write the model back on every
render and eat the keystrokes. It compares the *previous description* with the
*next* one instead, so a control is only ever written when the model actually
changed it. This is the controlled-input problem every virtual DOM has and it
is not optional -- `setValue` on an input line ends in `selectAll()`, so
getting it wrong turns the field the user is typing in into a selected block
that their next keystroke replaces.

**`valueChanged` closes the loop.** When the user moves a value, the binding
reports it and the differ records it in the description it is diffing against
-- *before* the model is told. A model that stores what it was told and renders
it straight back then writes nothing, which is the point of being told.

**A rebuilt list forgets its highlight.** `setItems` puts a list box's
highlight back on row zero, so `focused` is re-sent whenever the items changed
and not only when `focused` changed -- and the binding does not report the
intermediate zero it has to pass through. Leaving either half out is how a tree
collapses itself the moment you expand a branch.

## Testing, at three levels

"How do you unit-test a TUI?" has a better answer than it looks, because most
of what can break is not the terminal.

  - **`node --test` against a fake binding** (`gren-tvision-runtime/test/`).
    Every bug the diff layer has ever had -- a window rebuilt because its title
    changed, a self-inflicted close reported as the user's, an input line
    overwritten while somebody was typing in it -- is a pure-logic bug that a
    fake binding catches in milliseconds and a terminal catches by accident.
  - **`gren-lang/test`** (`gren-tvision/tests/`) for the package's pure logic.
    Narrow on purpose: most of `Tui` is types and encoders whose only real
    assertion is "the runtime understood it".
  - **pty drivers** (`gren-tvision/test/drive_*.py`) for everything that needs
    a terminal. Slow, and the only honest test of a TUI.

The pty harness keeps an 80x25 grid and replays the output stream through a
small terminal emulator, because **Turbo Vision repaints only the cells that
changed**: a counter going from 11 to 12 emits a cursor move and two digits,
and grepping the raw stream still sees `ticks: 1`. It also reads colour, which
is the only way to assert on a canvas that says what it means with a hue.

Every example is a driver, and there is no list to add one to:
`tools/run_tests.py` treats every `test/drive*.py` as a suite. They are almost
entirely asleep -- typing at a pty and waiting for a repaint -- so they run
several at a time.

## Running it

```sh
devbox run check      # consistency, docs, unit tests. No terminal, ~5s
devbox run test       # the above plus every pty driver, ~35s
devbox run test:asan  # the same drivers under AddressSanitizer, ~1m
devbox run gren -- <example> [args]
```

`gren` and node are not on `PATH` outside devbox, and the addon must be
compiled by the toolchain that will load it. For an application of your own,
the whole build is:

```sh
gren make Main --output=main.js && gren-tui main.js
```
