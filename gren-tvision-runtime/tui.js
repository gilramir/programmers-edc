'use strict';

// The layer between a Gren program and the Turbo Vision binding.
//
// Gren sends the whole UI over a port on every update -- the entire
// description, every time -- and this file works out what actually changed and
// patches it. That is the same bargain elm/browser makes with the DOM, and it
// is the reason the Gren side can be pure: it never calls C++, never blocks,
// and never has to know that a window is a long-lived object with focus and
// scroll position to lose.

const tv = require('tvision-node');

// Bumped in lockstep with Tui.protocolVersion on the Gren side. A Gren package
// and an npm package version independently, and they will skew; refusing an
// unknown version beats rendering nothing and leaving the author to guess.
const PROTOCOL = 1;

// Fields a view can change without being rebuilt. Everything else -- the id,
// the rectangle, a button's command -- is structural: change one and the
// window is torn down and made again. A window's *title* is not structural
// either; see setTitle below.
const MUTABLE = {
  staticText: ['text'],
  inputLine: ['value'],
  listBox: ['items'],
  canvas: ['lines'],
};

function skeleton(view) {
  const copy = { ...view };
  for (const field of MUTABLE[view.type] || []) delete copy[field];
  return JSON.stringify(copy);
}

function sameShape(before, after) {
  if (!before) return false;
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

/**
 * Drive a compiled Gren program's UI.
 *
 * @param grenModule  the module `gren make Main --output=main.js` produced
 * @param options     {flags, moduleName, outPort, inPort}
 */
function run(grenModule, options = {}) {
  // TUI_DEBUG=<file> traces the port traffic. The terminal belongs to TVision,
  // so this is the only way to watch the conversation.
  const trace = process.env.TUI_DEBUG
    ? (dir, what) =>
        require('fs').appendFileSync(process.env.TUI_DEBUG, `${dir} ${JSON.stringify(what)}\n`)
    : () => {};

  let started = false;
  let current = new Map(); // window id -> the spec we last applied

  // tv.close() destroys the window, which notifies onClose, which we would
  // otherwise report to Gren as "the user closed this" -- and Gren would drop
  // it from the model that had just asked for it. The notification is
  // delivered by the pump at a safe point rather than from inside the
  // destructor, so it arrives *after* the call that caused it: a synchronous
  // flag is not enough, and the ids we closed ourselves have to be remembered
  // until they come back.
  const selfClosed = new Set();

  // A render can arrive while we are in the middle of applying one: patching a
  // view can close a window, which notifies Gren, which updates, which
  // renders. Take the newest and apply it after, rather than recursing.
  let applying = false;
  let pending = null;

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

  // `gren make Main` produces Gren.Main; anything else is whatever was named.
  const namespace = grenModule.Gren || grenModule;
  const moduleName = options.moduleName || Object.keys(namespace)[0];
  const app = namespace[moduleName].init({ flags: options.flags || {} });

  const outPort = options.outPort || 'tuiOut';
  const inPort = options.inPort || 'tuiIn';
  if (!app.ports || !app.ports[outPort] || !app.ports[inPort]) {
    throw new Error(
      `gren-tvision: the program must declare ports named ${outPort} and ${inPort}. ` +
        `It has: ${Object.keys(app.ports || {}).join(', ') || '(none)'}`
    );
  }

  const send = (message) => {
    trace('<-', message);
    app.ports[inPort].send(message);
  };

  app.ports[outPort].subscribe((message) => {
    trace(
      '->',
      message.type === 'render'
        ? { type: 'render', windows: message.windows.map((w) => w.id) }
        : message
    );

    switch (message.type) {
      case 'render':
        if (message.protocol !== PROTOCOL) {
          throw new Error(
            `gren-tvision: the Gren side speaks protocol ${message.protocol}, ` +
              `this runtime speaks ${PROTOCOL}. Update whichever half is older.`
          );
        }
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

  return app;
}

module.exports = run;
module.exports.run = run;
module.exports.PROTOCOL = PROTOCOL;
