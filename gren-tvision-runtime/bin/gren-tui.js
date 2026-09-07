#!/usr/bin/env node
'use strict';

// Run a compiled Gren TUI program:
//
//     gren make Main --output=main.js && gren-tui main.js
//
// so that an application needs no JavaScript of its own.
//
//     gren-tui main.js --record /tmp/bug.tape
//
// records what crossed the port boundary, for a bug that is easier to hit than
// to describe. `--record-verbatim` keeps clipboard and editor contents too; see
// record.js for why that is a separate word rather than a default.

const path = require('path');

const run = require('..');
const { takeRecordFlags } = require('../record');

// Out of `process.argv` and not a copy of it: that is the list a Gren program
// is handed as `Node.Environment.args`, and a flag the launcher owns must not
// reach a program that parses its own command line.
const record = takeRecordFlags(process.argv, 'gren-tui');

const target = process.argv[2];
if (!target) {
  console.error('usage: gren-tui <compiled-gren-module.js> [--record FILE]');
  console.error('  compile with: gren make Main --output=main.js');
  process.exit(2);
}

const compiled = path.resolve(process.cwd(), target);
run(require(compiled), { record: record || undefined, modulePath: compiled });
