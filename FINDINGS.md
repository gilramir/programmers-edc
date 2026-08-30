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

## Still open, for milestone 2

Milestone 1 is the **blocking** design: `tv.run()` calls
`TApplication::run()` and Node's event loop is starved until the app quits. The
pieces for the pumped version are all present and were checked before any of
this was written:

- `TProgram::eventTimeoutMs` (`include/tvision/app.h:296`) is a public static;
  set it to `0` and `getEvent` stops blocking.
- `TGroup::execute()` (`source/tvision/tgroup.cpp:173`) is four lines, and
  `TGroup::endState` is public (`include/tvision/views.h:919`), so one iteration
  can be hoisted into a `step()` driven by a libuv timer.
- The repaint survives it: `THardwareInfo::waitForEvents` flushes the screen
  *before* polling (`source/platform/hardware.cpp:105-113`), which is on the path
  even at timeout 0.
- `TEventQueue::wakeUp()` (`source/tvision/tevent.cpp:461`) exists for
  cross-thread wakes, if the pump should become event-driven rather than timed.

The wart to design around: `execView` starts a *nested* blocking loop, so a modal
dialog opened from a JS callback stalls Node until it is dismissed. Milestone 1
does this and does not care. Milestone 3 cannot, which points at non-modal
dialogs delivering their result by callback.

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

**This is a constraint on milestone 2**: views need stable string ids and
in-place mutation (`setText(id, ...)`), not just construction. If the API can
only create-and-forget, the diff layer has to tear down and rebuild windows on
every model change, which will fight TVision's retained focus and keyboard
state. Cheap now, expensive later.
