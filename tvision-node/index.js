'use strict';

// Thin wrapper over the addon. Everything of substance is in src/; what lives
// here is the stuff that is nicer to write in JS -- above all the pump.

const fs = require('fs');

const addon = require('./build/Release/tvision.node');

// How long to wait before looking for input again when nothing is happening.
// TVision's own loop wakes 50 times a second by default (eventTimeoutMs = 20);
// this is a little livelier, and costs nothing measurable.
const IDLE_MS = 8;

// tv.start(config) -- TVision runs as a guest inside Node's event loop: every
// tick we hand it whatever input has arrived, it redraws, and then Node gets on
// with its timers, promises and I/O. Modal dialogs included -- see dialog().
function start(config) {
  let stopped = false;
  let asyncError = null;

  // A callback that throws synchronously is caught in C++, which shuts the
  // application down and rethrows once the terminal is restored. A callback
  // that *rejects* cannot reach C++ at all, so it gets the same treatment by
  // hand: tear the app down, then report.
  const failAsync = (err) => {
    if (asyncError) return;
    asyncError = err;
    try {
      addon.quit();
    } catch {
      /* already gone */
    }
  };

  const guard = (fn) => {
    if (typeof fn !== 'function') return undefined;
    return (...args) => {
      const result = fn(...args);
      if (result && typeof result.then === 'function') result.then(undefined, failAsync);
      return undefined;
    };
  };

  addon.start({
    ...config,
    onCommand: guard(config.onCommand),
    onSelect: guard(config.onSelect),
  });

  const report = (err) => {
    if (typeof config.onError === 'function') config.onError(err);
    else throw err;
  };

  const tick = () => {
    if (stopped) return;

    let handled;
    try {
      handled = addon.step();
    } catch (err) {
      stopped = true;           // step() restored the terminal before throwing
      report(err);
      return;
    }

    if (handled < 0) {
      stopped = true;
      if (asyncError) report(asyncError);
      else if (typeof config.onExit === 'function') config.onExit();
      return;
    }

    // Busy? Come straight back, so a paste or a held-down arrow key is not
    // rationed at the idle rate. Quiet? Let the loop breathe.
    if (handled > 0) setImmediate(tick);
    else setTimeout(tick, IDLE_MS);
  };

  tick();
}

// tv.messageBox(text) -- built here rather than in C++ because TVision's own
// ::messageBox() calls execView(), and execView is exactly the nested loop the
// pump exists to avoid. Returns a Promise, like every other dialog.
function messageBox(text, opts = {}) {
  const lines = String(text).split('\n');
  const screen = addon.screenSize();

  const width = Math.min(screen.width - 6,
                         Math.max(34, ...lines.map((l) => l.length + 8)));
  const height = Math.min(screen.height - 4, lines.length + 7);
  const x = Math.max(0, Math.floor((screen.width - width) / 2));
  const y = Math.max(1, Math.floor((screen.height - height) / 2));
  const mid = Math.floor(width / 2);

  return addon.dialog({
    title: opts.title || 'Information',
    rect: [x, y, x + width, y + height],
    items: [
      { type: 'staticText', rect: [3, 2, width - 3, 2 + lines.length], text: String(text) },
      { type: 'button', rect: [mid - 6, height - 4, mid + 6, height - 2],
        title: '~O~K', cmd: 'ok', default: true },
    ],
  });
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
  start,
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

  // Dialogs. Modal in the Turbo Vision sense -- input goes only to the dialog
  // -- but they do not stop Node: both return a Promise of {cmd, values}.
  dialog: addon.dialog,
  messageBox,

  screenSize: addon.screenSize,
  log,
};
