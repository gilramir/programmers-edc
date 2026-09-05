# Findings

Running notes on what actually turned out to be true. Line references are into
the `tvision/` checkout.

## Milestone 0 — the toolchain question

The question was whether a `.node` compiled by the **system** toolchain
(Ubuntu g++ 13 / glibc 2.39) could be loaded by devbox's **nix** node 22, since
mixing two glibcs in one process is the kind of thing that works right up until
it doesn't.

The question dissolved: **devbox puts a nix `gcc-wrapper` on `PATH`** (pulled in
with the nodejs package), and that wrapper does not search `/usr/include` at
all. The first build failed on `#include <curses.h>` even though
`/usr/include/curses.h` exists. So inside devbox everything is nix — gcc 15.3.0,
glibc 2.42, nix ncurses — and the resulting `.node` has nix store paths baked
into its RPATH:

```
libncursesw.so.6 => /nix/store/...-ncurses-6.6/lib/libncursesw.so.6
libstdc++.so.6   => /nix/store/...-gcc-15.3.0-lib/lib/libstdc++.so.6
libc.so.6        => /nix/store/...-glibc-2.42-67/lib/libc.so.6
```

Consequences, both of which milestone 1 depends on:

- **`libtvision.a` has to be built inside devbox too.** Static archives cannot be
  mixed across toolchains, so `tvision/build/` (built earlier with system g++) is
  unusable here. `tvision-node/scripts/build-tvision.sh` builds a fresh one.
- **nix packages split their headers into a `dev` output** that devbox does not
  install by default. `ncurses` needs the object form in `devbox.json`:
  ```json
  "ncurses": { "version": "latest", "outputs": ["out", "dev"] }
  ```
  With `pkg-config` alongside it, `binding.gyp` can just ask for
  `pkg-config --cflags/--libs ncursesw` and stay portable.

Also: node-gyp never downloaded any headers — it found them in the nix node
package. Nice side effect; the build works offline.

## Milestone 1 — the binding

### What had to be true, and was

- **`libtvision.a` must be PIC.** A non-PIC archive cannot go into a shared
  object, and a `.node` is a shared object.
  `-DCMAKE_POSITION_INDEPENDENT_CODE=ON`.
- **tvision builds clean under gcc 15.3.0**, PIC, examples off, GPM off, in
  about two minutes. No patches -- which stayed true until 2026-09-04 and the
  wide-character bug at the end of this file. `tvision/` is now a submodule of
  a fork, gilramir/tvision, pinned to its `patches` branch: upstream master
  plus the unlanded fixes, one commit each. See README.
- **`napi.h` must be included before `<tvision/tv.h>`.** The Borland
  compatibility headers define `Boolean`, `True`, `False` and a pile of macros;
  V8's headers do not enjoy meeting them.
- **`NODE_API_MODULE` cannot take a namespace-qualified function.** It pastes the
  name into an identifier, so `tvnode::Init` becomes `__napi_tvnode`. A global
  one-line wrapper fixes it.

### The design point nobody warns you about

`TProgInit` calls `initMenuBar` and `initStatusLine` **from inside the
`TApplication` constructor**, and they are plain static functions with no
user-data parameter. So a JS-supplied UI description has to be parked in a
global *before* the app is constructed. That, plus `TProgram::application`,
`deskTop`, `menuBar` and `statusLine` all being statics, means **one application
per process, permanently**. It is not a limitation of the binding; it is the
shape of the library.

### `TDialog` will not close on your own commands

`TDialog::handleEvent` ends a modal dialog only for `cmOK`, `cmCancel`, `cmYes`
and `cmNo` (`source/tvision/tdialog.cpp:77-90`). Give a button any other
command and pressing it does nothing at all.

This is why `hello.cpp` gives all four greeting buttons `cmCancel` — the
original could not tell them apart either, and threw the answer away. Since the
JS API promises to report *which* button was pressed, `JsDialog` overrides
`handleEvent` to `endModal` on any command in our user range. That is the
standard Turbo Vision idiom, but it is invisible until you hit it.

Related, and the reason a test caught this at all: **`Enter` does not press the
focused button.** It broadcasts `cmDefault`, which only a `bfDefault` button
answers. `Space` presses the focused one. The first version of the pty test
"passed" because `Esc` was closing the dialog with `cancel` a beat later, which
looked like a working round trip and was not.

### Testing a TUI

`test/drive.py` forks a pty, fixes it at 80x25, types at the app and strips ANSI
back out of the output to run substring checks on what was drawn. The checks
that matter are the ones on the log file: `command: greet` and
`answer: terrific` together prove the whole path — menu → C++ → JS → dialog
(C++) → button → JS → `messageBox` (C++, nested inside the JS callback that
itself came from C++) → JS.

The addon refuses to start when stdin/stdout are not a terminal, rather than
scribbling escape codes into a pipe.

## Milestone 2 — the pump

`tv.run()` is still there and still blocks. `tv.start()` + `tv.step()` is the
pumped form, and everything predicted about it held:

- `TProgram::eventTimeoutMs = 0` makes `getEvent` non-blocking.
- One iteration of `TGroup::execute()` transplants cleanly, outer
  `valid(endState)` loop included, because `endState` is public.
- The display still repaints, because `THardwareInfo::waitForEvents` flushes
  *before* polling and that is on the path even at timeout 0.

The pump itself lives in `index.js`, in about fifteen lines: call `step()`, and
if it handled anything come straight back via `setImmediate`, otherwise
`setTimeout(…, 8)`. Busy under a paste or a held-down key, nearly free when
idle. `step()` drains up to 64 events per call rather than one, or input would
be rationed at the timer's rate.

Node stays completely alive: the demo's clock is a plain `setInterval`, and its
directory listing is `await fs.readdir()` writing back into a window. The test
asserts both by watching the screen change on its own.

### Modal dialogs froze Node (fixed -- see "Modality without the loop")

`execView` starts a *nested* `TGroup::execute()` inside TVision, which the pump
knows nothing about. Open the demo's `File > Go to` and the clock stops dead
until you dismiss it.

This is asserted rather than hidden — `drive_demo.py` checks that the tick
counter does *not* move while the dialog is up, and does move again afterwards.
If milestone 3 makes dialogs non-modal, that check fails loudly and tells the
next person the constraint is gone.

### Modality without the loop

`TGroup::execView` (`tgroup.cpp:193-215`) is twenty lines, of which exactly one
is a problem:

```c++
saveOptions/saveOwner/saveTopView/saveCurrent/saveCommands…
TheTopView = p;  p->setState(sfModal, True);  setCurrent(p, enterSelect);
ushort retval = p->execute();          // ← the nested loop
…restore all of it…
```

**Modality in Turbo Vision is state, plus a loop.** The state is `sfModal`, the
global `TheTopView`, and some current-view and command-set bookkeeping. The
loop is the part we already know how to replace -- `step()` replaced the
application's one in milestone 2.

So `beginModal()` does everything up to `p->execute()`, `finishModal()` does
everything after it, and the pump drives the dialog's events in between,
keeping a stack so a dialog opened from a dialog is ordinary. Input goes only
to the top modal view -- that is what modal means -- and Node's loop never
stops. **No fork of tvision was needed.**

Three things had to be true, and all three were:

- **`TheTopView` is reachable.** It is a plain global with external linkage
  (`TView *TheTopView = 0;` in `tgroup.cpp`), declared in no header. One
  `extern` line and it is ours.
- **It does not affect drawing.** It is read in exactly two places --
  `TView::endModal` and the status line's command enabling -- and by no drawing
  code. That is what lets a window behind a modal dialog keep repainting, which
  is the whole point: the clock ticks behind the dialog.
- **Closing a modal window with the mouse is safe.** `TWindow::handleEvent`
  turns `cmClose` into `cmCancel` when `sfModal` is set rather than calling
  `close()`, so the view is never destroyed underneath the session that owns
  it.

Consequences for the API, both good:

- **`tv.dialog()` returns a Promise** of `{cmd, values}`. `await` reads better
  than the synchronous version did, and it is exactly the shape Gren needs: a
  `Cmd` that produces a `Msg`.
- **The blocking `tv.run()` is gone.** Under it Node's loop never ran, so a
  promise could never settle and every dialog would deadlock. `examples/hello.js`
  moved to the pump and awaits its dialogs. `tv.messageBox()` moved to
  JavaScript too, because TVision's `::messageBox()` calls `execView` and would
  have dragged the nested loop back in through the side door.

Two smaller things the change turned up: `tv.quit()` has to be *deferred* to
the pump rather than acted on immediately, because it can be called from a list
box's `onSelect`, which runs inside the dialog's own `handleEvent` -- tearing
the dialog down there would free it under TVision's feet. And `{onSelect:
undefined}` is ordinary JavaScript, so the config parser now treats an
undefined callback as an absent one instead of a type error.

### The ASAN build could not run the other tests

An addon linked with `-fsanitize=address` cannot be `dlopen`'d into a plain
node: *"ASan runtime does not come first in initial library list"*. The
regression driver knew to preload the runtime; the other two did not, so under
`TVNODE_ASAN=1` they failed every check at once and looked like an application
that could not start. All three drivers now go through `harness.node_argv()`,
which adds the wrapper when `TVNODE_ASAN=1` is set.

Related, and the same shape as the earlier gyp mistake: `devbox` runs every
line of a script in the *same* shell, so a second `cd tvision-node` fails. Each
line is its own subshell now.

### Ids, and the dangling pointer they invite

Views are addressable by string id (`setText`, `setItems`, `getValue`,
`setValue`, `focus`, `close`, `exists`) because milestone 3 needs to patch a
tree in place. The hazard is obvious in hindsight: TVision destroys a window's
children along with it, and the user can close a window from its frame without
telling anyone. `JsWindow::~JsWindow` is the single place that catches every
one of those paths, and it drops the window and every id inside it. `exists()`
is therefore a normal thing to call, not a paranoid one — an `await` is more
than long enough for a window to disappear.

### Two bugs worth remembering

**A `std::initializer_list` returned from a lambda is a dangling pointer.** The
first version of the dispatch helper built its arguments in a lambda returning
`std::initializer_list<napi_value>`; the backing array dies at the return, and
the addon segfaulted the moment a menu item was chosen. The tests caught it
immediately; a `std::vector` fixed it.

**A handle scope per dispatch is not optional under `run()`.** Because the
blocking form never returns to Node, every string handed to a JS callback would
otherwise accumulate for the entire life of the application. `Napi::HandleScope`
in the dispatch functions bounds it.

### The crash: one byte, ten minutes later

Reported from a real session: clock open, modal dialog open for a while, closed
it with the mouse, `free(): invalid size`, core dumped.

It was ours, in the input line setup:

```
TInputLine(bounds, limit)  ->  maxLen = limit - 1,  data = new char[maxLen + 1]
```

The constructor takes a *limit* but stores `maxLen = limit - 1`, so the last
writable index is the object's own `maxLen`, not the limit you passed in.
Writing the terminator at `data[limit]` runs one byte past the block, quietly
corrupts the next chunk's header, and aborts whenever that chunk is next freed
-- which is when the dialog is destroyed, minutes and several interactions
later. It looks like a TVision bug and is not.

The same function used `input->maxLen` in one place and the local `maxLen` in
another; only the second was wrong. Both callers now go through one
`setInputText()` helper so the off-by-one cannot come back.

### AddressSanitizer, and a test that passed for the wrong reason

This addon does manual memory management against a library from 1994, so the
crash bought an ASAN build: `TVNODE_ASAN=1 npx node-gyp rebuild`, then
`test/asan.sh` preloads the runtime and `test/drive_regress.py` opens and closes
input-line dialogs under it.

Two things about it are worth writing down.

**The first version of that build did nothing at all.** `binding.gyp` had a
`condition` on `asan==1`, but gyp `-D` values are strings, `"1" == 1` is false
in Python, and `node-gyp rebuild -- -Dasan=1` does not forward to gyp anyway. So
the addon was built without instrumentation, the regression test reported
"no AddressSanitizer report", and it was green while the bug was still in the
tree -- twice. `nm -D build/Release/tvision.node | grep -c __asan` returning 0
is what gave it away. The flags now come from `scripts/asan-flags.sh`, which
either prints them or does not.

**ASAN's report was being shredded by the terminal.** It goes to stderr, which
here is a pty that TVision has in raw mode and is actively repainting; the
report came out as confetti and the check could not find it. `ASAN_OPTIONS`
now sets `log_path=build/asan`, so a report is a *file*, and the check is
`glob()`. With the bug put back, it points straight at `views.cc:138`.

Both failure modes have the same shape, and it is the shape to watch for in
this project: a check that cannot fail is worse than no check.

### `Enter` is not the key you think it is, twice

`TListViewer` selects on **Space**, not Enter (`tlstview.cpp`) — Enter is not in
its key switch at all. Exactly the same shape as the `TButton` surprise from
milestone 1. In Turbo Vision, Enter means "the default action of this dialog",
never "activate what is focused".

### Testing needed a terminal emulator

The pty harness originally grepped the whole output stream for text. That works
for "did this window ever appear" and is useless for "what does this counter say
now", because **TVision repaints only the cells that changed** — a counter going
from 11 to 12 emits a cursor move and two digits, and a naive scrape still sees
`ticks: 1`. Worse, it produces convincing lies: unchanged spaces are skipped, so
`10 entries, read while the UI ran` arrives as `10 entries,readwhiletheUIran`.

`test/harness.py` now keeps an 80x25 grid and replays the stream through a
small emulator (cursor addressing, relative moves, erases; escape sequences
parsed just well enough to skip). `app.screen()` is history, `app.render()` is
the screen. The checks that matter use `render()`.

## Porting more of the C++ demos

The point of porting `tvdemo`'s ASCII chart and something in the shape of
`tvforms` was to find corner cases before Gren, not to have more demos. It
worked; here they are.

### Commands above 255 can never be disabled

```c++
Boolean TView::commandEnabled( ushort command ) noexcept
{
    return Boolean((command > 255) || curCommandSet.has(command));
}
```

User commands were being allocated from 1000, so `tv.setEnabled(cmd, false)`
was a silent no-op -- the menu item stayed live and still fired. Turbo Vision
reserves 0-99 for itself and 100-255 for the application, and `cmFileFocused`
(102) is the only constant it defines in the upper half. User commands now
start at **110** and only spill into 1000+ once 255 is exhausted, where the
restriction returns.

The test for this had to be behavioural: greying a menu item is a *colour*
change, and colour is exactly what the pty harness strips. What it checks is
that a disabled command does not fire.

### `operator+` decides whether a submenu nests or not

```c++
*sub + *nested;                              // sibling: a new top-level menu
*sub + *static_cast<TMenuItem *>(nested);    // child: a submenu, as intended
```

`operator+(TSubMenu&, TSubMenu&)` appends to the *sibling* chain;
`operator+(TSubMenu&, TMenuItem&)` inserts into the submenu. A `TSubMenu` is a
`TMenuItem`, so both compile, and the first one quietly turned "Samples" and
"More" into extra entries on the menu bar. The cast is load-bearing.

### Hotkeys are one flat namespace, and the status line wins

Two things collided in the form demo:

- **Inside a dialog**, the first control that claims `Alt-<letter>` gets it.
  A `~P~hone` label and a `~P~hone` radio button meant the radio took Alt-P and
  the field was unreachable.
- **The status line's hotkeys are global** and beat even a modal dialog:
  `TProgram::getEvent` hands every `evKeyDown` to the status line *before* the
  event reaches the modal view. The demo's status line offered `Alt-N` for
  "New", so a `~N~ame` field in a dialog could never be focused by its own
  label.

Neither is a bug -- it is how Turbo Vision works -- but both are invisible
until something silently does nothing.

### `Enter` is not the key you think it is, three times now

`TButton` (milestone 1), `TListViewer` (milestone 2), and now `TCluster`: check
boxes and radio buttons are toggled with **Space**, and Enter means "the
dialog's default action" everywhere. The pattern is consistent once you see it;
it just is not what a person raised on other toolkits will type first.

### magiblot's TVision draws Unicode, so an ASCII chart is not an ASCII chart

The C++ `TTable::draw` writes raw code page 437 cells, so the original shows
all 256 glyphs, dingbats included. A canvas takes a JS string, which is
Unicode: `String.fromCharCode(n)` gives C1 control characters for 128-159 and
they come out as replacement characters. `examples/ascii.js` carries a CP437
table to get the original's alphabet back, and writing it is the demonstration
-- what a canvas paints is whatever JS decides, down to the character.

### The canvas, and what it means for Gren

`TCalendarView` and `TTable` are plain `TView` subclasses with their own
`draw()`; nothing in the stock widget set can express them, and until now
nothing in the binding could either. `JsCanvas` is the hole filled: JS supplies
the lines, TVision paints them, keystrokes arrive back in JS *by name*
(`"Left"`, `"Alt-X"`, `"A"`), and the model -- which character is selected --
lives in a JS variable.

That round trip is the one milestone 3 needs for anything Gren renders itself.
It is also the only widget so far with no TVision-side state to keep in sync,
which makes it the easiest thing for a diff layer to drive.

Smaller things from the same pass: `TCluster` keeps its state in a protected
`value` (a bitmask for check boxes, an index for radio buttons), so a subclass
beats `getData`/`setData` with a raw byte buffer; text wider than its rect is
**silently truncated** by both `TStaticText` and the canvas, which cost two
rounds of confused test failures; and interning an empty command name was
handing out a real user command, so a status line hint with no `cmd` would have
delivered stray `onCommand('')` calls.

## Milestone 3 — Gren

It works. `gren-tvision/src/Main.gren` is a Turbo Vision application written in
Gren: a model, a `view : Model -> Ui`, and an `update`. Nothing in it knows
that C++ exists.

```
Gren (pure)                        tui.js                      the binding
  view : Model -> Ui   --JSON-->   diff vs last render  ---->   tv.window / setText / …
  update : Msg -> …    <--JSON--   events               <----   onCommand / onKey / onClose
```

### Correction: ports need no hack at all

The earlier note here said a Gren node program self-initializes and throws away
the handle, so reaching its ports would need a wrapper that strips the last
line. That was read off `gren-format/app`, which is the **executable** output
form. It is not the only one:

```
gren make Main                  → shebang + `this.Gren.Main.init({})`, runs itself
gren make Main --output=main.js → a plain CommonJS module, runs nothing
```

The second exports `Gren.Main.init`, and

```js
const app = require('./main.js').Gren.Main.init({});
app.ports.tuiOut.subscribe(…);
app.ports.tuiIn.send(…);
```

is all there is to it. Commands sent from `init` arrive after `init()` returns,
so subscribing afterwards does not miss them. No wrapper, no stripping, no
kernel code.

### The menu bar is configuration, not view *(wrong -- see below)*

`TProgInit` calls `initMenuBar` and `initStatusLine` from inside the
`TApplication` constructor, so they exist before there is a first model to
render. The conclusion drawn from that -- that they therefore cannot change --
was wrong, and porting `mmenu` is what found it.

### Turbo Vision focuses the last view; a list wants the first

`insert()` prepends, so the first view in z-order -- the *last* one written --
takes focus. In a declarative list written top to bottom that is the Cancel
button, so a dialog opened with the caret nowhere near the field the user was
about to type into. The first Gren dialog silently swallowed everything typed
into it.

The binding now focuses the first focusable view in declaration order, with
`focus: "<id>"` to override. It is a deliberate divergence: an artifact of
insertion order is not something a declarative API should inherit.

### A window title has to be mutable

`Entries (3)` becoming `Entries (4)` is an ordinary model change, and the first
diff treated the title as structural: close the window, build a new one. That
loses focus, z-order and scroll position on every update -- precisely what a
diff layer exists to prevent. `tv.setTitle` patches it in place, and the title
came out of the shape comparison.

### Notifying from a destructor hands JavaScript a corpse

`onClose` was dispatched from `~JsWindow`, which runs deep inside TVision --
from `TWindow::close()`, from the desktop's own destructor. At that moment the
window is half gone but its id still resolves, so the declarative layer,
reacting to "this window closed", called `close()` on it a second time and the
process aborted.

Closes are now *queued* and drained by the pump between events, where nothing
is mid-destruction.

That fix immediately broke its own suppression, in an instructive way. The glue
sets a flag while it deliberately closes a window, so it can ignore the
resulting notification instead of telling Gren the user did it. A synchronous
flag works for a synchronous callback and is useless for a queued one -- the
notification now arrives after the flag is cleared. It is a per-id set now.

### An input line's value is compared against the model, never the screen

The user types into a field; the model does not know. If the diff compared the
model's value with what is on screen it would write the model back on every
render and eat their keystrokes. It compares the *previous description* with
the *next description* instead, so an input line is only ever written when the
model actually changed it. This is the same trick controlled inputs use in Elm
and React, and it is not optional.

### Smaller things

The first click on an inactive window is spent activating it, so a test that
clicks a list row and expects that row to be focused is wrong about half the
time. Window rectangles are **desktop** coordinates -- y=0 is the row under the
menu bar, not the top of the screen -- which matters as soon as you are aiming
a mouse click at a close box.

### Porting mmenu: the menu bar *is* part of the view

`tvision/examples/mmenu` is not about nested menus. It exists to demonstrate a
menu bar that changes while the program runs, which this project had documented
as impossible.

It is not impossible. `TMenuView` keeps its `TMenu` in a protected member and
`TStatusLine` keeps its `TStatusDef` chain the same way, so a subclass can
replace either and redraw. Borland's `TMultiMenu` does exactly that: an array
of menus, a broadcast command `cmMMChangeMenu`, and

```c++
menu = mList[event.message.infoInt];
drawView();
```

The constructor is only where a menu bar *starts*.

So `menuBar` and `statusLine` moved out of the program's configuration and into
`Ui`, where they are diffed like everything else. The C++ original spends 124
lines across three files on the mechanism; the Gren version is

```gren
menuBar = menuBarFor model.current
```

Two smaller things came with it:

- **A menu bar entry does not have to be a pull-down.** The original puts a
  plain "Next menu" command directly on the bar. The API could not express
  that, so `Menu` went away and the menu bar became an `Array MenuItem`: an
  entry with entries of its own is a pull-down, one without is a command. That
  is both more faithful and less to explain.
- **`-fno-rtti`.** node-gyp compiles without RTTI, so there is no
  `dynamic_cast` to recover a `JsMenuBar` from `TProgram::menuBar`. Keeping our
  own pointer to what we built is cheaper than turning RTTI on.

Replacing the status line needs one further trick: `TStatusLine::update()`
refreshes its items only when the help context has changed, and ours never
changes. Setting `helpCtx` to a value nothing uses before calling `update()`
forces the refresh.

### Packaging: the split is forced, not chosen

Preparing for a release turned up a hard constraint. **A Gren package may not
declare ports** -- the compiler refuses outright:

```
-- PACKAGES CANNOT HAVE PORTS --
Packages cannot declare any ports, so I am getting stuck here:
1| port module Tui exposing (send)
```

with a long rationale about keeping the package ecosystem free of JavaScript.
Inherited from Elm, and not negotiable. So the library is three artifacts:

| artifact | registry | contents |
|---|---|---|
| `gilramir/gren-tvision` | Gren | pure Gren: types, encoders, `defineProgram` |
| `gren-tvision` | npm | the diff layer and the `gren-tui` bin |
| `tvision-node` | npm | the native binding |

The package takes the ports as an argument -- a `Tui.Ports msg` record of the
two functions -- and every application declares them itself. That is eight
lines of boilerplate per program and there is no way around it.

Two smaller things fell out of the same work:

- An example inside the package repo builds against the working copy with
  `"source-directories": ["src", "../../src"]`. Gren has no path dependencies,
  and this is the way round it.
- The render message carries a `protocol` integer that the runtime checks. A
  Gren package and an npm package version independently and *will* skew; the
  failure without a check is a UI that renders nothing, which is a miserable
  thing to debug.

### The native side needs no cmake

`tvision` has no CMake-generated config header -- `config.h` is a checked-in
source file and there is no `configure_file` anywhere -- and its `CMakeLists`
globs `source/*/*.cpp` with no platform filtering, because the Windows-only
files guard themselves. So `binding.gyp` can compile all 206 of them directly,
which was verified: full suite green, one 1.3 MB `.node`, no cmake anywhere.

That matters for distribution. It reduces a source install to a C++ compiler
and ncurses headers, and with `prebuildify` + `node-gyp-build` most users get a
binary and compile nothing. Because the addon is N-API, one prebuild per
platform covers every Node version -- which is the whole reason for having used
N-API rather than V8 directly.

### Testing a TUI at three levels

"How do you unit-test a TUI?" has a better answer than it looks, because most
of what can break is not the terminal:

- **`node --test`, against a fake binding** (`gren-tvision-runtime/test/`).
  Pulling the diff into its own module and passing the binding in as an
  argument made every bug this layer has ever had into a millisecond-long unit
  test: a window rebuilt because its title changed, a self-inflicted close
  reported as the user's, an input line overwritten while someone was typing in
  it. Eleven tests, 50ms, no terminal.
- **`gren-lang/test` via `gilramir/gren-unit-node`** (`gren-tvision/tests/`) for
  the package's own pure logic. Narrow on purpose: most of `Tui` is types and
  encoders whose only real assertion is "the runtime understood it".
- **pty drivers** for everything that needs a terminal. Slow, and the only
  honest test of a TUI.

The middle one turned up the two-output-forms lesson again: `gren make Main
--output=app.js` gives a module that runs nothing, so the test runner exited 0
in silence. A test runner wants `gren make Main`; the examples want the `.js`
form.

### A checker for the things no compiler checks

Adding a view type means editing four things in three languages: a Gren union,
a Gren encoder, a JavaScript patcher and a C++ builder. Miss one and nothing
complains -- the widget silently does not appear, or appears and then never
updates.

`tools/check_consistency.py` walks all four and compares them, plus the event
names in both directions, the callback names the runtime hands the binding, and
the protocol version on both sides of the port. It prints a table:

```
view type    Gren   encoder   patcher   binding
button         ok     ok        --        ok
canvas         ok     ok        ok        ok
checkBoxes     --     --        --        ok
```

The `--` under *binding* are errors. The `--` under *Gren* are the to-do list,
generated from the code rather than maintained by hand.

The callback check earned its place immediately. `tv.start()` takes its
callbacks as an object, and the addon installs the names it knows and ignores
the rest, so `onFocussed` where `onFocus` was meant is not an error in any
language: the object is valid JavaScript, the addon is happy, and the event
simply never arrives.

### Porting tvforms: a highlight has to travel both ways

The widgets tvforms needs -- check boxes, radio buttons, labels -- were already
in the binding, so the expectation was a morning's work exposing them in `Ui`.
The morning went elsewhere.

`listdlg.cpp` has Edit and Delete buttons, and what each of them does is

```c++
f->prevData = dataCollection->at(list->focused);   // edit
dataCollection->atFree(list->focused);             // delete
```

**They read the highlight at the moment they need it.** Every C++ example does
something of this kind, because in C++ a view is an object you can ask. A
program on the other side of a port cannot ask; it can only be told. And the
only thing a list box told anyone was `selectItem`, which Turbo Vision calls on
`Space` and a double click -- not on the arrow keys. So Edit would have opened
whichever record was last committed rather than the one under the highlight --
which is not a subtle difference: it is a different record, and Delete would
have removed it.

`TListViewer` does distinguish the two, and both are virtual:

- `focusItem(short)` -- the highlight moved, for any reason at all
- `selectItem(short)` -- this one, now, please

Overriding the first gives a `Focused` event, and that is half the fix. The
other half is the reverse direction, and the sorted collection is what forces
it: `TDataCollection` is keyed on the name, so renaming a record moves it, and
`setItems` puts the highlight back on row zero whatever the model wanted. The
model needs the last word, so `focused` became a field on `ListBox` that the
diff writes back after the items -- under the same rule as an input line's
text: **only when it changed in the model**, never merely because it disagrees
with the screen. A model that ignores the highlight never writes one, and the
arrow keys are left alone.

Two smaller things:

- **A label makes the order of `views` significant.** `TLabel` takes a pointer
  to the view it names, so that view has to exist first. Before this, the order
  of the array decided one thing: who gets focus.
- **`TCluster` gives out no hotkeys of its own.** It matches `Alt-`*x* against
  the `~` marks in its own item labels (`tcluster.cpp:258-262`), so items
  written without tildes claim nothing. That is why the original can put a
  `~P~hone` field next to a "Personal" check box and have both work.

### Anything a render can trigger must be queued

`setItems` calls `focusItem(0)`. `setItems` is called by the diff, which is
called from a port subscription, which is inside a JS call into the addon. So a
`focusItem` notification dispatched straight into JavaScript would re-enter the
Gren program from inside `tv.window()` -- during `buildItems`, with a window
half-constructed -- and the update it triggers would render, and the render
would reach the differ while it is in the middle of applying the previous one.

The differ survives that (it queues a render that arrives while it is
applying), but the C++ underneath would be reasoning about a view it has not
finished inserting.

This is the second notification with that shape. The first was `~JsWindow`,
which runs deep inside TVision's teardown, and the answer was the same: push
onto a vector and drain it at the pump's safe point, after the event that
caused it has finished. Worth stating as a rule -- **a notification that a
JavaScript call can cause must be queued, not dispatched** -- because the
alternative works in testing and fails on the day the model does something
interesting in response.

### A cursor cannot be placed on a view that is not on screen yet

The ASCII chart is the first Gren example to use a canvas, and it needed the
one part of a canvas that is not made of characters: the block cursor that
shows which cell is selected. A canvas takes it as `cursor = Just { x, y }`.

Setting it while the window is being built does nothing at all, and says
nothing about it. `TView::showCursor` sets `sfCursorVis` and calls
`resetCursor`, which is

```c++
if( (state & (sfVisible|sfCursorVis|sfFocused)) == (sfVisible|sfCursorVis|sfFocused) )
```

-- so it moves the terminal's cursor only for a view that is *focused*, and a
view still being constructed has no owner, no `sfVisible` and no focus. The
position is stored on the object and the terminal never hears about it. Worse,
it looks like it worked: the object's `cursor` member holds exactly what was
asked for.

So cursors are a second pass, after `deskTop->insert()` and after the initial
focus, in both `window()` and `dialog()`. The Gren side cannot see any of this
-- `cursor` is a field like `lines` -- which is the point.

The regression this leaves behind is easy to write, and only because the test
harness grew a `cursor()` of its own: a canvas has no highlight and no
selection bar, so the *only* evidence on screen of which cell is selected is
where the terminal cursor sits.

### What is left

`Tui` now covers static text, buttons, input lines, list boxes, check boxes,
radio buttons, labels and canvases -- everything the binding can build, cursor
included. The
consistency checker's coverage column is all `ok`, so the next widget has to
start in C++.

The gap the checker cannot see: **a cluster or an input line in a plain window
holds state the model never sees.** Values are collected when a dialog is
answered and at no other moment. Turbo Vision programs are shaped that way, so
nothing has needed it yet -- but it is the same hole `Focused` just filled for
list boxes. `gren-tvision/examples/README.md` tracks that along with what each
remaining C++ example would force into the API.


## Porting the rest of tvdemo

### A canvas had one colour, and three examples needed two

The chart came out the same colour all over because that is all a canvas could
be: `JsCanvas::draw()` took `getColor(colorIndex)` once and moved every string
into the buffer with it. Nothing had complained, because the ASCII chart really
is one colour.

The next three examples are all colour. `calendar.cpp` draws today with
`getColor(7)` and the rest of the month with `getColor(6)`; `puzzle.cpp` keeps
two attributes in an array and indexes it per tile; `palette.cpp` is an essay
about nothing else. So a canvas line stopped being a string and became an array
of spans:

```gren
type alias Span =
    { text : String, fg : Maybe Hue, bg : Maybe Hue }
```

Three things about that shape were decided by the C++ rather than by taste.

**The two halves are separate.** Turbo Vision's `TColorAttr` has a foreground
and a background and they are set independently, and the useful case really is
one of them: today on a calendar is `getColor(7)` on whatever the window is
already using. A `Maybe { fg, bg }` would have forced every highlight to name a
background it has no opinion about, which is how a view stops matching the rest
of the program when someone changes the theme.

**A span with no colour has to encode to what a string encoded to.** The
runtime diffs canvas lines by comparing their JSON, so a `plain` span emits
`{"text": "..."}` and nothing more; had it emitted `{"text":..,"fg":null,..}`
every canvas in every existing example would have repainted on every render and
the diff would still have said it was doing nothing.

**The column has to come from `moveStr`, not from the string.** Spans are laid
down left to right and the next one starts where the last one ended -- which is
not its length. magiblot's Turbo Vision draws Unicode: `╣` is one cell and
three bytes. `TDrawBuffer::moveStr` returns the number of *cells* it wrote,
which is the only number that is right.

The binding accepts a bare string in place of an array of spans, so the
`tvision-node` examples and their tests did not have to change at all. That is
not a courtesy: it is the shape every canvas had before colour existed, and it
is what `Tui.line` produces.

### The test harness could not see colour, so it grew eyes

`Screen`, the little terminal emulator in `tvision-node/test/harness.py`,
parsed SGR only well enough to skip it. That was fine while the only question
was what the screen said. It is not fine for a calendar, where the entire
visible difference between today and the twenty-ninth is the colour: the text
is identical, there is no highlight bar, and the cursor is somewhere else.

So `Screen` now keeps `(foreground, background)` per cell alongside the
character, and `Pty.display()` hands back the whole thing -- text, cursor and
colour together. `fg_at(col, row)` is what `drive_calendar.py` asserts on.

This is the third time the harness has had to grow before a port could be
tested (`render()` for the ticking clock, `cursor()` for the ASCII chart, now
colour), and every time the addition was smaller than the bug it would have
hidden.

### Porting the calendar: `localtime()` in a constructor is untestable

`TCalendarView`'s constructor calls `localtime()` and keeps the answer in
`curDay`/`curMonth`/`curYear`. The view therefore *is* today. There is no
argument to pass and no member to set: you cannot ask a `TCalendarView` what
March 1900 looks like, which means you cannot test one at all.

Gren has no clock a pure function can read, so this had to become a field, and
`Time.here` and `Time.now` are tasks -- the answer arrives after the first
render, not before it. The visible consequence is that the window is not on the
desktop for one turn of the event loop. The invisible one is the whole point:
today is data, so the calendar renders any month you hand it, and
`drive_calendar.py` walks a year back and checks that today stops being
highlighted when you leave its month.

Two smaller things fell out. The original's leap year rule is `year % 4 == 0`,
which is right for every year Borland expected to be run in and wrong for 1900
and 2100; a calendar that can be pointed anywhere has to use the real rule. And
the header's two arrows are backwards -- clicking the one that points *up*
moves to the next month. That was faithfully reproduced, because it is what
`calendar.cpp` did. Both were reported upstream as
[magiblot/tvision#229](https://github.com/magiblot/tvision/issues/229).

**Both are fixed upstream** (`e72d695`, 2026-09-01), and the arrows are now the
sensible way round in `calendar.cpp` too -- so this port turned them round with
it. The reason to reproduce a quirk was that it was what the original did, and
the moment that stops being true the reason expires; there is no separate
decision to make. It is also worth noticing what the port's own code had
already said about it: the *keyboard* here has always been Up for the previous
month and Down for the next, exactly as `calendar.cpp`'s always was. The two
halves of the original disagreed with each other, and copying both faithfully
copied the disagreement.

That is the argument for porting rather than reading, stated from the other
end. Two bugs that had been in `calendar.cpp` since Borland shipped it were
found by writing the same view in a language where today is data and a test can
walk to 1900, and are now fixed for everybody.

### Porting the puzzle: the generator has to be in the model, and that is better

`TPuzzleView::TPuzzleView` calls `srand(time(0))` and then makes five hundred
random moves. The board is a C++ member reached through a seed nobody kept, so
there is no board you can ask for, no way to know what the answer is, and no
way for a test to win.

Gren has no `rand()` to call. The generator has to be a field the shuffle
threads through and hands back -- a Lehmer step, which is all `rand()` was
providing -- and once it is a field the board is a pure function of a seed and
a depth. `--seed=` and `--scramble=` are then a one-line addition rather than a
debugging hook, `init` already receives the `Node.Environment` they come from,
and `test/drive_puzzle.py` reproduces the shuffle in eight lines of Python,
checks the screen agrees, breadth-first searches for the answer and plays it.

Purity bought a test that the original cannot have. It is the clearest example
so far of the trade this binding makes going the right way.

The colours are the other half, and they are keyed on the *letter* rather than
the square, so a tile carries its colour as it slides. The checkerboard is
therefore a picture of how scrambled the board is, and a solved board drops
back to one colour -- which is the only announcement `puzzle.cpp` makes that
you have won, and the thing the test asserts to prove it did.

### Porting the calculator: a button that cannot be focused

`TCalculator`'s constructor makes twenty buttons and then, for every one of
them, says

    tv->options &= ~ofSelectable;

There is no comment. The reason is two lines further down: the window's other
child is `TCalcDisplay`, a `TView` that reads the keyboard, and a keypad whose
buttons could take focus would eat every digit typed at it -- `7` would move
the caret to the button captioned 7 rather than reaching the display.

`Button` therefore grew `takesFocus`, which is the first field added to the
Gren API for a reason that is invisible until you try to use two kinds of input
in one window. It is not a calculator-shaped need: a toolbar wants it, and so
does anything where the window has a canvas doing the reading.

The display itself is a canvas, which is why it can be selectable, and it is
painted green on black -- the original uses palette entry 1, and this is the
first place where saying the colour outright is simply nicer than looking it
up.

`calcKey()` transcribes almost exactly. The one place it does not is
`setDisplay`, which formats a `double` with `ostrstream`'s default six
significant digits; Gren's `String.fromFloat` is not that, so the port shows
integers as integers and falls back to `fromFloat` otherwise. The rest --
including the detail that an operator key *finishes the pending operation
before recording itself*, which is what makes `2 + 3 + 4 =` come out as 9 --
is the original's state machine unchanged.

### Porting the palette example: the subject does not survive translation

`tvision/examples/palette` is an essay about how a view gets its colour. A view
asks for colour 1; its palette turns that into an index into the window's
palette; the window's turns that into an index into the application's; the
application's holds the byte the terminal receives. Three levels, three
parallel palettes for colour, black-and-white and monochrome displays, and a
comment explaining that the tables are `#define`s so the compiler will
concatenate them.

    #define cpTestView   "\x9\xA\xB\xC\xD\xE"
    #define cpTestWindow "\x88\x89\x8A\x8B\x8C\x8D"
    #define cpTestAppC   "\x3E\x2D\x72\x5F\x68\x4E"

In Gren a span names its colour and there is nothing in between, so the essay
becomes a six-row table holding what those three lines resolve to. The
original's last line -- the one whose comment says it "bypasses the palettes"
-- ends up indistinguishable from the six above it, because there are none to
bypass.

That is a real trade and the port says so rather than claiming a win. The
indirection exists so that one edit to the application's palette restyles every
view in the program; naming the colour gives that up. What comes back is that
the colour is in the model, where the same branch that decides *what* to draw
decides what colour to draw it -- which is how the calendar marks today and the
puzzle shows a tile out of place, and neither of those is a question a palette
can answer. A canvas that names no colour still follows the window, which is
what the example's second window is for and what nearly every other canvas in
these examples does.

`drive_palette.py` asserts the six attributes byte for byte, which is the only
way to test a port whose subject was the machinery it removed.

### Porting the mouse dialog: a scroll bar, and what a click on one does

`mousedlg.cpp` is a dialog with a scroll bar in it. That is a smaller sentence
than it sounds: a list box has always made a scroll bar for itself, but there
was no way for a Gren program to put one in a window and ask what it says. So
`ScrollBar` is a view now, with `value`, `min`, `max`, `pageStep` and
`arrowStep`, and a `Scrolled` event whichever way it moves.

`JsScrollBar` overrides `scrollDraw()`, which `TScrollBar` calls from every
path the value can change by -- arrows, the keyboard, a drag on the thumb. It
has to be queued rather than dispatched, more urgently than `focusItem` did:
`setValue()` calls `scrollDraw()` synchronously, so a render that moves a
scroll bar would call back into JavaScript from inside the diff. The queue also
collapses: a drag calls `scrollDraw()` for every cell the thumb passes, and
only the last position is worth a render.

**Which way it points is not a field.** `TScrollBar`'s constructor decides from
its own rectangle -- one column wide is vertical -- and an `orientation` field
next to a rectangle that already says the same thing would only give the two a
way to disagree.

**magiblot's scroll bar does not page on a click.** Borland's steps by `pgStep`
when you click past the thumb; this one takes the thumb straight to the pointer
and drags it from there (`tscrlbar.cpp`, the `default:` branch of the
`evMouseDown` switch). `pageStep` is reached only from the keyboard, and on a
*horizontal* bar that is `Ctrl-Left` and `Ctrl-Right` rather than PgUp and
PgDn. Both are in `drive_mouse.py`, because both are the kind of thing that
looks like a bug in the binding when it is not.

### `takesFocus` was not a button thing

The calculator needed non-focusable buttons. The mouse dialog needed the same
thing one view over, and finding out was instant: the tester strip is a canvas,
a canvas is selectable, a selected canvas consumes **every** key it is given --
`Tab` included -- so the scroll bar underneath it could not be reached from the
keyboard at all.

`Canvas` therefore has `takesFocus` too, and the field earns more there than it
does on a button: a canvas that is only there to be looked at, or clicked, will
otherwise trap the caret. Clicks reach a canvas either way, because
`JsCanvas::handleEvent` handles `evMouseDown` regardless of focus and only the
keyboard mask depends on `ofSelectable`.

Two of the canvases already written wanted `False` in hindsight -- the palette
example paints two pictures and reads nothing.

### Two clicks, and the setting that decides they are one

`TClickTester` reacts to `meDoubleClick`, so `Clicked` grew `isDouble`. The
first click of a pair still arrives on its own a moment earlier, which is not a
wart to hide: it is exactly what the dialog is demonstrating.

`TEventQueue::doubleDelay` is a static counted in the original PC timer's
1/18.2-second ticks, so `Tui.setDoubleClickDelay` is a command rather than part
of the view -- there is nowhere in a window for it to live.

The test that proves the setting is real turned out to need a note of its own.
Two mouse reports written back to back into a pty are read back to back, and
TVision timestamps a mouse event when it *reads* it -- so a gap that exists in
the byte stream does not exist as far as the library is concerned. The driver
pumps between the two presses, which is what makes 0.35 seconds a real 0.35
seconds: comfortably inside a 20-tick delay and outside a 1-tick one, which is
the whole demonstration.

### Porting tvdir: the widget that did not need wrapping

`gren-tvision/examples/README.md` had tvdir down as "needs a new widget:
`TOutline`". It does not, and finding that out took about ten minutes.

A tree view is a widget in C++ because it has to be. `TOutlineViewer` owns a
`TNode` chain, walks it to work out which rows are currently visible, draws the
`└─` graphics, and keeps a `foc` index into a list that only it can compute --
`TDirOutline` even has to define `getParent` by searching the whole tree,
because a `TNode` has no parent pointer. All of that is machinery for deciding
what to draw from a structure the view owns.

A model that re-renders owns the structure already. The tree is

    type Node = Node { name : String, path : Path, expanded : Bool, children : Maybe (Array Node) }

and the visible rows are a fold over it. A plain `ListBox` shows them, indent
and markers included, and it brings the scrolling and the highlight with it.
`getParent` has no equivalent because paths are unique: `mapNode path change`
finds the node and replaces it without a cursor or a parent pointer.

This is the same shape of finding as `mmenu`, in the other direction. There the
documentation said something was impossible and it was not; here it said
something was needed and it was not. Both were only settled by writing the
port.

`TScroller` went the same way for the same reason: what a scroller does is
decide which slice of the content to draw, and the model already knows.

### The "Please Wait" window is an artifact of blocking

`TDirWindow`'s constructor scans the entire drive before it returns, so nothing
can be on screen while it happens. The original's answer is a `QuickMessage`
window, a `TParamText` updated per directory, and a hand-written
`TScreen::flushScreen()` to force the terminal to catch up.

`FileSystem.listDirectory` is a `Task`. A directory is read when it is opened,
nothing blocks, and there is no wait window because there is nothing to wait
for. Milestone 2 went to some trouble to make that true and this is the first
example where it is the difference between two designs rather than a detail.

It is also the first example to use the file system at all, which is what `init`
being a full `Init.Task` was for: `FileSystem.initialize` is awaited before
there is a model.

One thing that has to be got right and is easy to miss: `listDirectory` answers
with the entries' *names*, not their paths, so each one has to be put back
underneath the directory it came from before it means anything to the next
listing.

### The bug the tree found: a rebuilt list forgets its highlight

Expanding a branch collapsed the whole tree instead. The cause is worth the
space, because the comment explaining it was already in `diff.js` and the code
next to it did not implement it.

`TListViewer::setItems` puts the highlight back on row zero -- it has to; the
old position may be past the end of the new list. `diff.js` therefore re-sent
`focused` after `setItems`, but only when `focused` had *changed*:

    if (before.focused !== after.focused) tv.setValue(after.id, after.focused);

Expanding a branch changes the items and leaves the highlight where it is. So
`focused` was 1 before and 1 after, no `setValue` went out, the list sat on row
zero, and -- because a list box reports where its highlight lands -- it told the
model the highlight had moved to zero. The model believed it, listed the root
again, and the render that followed collapsed the branch that had just been
opened.

Two changes, and both are needed:

  - `focused` is re-sent whenever the items changed, not only when the model
    moved it. A `focused` that did not change is still one the list no longer
    agrees with.
  - `JsListBox::setItems` no longer reports its own `focusItem(0)`. That
    position is an artifact of rebuilding rather than something that happened,
    the caller always follows `setItems` with the position it actually wants,
    and *that* is reported. Announcing the intermediate zero tells a model its
    highlight moved somewhere it was never going to stay -- and a model that
    acts on where the highlight is, by opening a directory say, acts on the
    wrong one.

The tvforms port wrote down exactly this hazard and did not hit it, because
there the model always moved `focused` when the list changed. It took a tree to
produce the case where the items change and the highlight does not.

### A list box's scroll bar belongs beside the list

`TWindow::standardScrollBar` puts it on the window's frame, which is right for a
Turbo Vision window that is a list and nothing else -- and every Borland
example is one. A directory tree beside a file pane is not, and the tree's
scroll bar came out on the far side of the files.

The binding now makes the bar itself, in the single column immediately to the
right of the list's own rectangle. That is a rule an author can lay out
against, it is local to the list, and it costs the two existing examples two
columns of width to keep the bar exactly where it was.

## Finishing tvdemo

### Every window was a dialog, and dialogs do not tile

`JsWindow` derives from `TDialog` so that a window and a dialog are one class.
That is a reasonable place to start and it quietly took the window-ness back
out: `TDialog`'s constructor sets `growMode = 0` and `flags = wfMove |
wfClose`, so no window this binding made could be zoomed, resized or grown with
the terminal. Worse, `ofTileable` is set by exactly one class in all of Turbo
Vision -- `TEditWindow` -- so `Tile` and `Cascade` had nothing to arrange and
did nothing at all, silently.

A non-modal window now puts all four back: `wfMove | wfGrow | wfClose |
wfZoom`, `gfGrowAll | gfGrowRel`, `ofTileable`, and a `zoomRect`. Dialogs keep
`TDialog`'s defaults, which is what makes them dialogs.

The child views do *not* grow with the window, because their rectangles are
what the model said they are. A tiled window therefore shows a clipped canvas
rather than a stretched one. That is the honest behaviour for a declarative
API and it is a known gap, not an oversight: growing a view would put its size
somewhere the model cannot see, which is the thing this whole binding is
arranged to avoid.

### `"tile"` and `"cascade"` were documented and not implemented

`Tui`'s docs have listed both as built-in command names since the first commit.
`CommandRegistry` did not intern either, so they were handed out as ordinary
user commands: the menu entry drew, the hotkey worked, and the model received
`Command "tile"` while the desktop sat still.

They were the two to be missed because they are the two `TApplication` handles.
Everything else on that list belongs to `TProgram`, which is where anyone
checking would look. `tools/check_consistency.py` now pulls the names out of
Tui's own documentation and compares them against the table in `tvnode.h`,
because nothing else can: an unknown name is a *valid* command, and its only
symptom is that Turbo Vision does not act on it.

### The first click is spent twice

The API documented that the first click on an inactive window is spent
activating it. `TView::handleEvent` applies the same rule one level down:

    case evMouseDown:
        if( (state & (sfSelected | sfDisabled)) == 0 && (options & ofSelectable) != 0 )
            if( !focus() || (options & ofFirstClick) == 0 )
                { clearEvent(event); return; }

so a control that can take focus and has not got it spends the first click
taking it. In `examples/viewer` the canvas holds the caret, so the scroll bar
beside it needs two clicks to move -- which looked exactly like a scroll bar
that had stopped responding, for about ten minutes.

A view with `takesFocus = False` has no first click to spend, which is one more
reason to say so where it is true.

### What a Gren event viewer can see, and what it cannot

`TEventViewer` hooks `getEvent` and prints every `TEvent` the application
receives, mouse moves included. `examples/demo`'s viewer prints what crossed
the port: a command, a selection, a key that reached a canvas, a dialog's
answer. Everything Turbo Vision handled on its own -- the click that raised a
window, the arrow that moved a highlight, `Tile` -- never arrives.

That is the bargain rather than a limitation, and a window that lists what does
cross the port is a fair way to show where the line is.

### The clock is a status item, and Borland had a reason not to do that

`TClockView` is a view on the *application*, outside the desktop, which this
API cannot express: `Ui` has a menu bar, a status line and windows, and nothing
that lives beside them. A status item is close enough for a clock -- an entry
with an empty command is a hint rather than a button -- except that the status
line is replaced whole rather than patched, so a clock in it rebuilds the
status line once a second.

Cheap, and it works. It is also precisely the reason Borland made the clock a
view, and worth knowing before putting anything larger in there.

### Porting the file viewer: `TScroller` goes the way of `TOutline`

`TFileViewer` is a `TScroller`: a view that owns a `delta`, is told a `limit`,
and paints the slice at `delta` when `scrollDraw()` says to. All of that is one
idea -- which part of the content is on screen -- kept inside the view because
the view is the only thing that can redraw fast enough.

A model that re-renders keeps it in the model: `top` and `left` are two fields,
the visible lines are a slice, and the scroll bars are ordinary views whose
`value` the model both reads and writes. It is the same conclusion `tvdir`
reached about `TOutline`, and it arrived faster the second time.

What is genuinely new is a horizontal scroll bar doing the job it is named for.
`mouse` has one as a slider; this one scrolls. They are the same view, because
which way a scroll bar points is decided by its rectangle.

### The gap nobody has decided about: asking for a path

`examples/dir` and `examples/viewer` both take their path on the command line,
and `tvdir`'s Change Dir half is the one part of it not ported, for the same
reason: there is no way for a Gren program to ask the user for a file.

`TFileDialog` and `TChDirDialog` (`stddlg.h`) are what Turbo Vision offers, and
the notable thing is that neither looks like a class worth wrapping.
`TFileDialog` *is* a `TDialog` full of stock controls — an input line, an OK
and an Open button, a history list — arranged around a `TFileList`, which is a
`TSortedListBox` over a directory listing. Every one of those pieces is already
in the API, and `FileSystem.listDirectory` supplies the rest.

So the shape of the answer is probably a helper in the *package* that builds a
`DialogSpec`, rather than anything in the binding: `Tui.filePicker { title,
directory, pattern }` handing back views the program passes to `Tui.dialog`,
with the listing done by the model. That follows `TOutline` and `TScroller` --
both of which turned out to be machinery for deciding what to draw, which a
model that re-renders does not need.

It is written down here rather than done because it is a design decision, and
because nothing so far has needed it badly enough to decide badly. The other
open gaps are listed at the end of `gren-tvision/examples/README.md`.

## The watcher: the first program here that is not a port

`examples/watch` runs a set of commands whenever a directory changes. It is the
only example in the package with no C++ original, and it exists to answer a
question the other thirteen cannot: what does binding Turbo Vision to Gren
provide that binding it to 1994 did not.

### Turbo Vision has exactly one source of events, and it is the user

`TProgram::run` is `getEvent`/`handleEvent`, and `getEvent` reads a keyboard, a
mouse and the clock TVision keeps for double-click timing. There is no third
thing. Nothing in `tvision/examples/` reacts to anything but a keystroke, and
that is not an omission — a Borland-era program that wanted to know something
about the world had to go and ask, in a call that returned when it had the
answer. `tvdir`'s constructor scanning the drive behind a "Please Wait" window
is what that looks like when the answer is slow.

`FileSystem.watchRecursive` is an ordinary `Sub`. inotify events arrive as
messages next to the keyboard's, on the same terms, through the same `update`.
Nothing in the binding had to change to allow it, which is the interesting
part: subscriptions were already there for `Time.every`, and a clock is a
subscription whose source happens to be inside the process. Once one of them
can come from outside, the shape of what can be built changes and the API does
not.

`test/drive_watch.py` asserts it the only way that means anything: **the test
writes a file, and the application does something.** Every other driver in this
repo types at the program.

### The built-in command names are a reserved vocabulary

The watcher wanted a command called `cancel`. It got a menu entry that drew, an
`Alt-C` that worked, and no event, ever.

`"cancel"` is one of the fourteen names `CommandRegistry::reset` interns
(`tvnode.h`), because `cmCancel` is Turbo Vision's — and outside a modal dialog
`cmCancel` does nothing at all. So the command was taken, handled, and dropped,
in silence.

`Tui`'s documentation listed nine of those fourteen. The five it did not
mention were `"help"`, `"ok"`, `"cancel"`, `"yes"` and `"no"` — every one of
them a word an application might reasonably want.

This is the `"tile"` and `"cascade"` bug seen from the other side. There the
docs promised a name the binding did not intern, so it reached the model as an
ordinary event and the desktop sat still. Here the binding interns a name the
docs never mentioned, so Turbo Vision swallows it and the model is never told.
Both are invisible; both are one missing row in a table.

`tools/check_consistency.py` had been comparing those two lists in one
direction: every name the docs promise must be interned. It now checks the
other direction too, which is the half that matters more — a promise the
binding does not keep is a feature that does not work, but a name the binding
takes without saying so is a trap laid for every program written against it.

### A save is not one event, and a killed child does not stop at once

Two things a watcher needs that are not visible until it is used.

**Editors write a file three or four times.** A save is typically a write, a
rename and a chmod; inotify reports each one. Undebounced, the commands run
four times per keystroke. The fix is a generation counter — a change bumps it
and schedules a `Process.sleep`, and the sleep starts a run only if its
generation is still the current one. `drive_watch.py` writes five files in a
row and checks that exactly one run happened and that all five were seen, which
is the pair of assertions that pins the behaviour down: debounced, not
throttled, and not deaf.

**A killed child goes on talking for a moment.** `Process.kill` on the id
`ChildProcess.spawn` hands back does kill it — the kernel binding's cleanup is
`subproc.kill()` — but the pipe still holds bytes, and they arrive after the
replacement run has started. Without a tag they land in the new run's output.
So every job carries the number of the run its child belongs to, and a chunk,
an exit or a process id belonging to any other run is dropped.

`examples/dir` has the same hazard in one comment: two directory listings in
flight, and the late one must not overwrite the recent one. That was a two-line
guard on a rare case. Here it is structural, because killing the previous run
is the normal path rather than an accident. **The Elm architecture does not
make stale-response bugs go away; it makes them all the same bug**, and one
that can be fixed once in the model instead of everywhere a callback fires.

### A scroll bar with two owners

`examples/mouse` has a scroll bar the user moves. `examples/dir` has one the
model moves. This is the first with both: output arriving scrolls the pane
down, and a user who has scrolled up to read a failure does not want it taken
away.

There is no rule the binding could impose here, because the two movements are
indistinguishable by the time they reach it. The model is the only thing that
knows whether the last move was output or a hand, so the policy lives there,
and it is the one every log viewer converges on: follow the bottom until the
user leaves it, follow again when they come back. One `follow : Bool` on the
job, set in the `Scrolled` handler.

Worth noting because the obvious alternative — a `stickToBottom` flag on
`ScrollBar` — would have looked like a convenience and been a mistake. It would
put the decision in the runtime, where the difference between the two kinds of
movement has already been lost.

### Two glibcs again, this time in a child process

Milestone 0's question was whether a system-built `.node` could be loaded by
nix's node. This is the same question, four hundred commits later, arriving
from the other end.

Under `test:asan`, `asan.sh` exports `LD_PRELOAD=<nix>/libasan.so`, and a child
process inherits it. Node's `shell: true` runs `/bin/sh` **by name** — the
distribution's, linked against the distribution's glibc — and the preloaded
`libasan.so` comes out of the nix store and drags nix's glibc 2.42 in behind
it. The system libc cannot satisfy `GLIBC_ABI_DT_X86_64_PLT`, so under ASAN
every child died before `main` with a link error, and the failure looked
exactly like a broken example.

A shell taken off `PATH` is devbox's own and has no such problem. `watch` grew
`--shell=`, which a watcher wants anyway, and the driver passes `--shell=bash`
when `TVNODE_ASAN=1`. Nothing here reaches a user: it takes an `LD_PRELOAD`
from one libc and a program from another, which only a sanitizer run inside a
devbox shell arranges.

The general form is worth keeping: **a preloaded sanitizer is inherited by
everything you spawn**, including its `log_path`. Under `test:asan` a child of
this program runs instrumented and writes its reports into
`tvision-node/build/`. For the shell built-ins the test uses that is free. For
a real command it would not be, which is a reason to keep the fixtures trivial
rather than a reason to stop spawning.

### What the watcher did not need

No new view type, no new event, no change to the wire protocol. Three windows,
three canvases, three scroll bars, and a `Sub`.

That is the result worth recording. Thirteen ports were each chosen because a
C++ example would force something, and each one did. The first program written
for the API rather than translated into it forced nothing — the widget set was
finished, and what it found instead was a documentation hole with teeth in it.

### Every window is grey, so half the palette is unreadable in one

`examples/watch` paints a job's output in the colour of its state, and the
first attempt used `LightGreen` for a pass, `LightRed` for a failure and
`LightGray` for a run still going. On screen that is hard to read, hard to
read, and completely invisible.

The reason is one line of inheritance. `JsWindow` derives from `TDialog`
(FINDINGS has the note on what else that cost), so a window's background is the
light grey a dialog has and not the blue a `TWindow` has. Against light grey
the eight *bright* hues — the top half of the sixteen — are the wrong half:
`LightGray` text on a `LightGray` ground is nothing at all, and the rest are
low contrast. Against Turbo Vision's blue they would all have been fine, which
is why the mistake is easy to make from a palette table.

`Green`, `Red` and `DarkGray` read properly, and a job with nothing to say uses
**no colour at all** — `Tui.plain`, which paints in whatever the view's palette
entry says. That last one is the point worth keeping: a span that names no
colour is the only kind that stays correct if the window's palette ever
changes, and it is exactly what the calendar's write-up argued for when spans
were added. Naming a colour is for the thing that is different from its
surroundings, not for the ordinary case.

`drive_watch.py` asserts on the two colour codes directly. Nothing else on
screen would show the difference, which is the same reason `drive_calendar.py`
has to.

## Walking the whole widget set, once

`examples/README.md` had five coverage gaps written down. Enumerating every
`TView` subclass in `tvision/include/tvision/*.h` and checking each against the
four layers turned five into ten, and turned two guesses into facts.

The widget set itself is finished. Every stock control a Turbo Vision program
is normally assembled from is in `Ui`, five more were left out for reasons
already written up, and `Canvas` covers the rest. That was the expected answer
and it is not the interesting part.

### Two things that were assumed and are not true

**The mouse wheel already works, and nothing here made it.** `TScrollBar` puts
`evMouseWheel` in its own event mask (`tscrlbar.cpp:57`), so a wheel turn
scrolls the bar and reaches the model as an ordinary `Scrolled`. Driving
`examples/viewer` with SGR wheel codes moves it fifteen lines. Grepping the
binding for "wheel" finds nothing and suggests the opposite, which is the
argument for running the thing rather than reading it. One inherited caveat:
`positionalEvents` excludes `evMouseWheel` (`views.h:199`), so a wheel event
goes to the focused view rather than the one under the pointer.

**No program written with this API knows how big its terminal is.** Every
example hardcodes 80x25 — `dir` stops at column 78, `watch` divides an assumed
23-row desktop by the number of jobs. In a 120x40 terminal Turbo Vision uses
the whole screen and the windows sit in an 80x23 box in the corner with fifteen
rows of empty desktop below them.

`screenSize()` has been in the binding since milestone 2. What is missing is a
way to ask: the Gren-to-runtime protocol is five messages — `render`,
`dialog`, `setEnabled`, `doubleClickDelay`, `quit` — and there is no sixth.
`tv.focus(id)` is unreachable for exactly the same reason.

That is worth more than the two features it costs. **The gap was invisible
because the check that exists to find gaps only looks at view types.**
`check_consistency.py`'s last pass reports "the binding supports X, the Gren
API does not expose it yet" for every *widget* the C++ builder knows and the
encoder does not. Nothing compares the binding's twenty exported functions
against the five messages the protocol can carry, so `screenSize` and `focus`
sat there being supported and unreachable for eleven examples.

### The shape of what is left

Ten gaps, and only the first two are about every program rather than one kind
of program: **the terminal's size, and views that grow with their window.**
They look like separate items and they are one design decision — both ask the
model to know a number that Turbo Vision owns. The answer worth trying is that
a `Rect` stops being the only way to place a view, and a declarative
`fill`/`fixed` layout says intent instead of coordinates, which the runtime
resolves against whatever size the window actually has. Then neither the model
nor the C++ has to tell the other a number, and both symptoms go at once.

*(Both are now settled differently, and the paragraph above is wrong on the
part that matters — see "Closing gap 1" at the end. They are two decisions, not
one, and the declarative layout does not have to be invented: `growMode` is it,
and Turbo Vision already resolves it.)*

The rest are ordinary: `focus`, a message box, `THistory`, `TMenuPopup`,
validators together with the cluster state they need, `TMultiCheckBoxes`, and
a view on the application. `examples/README.md` has each with what it would
take, and — as usefully — a list of the five things that look like gaps and are
not.

## Teaching the checker to see the protocol

### The gap-finder had a gap, and it found a fifth thing on the first run

The previous section ends by naming the reason `screenSize` and `focus` stayed
invisible: `check_consistency.py` compares *view types* across the four layers
and nothing compared the binding's exported functions against the messages the
protocol can carry. Writing that check took twenty lines and immediately
reported one more than the two it was written to catch.

The check is the whole protocol boundary stated once: the port is the only way
into the binding, so a function `index.js` exports that no runtime call site
reaches is a capability no Gren program can use, however finished it is on both
sides of it. Four names came back:

  - `focus()` and `screenSize()` — gaps (3) and (1), already written up;
  - `messageBox()` — gap (5), already written up;
  - **`getValue()`, which was not on the list at all.**

`getValue(id)` returns the text of a live input line, the highlighted row of a
list box, the bits of a check box cluster or the selected radio button
(`views.cc:683`) — from an *ordinary window*, not a dialog. Gap (8) says values
are collected when a dialog is answered and at no other moment, "so a check box
ticked in an ordinary window is invisible until something asks", and files that
under things the API cannot do. It can. The C++ has been able to answer that
question since the clusters were wrapped; there has never been a way to put it.
The gap is one message wide, not a feature.

That is the second time in this project that the thing worth having was the
statement of an invariant rather than the fix: the built-in command names
(above) were the first. Both are the same shape — two lists that must agree,
in two languages, with nothing but silence when they don't.

### The check that was there was checking four of five messages

Check 6 compares the messages Gren sends against the `switch` that receives
them, and it had a hardcoded whitelist:

```python
gren_out = gren_outbound_kinds(tui_gren) & {"render", "dialog", "quit", "setEnabled"}
```

The whitelist was there for a real reason. `gren_outbound_kinds` searched the
file for `"type", value = Encode.string "..."`, and every branch of
`encodeView` has one of those, so the raw list was thirteen view types plus
five messages and had to be pruned. Pruning it by hand meant the check silently
stopped covering `doubleClickDelay` the moment protocol 4 added it — four
protocol versions ago, and nothing said so, because a whitelist that is missing
an entry checks fewer things and still passes.

Anchoring the extractor on the `ports.toJs` call site instead of on the string
literal removes the need for the list: there are five call sites, the message
kind is the first `"type"` key in each, and a site whose kind cannot be read is
now a failure rather than a silent omission. The reverse direction is a note —
a `case` the runtime handles that Gren never sends is dead code, not a bug.

Both halves of this are the same lesson, and it is the one that keeps
recurring here: a consistency check that enumerates what to look at will drift
out of date exactly as quietly as the thing it is checking. Derive the list.

## Closing gap 3: the model can move the focus

`tv.focus(id)` had been in the binding since milestone 2 with no message to
carry it, and the gap list called it "plumbing rather than design, and the
cheapest item on the list". It was the cheapest. It was not plumbing: two
things had to be decided and one of the two calls turned out not to work.

### A message that names one view is a different kind of message

Every message this protocol carries describes the whole UI — `render` is the
model's entire `view`, and `dialog` is a whole dialog — or is about the
application: `quit`, `setEnabled`, `doubleClickDelay`. `focus` is the first one
that names a single view and asks for something to happen to it, and that is
not an accident of this feature. Where the caret is at any given moment belongs
to Turbo Vision: a click moves it, Tab moves it, closing a window moves it. A
model that tried to hold it as a field would be describing the past, and the
differ would fight the user for it on every render.

So focus is a command and not a field, nothing comes back, and an id naming
nothing is ignored. That is the same answer `Tui.dialog` gives, one size down.

### The message arrives before the view it names exists

`defineProgram` batches every update's command with the render that follows it:

```gren
command = Cmd.batch [ stepped.command, render ports config stepped.model ]
```

The user's command leaves first — the port trace shows `focus` on one line and
`render` on the next — so `Tui.focus tui "list"` in the same update that opens
the window called `"list"` reaches the binding while that window does not yet
exist. Focusing a view that is not there is the identical silent nothing the
canvas `cursor` was, and for a related reason: there is nothing to focus.

This is the third thing in this project with that shape, after `~JsWindow` and
`setItems`' `focusItem(0)`, and the rule from the first two applies unchanged:
**a thing that names a view has to happen after the view exists.** Cursors
became a second pass after `deskTop->insert()`; focus became an id the runtime
holds and applies again once the render has been applied. It is also tried
immediately, which costs one no-op call and means the feature does not depend
on a `Cmd.batch` ordering nothing promises.

### `sfSelected` does not mean what the name suggests

The first version focused the view and reported success, and the window it was
in stayed grey. The callback even came back — Turbo Vision said the list box
was focused — and the frame did not change.

`TView::focus()` starts with

```c++
if ((state & (sfSelected | sfModal)) == 0)
```

and does nothing at all otherwise. `sfSelected` is not "has the caret": it is
"I am my group's `current`", which a window's first control is from the moment
the window is built, whether or not that window is the active one. So focusing
the first control of a background window is always a no-op, and always claims
to have worked.

The binding's window branch was already right — `select()` then `focus()`, the
two calls a click on a frame makes. The view branch now raises the owning
window with those same two calls before focusing the view, which `ViewRef`
could already answer because it carries the `windowId` it was registered
under. A view in a modal dialog has no `JsWindow` to find, and falls through to
the plain `focus()` that was there before.

The consequence worth remembering is not the fix, it is that this failed
*successfully*: a `Boolean` came back `True`, the focus callback fired, and the
screen disagreed. Only a pty test that reads the frame characters could tell —
Turbo Vision draws the active window's frame with a double line and every other
window's with a single one, and that is the only evidence anywhere on screen of
which window has the focus.

### What it is worth

`examples/entries` had a menu entry that did nothing. Alt-L set `listOpen` to a
value it already had, the render found no difference, and the window stayed
behind whatever was in front of it — the failure mode of every "show me that
window" command written against a pure description of the UI. It is a one-line
fix now and it was unwriteable before. The other direction is the smaller and
more ordinary one: a dialog gives the caret back to whoever had it before,
which is not the list the new entry just went into.

## Closing gap 1: how big the terminal is

Every example here hardcoded 80x25 and there was no way not to. `screenSize()`
had been in the binding since milestone 2 with no message to carry it, and
there was no resize event either, so a program had no way to learn the size
once *or* to hear that it changed.

Two things turned out to be true before any of it was written, and both
contradict the gap list.

### Windows already grow with the terminal; their contents already do not

`beWindow()` sets `growMode = gfGrowAll | gfGrowRel` on every non-modal window,
because `TDialog`'s constructor takes the window-ness back out and a window on
the desktop should zoom, resize and tile. `gfGrowRel` is the one that matters
here: it means "keep my position and size *relative to the screen*", and
`TGroup::changeBounds` does the arithmetic when the screen changes. So resizing
the terminal has always rescaled the windows proportionally, and nobody had
written that down.

`JsCanvas` and every other child view is built with `growMode = 0`, on purpose.
So the window grows and the views inside it stay exactly where the model put
them. That is gap (2), and now it has a number: driving `examples/entries` from
100x30 to 120x40 moves the list window's bottom frame from screen row 22 to row
32 and leaves its Add button on row 15, where it was.

Which means gap (1) and gap (2) are **not** one design decision, as the list
says they are. Gap (2)'s answer already exists and is switched off: it is
`growMode`, one integer per view, with Turbo Vision doing the resolving. There
is no layout engine to invent. Gap (1) is a separate and simpler question —
telling the model a number it currently has to guess.

### The size cannot arrive in `init`, so it is an event

`init : Node.Environment -> Init.Task ...` is Gren's, and there is nowhere in
it to put a number that comes from C++. Worse, there is nothing to ask: the
runtime calls `tv.start()` on the *first render*, so at the moment `init` runs
there is no application, and `screenSize()` would refuse — it is guarded by
`requireRunning`.

So the size is an event, `Resized { cols, rows }`, which is the answer the rest
of this API would have given anyway. It arrives once immediately after startup
and again on every change, the model keeps it in a field, and `view` lays out
against it. The first render happens before it, at whatever default the model
was written with; nothing is on screen yet at that point, and driving the thing
at 100x30 shows the finished layout with no flicker.

It is the first event the model is told that it did not cause. Every other one
is the user doing something.

### The desktop's size, not the screen's

`tv.screenSize()` returns 80x25 for an 80x25 terminal. A window's rectangle is
in *desktop* coordinates, where `y = 0` is the row below the menu bar, so a
model handed the screen size has to subtract the menu bar and the status line
itself — which is precisely the arithmetic this exists to remove. `Resized`
carries `deskTop->size`, and 80x25 arrives as 80x23.

That leaves `screenSize()` superseded rather than missing. It is now in the
consistency check's small exempt list, next to `log`, with the reason written
down: an exemption that says why is a decision, and one that does not is a
silenced check.

### Polling the pump beats hooking the event

A resize reaches Turbo Vision as `evCommand`/`cmScreenChanged` from a
`WINDOW_BUFFER_SIZE_EVENT`, and `TProgram::handleEvent` answers it with
`setScreenMode(smUpdate)`. Hooking that is possible and is the wrong place:
`setScreenMode` can also be called by anything else, and the notification would
fire from inside TVision's own event dispatch, which is the shape the queueing
rule exists for.

`flushResize()` compares `deskTop->size` with the last size reported, at the
pump's safe point, beside `flushFocused` and `flushScrolled`. Two integers once
per pump. It is true no matter how the resize happened, it needs no queue
because the safe point *is* where it runs, and initialising the remembered size
to zero is what makes the first pass after startup report the real size with no
special case for startup at all.

### Adding a variant to `Event` is a breaking change, and that is the point

Three examples stopped compiling: `ascii`, `forms` and `demo`, each with an
exhaustive `when` over `Event`. That is Gren doing its job — a program that
silently ignored a new event would be the worse outcome — and the fix is one
branch each. `demo`'s is not a stub: its event viewer is a window that names
every event it sees, so it now prints `Resized 120x40`, which makes the third
example that watches the API from inside also the one that watches this.

### The harness had never resized a terminal

`Pty` fixed the pty at 80x25 in its constructor and `display()` replayed the
whole byte stream through a fresh 80x25 emulator on every call. Resizing needs
three things: the `TIOCSWINSZ` ioctl a real terminal emulator does, the
`SIGWINCH` the kernel sends with it — without the signal the size changes and
nothing notices — and an emulator that survives the replay.

The replay is the interesting one. A grid that changed size partway through
would have to be rewound, so instead it is built at the largest size the
terminal ever had, which everything written before a resize fits in, and then
cropped to the current size. The crop is not cosmetic: without it a terminal
that *shrank* still showed what it drew when it was bigger, because TVision
only repaints inside the current size and the old cells were still in the grid.

## Closing gap 2: views that grow with their window

The entry above narrowed this to a sentence: `growMode` already exists, Turbo
Vision already resolves it in `TGroup::changeBounds`, and every view here is
built with it set to zero. So the work was to decide how a `View` says it, and
then to find out why saying it changed nothing.

### An opt-in wrapper, because most views do not want one

The obvious shape is a `grow` field on all nine view records. That is uniform,
and it costs forty-nine literals across fourteen examples plus a `grow = fixed`
on every static text in every trivial program, forever. The alternative is a
constructor that wraps another view:

```gren
Grows
    { grow = Tui.stretch
    , view = ListBox { id = "entries", rect = ..., items = ..., focused = 0 }
    }
```

Nothing that does not care says anything, which is the right default because
most views genuinely do not care. It encodes as a `grow` field on the view it
wraps, so the runtime and the C++ never see a `Grows` at all — the differ
treats it as one more structural field, and `buildItems` reads it in one place
before `insert`.

Gren caps a variant at one argument, so it takes a record. That turned out to
read better than the two-argument version it replaced: every other constructor
of `View` takes a record too.

`Grow` itself is four booleans, one per edge, named `left`/`top`/`right`/
`bottom` rather than `gfGrowLoX` and friends, with `stretch`, `pinRight`,
`pinBottom`, `stretchWidth`, `stretchHeight` and `fixed` for the combinations
worth naming. `gfGrowRel` is deliberately not offered: rescaling an edge to the
same *fraction* of its owner is what a window on the desktop wants, and inside
a window it turns a one-row caption into a proportion of the window's height.

### The exemption that had to earn itself

`Grows` is the first constructor of `View` with no wire type, so
`check_consistency.py`'s four-layer walk had to be told about it — and an
exemption is exactly the kind of thing that quietly turns a check into
decoration. So it comes with a check of its own: that `encodeViewFields` really
has a branch unwrapping it, that `Tui` really emits a `grow` field, and that
`views.cc` really reads one. Break any of the three and the walk fails by name.
Verified by breaking each, which is the only way to know a check works.

### And then it did nothing, because the window was being rebuilt

Wrapping the views, rebuilding, resizing the terminal from 100x30 to 120x40:
the window grew and the button stayed exactly where it was, as if nothing had
been added at all.

`sameShape` compared the window's rectangle, so a model that lays out against
the terminal size sends a new rectangle on every resize and the differ **closed
the window and built it again**. Every child is then constructed fresh at the
rectangle the model wrote down, and `changeBounds` — the only thing that
resolves `growMode` — never runs at all. `growMode` is a rule about a window
that changes size, and rebuilding is not changing size.

So a window's rectangle stopped being structural, exactly as its title already
had. `tv.setBounds(id, rect)` calls `TView::locate`, which is what the frame's
own resize handle calls: it clamps to `sizeLimits`, calls `changeBounds`, and
repaints what the window uncovered. Rebuilding was also throwing away which
view had the caret, where a list was scrolled and which row was highlighted, on
every resize; that is now a patch and they survive.

The half of `sameShape` that had to stay is the half that makes Tile and
Cascade work: the comparison is against *the spec last applied*, not against
the screen. Turbo Vision moves windows without telling anyone, the model goes
on sending the rectangle it started with, the two match, and nothing is sent.
That invariant is what `examples/demo` exists to protect, and there is now a
unit test for it beside the new one rather than only a pty test.

### Two paths, and only one of them involves the model

`drive_entries` checks both, because they are genuinely different mechanisms
that happen to produce the same picture:

  - **the terminal resized** — the model is told, re-lays-out, sends new
    rectangles, the differ resizes the windows in place, and `changeBounds`
    moves the children. The model is in the loop.
  - **the frame's zoom box clicked** — Turbo Vision's own command. It never
    reaches the model, so every rectangle the model goes on sending is the one
    it was already sending and the differ has nothing to do. `growMode` is the
    *only* mechanism here, and it is the case gap (2) was actually written
    about: "a tiled window shows a clipped canvas rather than a stretched one".

The second is the better test for exactly that reason, and it is also the one
that proves the first invariant still holds: the clock guarantees a render a
second, and none of them undoes the zoom.

## Closing gap 8's read half: the model is told, not asked

`tv.getValue(id)` reads a live input line, list highlight, check box cluster or
radio button, and had never been reachable — the fifth thing the new
consistency check found. Making it reachable would have meant the protocol's
first query-and-response. It does not have one now either: the answer was to
tell the model instead, with a `Changed` event, which is the shape `Focused`
and `Scrolled` already set and leaves every message one-way.

So `getValue` is superseded rather than plumbed, and joins `log` and
`screenSize` in the consistency check's exempt list — three names, three
written reasons. An exemption that says why is a decision; one that does not is
a silenced check.

### There is no one method every edit goes through

`TInputLine` has no notification of its own, and no single place to hook: a
character, Backspace, Ctrl-Y, a paste and a click that moves the caret all land
in `handleEvent` and nowhere else in common. `TCluster` is the same — a box is
toggled by Space, by a click, by its hotkey and by the arrows moving the
selection.

So the comparison is made *around* `handleEvent` rather than inside anything:
what the value was, let the base class do whatever it does, what the value is
now. That cannot miss a route because it does not know about routes. Three
subclasses, four lines each.

`Value` is three shapes because three kinds of control have a value the user
can move and they are not the same kind of thing: `Text` for an input line,
`Flags` for a check box cluster, `Choice` for radio buttons. They arrive as a
JSON string, array and number, which are distinct enough that the wire does not
have to say which.

### And then the model wrote the user's keystrokes back over them

A model that is told what was typed keeps it — that is the point of being told
— and renders it straight back. The differ compares that against the value it
last *applied*, sees a difference, and calls `setValue`, which ended in
`selectAll(True)`. The field the user is typing in becomes a selected block and
their next keystroke replaces all of it.

This is the controlled-input problem every virtual DOM has, and the first half
of the answer is the same one: what the *view* last reported is what the next
render is compared against. `differ.valueChanged(id, value)` records it before
the model is asked.

That is correct and it is not sufficient, which the pty test found by typing
two characters in one write:

```
VALUECHANGED filter "o"
VALUECHANGED filter "or"
SETVALUE filter "or" -> "o"     <- the render for the first keystroke, late
SETVALUE filter "o" -> "or"
VALUECHANGED filter ""          <- one backspace, on a field left selected
```

Both characters were read in one pass of the pump, so two notifications went
out before either render came back, and the render carrying `"o"` arrived after
the field already said `"or"`. Renders always lag — a port send does not run
the model synchronously — so any two keystrokes close enough together race.
Typing quickly is close enough. So is pasting.

Two fixes, and both are improvements on their own:

**Changes flush once per pump, not once per event.** The other notifications
drain after every event, deliberately, so that a callback cannot re-enter
TVision mid-event. Changes are already collapsed per id, so draining them at
the end of the pump instead makes a burst of keystrokes one notification and
therefore one render. That is also the difference between the model's answer
arriving before the next keystroke and arriving after it.

**A value the model sets no longer selects.** `selectAll(True)` is Turbo
Vision's convention for a value handed to a field the user has not touched, and
it is right there — `buildItems` still uses it for a field's initial value. It
is wrong for a value that arrived because the model was echoing back what was
just typed. `setValue` now writes the text, puts the caret at the end and
selects nothing, so a stale write costs a repaint and nothing else. It is also
the right answer for the deliberate case: a model that transforms what was
typed wants the caret after the transformation, not the whole field selected.

The pty test types both characters in one write on purpose, because that is the
arrangement that fails.

### A dialog's fields report too, and the id is load-bearing

The first version of the filter box in `examples/entries` matched on the value
and not on the id. The Add dialog has an input line as well, its keystrokes
arrive as `Changed` like any others, and typing a new entry filtered the list
down to the entry being typed. Every event in this API carries an id and this
is the one where ignoring it is a live bug rather than an untidiness.

Reporting from inside a dialog is right, though: it is where validation as you
type belongs, and it is what a `TValidator` would have been for. The
keystroke-level half of gap (8) — rejecting a character outright, before it
reaches the field — is still missing, and is now the only part of that gap that
is.

### Where it is demonstrated, and where it was found

`examples/forms` is the port that walked into this: its values are collected
when the form dialog is answered and at no other moment. Every editable control
it has is in that dialog, so it has nothing to do with a `Changed` before then,
and its branch says so.

`examples/entries` is where it is demonstrated, because a filter box is the
smallest honest thing that could not be written before: a control in an
ordinary window, driving the list next to it, on every keystroke. Its list is
keyed by the row's text rather than its index, so narrowing it needs no
bookkeeping about where a row went.

The three C++ paths are tested one level down, in `tvision-node`'s own
`drive_form.py`, which already types into a field, toggles a check box by
hotkey and can move a radio button, and now reads all three out of the log.

## Closing gap 5: a message box the package builds

`tv.messageBox()` was the last name the reachability check printed, and closing
the gap added nothing to the protocol. That is the whole point of it.

### The one gap whose answer was "write it in Gren"

Turbo Vision's `messageBox()` is a library function because it has to be: it
calls `execView`, the nested modal loop milestone 2.5 removed, so a program
cannot express it. The JavaScript binding has its own for the same practical
reason — `tvision-node` is a package people use from JavaScript, and
`examples/hello.js` and `examples/demo.js` both call it.

None of that applies on the Gren side. A message box *is* a dialog: a static
text, a row of buttons, and a rectangle. Every one of those already crosses the
port. So `Tui.messageBox` returns a `DialogSpec` — a value, which the caller
hands to `Tui.dialog` like any other — and the answer arrives as an ordinary
`DialogClosed` carrying the id it was opened with. No message, no event, no
protocol version. `examples/demo`'s About box was fifteen lines of hand-built
dialog and is now five lines of spec, which is the argument in one diff.

That leaves `tv.messageBox()` reachable from JavaScript and not from Gren, on
purpose, and it is the fourth name in the consistency check's exempt list. Four
out of twenty-two exports, each with a written reason, and the check now prints
no coverage notes at all — every function the binding exports is either
reachable or deliberately not.

### It could not have been written two commits ago

A message box centres itself, a dialog's rectangle is in desktop coordinates,
and until the `Resized` event nothing in a pure `view` function knew how big
the desktop was. So `desktop` is a field on the spec and the model passes the
size it was last told:

```gren
Tui.dialog tui <|
    Tui.messageBox
        { id = "confirmClear"
        , title = "Clear"
        , text = "Throw away all " ++ String.fromInt n ++ " entries?"
        , buttons = Tui.yesNoButtons
        , desktop = model.desk
        }
```

The JavaScript one calls `screenSize()` and is a row out because of it: it
centres against the *screen* and then places the result in desktop
coordinates, so an 80x25 terminal puts the box one row below centre. Nobody
noticed, and nobody would; it is worth writing down only because the Gren
version gets it right by having been given the right number rather than by
being more careful.

### `"yes"` and `"no"` were already built-in names

A message box needs its buttons to dismiss it, and nothing in `Tui` does that
— a button sends a command and the model decides. The four that close a dialog
by themselves are `cmOK`, `cmCancel`, `cmYes` and `cmNo`, and all four have
been in `CommandRegistry`'s builtins table since the `watch` example put them
there. So `okButtons`, `okCancelButtons`, `yesNoButtons` and
`yesNoCancelButtons` are four arrays of two fields, and `TDialog::handleEvent`
does the rest.

The sharp edge is documented rather than fixed: a button whose `cmd` is
anything else does not close the box, which is a message box you cannot
dismiss. It is the same reserved-vocabulary trap the built-in command names
already had, one level up.

### Two examples, because a message box is two different things

`examples/demo` gets the informational one — its About box, which was already a
dialog and is now the helper, so the diff is the fifteen lines disappearing.

`examples/entries` gets the confirmation. `Clear` threw away every entry with
no question asked, and now asks; `Yes` and `No` come back as `DialogClosed`
with the id, which is how the model tells that answer from the Add dialog's.
The model needs no "am I asking?" flag, because the id it opened the box with
is the id that comes back.

## Closing gap 4: asking for a path

`TFileDialog` and `TChDirDialog` are how a Turbo Vision program asks for a
path, and this was the last gap that had never had its design decided —
`examples/dir` and `examples/viewer` both took theirs on the command line, and
`tvdir`'s Change Dir half was the one part of it not ported.

The gap list guessed the answer and the guess held: neither is a class worth
wrapping. `Tui.fileDialog` is a function returning a `DialogSpec`, the shape
gap (5) established, and it added nothing to the protocol.

### The model does the reading, so the dialog is two steps

`TFileDialog::readDirectory` runs inside the dialog, from its constructor and
again whenever the wildcard changes. There is no equivalent here and there
should not be: `FileSystem.listDirectory` is a `Task`, so the model reads the
directory and hands over what it found. `Alt-C` in `examples/dir` is therefore
a `Cmd` that produces a `Msg` that opens a dialog — read, then show — and the
helper never touches the filesystem at all.

Which makes `fileDialog` a *layout* and almost nothing else: where the field
goes, where the list goes, where the buttons go. What the entries say, whether
`".."` is among them, and what a name means are the program's business. That is
the same answer `TOutline` got in `dir` and `TScroller` got in `viewer`, for the
third time: the C++ class is a widget because C++ had nowhere else to put the
state.

### Navigating is a reopen, and that is a real cost

A window is part of `view` and is diffed. A dialog is a `Cmd` that produces a
`Msg`, and nothing patches one while it is up — the differ walks
`message.windows` and a dialog is not among them. So walking into a directory
cannot change the list in place. It is a second listing and a second dialog,
which in `update` is the same two lines that opened the first:

```gren
if closed.cmd == "yes" then
    { model = model, command = browse model chosen }
```

That is genuinely fine to write and it blinks on screen, and both halves are
worth saying out loud. A program that wants a file browser that never blinks
wants a *window*, not a dialog, and would then be writing its own — which is
allowed, and is what the helper being a plain function makes easy.

### Only four button names close a modal

`TChDirDialog` has Chdir, Revert, OK and Cancel; `TFileDialog` has Open,
Replace, Clear and Cancel. Here a dialog is ended by `cmOK`, `cmCancel`,
`cmYes` and `cmNo` and by nothing else — `TDialog::handleEvent` says so, and
the protocol has no "close that dialog" message for the model to send. A button
with any other command name is drawn, is pressable, sends its command, and
leaves the dialog open.

So a dialog gets at most four buttons, and `examples/dir` spends three of them:
Open is `"yes"`, Chdir is `"ok"`, Cancel is `"cancel"`. Naming a navigation
button `"yes"` reads oddly and is not a mistake — it is the reserved vocabulary
the built-in command names already established, one level up, and this is the
first thing that ran into its ceiling.

### What the answer carries

Two of the `values` matter, under ids the helper fixes rather than derives:

  - `Tui.text "fileName"` — what was typed.
  - `Tui.number "fileList"` — which row was highlighted, as an index into the
    `entries` that were passed in.

The index rather than the text, because the model already has the array it
handed over and can look the row up in it — which is how `dir` turns a
highlighted row back into a `Path` without parsing anything. Fixed ids because
only one modal can be open at a time, so a name you can write down beats a name
you have to construct; the cost is that a view in an open window must not use
either of them, and the docs say so.

### What is still missing, and it is not much

`THistory` — gap (6), the drop-down beside the field that remembers what was
typed before — is in every real `TFileDialog` and is not here. A wildcard is
not either: `TFileDialog` filters on `*.txt` and the model would do that to its
own array before passing it in, which is a line of `Array.keepIf` rather than a
feature. Neither stopped `tvdir`'s Change Dir from being ported, which is the
thing this gap was actually blocking.

## Closing gap 6: a widget worth wrapping, at last

`THistory` is the small `▐↓▌` beside an input line that drops down what was
typed into it before, and the gap list asked the question `TOutline` had
already answered once: is this a widget to wrap, or a `ListBox` in a small
window plus a field on the model?

Four times running the answer had been "not a widget" — `TOutline` in `dir`,
`TScroller` in `viewer`, `TFileDialog` and `messageBox` as package helpers that
return a `DialogSpec`. This is the first time the answer is "wrap it", and the
reason is worth having written down, because it is a property of the *shape* of
the thing and not of how much C++ it happens to contain.

### The package-helper shape cannot reach inside a modal

`Tui.messageBox` and `Tui.fileDialog` work because a dialog is a `Cmd` the
model issues and a `Msg` the model receives. A history drop-down opens over a
field that is very often *inside a dialog that is already open* — and while a
modal is up, `update` is not what is driving the screen. There is no `Cmd` the
model could issue at that moment and no `Msg` it could be answered with,
because the thing that would have to ask for it is a click on an arrow three
columns wide that the model is never told about.

So the drop-down has to be a view. That is the rule the four earlier answers
were really following, stated properly: a helper works when the interaction
*begins* in `update`. When it begins inside a widget, it is a widget.

### The list is Turbo Vision's, in one buffer, behind your back

`historyAdd`, `historyStr` and `historyCount` (`histlist.cpp`) are the whole of
Turbo Vision's history. They read and write **one** `calloc`'d block, shared by
every field in the process, keyed by a `uchar` the caller picks by hand, and
when it fills, `insertString` shifts the oldest records off the front and they
are gone. `THistory::recordHistory` writes into it from `handleEvent` — on
`cmReleasedFocus`, so simply tabbing out of a field appends to it.

None of that is reachable from a Gren model. It cannot see the list, cannot
bound it, cannot save it, and cannot decide what belongs in it. So none of it
is used: `JsHistoryViewer::getText` reads a `std::vector<std::string>` that
arrived with the render, and `recordHistory` is overridden to do nothing at
all.

**The widget shows the list; the model decides what goes into it.** That is a
better widget, not a compromise, and both examples make the point by
remembering something Borland's could not have: `dir` remembers the directories
Chdir was actually *answered* with, and `entries` remembers a filter only when
the user chose something out of the filtered list. Neither is "whatever was in
the field when focus left". And because the list is a value in the model, it
could be written to a file and read back at startup, which a history block
never could.

### The one line that had to go, and the machinery it needed

`THistory::handleEvent` ends with `owner->execView(historyWindow)`.

Milestone 2.5 took `execView` out of this binding on purpose: `TGroup::execView`
is twenty lines of bookkeeping around one nested `p->execute()` loop, and that
loop would run *inside* the pump's own `target->handleEvent(event)` call. Node's
event loop would stop for as long as the drop-down was open — no timers, no
promises, no subscriptions, no renders. "Modal means input goes here, not that
the process stops" is the single property the whole modal design exists to
preserve, and a widget that quietly reintroduced a nested loop would have
broken it in the one place nobody would think to look.

The fix is that the modal stack already existed and only needed a second way
in. `ModalSession` gained an `onDone` callback beside its promise — exactly one
of the two is ever set — and `openLocalModal(host, view, done)` pushes a view
onto the same stack `tv.dialog()` uses, with a C++ continuation instead of a
`Napi::Promise::Deferred`. `closeTopModal` calls the continuation while the view
is still alive, which is what lets `getSelection()` be read out of it, and
destroys it afterwards.

`drive_entries.py` asserts the point directly: the clock's tick counter is read
before and after a three-second pump *with the drop-down open*, and it moves.
That check is the reason this widget is thirty lines of C++ rather than three.

Two consequences fell out of reusing the stack rather than nesting:

  - **A dangling `this` became possible, and had to be designed away.** The
    model really is still running behind the drop-down, so it can close the
    window the field lives in while the list is up. The continuation therefore
    captures the history view's **id**, not `this`, and looks it up in the
    registry when it fires — `~JsWindow` clears the registry, so a lookup that
    finds nothing is the entire check.
  - **Clicking the drop-down's close box is safe for free.**
    `TWindow::handleEvent` already answers `cmClose` with `endModal(cmCancel)`
    rather than `close()` when `sfModal` is set, and `beginModal` sets it.

### No rectangle, and no protocol change

A `History` is the one view with no `rect`. Every Turbo Vision dialog puts the
icon in the three columns immediately right of its field (`tfildlg.cpp:75`,
`tchdrdlg.cpp:51`), which makes the rectangle a consequence of the `for` field
rather than a decision — the same rule a `ListBox`'s scroll bar already
follows, and one fewer thing an author can get wrong. It does still take a
`Grows` wrapper, and `entries` needs one: its filter box stretches with the
window, so the arrow glued to it has to move with `pinRight` or the two overlap
at the second size.

Nothing was added to the protocol. Choosing an entry writes into the input
line, so what the model is told is a `Changed` event **on the field** — because
that is what happened. `setItems` grew a second `kind`, and that is the whole
of the new surface.

The last small thing: an entry chosen from the history arrives *selected*
(Borland's `link->selectAll(True)`), where a value the model sets deliberately
does not. That looks like an inconsistency and is the opposite of one — the
user picked a whole entry and the next keystroke is meant to replace it, which
is exactly the argument `setInputTextKeepingCaret` makes in reverse. There is a
check for each.

## Closing gap 7: a context menu, and the loop the menu bar has always had

`TMenuPopup` is Turbo Vision's right-click menu, and the entry for this gap
said the menu machinery was all there and what was missing was a way to open
one at a point. Both halves turned out to be wrong: the way to open one was the
easy part, and the machinery is where the problem is.

### The menu bar freezes the whole program, and always has

`TMenuView::execute()` (`tmnuview.cpp:179`) is two hundred lines built around
`getEvent(e)` at the top of a `do ... while`. `TMenuBar::handleEvent` reaches it
through `do_a_select`, which means that when a pull-down is open, that loop is
running **inside the pump's own `target->handleEvent(event)` call**, and Node's
event loop is not running at all.

Measured in `examples/entries`, whose clock is a plain `Time.every`
subscription:

    control, nothing open:    ticks 1 -> 5 over 3.5s
    with a pull-down open:    ticks 5 -> 5 over 3.5s
    after Esc:                ticks 6 -> 9

Nothing is lost — the timers and the I/O are queued and fire when the menu
closes — but for as long as a menu is down, every subscription, every promise
and every render in the program is stopped. Nobody had written this down, and
it is the exact defect the history drop-down went out of its way to avoid one
commit earlier.

It is not fixed here, and the reason is a trade rather than an oversight.
Making it go away means reimplementing `TMenuView::execute` as a state machine
the pump can step: five flags carried across iterations (`autoSelect`,
`firstEvent`, `itemShown`, `lastTargetItem`, `mouseActive`), `putEvent`
re-injection in three places, and a recursive `owner->execView(target)` in the
middle for submenus. It is the least documented and most fiddly code in Turbo
Vision, every menu in every example runs through it, and what it buys is a
one-second freeze while somebody looks at a menu. So it is written down here
and in `examples/README.md`, and nothing new was built on top of it.

### Which is why a context menu is flat

`TMenuPopup::execute()` *is* `TMenuView::execute()`. Using it would have
widened the hole rather than left it where it was.

So `JsMenuPopup` is a `TMenuBox` — kept for the drawing, which is the part
worth having: the frame, the hotkey underlining, the right-aligned shortcut
column and the menu palette are all its — with a `handleEvent` of its own and
no `execute` anywhere. It goes on the same modal stack `tv.dialog()` and the
history drop-down use, so it is driven by the pump like everything else, and
`drive_demo.py` checks the clock against it: the status-line clock keeps
ticking with the menu open, which is the assertion the whole class exists for.

**A submenu is the recursion.** `PopupItem` has `Entry` and `Divider` and no
`SubMenu`, because a submenu in Turbo Vision is a menu opened by
`owner->execView` from inside the loop running the menu above it — which is
precisely the thing not being done here. Without them the state machine is a
highlight, a click and two keys, and that is short enough to be obviously
right. `TEditor::initContextMenu` (`teditor2.cpp:102`) is Cut, Copy, Paste and
Undo, so Turbo Vision's own only context menu is flat too. The type makes it
unexpressible and the binding throws on one anyway, because the wire shape is
shared with the menu bar's.

### A modal view is not always a group

This is the bug that was waiting rather than the one that was found. The pump
computed its target as

    TGroup *target = g_modals.empty() ? (TGroup *) g_app.get()
                                      : (TGroup *) g_modals.back()->view;

and then read `target->endState`. `endState` is a member of **`TGroup`**, not
`TView` (`views.h:919`) — and so is `eventError`. Every modal on the stack had
been a `JsWindow` or a `THistoryWindow`, both groups, so the cast had always
been true. A `TMenuBox` is not, and reading `endState` off one reads past the
end of the object.

`TView::endModal` gives the same result from the other side: it forwards to
`TopView()->endModal(command)`, and for a plain view that is `TView::endModal`
again — an infinite recursion. Turbo Vision's modality is group-only by
construction, which is *why* `TMenuView::execute` is a loop and not a modal
view.

So the session owns the answer now instead of the pump assuming it:
`ModalSession::endState()` reads `TGroup::endState` for a group and its own
`ended` slot for anything else, `endLocalModal(view, command)` sets that slot,
and `target` is a `TView *`. `handleEvent`, `valid` and `eventError` were the
only other things asked of it, and only the last is a group's.

### What comes back is a command, and nothing else

Choosing an entry puts an `evCommand` back on the event queue — which is what
`TMenuView::do_a_select` does with the command its own loop returned — rather
than reporting anything of its own. Two things fall out of that and both are
the point. A built-in name like `"quit"`, `"close"` or `"zoom"` is handled by
`TApplication` exactly as it would be from the menu bar, without a round trip
through the model. And a name of the model's own arrives as an ordinary
`Command` event, indistinguishable from the same entry on the menu bar or its
function key. `examples/demo`'s menu is three of Turbo Vision's own window
commands and `update` handles none of them; `drive_demo.py` checks that Zoom
zoomed *and* that nothing about it reached the model.

`Esc` and a click outside end it with `cmCancel` and send nothing. An entry
whose `cmd` is `"cancel"` is therefore indistinguishable from `Esc`, which is
correct rather than a collision.

### The right button had to cross the port

`Clicked` gained `isRight`, which is the other half of protocol 9: a context
menu is opened by the model, and until now the model was never told which
button was pressed. The coordinates were already right — `Clicked` reports in
the *view's* own coordinates, and `popupMenu` takes a view id and a point in
it, so opening a menu where the user clicked is the click event handed straight
back with no arithmetic.

One inherited surprise, and it is the "two clicks, not one" rule again: the
first right click on an inactive window is spent activating it, because
`TView::handleEvent` selects on `evMouseDown` whichever button it was. Both
`drive_demo.py` and anyone using this will click twice.

## Closing gap 8's other half: the model declares, it is not asked

`TFilterValidator` rejects a character before it reaches the field. The gap
entry framed that as something the model "is still never offered", and the
framing was the mistake: offering it would have been the first
question-and-answer this protocol ever carried, and there was no need.

**`allowed` is a set of characters on the view, not a callback.** The model
says what the field takes; a keystroke outside the set does not happen; nothing
is reported, because nothing happened. Every other message in this protocol is
one-way and this one is too — it is a *field*, which is one-way by
construction.

That is worth stating plainly because the obvious design was the other one: an
event carrying the keystroke, an answer carrying yes or no, and a field that
has to sit still until the model replies. It would have worked and it would
have made every keystroke a round trip through Gren, at which point a slow
model shows up as a laggy input line.

### Half of TFilterValidator is a nested loop, and it is overridden away

`TValidator` has two jobs and `TInputLine` uses them at two different moments.
`isValidInput` runs from `checkValid` after every edit and is the filter.
`isValid` runs from `TInputLine::valid()` when the dialog is answered and, on
failure, calls `error()` — which for every stock validator is `messageBox()`,
which is `execView()`, which is the nested loop the menu bar already has too
much of.

`JsFilterValidator::isValid` returns `True` unconditionally. Two reasons, and
the second is the better one. The loop is one. The other is that the only way a
field can hold a character its own filter rejects is for the **model** to have
put it there with a `value`, and a value the model set is the model's to
validate — a binding that blocked the dialog over it would be second-guessing
the program. So `allowed` filters typing and only typing, and the docs say so.

`TRangeValidator` and `TPXPictureValidator` are not wrapped and this is why.
The *filtering* half of a range validator is `allowed = Just "+-0123456789"`,
which is already here; the checking half is one `String.toInt` in `update` when
the dialog is answered, and doing it there gets a message the program wrote
rather than "Value not in the range 0 to 100" in a box the model cannot see.

## Closing gap 9: TMultiCheckBoxes, and the 32 bits behind it

A cluster whose boxes have more than two states. Small, and listed so it would
stop being a surprise; it turned out to be exactly as small as advertised, with
one thing worth knowing.

`TMultiCheckBoxes` reuses `TCluster::value` — a single 32-bit word — for
*every* box's state at once, which is why its constructor takes two numbers
nobody would guess. `selRange` is how many states there are, and `flags` packs
the low byte's bit mask together with the high byte's bits-per-item:
`(bits << 8) | ((1 << bits) - 1)`. Both are derivable from one thing the model
was going to give anyway — the marks, one character per state, drawn between
the brackets — so `JsMultiCheckBoxes` derives them and the Gren side never sees
either.

The packing is also a real ceiling: *items* × *bits per state* must fit in 32,
which is eight boxes of four states or sixteen of three. The builder throws
with both numbers in the message rather than silently dropping the boxes that
do not fit, which is what the bit shift would otherwise do.

`Value` gained a fourth shape, `Marks (Array Int)`, and `Tui.marks` reads the
same thing out of a dialog's answer beside `text`, `number` and `flags`. The
decoder tries `Flags` before `Marks` on purpose: an array of booleans is also
an array, and check boxes are the commoner control.

### And it found an upstream bug, which is what ASAN is for

`TMultiCheckBoxes` copies its `states` string with `newStr()` -- `new char[]`
-- and frees it in its destructor with plain `delete` (`tmulchkb.cpp:62`).
That is an alloc/dealloc mismatch, and AddressSanitizer does not warn about it,
it *stops the process*: the first ASAN run of `drive_forms.py` failed at
"Escape closed the form" and at everything after it, because closing the dialog
killed the program.

Worth knowing for two reasons beyond the fix. It is invisible in an ordinary
build -- `test` was green through the whole of this and `test:asan` is the only
thing that could have caught it, which is exactly the argument for running it
on anything that touches C++. And it is the second thing this port has had to
report upstream, after [#229](https://github.com/magiblot/tvision/issues/229)
-- but the first in the *library*: #229 is two findings in `calendar.cpp`,
which is a demo program.

**It is not one line.** Grepping the library for the same shape -- a pointer
filled by `newStr()` or `ipstream::readString()`, both of which use
`new char[]`, and freed with plain `delete` -- finds seven:

    tmulchkb.cpp:62   delete states       (newStr :27, readString :41)
    tevent.cpp:104    delete pasteText    (new char[] :332)
    tstatusl.cpp:270  delete t            (readString :264)
    tdircoll.cpp:167  delete txt          (readString :164)
    tdircoll.cpp:168  delete dir          (readString :165)
    colorsel.cpp:573  delete nm           (readString :569)
    colorsel.cpp:592  delete nm           (readString :588)

`tevent.cpp` is the one that settles what kind of mistake it is: the same
`pasteText` buffer is freed with `delete[]` at line 328 and with plain `delete`
at line 104, in the same file. Five of the seven are on `ipstream` read paths
that a program using the library normally never reaches, which is why they have
survived; `TMultiCheckBoxes`' is in an ordinary destructor, which is why this
was the one to fire.

Reported as
[magiblot/tvision#230](https://github.com/magiblot/tvision/issues/230), with
all seven and a one-line fix for each.

**The workaround stays anyway.** The local `tvision/` checkout carries the fix
on a branch, and `test:asan` is green with or without it -- but `tvision/` is
gitignored, so anyone building this repo gets upstream `master`, and a
`JsMultiCheckBoxes` that only works against a patched library would be a worse
kind of bug than the one it fixes. It comes out when the fix lands upstream and
the checkout this repo builds against has it.

The workaround is in the subclass, and there is no other place for it:
`tvision/` is an upstream checkout this repo does not own. `JsMultiCheckBoxes`
passes a **null** `states` to the base -- `newStr(nullptr)` returns 0, so the
destructor frees nothing -- keeps the marks in a `std::string` of its own, and
overrides `draw()` to hand that to `drawMultiBox()`. `TMultiCheckBoxes::draw()`
is one line and that line is what it does, so nothing is lost.

## Closing gap 10: a view on the application

`TClockView` and `THeapView` are inserted into `TProgram`, not into
`TDeskTop`. That is not an implementation detail — the desktop is the patterned
area windows live in, and a clock in the corner is not in it — and `Ui` had a
menu bar, a status line and windows with nothing in between.

`Ui.overlays` is that missing place: an `Array View` in **screen** coordinates,
drawn above every window, uncoverable by one, never tiled or cascaded. The
whole of the binding is one function, `tv.overlays(items)`, because
`buildItems` only ever needed the group to be a `TGroup` rather than a
`JsWindow` — it was already writing into one.

Three things that fell out.

**The status line was the workaround and it cost a repaint a second.**
`examples/demo` kept its clock as a status item, which works because a status
item with no command is a hint. But a status line is replaced *whole* — there
is no patching an entry — so a clock in one rebuilt the entire status line
every second. That is precisely why Borland made the clock a view, and the note
saying so has been in this file since the demo was ported. The clock is now one
`StaticText` in `overlays`, patched.

**Growing works because `Grows` already did.** `TClockView` sets its own
`growMode` in its constructor so it stays in the corner when the screen
changes; here the same thing is `Grows { grow = Tui.pinRight, ... }`, the
wrapper gap (2) built, applied to a view that is not in a window. Nothing had
to be added — `growModeOf` runs on every view the builder makes, whatever group
it is going into.

**Screen coordinates are not desktop coordinates**, and this is the one trap.
Everything else in this API that has a rectangle is in the desktop's frame, and
`Resized` reports the desktop's size — which is the same width but two rows
shorter. An overlay on row 0 is on the menu bar's row, which is where a clock
goes; an overlay at `rows - 1` would be under the status line. The docs say so
and `examples/demo` lays out against `cols` and row 0 to make it concrete.

The set is rebuilt whole when its shape changes and patched by id when it does
not, which is the same rule a window's contents follow. Without the patching
half, a clock rendering once a second would destroy and rebuild the corner of
the screen forever — the exact cost the status line was already paying.

## The tvedit milestone: where the state stops being the model's

Fourteen examples put the state in the model and re-rendered it, and every one
of them was an argument that a `TView` subclass is a widget because C++ had
nowhere else to put its state. `TOutline`, `TScroller`, `TTerminal` and
`TFileDialog` all went that way. The editor does not, and the reason is not the
one the coverage list guessed.

The list said: "Sending the whole buffer over a port on every keystroke is the
Elm answer and probably fine for real files, but the diff is per-view, not
per-character, so every keystroke would resend the document." That is the
view→model direction and it is the smaller half. The bigger half is the other
one: **`view` runs on every tick of every subscription.** A `text` field on an
editor would serialise the whole file into the render message once a second for
as long as a clock is running, whether or not anybody touched it. And a model
that owned the buffer would have to implement insert, delete, word-left, undo
and a clipboard — which is to say implement `TEditor`.

So the boundary moves exactly one step. **`TEditor` owns the buffer and the
model owns the file.** The document crosses the port twice per file, in through
`Tui.setEditorText` and out through `Tui.readEditor`, and what arrives in
between is an `Edited` event carrying `isModified`, `line` and `column`. Three
numbers per keystroke, coalesced at the pump like every other note, instead of
a file.

### `readEditor` is not the query this protocol has always refused

It looks like one, so it is worth being exact about why it is not. The thing
that was refused was `tv.getValue()` — a *synchronous read* the model would
have had to be able to call in the middle of deciding something, which Gren
cannot do and which is why `Changed` exists. `readEditor` is a `Cmd` that
produces a `Msg`, which is the shape `dialog` established at milestone 2.5 and
`fileDialog` and `messageBox` have used since. The message goes out, the
program carries on, and the document comes back as an ordinary event. Nothing
blocks and nothing is asked and answered inside one `update`.

The rule the protocol actually keeps is that **the render is one-way and the
model is told rather than asked**. A `Cmd` producing a `Msg` is an effect, and
effects are how Elm programs read the world.

### The one sharp edge: a rebuilt editor is an empty one

A view's rectangle is structural — change one and the differ closes the window
and makes it again. For every other view that costs a repaint and nothing else,
because the next render re-supplies the contents. For an editor it is
destructive: the new one is empty and the document is gone, because there was
never a copy of it in the render to put back.

The first version of `examples/edit` had exactly this bug, and
`drive_edit.py` caught it on the first run: the editor's rectangle was computed
from `model.desk`, so resizing the terminal silently emptied the buffer and the
next save wrote nothing. The fix is what gap (2) built `Grows` for — a fixed
rectangle and a `Grows Tui.stretch` around it — and the docs say so where
somebody would hit it.

It could be made impossible rather than documented, by teaching the differ to
patch a view's rectangle with `TView::changeBounds` instead of treating it as
structural. `sameShape`'s comment currently says "nothing can move one of those
but a rebuild", which is not true — `changeBounds` does, and it is what
`Grows` already runs. That is a change to how *every* view is diffed and the
scroll bars a view owns would have to move with it, so it is written down here
rather than done.

### What TEditor gave for free, and what it wanted

Free: insert and overwrite, selection, one level of undo, a clipboard shared
between editors (a `static TEditor *`), auto-indent, word motion, the whole of
Borland's keymap, Unicode-aware drawing and line-ending detection. The wrapper
is about a hundred lines and none of it is editing.

Wanted, and each is a decision:

  - **A real `setBufSize`.** `TEditor::setBufSize` returns `newSize <= bufSize`
    — it does not grow. Without an override the editor fills its initial 4KB
    and silently stops accepting text. `TFileEditor` has the growing version
    and that is most of what that class *is*; `JsEditor` has the same one, with
    the file half left out because reading a file is a `Task` in Gren.
  - **The buffer's allocator has to be consistent, and the base constructor
    gets there first.** `TEditor`'s constructor calls the virtual
    `initBuffer()` before `JsEditor` exists, so the first buffer is
    `new char[]`; the constructor here frees it with `TEditor::doneBuffer()`
    and allocates its own with `malloc`, which is exactly what
    `TFileEditor`'s does (`tfiledtr.cpp:56`) and for exactly that reason.
  - **`editorDialog` defaults to doing nothing**, which is the best possible
    default here. `defEditorDialog` returns `cmCancel` (`editstat.cpp:18`), so
    Find, Replace and the out-of-memory prompt put up nothing at all — and
    every one of them would otherwise be `messageBox`, which is `execView`,
    which is the nested loop the menu bar already has too much of. Nothing had
    to be done to avoid it. It also means Find and Replace are inert until
    something gives the editor a search string, which is the next piece of work
    rather than a bug.
  - **Scroll bars, like a list box's.** One in the column to the right and one
    in the row below, `ofPostProcess` so the keyboard reaches them. `TEditor`
    drives both itself.
  - **No `TIndicator`.** It is the line:column box Turbo Vision draws on the
    window frame, and the model can now say the same thing in a `StaticText`
    from the `Edited` event — which is better for the reason every display in
    these examples is better: what it says is the model's, and the model was
    told.

### The editor's commands are built-in names

`"editor.cut"`, `"editor.copy"`, `"editor.paste"`, `"editor.clear"`,
`"editor.undo"` and `"editor.selectAll"` are interned as `cmCut` and friends,
so a menu entry carrying one reaches whichever editor has the caret and never
passes through `update`. That is the same bargain `"tile"` and `"cascade"`
make, and `examples/edit`'s whole Edit menu is made of them: six entries, no
handler.

Two are deliberately absent, and they are absent for the same reason: each
needs something only the model has.

There is no `"editor.save"` because writing a file is a `Task` — which is what
makes `readEditor` necessary and is the clearest statement of where the line
is. `TFileEditor` is the class that would have handled `cmSave` itself, and not
wrapping it is the same decision one level up.

And there is no `"editor.find"` because `cmFind` does nothing without a search
string. `TEditor::find()` asks for one through `editorDialog`, which is
disabled here and for a good reason — every prompt it raises is a `messageBox`,
which is an `execView`. So a search is the model asking a question and then
issuing a command, the shape `dir`'s Change Dir already has.

### Searching is two steps, and the two-step shape has now happened four times

`Tui.findInEditor` and `Tui.replaceInEditor` are `Cmd`s answered by a
`Searched` event carrying how many matches were acted on. The model puts up its
own dialog, reads the string out of the answer, and issues the command; there
is nothing in the API for "search" that does not begin with the program asking
a question.

That is the same shape as `dir`'s Change Dir (list, then show), `edit`'s own
Save (read the editor, then write the file), and `entries`' Clear (ask, then
throw away). Four times now, and the rule behind all four is the same: **when
a command needs something only the model can produce — a path, a file, a
string, a yes — it is a command the model handles and answers with a `Cmd` of
its own.** Built-in command names are for the ones that need nothing.

None of `TEditor`'s own search machinery is used except the part that
searches. `find()`, `replace()` and `doSearchReplace()` all begin or end in
`editorDialog`, so what is left is `TEditor::search()` — which is public,
returns whether it hit, runs forward from the caret, and leaves the caret at
the *end* of the match it selected, so repeating it walks the document and a
replacement can never match itself. The replace loop is four lines out of
`doSearchReplace` with the per-occurrence prompt removed, because the prompt is
`editorDialog(edReplacePrompt)` and an inert one returns `cmCancel`, which
would stop the loop at the first match.

**One deliberate divergence.** `all = True` replaces every match in the
*document*, starting from the top. Turbo Vision's Replace All runs from the
caret, which makes it quietly depend on where the caret happens to be — and
after a Search again that ran off the end, "replace all" replaces nothing at
all. That is not what the word means. It cost one `setCurPtr(0, 0)`.

Turbo Vision's own `Ctrl-L` keeps working and is never told anything, because
the binding leaves `TEditor::findStr`, `replaceStr` and `editorFlags` set to
whatever the model last asked for. Search again in the menu is the *program*
issuing the same command a second time, which is what lets it say "not found"
in its own words; `Ctrl-L` does the same thing silently, which is Borland's
behaviour and is fine.

### And the reserved vocabulary reached its ceiling

The nine are prefixed, and the first version of them was not. That version
interned bare `"cut"`, `"copy"`, `"clear"` and the rest — and `devbox run test`
failed in two examples that have nothing to do with the editor.
`examples/demo`'s event viewer has a Clear button and `examples/entries` has a
Clear menu entry, both `cmd = "clear"`, both working for months, and both
silently stopped: the name interned as `cmClear`, Turbo Vision took the event,
and no editor existed to act on it. **Nothing reported anything.** The button
still drew, the hotkey still worked, and the model was simply never told.

That failure mode is not new — `Tui`'s docs have warned about it since the
built-in list existed, and the tvdemo port found the mirror image when `"tile"`
and `"cascade"` turned out *not* to be interned. What is new is the scale.
Everything already on the list is a word a program is unlikely to want for
itself: `"cascade"`, `"prev"`, `"zoom"`, `"yes"`. An editor's vocabulary is
nine of the most ordinary words a menu can contain, and taking all nine makes
the hazard nine times more likely to bite somebody who never asked for an
editor.

So they are prefixed — the only prefixed names on the list, and the prefix is
the whole argument. The bare words belong to the program.

Two smaller notes. The check that compares the C++ table against the promise in
`Tui`'s docs matched `\w+` on both sides and quietly stopped seeing a name once
a dot appeared; it is `[\w.]+` now, and it caught the first attempt at
rewording the docs. And the collision was found by *existing* examples rather
than by the new one, which is the argument for keeping every port in the suite
forever.

## What the hex viewer found, from outside the package

`programmers-edc` is written the way anybody else's program would be — it
depends on `gren-tvision` through `gren.json` and calls nothing else — so what
its tools run into is what a consumer runs into. The hex dump viewer is the
first of them that reads a file, and it found one real bug, one shape the
shell had to grow, and one trap that is nobody's fault but is worth writing
down.

### A file viewer needs no size limit, only a range

The obvious way to open a file is `FileSystem.readFile`, and the obvious
question straight after is what happens when somebody points it at a four
gigabyte core dump. The obvious answer is `FileSystem.metadata` for the size
and a refusal above some number, which works and costs a dialog explaining a
limit that nobody can defend.

There is a better one and it was already in `gren-lang/node`.
`FileSystem.readFileStream` takes a `Between { start, end }`, which is Node's
`createReadStream({ start, end })` — so a window showing sixteen rows of
sixteen bytes can read the two hundred and fifty-six bytes it is showing. The
model keeps the size, from `metadata`, and one 16 KB chunk around wherever the
cursor is. A file of any size opens instantly, a file under 16 KB is a single
read, and the limit question stops existing.

Three things follow, and they are all in `Tool/Hex.gren`:

  - **A chunk is a cache, so a late answer must be dropped.** Every read
    carries the range it asked for, and one that is not the range still wanted
    is ignored. Without that, two fast `PgDn`s can leave the older answer on
    screen.
  - **`Array.pushLast` is `toSpliced`** — a copy of the whole array — so
    decoding sixteen thousand bytes one push at a time is a hundred and thirty
    million element writes. `Array.Builder` is what makes a chunk that size
    affordable, and it is the first place in this repo that has needed it.
  - **`//` truncates its result to 32 bits.** Byte five billion over sixteen is
    not a number an `Int32` holds, so every offset here divides through
    `Math.truncate (toFloat n / toFloat d)`. `Ascii.radix` had the same fault
    and would have printed nonsense for any offset past four gigabytes — the
    one place in the ASCII chart's arithmetic where the chart could never have
    noticed, because it counts to 127.

Nothing in `gren-tvision` had to change for any of it, which is the finding: a
tool that reads files is a model with a `Cmd`, and the package already had that
shape.

### The first tool with a `Cmd` changed the shell, not the package

predc's tools were `update : Event -> Model -> Model`. A chart and a
calculator answer an event with a new model and nothing else, so `Main.toTools`
mapped over them and returned `Cmd.none` — and the hex viewer, which has three
tasks, does not fit that. It needs a `Msg` type of its own, the shell needs a
branch that routes those messages back into it, and `toTools` has to lift the
tool's `Cmd Tool.Hex.Msg` into the shell's.

Two smaller things came with it, both worth knowing before writing the third
program that does this:

  - **`FileSystem.initialize` is an `Init.Task`**, so the permission is the
    program's first act and nothing later can ask for one. The shell holds it
    and hands it over when the tool opens. A shell that never expected a tool
    to read a file would have to change its `init` to let one.
  - **A tool that opens a dialog needs a `Tui.Ports` record at *its* message
    type**, because `Tui.dialog` produces a `Cmd msg` and the tool's `Cmd`s are
    its own. Ports are polymorphic — `port tuiOut : Encode.Value -> Cmd msg` —
    so this is one four-line binding in `Main` and no change anywhere else. It
    has to be in `Main` because ports may only be declared in a `port module`.

The quiet tools were left alone. Making every tool return a `Cmd` it would
always fill with `Cmd.none` buys nothing but noise.

### A modal dialog opens with the caret in the wrong place

**This was not a bug in the binding, and the section that said it was is
replaced by the one at the end of this file** -- "The dialog that opened on the
wrong view, and the `append` that put it there". What follows is the symptom as
it was seen from predc, which is worth keeping because it is exactly what a
consumer meets.

`Tui.fileDialog` opens with the caret somewhere other than the `Name` field:
the field is two Tabs away, and typing a path -- the thing the field is for --
does nothing at all. `examples/dir` has had this since the day the dialog was
written and never noticed, because its test drives the dialog with the arrow
keys and never types.

What was verified at the time, all of it still true and none of it the cause:
a dialog of a field, a label and two buttons is fine (predc's Go To Offset
dialog, and `examples/entries`' Add dialog); it is not a render arriving behind
the dialog and stealing the caret, because it reproduces with an `update` that
changes no part of the model; and the same focus sent one message later --
`Cmd.batch [ Tui.dialog ports spec, Tui.focus ports "fileName" ]` -- sticks,
which is what made it look like a call being *undone* rather than a call being
made to the wrong view. `Tool.Hex` carried that one-line workaround until the
cause was found.


### And one documented rule whose failure mode is silence

A `Label` names a view that has to have been built already, and `View`'s doc
comment says so in bold -- *list the control before its label*. Writing the
label first anyway, because the label is drawn above the field and reads better
written above it, does not produce a message. The builder throws part way
through the dialog, the throw goes back through the port handler, and the
program simply stops: the terminal keeps the last frame Turbo Vision drew, the
menu bar still looks like a menu bar, and nothing responds again. The rule was
read afterwards, in the docs, where it had been all along.

A builder that dies leaves the application in a state where the *only* symptom
is that the screen stopped changing. That is worth a look on its own: an
exception raised while building a window or a dialog should end up somewhere a
person can see it, and today it does not.

## Closing the last one the hex viewer found: how big is *this* window?

The hex viewer's first write-up said sixteen bytes a row was "forced, not
preferred", and the reason was the honest one: `Resized` reports the desktop,
never a window, so nothing told a model that the user had dragged one wider.
The same sentence, read the other way round, says the tool cannot grow
*taller* either — a canvas fills its window by itself, because `Grows` has
done that since gap 2, but the canvas's **lines** are the model's, and a model
that does not know how many rows there are cannot produce them. A hex dump in
a taller window was sixteen rows and blank space.

Two things closed it, and they are two halves of one idea rather than two
features.

### `WindowResized`, and the poll that finds it

A window's bounds can change five ways: the frame's resize handle, its zoom
box, `Tile`, `Cascade`, and `growMode` carrying it along when the terminal
changes size. There is no one call they share that a callback could hang off —
`TView::locate`, `TView::calcBounds` and `TWindow::zoom` all end at
`changeBounds` by different routes, and `TGroup::changeBounds` is called for
reasons that are not resizes as well.

`flushResize` had already answered this question one level up. It does not
hook `SIGWINCH`, `WINDOW_BUFFER_SIZE_EVENT` or `setScreenMode`; it compares
the desktop's bounds against the ones it last saw, once per pump, because
whichever route was taken the desktop is a different size afterwards.
`flushWindowResize` is the same trick over the window registry: four integer
comparisons per open window per pump, and there are never many.

Two details are the interesting part.

**It reports the whole rectangle, not the size.** A window that was dragged
has moved without resizing, and a model that stores the rectangle and renders
it back — which is the intended shape, and the same shape `Changed` has for an
input line — needs the position too or it will move the window back sideways
the first time it re-renders.

**It is not reported for a size the model itself set.** `SetBounds` seeds the
remembered rectangle after calling `locate`, on the same principle `Changed`
already followed: only a change the model did not already know about is news.

And one non-detail that took the longest to get right: **the differ is told
nothing**. The first version recorded the new rectangle into the spec the
differ compares against, by analogy with `valueChanged` — and that is exactly
backwards. What the differ holds is the *model's* rectangle. A model that
ignores `WindowResized` renders the same rectangle it always did, it compares
equal, no `setBounds` is written, and the window stays where the user dragged
it. Recording the real one would have made every existing example snap its
windows back on the next render. A model that *does* store the rectangle
compares unequal exactly once and writes a `setBounds` to where the window
already is, which `TView::locate` drops on the floor (`if( bounds != r )`).
Both work, nothing regresses, and the code that makes it so is the code that
is not there.

### `Resize`, and why `sizeLimits` is the whole of it

The other half is the width, and the argument comes out the opposite way from
the one the original write-up assumed. Sixteen bytes a row is not a limitation
to be lifted once the model can know better — it is what a hex dump *is*. The
low nibble of the offset is the column number, so `0x4C` is in column C of the
row starting `40`, and a twenty-three byte row is a grid nobody can read an
offset off. The right answer is not to reflow; it is to stop offering.

`Window` gained `resize : Resize`, a record of two booleans, with
`Tui.resizable`, `Tui.resizeHeight`, `Tui.resizeWidth` and `Tui.fixedSize`
naming the four. It is Turbo Vision's `sizeLimits`, and `sizeLimits` turns out
to be the one call every route to a new size passes through:
`TFrame::dragWindow` for the handle, `TWindow::zoom` for the zoom box,
`TFrame::draw` for whether the zoom box is even drawn as a zoom, `TView::locate`
for `setBounds`, and `TView::calcBounds` — via `fitToLimits` — for `growMode`.
Pinning a dimension in one override pins it on all five, with nothing else to
remember and no state to keep in step. `JsWindow` also drops `wfGrow` and
`wfZoom` when *neither* dimension can move, because a resize handle that
cannot resize is a corner the user grabs for nothing.

A pinned dimension is pinned at the size the window was **built** at rather
than at whatever it currently is. The model wrote that number; a window that
quietly kept a width it had drifted to would be a window whose size nothing
owns.

### What it looks like in the tool, and the rule it turns on

`Tool/Hex.gren` now says `resize = Tui.resizeHeight`, wraps its canvas and
scroll bar in `Grows stretchHeight` and its two description lines in
`Grows pinBottom`, and keeps one field: how many dump rows the window is
showing.

Every rectangle in that window is still written for the height the window
*opens* at and is never recomputed. That is the rule this made concrete, and
it is worth stating plainly because the obvious alternative looks tidier and
is wrong: **a view's rectangle is structural.** Change one and the differ
tears the window down and builds it again, losing the caret and the z-order.
So a layout that recomputed itself from the new height would rebuild the whole
window on every drag — while `Grows` does the identical arithmetic inside
`TGroup::changeBounds`, where it costs a repaint and nothing else. The model
computes only what `Grows` cannot: the number of lines to put in the canvas,
which is `height - 6` because two frame rows, the header, the blank row and
the two description lines are spoken for whatever the height is.

The one cost is that a window rebuilt for some *other* structural reason comes
back at the model's declared size. For this tool nothing is structural — the
dump's lines, the scroll bar's bounds and the two description lines are all
patched — so it never happens. A window that both resizes and changes shape
would want to store the rectangle and render it back, which is what
`WindowResized` carrying the whole rectangle is for.

`drive_hex.py` drives it the way a person would: `Ctrl-F5` is the Window menu's
Resize/move, shifted arrows resize rather than move in `TView::dragView`, and
`Enter` commits. Five Shift-Ups leave eleven rows of dump with the description
lines directly under them and `PgDn` moving eleven rows; three Shift-Lefts
leave the width exactly where it was.

### And a menu entry that has to look as dead as it is

`fixedSize` turned up a gap in `TWindow::setState` on its first real use.
predc's ASCII chart and RPN calculator are both fixed-size windows -- sixteen
rows of eight columns, and a keypad, neither with anywhere to put extra space
-- and with the zoom box gone from the frame, the Window menu's Zoom entry and
the status line's `F5 Zoom` were still lit, and did nothing.

`TWindow::setState` only ever *enables* the commands a window supports when it
is selected. Nothing disables the ones it does not: it relies on the previously
selected window having disabled its own set on the way out. That works for two
windows taking turns and does not work for the first one, because
`initCommands()` starts with almost everything enabled, so a program whose
first window is fixed-size inherits a `cmZoom` that nobody ever turned off.

Upstream has the same gap for any window without `wfZoom` -- a `TDialog` on the
desktop, for one -- and it has stayed invisible because nothing in Turbo Vision
makes `wfZoom` a thing an author sets. `Resize` does, so `JsWindow::setState`
now disables `cmZoom` for a window that cannot zoom. `cmResize` is deliberately
left alone: a fixed-size window can still be *moved*, and `cmResize` is the
move as well as the grow.

The check for it is in `drive_ascii.py`, and it asserts on the colour the
entry is drawn in rather than on any text, because greying is the entire
visible difference -- the same reason the chart's own colour checks read
attributes.

## A window's colour set, and the buffer that hid the change

`WindowPalette` on a [`Window`](Tui#Window) is the small half of the colour
work and the one piece of Turbo Vision's palette machinery that survives being
asked to name a colour instead of an index into a table -- because there are
three of them and they have names, rather than a hundred and thirty-five of
them and byte offsets.

Two things were not obvious.

**They are the *dialog* palettes, not the window ones.** `JsWindow` derives
from `TDialog`, so `getPalette()` is `TDialog::getPalette`, which switches on
`dpBlueDialog | dpCyanDialog | dpGrayDialog` and never looks at
`wpBlueWindow | wpCyanWindow | wpGrayWindow`. The two sets are 0, 1, 2 either
way, so the first version compiled and worked while naming the wrong constants.

It also has to be that way. A window here can hold buttons, input lines and
list boxes, and those ask for palette entries past the eight that a
`cpBlueWindow` has; the dialog palettes are thirty-two long. Borland made the
first entries of `cpBlueDialog` agree with `cpBlueWindow` exactly so that a
dialog could be made to look like a window, which is what makes this work at
all -- and which means the fix in the previous section was, strictly, selecting
the blue *dialog* palette. The colours are the same; the length is not, and the
length is the reason.

**`drawView()` is not enough, and fails silently.** Setting `palette` and
asking the window to draw itself changed nothing on screen -- while the same
render's `setTitle` visibly worked, which is what made it confusing. A
`TGroup` that has a buffer draws by blitting it (`tgroup.cpp:128`), so
`drawView()` on a recoloured window paints the cached colours straight back.
`redraw()` is `drawSubViews`, which asks every child for its colour again, and
that is the only route to a palette. The check that found it asserts the body
colour of a canvas that names no colour -- three sets, three different
attributes, and the third `Alt-W` bringing the first back.

`examples/palette` is where this is demonstrated, and it is the right place
rather than a convenient one: that example exists to show the trade between
naming a colour and inheriting one, and `Alt-W` now shows both halves at once.
The window whose spans name both halves of their colour does not move; the
window whose spans name nothing follows. Same screen, same keystroke.

## The window palette, which was grey because nobody set it

Reviewing predc's colours turned up a bug that had been on screen since the
first window this package ever drew, and had been read as a design decision
because it was uniform.

`JsWindow` derives from `TDialog` so that a window and a dialog are one class,
and `beWindow()` puts back what `TDialog`'s constructor takes out: `wfGrow`,
`wfZoom`, `gfGrowAll | gfGrowRel`, `ofTileable`. Its comment lists exactly those
four. There is a fifth. `TWindow`'s constructor sets `palette = wpBlueWindow`
and `TDialog`'s overwrites it with `dpGrayDialog` (`tdialog.cpp:31`), so every
window on the desktop was drawn in the *dialog* palette: white on light grey.

That is the colour of the Find box in tvedit's screenshot at the top of
tvision's README rather than of the editor behind it, and it is why nothing
built on this ever looked like Turbo Vision. One line in `beWindow()` fixes it,
and the split it restores is the one Turbo Vision has always drawn: windows on
the desktop are blue, modal dialogs are grey. Dialogs never go through
`beWindow()`, so they were right all along.

### What it cost, which is the interesting half

`Hue` names an absolute colour with nothing between it and the terminal --
`examples/palette` argues at length for why -- so **every span in the repo had
been chosen against a background that was grey by accident.** Changing the
ground silently invalidated all of them, and the failure mode is invisible
rather than loud: a colour that no longer contrasts still draws.

Three kinds of breakage, and the suite found two of them:

  - **Dark on dark.** predc's hex viewer painted its column header and offset
    column in `ink Blue`, which was right on light grey and is blue-on-blue on
    a window. Measured at `fg=34 bg=44`: perfectly invisible, and *no test
    failed*, because nothing asserted on those cells.
  - **A highlight the same colour as the text.** `examples/calendar` marked
    today in `ink Yellow` and `examples/puzzle` drew its checkerboard in it --
    and yellow is exactly what a blue window's ordinary text is. Both drivers
    caught it, because both assert that some cell differs from the body colour.
  - **A background that matches the ground.** Both of predc's canvases marked
    their selection with `on Blue`, a blue block on a blue window. `drive_ascii`
    and `drive_hex` caught these.

The repaint settles a vocabulary, and it is worth having in one place because
the next canvas will need it: `LightCyan` for a ruler or a label, `Cyan` for a
placeholder, `LightRed` for something wrong, `LightGreen` for something marked,
and `on LightGray (ink Blue)` for a selection -- which is not an invention but
Turbo Vision's own selected-text colour, app palette entry 15 of a blue window.
`Tui.Hue`'s doc comment now says all of this, including the part that reads
backwards: `Yellow` is not a highlight on a window, it is the default.

`drive_ascii.py`'s comment on this has now been rewritten twice and is worth
reading as a pair. The first version pinned "dark blue labels, dark grey dots"
because an earlier attempt had put bright yellow on light grey at about 1.5:1.
Those are the two colours that disappear on blue. The check is the same check
either way -- *the model is the only thing that can get this wrong, so fail
here rather than in someone's eyes* -- which is the argument for asserting on
colour at all in a terminal test.

## The application palette, described rather than tabulated

`Theme` on a [`Ui`](Tui#Ui) is the rest of the colour work: every colour on the
screen that the package draws rather than the model, in seventeen fields.

### Why it is seventeen and not a hundred and thirty-five

Turbo Vision's application palette is 135 colour attributes and
`examples/palette` argues -- correctly -- that the *indirection* into them has
no Gren equivalent. The table does, and the reason is that the 135 are not 135
decisions. The layout is fixed and structured:

    1        the desktop
    2-7      the menu bar and the status line
    8-15     the blue window set
    16-23    the cyan window set
    24-31    the gray window set
    32-63    the gray dialog set
    64-95    the blue dialog set
    96-127   the cyan dialog set
    128-135  the help viewer

One desktop, one bar, and three coloured surfaces each described the same way
and written into two blocks apiece. So a `Theme` is a desktop pair, five bar
colours, and three `ThemePanel`s of nine -- and `buildAppPalette` in `app.cc`
is the expansion, one commented line per slot. That file is the only place the
thirty-two dialog entries are written down in order, which matters because
getting one wrong miscolours exactly one kind of control and nothing reports it.

**`Tui.borland` is Turbo Vision's look rebuilt, not its table reproduced**, and
the first version of this write-up said otherwise. It claimed the expansion was
proved right because all 529 checks passed against it unaltered. They did, and
that proves much less than it sounds: the suite asserts on a few dozen cells,
and a hundred and thirty-five slots do not fit in a few dozen cells.

Comparing the generated palette against `cpAppColor` byte for byte -- which is
twenty lines of Python and should have been the first thing done -- says **82 of
135 slots differ**. Most of the difference is in blocks nothing reaches: the
help viewer, the two slots per set that no view's palette string indexes, and
the cyan dialog set, which a program gets only by asking for a `CyanWindow`.
The rest is the model deliberately treating a surface as one surface: stock
Turbo Vision puts a list box on cyan *inside* a grey dialog and a check box
cluster on cyan too, and the seventeen-field model puts both on the panel's own
ground. The stock blue dialog set is the largest divergence and the most
deliberate -- it is a blue-framed grey dialog rather than a blue surface, and a
window drawn in it would not look like the editor it is supposed to look like.

That is a fair thing for a described scheme to be. It was not a fair thing to
call byte-identical.

### Three things that were not obvious

**A Gren union constructor takes at most one parameter**, so `Rgb Int Int Int`
does not compile. `Rgb 0xF08C00` is better anyway: it is how a colour is
written everywhere else, and it is what `TColorRGB`'s own constructor takes.
The split into three bytes happens in the encoder, once, rather than in C++
against a number that has already been through a double.

**`Ansi` and `Rgb` are a real choice and not a convenience.** A theme built out
of `Ansi` names one of the sixteen and therefore inherits whatever scheme the
person running the program has set on their terminal -- it belongs to their
machine and matches the rest of it. `Rgb` pins the colour and looks the same
everywhere, including where that is wrong. magiblot's TVision quantises an
`Rgb` down when the terminal cannot do better, so a 24-bit theme still runs
over ssh; it just stops being the colour that was picked. A dark theme is the
case that needs `Rgb`, because `Black` and `DarkGray` is the only dark pair the
sixteen offer and it is simultaneously too far apart to read as one surface and
too close to be a border.

**Applying it is a whole-screen repaint, so it has to be diffed.** `setTheme`
overwrites the palette in place and calls `setScreenMode(TScreen::screenMode)`,
which is what tvdemo's own colour dialog does (`tvdemo2.cpp:349`) and the only
precedent there is for changing a scheme while a program runs. A `Ui` is
rendered whole on every update, so a model that renders the same theme thirty
times a second would repaint the screen thirty times: `tui.js` compares the
theme by value and only calls through when it changed, the same rule the
differ applies to everything else. It is also sent *before* `tv.start()`, so
the first frame is drawn in the theme rather than repainted into it.

### What a theme still does not reach

A [`Span`](Tui#Span) that names a [`Hue`](Tui#Hue). That is deliberate and it
is the same trade `examples/palette` has always been about, one level up: a
span colour is absolute, so a program with themed canvases keeps its own hues
in its model beside its choice of `Theme` and paints from them. The colour is
a model decision, made where the decision about what to draw is made.

`examples/palette` now shows all three levels on one screen, which is why the
demonstration belongs there rather than anywhere more convenient. `Alt-W` moves
one window between the three sets a theme defines. `Alt-T` changes what those
three sets are, and takes the desktop and the menu bar with it -- which no
window palette can reach. And through both of them the window whose spans name
both halves of their colour does not move at all.

## predc's three schemes, and the seam between the two halves of a theme

The application palette is the package's half. predc is where the other half
turned up, and it turned up as a compile error rather than as an idea: making
the tools follow a theme meant changing `view : Model -> Tui.Window` to
`view : Inks -> Model -> Tui.Window` in all three of them, because a
`Tui.Theme` cannot reach a `Tui.Span`.

That is not a gap to close. It is the same trade `examples/palette` has always
been about, one level up: a span names a `Hue` and there is nothing between it
and the terminal, deliberately, so the colour is a model decision. What predc
adds is the shape that decision takes in a program with more than one scheme --
`Theme.Inks`, four fields named for what they *mean*:

  - `ruler` -- column headers, offsets, labels: the scaffolding, quieter than
    the data.
  - `dim` -- placeholders and standing hints, quieter still.
  - `alert` -- the line under the window when something went wrong.
  - `selected` -- the cell the caret is on, painted rather than pointed at.

Each theme answers for its own ground, and that is the point rather than an
inconvenience: the hues that read on Borland's blue are the hues that vanish on
a light one. The ASCII chart has now been repainted twice by hand for exactly
this reason -- once when its window's interior turned out to be light grey by
accident, once when fixing that made it blue -- and a program with three
schemes cannot be repainted a third time.

### The seam is that a palette is 24-bit and an ink is not

`Tui.Tint` has `Rgb`; `Tui.Hue` has sixteen names. So predc's Midnight theme is
a hand-picked near-black ground with `LightCyan` painted on it, and the two have
to be chosen to sit together. That asymmetry is deliberate -- a span colour is
resolved against a view's palette and giving it 24 bits would mean giving up
`TColorBIOS` in the one place where the point is to agree with whatever the
window is already using -- but it is the thing to know before writing a theme,
and `Theme.gren`'s doc comment says so where somebody would hit it.

### Two smaller things

**The config file reports nothing, ever.** A missing file is a first run, an
unreadable one is a directory somebody made read-only, a corrupt one is a
half-written file from a machine that lost power, and all three have the same
right answer: start in the defaults. `Config.load` is a `Task Never Config` and
every failure funnels into `default`. The write is fire-and-forget for the
mirror-image reason: a theme that failed to save is a theme that comes back
next time, which the user will notice and can act on, and a modal box saying so
in front of somebody who opened predc to read a hex dump is the worse outcome.

**It is loaded during `init`, not after it.** `Node.getEnvironmentVariables`
and `FileSystem.readFile` are both ordinary `Task`s and `Init.awaitTask` takes
a `Task Never a`, so the whole load happens before the first frame. Doing it
afterwards works and costs a visible flash -- the first frame in Borland,
repainted into the saved theme a moment later, once, every single run. `init`
is now three awaits deep and the order is forced: the file system permission is
an `Init.Task` and has to come first, the environment says where the file is,
and the file says which theme to start in.

Saving happens on the change and not at exit, which is the same argument: predc
is a program people leave open and close with `Alt-X` or from the window, and a
setting that survives only a tidy exit is a setting that gets lost.

### And the test harness could not see any of it

`drive_theme.py` asserts on colours, and the first version of it reported that
nothing had changed. The harness's SGR parser understood 30-37, 90-97, 40-47
and 100-107 and skipped anything else -- so `38;2;240;140;0` was read as four
separate codes, matched none of them, and left the *previous* colour in place.
Every cell of a truecolor screen came back as whatever was last set from the
sixteen, which is indistinguishable from a screen that did not repaint.

It now stores a 24-bit colour as an `(r, g, b)` tuple, which keeps every
existing `== 34` meaning what it meant and lets a check say
`isinstance(bg, tuple)` for "this really is the colour that was asked for and
not the nearest of sixteen". The driver sets `COLORTERM=truecolor` for the same
reason, and `HOME` to a fresh temporary directory so that the first-run case is
actually a first run.

## The slot map was wrong, and only a light theme could show it

Reviewing predc's Gren scheme turned up four things, three of them cosmetic and
one of them a bug in the binding that had been invisible in every theme.

**The dialog slot map was two off for the list viewer.** `writeDialogSet`'s
thirty-two entries were taken from the Turbo Vision Programming Guide's list,
which is *nearly* right and puts the list viewer at slots 28-31. The authority
is not the book: it is each view's own palette string, and `cpListViewer` is
`"\x1A\x1A\x1B\x1C\x1D"`, which is slots 26-29. So a file dialog's rows were
drawn in the scroll bar's colours -- blue on cyan under Borland, and a
1.85:1 grey-on-grey under Gren, which is where it was finally noticed.

Nothing reported it, and nothing could have: no check in the suite asserts on a
list row's colour, so both the wrong map and the "all 529 checks passed"
argument for it sailed through. `writeDialogSet` now cites the ten palette
strings it is derived from, one per line, with their file and line numbers --
`cpCluster`'s fifth colour being `0x1F` and therefore thirteen slots away from
its other three is exactly the sort of thing a list written from memory gets
wrong.

**Buttons and input lines had to become two fields.** They were one, `control`,
and Turbo Vision has always drawn them differently: in the stock scheme a grey
dialog's buttons are black on green and its fields are white on blue. One
colour for both makes every text field look like something to press -- and it
was also what forced predc's first Gren theme into a corner, because an orange
button meant an orange text box, so the dialogs had to keep a quiet grey and
could not have the orange at all. Split into `button`/`buttonAccent` and
`input`/`inputAccent`, both problems go away at once: the Gren theme's buttons
are the logo orange everywhere, its fields are recessed, and predc's dark theme
can put its fields *below* the window's ground rather than on it.

**Two smaller ones**, both places where a value was structurally in the wrong
family rather than merely an odd colour: a grey dialog's scroll bar was blue on
cyan when the stock scheme has it cyan on blue, and slot 8 -- the label of the
field that currently has the focus -- was mapped to `selected`, which put a
coloured block behind the word "Name" in every dialog. It is emphasis, not a
selection, so it is the brightened text now.

### A light theme is a better test than a dark one

Every one of these had been on screen since the palette work landed, in every
theme, and the light one is what made three of the four visible. A dark scheme
that goes wrong is illegible and gets fixed; a light one that goes wrong is
*nearly* legible and stays that way. `Theme.gren`'s doc comment now records the
contrast ratio of every colour in it against the ground it lands on, and the
numbers are the argument: white on the logo orange is 2.8:1 and reads as a
slightly odd choice rather than as a bug, which is precisely why the focused
Name field and the selected row of a file list were wrong for as long as they
were.

### And the suite was not isolated from the user's own config

`drive_ascii` and `drive_hex` assert on colours and read `$HOME`, so once a
scratch script left a `{"theme": "gren"}` in the real `~/.config/predc/`, four
checks in two suites started failing against a program that was working
perfectly. Every predc driver now runs with `HOME` set to a fresh temporary
directory. A suite whose result depends on which colour scheme the person
running it happens to like is not a suite.

## The dialog that opened on the wrong view, and the `append` that put it there

The one known bug on the list -- `Tui.fileDialog` opening with the caret
anywhere but its `Name` field -- was in `Tui.fileDialog`, in the one line
nobody reads:

```gren
    , views =
        Array.append
            [ InputLine { id = "fileName", … }, History …, Label …, ListBox …, StaticText … ]
            placed          -- the buttons
```

**`Array.append fst second` makes `fst` the postfix.** It is not `++` with the
arguments in the order they are written; it is the pipeline reading, `xs |>
Array.append suffix`, and `Array.prepend` is the one that means `++`. Gren
documents this with an example that says so in three symbols -- `append [1,2,3]
[4,5,6] == [4,5,6,1,2,3]` -- and the line above still reads, to anyone who
knows Elm, as "the fields and then the buttons". What it built was the buttons
and then the fields.

That array is two things at once, and this is why one typo produced two
symptoms:

  - **The caret opens on the first view in it that can hold one**
    (`buildItems` returns `firstSelectable`, `applyInitialFocus` focuses it),
    so the dialog opened on the OK button.
  - **Tab walks it in the same order.** `kbTab` is `focusNext(False)`
    (`twindow.cpp:147`), which is `prev()` through a chain that `insert()`
    builds by prepending -- so a Tab goes to the view declared *after* this one,
    and the order of the array is the tab order. From OK that was Cancel, then
    `fileName`. Which is where "the Name field is two Tabs away" came from: not
    an odd tab order plus a focus bug, but one wrong order seen twice.

Everything that made this look like a bug in the binding was true and none of
it was relevant. A dialog of a field and two buttons really is fine -- those
specs list the field first because they are written as one literal array, with
no `append` to get backwards. A `Tui.focus` sent one message later really does
stick -- naming a view by id has nothing to do with array order. And a
`ListBox` really is present in both affected dialogs -- because
`Tui.fileDialog` is the only helper in the package that builds its view array
out of two pieces, and it is the only one with a list. Every distinguishing
feature of the failing case pointed at `TListViewer`, and the actual difference
was the `Array.append`.

**What found it was printing the thing that was assumed.** Four rounds of
reading `tgroup.cpp`, `tview.cpp` and `tlstview.cpp` produced a plausible
mechanism (a list viewer shows its scroll bar when it goes active, and
`TView::setState(sfVisible)` calls `owner->resetCurrent()`) that was wrong,
because the scroll bar is not `ofSelectable` and the call never happens. Twenty
lines of `fprintf` in `buildItems` -- id, type and options for every item as it
is inserted -- answered it in one run:

```
  item[0] type=button       id=hex.file-ok      options=0035 sel=1
  item[1] type=button       id=hex.file-cancel  options=0035 sel=1
  item[2] type=inputLine    id=fileName         options=0005 sel=1
```

The order of a list is the kind of fact that reading cannot check, because
reading is where the wrong order came from.

**And the test could not see it either, which is the part worth fixing.**
`drive_dir.py` drove that dialog with arrow keys, `Alt-O` and the mouse through
nine checks and a history drop-down, and every one of them passed with the
caret on the wrong view -- a pty test reads a screen, and a screen does not say
where the caret is. Typing one word does say, because it lands somewhere. So
`drive_dir.py` ends by opening the chooser and typing `zz` into it, and that
check fails against the old array. The rule generalises past this dialog:
**for anything about focus, the assertion is what a keystroke does, not what
the screen shows.**

`Tool/Hex.gren`'s workaround is gone, and with it the last known bug on the
list before publishing.

## The mode a terminal will let you have: `v`, and the keystroke that never arrives

predc's hex viewer needed a gesture with a state in it -- mark a range, move,
paint it -- which is the first thing in this program that is not one keystroke
answered by one change. The obvious shapes were `Shift`-arrows and vim's
`Ctrl-v`, and the question asked of the binding was whether it could tell
`Ctrl-v` from `Ctrl-V` at all.

It can, and that turned out to be the less useful half of the answer. A
throwaway canvas that echoes `keyName(event)` for whatever is typed at it,
driven through the pty harness with the escape sequences written by hand:

| typed                       | bytes            | reaches the model as |
| --------------------------- | ---------------- | -------------------- |
| `v`                         | `v`              | `"v"`                |
| `V`                         | `V`              | `"V"`                |
| Ctrl-v                      | `0x16`           | `"Ctrl-V"`           |
| Ctrl-v, modifyOtherKeys     | `\e[27;5;118~`   | `"Ctrl-V"`           |
| Ctrl-Shift-v, modifyOtherKeys | `\e[27;6;118~` | `"Ctrl-Shift-V"`     |
| Ctrl-Shift-v, kitty         | `\e[118;6u`      | `"Ctrl-Shift-V"`     |
| Shift-Right                 | `\e[1;2C`        | `"Shift-Right"`      |
| Ctrl-Shift-Right            | `\e[1;6C`        | `"Ctrl-Shift-Right"` |

Two things in that table are worth keeping. **The case of the letter is not
what carries the distinction**: `TKey` uppercases letter keys on purpose, so
that Ctrl-A and Ctrl-a are one key in a shortcut table, and `keys.h` names the
modifier set instead. Plain Ctrl-v is `"Ctrl-V"` and `"Ctrl-v"` is a string the
model will never be handed. And **the binding is faithful about modifiers it is
given** -- the `Shift-` prefix is there, in every combination, once the
terminal has said so.

Which is the trap. *Whether a name is right* and *whether that keystroke can be
typed* are different questions, and only the second one decides a gesture. For
`Ctrl-Shift-V` the second answer is no, twice over: it needs the terminal to be
reporting modifiers at all -- TVision asks, with `\e[>4;1m` and the kitty
query in `termio.cpp`, and a terminal is free to decline -- and, on every
emulator on this machine, it is the *paste* binding, which means it is consumed
before any program sees it. The most vim-like shape available was the one
keystroke on the keyboard least likely to arrive.

So the tool uses vim's other two: `v` marks by byte, `V` marks by row. Plain
letters need no modifier report, no terminal cooperation and no negotiation
with a window manager; a focused canvas already eats every key it is sent, and
nothing else in the tool wanted a letter. **The gesture a terminal program can
rely on is the one that needs nothing of the terminal.**

### The mouse came with it, because the far end of the mark is the cursor

The mark stores an anchor and a grain, and *not* the other end -- the other end
is `model.cursor`. Every arrow key, every `PgDn`, every click on the dump and
every Go To already move the cursor, so every one of them extends the mark
without a line of code knowing that it does. "The mouse should move the far end
too" was a feature that needed nothing written and one test to prove.

That is the shape to reach for: **store what the second end is, not where it
is.** A mark holding two offsets would have needed every movement path in the
file to remember to update the second one, and the failure mode of forgetting
is a mark that quietly stops following.

What it did not buy, at the time, was dragging: `JsCanvas::handleEvent`
forwarded `evMouseDown` and nothing else, so there was no press-move-release
for a model to hear and `Tui.Event` had no motion variant to hear it with. That
is closed -- see "The drag, and the capture Turbo Vision keeps inside a loop"
at the end of this file -- and the shape above is exactly why it cost one small
function in `Tool/Hex.gren` when it came: a drag moves the cursor, and the
cursor is already the far end of the mark.

### A key that picks a colour has to wear it

The line the mode puts on the screen first read `1-6 paint`, which is a range
of numbers and not an answer to the question somebody in the mode is asking:
*which one is yellow*. It says the six digits in the six grounds instead --
eighteen columns, on a line that had them -- and the same swatch, with its
number in it, is what the byte under the cursor wears when it is inside a
range. This is the calculator's lesson from the other side. There the finding
was that a control's face has to be *readable* (`~` was rejected as a button
because at that size it is a hair from `-`); here it is that a control's face
can carry the answer instead of describing where to find it.

### And one off-by-one that only the menu could have

The six colours are a key each (`1`-`6`) and a menu entry each, and the menu
entry's `cmd` first carried the *index* while the key carried the number on the
cap. Both ends went through the same parser, which subtracted one. Every colour
picked from the menu came out as the one to its left, and every colour picked
with a key was right. Two ends of the same command have to agree on what the
number in it means, and the cheapest way to make them agree is to give them the
same number: `hex.ink3` is what `3` does.

## The clipboard, and why it is a request rather than a getter

`THardwareInfo::setClipboardText` and `requestClipboardText`
(`hardware.h:104`) were the last two functions in the C++ API that nothing in
this binding reached. They are now `tv.setClipboard(text)` and
`tv.requestClipboard()`, and on the Gren side
[`copyToClipboard`](Tui#copyToClipboard) and [`readClipboard`](Tui#readClipboard)
with a `Copied` and a `ClipboardText` event -- the first thing in this package
that talks to a program outside it.

**Reading is asynchronous, and that is the whole shape of the API.** On unix
Turbo Vision gets at the clipboard two ways (`unixcon.cpp:50`): it runs
`wl-copy`, `xsel`, `xclip` or WSL's `clip.exe` if one of them is there and its
environment variable is set, and otherwise it asks the *terminal*, with
`OSC 52`. The first is a subprocess and answers immediately. The second is an
escape sequence out and an escape sequence back, parsed by the same code that
parses keystrokes -- so the answer to "what is in the clipboard" can arrive
several events after the question, and on a terminal that never replies it does
not arrive at all. A getter would have to block on that. So `readClipboard` is
a `Cmd` and `ClipboardText` is an `Event`, which is the shape
[`readEditor`](Tui#readEditor) has for a much weaker reason.

**Writing can half-work, and the model is told.** `setClipboardText` returns
false when nothing took the text, and both `Copied` and `ClipboardText` carry a
`Bool` saying whether the system was involved. False is not a failure: the
binding keeps the last copy in a `std::string` of its own, so copy-and-paste
inside one program works on a machine with no clipboard at all. What false
means is that no *other* program will see it, and that is worth a line on a
status line rather than silence.

### `TClipboard` is twenty lines and the wrong twenty

Turbo Vision has a wrapper for exactly this -- `TClipboard::setText` and
`requestText` -- and it is not used here. `tclipbrd.cpp` is short enough to
quote the reason: `requestText` hands whatever it finds to
`TEventQueue::setPasteText`, which turns the text into *keystrokes* aimed at
whatever has focus.

That is the right answer for an input line and it already happens without any
of this: pasting with the terminal's own paste key is a burst of key events,
which is the `minPasteEventCount` mechanism the calculator found. It is the
wrong answer for a program that wants the text -- a hex dump viewer cannot be
typed into. So the accept callback is ours, the local fallback is ours, and
`TClipboard` is skipped. Note that `requestClipboardText` takes a function
*reference* rather than a `std::function`, so the callback cannot capture; there
is one clipboard and one JS callback, so a file-static suffices.

### The reason it is testable is that it is an escape sequence

A clipboard looks like the least testable thing in the library and is one of
the more testable, because the fallback path is *on the wire*. `drive_clip.py`
removes `DISPLAY` and `WAYLAND_DISPLAY` from the environment -- without which
the subprocess path wins and the suite would write to the clipboard of whoever
ran it -- and then drives both halves through the pty:

  - a copy is `ESC]52;;<base64>BEL` in the byte stream, which the driver
    decodes and compares against what it typed;
  - `ESC]60;allowWindowOps BEL` from the driver is a terminal claiming full
    OSC 52 support (`termio.cpp`, `parseOSC`), and it changes what both halves
    report without restarting anything;
  - a paste is then `ESC]52;;?BEL` out, and the driver answers it with a
    base64'd string of its own, which lands in the field.

No clipboard, no display, no window manager. The one platform note: on macOS
`pbcopy` has no environment variable guarding it, so the same suite would need
a different arrangement there.

### And two new variants broke four examples, which is the system working

`Event` is a public union, so adding `Copied` and `ClipboardText` to it stopped
four programs compiling -- three examples that answer every variant with
`model` and the demo's event log, which names them all. Every one was a two-line
fix and every one was found by the compiler in the first build. That is the
difference between a union and a string: the protocol version exists for the
runtime, and exhaustiveness is what covers the same skew inside one language.

## `y`, and the first thing that could not be copied

predc's hex viewer yanks: `y` takes what is marked, **Bytes | Copy as a dump**
takes the same range as the rows on the screen, and both go out through
[`copyToClipboard`](Tui#copyToClipboard). It is the first Gren program to call
the clipboard, and it found three things.

**With nothing marked, `y` takes the highlight under the cursor.** That rule is
one line and it is what makes a highlight worth more than its colour: mark a
range once, paint it, and it stays a range -- something to come back to
tomorrow and copy without marking it again. Painting stopped being decoration
the moment reading it back was possible.

**Two shapes, because neither is recoverable from the other.** `AsHex` is
`00 01 02 03` and goes into a debugger or a test fixture; `AsDump` is what the
window shows, offsets and printable column included, and goes into a bug
report. Nothing on the receiving end of a clipboard can turn one into the
other. The dump form snaps to whole rows however the range was made -- a first
line indented by an amount nothing explains is not a dump -- and writes full
stops where the screen writes middle dots, because what is on the other end of
a clipboard may be ASCII only.

**And the streaming design finally cost something.** The viewer never holds the
file: it holds the size and one 16 KB chunk around the cursor, which is what
lets it open a four gigabyte core dump instantly. A mark can be dragged across
more of the file than that -- `V` then `Ctrl-End` marks all forty kilobytes of
the test fixture -- and those bytes are genuinely not in the program. It
refuses, and says by how much:

    That is 40960 bytes and only 16384 are in memory at a time.

Refusing beats the alternative, which is copying the part it happens to be
holding. **A dump missing its middle looks exactly like a dump**, and it would
be found by whoever pasted it into a bug report rather than by whoever copied
it. Reading the range first and copying when it arrives is a state machine
worth building the day somebody wants it; a wrong answer is not worth shipping
in the meantime.

### The clipboard's wire is what makes a consumer's test possible too

`drive_hex.py` now removes `DISPLAY` and `WAYLAND_DISPLAY` like `drive_clip.py`
does, and gets the same thing back: what predc copied is base64 inside an
`OSC 52` in the pty's byte stream, so the driver decodes it and compares it
against the bytes the window was showing. It also sends
`ESC]60;allowWindowOps` halfway through, which turns the message from "this
program only" into a plain "Copied 4 bytes as hex" without restarting
anything. That is the whole of the Gren clipboard API exercised end to end, and
it is what the previous commit could not do.

### A pty test that counts menu lines breaks when the menu grows

Two entries added to predc's `Bytes` menu moved *Top of file* and *End of file*
down by three lines, and four checks failed -- none of them about copying, all
of them about paging past the first chunk. `menu(app, "Bytes", 5)` had been
clicking the fifth line of the pull-down.

Every entry is reached by the letter it underlines now (`bytes_menu(app,
b"e")`), which is shorter, is the only way into a *nested* submenu without
knowing where the second box lands, and checks the hot keys while it is there.
The general form: **in a pty test, name the thing rather than its position.**
The same rule already applies to rows and columns, where it is obvious; a menu
is the case where the position looks stable and is not.

## The second source, and how little of the program noticed

predc's hex viewer takes a paste now -- `p` for the clipboard's own bytes, `P`
for the bytes its hex digits spell -- which was the last thing on the README's
v1 list for that tool and the one that looked like a rewrite. `Model.file` was
`Maybe { path, size }`, `load` read a chunk around the cursor through
`readFileStream`, and eleven functions took a `File` to ask it how big it was.

It was not a rewrite, and the reason is worth keeping: **a pasted buffer is a
source whose every byte is already in the chunk.** The model was holding a
size and one 16 KB window of bytes, and a paste is a size and a window that
happens to be all of it -- so `covers` answers yes to every range, `load` never
reaches a read, and the dump, the scrolling, the marking, the highlighting and
both kinds of copy did not have to learn anything. The type became:

```gren
type alias Source =
    { name : String, size : Int, from : Origin }

type Origin
    = OnDisk Path
    | Pasted
```

and the union has exactly one job -- answering "where do more bytes come
from". It is a union rather than a `Maybe Path` on purpose: with a `Maybe`, the
absent case reads as "then do not read anything", which is also what a bug
looks like from the inside. With a union, the two places that need a path say
which source they are dealing with and the compiler asks the other one what it
means. Both turned out to be interesting -- the read that cannot happen, and
the file dialog's starting directory, which for a paste is the working
directory because there is nothing better to say.

The renaming was most of the work: eighteen `model.file`, sixteen `file.size`,
seven signatures. All of it mechanical, and all of it caught by the compiler
in three builds.

### Two commands, because sniffing is being silently wrong

`p` and `P` differ only in how the same clipboard is read, and the temptation
to have one command that works it out is strong and wrong. `beef`, `cafe`,
`decade` and `0123456789` are all words somebody might paste and all valid
hex. A program that guesses is a program that is sometimes silently wrong
about what it is showing -- and looking at what is really there is the entire
reason to open a hex viewer.

The same argument decides what `P` does with input that is *nearly* hex. An
`xxd` dump is hex digits, whitespace, an offset column that is also hex digits,
and a printable column that is sometimes hex digits. Keeping the hex and
dropping the rest would read all three as data and produce a buffer that is
wrong in a way nobody can see. So it refuses, and names the character that
stopped it:

    That is not hex: 'H' is not a hex digit. Offsets and a printable column
    have to come off first.

Which leaves a real gap -- a dump cannot be pasted back in -- and it is a
better gap than a silent misreading. The separators it *does* take are the ones
that carry no data: whitespace, `,`, `;`, `:`, `-`, and `0x` in front of each
byte.

### The paste is where the clipboard's shape finally shows

`readClipboard` is a request answered by an event, and this is the first
program to feel it. The tool keeps `awaiting : Maybe Reading` -- both to know
that *it* asked (every open tool is handed every event) and to remember what
the answer is for, which nothing in the event says. And because the answer may
take a moment or never arrive, asking puts `Asking for the clipboard...` on the
message line: the one state this program can be in that it cannot draw. The
answer clears it, and a terminal that never replies leaves the right thing on
the screen.

## The calculator's other half, and the `Float` it had no business using

predc's RPN calculator opens by saying its integers are exact. The stack holds
`BigInt`, a width is a question put to a value rather than a property the value
carries, and nothing is truncated without a word on the screen saying so. Its
other half divided two doubles.

`18446744073709551615 2 /` is `9223372036854775807.5`. What the calculator
answered was `9223372036854775808`: the dividend rounded up to the nearest
double *before* the division, and the trailing half gone with it. `0.1 0.2 +`
was `0.30000000000000004`. Both were there from the day the tool was written,
in the one program whose whole claim is that a `uint64` is exact, and neither
is visible until somebody types the number that shows it.

`gilramir/gren-bigint` became `gilramir/gren-bignum` -- the same `BigInt`
module plus a `BigDecimal` -- and the swap itself was two lines, because the
module kept its name and every signature predc uses. The interesting part was
what the second module then made possible:

```gren
type alias Decimal =
    { amount : BigDecimal, rounded : Bool }

type Value
    = Whole BigInt
    | Real Decimal
```

`add`, `subBy` and `mul` on a `BigDecimal` widen rather than round, so they
cannot lose anything. Mixing the two halves is exact too, and that is the
second bug fixed by the same change: promoting a `Whole` used to go through
`BigInt.toFloat`, and `BigDecimal.fromBigInt` is a change of representation
rather than a conversion. The only operation left that can lose a digit is a
division that does not terminate.

### The mark is carried, not computed

`ovf` is worked out at display time from the value and the width, because both
are still there to look at. Approximation is not like that: `0.999...` gives no
sign of having been three thirds, and by the time it is drawn the fact is gone.
So `rounded` rides along on the value, is set by the one operation that can set
it, and is ORed by everything downstream -- a sum is no more exact than what
went into it. `1 3 / 3 *` is `~0.99999999999999999999` and says so.

That is also why `Real` holds a record rather than a bare `BigDecimal`. The
alternative was a second constructor for approximate decimals, which would have
made every site that matches `Real` match twice to ask a question only two of
them care about.

### Twenty significant digits, not twenty places

`divByTo` takes decimal *places*, and a fixed number of them is wrong in a way
that only a programmer's calculator walks into. One over the largest `uint64`
begins nineteen zeroes after the point, so twenty places of it is a single
digit of answer and nineteen digits of nothing -- and dividing 1 by a `u64` is
not an exotic thing to do here. The fix is four lines: the magnitude of a
`BigDecimal` is the digit count of its `unscaled` less its `scale`, a
quotient's magnitude is within one of the difference of the operands', and one
either way does not matter for a number that is only going to be read.

    placesFor dividend divisor =
        max significant (significant - (magnitude dividend - magnitude divisor))

The `max` is the other half of it. A huge quotient must not be rounded to
twenty significant digits: those integer digits are all real, and cutting them
would be exactly the lie this change was made to stop.

### And the marker had to go on the left

It was `"  approx"` after the digits, matching `ovf`, and the pty driver
printed what that actually looks like:

    0.0033333333333333333333  appr

Twenty significant digits of a small quotient is most of a thirty-five-column
canvas, so a marker on the right is the first thing to fall off the end of the
line -- and a number too long to show is precisely the case the marker exists
for. A leading `~` is one column, is where the eye already is, and cannot be
cut off by the thing it is warning about. `~0.000000000000000000054210108` is
clipped and still honest.

`ovf` can stay on the right because the value it marks is bounded: sixty-four
bits of anything is a known width, and the marker is a comment on a number that
fits. `~` is not a comment. It is part of how the number is written.

## A program that is sometimes not a program: predc's command line

`predc hex dump.bin` is an unremarkable thing to want. The hex viewer already
opens a file dialog and walks a directory; a person who knows the name should
be able to say it and get the dump. The parsing is unremarkable too --
`gilramir/gren-argparse` describes a CLI as a value and hands back a typed
command, and `Argparse.Parser.run` is a pure function over the tokens, so it
can be called anywhere.

The unremarkable part ends at `--help`, and what it ran into was not argparse
and not the CLI at all. It was this:

```gren
defineProgram ports config =
    Node.defineProgram
        { init = \env ->
            Init.await (config.init env) <| \started ->
                Node.startProgram
                    { model = started.model
                    , command = Cmd.batch [ started.command, render ports config started.model ]
                    }
```

A `Tui` program renders after `init`, always, and **the first render is what
takes the terminal**: the runtime starts Turbo Vision the first time a render
message arrives, and Turbo Vision writes `\x1b[?1049h` and owns the screen from
then on. So a `--help` parsed in Gren printed its help *and* switched to the
alternate screen, which is a thing you notice the moment you pipe it into a
pager.

### The race that was not worth winning

There is an obvious-looking fix: put `Node.exitWithCode` in the same
`Cmd.batch` as the render and rely on the process being gone before the port
message is delivered. It was rejected twice over, and both reasons are worth
writing down because they are general.

The first is that the order is not a contract. Both are commands from one
`init`, and which effect manager the runtime drains first is an implementation
detail of the platform; a program whose correctness is "the exit happened to
run before the port" is a program that breaks on a compiler upgrade with no
diagnostic at all.

The second is worse, and it is in the documentation of the function:
`exitWithCode` "will not wait for tasks like http calls or file system writes
to complete". A help text on the way into `less` is exactly such a write. The
version of this that works on a terminal and truncates on a pipe is the version
that would have shipped.

So the decision has to be made *before* anything is rendered, which means it
has to be made in `init`, which means `init` has to be able to say it.

### `Startup`, and the alias that absorbed it

```gren
type Startup model
    = Start model
    | Exit

defineProgramOrExit : Ports msg -> ProgramConfigurationOrExit model msg -> Program model msg
```

`init` answers with a `Startup` instead of a model. `Start` is the ordinary
path. `Exit` says there is nothing to put on a screen and that the command it
was handed -- print this, set that code -- is the whole of what the program
does: no render is sent, so the runtime never starts Turbo Vision, `view` is
never called, `update` and `subscriptions` are never reached, and node leaves
when the write lands. `Node.setExitCode`, which waits, rather than
`exitWithCode`, which does not.

Three things about the shape are worth keeping.

**The model type is where the flag lives, not a field beside it.** The runtime
carries a `Startup model`, and the two states differ in what they *have*: a
started program has a model, an exiting one has no use for one and should not
have to invent one. `update` and `subscriptions` pattern-match it once and the
`Exit` branch is inert.

**`Tui.Program` swallowed the change whole.** It is an alias --
`type alias Program model msg = Node.Program (Startup model) msg` -- so every
`main : Tui.Program Model Msg` in the package, the fifteen examples included,
is the same line it was before. That is the difference between a type alias and
a type here, and it is why this cost one file.

**`defineProgram` is now four lines of `defineProgramOrExit`**, wrapping the
init in `Start`. Two entry points where one would do, and the alternative was
changing the `init` of every program ever written against this package to get a
capability that most of them will never use. `Argparse.Program` makes the same
trade for the same reason, and has four.

No protocol change, no C++, no runtime JavaScript. The whole of "do not paint"
is *not sending a message*, which is the nicest shape a feature can have in a
one-way protocol.

### What predc has to do by hand, and why

`Argparse.Program` is the runner that would normally handle all of this --
help to stdout, errors to stderr, exit codes, colour. predc cannot use it: it
is a `Node.SimpleProgram`, it ends in a process that exits, and predc's ends in
one that paints. So `Main.init` matches on `CommandParseResult` itself, which
is the manual shape argparse documents, and copies exactly one rule out of the
runner -- colour only if `Terminal.initialize` says a terminal is attached and
`NO_COLOR` is unset. (`Terminal.initialize` is a read of `process.stdout` and
touches nothing, so asking it before Turbo Vision starts is safe.)

One thing predc does that the runner does not: it wraps the help to the
terminal's own width, `PP.defaultOptions.maxColumns` being
`Math.maxSafeInteger` and a paragraph therefore being one very long line.
`terminal.columns` when there is a terminal, eighty when there is not.

### Two decisions in the CLI itself

**An empty argument list is not the help text.** `Argparse.Parser.run []`
answers `HelpText`, which is right for a tool whose every use is a subcommand
and wrong for one whose commonest use is no subcommand at all. `predc` on its
own opens the desktop it always opened, so `Main` checks for empty args before
the parser sees them. This is the sort of thing that is easier to write down
than to rediscover: the parser is not wrong, it is answering a different
question than the one this program asks.

**A file that does not exist is a message, not a refusal.** `predc hex
nosuch.bin` opens the viewer with `ENOENT ...` on its message line rather than
exiting 1 with a complaint. `Tool.Hex.openFile` is `statFile`, the same path
the file dialog takes, and its `Failed` message already lands on that line --
so the error appears where the person is already looking, and the window they
asked for is open and a Ctrl-O away from the file they meant. The `Exit` path
is for command lines that are *wrong*, not for ones that are right about a
world that disagrees.

The same three lines gave `predc hex ~/dumps` for free: `statFile` answers with
*what the name is*, and a directory has meant "list it" since the dialog was
written, so a directory on the command line opens the file dialog already
standing in the right place. Nobody designed that. It is what reusing the
tool's own entry point buys, and it is the argument against `Main` assembling a
read of its own.

### The check that pins it

`\x1b[?1049h` in the byte stream is the whole test. `drive_cli.py` runs
`--help`, `--version` and a bad command under a pty -- the case where a program
*would* paint, since stdout is a terminal -- and asserts that neither the
alternate screen nor mouse tracking nor a clear ever appears, alongside the
exit code and the text. It then runs the same two through a pipe, which is the
only way to tell stdout from stderr (a pty is one file) and the case where the
colour has to come off and the width has to be eighty.

## The scroll bar you had to click twice

`predc hex README.md`, a scroll bar on the right of the dump, and clicking it
was described exactly right: *"I click it and it sometimes advances the view; I
click it again, especially at a higher point, and it doesn't move."* Both
halves of that are true and they have different causes, which is why it felt
like neither.

### The half that was a bug: the first click was eaten

```cpp
void TView::handleEvent(TEvent& event)
{
    if( event.what == evMouseDown )
        if(!(state & (sfSelected | sfDisabled)) && (options & ofSelectable) )
            if( !focus() || !(options & ofFirstClick) )
                clearEvent(event);
}
```

`TScrollBar::handleEvent` calls that first, so a selectable bar that has not
got the caret consumes the mouse-down and does nothing else with it. The caret
is on the dump canvas -- everything a person does in this tool puts it there --
so the *first* click on the bar moved nothing, the second moved, and clicking
back into the dump made the next bar click dead again. Nothing on the screen
says which of the two the next click is: a frame says which *window* is active
and there is no mark at all for which view inside it has the caret.

And it was ours. `JsScrollBar` sets `options |= ofSelectable`, so that a bar
the model asked for by id is reachable by Tab, and Turbo Vision's own bars --
the one a `TListViewer` makes for itself -- are not selectable at all and
therefore never hit that branch. Making the bar keyboard-reachable had quietly
made it worse with a mouse than the one it was modelled on.

`ofFirstClick` is the option that exists for exactly this, and it is one line:

    options |= ofSelectable | ofFirstClick;

The rule to carry forward: **`ofSelectable` on a control whose whole purpose is
to be clicked needs `ofFirstClick` with it.** A button, a check box, a scroll
bar. The two-click rule is right for a *window* -- activating one is a real act
-- and right for a canvas, which is a surface rather than a control. It is
wrong for a widget.

### The half that was not a bug: a click does not page

magiblot's `TScrollBar` diverges from Borland's here, and the comment in
`tscrlbar.cpp` says so:

```cpp
default:            // Otherwise, move the thumb along the mouse cursor.
    ...
    setValue( int(((long(p - 1) * (maxVal - minVal) + ((s - 2) >> 1)) / (s - 2)) + minVal) );
```

Every mouse-down that is not on an arrow takes the thumb *to the pointer* and
drags from there. There is no `sbPageUp`/`sbPageDown` mouse path at all, so
`pageStep` is reached only from the keyboard. That is the modern behaviour and
worth keeping, but it has a consequence nobody expects from a Turbo Vision
program: **the bar's resolution is the number of cells it is tall.** A
sixteen-row bar has thirteen usable positions, so on a nine-kilobyte file one
cell is forty-six rows, and clicking two cells apart is a ninety-two-row jump
while clicking twice in the same cell is nothing at all. That is the "it
doesn't move" -- the pointer was already where the thumb was.

Which is also why the fix matters more than it looks: with the first click
eaten, *both* explanations were live at once, and no sequence of clicks could
tell them apart.

The keyboard and the wheel were both fine throughout and are the better tools
for this job anyway: `PgUp`/`PgDn` page by the model's `pageStep`, and the
wheel is `3 * arrowStep` and reaches the bar from anywhere in the window --
including with the pointer over the dump. Not because the `Canvas` passes it
up: a wheel turn never goes to the view under the pointer in the first place,
which is a stronger fact than it looks and is the subject of *The wheel that
turned the wrong list*, below.

## The double click that arrived and had nowhere to go

Asked from the application, and phrased as a question about the library: *"Does
tvision deliver double-click events? I open Bytes | Open file, select a file,
and double-click it, and nothing happens; I have to click OK."*

It does deliver them, and the proof is one line of the port trace. One double
click on a name in the dialog's list, as the very first thing after it opens:

    <- {"type":"focus","id":"fileList","index":1,"text":"alpha.bin"}
    <- {"type":"select","id":"fileList","index":1,"text":"alpha.bin"}

That is `TListViewer::selectItem`, forwarded by `JsListBox` as a
[`Selected`](Tui#Event) event. Nothing was missing between the terminal and the
model. `TListViewer` even sets `options |= ofFirstClick | ofSelectable` in its
own constructor -- the same pairing the scroll bar had to be taught the day
before -- so the list acts on the first click and the pair is timed normally
against the default 8-tick (440ms) window.

### What was missing was a way to act on it

The model hears `Selected` while the dialog is still open, and **a modal dialog
in this package can only be ended by a command**. There is no
`Tui.closeDialog`, deliberately: a dialog is a `Cmd` answered by a
`DialogClosed`, and something that could dismiss one from the outside would be
a second way for the model to reach into a window it does not own. So the model
could hear the double click and could do nothing with it.

Turbo Vision has exactly this problem and solves it inside the dialog, in four
lines of `tfildlg.cpp`:

```cpp
else if( event.what == evBroadcast && event.message.command == cmFileDoubleClicked )
    {
    event.what = evCommand;
    event.message.command = cmOK;
    putEvent( event );
    clearEvent( event );
    }
```

`Tui.fileDialog` is not a `TFileDialog` -- it is a layout the package builds
out of an `InputLine`, a `ListBox` and buttons, because listing a directory is
a `Task` and belongs to the model -- so it never inherited that wiring.

### `chooses`, and why it is a field rather than an event

    ListBox { id, rect, items, focused, chooses : String }

A command name, meaning *committing an entry is the same act as pressing the
button that carries this command*. `fileDialog` fills it with the first
button's command, which is the default one. `""` everywhere else, which is
every list in a window: there a `Selected` event is the whole answer and the
model does what it likes with it.

This is the fourth time the API has answered a widget with **a declarative
field, because the "interaction" is really a rule the model can state up
front** -- after `allowed` on an `InputLine`, `takesFocus` on a button and
`isDefault`. The test is always the same: could the model answer this at render
time? Here it can, and the alternative -- a round trip in which `Selected`
crosses the port and something crosses back to close the dialog -- would have
added the first message in this protocol capable of dismissing a window from
the outside.

The C++ is `putEvent` and not a direct dispatch, again copying `TFileDialog`:

```cpp
if (chooses != 0) {
    TEvent event = {};
    event.what = evCommand;
    event.message.command = chooses;
    putEvent(event);
}
```

The command goes back through the ordinary queue, so `JsWindow::handleEvent`
ends the modal with it exactly as it does for a button press, and the model is
answered by the same `DialogClosed` with the same `values`. **predc needed no
changes at all**: `answerFile` already preferred the highlighted row when the
Name field was empty, because that is what pressing OK without typing has
always meant.

Protocol 20. An older runtime would pass the new field to a binding that
ignores what it does not know, and the double click would go on doing nothing
-- which is the silence the version number exists to turn into a sentence.

## The copy that did reach the clipboard, and the sentence that said it did not

*"Bytes | Copy copies only in-application; I can't paste outside of predc.
That's useless to me."*

The report was right about the symptom and the message predc printed agreed
with it:

    Copied 16 bytes as hex -- this program only, nothing else took it.

That sentence was wrong, and it had been wrong since the clipboard was bound.
The bytes were on the wire the whole time. Under a pty that advertises nothing
at all -- no `DISPLAY`, no `WAYLAND_DISPLAY`, no `allowWindowOps` -- a yank
still writes:

    OSC 52 written to the terminal: True
      payload: b'00 01 02 03 04 05 06 07 08 09 0A 0B 0C 0D 0E 0F'

### Why the boolean says less than it seems to

`THardwareInfo::setClipboardText` is two attempts (`unixcon.cpp`):

```cpp
if (UnixClipboard::setClipboardText(text)) return true;
if (TermIO::setClipboardText(con, text, inputState)) return true;
```

The first tries `wl-copy`, `xsel` and `xclip`, and `commandIsAvailable` checks
**an environment variable before the executable**: no `WAYLAND_DISPLAY` or
`DISPLAY`, no attempt. Over ssh there is neither, so that half is skipped
whether or not the programs are installed -- and rightly, since the clipboard
it would set is the far machine's.

The second writes the `OSC 52`, and this is the part worth reading twice:

```cpp
con.write(buf, ...);
// Return false when there is no full OSC 52 support, even though we always
// make the request. This way, we can still use the internal clipboard.
return state.hasFullOsc52;
```

`hasFullOsc52` is set only by evidence that the terminal supports **reading**
the clipboard back -- a kitty capability reply, an answer to an `OSC 52` query,
or xterm's `allowWindowOps` in an `OSC 60`. Almost nothing volunteers that. So
the write happens and the return value is `false`, and every layer above
faithfully reported "nothing took it" about a copy that may have worked
perfectly.

### What was actually eating it, measured

The reporter's environment is an ssh session inside tmux 3.4 with
`XDG_SESSION_TYPE=tty`. tmux's own default is `set-clipboard external`, and the
manual page's wording for it -- "attempt to set the terminal clipboard but
ignore attempts by applications to set tmux buffers" -- can be read either way.
An isolated tmux server (`tmux -L probe`) driven through a pty, with an
application inside the pane writing exactly the sequence Turbo Vision writes,
answers it:

    set-clipboard = external   forwarded: no    tmux buffer: none
    set-clipboard = on         forwarded: yes   tmux buffer: set
    set-clipboard = off        forwarded: no    tmux buffer: none

`external` swallows it. Only `on` forwards an application's `OSC 52` to the
terminal outside. That is one line in a `.tmux.conf` and it is the whole fix
for the person who reported this.

### What changed here

Nothing about the copy: it was already doing the only thing it can do over
ssh. The three places that repeated the false claim are now accurate --
`Tui.copyToClipboard`'s doc comment, the `Copied` event's, and predc's message
line, which now says

    Copied 16 bytes as hex -- the terminal did not confirm it.

and predc's README carries the chain, the tmux measurement and the one-line
fix. `drive_hex.py` asserts the new sentence, and the check beside it -- the
one where the driver claims `allowWindowOps` and the caveat disappears -- is
what keeps the two states apart.

**The general rule, which cost a user an afternoon:** a boolean returned by a
platform layer is worth exactly what it was measured with. `setClipboardText`
returns "did the platform confirm", every layer above wrote it down as "did it
work", and the two are not the same claim. When a program repeats a library's
boolean in a sentence a person will read, the sentence has to say what the
boolean actually knows.

## The time converter, and the arithmetic Gren was never going to do

predc's last v1 tool converts one instant between several time zones. Almost
none of it is in Gren, and that was the first decision rather than a
concession.

### A time zone is not an offset, and there is no Gren that knows it

The tempting shape is a table: `America/Chicago` is -06:00, `Asia/Seoul` is
+09:00, done. It is wrong for Chicago half the year, wrong for all of Chicago
in 1974, and wrong about Nepal in either direction -- `Asia/Katmandu` was
+05:30 until 1986 and is +05:45 now. The rules live in the IANA database, which
ships inside every JavaScript runtime as `Intl` and has no Gren equivalent.

Gren core's `Time` is explicit about the half it cannot do. `Time.here`'s own
doc comment says it will never answer `America/New_York` and will hand back
`Etc/GMT-5` or `Etc/GMT-4` depending on the season, "due to limitations in
JavaScript". So `here` is useless for this.

`Time.getZoneName` is not, and this was the one pleasant surprise: it reads
`Intl.DateTimeFormat().resolvedOptions().timeZone` and answers
`Name "America/Chicago"`. **The machine's own zone costs no port at all**, and
that is what predc starts in when its config file has never been written.
`Offset minutes` is the other branch, for a runtime with no `Intl`, which is
not node.

Everything else goes over a second port pair, subscribed in `bin/predc.js` --
which is what the launcher's comment had been anticipating since the shell was
written. `run()` in `gren-tvision-runtime` returns the app precisely so that a
program with ports of its own can have them.

### One reply carries the whole window

The obvious protocol is a request per zone. It is wrong twice: N round trips
per keystroke, and a model holding a half-updated table while the answers
straggle in. So there are two requests and they answer with the same thing:

    {type:"atInstant", posix, zones}          -> {type:"rows", posix, rows, ...}
    {type:"fromParts", zone, y,mo,d,h,mi,s,
                       zones}                 -> {type:"rows", posix, rows, ...}

`rows` is every zone plus UTC, at one instant, with each one's offset in
**minutes** -- Kathmandu and Chatham are at :45, and a converter that cannot
say so is wrong about two countries.

The reply also echoes what was asked for. Several requests can be in flight and
a reply that describes itself needs no bookkeeping on the Gren side to match up
with the request that caused it.

### Getting a wall clock back to an instant

`Intl` will format an instant in a zone. It will not parse one, and it has no
API that hands back a zone's offset as a number. Both are done by subtracting
two clocks:

```js
function offsetMinutes(zone, ms) {
  return Math.round((utcMs(wallAt(zone, ms)) - ms) / 60000);
}
```

and the reverse is a two-pass guess -- assume the zone is at UTC, look up what
it really was near that guess, subtract; that can land on the wrong side of a
daylight-saving change, so look the offset up again at the corrected instant
and subtract that too.

Two candidates come out of that, and **twice a year the wall clock is not a
function**, so which one you take has to be decided rather than fallen into:

  - Both candidates read back as the time asked for: the clock went backwards
    and the instant is ambiguous. Take the earlier -- the first time the clock
    read it, which is what `fold = 0` means everywhere else that has had to
    name this.
  - Neither reads back: the clock jumped forwards and this time does not
    exist. Take the **later**.

The first version took whichever the second pass produced, and that quietly
resolved a missing `02:30` in Chicago to `01:30` -- an hour *earlier* than what
was typed, which is the more surprising of the two wrong answers. Pushing
forward matches the direction the clock moved and matches what `date`, Python
and Java do.

Either way the answer is read back and compared, and a mismatch is reported:

    2026-03-08 02:30 does not exist in America/Chicago -- read as
    2026-03-08 03:30.

The same check catches the 31st of April for free, which is why the day field
still accepts 1 to 31 in every month. How long April is happens to be a
question the one place that knows about calendars already answers.

### Three rules that fall out of recomputing on every keystroke

**The field being typed in is never written back to.** The model holds the id
of the last field touched and the text put in it; that field renders from
there and every other renders from the last reply. Without it, normalising a
typed `5` into `05` moves the caret under the user's fingers on the next
keystroke. It is one `Maybe` and it is load-bearing.

**An incomplete row asks nothing.** `allowed` keeps letters out entirely, and
empty-or-out-of-range is a sentence on the message line with no request sent,
so the other rows keep showing the last instant that made sense.

**A message line has to be two rows.** The sentence above is seventy-eight
characters and the window is sixty. Clipped at one row it read
"...America/Chicago -- read as", which keeps the complaint and loses the
answer.

### A number too big for a calendar used to close the program

Leaning on a digit key in the POSIX box killed predc. `Date` holds ±8.64e15
milliseconds; past that every `Intl` call throws a `RangeError`, and a throw
inside a port subscription takes the process down with the terminal still in
its alternate screen. It is checked before the call now, and the subscription
has a `try` around it as well, because the worst thing a converter can do is
disagree with you about a date by vanishing.

**The general rule:** a port subscription is an uncaught-exception boundary
with a terminal on the other side of it. Anything reachable from user input
belongs inside a `try`.

### The formatter that renamed a parameter, and whose bug it was

`fromParts ports posix wanted asked` came back from `gren-format` as
`fromParts ports posix (wanted as ked)`, which does not compile. It looks like
a formatter bug and is not: it is
[compiler-common#31](https://github.com/gren-lang/compiler-common/issues/31),
where the shared parser lexes the `as` pattern-alias keyword without checking
for a word boundary, so any parameter whose name *begins* with `as` is split in
two. `gren-format` inherits it along with the parser.

**The lesson is about where to look rather than about the bug.**
`gren-format-lib`'s own documentation has a *Known limitations and Bugs*
section listing every open upstream issue that affects its output, and #31 is
in it. Reading that first would have cost a minute; deriving it from a minimal
repro cost rather more, and produced a report of something already reported.
When a formatter appears to be wrong, that list is the first stop.

### `maxLen` was one short

`2026` came out as `202`. `TInputLine`'s constructor takes a *limit* and stores
`maxLen = limit - 1`, and `views.cc` passed the model's `maxLen` through as the
limit -- so every field held one character fewer than it asked for. Invisible
for fifteen examples, because the only `maxLen` in the package is
`fileDialog`'s 255. Fixed at the construction site; no protocol change, since
the wire field's meaning merely became correct. The rectangle needs one more
column than that again, for the caret.

### The picker is a window because a dialog cannot be redrawn

The zone picker filters 418 names as you type. `Tui.dialog` builds its views
once and reads them back as it is destroyed, so a live filter inside a modal is
not expressible; `Tool.Hex` reopens its dialog to change directory, which is
right for a directory and hopeless for a keystroke. So the picker is an
ordinary window, which loses nothing -- a modal is for a question and this is a
workspace.

**One piece of state, not two.** An area list *and* a filter would need a rule
about which wins, and that rule would be invisible. So choosing an area types
its prefix into the same Find box: `Asia` gives `Asia/`, typing `seo` gives
`Asia/seo`. The box on the screen is then always the whole reason you are or
are not seeing something. `All` is the first row rather than a mode, which also
answers an unavoidable event -- Turbo Vision highlights a list's first entry
when the window opens, and with the areas alone at the top that silently
filtered the picker to Africa before anybody touched it.

The counts are on the rows because the two levels help very unevenly:
`America` is 144 names, `Arctic` is one.

### The window that kept coming to the front

Adding a zone buried the picker under the converter. `Tui.focus` was being sent
with the request, and the runtime *does* re-apply a pending focus after the
render it came with -- but the render that rebuilds the converter is the next
one. Adding a zone does not make the table taller until the reply arrives with
a row in it, and a window whose view list changed is rebuilt rather than
patched, and a rebuilt window arrives on top.

So the focus is asked for **on the reply**, behind a flag, rather than on the
click -- and a flag rather than "always refocus the picker", because the user
may have clicked down to the converter deliberately and a reply that yanked the
caret back would be worse than the bug.

The port trace found this. The screen said only "wrong window in front", which
is consistent with about four different causes.

### Alt-T, and the hotkey that cost the Tools menu

The converter is on `Alt-C`. `Alt-T` is the obvious letter and it is the menu
bar's, for `~T~ools` -- and the status line wins, measured: putting the
converter on `Alt-T` opened the converter and silently cost the Tools menu its
hotkey. A shortcut for one tool is not worth the gateway to all of them.

The picker's three buttons carry no hotkey at all, which is the same rule the
calculator's keypad follows: `~A~dd` binds Alt-A, the status line has Alt-A for
the ASCII chart and is `ofPreProcess`, so pressing Add opened the ASCII chart.
Buttons serve the mouse; `Space` on a `ListBox` serves the keyboard.

### Two port pairs, and the type that cannot tell them apart

`Tui.Ports msg` and the converter's own `Ports msg` are the *same record of two
functions*. Handing one where the other belongs compiles silently and posts
Turbo Vision's traffic to the time zone helper. Nothing can catch that -- Gren's
records are structural -- so the two live in one record with field names,
`{ intl, tui }`, and the field name is the entire defence.

### `Maybe (Array String)` in the config, and why not an array

`Nothing` means predc has never been told and starts at this machine's zone;
`Just []` means the user removed them all and gets UTC and POSIX alone.
Collapsed into a bare array, emptying the list would put the local zone back on
the next run with no way left to say what the user plainly said. `Nothing`
writes no key at all rather than a `null`, so a config file predc has never
asked about zones is indistinguishable from one the previous version wrote.

Adding the field also forced every field in that decoder to become
independently optional. A required-field decoder would have thrown away a
`config.json` written yesterday -- theme and all -- for not mentioning time
zones.

### The name in the list is not always the name that works

`Intl.supportedValuesOf('timeZone')` returns canonical names, and a few of
those are the old spellings: the list says `Asia/Katmandu` and never
`Asia/Kathmandu`, though `Intl` accepts both. So a zone written into the config
file by hand can be one the picker cannot find, and it still works, because the
JavaScript side asks `Intl` whether a name is real rather than checking it
against the browsable list. Cost half an hour of believing the filter was
broken.

### What the tests are split by

`drive_time.py` drives the window: what a keystroke does, which row moves, that
the caret stays. `timezones.checks.js` -- run by `drive_timezones.py`, since
`tools/run_tests.py` discovers `test/drive*.py` and there is no list -- asks
the database questions a pty is the wrong instrument for: Nepal in 1970, the
two Chicago mornings, year 70 meaning 70, a name node has never heard of.

`TZ` is set for the whole pty run, which is what turns "the machine's own zone"
from a fact about whoever is running the suite into something a check can
assert. node honours it and `getZoneName` reports it.

## The wheel that turned the wrong list

Reported from the time zone picker: *"I selected Asia, then in the Zone list
I'm trying to scroll, but instead it's trying to scroll the Displaying column."*
Exactly right, and the pointer had nothing to do with it -- the Displaying
column would have taken that wheel turn from anywhere in the window.

### A wheel turn is not a positional event

```cpp
// views.h
positionalEvents    = evMouse & ~evMouseWheel,
```

Which is the whole finding. `TGroup::handleEvent` has three routes and the
wheel takes the third:

```cpp
else if( event.what )
    {
    phase = phFocused;
    if( (event.what & positionalEvents) != 0 )
        doHandleEvent( firstThat( hasMouse, &event ), &hs );   // a click
    else
        forEach( doHandleEvent, &hs );                          // a wheel turn
    }
```

A click is delivered to the view under the pointer. A wheel turn is offered to
*every* view in z-order until one clears it, and `TScrollBar` is the only stock
view that asks for `evMouseWheel` at all (`tscrlbar.cpp:57` puts it in the
`eventMask`; nothing else in the library does). So the wheel belongs to
whichever scroll bar is frontmost in the window, wherever the pointer is -- and
frontmost means last inserted, because `TGroup::insert` puts a view at the
front. The picker inserts its three lists left to right, so `Displaying`'s bar
was in front of the zone list's, and turning the wheel anywhere in that window
moved the rightmost column.

This is not a bug in Turbo Vision. In a window that is one pane and its bar --
which is every window in `tvision/examples/` -- it is the better rule: the
wheel works over the text, over the frame, over the status area, everywhere,
and the alternative would be worse. It takes a window with more than one
scrollable pane to see it at all, and this repo did not have one until predc
put three lists side by side.

### The bar answers for a region instead of for the window

`PaneScrollBar` in `tvnode.h`, and it is the whole change:

```cpp
if (event.what == evMouseWheel && pane != nullptr &&
    !mouseInView(event.mouse.where) && !pane->mouseInView(event.mouse.where))
    return;
TScrollBar::handleEvent(event);
```

The bar a `listBox` or an `editor` makes for itself now knows which view it
scrolls, and takes a wheel turn only over that view or over its own column.
`mouseInView` takes screen coordinates and converts them itself, which is why
the question can be asked of two views in one line. A single-pane window is
unchanged, because the pointer is over the pane.

`pane` is set after construction rather than passed in: `TListViewer`'s
constructor wants its scroll bar to already exist, so the bar cannot know its
list at the moment it is built.

### The bar the model owns cannot be told, so it is asked

A `ScrollBar` the *model* put in a window is the other half, and it could not
be fixed the same way: it scrolls something the binding cannot see. In `predc
hex` it drives a `Canvas` the model paints, and nothing on the C++ side knows
the two go together. There is no pane to infer.

So it is named. `for` on `ScrollBar`, resolved by id at build time, which is
the shape `Label` and `History` already use -- **list the view before the
bar** -- with one difference: theirs must name a particular kind of view (a
control, an input line), and this one may name any view at all, because what a
model-owned bar scrolls is usually a canvas.

`""` is not an omission and not a default that will be tightened later. It is
the right answer for the majority: a window whose only scrollable thing is
this bar's wants the wheel from everywhere in it, including with the pointer
over the content, which is where a hand already is. `mouse`, `watch`,
`viewer` and `predc hex` all say `""` and all mean it.

`examples/dir` is the one that wanted the field, and it is the case that
proves the rule is not academic: a tree `ListBox` on the left, a model-owned
bar for the file pane on the right, the file bar inserted last and therefore
in front. Turning the wheel over the *tree* scrolled the *files*, and there
was no pointer position anywhere in that window that could scroll the tree.

Which is what `JsScrollBar` deriving from `PaneScrollBar` rather than from
`TScrollBar` is for: one implementation of the rule, and the model-owned bar
opts into it by naming something.

### Driving a wheel from a test

`\x1b[<65;col;rowM` -- SGR codes 64 and 65 instead of a button, and a press
with no release, because a wheel has nothing to let go of
(`termio.cpp:541`). `Pty.wheel()` in the harness.

One turn is `3 * arrowStep`, so on a nine-row list the first three turns only
walk the highlight down inside what is already on the screen and the fourth is
the first one that scrolls. A check that turned the wheel once and looked at
the top row would have passed before the fix and after it.

The check that bites hardest is the one on the *area* list, because it reads
out in text: choosing an area writes its prefix into `Find`, so a wheel that
reaches the areas at all is a wheel that changes the box. The zone list can
only be checked by what scrolled; the area list says which pane got the event.

`drive_dir.py` does the same trick with no scrolling at all, and it is the
better version. Neither of that window's panes has enough rows to move --
the fixture is four directories and a handful of files -- but the tree's
highlight *is* the directory being shown, so a wheel turn that reaches the tree
changes the title and the file list, and one that does not reach it changes
nothing. A test for which pane got an event does not need a pane long enough to
scroll; it needs a pane that says out loud when it was touched.

## The button that acted on the first row, whatever the highlight said

Reported straight after the wheel was fixed, and the two are related only in
that fixing the first made the second easy to hit: *"my cursor is on
Asia/Seoul, and then I clicked Add, but Asia/Aden was added."* The same with
Remove, on the other list.

### A list box's highlight lives in C++, and only one event says where it is

`Tui.gren` has said so all along, in the sentence describing the event:

> `Focused` -- the highlight in a list box moved, by arrow key, mouse or a
> render that replaced the list. **This is how the model learns which entry an
> "Edit" or "Delete" button should act on**; Turbo Vision's own examples read
> the list's `focused` member at the moment they need it, which a program that
> cannot call into C++ has no way to do.

The picker handled `Focused` for exactly one of its three lists -- the area
list, where it is load-bearing, because choosing an area *is* writing its
prefix into Find. The zone list and the Displaying list had no branch at all.

So `picker.highlight` and `picker.picked` were only ever written by
`Tui.Selected`, which carries an index of its own. `Space` and a double click
were therefore always right, and every check in the suite went through
`space_on()` and passed. The buttons read the model's copy, and the last thing
to have written to it was a filter reset -- `highlight = 0`. Add added row
zero. Click, arrow key or wheel, however far down, made no difference to it at
all.

Three lines fixed it, and the shape of the bug is worth more than the fix:
**an event handled for one view of a kind and not for its siblings.** The area
list needed `Focused` for a visible, interesting reason, which is exactly what
made it look like an area-list feature rather than the list-box contract it
is.

### And the test suite was written in the one style that could not see it

`space_on()` clicks a row and presses `Space`, which is how the picker is meant
to be driven and is what the pty checks had always used. It sends `Selected`,
and `Selected` carries the index, so the stale copy was never read. A driver
that used the buttons instead would have caught this on the day the picker was
written.

The new checks click a row and press the *button*, which is the other half of
the same act -- and one of them borrows a zone and puts it back, so the state
the later checks read is unchanged. The rule that falls out: **drive a widget
by every route the user has, not by the one the model treats as canonical.**

## Cancel, on a window that has already committed everything

Asked for in the same breath: *"this zone window also needs a Cancel button, so
we can exit it without saving the changes."*

There was nothing to not-save. The picker applies every add and remove to the
converter as it happens -- `withPicker` sets `model.zones` and asks for the
recompute -- because that is what makes it a workspace rather than a form: you
add Seoul, the row appears behind you, and that is the answer to "is that the
one I meant". `Main` writes the config file whenever what the converter is
displaying disagrees with what the file says, so the file is already written
too, by the time a hand reaches the button.

So Cancel could not be "do not commit". It is an undo, and the thing it undoes
to has to be *remembered when the picker opens*, because by the time it is
pressed no other copy of the list the user started with exists. One field on
`Picker`, set once in `open`.

The config file needs no part of this and gets none: restoring `model.zones`
makes the converter disagree with the file, and the shell writes it for the
same reason it wrote every other change. A cancel that changed nothing writes
nothing. That comparison-not-message design in `Main` was written for the
picker's *four* ways of changing the list; a fifth arrived and cost nothing,
which is the argument for it made concrete a year late.

**Closing the window is not Cancel.** The close box and `Alt-F3` keep what is
on the screen. Turbo Vision's own convention is the opposite -- a dialog's
close box is `cmCancel` -- and it is the wrong convention here: everything in
that window has been visible on the converter behind it for as long as it has
been open, and a close box that threw away five zones the user had just watched
appear is a worse surprise than one that keeps them. The picker is only a
window rather than a dialog for a redraw reason, but this is a place where it
should behave like one.

### The layout cost

A fourth button did not fit beside the third, so the row moved left rather than
Cancel going on the end: `Add >>` from column 19 to 4, and Done and Cancel in
that order, which is the order every Turbo Vision dialog puts them in. None of
them carries an `Alt` letter, for the reason the others do not -- `~C~ancel`
would bind Alt-C and the status line has that for the converter itself.

## Reordering the list, and `Array.get -1`

*"How are the times sorted? In order of adding? We need a way to re-order the
zones, like a move up / move down set of buttons."* Order of adding, yes, with
`UTC` appended last and never in the list -- and until now the only way to
change it was to remove three zones so as to put them back differently.

The move itself is a swap of two rows, and `picked` follows the row rather
than staying on the position, which is the only reading of pressing the button
twice that is any use: it moves one zone two places instead of moving two
different zones one place each. `withPicker` carries the rest -- the table
recomputes, the config file follows, Cancel still undoes the lot.

### The trap: a negative index is not out of bounds

```gren
    when Array.get to picker.chosen is
        Nothing -> { model = model, command = Cmd.none }
        Just other -> ...
```

Which is the obvious guard and is wrong. gren core:

> Retrieve the element at a given index, or `Nothing` if the index is out of
> bounds. **A negative index looks up an element in reverse from the end of the
> array.**
>
>     get -1 [ 1, 2, 3 ] == Just 3

So `Move Up` on the top row asked for index `-1`, got the *last* zone, and
swapped the first with the last. `Array.set` does the same, so both ends were
written. On the screen it did not read as an off-by-one; it read as the list
shuffling itself, which is a much worse thing to debug.

The bounds test is now written out -- `if to < 0 || to >= Array.length` -- and
this is the second Gren-shaped trap in this one module, after `//` truncating
its *result* to 32 bits. Both have the same character: an API close enough to
what you expect that the difference does not announce itself, and a symptom
that looks like an application bug.

## The converter that is sometimes a clock

*"Could we have a toggle button which converts this to a clock, which updates
every minute? It would disable the editing of the times until Clock mode is
turned off."*

### Read-only by being a different widget

The fields become `StaticText` while the clock runs, rather than input lines
that ignore what is typed into them. In a model that re-renders that is barely
any more code -- one branch in `clockRow` -- and it is the honest version:
there is nothing to type into, rather than a field that swallows it. It also
looks right without being styled, because an input line carries its own
background colour and a static text wears the window's.

One column of arithmetic came with it. `TInputLine::draw` writes its text at
offset 1 inside its own rectangle (`tinputli.cpp:144`), so a static text at the
same `x1` sits one column left of the digits it replaces and the whole table
slides out from under its heading the moment the clock starts. `+ 1` on the x,
and `width` rather than `width + 2` -- the two spare columns were the input
line's margins and a static text has none.

### A tick a second, a recomputation a minute

`Time.every` counts from whenever it was subscribed, not from the top of the
minute, so a sixty-second interval leaves the window up to fifty-nine seconds
stale and a clock that says 10:31 while it is 10:32 is simply wrong. The tick
is therefore once a second, and `update` decides what a tick is worth:

  - a different second: set `posix`. The POSIX line moves; nothing else can.
  - a different *minute*: set `posix` **and** ask the helper for the table.

So the port carries one message a minute and the screen gets one `setText` a
second. Verified by hand -- the recomputation landed on POSIX `1788351000`,
which is a multiple of sixty, so the tick is not merely firing, it is firing on
the boundary.

The reply carries back the instant it was asked about, so `Answered` writing
`posix` from it is a no-op rather than a second that stutters: it arrives in
milliseconds, while this side is still on the second that sent it.

### A button with two captions, and the check box that would have worked

A toggle wants a check box, and the first draft of this note said `CheckBoxes`
could not be one -- *"a cluster reports what is ticked only when a dialog is
answered"*. That was wrong, and it was wrong because of a stale comment in
`diff.js` that is still describing the world before protocol 8. `Changed` is
exactly the event that closed this hole, its own doc comment says so in as many
words, and `JsCheckBoxes::handleEvent` sends `noteChangedFlags` on any change
with no dialog anywhere near it. Building it proved it: a one-item cluster in
the converter's button row, `Alt-L`, and the clock started.

**The lesson is about the comment, not the cluster.** A note that explains a
limit is a load-bearing claim, and when the limit is lifted the note becomes a
lie that reads like documentation. `diff.js`'s comment was right about the
*rule* it guards -- write a cluster back only when the model changed it -- and
its stated reason had been false for several protocol versions. It is fixed,
and it is the second time in this file that a stale explanation for a correct
rule has cost an hour.

So the button is a design choice and not a constraint: it sits in a row of
buttons with `Now` and `Zones...`, and a caption can say what pressing it does
where a tick can only say what is true. The title bar carries the state --
`Time converter -- live` -- which is the job the check box would have done.

`L` and `S` because both are free, and the two letters that read best were not:
`~C~lock` binds Alt-C, the status line is `ofPreProcess` and already has Alt-C
for the converter, so the button would have opened the window it is in.
Alt-D for "Down" is the hex viewer for the same reason. This is the third time
the status line has picked the letters in this program.

### What the pty driver can and cannot ask

It checks that the mode is live, that it is read-only and that it stops. It
does not check the minute turning over, and the reason is arithmetic rather
than principle: the tick recomputes on the minute, so a driver that waited for
one would wait up to sixty seconds, and `drive_time.py` is already the slowest
of the twenty-nine suites and sets the wall clock for all of them.

What makes the cheap half checkable at all is the POSIX line counting seconds
where the clocks count minutes. Three seconds of waiting proves the
subscription is alive, and it costs the suite three seconds rather than sixty.
That is not why the POSIX line counts -- it counts because a POSIX timestamp
*is* a count of seconds and the rows have no seconds column -- but a design
that makes a fast test possible is worth noticing when it happens.

## The drag, and the capture Turbo Vision keeps inside a loop

The last thing on the sweep that started with the unbound clipboard.
`JsCanvas::handleEvent` forwarded `evMouseDown` and nothing else, so a model
could hear a click and could not hear a drag, and `Tui.Event` had no variant to
hear one with. predc's hex viewer wanted it for extending a highlight and got
most of the way there without it — the far end of a mark *is* the cursor, so a
click extends one — but "press here, pull to there" is a gesture the package
simply did not have.

It is now `Tui.Dragged { id, x, y, isDone }`, protocol 21. Most of what had to
be decided to get there is not about mice.

### A drag needs a capture, and a capture is what the nested loop was for

`TGroup::handleEvent` routes a positional event to `firstThat(hasMouse)`
(`tgroup.cpp:377`) — the view the pointer is over *now*. That is correct for a
click and useless for a drag: pull a selection one column past the edge of the
canvas and the motion belongs to the frame, or to the window underneath, or to
nothing.

Every stock Turbo Vision view that drags gets round this the same way, with
`TView::mouseEvent(event, evMouseMove | evMouseAuto)` in a `do…while` inside
`handleEvent` (`tview.cpp:636`) — which pulls events out of the queue itself
and is therefore a nested event loop, the exact shape this package refuses
everywhere else and the reason the menu bar's one is a known defect.

So the capture is written out longhand instead: a `JsCanvas *` set by the
press, consulted by the pump before it routes, cleared by the release. One
pointer, a couple of dozen lines, and no loop. **The nested loop was never the
point of `mouseEvent` — the capture was**, and a capture is a variable.

Three things fall out of it that are worth knowing before writing the next one.
The pointer has to be cleared in `~JsCanvas`, because a window closed mid-drag
would otherwise leave the pump dereferencing freed memory on the very next
motion. It has to be cleared when a modal opens, because every event now goes
to the modal and the release that would have ended the gesture is never coming.
And the captured view gets `handleEvent` and no `eventError`: that call takes a
`TGroup *` and a canvas is not one.

### The coordinates are not clamped, and that is the whole of the edge case

A drag pulled above a canvas reports row `-1`, and past the bottom it reports
`rows`. Clamping in C++ was the obvious thing and is the wrong one: a model that
wants the cells it owns clamps in one line, and a model that wants to scroll
needs the number that says *how far past*. Nobody can un-clamp a clamped
coordinate back into "off the top". So the honest number goes out and
`examples/ascii` demonstrates the clamp on the Gren side, in the `moveTo` it
already had for Home and End.

What is deliberately *not* forwarded is `evMouseAuto`, which Turbo Vision fires
repeatedly while a button is held still (`tevent.cpp:196`). That is the event
that would buy "hold it off the bottom edge and keep scrolling", and it is a
separate decision rather than an oversight: its whole job is to report a
position that has not changed, which is the one thing the collapse below exists
to throw away. It would need its own variant or its own flag, and nothing has
asked for it yet.

### A plain click has to stay a plain click

The first design reported the release of every gesture, and every single click
on a canvas became two events. Clicking is what a canvas is mostly for, so:
the press arms the capture and sends nothing extra, the first cell the pointer
*moves* to sends the first `Dragged`, and the release sends one only if there
was motion to end. A click is exactly the one `Clicked` it has always been, and
`drive_ascii.py` pins that with a click after a drag.

The same rule inside predc is what lets the mouse draw a mark without taking
away the click that moves the cursor: the press moves the cursor, the first
motion turns that position into the mark's anchor, and every motion after it is
the ordinary `clickAt`. One small function in `Tool/Hex.gren`, and `v`, `1`-`6`,
the legend, `y` and the dump copy all work on what the mouse drew without
knowing a mouse was involved.

### One thing the capture cannot rescue: the focusing click

`TView::handleEvent` spends the first mouse-down on a selectable view that does
not hold the selection on giving it the selection, and clears the event
(`tview.cpp:551-558`) unless the view carries `ofFirstClick`. A canvas with
`takesFocus = True` therefore does not hear that click.

**The condition is `sfSelected`, not `sfFocused`, and that is what makes it
rare enough to have gone unnoticed.** `sfSelected` means *current within its own
owner*, so a window whose only selectable view is the canvas has an
always-selected canvas and never sees this at all -- which is every example in
this repo. It takes a second selectable view in the same window to reach it,
and predc's hex viewer has one: the model-owned `ScrollBar` down its right
edge. Measured there, with the file open and the cursor at 0:

| what was clicked                     | where the cursor went |
| ------------------------------------ | --------------------- |
| the dump, canvas holding the selection | 0 → 34 (it acted)     |
| the scroll bar                       | the bar is selected now |
| the dump again                       | 34 (the click was spent) |
| the dump a second time               | 34 → 84 (it acted)    |

It matters more than it did, because the press is what creates the capture: a
drag begun with the focusing click is not a drag, it is a selection, and the
motion after it belongs to nobody.

**Kept as it is, on purpose (Gilbert, 2026-09-02): the first click brings the
view back and does nothing else.** The alternative is `ofFirstClick`, which is
what `JsScrollBar` carries -- and the note beside that class says why the two
flags together were awkward for a *bar*, where a click has a position-dependent
meaning and nothing on screen says whether it counted. The argument against it
for a canvas is different and simpler: a window with a scroll bar in it has two
things the user can be pointing at, and one click that both moved the selection
and acted would act inside a view the user had not been working in. Two clicks
is the cheaper surprise. `drive_hex.py` pins all four rows of that table plus
the drag, because a decision with no test is a decision the next edit undoes
without telling anybody.

### Motion is collapsed per pump, like a scroll bar's positions

The pointer crossing six cells is six events and only the sixth means anything,
which is the argument `noteScrolled` already makes about a thumb drag. So
`noteDragged` collapses per canvas and `flushDragged` runs once per pass of the
pump rather than at each event's safe point — the collapse is worth nothing if
it is drained between the events it is meant to merge.

The release wins any collapse it takes part in, because it arrives last, so a
whole flick of the wrist can reach the model as a single event with `isDone`
set. A model that only acts on `isDone` still learns where the drag ended; one
that draws a selection as it grows acts on all of them.

One ordering hazard came with that and is worth naming because it is generic.
**A click is dispatched where it happens and a drag is queued, so mixing the
two mixes their order**: a press arriving in the same pass as the end of the
previous gesture would overtake it. `dispatchClick` therefore flushes the drag
notes before it dispatches. Any future event that is queued alongside one that
is not has the same problem in the same place.

### Driving one from a test

SGR mouse reporting encodes motion as the button code **plus 32**
(`termio.cpp:531`), and TVision has mode 1002 on from startup, so a driver can
send one. What classifies it is not the terminal but `TEventQueue`: a `32` sets
the same button bit a press does, and `getMouseEvent` calls it `evMouseDown`,
`evMouseMove` or `evMouseUp` by comparing against the buttons that were already
down (`tevent.cpp:108-190`). A release at a position the pointer had not
reported yet is split into a move and a *deferred* up, which is what
`pendingMouseUp` is for.

`harness.py` grew `drag(path)` — press at the first cell, motion through the
rest, release at the last. The check worth copying is not that the cursor
follows the pointer; it is the one that drags to screen (1, 1), the top-left
corner of the desktop and nowhere near the chart. It arrives anyway, and it
arrives with negative coordinates. Nothing else asserts that the capture is
real.

## Surveying the library instead of the examples

Coverage here was decided by porting the C++ examples one at a time, and the
method has a failure mode that took until now to name: **it finds what an
example happened to need, and nothing else.** `examples/README.md` said "the
widget set is complete" and meant it — every `TView` subclass was wrapped. Every
gap found since has been a *member* of one of those subclasses. `maxLen` off by
one. A scroll bar with no `ofFirstClick`. A list box that could not say what a
double click meant. No motion event to hear a drag with. Each one found by
writing an application against the binding, which is the most expensive place
to find anything.

`tools/audit_api.py` asks the other question and `tools/decisions.tsv` holds the
answers: every public member of every wrapped class needs a line saying what was
decided about it, and a member with no line fails `check`.

### The verdict that makes it worth anything is `used`

The first draft had `bound` and `internal` and would have been useless.
"The C++ mentions it" is not "a Gren program can ask for it", and a survey that
conflates them produces exactly the false comfort that "the widget set is
complete" produced. `TView::makeLocal` is called by the binding on every click
and is not a capability anybody can name; `TListViewer::numCols` was called by
nothing and was a capability people wanted. So the file distinguishes `bound`
(reachable from Gren), `used` (the binding calls it, and no model names it),
`internal`, `skipped` with a reason, and `todo` with what the gap would buy.

### A member-level walk cannot see a flag

Turbo Vision keeps much of its configurability in *bits* — `options`, `state`,
`growMode`, a window's `flags` — so a walk over members sees one member called
`options` and calls it covered. `ofFirstClick` is a bit, and a scroll bar that
had to be clicked twice is what finding it cost. Auditing the bit names
separately found four more gaps that the member walk had missed, including the
one that turned out to matter most.

### `setEnabled` greys a command, and most views do not have one

`Tui.setEnabled` disables a *command*, everywhere it appears — a menu entry, a
status line entry, a button carrying it. An `InputLine`, a `ListBox`, a
`ScrollBar` and a `Canvas` carry no command at all, so `sfDisabled` was
unreachable and **there was no way to say that a control is not available**.
Not a corner: it is what every form does while it is waiting for something, and
it had been missing since the first window this package drew.

It is the `Enabled` wrapper now, for the reason `Grows` is one — being
available is `TView`'s, so it is true of every widget rather than of any one of
them. Two things fell out of adding a second wrapper. `encodeView` had been
matching one level and now walks down, and "the outer one wins" had been true
by accident (the inner wrapper's field was dropped on the way past rather than
overridden) and is now `keepFirst`, which is deliberate. And
`check_consistency.py`'s exemption became a set: a wrapper has no wire type of
its own and never will, and naming them is what keeps the four-layer walk exact
for the widgets.

### The check for a disabled view is what it refuses, not what colour it is

Turbo Vision greys a disabled view *and* skips it in the tab order *and* hands
it no keystroke and no click (`TGroup::doHandleEvent` tests `sfDisabled` before
anything else). The first driver check read the foreground colour off the cell
and could not tell the difference between a greyed field and the same field —
the palette answers 97 either way at that column. Typing at it and finding the
characters absent is the assertion that means something, and it is the half a
screenshot cannot show.

The same shape one level down: `TCluster::buttonState` gates both the arrow
keys and the hotkey (`tcluster.cpp:170`), so `available` on a cluster is
checked by pressing Down and landing two boxes further on.

### `topItem` is the one field that can hide the highlight

A list's vertical scroll bar tracks `focused` and not `topItem`
(`tlstview.cpp:159-183`): Turbo Vision moves the top itself to keep the focused
item visible and offers no way to say it. So `top` is the only field in this
package with which a model can put the highlight out of sight, and that is
deliberate — "scroll the list" and "move the highlight" are two sentences, and
deciding which one a model meant on its behalf is worse than doing what it
said. The next thing that moves the highlight scrolls it back.

It has to be written **after** `focused` at both ends, the builder and the
differ, because moving the highlight scrolls the list: a `top` written first is
a `top` undone, silently.

### And one that looked exactly like the feature not working

A cluster's captions carry hotkey tildes, so the rule `!/phone/i.test(name)`
tested against `~P~hone` and matched nothing: every box came out available and
the new flag appeared to do nothing at all. The driver caught it. Worth
remembering because the failure is indistinguishable from a broken binding
until you print the string.

## Hidden, disabled, and absent are three things

The audit's second batch, and the interesting part is that all three of these
were expressible before by *accident* and each accident cost something.

**Absent** — leaving a view out of the render — is a structural change, so the
differ tears the window down and builds it again. That is right when the view
is genuinely gone and wrong as a way of saying "not now": it throws away the
caret, an editor's document and every list highlight in the window. `entries`
would have rebuilt its window the first time a filter was remembered, because
that is the moment the history arrow would have appeared.

**Disabled** is `sfDisabled`: drawn grey, skipped by Tab, handed no event.
**Hidden** is `sfVisible`: not drawn at all, and the view survives. Neither was
reachable, and the two are different enough that both are worth having --
a control that is unavailable should say so, and a control that has nothing
behind it should not be there.

Both are wrappers, which makes three of them, and three is where the shape had
to be made deliberate rather than incidental. `encodeView` had matched one
level of `Grows`; it walks down now. And "the outer wrapper wins" had been true
because the inner one's field was *dropped on the way past* rather than
overridden -- an accident that read like a rule. `keepFirst` is the rule.

### Raising a window used to be a side effect of breaking it

The only way to bring a window to the front was to change something structural
about it, so that the differ closed it and built a new one -- in front, because
a new window is. It worked. It is written up two sections above this file as
"a rebuilt window comes to the front, one update later than you think", filed
as a surprise to be careful of, and nobody noticed that the reason it was a
surprise is that the thing it was standing in for did not exist.

`Tui.bringToFront` is `TView::select` and not `makeFirst`, although the gap was
named after `makeFirst`. A `TWindow` sets `ofTopSelect` in its constructor
(twindow.cpp:50) and `TView::select` calls `makeFirst()` for a view that has it
(tview.cpp:732), so selecting raises *and* focuses -- and a raised window
without the caret is a state Turbo Vision has no way to be in. Wrapping the
narrower call would have offered a shape the library does not have.

### The check that a window cannot be closed is two checks

The close box being absent and the window refusing to go are different claims,
and only the second is what the model asked for: `TFrame::draw` gates the icon
on `wfClose` (tframe.cpp:96) and `TFrame::handleEvent` gates the *command* on
it separately. A binding could get one right and the other wrong. `drive_hello.py`
asserts both, and the first run of it failed for a third reason entirely --
the example's `main.js` had not been rebuilt after the source changed, so the
driver was running the old program. Worth knowing: a pty driver tests the build,
not the source, and a stale build fails in ways that look like the feature.

## Who owns a setting decides where it lives

The last six gaps were all on `TEditor` and closed together, because they were
one question: **who moves this?** The answer picked the mechanism each time,
and the rule generalises past editors.

*The model owns it* → a field on the view. `autoIndent` is this. Structural
here rather than patched, which is a second decision and a deliberate one: an
editor is the only view that loses its contents when rebuilt, so a setting that
rebuilds it had better be one a program makes once.

*The user owns it* → an event, and **not** a field. Insert-versus-overwrite is
this. A field the user can move is a field the model writes back on the next
render, which is the exact trap `value` on an input line already documents and
the reason the runtime records what a view reported before the model is asked.
Making `overwrite` a field would have re-created that bug in a place with no
existing defence.

*Nobody owns it* — it is a fact about the document that changes under both →
also an event, for a different reason. `canUndo` and `hasSelection` could only
otherwise be *asked for*, and this port has never had a synchronous query. They
ride on `Edited`, which was already being sent on every keystroke and already
carried the caret on exactly the same argument.

What that bought is small and precise, and is the sort of thing that had been
quietly wrong for months: `examples/edit` now greys **Undo** when there is
nothing to undo and **Cut** when nothing is selected. Before this it could not
know, so both stayed lit and the program offered two actions that would do
nothing.

### Seeding the "last seen" flags to the impossible

`JsEditor` reports only when something changed, which is what stops a burst of
arrow keys being a burst of events. The three new facts join that comparison —
and their `last*` members are seeded to `true` rather than to `false`, so that
the *first* notification always goes out. A model that greys Undo needs to be
told it is unavailable before anything has happened, not only once something
has; seeded the other way, an editor opens with a lit Undo and stays that way
until the first keystroke.

### And the check that says which grey

A disabled *view* is checked by what it refuses, because a colour read off the
screen is a claim about the palette. A disabled *menu entry* is the opposite:
an entry is only ever looked at, so how it looks is what it does. The check
compares Undo's ink against Cut's rather than against a number -- the claim is
that the two are in different states -- and only then names the colour of the
one that is greyed.

## The clipboard you cannot read, and the field that replaced it

`predc unicode` over ssh, inside tmux, with a selection sitting on the machine
the human is actually at: `p` answers **There is nothing on the clipboard.**
The obvious diagnosis is the right one about unix and the wrong one about this
program. `PRIMARY` and `CLIPBOARD` really are different stores, and a mouse
drag really does fill only the first -- but neither of them is what fails here,
because both of them are on the *other machine*.

Reading is not writing, and the asymmetry is total. Follow
`Tui.readClipboard` down and it gets two chances:

  - `UnixClipboard::requestClipboardText` spawns `wl-paste`, `xsel` or
    `xclip`, and checks `WAYLAND_DISPLAY` / `DISPLAY` **before** checking the
    executable exists. Over ssh neither is set, so the whole half is skipped
    however many of those are installed -- and rightly, since the display it
    would talk to is the far end's.
  - `TermIO::requestClipboardText` falls through to `requestOsc52Clipboard`,
    which is four lines and the whole story
    (`source/platform/termio.cpp:913`):

        static bool requestOsc52Clipboard(ConsoleCtl &con, InputState &state)
        {
            if (state.hasFullOsc52)
                { con.write("\x1B]52;;?\x07", 8); return true; }
            return false;
        }

    **The query is not written unless the terminal has already proved it will
    answer one.** `hasFullOsc52` is set by exactly three things -- a kitty
    capability reply naming `read-clipboard`, an unsolicited `OSC 52` answer,
    or xterm reporting `allowWindowOps` in an `OSC 60`. tmux sends none of
    them and forwards none of them.

So `requestClipboardText` returns false without asking anybody, the binding
falls back to this process's own last copy (`app.cc:2069`), and that is empty
because nothing has been copied here yet. Every layer did what it should and
the sentence at the end of it was still wrong.

The one line of `~/.tmux.conf` this repo has recommended for months --
`set -g set-clipboard on` -- is about **writing** and does nothing here.
Reading is the direction with a security question attached: a program that can
read your clipboard can read the password you put there a minute ago, and
terminals that cheerfully accept a write refuse a read on purpose. There is no
configuration that makes `p` work over ssh, and looking for one is the trap.

### The half that looks like it works

There is a fallback under all of this and it is deliberate: when nothing
outside answers, the binding hands back **this process's own last copy**
(`app.cc:2069`), so a copy in one window and a paste in another work on a
machine with no clipboard at all. The consequence over ssh is a shape worth
recognising -- `p` does nothing until something has been copied, and pastes
that same thing back for ever afterwards. Nothing is wrong and nothing is
reaching the desktop.

It also cost a check. A `p`-says-so assertion added halfway down `drive_hex.py`
failed, and then took four unrelated checks with it, because by then the driver
had copied a dump: `p` succeeded, replaced the open file with it, and every
check about that file was suddenly about a paste. The assertion has to run
before anything is copied, which is a fact about the fallback and not about the
driver.

### What does get through, and it was there all along

A terminal paste -- `Ctrl-Shift-V`, middle click, tmux's `prefix ]` -- is not
an escape sequence asking a question. It is *keystrokes*, sent down the pty in
the direction that has never had a problem, and Turbo Vision even brackets them
(`\x1B[?2004h` at startup, `kbPaste` on each key). They were arriving the whole
time. What was missing was somewhere for them to land.

Two facts followed from that, and one of them was a bug already:

  - **A canvas is the wrong place for them to land.** Pasting into the Unicode
    window before this ran the pasted text through `pressKey`, so any `p`, `P`,
    `8`, `l`, `b` or `y` in it fired a command. Nobody had reported it because
    nobody could paste.
  - **A field is not one shape.** Both tools got one and they are not the same
    widget, and the rule that decided it is this repo's own: *who moves the
    state.* The Unicode decoder's input is a paste and nothing else, so the
    field is the source and belongs in the window, where it is read live on
    every keystroke. The hex viewer's input is a **file**; a live field there
    would be a second source competing with the model's, and one stray
    keystroke would take away the open file and every highlight on it. So its
    field is a dialog on **Bytes | Type bytes...**, and costs the dump no rows.

### Half a byte is not an error

A field read on every keystroke is read halfway through every byte, so the
paste-time rule -- *an odd number of hex digits is a refusal, with the count* --
becomes an error message flashing on and off under somebody's hands. The
field's version drops a trailing lone digit and says so on the line below:
`one hex digit is waiting for its pair`. A stray *character* is still refused
at once, because `z` is not halfway through anything.

That is one sentence of policy and it needed a second function rather than an
argument on the first, because the two callers are asking different questions.
A paste arrived whole and is either right or wrong. A field is a thing being
typed.

### And the thing that is still silent

`TInputLine` refuses a keystroke past `maxLen` and says nothing at all, which
for a paste means bytes that quietly did not arrive -- the one failure this
program refuses to have about bytes. So the status line says **the field is
full** when it is, and `maxLen` is 512 rather than unbounded for a reason that
is also about pastes: they arrive one keystroke at a time, one `Changed` each,
and the whole field is decoded again on every one of them. That is quadratic.
Five hundred squared is nothing; five thousand squared is a pause.

### Two notes for a driver

Both cost a check that silently does nothing, and both are `TInputLine`
(`tinputli.cpp:380`):

  - A field selects its whole value when it **gains** the caret, not while it
    has it. `Alt-`its-label is a no-op when it is already focused, so a driver
    that wants a fresh selection has to leave and come back.
  - `Del` honours a selection; `Backspace` with no selection deletes one
    character. To empty a field: leave, return, `Del`.

And one about the window: the field is the first selectable view, so it has
the caret when the tool opens -- which is the point of it, and which means the
single-letter commands do not reach the canvas until `Tab` gets there. They are
all on the menu, which is what makes that survivable.

## Two clipboards, and the class that could not be wrapped

The field added the day before made a paste possible over ssh. It did not make
`Shift-Ins` work in one, and finding out why turned up a second clipboard
nobody had noticed.

The trail started at [magiblot/tvision#178][178], which is about something else
and points at the thing that matters. Somebody reported that copy and paste do
not work in an `inputBox`; the maintainer's answer is that they do, but only
once the program binds keys to `cmCut`, `cmCopy` and `cmPaste` itself:

> I agree that it is annoying not to have this working out-of-the-box [...]
> However, an out-of-the-box solution would require hardcoding specific
> keyboard shortcuts for these commands, which I don't think is a good idea
> either.

Which is correct, and which meant `TInputLine` had been answering those three
commands all along (`tinputli.cpp:470`, and `setCmdState` on all three at
`:557`). This binding exposed them under the names `"editor.cut"`,
`"editor.copy"` and `"editor.paste"`, and the docs said outright that they
"reach whichever `Editor` has the caret". **The one name that made a field copy
and paste announced that it was for something else**, so nobody would ever try
it, and nothing anywhere could report that. `audit_api.py` could not: it walks
class *members*, and a command is not a member of anything.

[178]: https://github.com/magiblot/tvision/issues/178

### The two stores

Binding `Shift-Ins` to `"editor.paste"` and pressing it after a `y` pasted
nothing at all, which is the interesting part. There were two fallback
clipboards:

  - `TClipboard::localText`, which `cmCut`/`cmCopy`/`cmPaste` fill and read;
  - `g_clipboardLocal` in `app.cc`, which `Tui.copyToClipboard` and
    `Tui.readClipboard` fill and read.

Two closed loops. Each round-trips perfectly with itself and neither can see the
other, so a copy made by the model and a paste made in a field were different
text.

**It stayed invisible because both are only fallbacks.** With a real system
clipboard -- a local display, or a terminal that answers an `OSC 52` read --
`THardwareInfo` succeeds on both sides, both classes return early, and the two
private copies are never touched at all. The seam exists exactly where there is
nothing to meet in, which is every ssh session: invisible on the machine you
develop on and visible on the machine you use.

### Why the obvious fix is impossible

The instinct is right -- one store, and ours a wrapper over Turbo Vision's
rather than a duplicate of it. It cannot be built:

```cpp
class TClipboard {
public:
    static void setText(TStringView text) noexcept;
    static void requestText() noexcept;
private:
    static char *localText;
    static size_t localTextLength;
};
```

`localText` is a private static with no accessor and no `friend`, and the only
reader is `requestText()`, which is `void` and hands what it finds to
`TEventQueue::setPasteText` -- which does not return a string, it queues a
buffer that `getPasteEvent` drains one character at a time as `evKeyDown` events
with `kbPaste` set. There is no expression that gets text out of that class.
That is precisely why `app.cc` reimplemented it in the first place, and the
comment there has said so all along.

There is also a bug in it worth not inheriting. `setText` stores locally *only
when the platform refuses*, so on a machine where copying works `localText`
keeps a stale copy -- and a later paste that falls back to it pastes something
from two copies ago rather than nothing. Ours stores first, unconditionally.

### So it was inverted

Ours became the single store, and the rule became **no view may reach
`TClipboard` either**. `JsInputLine` and `JsEditor` answer `cmCut`, `cmCopy` and
`cmPaste` themselves and never delegate them, which finally makes true a
sentence `doc/clipboard.md` had been asserting for months.

The delete inside `cmCut` was the only awkward part: `TInputLine::deleteSelect`,
`saveState` and `checkValid` are all private. It is asked for in the vocabulary
the class does expose -- a synthetic `kbDel`, which with a selection out runs
exactly those three in that order (`tinputli.cpp:399`) and, as a bonus, also
pulls `firstPos` back afterwards, which the real `cmCut` branch forgets to do.

### The queue that was worse than the problem

`THardwareInfo::requestClipboardText` keeps **one** callback slot, and an
`OSC 52` reply carries nothing saying which question it answers. With two
things able to ask, the first attempt was a FIFO of askers: replies arrive in
order, so match them in order.

It broke `drive_hex.py` immediately, and the failure is the argument against
it. A driver pressed `Shift-Ins`, which wrote a query the driver never answered
-- leaving an entry in the queue for ever, so every reply *afterwards* went to
the wrong asker, and a check three hundred lines later failed for a reason
nothing near it could explain.

The answer is two accept functions and no bookkeeping at all. TVision's own
single slot then does the routing, and the degenerate case degrades to "the last
thing that asked is what the answer goes to" -- which is the only correlation
this protocol can support, and the semantics TVision already had.

### And two names split into two

`"clipboard.cut"`, `"clipboard.copy"` and `"clipboard.paste"` act on whichever
of the two views holds the caret. `"editor.clear"`, `"editor.undo"` and
`"editor.selectAll"` stay as they were, because `TInputLine` has no branch for
any of the three. Nothing is published, so this was a rename rather than an
alias.

`audit_api.py` grew a `commands` pseudo-class, the same carve-out the flag bits
have and for the same reason -- a member-level walk cannot see a command, and
85 of Turbo Vision's now have a line in `decisions.tsv` saying what was decided
about each.

### The thing that hid it for a decade

`TEditor` has its own keymap: `Ctrl-Ins`, `Shift-Ins` and `Shift-Del` become the
three commands inside `convertEvent` (`teditor1.cpp:84`). `TInputLine` has no
such thing. So in any program that never binds those keys -- which is every
program, because Turbo Vision deliberately binds none -- **the editor works and
every input line in the same program silently does not**, and it looks like a
fact about editors rather than a missing three lines of status line.

`examples/edit` and `predc` both name them now, as invisible status entries. In
`edit` that means the Find dialog's field takes a paste, which is a real thing
to want there: what you search for is usually something you are looking at.

## The window that measures instead of explaining

Two commits of clipboard work left `doc/clipboard.md` correct and predc's users
no better off, because a user in front of a terminal that will not paste does
not read a repository. So **Help | Copying and pasting** (`F1`), which is the
same subject in the program.

The design decision worth writing down is that **it is a measurement rather
than a page**. Most of the answer is in the environment -- `DISPLAY`,
`WAYLAND_DISPLAY`, `SSH_CONNECTION`, `TMUX`, `STY`, `TERM` -- and `Help.detect`
reads all six at start-up, because `Node.getEnvironmentVariables` is an
`Init.Task` and nothing later can ask for one.

But the fact that actually settles it is in none of them. Whether a *terminal*
will hand its clipboard back is decided by `hasFullOsc52`, which is set by a
reply to a capability query and is invisible from Gren. What is visible is
`ClipboardText.fromSystem`: false means nothing outside answered. So opening
the window fires a `readClipboard` and keeps the boolean, throwing the text
away. One line of the window is then a fact about this terminal rather than a
row of a table:

    Measured: nothing outside this program answered a clipboard
    read, so p and P cannot reach your clipboard here.

**It asks again on every opening rather than caching**, which is the cheaper
mistake in both directions. `set-clipboard` is a live tmux setting and so is
kitty's `clipboard_control`, so somebody who opens this window *because* they
just changed one is exactly the person a cached answer would mislead.

### What to press first, why second

Written the opposite way round from every explanation of this subject,
including the one in `doc/clipboard.md`. Somebody whose paste did nothing wants
three lines. The background is real and is underneath, where it belongs: the
two different mechanisms both called pasting, what the tmux line does and does
not fix, a row per environment, and the six stores.

### Three things the shape of it forced

**Text and theme are separated.** `update` has to count lines to scroll them
and `update` has no `Inks`, so the body is an `Array Line` of
`Head`/`Text`/`Warn`/`Gap` and `paint` applies the theme at render time. One
array both halves agree about is what stops the scroll bar and the text
drifting apart -- and the alternative, a second `lineCount` function, is a
thing that drifts by construction.

**A window that is not a tool.** It lives at `src/Help.gren` rather than in
`src/Tool/`, because `Tool/` means "on the Tools menu, a thing the program
does" and this is neither. It is otherwise exactly a tool's shape -- `command`,
`windowId`, `init`, `update`, `view` -- which is what let the shell take it
with four lines.

**Re-opening does something.** Every other window in predc answers a second
`Alt-`key by coming to the front. This one measures again, so the command
branch is a `Help.opened` plus a `Tui.focus` rather than one or the other.

### As tall as the desktop, and the `Resized` nobody was getting

Reported from the application: a tall tmux pane and a seventeen-row window in
the middle of it. The window's rectangle was a constant, which every other
window here can afford -- a chart is sixteen rows of eight columns and there is
no more of it -- and prose cannot: the text is a hundred-odd lines, so the
screen is what decides how much is visible.

So the rectangle is computed from `model.desktop` on every render. The differ
does the rest for free, and both halves of that matter: it writes `setBounds`
when the desktop changes, and writes nothing when it has not, which is what
leaves a window the user dragged where they put it.

**Which turned up a bug in the shell.** `Help` needs `Resized`, so it grew a
branch for it -- and the branch never fired, because `handleEvent`'s `Resized`
case updated the shell's own `desktop` and returned without calling `toTools`.
`Tool.Hex` had had a `Tui.Resized` branch for months under the same roof, and
it had never run either: the viewer's `desktop` sat at the `80x23` it was
seeded with for the life of the process. On a 120-column terminal **Go to
offset** and **Type bytes** opened nine columns from the left edge, centred for
a desktop that was not there.

Nothing reported it, and nothing could: a dialog in the wrong place is still a
dialog, and `80x23` is a plausible enough size that it looks deliberate.

**Forwarding the event is only half the fix.** `Resized` fires when the size
*changes*, so a tool opened after somebody stretched their terminal never hears
it at all -- it has to be handed the current desktop when it opens, the way it
is handed the file system permission. Both halves, or the bug survives in
whichever case is not tested.

### The floor that hung off the bottom

`textRows` is capped at `desktop.rows - 4`, because the window is `textRows + 3`
tall and sits one row down. It also had a *floor* of three, which looked like
politeness and was arithmetic: on an eight-row terminal the desktop is six rows
and the floor asked for a window that ended one row past the bottom of it,
drawing a frame with no lower border. The floor is one now, which is the only
value that cannot fight the ceiling -- and Turbo Vision refuses to draw a window
under six rows anyway, so below a five-row desktop there is nothing to get
right.

### The menu entry that broke four checks in two other suites

Adding one entry to the Help menu moved **About** down two rows, and three
checks in `drive_shell.py` and one in `drive_ascii.py` failed -- all of them
about the About box centring itself, none of them about the Help menu. Both
drivers were clicking the *n*-th line of the pull-down.

`drive_hex.py` already had the rule written down, from the last time this
happened to it: reach a menu entry by the letter it underlines, never by
counting lines. It is in `bytes_menu` there and now in `menu` here, with the
same note. A convention that lives in one driver is a convention the next one
does not have.

### And a table whose columns were wrong

The first version was written by hand and the columns did not line up, because
`works` is five characters and `needs tmux line` is fifteen. It is generated
with `ljust` now and pasted in. A table nobody can read is worse than a
paragraph, and in a terminal there is no layout engine to hide behind.

## A config file with comments in it is a config file you cannot serialise

predc's settings were JSON. They are TOML now, and the reason given for the
change was one word -- comments -- but the interesting part is what having
comments does to the *write*, which was not the part anyone was thinking about.

`gilramir/gren-toml` is a TOML parser that keeps the whitespace and the
comments in its AST as text rather than throwing them away, so a document that
was parsed and then edited comes back byte for byte apart from the edit. The
package is not published yet; predc depends on it as `local:../../gren-toml`,
and this is its first use by a program rather than by its own test suite.

### The finding: the format changed what `save` is allowed to be

The old `Config.save` was the obvious shape and every program has one -- take
the model, encode it, write it out. That is *correct* for JSON, because nothing
in a JSON file is worth preserving that is not in the model. It is destructive
for TOML, and the reason is not the format, it is the user: a file with
comments in it is a file somebody opens in an editor, and predc rewrites that
file every time somebody picks a colour. Serialising the model over it deletes
everything the user wrote, silently, on an action that looks unrelated.

So `save` **reads the file back off the disk** and edits the document it
parsed:

    FileSystem.readFile
        |> Task.map (Toml.parseBytes >> Result.toMaybe)
        |> Task.onError (\_ -> Task.succeed (Just (Encode.toDocument [])))
        |> Task.andThen (write << apply config)

Reading at the moment of writing rather than keeping the document parsed during
`init` is not caution about staleness in the abstract. predc is a TUI somebody
leaves open, and `$EDITOR` on the config file is a thing that happens while it
is open. A document held since start-up is a snapshot of the file before that
edit, and writing it back is the same data loss by a slower route.

`Toml.Encode.toDocument []` is the empty document, which is how "create the
file" and "change two values in the file" became one code path instead of two.
There is no separate serialiser to keep in step with the editor.

### Four outcomes, and only two of them write

The `Maybe` in that pipeline is doing real work, because `readFile` failing and
`parseBytes` failing want opposite answers:

  - **No file** -- create one.
  - **A file that parses** -- edit it.
  - **A file that does not parse** -- *leave it completely alone*.
  - **No path at all** -- nothing to write to.

The third is the one worth arguing about. A syntax error in a config file is
almost always a half-finished hand edit, and the rest of that page is worth
more than the setting predc wanted to record. `load` has already fallen back to
the defaults, so predc runs; the user fixes the typo and picks the theme again.
Overwriting would have been the tidier-looking behaviour and would have thrown
away the file it was tidying.

### The key nobody touched is the one that gets destroyed

Writing both keys on every save is what any encoder does and is wrong here, for
a reason that took a hand-written file to see. `Toml.Edit.set` replaces a
*value*, and the whitespace inside it is part of the value:

    timezones = [
      "Asia/Seoul",     # them
      "America/Chicago" # me
    ]

came back as `timezones = ["Asia/Seoul", "America/Chicago"]`. That is correct
for a list that changed -- there is no old formatting to keep for a new value --
and it is destructive for one that did not, which is the case that actually
happens: the user arranged that list once, and then picked a colour. The key
they never touched is the key that got flattened, by an action about something
else.

The rule generalises past this program. **An editing API turns "write the model
out" into a destructive operation, and the fix is to make each write conditional
on the value having moved.** A serialiser never had to know which fields
changed. An editor does.

predc did that itself first, by decoding the document it was about to edit and
comparing, and that version is worth remembering for the trap inside it: "what
does the file say" and "is the key there" are not the same question, because
every field in that decoder is optional and so an *empty* file already *says*
the defaults. Comparing meanings alone found both keys correct on a first run
and wrote an empty file.

None of it is here any more, because the comparison went into the library
instead -- `Toml.Edit.set` now leaves a value alone when the document already
means it. That is the right home for it: the caller has to hold the old
document, decode it, and know that `0x1F` and `31` are the same integer and
`1.50` and `1.5` the same number, and the library knows all three without being
asked. `apply` is two calls again, and the property is stronger than the one
predc had, since it holds for every value rather than for the two fields
somebody remembered to compare.


### Comments predc writes, and comments predc must not touch

A key predc invents arrives with a sentence saying what it is for, since a
config file whose fields are undocumented is one nobody opens. But it is
written **only when the key is new** -- `Toml.Edit.get` says whether it is
there -- because a user who deleted the sentence, or rewrote it in Korean, has
not made a mistake for the next theme change to correct.

That rule is only coherent because `Toml.Edit.remove` takes a key's leading
comments with it. `timezones` comes and goes as the user configures zones and
clears them; the explanation leaves with the key and returns with it, rather
than being lost the first time the list is emptied.

This too started as a private helper here and ended up in the library, as
`Toml.Edit.introduce` -- `set` and `setComments` in one call, with the comments
written only for a key that was not already in the document. It is the
config-file idiom for a library that keeps comments, and a program made to
assemble it out of `get` will sooner or later assemble it wrong and start
correcting somebody's Korean.

### `Theme.encode` was the wrong type all along

`Theme` exported `encode : Name -> Json.Encode.Value` and a matching
`Decode.Decoder Name`. Porting them to TOML would have been two lines. They are
`toKey : Name -> String` and `fromKey : String -> Name` instead, and `Theme`
does not import any codec at all now.

Which format the config file is in has never been a fact about a colour scheme.
The old signature made `Theme` depend on the answer, so a decision taken in
`Config.gren` reached two modules; the string is the one thing only `Theme`
knows, and handing that over is the whole of its business here. The file has
now been JSON and TOML and `Theme` has an opinion about neither.

### What the driver checks, which is not what it used to

`drive_theme.py` compared `json.load(f)` against a dict. The dict comparison is
still there, in `tomllib`, and it is now the *weaker* half: the thing worth
asserting about a format with comments is what survives, not what parses.

So the driver writes a file by hand -- a comment above the key, a comment on
the line, blank lines, a `timezones` list spread over four lines with a comment
against each zone, and `language = "ko"`, which no version of predc has ever
heard of -- then makes predc write that file twice, and compares the result to
the original string character for character. Two more checks say predc leaves a
file with a syntax error exactly as it found it.

### What the port put back into the library

Five things, and the shape of the list is the finding. One was a bug in the
API -- `set` reformatting a value that had not changed -- and it is the one that
would have cost somebody their file. The other four were papercuts, and every
one of them was predc writing something the library was the right place for:

  - **`Toml.empty`**, so that creating the config file and updating it are one
    code path. `Toml.Encode.toDocument []` already was that document, and
    nobody was going to find it there.
  - **`Toml.Edit.introduce`**, which was `put` in this file.
  - **`blankBefore`** on the comments record, because a document is a list of
    expressions and there was no way to ask for a blank line at all. Without it
    the explanation above `timezones` sat flush against `theme`'s value.
  - **`Toml.Edit.Value` exposed, and `Toml.Edit.member`.** `set` took a type the
    module did not export, so `put`'s annotation had to import `Toml.Ast` for a
    name it had no other use for -- and it called `get` for a `Maybe` whose
    contents it threw away.

`Toml.Encode.commented` came out of the same pass without predc needing it: the
module that builds a file from nothing could not write the one thing the package
exists to keep.

The general version, since this is the second time this repo has arrived at it:
**the first program to use a library is where its API gets decided, and a
private helper in that program is usually the library's missing function.**
`tools/audit_api.py` exists for the same reason on the Turbo Vision side, and
says so at more length.

## The wheel, and the echo that dragged the list back to where it had been

Reported from a real terminal rather than found by a driver, which is the part
worth noticing: pick an area in the zone picker, turn the mouse wheel over the
Zone column, click a zone -- and the list jumps and the wrong zone is added.
Every pty check in the suite passed throughout.

### Two parties move one highlight

A `ListBox`'s highlight is moved by the user, with an arrow key or a click or
the wheel, and by the model, by rendering a different `focused`. Both are
wanted: the first is how the model learns which row a Delete button should act
on, and the second is how a re-sorted list keeps the record the user was
looking at.

The binding reported *both*. `JsListBox::focusItem` is the override that calls
`noteFocused`, and every path goes through it -- including `tv.setValue`, which
is the model writing the highlight. So:

    model writes focused = 3
      -> C++ moves the highlight to 3
      -> Focused { index = 3 } is sent to the model
      -> the model stores 3
      -> the next render writes focused = 3

A loop, and one that terminates only because the values happen to agree. They
agree for an arrow key, because a person cannot press one faster than the
model renders. **They do not agree for a wheel**, which arrives as a burst: ten
turns is ten events in a few milliseconds, and the model is several renders
behind the whole way through. Each render writes an index the list left behind
long ago; `focusItemNum` scrolls the list to make that index visible; and the
list ends up wherever the last echo of a stale value put it. Click on a row and
the click is right about where the pointer is -- it is the list that is in the
wrong place, and it got there between the eye and the finger.

`setItems` already knew about this. It has a `quiet` flag with a comment saying
that its trip through row zero "is not news", and that announcing it "tells the
model its highlight moved somewhere it was never going to stay". The same
sentence is true of every model-driven move and only one of them had the flag.

### The rule this is an instance of

CLAUDE.md has it already, in the paragraph about who moves a piece of state:
**the user's moves are an event, the model's are a field.** What was missing is
the corollary, which is that the two directions have to stay separate at the
seam. A field the model writes must not come back as the event that means the
user did something, because the model cannot tell them apart -- and a model
that stores what it hears will write back what it stored.

`Focused` is now the user's move only. `JsListBox::setFocused` sets `quiet`
around `focusItemNum`, and the builder and `tv.setValue` both go through it.

### The exception, which is the interesting half

Staying silent about every model-driven move loses something real: the list
*clamps*. Ask for row ten of a list that now has three and the highlight lands
on row two, and a model that hears nothing goes on believing it has row ten --
which is the tree that collapses itself when a branch is expanded, the failure
`gren-tvision-runtime/diff.js` already has a comment about.

So the rule is not "the model's writes are silent". It is **"the model is told
when the list could not do what it asked"**, which is a different sentence and
a better one: it reports a disagreement rather than an action. It cannot loop,
because the model stores the row it was given, asks for that row next time, and
gets it -- one echo, then agreement.

### What the driver has to do that the old checks did not

`app.wheel` settles between turns, and the bug needs a queue. Three checks in
`drive_time.py` write every turn in one `os.write`, which is what a hand does,
and then ask the question the eye asks: **is the zone that got added the one
that was under the pointer?** Reading the row off the screen first and
comparing afterwards is what makes it a test of the seam rather than of an
index.

A wheel check already existed, and passed, and was about routing -- that a turn
over one list scrolls that list and not the one beside it. It turned one notch
at a time, so it never built a queue. A test that is slower than a person is a
test of something a person will not do.


## The character that decoded and would not draw

Reported from a real terminal, like the wheel above, and by somebody using the
Unicode decoder for the thing it is for: paste `メモ`, and predc says `U+30E1`
and `U+30E2` -- correct, and the whole point of the tool -- while the `char`
column beside them is **blank**. Every pty check in the suite passed
throughout, including one written expressly to check that a wide character is
on the screen.

The first question was whether the font could draw Katakana, and the answer was
that the same terminal was drawing `メモ` in the message that reported it. So
the font was not it.

### It is TVision, and no part of this repo is involved

Cheapest way to find out: a thirty-line `TApplication` with one `TView` that
does `moveStr` of `"[A" "メモ한" "B]"`, linked against `libtvision.a`, run under
`tmux capture-pane`. No Gren, no node, no binding.

    [A      B]

Six columns reserved for three characters, and nothing in them.

### validateCell eats the flag the flush algorithm needs

A double-width character is one glyph in two cells. `TText::drawOneImpl` writes
it into the first, marks the second with `TScreenCharacter::fTrail`
(`ttext.cpp:350`), and returns a width of two -- which is why the columns are
reserved and why every other column on the row lines up. Nothing there is
wrong.

Then `DisplayBuffer::validateCell` runs on every cell on its way to the screen:

    TStringView text = cell.character.getText();
    uchar c = text[0];
    if (c == '\0')
        cell.character.initWithChar(' ');

A trail cell's text is one `'\0'`, so it takes the first branch --
and `initWithChar` begins `*this = {}`, which zeroes `_flags` and takes the
trail marking with it. `getText()`'s own comment says *"Pre: This is not a wide
char trail"*, and the flush algorithm has a comment saying the value "is
otherwise discarded in `ensurePrintable()`", which is what `validateCell` used
to be called. So the discarding is known about. What is not is what happens
next.

`FlushScreenAlgorithm::handleWideCharSpill` writes the wide character, then
walks the cells it spills into to make sure they are trails. They are not any
more -- they are spaces. On unix `wideOverlapping` is `true`, so the branch it
takes is the one whose comment reads *"Write over the wide character"*:

    ...U+30E1   ␛[36G    basic multilingual plane

`メ` goes in at column 35, and then the caret is moved **back** to 36 -- the
right half of it -- and a space is written there. A terminal answers a write
into the second cell of a double-width character by blanking *both* halves, so
the character is gone. The columns stay reserved, which is why nothing else on
the row moves and why this looks like a font problem.

Reported as [magiblot/tvision#233][233], with a bisect: `d726902^` draws the
characters and `d726902` -- "Rework screen cell and color attributes API",
2026-07-06 -- does not, both built and run rather than reasoned about. The old
`validateCell` assigned `ch[0] = ' '` in place, which left `_flags` alone; the
rework replaced that with `initWithChar`, whose first statement is `*this = {}`.
The stale comment about the value being "discarded in `ensurePrintable()`" is
from the era when what got discarded was the trail cell's *text* and not its
flag.

[233]: https://github.com/magiblot/tvision/issues/233

The fix is a commit on the `patches` branch of gilramir/tvision, the fork
`tvision/` is a submodule of, and on `fix/wide-char-trail` beside it for the
pull request. It began as a `.patch` file in `tvision-node/patches/`, applied
by `build-tvision.sh` -- which lasted a day, until a second unlanded fix made
the shape of the problem obvious: `git apply -R --check` printed
`already applied` whether the fix was in the checkout or not, so the mechanism
that was supposed to guarantee the patch was there could not tell you when it
wasn't. A branch can only be one thing. See README for the fork's layout.

### The harness was the reason nobody knew

`drive_unicode.py` has had this check since the day it was written:

    check("and the character itself is on the screen",
          "한" in rows(app)[3] and "😀" in rows(app)[6], ...)

It passed. It passed against the broken library, every run, from the day it
was written.

`Screen._put` in `harness.py` wrote a wide character into its cell and a filler
space into the cell beside it -- which is right, and is what keeps a row's
string index and its column the same number, the thing every driver counts on.
But a filler space and a *written* space were then the same thing, so the space
TVision writes over the right half landed on the filler and the left half sat
there being found by `in`. The model had no way to represent the one state that
mattered.

It does now. A row keeps the set of columns holding the **left** half of a wide
character, and `_break_at` erases the pair when anything is written into either
of them, which is what a terminal does -- tmux is the one that was measured
here, through `capture-pane`. Erases (`CSI K`, `CSI J`) go through the same
helper.

With the library patch reverted, the check above fails, and its failure message
is the blank `char` column the bug report described. That is the point of
fixing a harness rather than only a library: **the check was already written,
and the emulator was answering a question a real terminal would have answered
the other way.**

The general rule, which is worth more than this instance: a screen model that
cannot represent a state cannot fail a check about it, and it will not say so
-- it will pass. The wide-character trail was the second cell of a pair the
model stored as two independent cells, and two independent cells is exactly one
bit short of what a terminal knows.

### A button costs a row, and says nothing when it does not get one

The same window gained a `Clear` button, because emptying its field by hand is
the two-trap dance CLAUDE.md warns about -- leave, come back for a fresh
selection, then `Del` -- and somebody switching a field of text over to hex
should not have to know either trap.

The first attempt put it on the entry row, one row tall, and it drew nothing at
all. `TButton::drawState` draws the face on rows `0 .. size.y - 2` and the
shadow on `size.y - 1` (`tbutton.cpp:124`), so a one-row button is a loop that
runs zero times followed by a shadow. No error, no warning, no button --
which is the same silence as the four places a view type has to be added in,
and the same cure: know the rule. **A `Button` needs two rows**, and the
window is a row taller than the rows it shows because of it.

The hotkey is `C~l~ear` and the menu entry is `~C~lear the field`, which look
inconsistent and are each the only letter free where they are: a menu entry's
hotkey is local to the open pull-down, where `L` is already `Read as UTF-16
~L~E` and `C` is free, while a button's is an Alt- accelerator competing with
the status line, where `Alt-C` is Time and `Alt-L` is free.

`takesFocus = False`, so it is pressable by mouse and by `Alt-L` and is not in
the tab order. That is not a preference: the field is first so that it holds
the caret when the window opens, and one `Tab` from there has to reach the
radio and two the rows, which is the route every letter command in
`drive_unicode.py` depends on. There is a check that says so now.

### And a line that says how to paste, because the window is where the question is

The other half of the same report. predc already has a whole window that
answers "why can I not paste into this?", measured rather than guessed, and
`p` in the decoder already says *the terminal will not hand the clipboard
over; type into the field instead* when it cannot. What it never said is what
to press instead, and the place to say that is the window somebody is already
looking at.

So there is a permanent line under the rows: `Paste  Ctrl-Shift-V, Shift-Ins,
tmux prefix ] into the field.  F1 for why.` It is session-aware -- `prefix ]`
only inside tmux, `p reads the clipboard` only where there is a display -- and
the sentence lives in `Help.pasteHint` rather than in the decoder, because
there is exactly one correct answer to that question and a second copy of it is
a second copy that will go stale.

It cost no rows. The window's height arithmetic was already leaving one
interior row empty -- `rowsIn` said `height - 6` while the layout used five
rows of chrome -- so the line went where the blank row was, and adding the
button's shadow row made `rowsIn` right for the first time.

Two things about testing it. The sentence depends on the environment, so
`drive_unicode.py` now dresses one: it clears `SSH_*` and `STY` and sets
`TMUX`, the way `drive_help.py` already did, and pins the tmux variant because
it is the longest of the four and spends all seventy-six columns. And the
check that it *fits* is not a length assertion on the string -- it is that
column 78 of that row is still `║`, which is the frame, and which is the
question a reader actually has.

## Two drivers were the whole wall clock, one after the other

`devbox run test` took 229.6s. `drive_hex.py` took 208.7s of it. The other
thirty-one suites finished inside the first 56s, and the last two and a half
minutes were one Python process and fifteen idle cores.

Nothing was wrong with the parallelism -- `run_tests.py` already runs
`os.cpu_count()` suites at once, and they genuinely do not step on each other:
separate processes, separate ptys, separate `mkdtemp` scratch directories. That
is exactly why more of it bought nothing. **A parallel suite's wall clock is
its slowest single member**, and a driver that outgrows the rest stops being a
member and becomes the number.

### Measure the phases; do not reason about the file

`drive_hex.py` was a thousand lines in seventeen numbered phases. Timing a
throwaway instrumented copy of it, rather than counting lines or settles:

```
 1-11  open, dialog, dump layout, movement, paging, go-to, mouse, bar    39.1s
   12  window resize                                                     18.9s
   13  highlighting                                                      45.2s
   14  yanking, including the megabyte                                   30.8s
   15  pasting                                                           61.3s
16-17  small and empty files, close and reopen                           13.4s
```

Three phases were two thirds of it, and they fell on a seam that was already
conceptual -- reading a file, marking it, and the clipboard. Four drivers now
(`drive_hex.py`, `_marks`, `_yank`, `_paste`) over a shared `hex_common.py`:
**208.7s to 71.9s**. The predictions were 71/53/39/69 and the measurements
71.9/56.5/38.5/69.0, which is the useful part -- the phase timings were the
whole design.

The suite went 229.6s to 149.6s rather than to the ~79s that arithmetic
suggests, because the lesson repeated one driver later: `drive_time.py` was
125.2s and became the wall clock the moment hex stopped being it. It had always
been the second pole and was invisible behind the first -- a per-suite table
read off a still-running log had not seen it report yet, which is its own small
warning about measuring a parallel run before it has finished.

### The second one wanted a different split, and the timings said so

`drive_time.py`'s sections came out **flat** where hex's had been lopsided:

```
setup + the conversions                     35.9s
the picker                                  15.9s
the wheel turns the list it is pointing at   5.9s
the buttons act on the highlight            16.8s
the wheel, and the echo                     10.5s
Move Up and Move Down                       14.9s
Cancel puts back the list                    7.6s
the live clock                              17.7s
```

No phase to lift out. What there was instead was a *seam*: the converter
window (conversions and the live clock, which is the same window in the mode
that throws the pinned instant away) against the picker, which is 71.6s spread
over six sections. Three drivers -- `drive_time.py`, `_picker`, `_moves` --
over a `time_common.py`: **125.2s to 55.1s** (50.4 / 44.3 / 55.1).

Three and not four, and the reason is the floor rather than the file:
`drive_unicode.py` is 55.5s, so nothing cut below that changes the suite at
all. **Know what the next pole is before deciding how many pieces to make.**

The suite is **93.9s** now, from 229.6s. Not the ~57s the slowest driver
suggests, and this is where the arithmetic changes character: there are 37
suites on 16 cores, so the run has stopped being "the slowest member" and gone
back to being partly the sum. 972.8s over 16 cores is a 60.8s floor, and 93.9s
against a 71.9s slowest driver is most of the distance to it. Splitting
further would move the first number and not the second.

The next win is therefore a driver that *costs* less rather than one cut into
more pieces, and there is an obvious candidate: `Pty.pump()` loops to its
deadline whether or not the app went quiet after 40ms, so every settle is paid
in full. Making it a ceiling with a quiescence window is the change -- with the
caveat that a quiescence window is a race by construction, since TVision can go
quiet mid-repaint, which is why the ceiling has to stay.

The picker's six sections are far more coupled than hex's phases were -- it is
one workspace with running state, and each section restores the list for the
next. That is what `time_common.picker_with_three` is: the seam between
`_picker` and `_moves` written down as a function, built from nothing rather
than inherited. The one real trap was at the end. The last checks relaunch
predc on the config the first run wrote and assert *an emptied list stays
empty across a restart* -- and the list is emptied by **Cancel**, three
sections earlier. That tail had to travel with `_moves`, not stay with the
converter, or it would have asserted about a list that was never emptied.

### A driver's cost is not linear in its length

`Pty.display()` replays the entire stream into a fresh emulator whenever the
buffer changes -- deliberately, because a stateful emulator that could drift is
not worth debugging. So a session pays for its own history on every check, and
a long driver is quadratic in itself. Four short sessions each replay a quarter
as much, a quarter as often.

That is visible in the phase table above: pasting cost more than highlighting
despite being shorter, because it ran later, against a bigger buffer. It is
also why `forget_copies` exists, and why the split beats what dividing 208 by
four would predict for the two long tails.

### Two orderings that were comments are now structure

Both were real constraints held only by a note in the file, and both are held
by the process boundary now, which is the better half of the change:

  - **`p` with nothing ever copied.** predc falls back to its own last copy, so
    the check that it names the *terminal* rather than the clipboard -- the
    true sentence over ssh -- only works before anything has copied. It lives
    in `drive_hex.py`, which is now the driver that never copies anything.
  - **`ESC]60;allowWindowOps`**, which is what TVision reads as "this terminal
    really does answer an OSC 52". Nothing pastes before it. `hex_common`'s
    `allow_osc52` sends it; `_paste` calls it in setup, `drive_hex.py` calls it
    after the `p` check and before the paste at the end, and `_yank` does not
    call it at all -- because opening with the sentence predc prints *without*
    the claim is what that phase is for.

### The safeguard

A split like this fails by silently dropping checks, which is the same shape of
problem `check_consistency.py` exists for. The count is the guard: 148 checks
in the old file, 49 + 39 + 16 + 32 + 12 by phase, and 61 + 39 + 16 + 32 = 148
across the four afterwards -- and 951 for the suite, unchanged, before and
after.

## A status line that will not fit does not truncate, it disappears

predc's bottom row carried Exit, four of its five tools, and Close. Each new
tool pushed something off it: `F5` and `F6` went for the fourth, and the fifth
— the Unicode decoder — never went on at all, so `Alt-U` had been menu-only
since the day it was written. **A list that has to shrink when the thing it
lists grows is not a list of that thing**, and the bar had been quietly wrong
about what predc has for two tools running.

So the tools came off entirely. Nothing is lost: every one carries its `Alt`
key on the Tools menu, and `TMenuBar` is `ofPreProcess` exactly as
`TStatusLine` is, so the shortcut still arrives from inside a window whose
canvas eats every key — the same measurement that let `F5` and `F6` go.

### The failure mode is silence, and it decided the design

`TStatusLine::drawSelect` (`tstatusl.cpp:270`) draws an item only

```cpp
ushort l = cstrlen( T->text );
if( i + l < size.x )
    { ...draw... }
i += l+2;
```

and there is **no `else`**. An entry one column too long is not truncated and
not marked — it is dropped whole, the bar closes over the gap, and nothing
anywhere says a sentence was discarded. Combined with a terminal that can be
resized under the program, a hint written for eighty columns is a hint that
vanishes at sixty: precisely the narrow terminal where somebody most needs it.

That is why the paste hint is a **ladder measured at render time** rather than
a string. `Help.barVariants` is a list per situation, longest first;
`Help.pasteBar` takes the columns left after the fixed entries and returns the
first rung that fits. Selection is by `Help.barWidth`, which is `cstrlen`'s
rule — length ignoring the `~` that mark highlighted stretches — so a sentence
that is one character longer than its author counted gets demoted instead of
disappearing. Nothing depends on anyone's arithmetic being right.

The budget is derived, not written down: `Array.foldl (\i n -> n + barWidth
i.text + 2) 0 fixed`, then `cols - spent - 1` for the `<` rather than `<=`.
Change the wording of Exit and the hint re-fits itself.

### Two situations, and the app is told about both

Which routes exist is the environment's answer and `Help.detect` already knew
it; how much room there is to say it in is the terminal's, and it moves while
the program runs. The bar reads both — `model.session` and `model.desktop.cols`
— which is the whole of "detect what situation you are in":

```
inside tmux    Paste  Ctrl-Shift-V, Shift-Ins, tmux prefix ]   F1
inside screen  Paste  Ctrl-Shift-V, Shift-Ins, screen Ctrl-a ]   F1
with a display Paste  Ctrl-Shift-V, Shift-Ins, or p   F1 why
over bare ssh  Paste  Ctrl-Shift-V or Shift-Ins, not p   F1 why
```

at eighty columns, growing to the `into a field` versions at a hundred and
falling through `Paste  Shift-Ins   F1` at sixty to `F1 paste` at forty.

**The bottom rung is `""` and that is a feature.** An entry with no text costs
no columns and is still offered every keystroke — the trick that already put
cut, copy and paste on this bar for free — so on a terminal too narrow for any
sentence, `F1` still opens the explanation with nothing drawn.

`F1` survives down to 35 columns, which was a retune rather than a first
draft: the first ladder dropped it at eighty for tmux and screen, and `F1` is
the escape hatch to the page-long answer, so it is the last thing that should
go.

### Checking it needs a resize, not a screenshot

`drive_statusbar.py` dresses four environments and reads the bar at 40, 60,
80, 100 and 132 columns. The assertion that matters is not that the right
words appear but that **the row still fits** at each width, because the way
this breaks leaves nothing on the screen to notice.

### A colour scheme is not a tool

predc's themes were on **Tools | Colors**, which put a setting inside the menu
that lists what the program *has*. That reads fine with one setting and stops
reading fine the moment there is a second, because the menu then answers two
different questions and the answer to neither is complete.

Turbo Vision settled it rather than taste: `tvdemo3.cpp:218` has an
`~O~ptions` menu and `~C~olors...` is in it, beside Mouse, Background and the
desktop save/retrieve. It is the Borland IDE's answer too, where Options always
sits just before Window and Help. So predc's bar is now

    File   Tools   [the open tool's own menu]   Options   Window   Help

with Colors a submenu of Options. `Alt-O` was free; the `~O~` in Calc's
**Octal** and Hex's **Open file...** are item hotkeys inside a pull-down and
never reach the bar.

One entry in a new menu looks thin, and is still right. Colors is the only
preference predc has *today*, but the config file already stores a second thing
the user chose -- the converter's zone list -- and under Tools the next one had
nowhere to go that would not make that menu wrong again. Same argument as the
status line: a list that has to be edited when the program grows is not a list
of the thing it claims to list.

`drive_theme.py` gained a check that Colors is **not** on Tools, which is not
implied by the ones that follow it. A move that left the entry in both menus
would pass every "is it reachable" check in that file, and two routes to one
setting is the shape of the bug where only one of them writes the config.

## A menu item with no command is a type confusion, not an item that does nothing

The calculator grew a **Copy** submenu listing the stack, and with an empty
stack it listed one placeholder: `Item { title = "(the stack is empty)",
cmd = "", ... }`. predc then died with SIGSEGV on the *first keystroke after
opening the calculator* — which looked like a crash in typing a digit, and was
not.

`""` interns to command 0, and the binding's own comment said that was the safe
value: "an item with no command gets 0 (cmValid), which nothing dispatches on."
Nothing dispatches on it. But **Turbo Vision reads `command == 0` as "this item
is a submenu"**, and `TMenuItem` keeps the two possibilities in a union:

```cpp
union { const char *param; TMenu *subMenu; };
```

So the same zero that means "no command" to the binding means "read `param` as
a `TMenu *`" to at least three places in TVision: `TMenuView::updateMenu`
recurses into `p->subMenu` (`tmnuview.cpp:485`), `~TMenuItem` frees it with
`delete subMenu` (`tmnuview.cpp:81`), and `TMenuBox` widens the item by three
columns and draws a submenu arrow beside it (`tmenubox.cpp:36`, `:110`). The
item is built, drawn and left alone until something walks the tree; the first
keystroke is what does.

The fix is in the binding, because no Gren program should be able to reach
this: `makeMenuItem` gives a command-less item `kCmdNothing` and disables it,
which is what "no command" meant anyway — nothing to dispatch and nothing to
choose. Verified both ways on the same Gren source: the crash returns when the
mapping is taken out and goes when it is put back.

**What I could not do is reduce it.** A fixture with a command-less item at the
top level, nested one deep, rebuilt on a timer, and typed at, does not crash —
so something about predc's menu that the fixture does not have is part of the
trigger, and the account above is the mechanism rather than the whole story. A
regression test that passes with and without the fix is worse than none, so
there is no fixture: the real coverage is `drive_calc.py`, which dies outright
against the unfixed build and was verified doing so. If this ever comes back,
reduce it properly and put the fixture in `drive_regress.py`.
