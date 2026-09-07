#!/usr/bin/env node
'use strict';

// Run a tape back through the program that made it:
//
//     gren-replay bug.tape main.js
//
// It starts no terminal and needs none. The program is driven straight through
// its ports, its output is fingerprinted the way the recorder fingerprinted the
// original, and the first pair that differs is the answer -- with the message
// that was fed last, which is the line of the tape to look at.
//
// Exit 0 if the tape reproduced, 1 if it diverged, 2 if it could not be run.

const fs = require('fs');
const path = require('path');

const { read, analyse } = require('../tape');
const { replay } = require('../replay');

const args = process.argv.slice(2);
const flags = new Set(args.filter((a) => a.startsWith('-')));
const values = new Set();
args.forEach((a, i) => {
  if (a === '--env') values.add(i + 1);
});
const files = args.filter((a, i) => !a.startsWith('-') && !values.has(i));

if (files.length < 1 || files.length > 2 || flags.has('-h') || flags.has('--help')) {
  process.stderr.write(
    'usage: gren-replay FILE.tape [MODULE.js] [--session=N] [--json] [--quiet]\n' +
      '  the module is what `gren make Main --output=main.js` produced, not\n' +
      '  the launcher that runs it. A tape written by a launcher that said\n' +
      '  which module it loaded carries the path, and the argument is then\n' +
      '  only for replaying a tape against a different build.\n' +
      '  --env NAME=VALUE   plant a variable the tape kept only the name of\n' +
      '                     (repeatable)\n' +
      '  --in-place         let the program write where it wrote when it was\n' +
      '                     recorded, instead of into a directory of its own\n' +
      '  --trace            print every message, both ways, as it goes\n'
  );
  process.exit(2);
}

const [tapeFile, moduleFile] = files;
// A tape keeps environment variables by name and never by value, so the two
// or three a program actually reads have to be handed back by whoever is
// looking at the bug.
const env = {};
args.forEach((a, i) => {
  const pair = a === '--env' ? args[i + 1] : a.startsWith('--env=') ? a.slice(6) : null;
  if (!pair) return;
  const at = pair.indexOf('=');
  if (at > 0) env[pair.slice(0, at)] = pair.slice(at + 1);
});
const which = Number((args.find((a) => a.startsWith('--session=')) || '').split('=')[1] || 0);

let text;
try {
  text = fs.readFileSync(tapeFile, 'utf8');
} catch (err) {
  process.stderr.write(`gren-replay: ${err.message}\n`);
  process.exit(2);
}

const { sessions } = read(text);
if (!sessions.length) {
  process.stderr.write(`gren-replay: ${path.resolve(tapeFile)} has no header line in it.\n`);
  process.exit(2);
}
const session = sessions[which] || sessions[0];

const module_ = moduleFile || (session.header.program && session.header.program.module);
if (!module_) {
  process.stderr.write(
    'gren-replay: this tape does not say which module it was, so name one:\n' +
      `  gren-replay ${tapeFile} path/to/main.js\n`
  );
  process.exit(2);
}

let grenModule;
try {
  grenModule = require(path.resolve(process.cwd(), module_));
} catch (err) {
  process.stderr.write(`gren-replay: cannot load ${module_}: ${err.message}\n`);
  process.exit(2);
}

replay(grenModule, session, {
  env,
  inPlace: flags.has('--in-place'),
  // Every message, both ways, as it happens. What it is for is the case where
  // the two sequences differ in *length*: the report names the first pair that
  // disagrees, and a missing message makes every pair after it disagree.
  trace: flags.has('--trace')
    ? (dir, port, what) => console.log(`  ${dir} ${port.padEnd(5)} ${JSON.stringify(what)}`)
    : undefined,
})
  .then((result) => {
    if (flags.has('--json')) {
      console.log(JSON.stringify(result, null, 2));
      process.exit(result.ok ? 0 : 1);
    }

    result.warnings.forEach((w) => console.log(`note: ${w}`));
    if (result.warnings.length) console.log('');

    if (result.ok) {
      console.log(`replayed ${result.matched} messages, all of them the same as the tape.`);
      process.exit(0);
    }

    if (result.divergence) {
      const { step, after, why, actual } = result.divergence;
      console.log(`diverged after ${result.matched} matching messages.`);
      console.log('');
      if (after) {
        const m = after.message || {};
        console.log(`  last fed   line ${after.at}, ${(after.t / 1000).toFixed(1)}s: ${m.type}${m.id ? ` ${m.id}` : ''}${m.cmd ? ` ${m.cmd}` : ''}`);
      }
      // A divergence can name a message going the other way -- a port the
      // program does not have, or the tape running on past a program that
      // stopped -- and those have nothing expected about them.
      if (step && step.kind === 'expect') {
        console.log(
          `  expected   line ${step.at}: ${step.expected.out}` +
            (step.expected.hash ? ` ${step.expected.hash}` : '')
        );
      } else if (step) {
        console.log(`  at         line ${step.at}, ${(step.t / 1000).toFixed(1)}s`);
      }
      if (actual) console.log(`  got        ${actual.out}${actual.hash ? ` ${actual.hash}` : ''}`);
      console.log(`  which is   ${why}`);
    } else if (result.extra.length) {
      console.log(
        `the tape ended, and the program had ${result.extra.length} more message(s) to say: ` +
          result.extra.map((e) => e.out).join(', ')
      );
    }
    if (!flags.has('--quiet')) {
      const a = analyse(session);
      if (a.summary.random && a.summary.random.withheld) {
        console.log('');
        console.log('  the tape withheld its random draws, which is the commonest reason for this.');
      }
    }
    process.exit(1);
  })
  .catch((err) => {
    process.stderr.write(`gren-replay: ${(err && err.stack) || err}\n`);
    process.exit(2);
  });
