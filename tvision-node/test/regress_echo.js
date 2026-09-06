'use strict';

// A field the model writes must not come back as the user's event.
//
// Two parties move a widget's state. The user moves it with a key, a click or
// the wheel, and that has to be reported, because it is how the model learns
// what the user did. The model moves it by rendering a different value, and
// that has to work, because it is how a re-sorted list keeps the row somebody
// was looking at. If the binding reports the second as though it were the
// first, the model stores what it hears and writes back what it stored:
//
//     model writes focused = 3
//       -> C++ moves the highlight to 3
//       -> Focused { index = 3 } arrives at the model
//       -> the model stores 3
//       -> the next render writes focused = 3
//
// A loop, held together only by the two values happening to agree. They agree
// for an arrow key, because nobody presses one faster than the model renders.
// They stop agreeing for a wheel, which arrives as a burst -- and that is
// exactly how it was found, from a real terminal, with 935 pty checks green.
//
// `JsListBox::setFocused` was fixed with a `quiet` flag. Nothing checks the
// other five widgets, and there is no reason to think the next one added will
// get it right by itself: the failure is silent, it needs a burst to show, and
// every screen involved looks correct.
//
// **The exception is the interesting half.** A write the widget could not
// honour -- a `focused` past the end of a shortened list -- *is* reported,
// because that is a disagreement rather than an action and it settles in one
// round. So a sweep that only asserted silence would be asserting a bug.
//
// The fixture is driven by keys, one per programmatic write, and every
// callback it hears goes into a counter on the screen. A driver presses a key
// and looks at the counter: unchanged is the model's write staying quiet,
// and one more is the widget saying it could not do as it was told.

const tv = require('..');

const HEARD = 'echoHeard';
const LIST = 'echoList';
const BAR = 'echoBar';
const FIELD = 'echoField';
const CHECK = 'echoCheck';

const TEN = ['row 0', 'row 1', 'row 2', 'row 3', 'row 4',
             'row 5', 'row 6', 'row 7', 'row 8', 'row 9'];

let heard = 0;
let last = '';

function note(what) {
  heard += 1;
  last = what;
  if (tv.exists(HEARD)) tv.setText(HEARD, `heard: ${heard} ${what}`);
}

// One key per write the model can make. The letters are what the driver
// presses; each does exactly one thing so that a counter that moved names it.
const WRITES = {
  // The one that was broken, and the one it was fixed with.
  f: () => tv.setValue(LIST, 3),               // move the highlight
  g: () => tv.setValue(LIST, 7),               // move it again
  i: () => tv.setItems(LIST, TEN.slice(0, 4)), // a shorter list, highlight still in it
  t: () => tv.setListTop(LIST, 2),             // scroll without moving the highlight

  // The five nobody has ever checked.
  b: () => tv.setValue(BAR, 12),               // a scroll bar's thumb
  x: () => tv.setValue(FIELD, 'written'),      // an input line's text
  c: () => tv.setValue(CHECK, [1]),            // a check box's ticks
  e: () => tv.setViewEnabled(BAR, false),
  v: () => tv.setViewVisible(BAR, true),

  // And the exception: a highlight the list cannot honour, because the list
  // it is being asked for is shorter than the index. This one *must* be
  // reported -- silence here is the tree that collapses itself.
  k: () => {
    tv.setItems(LIST, TEN.slice(0, 2));
    tv.setValue(LIST, 8);
  },

  // Put it back, so the driver can carry on from a known list.
  r: () => {
    tv.setItems(LIST, TEN);
    tv.setValue(LIST, 0);
  },
};

tv.start({
  menuBar: [
    {
      title: '~W~indow',
      key: 'Alt-W',
      items: [{ title: 'E~x~it', cmd: 'quit', key: 'Alt-X', shortcut: 'Alt-X' }],
    },
  ],

  statusLine: [{ text: '~Alt-X~ Exit', key: 'Alt-X', cmd: 'quit' }],

  onCommand(cmd) {
    if (cmd === 'quit') tv.quit();
    else note(`command ${cmd}`);
  },

  // Every way a widget can tell the model something. All of them count,
  // because the question is not "did the right event arrive" but "did any
  // event arrive at all for something the model itself did".
  onSelect(id, index) { note(`select ${id}=${index}`); },
  onFocus(id, index) { note(`focus ${id}=${index}`); },
  onScroll(id, value) { note(`scroll ${id}=${value}`); },
  onChange(id, value) { note(`change ${id}=${JSON.stringify(value)}`); },

  onKey(id, key) {
    const write = WRITES[key];
    if (write) write();
  },

  onExit() {
    console.log(`echo regress exited cleanly; heard ${heard}, last ${last}`);
    process.exit(0);
  },
});

tv.window({
  id: 'echoWin',
  title: 'Echo',
  rect: [2, 2, 70, 20],
  items: [
    { id: HEARD, type: 'staticText', rect: [2, 1, 60, 2], text: 'heard: 0' },
    // `takesKeys` so that the letters above reach `onKey` rather than being
    // eaten as list navigation. The list is what the keys act *on*, not what
    // they are typed into.
    { id: 'echoKeys', type: 'canvas', rect: [2, 2, 60, 4],
      lines: ['press a letter; each one is one programmatic write'] },
    { id: LIST, type: 'listBox', rect: [2, 5, 30, 12], focused: 0, items: TEN },
    { id: BAR, type: 'scrollBar', rect: [60, 5, 61, 12],
      value: 5, min: 0, max: 20, pageStep: 5 },
    { id: FIELD, type: 'inputLine', rect: [32, 5, 58, 6], maxLen: 40, value: '' },
    { id: CHECK, type: 'checkBoxes', rect: [32, 8, 58, 10],
      items: ['one', 'two'], value: [] },
  ],
});
