'use strict';

// Milestone 2: a Turbo Vision app where Node is the one running the loop.
//
// The point of the demo is what the C++ examples in tvision/examples cannot
// easily do. The clock window is repainted by a plain setInterval. The
// directory window is filled by await fs.readdir(), and selecting an entry
// stats it asynchronously and writes the answer back into the window. None of
// that is possible under milestone 1's blocking run() -- Node's event loop
// never gets a turn.
//
// Dialogs are modal in the Turbo Vision sense -- File > Go to takes all the
// input until you dismiss it -- without stopping Node. The clock keeps ticking
// behind it, because the dialog is driven by the same pump as everything else
// rather than by a nested loop inside TVision.

const fsp = require('fs/promises');
const path = require('path');

const tv = require('..');

let dirPath = process.cwd();
let ticks = 0;

const CLOCK = { win: 'clockWin', time: 'clockTime', ticks: 'clockTicks', note: 'clockNote' };
const DIR = { win: 'dirWin', list: 'dirList', info: 'dirInfo' };

/* ---------------------------------------------------------------- */
/*  Clock: proof that Node's timers still run                       */
/* ---------------------------------------------------------------- */

function openClock() {
  if (tv.exists(CLOCK.win)) return tv.focus(CLOCK.win);

  tv.window({
    id: CLOCK.win,
    title: 'Clock',
    rect: [48, 1, 79, 10],
    items: [
      { id: CLOCK.time, type: 'staticText', rect: [2, 1, 29, 2], text: '--:--:--' },
      { id: CLOCK.ticks, type: 'staticText', rect: [2, 3, 29, 4], text: 'ticks: 0' },
      { id: CLOCK.note, type: 'staticText', rect: [2, 5, 29, 8],
        text: 'Painted by setInterval, from inside Node\'s event loop.' },
    ],
  });
  paintClock();
}

function paintClock() {
  if (!tv.exists(CLOCK.time)) return;
  tv.setText(CLOCK.time, new Date().toLocaleTimeString());
  tv.setText(CLOCK.ticks, `ticks: ${ticks}`);
}

setInterval(() => {
  ticks += 1;
  paintClock();
}, 1000);

/* ---------------------------------------------------------------- */
/*  Directory: proof that async I/O still runs                      */
/* ---------------------------------------------------------------- */

function openDirectory() {
  if (tv.exists(DIR.win)) {
    tv.focus(DIR.win);
    return refreshDirectory();
  }

  tv.window({
    id: DIR.win,
    title: `Directory: ${short(dirPath)}`,
    rect: [1, 1, 47, 21],
    items: [
      { id: DIR.list, type: 'listBox', rect: [2, 1, 42, 16] },
      { id: DIR.info, type: 'staticText', rect: [2, 17, 43, 18], text: 'reading...' },
    ],
  });
  refreshDirectory();
}

async function refreshDirectory() {
  try {
    const entries = await fsp.readdir(dirPath, { withFileTypes: true });
    const names = entries
      .map((e) => (e.isDirectory() ? `${e.name}/` : e.name))
      .sort((a, b) => a.localeCompare(b));

    // The await gave the user time to close the window out from under us.
    if (!tv.exists(DIR.list)) return;
    tv.setItems(DIR.list, ['../', ...names]);
    tv.setText(DIR.info, `${names.length} entries, read while the UI ran`);
  } catch (err) {
    if (tv.exists(DIR.info)) tv.setText(DIR.info, `error: ${err.code || err.message}`);
  }
}

async function describe(name) {
  const target = path.resolve(dirPath, name);
  try {
    const st = await fsp.stat(target);
    const what = st.isDirectory() ? 'directory' : `${st.size} bytes`;
    if (tv.exists(DIR.info)) tv.setText(DIR.info, `${name}  --  ${what}`);
  } catch (err) {
    if (tv.exists(DIR.info)) tv.setText(DIR.info, `${name}  --  ${err.code}`);
  }
}

function short(p) {
  const home = process.env.HOME || '';
  const s = home && p.startsWith(home) ? `~${p.slice(home.length)}` : p;
  return s.length > 32 ? `...${s.slice(-29)}` : s;
}

/* ---------------------------------------------------------------- */
/*  The application                                                 */
/* ---------------------------------------------------------------- */

tv.start({
  menuBar: [
    {
      title: '~F~ile',
      key: 'Alt-F',
      items: [
        { title: '~D~irectory window', cmd: 'openDir', key: 'Alt-D', shortcut: 'Alt-D' },
        { title: '~G~o to...', cmd: 'goto', key: 'Alt-G', shortcut: 'Alt-G' },
        { separator: true },
        { title: 'E~x~it', cmd: 'quit', key: 'Alt-X', shortcut: 'Alt-X' },
      ],
    },
    {
      title: '~V~iew',
      key: 'Alt-V',
      items: [
        { title: '~C~lock', cmd: 'openClock', key: 'Alt-C', shortcut: 'Alt-C' },
        { title: '~R~efresh directory', cmd: 'refresh', key: 'F5', shortcut: 'F5' },
        { separator: true },
        { title: '~A~bout', cmd: 'about' },
      ],
    },
  ],

  statusLine: [
    { text: '~Alt-X~ Exit', key: 'Alt-X', cmd: 'quit' },
    { text: '~Alt-D~ Directory', key: 'Alt-D', cmd: 'openDir' },
    { text: '~Alt-C~ Clock', key: 'Alt-C', cmd: 'openClock' },
    { text: '', key: 'F10', cmd: 'menu' },
  ],

  async onCommand(cmd) {
    tv.log('command:', cmd);

    switch (cmd) {
      case 'openDir':
        return openDirectory();

      case 'openClock':
        return openClock();

      case 'refresh':
        return refreshDirectory();

      case 'goto': {
        // Modal, and awaited: input goes only to this dialog, but the clock
        // behind it keeps running.
        const answer = await tv.dialog({
          title: 'Go to directory',
          rect: [15, 6, 65, 14],
          items: [
            { id: 'pathInput', type: 'inputLine', rect: [3, 3, 46, 4], maxLen: 200, value: dirPath },
            { type: 'label', rect: [2, 2, 20, 3], text: '~D~irectory:', for: 'pathInput' },
            { type: 'button', rect: [12, 5, 22, 7], title: '~O~K', cmd: 'ok', default: true },
            { type: 'button', rect: [26, 5, 36, 7], title: 'Cancel', cmd: 'cancel' },
          ],
        });

        tv.log('goto:', answer);
        if (answer.cmd === 'ok' && answer.values.pathInput) {
          dirPath = path.resolve(answer.values.pathInput);
          openDirectory();
        }
        return undefined;
      }

      case 'about':
        return tv.messageBox(
          `Turbo Vision, driven by Node ${process.version}.\n` +
            `The event loop is Node's; TVision is a guest in it.`
        );

      default:
        return undefined;
    }
  },

  // List boxes report their selection here.
  onSelect(id, index, text) {
    tv.log('select:', id, index, text);
    if (id !== DIR.list) return;

    if (text === '../') {
      dirPath = path.dirname(dirPath);
      openDirectory();
      return;
    }
    describe(text.endsWith('/') ? text.slice(0, -1) : text);
  },

  onExit() {
    console.log('demo exited cleanly; ticks while it ran:', ticks);
    process.exit(0);
  },
});

// Note where control is right now: start() returned, and Node is idle-looping
// on its own event loop with a Turbo Vision app painted on the terminal.
tv.log('start() returned; node is running the show');
