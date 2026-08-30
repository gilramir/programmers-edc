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
  about two minutes. No patches.
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
moves to the next month. That is faithfully reproduced, because it is what
`calendar.cpp` does. Both are reported upstream as
[magiblot/tvision#229](https://github.com/magiblot/tvision/issues/229).

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
