'use strict';

// A window to move and resize, and a counter that says whether Node is alive.
//
// Turbo Vision moves a window inside `TView::dragView`, which is a nested
// `getEvent` loop -- so under the pump the whole of Node stopped for as long as
// the gesture lasted, and with `eventTimeoutMs` at 0 it stopped while spinning
// a core. Off the Window menu it never ended on its own: the mode swallows the
// mouse, the menu bar and Alt-X, and on a maximized window the size limits pin
// every arrow key, so nothing on screen changes and it reads as a hang.
//
// The counter is the assertion the drivers are really about. It is painted by
// a plain setInterval, so a number that keeps climbing while the window is held
// is Node's event loop still getting a turn -- the same thing demo.js's clock
// says about dialogs, said about drags.

const tv = require('..');

const WIN = 'dragWin';
const TICKS = 'dragTicks';

// `node regress_drag.js maxed` opens the window filling the desktop instead of
// at a fixed rectangle, which is the other half of what this fixture is for.
//
// A window built at its maximum size has `zoomRect` equal to its own bounds,
// so `TWindow::zoom` restores it to where it already is and the zoom box does
// nothing -- while `TFrame::draw` goes on drawing `[↕]`, the un-zoom box,
// because the only thing that decides which icon it draws is whether the
// window is at its maximum. `JsWindow::zoom` is what gives it somewhere to go,
// by noticing that restoring would not move it.
//
// Opened from `onResize` rather than from a constant, because that is the only
// honest way to fill a desktop whose size the program does not know yet -- and
// it is how predc's environment list, where this was reported, does it.
const MAXED = process.argv[2] === 'maxed';

let ticks = 0;
let opened = false;

setInterval(() => {
  ticks += 1;
  if (tv.exists(TICKS)) tv.setText(TICKS, `ticks: ${ticks}`);
}, 100);

tv.start({
  menuBar: [
    {
      title: '~W~indow',
      key: 'Alt-W',
      items: [
        { title: '~R~esize/move', cmd: 'resize', key: 'Ctrl-F5', shortcut: 'Ctrl-F5' },
        { title: '~Z~oom', cmd: 'zoom', key: 'F5', shortcut: 'F5' },
        { separator: true },
        { title: 'E~x~it', cmd: 'quit', key: 'Alt-X', shortcut: 'Alt-X' },
      ],
    },
  ],

  statusLine: [
    { text: '~Alt-X~ Exit', key: 'Alt-X', cmd: 'quit' },
    { text: '~Ctrl-F5~ Size/Move', key: 'Ctrl-F5', cmd: 'resize' },
  ],

  onCommand(cmd) {
    if (cmd === 'quit') tv.quit();
  },

  onResize(cols, rows) {
    if (!MAXED || opened) return;
    opened = true;
    openWindow([0, 0, cols, rows]);
  },

  onExit() {
    console.log('drag regress exited cleanly; ticks while it ran:', ticks);
    process.exit(0);
  },
});

function openWindow(rect) {
  tv.window({
    id: WIN,
    title: 'Ticker',
    rect,
    items: [
      { id: TICKS, type: 'staticText', rect: [2, 1, 20, 2], text: 'ticks: 0' },
    ],
  });
}

// Small, and away from every edge, so that all four arrow keys have somewhere
// to go and both grow corners are reachable without leaving the desktop. The
// maximized one waits for onResize instead.
if (!MAXED) openWindow([20, 4, 60, 14]);
