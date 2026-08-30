'use strict';

// Thin wrapper over the addon. Everything of substance is in src/tvnode.cc;
// what lives here is the stuff that is simply nicer to write in JS.

const addon = require('./build/Release/tvision.node');

const fs = require('fs');

// TVision owns the terminal, so console.log() draws garbage over the app.
// Log to a file instead: TVISION_LOG=/path/to/log, else silently dropped.
const logPath = process.env.TVISION_LOG;
let logStream = null;

function log(...args) {
  if (!logPath) return;
  if (!logStream) logStream = fs.createWriteStream(logPath, { flags: 'a' });
  logStream.write(args.map((a) => (typeof a === 'string' ? a : JSON.stringify(a))).join(' ') + '\n');
}

module.exports = {
  run: addon.run,
  dialog: addon.dialog,
  messageBox: addon.messageBox,
  quit: addon.quit,
  screenSize: addon.screenSize,
  log,
};
