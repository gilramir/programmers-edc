#!/usr/bin/env node
'use strict';

// Run a compiled Gren TUI program:
//
//     gren make Main --output=main.js && gren-tui main.js
//
// so that an application needs no JavaScript of its own.

const path = require('path');

const run = require('..');

const target = process.argv[2];
if (!target) {
  console.error('usage: gren-tui <compiled-gren-module.js>');
  console.error('  compile with: gren make Main --output=main.js');
  process.exit(2);
}

run(require(path.resolve(process.cwd(), target)));
