# Driving a C or C++ library from Gren

Gren has no foreign function interface. A Gren program cannot call C, cannot
load a shared library, and cannot ship JavaScript of its own inside a package.
This document is about what you can do instead, and it is written for a Gren
programmer who has some C or C++ library in mind and wants to know how to get
at it from a Gren program running on Node.

Everything in it was learned by binding one particular library, Turbo Vision,
and that binding is used as the example throughout.
[architecture.md](architecture.md) describes that binding in detail. This
document is about the general approach of using a C or C++ library from Gren.

## The shape of the problem

There are exactly three ways for anything to leave or enter a Gren program on
Node, and only one of them is yours to use:

  - **Kernel code.** The Gren core packages (`gren-lang/core`, `gren-lang/node`
    and the rest) contain JavaScript that the compiler links in. That is how
    `FileSystem`, `ChildProcess` and `HttpClient` exist. The compiler refuses
    kernel code in any other package, so you cannot write a `Curses.gren`
    with JavaScript behind it and publish it.
  - **The node platform's own tasks.** `ChildProcess.spawn`, `FileSystem`,
    `HttpClient` and friends. These reach the outside world, and one of them
    (a child process) is a legitimate way to reach a C library, covered below.
  - **Ports.** An application, and only an application, may declare a port.
    An outgoing port carries a JSON value from Gren to JavaScript; an incoming
    port carries one the other way. Each is one-directional and asynchronous
    and has no return value.

So the library will live on the JavaScript side of a port, and the Gren program
will talk to it in messages. Three consequences follow from that and they shape
every decision afterwards:

  1. **Nothing can be asked, only told.** There is no call that returns a value.
     If the Gren program needs to know something the library knows, either the
     JavaScript side sends it unprompted whenever it changes, or the program
     sends a request and later receives an answer as an event.
  2. **Everything crosses as JSON.** Pointers, handles and objects do not
     travel. Anything long-lived on the C side needs a name the Gren program
     chooses, an `id` string, so both sides can refer to it.
  3. **The JavaScript side is a real layer with real responsibilities**, not a
     shim. It owns the library's objects, translates between the Gren
     program's messages and the library's calls, and decides when it is safe
     to call back. It will be the part with the most bugs and it needs its own
     tests.

## Four ways for C to reach Node

The library has to become something Node can call. There are four routes, and
the choice depends on the library rather than on Gren.

| route | what it is | when it fits |
|---|---|---|
| **Node-API addon** | C++ compiled into a `.node` shared object with `node-addon-api` and `node-gyp` | the library is C++, or wants callbacks into JavaScript, or owns the terminal, a window or its own main loop. This is what tvision-node is. |
| **FFI** | a JavaScript FFI package loads a shared library and calls it with no compiled glue | a plain C API with a flat surface, data in and data out. No C++ compiler at install time. Callbacks and ownership of a main loop are where it stops being simple. `koffi` may be the package to use for this, but nothing in this repository has tried it. |
| **WebAssembly** | the library compiled with Emscripten or clang to `.wasm`, loaded by Node | pure computation: parsers, codecs, maths. No native toolchain at install time and one build for every platform. Anything that touches the terminal, files or sockets directly does not port. |
| **child process** | the library wrapped in a small C program that speaks a line protocol on stdin and stdout, started with `ChildProcess.spawn` | no JavaScript layer at all: Gren talks to it through the node platform's tasks. The process boundary gives you memory safety for free. It cannot share a terminal or a screen with anything else. |

Turbo Vision needed the first route. It is C++, it owns the terminal, it wants
to run the main loop, and it calls back into application code on every event.
None of the other three can do that.

If your library is a C API that computes something and returns it, do not
write an addon. FFI or WebAssembly gets you there with no compiler and no
build matrix.

## Getting a handle on the Gren program

The JavaScript side needs to start the Gren program and hold on to its ports.
Two things about the Gren toolchain make this possible.

**Compile to a module, not an executable.** `gren make Main` produces a
self-running script that initialises itself and throws the handle away.
`gren make Main --output=main.js` produces a CommonJS module that runs nothing
and exports the program:

```js
const program = require('./main.js');
const app = program.Gren.Main.init({ flags: {} });
app.ports.toJs.subscribe((message) => { /* drive the library */ });
app.ports.fromJs.send({ type: 'event', /* ... */ });
```

That is the whole of the interface. `init` takes the flags the program's
`init` will decode. Commands the program issues from its own `init` arrive
after `init()` returns, so subscribing afterwards misses nothing.

**A package may not declare ports.** The compiler refuses with
`PACKAGES CANNOT HAVE PORTS`, and the rationale, inherited from Elm, is not
negotiable. So if you want to publish your binding as a Gren package, the
package cannot contain the ports. The application declares them and hands them
to the package as a record:

```gren
port module Main exposing (main)

port toJs : Encode.Value -> Cmd msg
port fromJs : (Decode.Value -> msg) -> Sub msg

ports : MyLib.Ports Msg
ports =
    { toJs = toJs, fromJs = fromJs }
```

and the package exposes something like

```gren
type alias Ports msg =
    { toJs : Encode.Value -> Cmd msg
    , fromJs : (Decode.Value -> msg) -> Sub msg
    }

defineProgram : Ports msg -> Configuration model msg -> Program model msg
```

which wraps the application's `init`, `update`, `subscriptions` and `view`,
encodes what goes out, and decodes what comes in. Eight lines of boilerplate
per application is the price and there is no way round it.

This is why a binding is three published artifacts rather than one:

| artifact | registry | contents |
|---|---|---|
| the Gren package | Gren | types, encoders, decoders, `defineProgram`. Pure Gren. |
| the runtime | npm | the JavaScript layer that reads the port and drives the library, plus a launcher script |
| the native binding | npm | the addon, or whichever of the four routes you chose |

The launcher is a few lines. For gren-tvision it is `gren-tui`, and an
application's whole build is:

```sh
gren make Main --output=main.js && gren-tui main.js
```

Naming both ports as an option on the runtime, with a default, is worth doing
early: it lets an application that already has ports of its own choose names
that do not collide.

## Designing the protocol

The port carries JSON and nothing else, so the protocol is the API. These rules
came out of getting it wrong first.

**Tell, do not ask.** For every piece of library state a C program would read
with a getter, decide who moves it. If the library or the user moves it, the
JavaScript side reports it as an event when it changes, and the Gren program
stores what it heard. If the Gren program moves it, it sends the new value and
the JavaScript side applies it. Turbo Vision's Edit button reads the list's
focused row at the moment it is pressed; the Gren version cannot, so the list
reports every highlight move as a `Focused` event and the program already
knows it.

**An echo is not an event.** Some values move from both ends: the Gren program
writes them, and the user moves them too. A highlighted row, a scroll position,
a cursor offset, the size of a window. The JavaScript layer sees both kinds of
change, and must report only the ones the Gren program did not cause. If it
echoes the program's own writes back, the program is told about a value it just
set, stores that, and sends it out again on the next render. Nothing goes wrong
while the two sides agree, which is most of the time. They stop agreeing when
the value moves faster than a round trip -- a held key, a mouse wheel -- and
then a value from several renders ago comes back as news and is written over
what the user has done since. The exception is a write the library could not
honour, such as a position past the end of something that has since got
shorter. That is worth reporting, because it is news rather than an echo, and
it settles in one round.

**A query is asynchronous.** When an answer genuinely has to come back, such as
reading a document out of an editor or opening a dialog, the shape is a
request message out and an answer message in, and the Gren side wraps it as a
`Cmd` that produces a `Msg`. This is exactly how an HTTP request looks in Gren
and it needs no new machinery.

**Version the wire format.** A Gren package and an npm package are published
separately and will drift apart. Every message from Gren carries a `protocol`
integer, and the runtime refuses a number it does not recognise. Without that,
a new field looks to an old runtime like nothing at all, and the failure is a
program that renders nothing or quietly stops updating.

**Decode leniently in one direction.** The Gren side's event decoder has an
`Unknown` variant for a message type it does not know, so a newer runtime can
send events an older package ignores. The runtime side is strict about the
protocol number and the Gren side is lenient about event names. That
combination lets either half move first.

**Name long-lived things.** Anything the library keeps alive across messages,
a window, a widget, a buffer, needs an `id` chosen by the Gren program. The
JavaScript layer keeps the map from id to object. Two ids for the same thing,
or an id that outlives its object, are the bugs this invites, and the layer
needs an `exists` check it is not embarrassed to call.

**Choose between describing and commanding.** There are two styles of
protocol. A *command* protocol sends imperative messages: open this, set that,
close the other. A *description* protocol sends the whole desired state every
time and lets the JavaScript side diff it against what it applied last. The
description style is what Elm does with the DOM and what gren-tvision does with
windows: the Gren program's `view` is a pure function and never has to know
that a window is an object with focus and a scroll position to lose. It costs a
differ, which is the most intricate piece of JavaScript in the binding. The
command style is simpler and fits a library whose objects are few and whose
state the program does not want to own. Most bindings will want the
description style for their main state and a few command messages for the
things that are actions rather than state, which is exactly what gren-tvision
ended up with.

**Compare descriptions with descriptions, never with the library.** If the
JavaScript side diffs the Gren program's value against what the library
currently holds, it will write that value back over whatever the user just did.
It has to diff the previous description against the next one, so a value is
only written when the program changed it. Every virtual DOM has this rule and
it is not optional.

## The event loop

This is the part most likely to decide whether the binding is possible at all.

A library that expects to own the process has a blocking main loop, and under
that loop Node's event loop never runs: no timers, no promises, no I/O and no
ports. A Gren program under it could not receive its own commands, so the
first request that needs an answer deadlocks. The library has to become a
guest inside Node's loop rather than the host.

Whether that is possible depends on the library. Look for three things before
writing any code:

  - a way to make its wait-for-input call return immediately when there is
    nothing to do. A timeout parameter that accepts zero, or a poll variant.
  - one iteration of its loop, separable from the loop. If the loop is a small
    function around a `getEvent` and a `handleEvent`, the iteration can be
    lifted out into the addon even if the library does not export it.
  - whatever it does at the top of its loop, such as flushing a display, being
    on the path for that one iteration and not only on the blocking path.

With those, the addon exports `start()` and `step()` in place of `run()`, and
the JavaScript side pumps:

```js
const tick = () => {
  const handled = addon.step();
  if (handled < 0) return;              // the library has shut down
  if (handled > 0) setImmediate(tick);  // busy: come straight back
  else setTimeout(tick, IDLE_MS);       // idle: a few milliseconds
};
tick();
```

`step()` should drain what is waiting rather than handle one event, or input is
rationed at the timer's rate and a paste trickles in.

**Modal loops are the same problem again, inside.** A library with a blocking
main loop usually has nested blocking loops too, for dialogs, menus and
anything else "modal". Each has to be found and either hoisted out the same
way or left alone with its cost written down. Turbo Vision's dialogs were
hoisted, and its pull-down menus were not; for as long as a menu is down the
process is stopped, with the timers and the I/O queueing up to fire when it
closes, and that is documented rather than fixed.

**Call back only at safe points.** A callback into JavaScript can do anything,
including sending a message to Gren whose reply arrives synchronously as a
port message that closes the very object the library is in the middle of
using. So the addon must not call JavaScript from inside the library's own
dispatch. It queues notifications in C++ and drains them from `step()` between
events, where nothing is half-destroyed. Two rates are useful: some
notifications drain after every event, and some once per `step()` so that a
burst of keystrokes becomes one message.

**One handle scope per dispatch.** Every JavaScript value the addon creates
while calling back is held until the enclosing `Napi::HandleScope` closes. A
long-running loop with no scope of its own leaks every string it ever passed.

**Errors in callbacks.** A callback that throws is caught in C++ where the
call was made. The right response is to tear the library down first, restore
whatever it took over (the terminal, in Turbo Vision's case), and rethrow once
`step()` is back in JavaScript. A callback that returns a rejected promise
cannot be seen from C++ at all, so the JavaScript layer wraps every callback
and routes rejections to the same teardown by hand.

## Writing the addon

A Node-API addon is a C++ file and a `binding.gyp`. The smallest real one in
this repository is `m0-load-test/`, thirty lines that load ncurses and add two
numbers, and it exists because the first question is always whether the addon
loads at all:

```c++
#include <napi.h>
#include <ncurses.h>

static Napi::Value CursesVersion(const Napi::CallbackInfo &info)
{
    return Napi::String::New(info.Env(), curses_version());
}

static Napi::Object Init(Napi::Env env, Napi::Object exports)
{
    exports.Set("cursesVersion", Napi::Function::New(env, CursesVersion));
    return exports;
}

NODE_API_MODULE(m0, Init)
```

```python
{
  "targets": [{
    "target_name": "m0",
    "sources": [ "src/m0.cc" ],
    "include_dirs": [ "<!@(node -p \"require('node-addon-api').include_dir\")" ],
    "cflags_cc": [ "-std=c++17", "-fexceptions", "<!@(pkg-config --cflags ncursesw)" ],
    "cflags_cc!": [ "-fno-exceptions" ],
    "defines": [ "NAPI_CPP_EXCEPTIONS" ],
    "libraries": [ "<!@(pkg-config --libs ncursesw)" ]
  }]
}
```

`npx node-gyp rebuild` produces `build/Release/m0.node`, and
`require('./build/Release/m0.node')` is an object with `cursesVersion` on it.

Use Node-API through `node-addon-api`, not V8's own headers. Node-API is
ABI-stable across Node major versions by contract, so one compiled `.node`
works on Node 18, 20, 22 and after. That removes the build-per-Node-version
cost that native addons are remembered for. Set `NAPI_VERSION` in the
`defines` so the minimum Node version is a decision rather than an accident.

Things that went wrong here and will go wrong again:

  - **The library has to be position-independent.** A `.node` is a shared
    object, so a static archive linked into it must be built with `-fPIC`
    (`-DCMAKE_POSITION_INDEPENDENT_CODE=ON` under CMake). A non-PIC archive
    fails at link time with a message about relocations.
  - **One toolchain for everything.** The static archive, the addon and the
    `node` that loads it have to agree on libc and libstdc++. This repository
    builds inside devbox, where `node` and `g++` are both nix's, and an
    archive built by the system compiler does not link there. Building on two
    machines and copying either half across does not work either.
  - **Header order.** A library with a long history has macros and typedefs
    that collide with V8's headers. Turbo Vision's Borland compatibility layer
    defines `Boolean`, `True` and `False`. Include `napi.h` first.
  - **`-fno-rtti` is the default.** node-gyp compiles without run-time type
    information, so `dynamic_cast` is unavailable. Keep your own pointers to
    the objects you created rather than recovering them from the library.
  - **Exceptions.** Turn them on (`-fexceptions`, `NAPI_CPP_EXCEPTIONS`) so a
    `Napi::Error` thrown in C++ becomes a JavaScript exception at the call
    site. Type-check every argument and throw a `Napi::TypeError` with the
    expected signature in the message. The alternative is a segfault with no
    stack.
  - **Global state.** If the library keeps its application, screen or
    equivalent in statics, there is one instance per process and the addon
    should say so with an error on the second `start()`.
  - **Manual memory management against somebody else's library** wants an
    AddressSanitizer build from the first week. `-fsanitize=address` on both
    `cflags` and `ldflags`, and run `node` with the ASAN runtime preloaded.
    The one-byte overrun that aborts ten minutes later in an unrelated `free`
    is found in seconds this way and in days any other way.
  - **Object lifetimes.** The library destroys things on its own schedule, and
    the user may destroy things the program never asked to close. Find the one
    place every destruction passes through, a destructor usually, and drop the
    id there. Do not call JavaScript from that destructor; queue it.

## The JavaScript layer

Between the port and the addon sits the layer that translates. Write it as a
function that takes the binding as an argument rather than requiring it
directly, because the whole of it can then be unit-tested against a fake
binding in milliseconds, with no library, no terminal and no C++:

```js
function createDriver(binding, sendToGren) {
  let previous = null;
  return {
    apply(description) {
      /* diff previous against description, call binding.* for the difference */
      previous = description;
    },
  };
}
```

Every bug gren-tvision's differ has ever had, a window rebuilt when only its
title changed, a self-inflicted close reported as the user's, a value written
back over the user's typing, was a pure-logic bug that a fake binding catches
and a terminal catches by accident.

The other thing this layer owns is the guard against re-entry. A message from
Gren can arrive while the previous one is being applied, because applying it
called back into Gren. `apply` sets a flag, stashes the newest message, and
loops rather than recursing.

## Four places have to agree

Every capability the binding exposes is spelled out in four places: a Gren
type, its Gren encoder, the JavaScript layer that reads the JSON, and the C++
that acts on it. No compiler sees more than one of them. Miss one and nothing
complains; the widget silently does not appear, or appears and silently stops
updating.

Write a script that walks all four and compares them, and run it before every
commit. In this repository it is `tools/check_consistency.py`, and it compares
view types, event names in both directions, the callback names the runtime
hands the addon, and the protocol number on both sides. Its first catch was a
callback named `onFocussed` where the addon wanted `onFocus`: valid
JavaScript, accepted without complaint, never called.

## Testing

Three levels, fastest first, and the fast ones catch most of it:

  1. **The JavaScript layer against a fake binding**, with `node --test`. No
     library involved.
  2. **The Gren package's pure logic**, with `gren-lang/test`. Encoders and
     decoders round-trip; anything with a rule in it.
  3. **The real thing**, driven end to end. For a terminal library that means
     a pseudo-terminal, a small terminal emulator to replay the output into a
     grid, and a driver that types and asserts on the grid. Slow, and the only
     honest test. Run the same drivers under the AddressSanitizer build.

## Shipping

The Gren package publishes like any other. The npm side is where the cost is,
because one of the packages contains a compiled shared object.

  - Node-API means one binary per platform, not one per Node version.
  - `prebuildify` puts the binaries inside the tarball and `node-gyp-build`
    picks the right one at install time, falling back to a source build. No
    download at install time, which is the part users distrust.
  - A source build needs a C++ compiler and the library's own dependencies.
    Say exactly which in the README. If the library can be compiled directly
    from `binding.gyp`, with no CMake step, a source install gets much simpler;
    check whether its build generates any headers before assuming it can.
  - The library's licence travels with the binary. If you link it statically,
    its notice files have to be in your tarball.

[../../doc/publishing.md](../../doc/publishing.md) has the platform-by-platform
detail for gren-tvision, including what a manylinux build is for.

## Where to look in this repository

| | |
|---|---|
| `m0-load-test/` | the thirty-line addon: does it load, can it reach a system library |
| `tvision-node/src/app.cc` | the pump, the safe-point queues, modality hoisted out of the library's nested loop |
| `tvision-node/index.js` | the `tick` loop and the callback guard that routes rejections to teardown |
| `gren-tvision-runtime/tui.js` | starting the Gren program, the port subscription, the protocol check |
| `gren-tvision-runtime/diff.js` | the differ, written against a binding passed in |
| `gren-tvision-runtime/test/` | the fake binding and the tests that use it |
| `gren-tvision/src/Tui.gren` | the `Ports msg` record and `defineProgram` |
| `tools/check_consistency.py` | the four-places check |
| `FINDINGS.md` | every one of the above, in the order it was discovered |
