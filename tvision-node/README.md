# tvision-node

A Node-API addon that binds [Turbo Vision](https://github.com/magiblot/tvision)
(magiblot's C++ revival of Borland's 1990 TUI framework) to Node, plus a thin
JavaScript wrapper over it.

It exists to be the native half of [gren-tvision](../gren-tvision). Everything
in it was built because a Gren program needed it, and that is the only measure
by which it is finished. It is usable from plain JavaScript -- the examples in
`examples/` are plain JavaScript and nothing here knows what Gren is -- but see
[What this is not](#what-this-is-not) before treating it as a general-purpose
Node binding for Turbo Vision. It is not one, and is not trying to become one.

## The one idea

Turbo Vision expects to own the process. `TApplication::run()` blocks, and
under it Node's event loop never gets a turn: no timers, no promises, no I/O,
no ports. A Gren program under that could not receive its own commands.

So the loop is inverted. The addon exports `start()` and `step()` instead of
`run()`, and `index.js` pumps:

```js
const tick = () => {
  const handled = addon.step();
  if (handled < 0) return;              // shut down
  if (handled > 0) setImmediate(tick);  // busy: come straight back
  else setTimeout(tick, IDLE_MS);       // idle
};
```

`step()` drains whatever input is waiting rather than handling one event, so a
paste does not trickle in at the timer's rate. Three facts in the Turbo Vision
source make this possible, and they are cited at the top of `src/app.cc`:
`TProgram::eventTimeoutMs` is a public static that can be set to 0,
`TGroup::execute()` is four lines around a public `endState`, and the screen is
flushed before polling rather than after, so the display still repaints at
timeout 0.

The visible payoff is in `examples/demo.js`: a clock repainted by
`setInterval`, a directory listing filled by `await fs.readdir`, and modal
dialogs that take all the keyboard input without stopping any of it.

Two consequences run through the whole design:

- **Callbacks happen at safe points, never inside Turbo Vision's dispatch.** A
  callback into JavaScript can do anything, including closing the very view the
  library is in the middle of using. Notifications are queued in C++ and
  drained between events, where nothing is half-destroyed. Some drain after
  every event; changes, edits and drags drain once per `step()`, so a burst of
  keystrokes becomes one notification and one render.
- **Modality is hoisted out of the library.** `dialog()` and `popupMenu()` are
  modal in the Turbo Vision sense -- input goes only to the dialog -- but they
  return promises and do not stop Node. `execView()`'s nested loop is
  reimplemented over the pump instead.

## Building

Everything runs inside devbox; `node` and `g++` are nix's, and Turbo Vision,
the addon and the `node` that loads it must all agree on libc and libstdc++.

```sh
devbox run build                              # this addon and everything downstream
(cd tvision-node && npx node-gyp build)
```

**node-gyp is the whole build.** `binding.gyp` has two targets:
`tvision_lib`, a static library of Turbo Vision's 206 sources, and `tvision`,
the addon, which `dependencies` it. There is no cmake step and no
`build-tvision/`. The flags on the first target are the ones cmake used to
generate, copied across and commented; the one that is not optional is
`-fPIC`, because a `.node` is a shared object and a non-PIC archive cannot be
linked into one.

The source list is generated into `tvision-sources.gypi` by
`scripts/gen-tvision-sources.py` and committed. gyp has no globbing, and the
`<!@(find ...)` that would stand in for it is a shell dependency in a file that
runs on the machine of whoever installs the package. Regenerate it after moving
the submodule pin; `devbox run check` fails if it is stale.

`tvision/` is a git submodule pinned to `gilramir/tvision`'s `patches` branch
-- upstream master plus the fixes upstream has not taken yet. There is no patch
directory; what the submodule is checked out at is what gets built. It is
inside this package rather than beside it because `npm pack` walks the
filesystem: a checked-out submodule's files travel in the tarball, so the
source build works for anybody with no prebuilt binary for their platform.

An AddressSanitizer build is `TVNODE_ASAN=1 npx node-gyp configure && npx
node-gyp build`, run with `test/asan.sh`. Prefer that over `rebuild`, which now
recompiles Turbo Vision too: the sanitizer flags are decided at configure time
and gyp recompiles only the objects whose command line changed, which is the
two files in `src/`. This is manual memory management against a C++ library from
1994; the one-byte overrun that aborts ten minutes later in an unrelated
`free()` is found in seconds this way and in days any other way.

## The shape of the API

Views are named by ids the caller chooses, not held as objects. A window is
described whole; the callbacks are global and say which id they are about.

```js
const tv = require('..');   // from examples/; this package is not published

tv.start({
  menuBar: [{ title: '~F~ile', items: [{ title: 'E~x~it', cmd: 'quit', key: 'Alt-X' }] }],
  statusLine: [{ text: '~Alt-X~ Exit', key: 'Alt-X', cmd: 'quit' }],
  onCommand: (cmd) => { if (cmd === 'quit') tv.quit(); },
  onSelect: (id, index, text) => { /* a list row was chosen */ },
});

tv.window({
  id: 'greeting',
  title: 'Hello',
  rect: [10, 3, 50, 12],
  items: [
    { id: 'text', type: 'staticText', rect: [2, 1, 36, 3], text: 'Hello, world' },
    { id: 'ok', type: 'button', rect: [14, 5, 24, 7], title: '~O~K', cmd: 'ok' },
  ],
});
```

Twelve view types: `staticText`, `label`, `button`, `inputLine`, `history`,
`checkBoxes`, `multiCheckBoxes`, `radioButtons`, `listBox`, `scrollBar`,
`editor`, and `canvas` -- the last being the escape hatch for anything the set
does not have, a rectangle of coloured spans the caller paints and gets key and
click callbacks for. The puzzle, the calendar and the ASCII table from
`tvdemo` are all canvases.

Roughly: `window`/`close`/`focus`/`exists`/`bringToFront` for windows;
`setText`, `setItems`, `setValue`/`getValue`, `setLines`, `setScroll`,
`setBounds`, `setViewEnabled`, `setViewVisible` and friends for the things
inside them; `setEditorText`/`readEditor`/`searchEditor` for an editor's
document, which is the one piece of state that does not travel with the render;
`dialog`, `messageBox` and `popupMenu`, all promise-returning;
`setMenuBar`/`setStatusLine`/`setTheme`/`overlays` for the application itself;
`setClipboard`/`requestClipboard`, which is a request and an answer rather than
a getter. `index.js` lists them all with the reason for each grouping, and
`src/views.cc` is the authority on what fields each view type takes.

`tv.log()` writes to `$TVISION_LOG` and drops everything otherwise, because
Turbo Vision owns the terminal and `console.log` draws over the app.

## What this is not

- **Not the Turbo Vision API.** There is no `TView` to subclass, no object
  pointers, no `draw()` override. Ids, declarative window descriptions, and
  about fourteen global callbacks. That shape came from the constraint the
  binding was built under -- everything has to survive a trip through JSON --
  and it is not what a C++ Turbo Vision programmer would expect to find.
- **Not the whole library.** `TFileDialog`, `TChDirDialog` and the
  `TColorDialog` family are deliberately not wrapped: in this architecture the
  program owns its data and builds those dialogs out of the parts it already
  has, which is what gren-tvision's own `Tui.fileDialog` helper is and what
  `examples/palette` argues at length for the colour one. There is no help
  system; `THelpFile` reads a binary format produced by `tvhc` and porting the
  compiler buys nothing. `gren-tvision/examples/README.md` records what was
  left out and why.
- **Not stable.** `private: true`, version 0.0.1, no `.d.ts`, no changelog. The
  API changes whenever gren-tvision needs it to.
- **Not multi-instance.** `TProgram::application`, `deskTop`, `menuBar` and
  `statusLine` are statics, so there is one application per process and a
  second `start()` is an error.
- **Not free of the library's nested loops.** Dialogs and context menus were
  hoisted onto the pump; the menu bar's pull-downs were not. While a pull-down
  is open Node's loop is stopped -- timers, promises and I/O queue up and fire
  when the menu closes. Fixing it means reimplementing `TMenuView::execute` as
  a steppable state machine, which is the least documented code in Turbo
  Vision, and the trade was judged not worth it. `FINDINGS.md` has the
  measurement.

## Layout

| | |
|---|---|
| `src/app.cc` | the application, the pump, the safe-point queues, hoisted modality, the menu bar and status line |
| `src/views.cc` | every view type: built from a JSON description, updated, read back |
| `src/tvnode.h` | the `Js*` subclasses -- where Turbo Vision's behaviour is overridden rather than merely called |
| `src/keys.h` | key names to `kb*` codes, in both directions |
| `index.js` | the pump's timing, the promise-rejection guard, `messageBox`, `log` |
| `examples/` | plain-JavaScript applications: `hello`, `demo`, `form`, `ascii`, `clip` |
| `test/drive_*.py` | pty drivers: run the example in a pseudo-terminal, type at it, assert on the screen |
| `test/regress_*.js` | small applications that exist only to be driven |

`tvnode.h` is worth reading before proposing a patch to the submodule: a good
deal of what looks like missing Turbo Vision behaviour is overridden here
instead.

## Tests

From the repository root, `devbox run test` runs these along with everything
else, and `devbox run test:asan` runs the pty drivers again against the
sanitized build. Directly:

```sh
devbox run -- python3 tools/run_tests.py drive_demo
```

The drivers test the **build**, not the source: rebuild the addon after editing
`src/`, or the driver runs the old `.node` and fails in a way that looks
exactly like the feature not working.

## Licence

ISC, in `LICENSE`. Turbo Vision itself is under its own licence and is linked
statically, so anything shipping this binary has to carry the library's notice
files too. `docs/publishing.md` at the repository root has the rest.
