#!/usr/bin/env node
'use strict';

// predc's entry point.
//
// gren-tvision ships a `gren-tui` bin that runs any compiled Gren program, and
// for the examples that is the right thing: they are demonstrations, and the
// name on the command line is the runtime's. An application is not a
// demonstration. `predc` is the name the user types, the path to the compiled
// module is ours and not theirs, and it is resolved against this file rather
// than the working directory -- a tool you carry every day gets run from
// wherever you happen to be standing.
//
// It is also where the time converter's host port is wired. `run()` hands back
// the Gren app, so ports beyond the two the runtime insists on are the
// launcher's to subscribe to -- and the IANA time zone database is exactly the
// kind of thing that has to be, because it lives in node's `Intl` and there is
// no Gren of it. See `bin/timezones.js`.
//
// And it is where `--record` is taken off the command line, for the reason
// given in `record.js`: the flag belongs to the launcher, not to the parser in
// `Cli.gren`, which would answer a word it has never heard of with an error and
// an exit. Taking it out here is what lets both be true.

const fs = require('fs');
const os = require('os');
const path = require('path');

const run = require('gren-tvision');
const { takeRecordFlags } = require('gren-tvision/record');
const timezones = require('./timezones');

const version = require('../package.json').version;

// Before the compiled module is even loaded, so there is no window in which
// anything could read the unspliced list.
const record = takeRecordFlags(process.argv, 'predc');

/**
 * `$XDG_STATE_HOME/predc/crash.log`, or `~/.local/state/predc/crash.log`.
 *
 * State and not config: the XDG spec puts logs under the state directory, and
 * predc's config file -- which `Config.where_` places under
 * `$XDG_CONFIG_HOME` -- is a different kind of thing that happens to belong to
 * the same program. Two conventions rather than one is the price of following
 * the specification instead of the nearest existing line of code.
 *
 * It is written whether or not `--record` was given, which is the entire point
 * of it: a crash happens on the run where nobody thought to record.
 */
function crashLog() {
  const state = process.env.XDG_STATE_HOME || path.join(os.homedir(), '.local', 'state');
  return path.join(state, 'predc', 'crash.log');
}

/**
 * The config file, as the program will read it.
 *
 * This is the one thing in the header that is not the runtime's to know and is
 * not optional either: predc decides its theme, its week numbering, its chart
 * mode and its zone list from this file during `init`, before the first frame,
 * so a tape without it replays into a different program. Recorded as text,
 * because a value that round-tripped through a decoder is a value whose
 * decoding is no longer under test -- and a corrupt file is a case worth being
 * able to reproduce.
 *
 * The path rule is `Config.where_`'s, restated in JavaScript because there is
 * no way for this side to ask. If that rule changes, this changes with it; the
 * `path` in the header is what says which file was actually read, so a skew
 * shows up as a wrong path rather than as a silent lie.
 */
function configFile() {
  const home = process.env.HOME;
  const base = process.env.XDG_CONFIG_HOME || (home ? path.join(home, '.config') : null);
  if (!base) return { path: null };
  const file = path.join(base, 'predc', 'config.toml');
  try {
    return { path: file, contents: fs.readFileSync(file, 'utf8') };
  } catch (err) {
    // Every failure is the same answer to predc -- start in the defaults --
    // so it is the same answer here, with the reason kept because "which
    // failure" is occasionally the bug.
    return { path: file, contents: null, problem: err.code || String(err) };
  }
}

const compiled = path.join(__dirname, '..', 'main.js');

let main;
try {
  main = require(compiled);
} catch (err) {
  if (err.code !== 'MODULE_NOT_FOUND') throw err;
  console.error('predc: not built yet -- run ./build.sh');
  process.exit(2);
}

const app = run(main, {
  record: record
    ? { ...record, program: { name: 'predc', version }, extra: { config: configFile() } }
    : undefined,
  crashLog: crashLog(),
});

// The recorder goes with it: `intlIn` is a second stream into the program, and
// a tape without it is a tape the time converter will not replay from.
timezones.attach(app, { record: app.tuiRecorder });
