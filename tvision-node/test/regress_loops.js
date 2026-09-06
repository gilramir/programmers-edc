'use strict';

// One of everything that tracks the mouse inside a loop of its own.
//
// `TView::dragView` was rewritten because it was a nested `getEvent` loop with
// no way out, and the commit that did it listed the loops that were left --
// a button, a check box, a scroll bar, a list viewer, an input line, the
// editor, the status line and the close box -- and said they were fine,
// because they end when the finger comes up. What it did *not* list is
// `TGroup::execView`, which is a nested loop of a different kind: the menu bar
// and the context menu run in one and are documented, and so does
// `THistoryWindow` (thistory.cpp:101), which nobody has ever written down.
//
// A history drop-down is a modal window opened from inside `TInputLine`'s
// event handler. `JsHistory::openDropDown` already replaces Borland's
// `owner->execView()` with `openLocalModal`, and the comment there says in
// as many words that the model keeps running behind it -- but nothing has ever
// checked that it does, and the difference is invisible: a frozen program and
// a live one draw the same drop-down.
//
// **The counter is the assertion.** `ticks:` is painted by a plain
// setInterval, so a number that climbs while something is held or open is
// Node's event loop still getting a turn. The CPU is the other one: with
// `eventTimeoutMs` at 0 a nested loop polls without ever sleeping, which is
// 100 ticks a second of nothing.

const tv = require('..');

const WIN = 'loopWin';
const TICKS = 'loopTicks';
const FIELD = 'loopField';

const HEARD = 'loopHeard';

let ticks = 0;
let heard = 0;

setInterval(() => {
  ticks += 1;
  if (tv.exists(TICKS)) tv.setText(TICKS, `ticks: ${ticks}`);
}, 100);

// Every callback a gesture here can produce, counted into one number on the
// screen. A hold that missed its widget is quiet, and quiet is exactly what
// the CPU checks are looking for -- so each of them needs something that says
// the press landed, and this is it.
function note(what) {
  heard += 1;
  if (tv.exists(HEARD)) tv.setText(HEARD, `heard: ${heard} ${what}`);
}

tv.start({
  menuBar: [
    {
      title: '~W~indow',
      key: 'Alt-W',
      items: [{ title: 'E~x~it', cmd: 'quit', key: 'Alt-X', shortcut: 'Alt-X' }],
    },
  ],

  // Two entries, and the second one is what a test can hold: pressing the
  // first and letting go quits, which ends the program rather than measuring
  // it.
  statusLine: [
    { text: '~Alt-X~ Exit', key: 'Alt-X', cmd: 'quit' },
    { text: '~F2~ Note', key: 'F2', cmd: 'noted' },
  ],

  onCommand(cmd) {
    if (cmd === 'quit') tv.quit();
    else note(cmd);
  },

  onSelect(id) { note(`select ${id}`); },
  onFocus(id) { note(`focus ${id}`); },
  onScroll(id, value) { note(`scroll ${id}=${value}`); },
  onChange(id, value) { note(`change ${id}=${JSON.stringify(value)}`); },

  onExit() {
    console.log('loops regress exited cleanly; ticks while it ran:', ticks);
    process.exit(0);
  },
});

// A window rather than a dialog, so that it stays up and every gesture can be
// tried against it in turn. The history icon has no rectangle of its own -- it
// goes in the three columns right of its field, the way every Turbo Vision
// dialog puts one -- so the field stops short of the frame to leave room.
tv.window({
  id: WIN,
  title: 'Loops',
  rect: [4, 2, 70, 20],
  items: [
    { id: TICKS, type: 'staticText', rect: [2, 1, 20, 2], text: 'ticks: 0' },
    { id: HEARD, type: 'staticText', rect: [22, 1, 62, 2], text: 'heard: 0' },
    { id: FIELD, type: 'inputLine', rect: [2, 3, 40, 4], maxLen: 60, value: '' },
    { id: 'loopHist', type: 'history', for: FIELD,
      items: ['alpha', 'beta', 'gamma', 'delta'] },
    { id: 'loopButton', type: 'button', rect: [2, 5, 16, 7], title: '~P~ress',
      cmd: 'pressed' },
    { id: 'loopCheck', type: 'checkBoxes', rect: [20, 5, 40, 7],
      items: ['one', 'two'], value: [] },
    { id: 'loopBar', type: 'scrollBar', rect: [60, 3, 61, 15],
      value: 5, min: 0, max: 20, pageStep: 5 },
    { id: 'loopList', type: 'listBox', rect: [2, 8, 40, 15], focused: 0,
      items: ['row 0', 'row 1', 'row 2', 'row 3', 'row 4', 'row 5', 'row 6',
              'row 7', 'row 8', 'row 9', 'row 10', 'row 11'] },
  ],
});
