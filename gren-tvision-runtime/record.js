'use strict';

// The tape: a recording of everything that crossed the port boundary, written
// so that somebody who hit a bug can mail you the file instead of describing
// what they saw.
//
// The reason this is worth more than a log is that the boundary is *total*. A
// Gren program here is a pure function of what `init` read and what arrived on
// `tuiIn`; it cannot reach the terminal, the clock or the disk except through a
// port. So a file with the header and the inbound messages in it is not an
// account of what happened, it is the input that made it happen -- and phase
// two is a replayer that feeds it back into a fresh `main.js` and gets the same
// program, on your machine, without anybody having had to describe anything.
//
// Three decisions follow from that and none of them are obvious:
//
//   - **Renders are not recorded, only fingerprinted.** They are the *output*,
//     and a replayer regenerates them; keeping them would be keeping the
//     answer next to the question. They are also enormous -- predc's idle
//     render is 4.0 KB of JSON and one open window is 7.0 KB, and a render
//     fires per `Time.every` tick, so an open clock is 4 KB a second for as
//     long as the program is up. The hash is what makes a replay checkable:
//     the same tape through the same build must produce the same fingerprints,
//     and the first one that differs is where to look.
//
//   - **A render carries whatever the tools are showing**, which for predc
//     means the user's environment block. `AWS_SECRET_ACCESS_KEY=hunter2` is in
//     the render payload of `predc env` verbatim -- measured, not assumed. A
//     recorder that logged renders would be a recorder that mails you other
//     people's credentials, and that is the whole argument above restated as a
//     rule rather than as an efficiency.
//
//   - **Inbound is not innocent either.** `editorText` is a whole notes
//     document and `clipboardText` is whatever was on the clipboard, so both
//     are reduced to a length and a hash unless the tape was asked for
//     verbatim. Keystrokes cannot be redacted without destroying the point, so
//     they are kept and the program says so on the way out: the user is told
//     the file has everything they typed in it, and told to look before
//     sending. That notice is not decoration. It is the thing that makes the
//     feature honest.
//
// The format is JSON lines. First line is the header, every line after it is
// one event. It is meant to be read with `grep` and `jq` and by us.

const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

// The clock as it was before anything here touched it. Every stamp this file
// writes goes through it, so that a recorder which is *watching* `Date.now`
// does not record its own looking.
const realNow = Date.now;

/** Bumped when a reader would get the wrong answer from an older tape. */
const TAPE = 6;

/** Stop before filling somebody's disk. The header says when this happened. */
const MAX_BYTES = 16 * 1024 * 1024;

// Environment variables whose *value* is worth having and cannot be a secret.
// Everything else is recorded by name only: which variables exist is often the
// answer ("no COLORTERM") and what is in them never is.
const SAFE_ENV = [
  'COLORFGBG',
  'COLORTERM',
  'LANG',
  'LC_ALL',
  'LC_CTYPE',
  'NO_COLOR',
  'SHELL',
  'STY',
  'TERM',
  'TERM_PROGRAM',
  'TERM_PROGRAM_VERSION',
  'TMUX',
  'TZ',
  'VTE_VERSION',
  'WSL_DISTRO_NAME',
  'XDG_SESSION_TYPE',
];

// Inbound messages that carry a document rather than a gesture, and the field
// the document is in. These are what `verbatim` is about.
const BULK = {
  clipboardText: 'text',
  editorText: 'text',
};

/** What `Intl` says this machine's zone is, or null on a runtime without it. */
function zoneName() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

/** Short, stable, and says nothing about the content. */
function digest(text) {
  return crypto.createHash('sha256').update(String(text)).digest('hex').slice(0, 16);
}

/**
 * A copy of `message` with any document in it replaced by its shape.
 *
 * Returns the message itself when there is nothing to withhold, which is the
 * common case -- a key, a click, a command -- so the ordinary event costs one
 * property lookup rather than a clone.
 */
function redact(message) {
  const field = message && BULK[message.type];
  if (!field || typeof message[field] !== 'string') return message;
  return {
    ...message,
    [field]: undefined,
    withheld: { field, chars: message[field].length, sha: digest(message[field]) },
  };
}

/**
 * What an outbound message looks like on a tape.
 *
 * Its own function because a replayer has to produce exactly this from a
 * message the program just sent, and compare it against what the tape has. Two
 * spellings of the same rule, in two files, is the shape of a bug that reports
 * a divergence nobody can find.
 */
function fingerprint(message) {
  const type = message && message.type;
  const record = { out: type };
  if (type === 'render') {
    record.hash = digest(JSON.stringify(message));
    record.windows = (message.windows || []).map((w) => w.id);
    record.overlays = (message.overlays || []).length;
  } else if (message && message.id !== undefined) {
    record.id = message.id;
  } else if (message && message.spec && message.spec.id !== undefined) {
    record.id = message.spec.id;
  }
  return record;
}

/**
 * Leave the terminal the way TVision found it.
 *
 * The binding already does this on every path it controls: a callback that
 * throws synchronously is caught in C++, which shuts the application down and
 * rethrows *once the terminal is restored*, so `onError` runs on a terminal
 * that is already back. What it does not control is an exception from
 * somewhere else entirely -- a `setTimeout` in application code, the Gren
 * runtime's own scheduler -- which kills the process with the alternate screen
 * still up and the cursor still hidden, and the user sees a hang.
 *
 * These are the modes that matter, and every one of them is a no-op if it was
 * not set, which is what makes it safe to write them blind from a handler that
 * is already unwinding.
 */
function restoreTerminal() {
  try {
    fs.writeSync(
      1,
      '\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1015l' + // mouse reporting
        '\x1b[?2004l' + // bracketed paste
        '\x1b[?1049l' + // alternate screen
        '\x1b[0m\x1b[?25h' // attributes, cursor
    );
  } catch {
    /* stdout is gone; nothing to restore it for */
  }
}

/** What an Error looks like on a line of JSON. */
function describe(err) {
  if (err instanceof Error) {
    return {
      name: err.name,
      message: err.message,
      stack: String(err.stack || '').split('\n').slice(0, 40),
      ...(err.code ? { code: err.code } : {}),
    };
  }
  return { message: String(err) };
}

/**
 * Open a tape.
 *
 * @param opts.path      where to write. Opened now, so a bad path fails while
 *                       there is still a terminal to complain on.
 * @param opts.verbatim  keep documents rather than their hashes.
 * @param opts.program   {name, version} of the application, for the header.
 * @param opts.extra     anything else the launcher knows and the runtime does
 *                       not -- predc puts its config file's path here.
 */
function createRecorder(opts = {}) {
  const file = opts.path;
  const verbatim = !!opts.verbatim;
  const maxBytes = opts.maxBytes || MAX_BYTES;

  // 'a', not 'w': two runs recording to the same name is a mistake worth
  // surviving, and the header line tells the reader where the second one began.
  const fd = fs.openSync(file, 'a');
  const began = realNow();
  let written = 0;
  let truncated = false;
  let farewelled = false;

  const put = (record) => {
    if (truncated) return;
    let line;
    try {
      line = JSON.stringify(record) + '\n';
    } catch (err) {
      // A message that will not serialise is itself worth knowing about, and
      // must not be the thing that takes the program down.
      line = JSON.stringify({ t: realNow() - began, unserialisable: String(err) }) + '\n';
    }
    if (written + line.length > maxBytes) {
      truncated = true;
      line = JSON.stringify({ t: realNow() - began, truncated: maxBytes }) + '\n';
    }
    written += line.length;
    try {
      fs.writeSync(fd, line);
    } catch {
      /* the disk filled, or the file went away. Losing the tape must not lose
         the program. */
    }
  };

  const env = opts.env || process.env;
  put({
    tape: TAPE,
    at: new Date(began).toISOString(),
    redacted: !verbatim,
    program: {
      ...(opts.program || {}),
      argv: (opts.argv || process.argv).slice(1),
      cwd: opts.cwd || process.cwd(),
      // What the launcher handed `init` as flags. Nothing here passes any and
      // it is recorded regardless, for the same reason as `colorDepth`: it is
      // an input, and an input a replay has to guess at is an input that makes
      // a divergence unreadable.
      flags: opts.flags === undefined ? {} : opts.flags,
      // Which compiled module this was. `argv` names the *launcher*, and a
      // launcher is not the thing a replay runs: `gren-tui main.js` and
      // `predc` resolve their module differently and neither rule is
      // recoverable from the arguments. With this a tape says what to replay
      // it against, which is the difference between `gren-replay bug.tape` and
      // a person guessing at a path.
      ...(opts.modulePath ? { module: opts.modulePath } : {}),
    },
    protocol: opts.protocol,
    runtime: {
      node: process.version,
      platform: process.platform,
      arch: process.arch,
      release: os.release(),
      // The zone `Time.getZoneName` will answer with, which is read through
      // `Intl` and therefore never crosses a port. Two of predc's tools decide
      // what to draw from it, so a tape without it replays into a program
      // standing somewhere else on the earth. A replayer puts it back by
      // setting `TZ` before the compiled module loads, which is why this is
      // worth one line here rather than an interception anywhere.
      timeZone: zoneName(),
    },
    // The size the program will lay itself out against before any `Resized`
    // arrives -- half the layout bugs there are begin here.
    terminal: {
      isTTY: !!(process.stdout && process.stdout.isTTY),
      columns: (process.stdout && process.stdout.columns) || null,
      rows: (process.stdout && process.stdout.rows) || null,
      // The fourth thing `Terminal.initialize` answers with. Nothing in this
      // repo reads it and it goes on the tape anyway, because a replay has to
      // hand `init` the same four numbers it was given and cannot know which
      // of them the program looked at.
      colorDepth:
        process.stdout && process.stdout.getColorDepth ? process.stdout.getColorDepth() : 0,
      env: SAFE_ENV.reduce((acc, name) => {
        if (env[name] !== undefined) acc[name] = env[name];
        return acc;
      }, {}),
    },
    // Names only. Which variables are set is frequently the answer; what is in
    // them never is.
    envNames: Object.keys(env).sort(),
    ...(opts.extra ? { extra: opts.extra } : {}),
  });

  // Built here rather than inside `farewell` so that it can be read as well as
  // printed: what a tape holds is the one thing about this feature a person
  // has to be able to check, and a string only a file descriptor ever sees is
  // a string nothing can test.
  const notice = [
    `\nRecorded to ${path.resolve(file)}`,
    '  It contains everything you typed and every event the program saw.',
    verbatim
      ? '  It was recorded verbatim: clipboard and editor contents are in it,\n' +
        '  and so is every random value the program generated.'
      : '  Clipboard and editor contents were left out, and so were any random\n' +
        '  values generated; keystrokes were not.',
    '  Look at it before you send it to anybody.\n',
  ].join('\n');

  const recorder = {
    path: file,
    verbatim,

    /** A message on its way *into* the Gren program: the tape's whole point. */
    inbound(message, port = 'tui') {
      put({ t: realNow() - began, in: verbatim ? message : redact(message), ...(port === 'tui' ? {} : { port }) });
    },

    /**
     * A message on its way *out*, as a fingerprint and never as a payload.
     *
     * A render becomes its hash and the ids it drew, which is enough to check
     * a replay against and not enough to leak anything. The rest keep their
     * type and their id, because "the model asked to focus w3 and nothing
     * happened" is a complete bug report and "the model set the editor text to
     * the following 40 kilobytes" is a liability.
     */
    outbound(message, port = 'tui') {
      put({
        t: realNow() - began,
        ...fingerprint(message),
        ...(port === 'tui' ? {} : { port }),
      });
    },

    /**
     * Bytes the program drew from the system's random source.
     *
     * This is the one thing a tape has to record that is neither inbound nor
     * outbound: `Crypto` is a Gren task, not a port, so nothing here sees it
     * cross anything. Without it a replay of `predc random` regenerates the
     * page with different numbers on it and reports a divergence that is not a
     * bug -- which, repeated, is how a replayer teaches you to ignore it.
     *
     * **Withheld by default, like a document, and for the same reason.** The
     * whole purpose of the random tool is to produce a value somebody is about
     * to use for something: a key, a token, a password. Those are on the
     * screen and therefore in nobody's render, but they would be on the tape,
     * and a recorder that mails you other people's keys is the thing this
     * format was shaped to avoid. The count and the hash are kept, so a reader
     * can still say how many draws it cannot reproduce and a replayer can
     * still tell whether it is being handed the same ones.
     */
    random(kind, bytes) {
      const buffer = Buffer.from(bytes || []);
      const encoded = buffer.toString('base64');
      put({
        t: realNow() - began,
        rng: kind,
        n: buffer.length,
        ...(verbatim ? { value: encoded } : { sha: digest(encoded) }),
      });
    },

    /**
     * A reading of the clock, as the program saw it.
     *
     * The one thing on a tape that was argued out of it and back in. The
     * argument for reconstructing it -- every line is stamped, so a replay can
     * work out what `Time.now` should answer -- holds right up until a program
     * *seeds* something with a millisecond: `examples/puzzle` shuffles its
     * board from `Time.now`, and a board is not nearly the same when the seed
     * is nearly the same. Nothing on the tape said which millisecond it was.
     *
     * The argument against recording it was that `Date.now` cannot be
     * intercepted for one caller. Measured rather than assumed, a running
     * gren-tvision program has exactly two: the Gren kernel, and this file's
     * own stamps -- which is why `realNow` exists a few lines up. tvision-node
     * does not call it and neither does node.
     */
    clock(value) {
      put({ t: realNow() - began, now: value });
    },

    /**
     * A `Time.every` going off.
     *
     * The last thing about a tape that was inferred rather than recorded. A
     * replay has to fire these itself -- the wall clock is not the program's
     * -- and it worked out where from the clock reading each tick takes on its
     * way, which is a signature and not a fact: a reading between a message
     * going in and the render it produced belongs to that update, and `demo`
     * timestamps every event it logs. Recording the tick says which is which,
     * and says how many the model has been sent, which is the number the time
     * converter's behaviour turned out to depend on.
     */
    tick(interval) {
      put({ t: realNow() - began, tick: interval });
    },

    /** Anything the launcher knows that the protocol does not. */
    note(kind, data) {
      put({ t: realNow() - began, note: kind, ...(data === undefined ? {} : { data }) });
    },

    /** The last line a tape gets when something went wrong. */
    crash(where, err) {
      put({ t: realNow() - began, crash: where, error: describe(err) });
      try {
        fs.fsyncSync(fd);
      } catch {
        /* best effort: the record is already written, this only forces it out */
      }
    },

    close(reason) {
      put({ t: realNow() - began, end: reason || 'exit' });
      try {
        fs.closeSync(fd);
      } catch {
        /* already closed */
      }
    },

    /**
     * What the user is told on the way out, on stderr, after TVision has given
     * the terminal back.
     *
     * It says the two things a person needs to decide whether to send the file:
     * where it is, and that their keystrokes are in it.
     */
    notice,

    farewell() {
      if (farewelled || opts.quiet) return;
      farewelled = true;
      try {
        fs.writeSync(2, notice);
      } catch {
        /* stderr is gone */
      }
    },
  };

  return recorder;
}

/**
 * Record the random bytes the Gren program draws, without changing them.
 *
 * Gren's `Crypto` reaches `require("crypto")` and holds the module object,
 * reading the method off it at each call -- so replacing the method on that
 * object is enough, and the object is the same one this file already required
 * for `digest`. The wrapper calls through and records what came back: the
 * program gets the system's randomness, exactly as it would have, and the tape
 * gets a note that a draw happened.
 *
 * Called only when there is a recorder, so a run without `--record` is
 * untouched -- which matters more than it sounds. Weakening a program's
 * randomness to make it reproducible would be the wrong trade in any program
 * and an absurd one in a program whose randomness is the feature.
 */
let tickRecorder = null;
let tickPatched = false;

/**
 * Record every `Time.every` the model is sent.
 *
 * `setInterval` is the seam and it is an exact one *here*: in a running
 * gren-tvision program the only caller is the Gren kernel's `_Time_setInterval`,
 * which is what `Time.every` is made of. The binding's own pump is a
 * `setTimeout` that reschedules itself (`tvision-node/index.js`), and nothing
 * else in the runtime uses either.
 */
function recordTicks(recorder) {
  tickRecorder = recorder || null;
  if (tickPatched || !recorder) return;
  tickPatched = true;
  const realSetInterval = global.setInterval;
  global.setInterval = function (fn, interval, ...args) {
    return realSetInterval.call(
      global,
      function (...fired) {
        try {
          if (tickRecorder) tickRecorder.tick(interval);
        } catch {
          /* a tape that cannot describe a tick must not stop the tick */
        }
        return fn.apply(this, fired);
      },
      interval,
      ...args
    );
  };
}

let clockRecorder = null;
let clockPatched = false;

/**
 * Record every reading of the clock the program takes.
 *
 * The same shape as `recordRandomness`: aimed by a variable, patched once, and
 * a pass-through -- the program gets the real answer and the tape gets a copy.
 * Passing null aims it at nothing.
 */
function recordClock(recorder) {
  clockRecorder = recorder || null;
  if (clockPatched || !recorder) return;
  clockPatched = true;
  Date.now = function () {
    const value = realNow();
    try {
      if (clockRecorder) clockRecorder.clock(value);
    } catch {
      /* a tape that cannot describe a reading must not stop the reading */
    }
    return value;
  };
}

let randomnessRecorder = null;
let randomnessPatched = false;

function recordRandomness(recorder) {
  // The target is a variable and the patch is installed once, which is the
  // shape a process wants: a second `run()` in the same process re-aims this
  // rather than wrapping the wrapper, and passing null aims it at nothing --
  // which is how the tests put the runtime back the way they found it.
  randomnessRecorder = recorder || null;
  if (randomnessPatched || !recorder) return;
  randomnessPatched = true;

  const keep = (kind, bytes) => {
    try {
      if (randomnessRecorder) randomnessRecorder.random(kind, bytes);
    } catch {
      /* a tape that cannot describe a draw must not stop the draw */
    }
  };

  try {
    // **Not on the module object**, which is where the Gren kernel reads it
    // from and where it cannot be replaced: node defines `getRandomValues`
    // there as a non-configurable getter. What that getter hands back is a
    // wrapper that calls the method on `Crypto.prototype`, and *that* is an
    // ordinary writable property. So the seam is one level in, reachable
    // through `webcrypto`, which is an instance of the class whose prototype
    // it is. `randomUUID` needs none of that: on the module object it is a
    // plain writable value.
    const proto = Object.getPrototypeOf(crypto.webcrypto);
    const getRandomValues = proto && proto.getRandomValues;
    if (typeof getRandomValues === 'function') {
      proto.getRandomValues = function (array) {
        const filled = getRandomValues.call(this, array);
        keep('getRandomValues', Buffer.from(filled.buffer, filled.byteOffset, filled.byteLength));
        return filled;
      };
    }
  } catch {
    /* a runtime that will not be patched here is a runtime whose tapes cannot
       replay a random draw, which is a note for the reader rather than a
       reason to refuse to run */
  }

  try {
    const randomUUID = crypto.randomUUID;
    if (typeof randomUUID === 'function') {
      crypto.randomUUID = function (...args) {
        const id = randomUUID.apply(crypto, args);
        keep('randomUUID', Buffer.from(String(id), 'utf8'));
        return id;
      };
    }
  } catch {
    /* as above */
  }
}


/**
 * Catch what the binding cannot.
 *
 * `onError` covers a callback that threw while TVision had the terminal --
 * that path is already handled, and handled better than this, because the C++
 * side restored the terminal before rethrowing. What nothing covers is an
 * exception with no callback under it: the process dies, the alternate screen
 * stays up, and the user's terminal appears to have hung. That is the bug
 * report you cannot do anything with, and it is the cheapest one to fix.
 *
 * `crashLog` is written whether or not a tape was asked for, because the whole
 * problem with a crash is that it happens on the run where nobody was
 * recording.
 */
function installCrashHandlers({ recorder, crashLog, program } = {}) {
  const handle = (where) => (err) => {
    restoreTerminal();
    if (recorder) recorder.crash(where, err);
    if (crashLog) {
      try {
        fs.mkdirSync(path.dirname(crashLog), { recursive: true });
        fs.appendFileSync(
          crashLog,
          JSON.stringify({
            at: new Date().toISOString(),
            program: program || null,
            argv: process.argv.slice(1),
            where,
            error: describe(err),
            ...(recorder ? { tape: path.resolve(recorder.path) } : {}),
          }) + '\n'
        );
      } catch {
        /* if we cannot write the crash log we are certainly not going to
           recover from that here */
      }
    }
    try {
      fs.writeSync(2, `\n${(err && err.stack) || err}\n`);
      if (crashLog) fs.writeSync(2, `\nThis was also written to ${crashLog}\n`);
      if (recorder) recorder.farewell();
    } catch {
      /* nothing left to say it on */
    }
    process.exit(1);
  };

  process.on('uncaughtException', handle('uncaughtException'));
  process.on('unhandledRejection', handle('unhandledRejection'));
}

/**
 * Take `--record FILE` / `--record-verbatim FILE` out of an argument list.
 *
 * It has to come *out*, not merely be read: predc parses its own command line,
 * in Gren, through `Argparse.Parser.run`, and a word that parser has never
 * heard of is an error and an exit -- so a flag the launcher owns has to be
 * gone before the program is handed its arguments. `process.argv` is the list
 * to splice, because that is the one Gren's `Node.Environment` reads, and it
 * reads it when `init` runs rather than when the module loads.
 *
 * Returns null when neither flag was given, so the caller can pass it straight
 * through as `record`.
 */
function takeRecordFlags(argv, complain = 'gren-tui') {
  const take = (name) => {
    const at = argv.indexOf(name);
    if (at < 0) return null;
    const value = argv[at + 1];
    if (!value || value.startsWith('-')) {
      process.stderr.write(`${complain}: ${name} needs a filename\n`);
      process.exit(2);
    }
    argv.splice(at, 2);
    return value;
  };

  // Verbatim first: it is the more specific word, and `indexOf('--record')`
  // does not match it, but taking them in the other order would let somebody
  // pass both and get the quieter one.
  const verbatim = take('--record-verbatim');
  const plain = take('--record');
  const file = verbatim || plain;
  return file ? { path: file, verbatim: !!verbatim } : null;
}

module.exports = {
  TAPE,
  MAX_BYTES,
  SAFE_ENV,
  createRecorder,
  fingerprint,
  recordClock,
  recordTicks,
  recordRandomness,
  takeRecordFlags,
  installCrashHandlers,
  restoreTerminal,
  redact,
  digest,
};
