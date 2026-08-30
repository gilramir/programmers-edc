'use strict';

// Regression: a dialog with a pre-filled input line.
//
// TInputLine(bounds, limit) stores maxLen = limit - 1 and allocates
// maxLen + 1 bytes, so writing the terminator at [limit] runs one byte past
// the end of the block. It corrupted the heap silently and aborted later --
// "free(): invalid size" -- when the dialog was destroyed, which made it look
// like a TVision bug rather than ours.
//
// Open the dialog, cancel it, repeat. Under -Dasan=1 the bad write is caught
// on the first one; without ASAN it takes a few rounds to abort, if at all.

const tv = require('..');

const ROUNDS = 5;
let round = 0;

tv.start({
  statusLine: [{ text: '~Esc~ next', key: 'Esc', cmd: 'cancel' }],

  onCommand() {},

  onExit() {
    console.log(`inputline regression: survived ${round} dialogs`);
    process.exit(0);
  },
});

// The dialog is modal, so this runs one round per turn of the pump rather than
// in a loop -- setImmediate hands control back so the app can actually draw.
function next() {
  if (round >= ROUNDS) {
    tv.quit();
    return;
  }
  round += 1;
  tv.dialog({
    title: `Round ${round}`,
    rect: [10, 5, 70, 13],
    items: [
      { id: 'input', type: 'inputLine', rect: [3, 3, 55, 4], maxLen: 200,
        value: 'x'.repeat(199) },
      { type: 'button', rect: [20, 5, 30, 7], title: 'OK', cmd: 'ok', default: true },
    ],
  });
  setImmediate(next);
}

setImmediate(next);
