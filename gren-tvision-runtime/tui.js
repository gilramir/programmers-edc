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
const { createRecorder, installCrashHandlers, recordRandomness } = require('./record');

// Bumped in lockstep with Tui.protocolVersion on the Gren side. A Gren package
// and an npm package version independently, and they will skew; refusing an
// unknown version beats rendering nothing and leaving the author to guess.
const PROTOCOL = 22;

/**
 * Drive a compiled Gren program's UI.
 *
 * @param grenModule  the module `gren make Main --output=main.js` produced
 * @param options     {flags, moduleName, outPort, inPort, tv, record, crashLog}
 */
function run(grenModule, options = {}) {
  const tv = options.tv || require('tvision-node');
  // TUI_DEBUG=<file> traces the port traffic. The terminal belongs to TVision,
  // so this is the only way to watch the conversation.
  const trace = process.env.TUI_DEBUG
    ? (dir, what) =>
        require('fs').appendFileSync(process.env.TUI_DEBUG, `${dir} ${JSON.stringify(what)}\n`)
    : () => {};

  // The tape, if one was asked for. Opened *before* the Gren program is
  // started, for two reasons: a path that cannot be written has to fail while
  // there is still an ordinary terminal to say so on, and a program that
  // crashes in `init` -- reading a config file, say -- is exactly the crash
  // worth having a recording of.
  //
  // `record` is a path or {path, verbatim, program, extra}; TUI_RECORD is the
  // same thing for a program whose launcher has no flag for it, which is every
  // example.
  const asked = options.record || process.env.TUI_RECORD;
  const recorder = asked
    ? createRecorder({
        ...(typeof asked === 'string' ? { path: asked } : asked),
        protocol: PROTOCOL,
        flags: options.flags || {},
      })
    : null;
  // Unconditional: the whole difficulty with a crash is that it lands on the
  // run where nobody thought to record. See record.js.
  installCrashHandlers({
    recorder,
    crashLog: options.crashLog,
    program: options.record && options.record.program,
  });
  // Before the program is started, and only when there is a tape to write it
  // on: `Crypto` never crosses a port, so a draw is invisible to everything
  // else here and a replay without it regenerates different numbers. After the
  // crash handlers rather than before, because everything from here on is
  // allowed to be reported and nothing is allowed to be fatal.
  if (recorder) recordRandomness(recorder);
  if (recorder) process.on('exit', () => recorder.farewell());

  let started = false;
  // The theme last handed to the binding, as JSON, so a render that did not
  // change it does not repaint the screen.
  let appliedTheme = null;
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
    // Before the send and not after: if the program throws on this message,
    // the message that killed it is the one thing the tape must have.
    if (recorder) recorder.inbound(message);
    app.ports[inPort].send(message);
  };

  app.ports[outPort].subscribe((message) => {
    if (recorder) recorder.outbound(message);
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
          // Before start(), so that the very first frame is drawn in the
          // theme rather than repainted into it a moment later.
          tv.setTheme(message.theme);
          appliedTheme = JSON.stringify(message.theme);
          tv.start({
            menuBar: message.menuBar,
            statusLine: message.statusLine,
            onCommand: (cmd) => send({ type: 'command', cmd }),
            onSelect: (id, index, text) => send({ type: 'select', id, index, text }),
            onFocus: (id, index, text) => send({ type: 'focus', id, index, text }),
            onScroll: (id, value) => send({ type: 'scroll', id, value }),
            onKey: (id, key) => send({ type: 'key', id, key }),
            onClick: (id, x, y, doubled, right) =>
              send({ type: 'click', id, x, y, doubled: !!doubled, right: !!right }),
            // The pointer moved on a canvas with a button held, or the button
            // came up and ended the gesture. Only ever the canvas the press
            // happened in, and collapsed to one position per pass of the pump,
            // so this arrives at about the rate a model can render at rather
            // than at the rate a terminal reports cells at.
            onDrag: (id, x, y, done) =>
              send({ type: 'drag', id, x, y, done: !!done }),
            onClose: (id) => differ.windowClosed(id),
            // Fires once at startup and again on every resize, so a model
            // that lays out against it never has to assume a size. The
            // numbers are the desktop's, not the screen's: window rectangles
            // are in desktop coordinates.
            onResize: (cols, rows) => send({ type: 'resized', cols, rows }),
            // The user moved, resized, zoomed or tiled a window. Nothing is
            // said to the differ: what it last applied is the model's own
            // rectangle, which has not changed, so it compares equal and no
            // setBounds is written -- which is exactly what leaves the window
            // where the user put it. The model decides whether to care.
            onWindowResize: (id, x1, y1, x2, y2) =>
              send({ type: 'windowResized', id, rect: [x1, y1, x2, y2] }),
            // The differ is told first and the model second. The order is not
            // cosmetic: the model's answer is a render, and the render has to
            // find a description that already agrees with the view, or it
            // writes the value back into the control the user is using.
            // An editor was edited, or its caret moved. Deliberately without
            // the document: see `editorText` below for how one travels.
            onEdit: (id, modified, line, column, canUndo, hasSelection, overwrite) =>
              send({ type: 'edited', id, modified: !!modified, line, column,
                     canUndo: !!canUndo, hasSelection: !!hasSelection,
                     overwrite: !!overwrite }),
            // The clipboard's answer, which arrives when it arrives: a
            // terminal that owns the clipboard is asked for it with an escape
            // sequence and replies through the input stream, so this can be
            // several events after the request that caused it. `fromSystem` is
            // false when the answer is this process's own last copy, which is
            // what a machine with no clipboard falls back to.
            onClipboard: (text, fromSystem) =>
              send({ type: 'clipboardText', text, fromSystem: !!fromSystem }),
            // A *view* copied -- a selection cut or copied out of an input line
            // or an editor with `clipboard.copy`. The same event as the one
            // `setClipboard` below answers with, because it is the same claim:
            // the text is on this program's clipboard, and `toSystem` says
            // whether anything outside confirmed taking it.
            onCopied: (toSystem) => send({ type: 'copied', toSystem: !!toSystem }),
            onChange: (id, value) => {
              differ.valueChanged(id, value);
              send({ type: 'changed', id, value });
            },
            onExit: () => {
              if (recorder) recorder.close('exit');
              process.exit(0);
            },
            // The terminal is already back by the time this runs -- a callback
            // that throws synchronously is caught in C++, which shuts the
            // application down and rethrows once it has restored it -- so the
            // message here is visible. What it was not, before the tape, was
            // keepable.
            onError: (err) => {
              if (recorder) {
                recorder.crash('onError', err);
                recorder.close('error');
              }
              console.error(err);
              process.exit(1);
            },
          });
          started = true;
        } else {
          // Compared by value, like everything else here: a model that
          // re-renders the same theme thirty times a second must not repaint
          // the screen thirty times, and setTheme's repaint is the whole
          // screen.
          const theme = JSON.stringify(message.theme);
          if (theme !== appliedTheme) {
            appliedTheme = theme;
            tv.setTheme(message.theme);
          }
          differ.chrome(message.menuBar, message.statusLine);
        }
        differ.apply(message.windows);
        // After the windows, because an overlay sits above them and is built
        // by insertion order like everything else in a group.
        differ.overlay(message.overlays);
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

      // Raising a window, which is not queued the way focus is: a window can
      // only be raised once it exists, and one that does not exist yet will be
      // built in front anyway, which is what the model asked for.
      case 'bringToFront':
        if (started) tv.bringToFront(message.id);
        break;

      // A context menu, which is a Cmd for the same reason a dialog is: it is
      // modal, and what comes back is the user's answer. Unlike a dialog it
      // needs no plumbing on the way back at all -- the command the user chose
      // arrives through onCommand, indistinguishable from the same command on
      // the menu bar, which is the whole point.
      case 'popupMenu':
        tv.popupMenu({
          view: message.view,
          x: message.x,
          y: message.y,
          items: message.items,
        });
        break;

      // The two halves of an editor's document, and the only pair of messages
      // in this protocol that carry one. A render cannot: `view` runs on every
      // tick of every subscription, and a file does not belong in it.
      // The other way text gets into an editor, and the one that keeps what
      // is already there: setEditorText replaces the document, this puts
      // characters in at the caret the way typing them would.
      case 'insertIntoEditor':
        tv.insertIntoEditor(message.id, message.text);
        break;

      case 'setEditorText':
        tv.setEditorText(message.id, message.text);
        break;

      // Where the caret goes, which setEditorText has just reset. The pair of
      // numbers is the pair an `Edited` event carries, so a model that reads
      // a document, rewrites it and puts it back can put the reader back with
      // what it was already told.
      case 'setEditorCaret':
        tv.setEditorCaret(message.id, message.line, message.column);
        break;

      case 'readEditor': {
        // A Cmd answered by a Msg, exactly as `dialog` is. The read itself is
        // synchronous in the binding -- it is a copy out of a buffer -- but
        // what the model sees is an ordinary event.
        const text = tv.readEditor(message.id);
        if (text !== null && text !== undefined) {
          send({ type: 'editorText', id: message.id, text });
        }
        break;
      }

      // Find and replace. A Cmd answered by a Msg, the same shape readEditor
      // has and for the same reason: the model already had to put up a dialog
      // to get the search string, so the answer belongs in `update` beside the
      // dialog's.
      case 'searchEditor': {
        const matches = tv.searchEditor(message.id, {
          what: message.what,
          replace: message.replace,
          replacement: message.replacement,
          matchCase: message.matchCase,
          wholeWords: message.wholeWords,
          all: message.all,
        });
        if (matches !== null && matches !== undefined) {
          send({ type: 'searched', id: message.id, matches });
        }
        break;
      }

      // Copy is synchronous and its answer is not interesting enough to wait
      // for -- but it is interesting: false means the system clipboard refused
      // it and no other program will see it, which a model may want to say out
      // loud. So it goes back as an event, like every other answer here.
      case 'copyToClipboard':
        send({ type: 'copied', toSystem: !!tv.setClipboard(message.text) });
        break;

      // And read is a request whose answer comes back through onClipboard
      // above, whenever the clipboard gets round to it.
      case 'readClipboard':
        tv.requestClipboard();
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

  // The app is handed back so that a program with ports of its own can
  // subscribe to them -- the runtime claims `tuiOut` and `tuiIn` and nothing
  // else. A program that does that has a second inbound stream, and a tape
  // missing it is a tape that will not replay, so the recorder goes back with
  // it. Non-enumerable: this is a Gren value and nobody should find a
  // JavaScript object while walking its ports.
  Object.defineProperty(app, 'tuiRecorder', { value: recorder, enumerable: false });
  return app;
}

module.exports = run;
module.exports.run = run;
module.exports.PROTOCOL = PROTOCOL;
module.exports.record = require('./record');
