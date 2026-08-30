#!/usr/bin/env node
'use strict';

// The layer between a Gren program and the Turbo Vision binding.
//
// Gren sends the whole UI over a port on every update -- the entire
// description, every time -- and this file works out what actually changed and
// patches it. That is the same bargain elm/browser makes with the DOM, and it
// is the reason the Gren side can be pure: it never calls C++, never blocks,
// and never has to know that a window is a long-lived object with focus and
// scroll position to lose.

const path = require('path');

const tv = require(path.join(__dirname, '..', 'tvision-node'));
const gren = require(path.join(__dirname, 'main.js'));

// TUI_DEBUG=<file> traces the port traffic. The terminal belongs to TVision,
// so this is the only way to watch the conversation.
const trace = process.env.TUI_DEBUG
  ? (dir, what) => require('fs').appendFileSync(process.env.TUI_DEBUG, `${dir} ${JSON.stringify(what)}\n`)
  : () => {};

// Fields a view can change without being rebuilt. Everything else -- the id,
// the rectangle, a button's command -- is structural: change one and the
// window is torn down and made again.
const MUTABLE = {
  staticText: ['text'],
  inputLine: ['value'],
  listBox: ['items'],
  canvas: ['lines'],
};

let started = false;
let current = new Map();     // window id -> the spec we last applied

// tv.close() destroys the window, which notifies onClose, which we would
// otherwise report to Gren as "the user closed this" -- and Gren would drop it
// from the model that had just asked for it. The notification is delivered by
// the pump at a safe point rather than from inside the destructor, so it
// arrives *after* the call that caused it: a synchronous flag is not enough,
// and the ids we closed ourselves have to be remembered until they come back.
const selfClosed = new Set();

// A render can arrive while we are in the middle of applying one: patching a
// view can close a window, which notifies Gren, which updates, which renders.
// Take the newest and apply it after, rather than recursing.
let applying = false;
let pending = null;

function skeleton(view) {
  const copy = { ...view };
  for (const field of MUTABLE[view.type] || []) delete copy[field];
  return JSON.stringify(copy);
}

function sameShape(before, after) {
  if (!before) return false;
  // The title is patchable, so it is not part of the shape.
  if (JSON.stringify(before.rect) !== JSON.stringify(after.rect)) return false;
  if (before.items.length !== after.items.length) return false;
  return before.items.every((view, i) => skeleton(view) === skeleton(after.items[i]));
}

function patchView(before, after) {
  switch (after.type) {
    case 'staticText':
      // Compared against the *previous description*, never against what is on
      // screen. An input line the user has typed into disagrees with the model
      // by design; writing the model back on every render would eat their
      // keystrokes.
      if (before.text !== after.text) tv.setText(after.id, after.text);
      break;
    case 'inputLine':
      if (before.value !== after.value) tv.setValue(after.id, after.value);
      break;
    case 'listBox':
      if (JSON.stringify(before.items) !== JSON.stringify(after.items)) {
        tv.setItems(after.id, after.items);
      }
      break;
    case 'canvas':
      if (JSON.stringify(before.lines) !== JSON.stringify(after.lines)) {
        tv.setLines(after.id, after.lines);
      }
      break;
    default:
      break;
  }
}

function closeWindow(id) {
  selfClosed.add(id);
  tv.close(id);
}

function applyWindows(windows) {
  if (applying) {
    pending = windows;
    return;
  }
  applying = true;

  try {
    do {
      const next = new Map(windows.map((w) => [w.id, w]));

      for (const id of current.keys()) {
        if (!next.has(id) && tv.exists(id)) closeWindow(id);
      }

      for (const window of windows) {
        // tv.exists() rather than our own bookkeeping: the user may have
        // closed this window from its frame since the last render.
        if (!tv.exists(window.id)) {
          tv.window(window);
        } else if (!sameShape(current.get(window.id), window)) {
          closeWindow(window.id);
          tv.window(window);
        } else {
          const before = current.get(window.id);
          if (before.title !== window.title) tv.setTitle(window.id, window.title);
          window.items.forEach((view, i) => patchView(before.items[i], view));
        }
      }

      current = next;
      windows = pending;
      pending = null;
    } while (windows);
  } finally {
    applying = false;
  }
}

function main() {
  const app = gren.Gren.Main.init({});
  const send = (message) => {
    trace('<-', message);
    app.ports.tuiIn.send(message);
  };

  app.ports.tuiOut.subscribe((message) => {
    trace('->', message.type === 'render'
      ? { type: 'render', windows: message.windows.map((w) => w.id) }
      : message);
    switch (message.type) {
      case 'render':
        if (!started) {
          // The menu bar and status line arrive with the first render and are
          // used once: Turbo Vision builds them inside the TApplication
          // constructor and they cannot be swapped afterwards.
          tv.start({
            menuBar: message.menuBar,
            statusLine: message.statusLine,
            onCommand: (cmd) => send({ type: 'command', cmd }),
            onSelect: (id, index, text) => send({ type: 'select', id, index, text }),
            onKey: (id, key) => send({ type: 'key', id, key }),
            onClick: (id, x, y) => send({ type: 'click', id, x, y }),
            onClose: (id) => {
              if (selfClosed.delete(id)) return;
              send({ type: 'windowClosed', id });
            },
            onExit: () => process.exit(0),
            onError: (err) => {
              console.error(err);
              process.exit(1);
            },
          });
          started = true;
        }
        applyWindows(message.windows);
        break;

      case 'dialog':
        // Modal, and awaited. The result goes back as an event, so on the Gren
        // side opening a dialog is a Cmd that produces a Msg -- exactly like
        // an HTTP request.
        tv.dialog(message.spec).then((answer) =>
          send({
            type: 'dialogClosed',
            id: message.spec.id,
            cmd: answer.cmd || '',
            values: answer.values,
          })
        );
        break;

      case 'setEnabled':
        tv.setEnabled(message.cmd, message.on);
        break;

      case 'quit':
        tv.quit();
        break;

      default:
        break;
    }
  });
}

main();
