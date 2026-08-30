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

## Milestone 3 — Gren, from reading the compiler output

Checked against a compiled Gren 0.6 node app rather than from memory:

- Gren still ships the Elm port machinery — `_Platform_outgoingPort` and
  `_Platform_incomingPort` are both in the output. **Ports exist.**
- But a `node`-platform build ends with
  `_Platform_export({'Main':{'init':...}}); this.Gren.Main.init({});` — it
  self-initializes and **throws the handle away**, so there is nothing to call
  `.ports.foo.subscribe()` on. A wrapper that strips that last line and calls
  `require('./main.js').Gren.Main.init({})` itself would work; whether the
  compiler offers something cleaner is unverified.
- Third-party kernel code is almost certainly disallowed (inherited from Elm),
  so "a Gren package that calls the addon directly" is out. Ports it is.

The shape to aim at is the Elm one: Gren's `view` produces a declarative tree
(windows, dialogs, buttons — each with a stable id), JSON over an outgoing port,
JS diffs it against the previous tree and makes imperative addon calls; events
come back over an incoming port as messages. Gren never calls C++ synchronously,
so the blocking-loop problem disappears entirely.

**This was the constraint on milestone 2**, and it is now satisfied: views have
stable string ids and mutate in place, so a diff layer can patch rather than
rebuild.

What is left in the way is modality. `tv.dialog()` blocks Node, which a
port-based Gren app cannot tolerate — a `Cmd` that never returns to the runtime
is a deadlock, not a dialog. Milestone 3 needs dialogs inserted non-modally
with their result delivered as a message, which the `JsWindow` non-modal path
already supports; what is missing is a `dialog()` that does not call
`execView`.
