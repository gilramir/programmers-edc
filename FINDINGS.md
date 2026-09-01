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

This one is a bug, it is in the binding, and every program that uses
`Tui.fileDialog` has it.

`applyInitialFocus` (`views.cc`) exists precisely to undo Turbo Vision's
"whatever was inserted last has the caret" — `insert()` prepends, so in a list
written top to bottom the Cancel button wins, and a declarative API should not
inherit an artifact of insertion order. It is called on both paths: for a
window (`views.cc`, after `deskTop->insert`) and for a modal dialog
(`app.cc`, after `beginModal`).

For a window it works. The calculator's canvas has the caret the moment it
opens, which is why typing digits at it does anything.

For a modal dialog with a list in it, it does not. `Tui.fileDialog` opens with
the caret on the *file list*: the `Name` field is two Tabs away, and typing a
path — the thing the field is for — does nothing at all. `examples/dir` has
had this since the day the dialog was written and never noticed, because its
test drives the list with the arrow keys and never types.

What is verified, and it narrows the fault usefully:

  - A dialog of a field, a label and two buttons is **fine**. predc's Go To
    Offset dialog takes what is typed at it the moment it opens, and
    `examples/entries` has been typing into its Add dialog for months.
  - A dialog with a `ListBox` and a `History` in it is **not**. Both the
    programs that have one are affected.
  - It is not a render arriving behind the dialog and stealing the caret: it
    reproduces with an `update` that changes no part of the model.
  - **The same focus, sent one message later, sticks.** `Cmd.batch
    [ Tui.dialog ports spec, Tui.focus ports "fileName" ]` puts the caret in
    the field and leaves it there. So the call is being undone rather than
    refused, by something between `beginModal` and the dialog reaching the
    screen.

The root cause is not found yet. The suspect is `TView::setState(sfVisible,
True)`, which calls `owner->resetCurrent()` for any selectable view being
shown, and a list box brings a scroll bar of its own into the group — but that
happens inside `buildItems`, which runs *before* `applyInitialFocus`, so the
order does not obviously explain it.

`Tool.Hex` carries the one-line workaround with a comment saying why, and
`drive_hex.py` asserts that the field takes what is typed at it, which is a
check that stays true and stays useful after the binding is fixed. **It should
be fixed before anything is published**: a file dialog that ignores the
keyboard is the first thing a new user of this package will meet.

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
