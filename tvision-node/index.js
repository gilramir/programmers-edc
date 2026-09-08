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
    onFocus: guard(config.onFocus),
    onScroll: guard(config.onScroll),
    onKey: guard(config.onKey),
    onClick: guard(config.onClick),
    onDrag: guard(config.onDrag),
    onClose: guard(config.onClose),
    onResize: guard(config.onResize),
    onWindowResize: guard(config.onWindowResize),
    onChange: guard(config.onChange),
    onEdit: guard(config.onEdit),
    onClipboard: guard(config.onClipboard),
    onCopied: guard(config.onCopied),
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
  // Where the caret has been moved to since a window was built, if anywhere.
  // For the layer that rebuilds windows: see the note in views.cc for why this
  // is a question rather than an event, and why it answers about *moving*
  // rather than about focus.
  movedCaret: addon.movedCaret,
  setText: addon.setText,
  setViewEnabled: addon.setViewEnabled,
  setWindowFlags: addon.setWindowFlags,
  bringToFront: addon.bringToFront,
  insertIntoEditor: addon.insertIntoEditor,
  setViewVisible: addon.setViewVisible,
  setListTop: addon.setListTop,
  setItemsEnabled: addon.setItemsEnabled,
  setItems: addon.setItems,

  // An editor's document, which is the one thing in this binding that does not
  // travel with the render: setEditorText puts one in, readEditor takes it
  // out. See the note on JsEditor in tvnode.h.
  setEditorText: addon.setEditorText,
  // And the caret, which setEditorText resets: a model that puts back a
  // reflowed copy of what it just read has to be able to put the reader back
  // too.
  setEditorCaret: addon.setEditorCaret,
  readEditor: addon.readEditor,
  searchEditor: addon.searchEditor,
  setLines: addon.setLines,
  setTheme: addon.setTheme,
  setTitle: addon.setTitle,
  setWindowPalette: addon.setWindowPalette,
  setCursor: addon.setCursor,
  setScroll: addon.setScroll,
  setEnabled: addon.setEnabled,
  setBounds: addon.setBounds,

  // The menu bar and status line start as configuration and can then be
  // replaced outright -- Turbo Vision keeps them in swappable members.
  setMenuBar: addon.setMenuBar,
  setStatusLine: addon.setStatusLine,
  getValue: addon.getValue,
  setValue: addon.setValue,

  // Dialogs. Modal in the Turbo Vision sense -- input goes only to the dialog
  // -- but they do not stop Node: both return a Promise of {cmd, values}.
  dialog: addon.dialog,
  messageBox,

  // A context menu at a point in a view, modal until something is chosen or
  // the user clicks away. The chosen command comes back through onCommand like
  // any other, because it is put back on the event queue rather than reported
  // specially -- so the model never has to know where a command came from.
  // Flat: entries and separators, no submenus. See the note on JsMenuPopup.
  popupMenu: addon.popupMenu,

  // The views that sit on the application rather than on the desktop -- a
  // clock in the corner, a heap gauge. Screen coordinates, replaced whole.
  overlays: addon.overlays,

  screenSize: addon.screenSize,

  // The clipboard, which is a request and an answer rather than a getter:
  // see the note on requestClipboard() in app.cc.
  setClipboard: addon.setClipboard,
  requestClipboard: addon.requestClipboard,
  doubleClickDelay: addon.doubleClickDelay,
  log,
};
