'use strict';

// Thin wrapper over the addon. Everything of substance is in src/; what lives
// here is the stuff that is simply nicer to write in JS -- above all the pump.

const fs = require('fs');

const addon = require('./build/Release/tvision.node');

// How long to wait before looking for input again when nothing is happening.
// TVision's own loop wakes 50 times a second by default (eventTimeoutMs = 20);
// this is a little livelier, and costs nothing measurable.
const IDLE_MS = 8;

// tv.start(config) -- the non-blocking form. TVision runs as a guest inside
// Node's event loop: every tick we hand it whatever input has arrived, it
// redraws, and then Node gets on with its timers, promises and I/O. This
// function is the whole of milestone 2's argument.
function start(config) {
  addon.start(config);

  let stopped = false;

  const tick = () => {
    if (stopped) return;

    let handled;
    try {
      handled = addon.step();
    } catch (err) {
      // step() restored the terminal before throwing.
      stopped = true;
      if (typeof config.onError === 'function') config.onError(err);
      else throw err;
      return;
    }

    if (handled < 0) {
      stopped = true;
      if (typeof config.onExit === 'function') config.onExit();
      return;
    }

    // Busy? Come straight back, so a paste or a held-down arrow key is not
    // rationed at the idle rate. Quiet? Let the loop breathe.
    if (handled > 0) setImmediate(tick);
    else setTimeout(tick, IDLE_MS);
  };

  tick();
}

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
  // Lifecycle
  run: addon.run,     // milestone 1: blocking, starves Node's loop
  start,              // milestone 2: pumped, Node stays in charge
  quit: addon.quit,

  // Windows and views
  window: addon.window,
  close: addon.close,
  exists: addon.exists,
  focus: addon.focus,
  setText: addon.setText,
  setItems: addon.setItems,
  getValue: addon.getValue,
  setValue: addon.setValue,

  // Modal things (these block Node's loop for as long as they are up)
  dialog: addon.dialog,
  messageBox: addon.messageBox,

  screenSize: addon.screenSize,
  log,
};
