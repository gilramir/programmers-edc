'use strict';

// The layer between a Gren program and the Turbo Vision binding.
//
// Gren sends the whole UI over a port on every update -- the entire
// description, every time -- and this file works out what actually changed and
// patches it. That is the same bargain elm/browser makes with the DOM, and it
// is the reason the Gren side can be pure: it never calls C++, never blocks,
// and never has to know that a window is a long-lived object with focus and
// scroll position to lose.

const { createDiffer } = require('./diff');

// Bumped in lockstep with Tui.protocolVersion on the Gren side. A Gren package
// and an npm package version independently, and they will skew; refusing an
// unknown version beats rendering nothing and leaving the author to guess.
const PROTOCOL = 8;

/**
 * Drive a compiled Gren program's UI.
 *
 * @param grenModule  the module `gren make Main --output=main.js` produced
 * @param options     {flags, moduleName, outPort, inPort, tv}
 */
function run(grenModule, options = {}) {
  const tv = options.tv || require('tvision-node');
  // TUI_DEBUG=<file> traces the port traffic. The terminal belongs to TVision,
  // so this is the only way to watch the conversation.
  const trace = process.env.TUI_DEBUG
    ? (dir, what) =>
        require('fs').appendFileSync(process.env.TUI_DEBUG, `${dir} ${JSON.stringify(what)}\n`)
    : () => {};

  let started = false;
  let differ = null;
  // See the `focus` case below: a focus can name a view the render it came
  // with has not built yet.
  let pendingFocus = null;

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
          differ = createDiffer(tv, (id) => send({ type: 'windowClosed', id }));
          differ.chrome(message.menuBar, message.statusLine);   // records them
          // The first render builds the application, menu bar and status line
          // included; later ones can replace them, because Turbo Vision keeps
          // both in members a subclass can swap.
          tv.start({
            menuBar: message.menuBar,
            statusLine: message.statusLine,
            onCommand: (cmd) => send({ type: 'command', cmd }),
            onSelect: (id, index, text) => send({ type: 'select', id, index, text }),
            onFocus: (id, index, text) => send({ type: 'focus', id, index, text }),
            onScroll: (id, value) => send({ type: 'scroll', id, value }),
            onKey: (id, key) => send({ type: 'key', id, key }),
            onClick: (id, x, y, doubled) =>
              send({ type: 'click', id, x, y, doubled: !!doubled }),
            onClose: (id) => differ.windowClosed(id),
            // Fires once at startup and again on every resize, so a model
            // that lays out against it never has to assume a size. The
            // numbers are the desktop's, not the screen's: window rectangles
            // are in desktop coordinates.
            onResize: (cols, rows) => send({ type: 'resized', cols, rows }),
            // The differ is told first and the model second. The order is not
            // cosmetic: the model's answer is a render, and the render has to
            // find a description that already agrees with the view, or it
            // writes the value back into the control the user is using.
            onChange: (id, value) => {
              differ.valueChanged(id, value);
              send({ type: 'changed', id, value });
            },
            onExit: () => process.exit(0),
            onError: (err) => {
              console.error(err);
              process.exit(1);
            },
          });
          started = true;
        } else {
          differ.chrome(message.menuBar, message.statusLine);
        }
        differ.apply(message.windows);
        if (pendingFocus !== null) {
          tv.focus(pendingFocus);
          pendingFocus = null;
        }
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

      // The only message that names one view. Everything else describes the
      // whole UI and lets the differ work out what moved; focus cannot be
      // derived that way, because where the caret is at any moment is
      // Turbo Vision's business and not the model's.
      //
      // Held until after the next render, and tried once now as well.
      //
      // An update's Cmd and its render are one Cmd.batch, and the Cmd leaves
      // first: a focus naming a window the same update opens arrives before
      // the window exists. Focusing a view that is not there yet is the same
      // silent nothing `cursor` was -- it reports failure and that is all --
      // so the id is held and applied again once the render that builds it
      // has been applied. That also covers the case where the view does exist
      // but the render rebuilds the window it is in.
      //
      // The attempt now is for the other order, which Cmd.batch does not rule
      // out. Focusing an id twice is idempotent and an id that names nothing
      // is a no-op, so the redundant call costs nothing.
      case 'focus':
        pendingFocus = message.id;
        if (started) tv.focus(message.id);
        break;

      case 'doubleClickDelay':
        tv.doubleClickDelay(message.ticks);
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
