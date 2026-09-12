# gren-tvision-runtime (the JavaScript half)

The Gren package [`gilramir/gren-tvision`](https://github.com/gilramir/gren-tvision) is pure Gren: it can
describe a UI but cannot touch a terminal, because **Gren packages may not
declare ports**. This npm package is the other half — it takes the description
off the port and drives [`tvision-node`](https://www.npmjs.com/package/tvision-node) with it.

The npm name is `gren-tvision-runtime` and the Gren name is
`gilramir/gren-tvision`. Two registries, so nothing collides, but they are two
different artifacts and the suffix is there to keep anybody from having to work
that out for themselves.

```
gren make Main --output=main.js
gren-tui main.js
```

or, from your own JavaScript:

```js
const run = require('gren-tvision-runtime');
run(require('./main.js'));           // options: {flags, moduleName, outPort, inPort}
```

The program must declare ports named `tuiOut` and `tuiIn` (override with
`outPort` / `inPort`). `TUI_DEBUG=/tmp/trace` logs the port conversation, which
is the only way to watch it — the terminal belongs to Turbo Vision.

## Testing your own program at a pty

A Turbo Vision program cannot be tested by piping stdin: the addon refuses to
start unless stdin and stdout are a terminal, and it draws with cursor
addressing rather than lines of text. So this package ships the harness the
project's own fifty-odd drivers use, as

    node_modules/gren-tvision-runtime/pty/harness.py

It is one Python file, standard library only. It allocates a pty, gives it a
size, types at it, strips the escape sequences back out of what comes off the
other end, and hands you the screen as text to make assertions against:

```python
import os, sys
sys.path.insert(0, os.path.join("node_modules", "gren-tvision-runtime", "pty"))
from harness import Pty, Checks, node_argv

GREN_TUI = os.path.join("node_modules", "gren-tvision-runtime", "bin", "gren-tui.js")

check = Checks()
app = Pty(node_argv(GREN_TUI, "main.js"), dict(os.environ, TERM="xterm-256color"))

app.pump(2.0)                             # let it start and draw
check("the title is drawn", "ASCII Chart" in app.render())

app.send(b"\x1b[B", settle=0.3)           # Down, then wait for the repaint
app.click(10, 3, settle=0.5)              # column then row, both from one
check("the chart is drawn", "ABCDEFGH" in app.screen())

sys.exit(check.report(app))
```

**The program is started through `gren-tui.js` and not by node directly.** A
Gren program compiled with `--output=main.js` is a module that exports
`Gren.Main.init`; it does not run itself, and handing it straight to `node` gets
you a pty that draws nothing and two failing checks that say nothing about why.

Four things are worth knowing before you write the second test.

**`send` settles rather than sleeps.** `settle=n` is an upper bound: it returns
as soon as the terminal has been quiet for 200ms, so a generous number costs
nothing. What it cannot wait for is anything the screen does not show -- a
debounced save, a megabyte being copied -- and those pass `wait=n` instead and
get the whole of it. So does a burst of the same key: sixty Downs is sixty
events, the pump chews through them in batches, and the screen is perfectly
still between two of them.

**`render()` is the screen as it stands and `screen()` is everything ever
drawn.** The first answers "what does this say now", the second "did this ever
appear".

**`click` takes column then row, and both count from one.** Row 1 is the menu
bar, so a window's top frame is row 2.

**`check.report(app)` fails on any glyph drawn in the colour behind it**, across
every screen the test looked at. It costs nothing, needs no setting up, and
catches the palette mistake that eyes slide over.

`node_argv` has a branch for running under AddressSanitizer that looks for an
`asan.sh` beside the harness. There is none in this package and there does not
need to be: it is reached only when `TVNODE_ASAN=1`, which is this project's
own variable for testing the addon.

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
{"t":39,"out":"render","hash":"db6159a141bafe53","windows":["env"],"rects":{"env":[2,1,40,20]},"overlays":0}
{"t":40,"in":{"type":"resized","cols":80,"rows":23}}
{"t":2464,"in":{"type":"changed","id":"env.find","value":"TERM"}}
{"t":3464,"end":"exit"}
```

**Inbound is kept, outbound is fingerprinted.** A render is the output and a
replay regenerates it, so what goes on the tape is its hash, the window ids it
drew and the rectangle it drew each of them at — enough to check a replay
against, and not enough to leak anything. It is also the only safe choice: a
render carries whatever the tools are showing, and predc's environment tool
showed the user's credentials. The rectangles are the one exception, and they
are there for the anomaly below: a window off the desktop is a defect when the
*model* put it there and the user's own business when they dragged it there,
and only the outbound side can tell those apart. A position is not a document.

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

**The tape drives itself, through the program's own output.** There is one
cursor over the tape. Each outbound message the program sends is matched
against what the cursor points at and steps it forward; when the cursor then
lands on an inbound message, that message is sent immediately, from inside the
subscription that moved it there.

The obvious alternative — send a message, wait, check the reply, send the next
— cannot reproduce a tape, because the timing it feeds is its own and not the
program's. In `predc time` the terminal's first `resized` arrived *between* two
steps of `init`'s chain, after its first render and before it asked node for
the time zones. Sending it a moment later puts the program in a state the
recording never had, and every render after that differs for a reason that is
not a bug.

**A replay is the program, so a replay writes what the program writes.** That
is obvious once it has happened to you: replaying a session in which somebody
changed a setting makes the program save the setting, over yours, on a machine
that was only meant to be reading a bug report. So a replay gets a directory of
its own, with `HOME` and the XDG variables pointed into it, and the files the
launcher recorded in `extra` seeded inside it. That is safer and also *more*
faithful — `init` then decides from the recording's config rather than from the
config of whoever is reading the tape. `--in-place` turns it off and says so.

What goes back before the program starts: the arguments (in predc, for one,
they decide whether there is a program to run at all), the working directory,
the time zone, the four numbers `Terminal.initialize` answers with, the flags
`init` was given, and the clock. `Time.every` is driven rather than waited for, so a tape
with a clock in it replays in milliseconds rather than in the minute it took to
record.

A launcher that wants its own state replayed records it as `{path, contents}`
under `extra`, and a path under `.config`, `.local/share`, `.local/state` or
`.cache` is placed where the matching XDG variable will find it.

`Time.every` is driven from the tape rather than from arithmetic. A recording
has its ticks at 1017, 2017, 3018; a replay firing its own at 1000, 2000, 3000
draws a clock a second out the moment the offset crosses one, and fires ticks
in places the recording has none — a timer due at 42032 is due whether or not
the program was awake for it. **So the recorder records them**, by wrapping
`setInterval`, whose only caller in a gren-tvision program is the kernel behind
`Time.every` — the binding's pump is a `setTimeout` that reschedules itself. A
tick is a line on the tape and a step in the replay: fired where the tape has
it, with the interval the tape names, and never inferred.

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
message lands in between — but never over an unmet expectation on its own
port, since a request and its reply share one and that would be answering a
question nobody asked.

**A message goes in on a microtask** — `queueMicrotask`, which runs the callback
once the current JavaScript call stack has unwound but before node takes any
timer or I/O callback. Getting that right is what made the replay a function of
its tape. Feeding it from inside the subscription that brought the cursor to it
re-enters the Gren scheduler mid-dispatch, where `_Scheduler_enqueue` queues
rather than runs, and one update's two effects come back in either order
depending on how busy the machine is. Feeding it a turn
later instead is deterministic and wrong, because a recording's messages are
coupled to the program's own progress: Turbo Vision's pump delivers the next
event only once the last render has been applied, and a free turn lets the
program's own chains get ahead. A microtask is between — the dispatch unwinds
first, and nothing on a timer gets in front.

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

The `pty/harness.py` above points `TUI_RECORD_VERBATIM` at a scratch file
for every session a pty driver runs, and `Checks.report` runs each tape back
through the program with no terminal. **You get this too**: the harness finds
`gren-replay.js` beside itself in this package, so a test written the way the
section above shows is also a replay test, with nothing declared and nothing
installed. There is nothing to add to a driver: the
variable is the runtime's own, so fifty-odd drivers became fifty-odd replay
tests for nothing. It is **on by default** — `TVNODE_TAPES=0` turns it off — because all 37
reproduce, run after run, and it costs nothing on the clock: a replay is
milliseconds against a pty driver that is mostly asleep. Six
drivers are marked as never replayable and say why: `watch` spawns child
processes and watches a directory, `dir` lists one, `notes` reads and writes
files, `edit` saves the document it opened, `viewer` is pointed at a file
each case rewrites, and `hotkeys` opens the environment tool — whose rows
include the one variable a replay has to change, `HOME`. A driver
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

A program with a second inbound stream gets it labeled — predc's time
converter answers over `intlIn`, and two conversations printed as one would be
worse than not having teed the second onto the tape at all.

It also reports what it can tell is wrong without replaying anything: a window
the model drew with a negative origin or past the edge of the desktop, a
`readClipboard` or a `dialog` that was never answered, a crash, a truncation, a
tape that just stops, and a format or protocol older than the build reading it
— which names what the older format was missing rather than only that a number
differs.

The window check reads the rectangles on the render lines and skips any the
user dragged to, which is the correction that made it worth having. It used to
read the inbound `windowResized` messages instead, so it fired on somebody
pulling a window past an edge on purpose — Turbo Vision allows that — and could
never see the case it was written for, a rectangle the model itself chose. The
rule is the one the rest of this binding runs on: who moved the value decides
what it means.

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
