'use strict';

// A port of tvdemo's ASCII chart (tvision/examples/tvdemo/ascii.cpp).
//
// The original is a TView subclass with its own draw() and handleEvent() --
// nothing in the stock widget set can express it. Here the drawing is a
// `canvas`: JS hands over the lines, TVision paints them, and keystrokes come
// back to JS as names. The model (which character is selected) lives entirely
// in JavaScript.
//
// A corner case worth knowing about: magiblot's TVision draws Unicode, while
// the 1994 original wrote raw code page 437 cells. String.fromCharCode(n) is
// therefore *not* what the C++ chart shows -- codes 128-159 are C1 controls in
// Unicode and come out as replacement characters. The CP437 table below is the
// translation, and having to write it is the point: what a canvas paints is
// whatever JS decides, down to the character.

const tv = require('..');

const COLS = 32;
const ROWS = 8;

let cursor = { x: 0, y: 0 };

// Code page 437, as Unicode. Eight rows of exactly 32.
const CP437 =
  ' \u263a\u263b\u2665\u2666\u2663\u2660\u2022\u25d8\u25cb\u25d9\u2642\u2640\u266a\u266b\u263c' +
  '\u25ba\u25c4\u2195\u203c\u00b6\u00a7\u25ac\u21a8\u2191\u2193\u2192\u2190\u221f\u2194\u25b2\u25bc' +
  ' !"#$%&\'()*+,-./0123456789:;<=>?' +
  '@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_' +
  '`abcdefghijklmnopqrstuvwxyz{|}~\u2302' +
  '\u00c7\u00fc\u00e9\u00e2\u00e4\u00e0\u00e5\u00e7\u00ea\u00eb\u00e8\u00ef\u00ee\u00ec\u00c4\u00c5' +
  '\u00c9\u00e6\u00c6\u00f4\u00f6\u00f2\u00fb\u00f9\u00ff\u00d6\u00dc\u00a2\u00a3\u00a5\u20a7\u0192' +
  '\u00e1\u00ed\u00f3\u00fa\u00f1\u00d1\u00aa\u00ba\u00bf\u2310\u00ac\u00bd\u00bc\u00a1\u00ab\u00bb' +
  '\u2591\u2592\u2593\u2502\u2524\u2561\u2562\u2556\u2555\u2563\u2551\u2557\u255d\u255c\u255b\u2510' +
  '\u2514\u2534\u252c\u251c\u2500\u253c\u255e\u255f\u255a\u2554\u2569\u2566\u2560\u2550\u256c\u2567' +
  '\u2568\u2564\u2565\u2559\u2558\u2552\u2553\u256b\u256a\u2518\u250c\u2588\u2584\u258c\u2590\u2580' +
  '\u03b1\u00df\u0393\u03c0\u03a3\u03c3\u00b5\u03c4\u03a6\u0398\u03a9\u03b4\u221e\u03c6\u03b5\u2229' +
  '\u2261\u00b1\u2265\u2264\u2320\u2321\u00f7\u2248\u00b0\u2219\u00b7\u221a\u207f\u00b2\u25a0 ';

function glyph(code) {
  return CP437[code] || ' ';
}

function chartLines() {
  const lines = [];
  for (let y = 0; y < ROWS; y++) {
    let line = '';
    for (let x = 0; x < COLS; x++) line += glyph(y * COLS + x);
    lines.push(line);
  }
  return lines;
}

function selected() {
  return cursor.y * COLS + cursor.x;
}

function describe() {
  const code = selected();
  // 32 columns, no more: a staticText silently drops what does not fit.
  return `Char ${glyph(code)}  Dec ${String(code).padStart(3)}  ` +
         `Hex ${code.toString(16).toUpperCase().padStart(2, '0')}`;
}

function refresh() {
  tv.setCursor('chart', cursor.x, cursor.y);
  tv.setText('report', describe());
}

function moveTo(x, y) {
  cursor = {
    x: Math.max(0, Math.min(COLS - 1, x)),
    y: Math.max(0, Math.min(ROWS - 1, y)),
  };
  refresh();
}

function openChart() {
  if (tv.exists('chartWin')) return tv.focus('chartWin');

  tv.window({
    id: 'chartWin',
    title: 'ASCII Chart',
    rect: [8, 3, 8 + COLS + 4, 3 + ROWS + 5],
    items: [
      { id: 'chart', type: 'canvas', rect: [2, 1, 2 + COLS, 1 + ROWS],
        lines: chartLines(), cursor: 'block', color: 6 },
      { id: 'report', type: 'staticText', rect: [2, ROWS + 2, 2 + COLS, ROWS + 3],
        text: '' },
    ],
  });
  refresh();
}

tv.start({
  menuBar: [
    {
      title: '~C~hart',
      key: 'Alt-C',
      items: [
        { title: '~A~SCII table', cmd: 'chart', key: 'Alt-A', shortcut: 'Alt-A' },
        { separator: true },
        { title: 'E~x~it', cmd: 'quit', key: 'Alt-X', shortcut: 'Alt-X' },
      ],
    },
  ],

  statusLine: [
    { text: '~Alt-X~ Exit', key: 'Alt-X', cmd: 'quit' },
    { text: '~Alt-A~ Chart', key: 'Alt-A', cmd: 'chart' },
    { text: 'Arrows move, Home/End jump' },
    { text: '', key: 'F10', cmd: 'menu' },
  ],

  onCommand(cmd) {
    if (cmd === 'chart') openChart();
  },

  // The canvas has focus, so its keys arrive here by name rather than being
  // handled inside TVision.
  onKey(id, key) {
    if (id !== 'chart') return;
    tv.log('key:', key);

    switch (key) {
      case 'Left':  return moveTo(cursor.x - 1, cursor.y);
      case 'Right': return moveTo(cursor.x + 1, cursor.y);
      case 'Up':    return moveTo(cursor.x, cursor.y - 1);
      case 'Down':  return moveTo(cursor.x, cursor.y + 1);
      case 'Home':  return moveTo(0, 0);
      case 'End':   return moveTo(COLS - 1, ROWS - 1);
      default:
        // Any printable key jumps to that character, as the original does.
        if (key.length === 1) {
          const code = key.charCodeAt(0);
          return moveTo(code % COLS, Math.floor(code / COLS));
        }
        return undefined;
    }
  },

  onClick(id, x, y) {
    if (id === 'chart') moveTo(x, y);
  },

  onExit() {
    console.log(`ascii chart exited; last selection was ${selected()}`);
  },
});

openChart();
