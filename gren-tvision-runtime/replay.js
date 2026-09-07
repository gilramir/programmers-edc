'use strict';

// Feeding a tape back in.
//
// `record.js` writes one and `tape.js` reads it; this runs it. The claim the
// recorder was built on is that the port boundary is total -- a Gren program
// here is a pure function of what `init` read and what arrived on `tuiIn` --
// and this is the file that either makes that true or finds out where it is
// not.
//
// **The binding is not involved.** A replay drives the compiled Gren module
// directly: subscribe to its outbound port, push the tape's messages into its
// inbound one, and compare the fingerprints. Turbo Vision is not started, no
// terminal is opened, and `diff.js` never runs -- which is not a shortcut but
// the correct boundary. What a tape records is what the *model* did; what the
// differ does with it is `diff.test.js`'s subject, against a fake binding, and
// running it here would mean answering the messages it sends back and having
// two things feeding the program at once.
//
// Three things are put back before the program starts, because they are what
// `init` reads and none of them cross a port:
//
//   - **argv**, which for predc decides whether there is a program to run at
//     all: a word its parser has never heard of is an exit rather than a
//     screen, and an empty list is the desktop rather than the help text.
//   - **the working directory and the time zone**, the second because
//     `Time.getZoneName` reads `Intl` and two of predc's tools decide what to
//     draw from the answer.
//   - **the clock**, which is not replayed from a recording of it but
//     reconstructed: `Date.now` answers with the header's instant plus the
//     stamp on the event being fed. Recording the calls would have meant
//     intercepting `Date.now` for the whole process with no way to tell the
//     program's reads from node's own.
//
// And `Time.every` is driven rather than waited for. In a replay there is no
// pump and no terminal, so every `setInterval` in the process is the Gren
// kernel's, and firing them at the virtual times they were due is both exact
// and instant -- a tape with a clock in it replays in milliseconds rather than
// in the minute it took to record.

const fs = require('fs');
const os = require('os');
const path = require('path');

const { digest, fingerprint, TAPE } = require('./record');
const { PROTOCOL } = require('./tui');

/** How long to wait for output the tape says is coming. */
const DEFAULT_TIMEOUT_MS = 5000;

/** A turn of the event loop that lets I/O run, which a microtask does not. */
function turn() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

/**
 * Where a file the recording read goes inside the replay's own directory.
 *
 * The tape has the absolute path on the recording machine, and the program
 * will look for it through whatever rule it used the first time -- which this
 * cannot know. What it can do is follow the same convention the path itself
 * announces: anything under a `.config`, `.local/share` or `.local/state`
 * directory is an XDG path, and the tail after that is what the program will
 * ask for once the matching variable points here. Anything else is a path
 * shaped by a rule this cannot guess, and saying so beats planting the file
 * somewhere the program will not look.
 */
function seedPath(recorded, scratch) {
  const marks = [
    ['/.config/', 'config'],
    ['/.local/share/', 'data'],
    ['/.local/state/', 'state'],
    ['/.cache/', 'cache'],
  ];
  for (const [mark, where] of marks) {
    const at = recorded.indexOf(mark);
    if (at >= 0) return path.join(scratch, where, recorded.slice(at + mark.length));
  }
  return null;
}


/**
 * Everything the replay changes about this process, and how to change it back.
 *
 * A replay is a program pretending to be another program on another machine,
 * and the pretence is global: `Date.now`, `setInterval`, the working
 * directory, `TZ`. All of it is undone at the end, so that a test file can
 * replay two tapes and a bin can replay one without leaving the process a
 * worse place than it found it.
 */
function install(session, options) {
  const header = session.header || {};
  const startMs = Date.parse(header.at || 0) || 0;
  const notes = [];
  const undo = [];

  let virtualNow = startMs;

  // --- the clock ---------------------------------------------------------
  //
  // The readings the program took, in the order it took them, and the virtual
  // clock underneath for when it takes one the recording did not -- which is
  // either an older tape or a program that has started asking a new question,
  // and both want an answer rather than a crash.
  // Kept with the line each was written on, and handed out by *position on the
  // tape* rather than by call number. A queue served purely in order is a
  // queue one missed reading knocks out of step for the rest of the run --
  // and a tick that fired a moment differently is exactly that missed
  // reading. Anything recorded before where the replay has got to is dropped
  // rather than handed over late.
  const readings = (session.events || [])
    .filter((e) => e.now !== undefined)
    .map((e) => ({ at: e.at, value: e.now }));
  let readAt = 0;
  const position = options.position || (() => 0);
  const realNow = Date.now;
  Date.now = () => {
    const here = position();
    while (readAt < readings.length && readings[readAt].at < here) readAt += 1;
    return readAt < readings.length ? readings[readAt++].value : virtualNow;
  };
  undo.push(() => {
    Date.now = realNow;
  });

  // --- Time.every --------------------------------------------------------
  const timers = new Map();
  let nextTimer = 1;
  const realSetInterval = global.setInterval;
  const realClearInterval = global.clearInterval;
  global.setInterval = (fn, ms, ...args) => {
    const id = { virtual: nextTimer++ };
    timers.set(id.virtual, { fn, args, ms: Math.max(1, ms || 1), due: virtualNow + Math.max(1, ms || 1) });
    return id;
  };
  global.clearInterval = (id) => {
    if (id && id.virtual !== undefined) timers.delete(id.virtual);
    else realClearInterval(id);
  };
  undo.push(() => {
    global.setInterval = realSetInterval;
    global.clearInterval = realClearInterval;
  });

  // --- the terminal ------------------------------------------------------
  //
  // `Terminal.initialize` reads four properties off `process.stdout`, and a
  // replay's stdout is a pipe: no `isTTY`, no size. Half the layout in a Turbo
  // Vision program is decided from those numbers before the first `Resized`
  // can arrive -- predc sizes its desktop from them in `init` -- so a replay
  // that let its own stdout answer would diverge on the first render and blame
  // the program.
  const term = header.terminal || {};
  const stdout = process.stdout;
  for (const [name, value] of [
    ['isTTY', !!term.isTTY],
    ['columns', term.columns || undefined],
    ['rows', term.rows || undefined],
  ]) {
    const was = Object.getOwnPropertyDescriptor(stdout, name);
    try {
      Object.defineProperty(stdout, name, { value, configurable: true, writable: true });
      undo.push(() => {
        if (was) Object.defineProperty(stdout, name, was);
        else delete stdout[name];
      });
    } catch {
      notes.push(`this process will not let ${name} be set on stdout`);
    }
  }
  const wasColorDepth = stdout.getColorDepth;
  stdout.getColorDepth = () => term.colorDepth || 0;
  undo.push(() => {
    if (wasColorDepth) stdout.getColorDepth = wasColorDepth;
    else delete stdout.getColorDepth;
  });

  // --- somewhere for the program to live ---------------------------------
  //
  // **A replay is the program, so a replay writes what the program writes.**
  // That is obvious once it has happened to you and not before: replaying a
  // session in which somebody changed a setting makes predc save the setting,
  // over yours, on a machine that was only meant to be reading a bug report.
  // It costs the user's notes as easily as their theme.
  //
  // So the default is a directory of its own, with `HOME` and the XDG
  // variables pointed into it. That is not only safer, it is *more faithful*:
  // the tape carries the file the recording read, and seeding it here means
  // `init` decides from the recording's config rather than from the config of
  // whoever is reading the tape -- which is the difference between a replay
  // that reproduces a bug and one that diverges on the first render for a
  // reason nobody can see.
  const scratch = options.inPlace ? null : fs.mkdtempSync(path.join(os.tmpdir(), 'gren-replay-'));
  if (scratch) {
    for (const [name, where] of [
      ['HOME', ''],
      ['XDG_CONFIG_HOME', 'config'],
      ['XDG_DATA_HOME', 'data'],
      ['XDG_STATE_HOME', 'state'],
      ['XDG_CACHE_HOME', 'cache'],
    ]) {
      const dir = where ? path.join(scratch, where) : scratch;
      fs.mkdirSync(dir, { recursive: true });
      const was = process.env[name];
      process.env[name] = dir;
      undo.push(() => {
        if (was === undefined) delete process.env[name];
        else process.env[name] = was;
      });
    }
    undo.push(() => fs.rmSync(scratch, { recursive: true, force: true }));
    for (const [name, value] of Object.entries(header.extra || {})) {
      if (!value || typeof value.path !== 'string' || typeof value.contents !== 'string') continue;
      const at = seedPath(value.path, scratch);
      if (!at) {
        notes.push(`the ${name} file was recorded at ${value.path}, which is not a path this can place`);
        continue;
      }
      fs.mkdirSync(path.dirname(at), { recursive: true });
      fs.writeFileSync(at, value.contents);
    }
  } else {
    notes.push('running in place: whatever the program writes, it writes for real');
  }

  // --- the environment ---------------------------------------------------
  //
  // On top of the above, so `--env HOME=...` still wins. A tape records
  // variable *names* and not values, on purpose, so this is where somebody
  // replaying a tape from another machine puts back the two or three that
  // mattered.
  for (const [name, value] of Object.entries(options.env || {})) {
    const was = process.env[name];
    process.env[name] = value;
    undo.push(() => {
      if (was === undefined) delete process.env[name];
      else process.env[name] = was;
    });
  }
  // A launcher that recorded a file it read -- as `{path, contents}` under
  // `extra`, which is predc's config -- gets it checked against what is at
  // that path now. Nothing here can put the file back: the path is the
  // recording machine's and the file is the user's. Saying so is the whole
  // job, and it is worth doing because this is the failure that looks most
  // like a bug in the program: predc reads its theme and its chart mode out
  // of that file during `init`, so a stale copy diverges on the first render
  // with nothing on the tape to suggest why.
  for (const [name, value] of Object.entries(options.inPlace ? header.extra || {} : {})) {
    if (!value || typeof value.path !== 'string' || value.contents === undefined) continue;
    let onDisk = null;
    try {
      onDisk = require('fs').readFileSync(value.path, 'utf8');
    } catch {
      onDisk = null;
    }
    if (onDisk !== value.contents) {
      notes.push(
        `the ${name} file the recording read (${value.path}) is ${onDisk === null ? 'not here' : 'different here'}` +
          ', and whatever the program decided from it will differ'
      );
    }
  }

  const missing = (header.envNames || []).filter((n) => process.env[n] === undefined);
  if (missing.length) {
    notes.push(
      `${missing.length} of the ${header.envNames.length} variables the recording had are not set here` +
        ' (a tape keeps names, never values -- use --env NAME=VALUE for the ones that matter)'
    );
  }

  // --- the zone, the directory, the arguments ----------------------------
  const zone = header.runtime && header.runtime.timeZone;
  if (zone) {
    const wasTZ = process.env.TZ;
    process.env.TZ = zone;
    undo.push(() => {
      if (wasTZ === undefined) delete process.env.TZ;
      else process.env.TZ = wasTZ;
    });
  } else {
    notes.push('the tape does not say what zone the machine was in, so this one\'s is used');
  }

  const wasCwd = process.cwd();
  const cwd = header.program && header.program.cwd;
  if (cwd) {
    try {
      process.chdir(cwd);
      undo.push(() => process.chdir(wasCwd));
    } catch (err) {
      notes.push(`the recording ran in ${cwd}, which is not here: ${err.code || err.message}`);
    }
  }

  const wasArgv = process.argv;
  if (header.program && header.program.argv) {
    // `process.argv` without the interpreter is what the recorder kept, and
    // `Node.Environment.args` is read when `init` runs rather than when the
    // module loads, so putting it back here is early enough.
    process.argv = [wasArgv[0], ...header.program.argv];
    undo.push(() => {
      process.argv = wasArgv;
    });
  }

  // --- the draws ---------------------------------------------------------
  const draws = (session.events || []).filter((e) => e.rng !== undefined);
  const queue = draws.slice();
  let withheldServed = 0;
  const nextDraw = (kind) => {
    while (queue.length && queue[0].rng !== kind) queue.shift();
    return queue.length ? queue.shift() : null;
  };

  const proto = (() => {
    try {
      return Object.getPrototypeOf(require('crypto').webcrypto);
    } catch {
      return null;
    }
  })();
  if (proto && typeof proto.getRandomValues === 'function') {
    const real = proto.getRandomValues;
    proto.getRandomValues = function (array) {
      const draw = nextDraw('getRandomValues');
      const bytes = draw && draw.value ? Buffer.from(draw.value, 'base64') : null;
      const view = new Uint8Array(array.buffer, array.byteOffset, array.byteLength);
      if (bytes) {
        view.set(bytes.subarray(0, view.length));
      } else {
        // Zeroes rather than real randomness, deliberately: a redacted tape
        // cannot reproduce the draw, and a replay that filled it with fresh
        // bytes would diverge differently every time it was run. This way the
        // divergence is the same one twice and the report can name its cause.
        view.fill(0);
        withheldServed += 1;
      }
      return array;
    };
    undo.push(() => {
      proto.getRandomValues = real;
    });
  }

  const crypto = require('crypto');
  if (typeof crypto.randomUUID === 'function') {
    const real = crypto.randomUUID;
    crypto.randomUUID = function (...args) {
      const draw = nextDraw('randomUUID');
      if (draw && draw.value) return Buffer.from(draw.value, 'base64').toString('utf8');
      withheldServed += 1;
      return '00000000-0000-4000-8000-000000000000';
    };
    undo.push(() => {
      crypto.randomUUID = real;
    });
  }

  return {
    notes,
    startMs,
    draws,
    get clockReadings() {
      return readings.length;
    },
    get clockServed() {
      return readAt;
    },
    get withheldServed() {
      return withheldServed;
    },
    /**
     * Move the clock to `t` without firing anything.
     *
     * Used before each message goes in, so that a `Time.now` inside the update
     * answers with what it answered then.
     */
    clockAt(t) {
      virtualNow = startMs + t;
    },

    /**
     * Fire one due timer, as of `t`.
     *
     * **The tape says when a tick happened, and that is better than working it
     * out.** A `Time.every 1000` does not fire on the thousand: the recording
     * has its ticks at 1017, 2017, 3018, and a replay that fired its own at
     * 1000, 2000, 3000 draws a clock one second out the moment the offset
     * crosses a boundary -- and, worse, fires ticks in places the recording
     * has none, because a timer due at 42032 is due whether or not the program
     * was awake for it.
     *
     * So a tick is fired only where the tape has a render with no message
     * under it, and the clock is set to *that render's* stamp before it goes.
     * The interval arithmetic decides which timer, and the tape decides when.
     *
     * Synchronous, because it is called from the driver's pump, which is
     * called from inside a port subscription: a tick's render comes back
     * through the same subscription and is matched like any other.
     */
    tickAt(t) {
      virtualNow = startMs + t;
      let soonest = null;
      for (const [, timer] of timers) {
        if (!soonest || timer.due < soonest.due) soonest = timer;
      }
      if (!soonest) return false;
      // Fired whether or not the arithmetic says it is due, because the tape
      // says it is: the caller only asks when the program has gone quiet with
      // an unexplained render still expected, and a recording's ticks are 1016
      // and 2015 apart rather than 1000 and 2000. Holding a timer to its own
      // sums against a stamp somebody else wrote is how a replay stalls one
      // millisecond short of a tick.
      soonest.due = virtualNow + soonest.ms;
      try {
        soonest.fn(...(soonest.args || []));
      } catch {
        /* a tick that throws is the program's business, and the divergence
           that follows is what says so */
      }
      return true;
    },
    undo() {
      while (undo.length) undo.pop()();
    },
  };
}

/**
 * The tape as a list of things to do, in order.
 *
 * An inbound message is something to send; an outbound one is something to
 * expect. Everything else -- a note, a draw, the end -- is context the driver
 * walks past, having already taken what it needed from it.
 */
function script(session) {
  const steps = [];
  for (const ev of session.events || []) {
    if (ev.in) steps.push({ kind: 'send', t: ev.t, at: ev.at, message: ev.in, port: ev.port });
    else if (ev.out) steps.push({ kind: 'expect', t: ev.t, at: ev.at, expected: ev, port: ev.port });
    else if (ev.end !== undefined) steps.push({ kind: 'end', t: ev.t, at: ev.at, reason: ev.end });
  }
  return steps;
}

/** Which port a message recorded under this label goes back into. */
function inboundPort(label) {
  return label ? `${label}In` : 'tuiIn';
}

function outboundPort(label) {
  return label ? `${label}Out` : 'tuiOut';
}

/** Two fingerprints differ, and this says how, in a sentence. */
function difference(expected, actual) {
  if (!actual) return `the program produced nothing`;
  if (expected.out !== actual.out) return `expected ${expected.out}, got ${actual.out}`;
  if (expected.out === 'render') {
    if (expected.hash !== actual.hash) {
      const windows = (actual.windows || []).join(', ') || 'none';
      const was = (expected.windows || []).join(', ') || 'none';
      return `the render differs: ${expected.hash} on the tape, ${actual.hash} here` +
        (was === windows ? ` (both drew ${windows || 'nothing'})` : ` (tape drew ${was}, this drew ${windows})`);
    }
    return null;
  }
  if (expected.id !== actual.id) return `${expected.out} named ${expected.id} on the tape and ${actual.id} here`;
  return null;
}

/**
 * Run a tape against a compiled Gren module.
 *
 * **The tape drives itself, through the program's own output.** That is the
 * whole design and it took a wrong one to find it. The obvious driver feeds a
 * message, waits, checks what came back, feeds the next -- and it cannot
 * reproduce a tape, because a tape's order is not the program's. `predc time`
 * proved it in four lines: the terminal's first `resized` arrived *between*
 * two steps of `init`'s own chain, after its first render and before it asked
 * node for the time zones. Feeding that resize a moment later -- which is all
 * "wait, then send" can do -- puts the program in a state the recording never
 * had, and every render after it differs for a reason that is not a bug.
 *
 * So: one cursor over the tape. An outbound message is matched against what
 * the cursor points at and steps it forward; an inbound message is sent the
 * instant the cursor reaches it, from inside the subscription that moved it
 * there. The program's own output is the clock the messages are fed by, which
 * is the only clock both runs share.
 *
 * @param grenModule  what `gren make Main --output=main.js` produced
 * @param session     one entry from `tape.read().sessions`
 */
async function replay(grenModule, session, options = {}) {
  const header = session.header || {};
  const timeoutMs = options.timeoutMs || DEFAULT_TIMEOUT_MS;
  const warnings = [];

  if (header.tape !== TAPE) warnings.push(`tape format ${header.tape}, this build reads ${TAPE}`);
  if (header.protocol !== undefined && header.protocol !== PROTOCOL) {
    warnings.push(
      `the tape speaks protocol ${header.protocol} and this build speaks ${PROTOCOL}: ` +
        'a divergence here is two different programs, not a bug'
    );
  }

  // Where on the tape the replay has got to, which the clock needs: see
  // `install`.
  let atLine = 0;
  const stage = install(session, { ...options, position: () => atLine });
  warnings.push(...stage.notes);
  const withheldDraws = stage.draws.filter((d) => d.value === undefined).length;
  if (withheldDraws) {
    warnings.push(
      `${withheldDraws} random draw(s) were withheld from this tape, so anything drawn from ` +
        'them diverges here -- record with --record-verbatim to reproduce those'
    );
  }

  try {
    const namespace = grenModule.Gren || grenModule;
    const moduleName = options.moduleName || Object.keys(namespace)[0];
    const flags = options.flags || (header.program && header.program.flags) || {};
    const app = namespace[moduleName].init({ flags });
    if (!app.ports || !app.ports.tuiIn || !app.ports.tuiOut) {
      throw new Error('the program declares no tuiIn/tuiOut: it is not a gren-tvision program');
    }

    const steps = script(session);
    let cursor = 0;
    let matched = 0;
    let lastSent = null;
    let divergence = null;
    let done = false;
    const extra = [];

    const stop = (why, step, actual) => {
      if (divergence) return;
      divergence = { step, after: lastSent, why, actual };
      done = true;
    };

    /** Feed everything the cursor is standing on, until it wants output. */
    const pump = () => {
      while (!done && cursor < steps.length) {
        const step = steps[cursor];
        if (step.kind === 'end') {
          cursor += 1;
          done = true;
          return;
        }
        if (step.kind !== 'send') return;
        cursor += 1;
        lastSent = step;
        atLine = step.at;
        stage.clockAt(step.t);
        const name = inboundPort(step.port);
        if (!app.ports[name]) {
          stop(`the program has no ${name} port to send this to`, step);
          return;
        }
        if (options.trace) options.trace('<-', step.port || 'tui', { in: step.message.type, at: step.at });
        app.ports[name].send(step.message);
      }
      done = true;
    };

    /**
     * How far ahead an outbound message may be matched: to the next message
     * going *in*, and no further.
     *
     * An inbound message is a barrier -- nothing recorded after it can have
     * been produced before it was sent -- and between two of them the order of
     * two *different* ports is not the program's. `predc time` shows both
     * orderings on two tapes of the same session: init's request to node for
     * the time zones lands either side of the render the terminal's first
     * resize produced, depending on which of two chains the recording machine
     * finished first. Asserting on that is asserting on somebody's disk.
     *
     * Within one port the order is asserted, and it is the whole check.
     */
    const barrier = (from) => {
      let i = from;
      while (i < steps.length && steps[i].kind === 'expect') i += 1;
      return i;
    };

    const observe = (label) => (message) => {
      const actual = fingerprint(message);
      if (options.trace) options.trace('->', label || 'tui', actual);
      if (divergence) return;
      const port = label || 'tui';
      const end = barrier(cursor);
      // By type first, and only then by position. Between two inputs a model
      // may emit a render and a `focus` in either order -- they are one
      // `Cmd.batch` on one port, and which of them the recorder saw first is
      // not something a tape can hold anybody to. What it *can* hold them to
      // is that both happened, that there were exactly this many of each, and
      // that the renders were these renders.
      let found = -1;
      let fallback = -1;
      for (let i = cursor; i < end; i += 1) {
        if (steps[i].done || (steps[i].port || 'tui') !== port) continue;
        if (steps[i].expected.out === actual.out) {
          found = i;
          break;
        }
        if (fallback < 0) fallback = i;
      }
      if (found < 0) found = fallback;
      if (found < 0) {
        // Nothing on this port was expected here. After the tape's last step
        // that is ordinary -- the recorder's `end` line is written as the
        // process leaves, and whatever the program said on the way out was
        // never written down.
        extra.push({ ...actual, port, afterEnd: cursor >= steps.length });
        return;
      }
      const why = difference(steps[found].expected, actual);
      if (why) {
        stop(why, steps[found], actual);
        return;
      }
      steps[found].done = true;
      atLine = steps[found].at;
      matched += 1;
      while (cursor < steps.length && steps[cursor].kind === 'expect' && steps[cursor].done) {
        cursor += 1;
      }
      pump();
    };

    // Every port the tape mentions, not only `tuiOut`: a program with a stream
    // of its own recorded it under a label, and a replay deaf to that one
    // would report its messages as missing.
    const labels = new Set([undefined, ...(session.events || []).map((e) => e.port).filter(Boolean)]);
    for (const label of labels) {
      const name = outboundPort(label);
      if (app.ports && app.ports[name]) app.ports[name].subscribe(observe(label));
      else if (label) warnings.push(`the tape has ${label} messages on it and the program has no ${name} port`);
    }

    pump();
    const started = process.hrtime.bigint();
    let was = cursor;
    let idle = 0;
    while (!done) {
      if (Number(process.hrtime.bigint() - started) / 1e6 > timeoutMs) {
        const want = steps[cursor];
        stop(
          want && want.kind === 'expect'
            ? `${difference(want.expected, null)} in ${timeoutMs}ms`
            : 'the program stopped before the tape did',
          want
        );
        break;
      }
      await turn();
      if (cursor !== was) {
        was = cursor;
        idle = 0;
        continue;
      }
      // Two quiet turns, not one: a program waiting on a file read is quiet
      // too, and firing a tick into that would put a render where the tape has
      // none.
      idle += 1;
      if (idle < 2) continue;
      idle = 0;
      // Nothing arrived, and the tape says something should have. A render
      // with no message under it is a `Time.every` tick, so one is fired, at
      // the moment the tape stamped it. A replay that waited for the wall
      // instead would take as long as the recording did, which for a tool with
      // a clock in it is the difference between a test and an afternoon.
      const want = steps[cursor];
      if (want && want.kind === 'expect') {
        atLine = want.at;
        stage.tickAt(want.t);
      }
    }
    // A last turn or two, so that anything the program was about to say is
    // said before the extras are counted.
    await turn();
    await turn();

    const unexpected = extra.filter((e) => !e.afterEnd);
    if (extra.length > unexpected.length) {
      warnings.push(
        `${extra.length - unexpected.length} message(s) came after the tape's last line, ` +
          'which is where a recorder stops rather than where a program does'
      );
    }

    return {
      ok: !divergence && !unexpected.length && cursor >= steps.length,
      matched,
      total: steps.filter((s) => s.kind === 'expect').length,
      divergence,
      extra: unexpected,
      warnings,
      withheldServed: stage.withheldServed,
    };
  } finally {
    stage.undo();
  }
}

module.exports = { replay, script, install, difference, digest };
