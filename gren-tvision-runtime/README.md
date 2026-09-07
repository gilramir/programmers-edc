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

`TUI_RECORD_VERBATIM=/tmp/bug.tape` is the same with the withholding off. It is
for a *test*, which owns the documents it pastes, and not for a user, who does
not.

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

**What never crossed a port.** `Time.now`, `Time.every` and `Crypto` are Gren
tasks rather than messages, so nothing here sees them happen, and a tape
without them is not quite the input it claims to be. They are dealt with
differently because they need different things:

  - **Random draws are recorded**, by replacing `Crypto.prototype`'s
    `getRandomValues` while a tape is open — the module object node hands the
    Gren kernel defines it as a getter that cannot be replaced, so the seam is
    one level in. The wrapper calls through, so the program gets the system's
    own randomness; only the recorder is any the wiser. The bytes are
    **withheld like a document**, because the whole purpose of a random value
    is that somebody is about to use it for something.
  - **Every reading of the clock is recorded too**, which was argued out and
    back in. Reconstruction — every line is stamped, the header carries the
    instant it began — is enough for a program that *displays* the time and not
    for one that seeds something with it: `examples/puzzle` shuffles its board
    from `Time.now`, and a board is not nearly the same when the seed is nearly
    the same. The argument against was that `Date.now` cannot be intercepted
    for one caller; measured rather than assumed, a running gren-tvision
    program has exactly two, the Gren kernel and this file's own stamps.
    `runtime.timeZone` is on the header for the same reason — `Time.getZoneName`
    reads `Intl` and crosses nothing.

Two things a tape still cannot reach: it sits above Turbo Vision, so a key that
decoded wrong or a paint that came out wrong is invisible to it; and the values
`init` read off the disk — the environment, the file a viewer was opened on —
are the user's, and deliberately not on it.

## Replaying a tape

```sh
gren-replay bug.tape main.js        # the compiled module, not the launcher
```

No terminal is opened and Turbo Vision is never started. The program is driven
straight through its ports and its output is fingerprinted the way the recorder
fingerprinted the original; the first pair that differs is the answer, printed
with the message that was fed last. Exit 0 if the tape reproduced, 1 if it
diverged, 2 if it could not be run.

```
  --env NAME=VALUE   plant a variable the tape kept only the name of
  --in-place         let the program write where it wrote when recorded
  --trace            print every message, both ways, as it goes
```

**The tape drives itself, through the program's own output.** This is the whole
design and it took a wrong one to find it. The obvious driver feeds a message,
waits, checks what came back, and feeds the next — and it cannot reproduce a
tape, because a tape's order is not the program's. `predc time` proved it in
four lines: the terminal's first `resized` arrived *between* two steps of
`init`'s own chain, after its first render and before it asked node for the
time zones. Feeding that resize a moment later — which is all "wait, then
send" can do — puts the program in a state the recording never had, and every
render after it differs for a reason that is not a bug. So there is one cursor
over the tape: an outbound message is matched against what it points at and
steps it forward, and an inbound message is sent the instant the cursor reaches
it, from inside the subscription that moved it there.

**A replay is the program, so a replay writes what the program writes.** That
is obvious once it has happened to you: replaying a session in which somebody
changed a setting makes the program save the setting, over yours, on a machine
that was only meant to be reading a bug report. So a replay gets a directory of
its own, with `HOME` and the XDG variables pointed into it, and the files the
launcher recorded in `extra` seeded inside it. That is safer and also *more*
faithful — `init` then decides from the recording's config rather than from the
config of whoever is reading the tape. `--in-place` turns it off and says so.

What goes back before the program starts: the arguments (which for predc decide
whether there is a program to run at all), the working directory, the time
zone, the four numbers `Terminal.initialize` answers with, the flags `init` was
given, and the clock. `Time.every` is driven rather than waited for, so a tape
with a clock in it replays in milliseconds rather than in the minute it took to
record.

A launcher that wants its own state replayed records it as `{path, contents}`
under `extra`, and a path under `.config`, `.local/share`, `.local/state` or
`.cache` is placed where the matching XDG variable will find it.

`Time.every` is driven from the tape rather than from arithmetic. A recording
has its ticks at 1017, 2017, 3018; a replay firing its own at 1000, 2000, 3000
draws a clock a second out the moment the offset crosses one, and fires ticks
in places the recording has none — a timer due at 42032 is due whether or not
the program was awake for it. So a tick goes off only where the tape has a
render with no message under it, stamped with that render's own time.

**What a tape can and cannot hold a program to.** An inbound message is a
barrier: nothing recorded after one can have been produced before it was sent.
*Between* two of them the order of two different ports is not the program's —
predc's request to node for its time zones lands either side of a render
depending on which chain the recording machine finished first — and neither is
the order of two different kinds of message on one port. Nor is a render that
repeats the screen already drawn: the differ patches nothing for it and no
screen can tell, so a repeat is walked past on whichever side has it. What is
asserted is that each distinct screen happened, in this order, and that they
were these screens.

A message going *in* can be fed one step early when what the program has just
said is exactly what the tape has on the other side of it — a `Cmd` resolving
through a Task comes out after the render beside it, and the terminal's next
message lands in between.

And "the program has stopped" is asked rather than waited for:
`process.getActiveResourcesInfo()` shows a file read as `FSReqCallback` and a
real timer as `Timeout`, and shows nothing for a virtual `Time.every`. Counting
milliseconds instead makes the answer depend on how loaded the machine is,
which is a replayer reporting races it invented.

What it cannot put back is what the tape does not carry: the values of
environment variables (names only, on purpose — `--env` is for the two that
mattered) and any file the program read that its launcher did not record. Both
are reported before the first message is fed, because the failure they cause
looks exactly like a bug in the program.

## Every driver as a replay

`tvision-node/test/harness.py` points `TUI_RECORD_VERBATIM` at a scratch file
for every session a pty driver runs, and `Checks.report` runs each tape back
through the program with no terminal. There is nothing to add to a driver: the
variable is the runtime's own, so fifty-odd drivers became fifty-odd replay
tests for nothing. It is **off by default** — `TVNODE_TAPES=1` turns it on —
because 38 of 40 replay exactly and the two that do not still flap. Five
drivers are marked as never replayable and say why: `watch` spawns child
processes and watches a directory, `dir` lists one, `notes` reads and writes
files, `edit` saves the document it opened, and `viewer` is pointed at a file
each case rewrites — all Tasks rather than messages, and on no tape. A driver
that knows it cannot replay says so with `Checks(replays="...")`, with the
reason.

## Reading a tape

```sh
gren-tape bug.tape             # what the person did, and what changed
gren-tape bug.tape --all       # one line per message, nothing collapsed
gren-tape bug.tape --extra     # the launcher's block, as JSON
gren-tape bug.tape --json      # the analysis, for something else to read
```

A tape is mostly drag events — a window pulled across the screen is fifty
`windowResized` messages — so the report collapses runs of the same gesture and
says what each one changed:

```
   9.7s  command tool.calendar                          → +calendar  a1d01b9c
  10.8s  calendar moved ×37  [25,4,63,17] → [50,18,88,31]  → unchanged
  13.4s  command calendar.prev                          → 2f17b5e0
  46.5s  command help.tools                             → +help  089b607e
  48.0s  help.scroll scrolled 3 → 0, out to 18 ×12      → 089b607e  (12 renders)
```

**The right-hand column is the reason this exists.** A render is on the tape as
a hash, and the hash is the only thing that says whether the program did
anything: an input followed by an identical hash is an input the model looked at
and ignored. That is usually correct — the calendar does not store its own
rectangle, so dragging it changes nothing it draws — and occasionally it is the
whole bug, and either way it cannot be seen in the raw file.

A program with a second inbound stream gets it labelled — predc's time
converter answers over `intlIn`, and two conversations printed as one would be
worse than not having teed the second onto the tape at all.

It also reports what it can tell is wrong without replaying anything: a window
rectangle with a negative origin or one past the desktop, a `readClipboard` or a
`dialog` that was never answered, a crash, a truncation, a tape that just stops,
and a format or protocol older than the build reading it — which names what the
older format was missing rather than only that a number differs.

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
