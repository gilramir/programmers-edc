# gren-tvision (the JavaScript half)

The Gren package [`gilramir/gren-tvision`](../gren-tvision) is pure Gren: it can
describe a UI but cannot touch a terminal, because **Gren packages may not
declare ports**. This npm package is the other half — it takes the description
off the port and drives [`tvision-node`](../tvision-node) with it.

```
gren make Main --output=main.js
gren-tui main.js
```

or, from your own JavaScript:

```js
const run = require('gren-tvision');
run(require('./main.js'));           // options: {flags, moduleName, outPort, inPort}
```

The program must declare ports named `tuiOut` and `tuiIn` (override with
`outPort` / `inPort`). `TUI_DEBUG=/tmp/trace` logs the port conversation, which
is the only way to watch it — the terminal belongs to Turbo Vision.

## Recording a session

```sh
gren-tui main.js --record /tmp/bug.tape     # or TUI_RECORD=/tmp/bug.tape
```

A **tape** is what somebody who hit a bug can send you instead of describing
it. The port boundary is total — a Gren program here is a pure function of what
`init` read and what arrived on `tuiIn` — so a file with those two things in it
is the input that produced the failure, not an account of it.

It is JSON lines. The first line is the header: argv, working directory,
terminal size and TTY-ness, `TERM` and the handful of other variables that
decide how a terminal behaves, node and OS versions, the protocol number, and
whatever the launcher put in `extra`. Every line after it is one event, stamped
with milliseconds since the header.

```
{"tape":1,"at":"…","redacted":true,"program":{…},"protocol":22,"terminal":{…},"envNames":[…]}
{"t":39,"out":"render","hash":"db6159a141bafe53","windows":["env"],"overlays":0}
{"t":40,"in":{"type":"resized","cols":80,"rows":23}}
{"t":2464,"in":{"type":"changed","id":"env.find","value":"TERM"}}
{"t":3464,"end":"exit"}
```

**Inbound is kept, outbound is fingerprinted.** A render is the output and a
replay regenerates it, so what goes on the tape is its hash and the window ids
it drew — enough to check a replay against, and not enough to leak anything. It
is also the only safe choice: a render carries whatever the tools are showing,
and predc's environment tool showed the user's credentials.

**What is withheld, and what cannot be.** `editorText` and `clipboardText` are
documents rather than gestures, so they are recorded as a length and a hash;
the rest of the message, including the id, is kept. Environment variables are
recorded by name only. Keystrokes are kept, because redacting them redacts the
bug — so the program prints a notice on the way out saying where the file is,
that everything typed is in it, and to look before sending it.
`--record-verbatim` turns the withholding off for the case where the document
*is* the bug.

**A program with ports of its own** must tee them, or its tape will not replay:
`run()` returns the app with a `tuiRecorder` on it for exactly that.

```js
const app = run(main, { record: { path, verbatim, program, extra }, crashLog });
myPort.attach(app, { record: app.tuiRecorder });
```

Three things a tape cannot reach, stated so nobody is surprised by them:
`Time.every`, `Time.now` and `Crypto` never cross a port, so a replay gets
different ticks and different random bytes; the tape sits above Turbo Vision,
so a key that decoded wrong or a paint that came out wrong is invisible to it;
and a replayer is not written yet — this is the recording half.

## Crashes

`crashLog` is a path, and the handlers are installed whether or not a tape was
asked for, because a crash happens on the run where nobody thought to record.

The binding already handles the case it can see: a callback that throws
synchronously is caught in C++, which shuts the application down and rethrows
once the terminal is restored. What this covers is an exception with no
callback under it — a `setTimeout`, the Gren runtime's own scheduler — which
otherwise kills the process with the alternate screen still up, and looks to
the user like a terminal that hung. The handler puts the terminal back, writes
the error to the tape and the crash log, prints it, and exits 1.
