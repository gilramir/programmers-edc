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

/**
 * The last resort, for a program that has genuinely stopped.
 *
 * Generous on purpose. Waiting is no longer how the driver decides anything --
 * `working` answers that, and an expectation nothing is coming for is set
 * aside rather than waited on -- so this only fires for a program stuck for
 * good, and a replay that has finished exits the moment it does. Five seconds
 * was enough on an idle machine and not with sixteen drivers running, which is
 * the last place the wall clock could still change the answer.
 */
const DEFAULT_TIMEOUT_MS = 10000;



/** A turn of the event loop that lets I/O run, which a microtask does not. */
function turn() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

/**
 * Is the program still working?
 *
 * The driver has to decide "there is nothing more coming" before it fires a
 * tick, and the only way to ask an async runtime that used to be to wait a
 * while -- which makes the answer depend on how busy the machine is, and a
 * replayer whose result depends on the load reports races it invented. This is
 * the question asked properly: `process.getActiveResourcesInfo` is node's own
 * list of what is outstanding, and during a replay it is `PipeWrap` twice for
 * stdio and nothing else when the program has stopped. A file read in flight
 * shows as `FSReqCallback`; a `Process.sleep` or anything else waiting on a
 * real timer shows as `Timeout`. `Time.every` shows as neither, because a
 * replay's intervals are virtual -- which is exactly the distinction wanted.
 */
function working() {
  for (const resource of process.getActiveResourcesInfo()) {
    if (resource === 'FSReqCallback' || resource === 'Timeout') return true;
  }
  return false;
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
function seedPath(recorded, roots) {
  const marks = [
    ['/.config/', 'config'],
    ['/.local/share/', 'data'],
    ['/.local/state/', 'state'],
    ['/.cache/', 'cache'],
  ];
  for (const [mark, kind] of marks) {
    const at = recorded.indexOf(mark);
    if (at >= 0) return path.join(roots[kind], recorded.slice(at + mark.length));
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
  // Handed out in order, one per call, with the virtual clock underneath for
  // a call the recording did not make.
  //
  // In order is right *because* the ticks are fired from the tape rather than
  // from arithmetic: the program asks for the clock exactly as often as it did
  // when this was recorded, so the queue cannot get out of step. It used to be
  // handed out by position on the tape instead, to resynchronise after a tick
  // that fired a moment differently -- and that was the thing stopping predc's
  // time converter from replaying, because a reading its `init` took before
  // the first render was thrown away when the program asked for it a moment
  // later than the recording did. The compensation outlived the problem.
  const readings = (session.events || [])
    .filter((e) => e.now !== undefined)
    .map((e) => e.now);
  let readAt = 0;
  const realNow = Date.now;
  Date.now = () => (readAt < readings.length ? readings[readAt++] : virtualNow);
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
  // Where each kind of file goes inside it. An XDG variable is set only when
  // the recording had one: **a variable the replay invents is a variable on
  // the screen**, and predc's environment tool draws the lot -- so a sandbox
  // that helpfully exported `XDG_CACHE_HOME` made that tool's render differ
  // for a reason that had nothing to do with the program. Where the recording
  // had none, the file goes where the program's own default rule will look for
  // it, under the scratch `HOME`.
  const had = new Set(header.envNames || []);
  const roots = {};
  if (scratch) {
    for (const [name, kind, fallback] of [
      ['XDG_CONFIG_HOME', 'config', '.config'],
      ['XDG_DATA_HOME', 'data', '.local/share'],
      ['XDG_STATE_HOME', 'state', '.local/state'],
      ['XDG_CACHE_HOME', 'cache', '.cache'],
    ]) {
      roots[kind] = path.join(scratch, had.has(name) ? kind : fallback);
      if (!had.has(name)) continue;
      const was = process.env[name];
      process.env[name] = roots[kind];
      undo.push(() => {
        if (was === undefined) delete process.env[name];
        else process.env[name] = was;
      });
    }
    const wasHome = process.env.HOME;
    process.env.HOME = scratch;
    undo.push(() => {
      if (wasHome === undefined) delete process.env.HOME;
      else process.env.HOME = wasHome;
    });
    undo.push(() => fs.rmSync(scratch, { recursive: true, force: true }));
    for (const [name, value] of Object.entries(header.extra || {})) {
      if (!value || typeof value.path !== 'string' || typeof value.contents !== 'string') continue;
      const at = seedPath(value.path, roots);
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

  // And the other way round, which is the one that shows on a screen: predc's
  // environment tool draws what it was given, so a variable this replay
  // invented is a difference the program is right about and the tape cannot
  // explain.
  const invented = Object.keys(process.env).filter((n) => !had.has(n));
  if (had.size && invented.length) {
    notes.push(
      `${invented.length} variable(s) are set here that the recording did not have ` +
        `(${invented.slice(0, 4).join(', ')}${invented.length > 4 ? ', …' : ''}), which a ` +
        'program that draws its own environment will draw'
    );
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
    tickAt(t, interval) {
      virtualNow = startMs + t;
      let soonest = null;
      for (const [, timer] of timers) {
        // By interval when the tape says which -- a program with two
        // `Time.every` subscriptions has two timers, and the tape knows which
        // of them went off.
        if (interval !== undefined && timer.ms !== interval) continue;
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
 * An inbound message is something to send, an outbound one is something to
 * expect, and a tick is a timer to fire. Everything else -- a note, a draw --
 * is context the driver walks past, having already taken what it needed.
 */
function script(session) {
  const steps = [];
  for (const ev of session.events || []) {
    if (ev.in) steps.push({ kind: 'send', t: ev.t, at: ev.at, message: ev.in, port: ev.port });
    else if (ev.out) steps.push({ kind: 'expect', t: ev.t, at: ev.at, expected: ev, port: ev.port });
    else if (ev.tick !== undefined) {
      steps.push({ kind: 'tick', t: ev.t, at: ev.at, interval: ev.tick });
    } else if (ev.end !== undefined) {
      steps.push({ kind: 'end', t: ev.t, at: ev.at, reason: ev.end });
    }
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

  // Where on the tape the replay has got to, which the tick test needs: a
  // reading between here and the render being waited for is what says that
  // render is a timer going off. It moves only at an inbound message, which is
  // the only barrier there is.
  let atLine = 0;
  // The lines the program's readings of the clock were written on. Used to
  // tell a tick from the second render of one update: see the wait loop.
  const readingLines = (session.events || [])
    .filter((e) => e.now !== undefined)
    .map((e) => e.at);
  const readAfter = (from, before) => readingLines.some((l) => l > from && l < before);
  const hasTicks = (session.events || []).some((e) => e.tick !== undefined);
  const stage = install(session, options);
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
    // The screen as the replay last agreed it was, and how many repeats of it
    // went past on each side.
    let lastHash = null;
    let repeats = 0;
    // Expectations met later than the tape has them. A `Cmd` that resolves
    // through a Task comes out a few milliseconds after the render beside it,
    // and once that happens the two are matched out of order rather than
    // called a difference -- see the wait loop.
    const deferred = [];
    let done = false;
    // The tape's last line reached, which is not the same as being finished: a
    // message set aside earlier may still be on its way, and stopping at the
    // `end` line with one outstanding is how a `Cmd` that resolves four
    // milliseconds after the render beside it gets reported as never having
    // arrived at all.
    let ended = false;
    const allMet = () => !deferred.some((i) => !steps[i].done);
    const extra = [];

    const stop = (why, step, actual) => {
      if (divergence) return;
      divergence = { step, after: lastSent, why, actual };
      done = true;
    };

    /** Feed the message at `from`, stepping the cursor over it. */
    const pumpFrom = (from) => {
      const step = steps[from];
      if (!step || step.kind !== 'send' || step.done) return;
      step.done = true;
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
    };

    /** Feed everything the cursor is standing on, until it wants output. */
    const pump = () => {
      while (!done && cursor < steps.length) {
        const step = steps[cursor];
        if (step.kind === 'end') {
          cursor += 1;
          ended = true;
          done = allMet();
          return;
        }
        // A tick is fired rather than waited for, because the program can
        // never produce one on its own: the timer belongs to the driver. The
        // tape says exactly where each went off, so there is nothing to infer
        // and nothing to wait for.
        if (step.kind === 'tick') {
          cursor += 1;
          if (step.done) continue;
          step.done = true;
          stage.tickAt(step.t, step.interval);
          continue;
        }
        if (step.kind !== 'send') return;
        cursor += 1;
        if (step.done) continue;
        step.done = true;
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
      ended = true;
      done = allMet();
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
      // **A render identical to the one before it is a no-op**, and how many
      // of them a run produces is not the program's behaviour: the differ
      // patches nothing for the second, and a screen cannot tell them apart.
      // They differ between runs because a message can land either side of a
      // Task's continuation -- `predc random` draws its bytes, and whether the
      // terminal's first resize arrives before or after the draw comes back
      // decides whether the resize redraws the old page or the new one. So a
      // repeat is skipped on the way in, and, in the wait loop, on the way out
      // of the tape.
      if (actual.out === 'render' && actual.hash === lastHash) {
        const end = barrier(cursor);
        const wanted = steps
          .slice(cursor, end)
          .some((step) => !step.done && (step.port || 'tui') === port &&
            step.expected.out === 'render' && step.expected.hash === actual.hash);
        if (!wanted) {
          repeats += 1;
          return;
        }
      }
      // Anything set aside earlier, first: it was expected before this and is
      // still expected.
      for (const i of deferred) {
        const step = steps[i];
        if (step.done || (step.port || 'tui') !== port) continue;
        if (step.expected.out !== actual.out) continue;
        if (actual.out === 'render' && step.expected.hash !== actual.hash) continue;
        step.done = true;
        if (actual.out === 'render') lastHash = actual.hash;
        matched += 1;
        if (ended) done = allMet();
        pump();
        return;
      }

      const end = barrier(cursor);
      // The tape's own repeats, walked past for the same reason: a render it
      // has twice and the program only drew once is two of the same screen,
      // and nothing downstream can tell. Only ones that are not what just
      // arrived -- an actual repeat the program *did* make matches here.
      for (let i = cursor; i < end; i += 1) {
        const step = steps[i];
        if (step.done) continue;
        if ((step.port || 'tui') !== port) continue;
        if (step.expected.out !== 'render') break;
        if (step.expected.hash !== lastHash || step.expected.hash === actual.hash) break;
        step.done = true;
        repeats += 1;
      }
      while (cursor < steps.length && steps[cursor].kind === 'expect' && steps[cursor].done) {
        cursor += 1;
      }
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
      // One step past the barrier, and only for an exact match. A `Cmd` that
      // resolves through a Task comes out a few milliseconds after the render
      // beside it, and the terminal's next message lands in between -- so the
      // tape has a message going *in* between two things one update sent out.
      // Sending that message early is safe when what has just arrived is
      // exactly what the tape has on the other side of it: the terminal did
      // not wait for us either.
      if (found < 0 && end < steps.length && steps[end].kind === 'send') {
        for (let i = end + 1; i < steps.length && steps[i].kind === 'expect'; i += 1) {
          const step = steps[i];
          if (step.done || (step.port || 'tui') !== port) continue;
          if (step.expected.out !== actual.out) continue;
          if (actual.out === 'render' && step.expected.hash !== actual.hash) continue;
          // Marked before the message goes in, not after: sending it runs the
          // program, which can call straight back into here, and a step still
          // open at that moment is a step that gets matched twice.
          step.done = true;
          if (actual.out === 'render') lastHash = actual.hash;
          matched += 1;
          deferred.push(i);
          pumpFrom(end);
          // And on with the rest: the cursor is still standing behind the
          // message that was just sent out of turn, and nothing else moves it.
          pump();
          return;
        }
      }

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
      if (actual.out === 'render') lastHash = actual.hash;
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
    let waited = 0;
    while (!done) {
      if (Number(process.hrtime.bigint() - started) / 1e6 > timeoutMs) {
        // Something set aside and never met is the better thing to report:
        // the cursor by then is wherever the conversation carried on to.
        const want = deferred.map((i) => steps[i]).find((step) => !step.done) || steps[cursor];
        stop(
          want && want.kind === 'expect'
            ? `${difference(want.expected, null)} at all`
            : 'the program stopped before the tape did',
          want
        );
        break;
      }
      // Everything fed, and only messages set aside still outstanding: give
      // the program a moment and then say which one never came.
      if (done) break;
      await turn();
      if (cursor !== was) {
        was = cursor;
        idle = 0;
        waited = 0;
        continue;
      }
      waited += 1;
      // Quiet means node says nothing is outstanding, not that some number of
      // milliseconds went by: see `working`. A few such turns rather than one,
      // since a task can sit between its resolution and its continuation with
      // nothing outstanding to show for it.
      if (working()) {
        idle = 0;
        continue;
      }
      idle += 1;
      if (idle < 5) continue;
      // Nothing arrived, and the tape says something should have. A render
      // with no message under it is a `Time.every` tick, so one is fired, at
      // the moment the tape stamped it. A replay that waited for the wall
      // instead would take as long as the recording did, which for a tool with
      // a clock in it is the difference between a test and an afternoon.
      // The position is *not* moved to the render being waited for. A tick
      // reads the clock and then renders, so its reading is written on the
      // line before the render's -- moving up to the render first throws that
      // reading away and hands the tick the next one, which is a second later
      // and a clock a second wrong for the rest of the run.
      //
      // And only a render the tape says *is* a tick. `demo` renders twice for
      // one message, a millisecond apart, and a replay that fired a tick while
      // waiting for the second of them put a clock a second on where the
      // recording had none, and then blamed the program for the difference.
      // The tape tells the two apart, and not by how long the gap is -- a tick
      // eight milliseconds after a resize is still a tick. **Every tick reads
      // the clock before it renders**, because that is how `Time.every` builds
      // the `Posix` it hands over, so a reading between here and the render
      // being waited for is what says this one was a timer going off.
      const want = steps[cursor];
      // The cursor can be left standing on a message already sent out of turn
      // by the lookahead above. Stepping over it is `pump`'s job, and nothing
      // has called it since.
      if (want && want.kind !== 'expect') {
        pump();
        continue;
      }
      if (!want) continue;
      // The other half of the no-op rule: the tape has a render the program
      // did not repeat here. Nothing on a screen distinguishes them, so it is
      // walked past rather than waited for.
      if (want.expected.out === 'render' && want.expected.hash === lastHash) {
        want.done = true;
        repeats += 1;
        cursor += 1;
        while (cursor < steps.length && steps[cursor].kind === 'expect' && steps[cursor].done) {
          cursor += 1;
        }
        pump();
        continue;
      }
      // Only for a tape written before ticks were recorded: on one of those
      // the clock reading a tick takes is the only sign it went off.
      if (!hasTicks && readAfter(atLine, want.at)) {
        // Reset, so that a tape wanting two ticks in a row gets two: each
        // stall fires one, and a `Time.every` with more than one interval on
        // it can need several before the render the tape has comes out.
        idle = 0;
        stage.tickAt(want.t);
        continue;
      }

      // Setting an expectation aside is the one decision here that cannot be
      // taken back, so it waits for both answers: node saying nothing is
      // outstanding, *and* a good many turns since anything last moved.
      // Waiting longer than necessary only costs time, and only in the one
      // place this is reached; setting one aside a moment too early costs the
      // match, and then reports the message as never arriving at all.
      if (waited < 30) continue;
      waited = 0;

      // Not a tick, and node says there is nothing outstanding: the program
      // has said everything it is going to say, and the tape still has a
      // message it has not. **That is an ordering, not an absence.** predc's
      // time converter records in two shapes on the same session -- the
      // render its first `resized` produces comes out either before the
      // request it sends node for the zones or after the answer -- because a
      // `Task` issued from `init` resolves where it likes against messages
      // arriving from a terminal. Both are the same renders in a different
      // order.
      //
      // So the expectation is set aside rather than waited for: the
      // conversation carries on, it stays matchable, and one still set aside
      // at the end is a real absence rather than a late arrival.
      idle = 0;
      deferred.push(cursor);
      cursor += 1;
      while (cursor < steps.length && steps[cursor].kind === 'expect' && steps[cursor].done) {
        cursor += 1;
      }
      pump();
    }
    // A last turn or two, so that anything the program was about to say is
    // said before the extras are counted.
    await turn();
    await turn();

    // Anything set aside and never met is an absence rather than a difference,
    // and it is reported as the first one.
    if (!divergence) {
      const missing = deferred.map((i) => steps[i]).find((step) => !step.done);
      if (missing) {
        stop(`${difference(missing.expected, null)} at all`, missing);
      }
    }

    const unexpected = extra.filter((e) => !e.afterEnd);
    if (repeats) {
      warnings.push(
        `${repeats} render(s) that repeated the screen already drawn were passed over on ` +
          'one side or the other: how many of those a run makes is not the program'
      );
    }
    if (extra.length > unexpected.length) {
      warnings.push(
        `${extra.length - unexpected.length} message(s) came after the tape's last line, ` +
          'which is where a recorder stops rather than where a program does'
      );
    }

    return {
      ok:
        !divergence &&
        !unexpected.length &&
        steps.every((step) => step.kind !== 'expect' || step.done),
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
