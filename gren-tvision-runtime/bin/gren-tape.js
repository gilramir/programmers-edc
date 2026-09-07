#!/usr/bin/env node
'use strict';

// Read a tape:
//
//     gren-tape bug.tape             what the person did, and what changed
//     gren-tape bug.tape --all       every message, nothing collapsed
//     gren-tape bug.tape --extra     the launcher's block, as JSON
//     gren-tape bug.tape --json      the analysis, for something else to read
//
// The default is the one worth having. A tape is mostly drag events -- a
// window pulled across the screen is fifty `windowResized` messages -- and the
// question anybody asks first is what the person did, which is about twenty
// lines. `--all` is there for when the collapsing is hiding the thing.

const fs = require('fs');
const path = require('path');

const { read, analyse, format } = require('../tape');

const args = process.argv.slice(2);
const flags = new Set(args.filter((a) => a.startsWith('-')));
const files = args.filter((a) => !a.startsWith('-'));

if (!files.length || flags.has('-h') || flags.has('--help')) {
  process.stderr.write(
    'usage: gren-tape FILE [--all] [--extra] [--json] [--no-timeline]\n' +
      '  --all          one line per message, with nothing collapsed\n' +
      '  --extra        print the launcher\'s `extra` block and nothing else\n' +
      '  --json         the analysis as JSON\n' +
      '  --no-timeline  the header, the summary and the anomalies only\n'
  );
  process.exit(files.length ? 0 : 2);
}

const unknown = [...flags].filter(
  (f) => !['--all', '--extra', '--json', '--no-timeline', '-h', '--help'].includes(f)
);
if (unknown.length) {
  process.stderr.write(`gren-tape: no such option: ${unknown.join(' ')}\n`);
  process.exit(2);
}

let text;
try {
  text = fs.readFileSync(files[0], 'utf8');
} catch (err) {
  process.stderr.write(`gren-tape: ${err.message}\n`);
  process.exit(1);
}

const { sessions, problems } = read(text);

if (!sessions.length) {
  process.stderr.write(`gren-tape: ${path.resolve(files[0])} has no header line in it.\n`);
  problems.slice(0, 5).forEach((p) => process.stderr.write(`  ${p}\n`));
  process.exit(1);
}

const analyses = sessions.map((s) => analyse(s, { collapse: !flags.has('--all') }));

if (flags.has('--extra')) {
  analyses.forEach((a) => console.log(JSON.stringify(a.header.extra || null, null, 2)));
  process.exit(0);
}

if (flags.has('--json')) {
  console.log(JSON.stringify({ problems, sessions: analyses }, null, 2));
  process.exit(0);
}

console.log(`${path.resolve(files[0])}`);
// A tape is opened with 'a', so one file can hold more than one run: two goes
// at the same bug recorded to the same name is the ordinary way that happens,
// and the second one is usually the interesting one.
if (sessions.length > 1) console.log(`  ${sessions.length} sessions in this file\n`);

analyses.forEach((a, i) => {
  if (i) console.log('');
  if (analyses.length > 1) console.log(`session ${i + 1}`);
  console.log(
    format(a, { timeline: !flags.has('--no-timeline'), lines: flags.has('--all') })
  );
});

if (problems.length) {
  console.log('\nlines this reader could not use');
  problems.forEach((p) => console.log(`  ${p}`));
}
