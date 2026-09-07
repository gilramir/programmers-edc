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

/** Bumped when a reader would get the wrong answer from an older tape. */
const TAPE = 1;

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
  const began = Date.now();
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
      line = JSON.stringify({ t: Date.now() - began, unserialisable: String(err) }) + '\n';
    }
    if (written + line.length > maxBytes) {
      truncated = true;
      line = JSON.stringify({ t: Date.now() - began, truncated: maxBytes }) + '\n';
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
    },
    protocol: opts.protocol,
    runtime: {
      node: process.version,
      platform: process.platform,
      arch: process.arch,
      release: os.release(),
    },
    // The size the program will lay itself out against before any `Resized`
    // arrives -- half the layout bugs there are begin here.
    terminal: {
      isTTY: !!(process.stdout && process.stdout.isTTY),
      columns: (process.stdout && process.stdout.columns) || null,
      rows: (process.stdout && process.stdout.rows) || null,
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

  const recorder = {
    path: file,
    verbatim,

    /** A message on its way *into* the Gren program: the tape's whole point. */
    inbound(message, port = 'tui') {
      put({ t: Date.now() - began, in: verbatim ? message : redact(message), ...(port === 'tui' ? {} : { port }) });
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
      const type = message && message.type;
      const record = { t: Date.now() - began, out: type };
      if (port !== 'tui') record.port = port;
      if (type === 'render') {
        record.hash = digest(JSON.stringify(message));
        record.windows = (message.windows || []).map((w) => w.id);
        record.overlays = (message.overlays || []).length;
      } else if (message && message.id !== undefined) {
        record.id = message.id;
      } else if (message && message.spec && message.spec.id !== undefined) {
        record.id = message.spec.id;
      }
      put(record);
    },

    /** Anything the launcher knows that the protocol does not. */
    note(kind, data) {
      put({ t: Date.now() - began, note: kind, ...(data === undefined ? {} : { data }) });
    },

    /** The last line a tape gets when something went wrong. */
    crash(where, err) {
      put({ t: Date.now() - began, crash: where, error: describe(err) });
      try {
        fs.fsyncSync(fd);
      } catch {
        /* best effort: the record is already written, this only forces it out */
      }
    },

    close(reason) {
      put({ t: Date.now() - began, end: reason || 'exit' });
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
    farewell() {
      if (farewelled) return;
      farewelled = true;
      const lines = [
        `\nRecorded to ${path.resolve(file)}`,
        '  It contains everything you typed and every event the program saw.',
        verbatim
          ? '  It was recorded verbatim: clipboard and editor contents are in it too.'
          : '  Clipboard and editor contents were left out; keystrokes were not.',
        '  Look at it before you send it to anybody.\n',
      ];
      try {
        fs.writeSync(2, lines.join('\n'));
      } catch {
        /* stderr is gone */
      }
    },
  };

  return recorder;
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
  takeRecordFlags,
  installCrashHandlers,
  restoreTerminal,
  redact,
  digest,
};
