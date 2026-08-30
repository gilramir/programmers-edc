'use strict';

// Regression: a dialog with a pre-filled input line.
//
// TInputLine(bounds, limit) stores maxLen = limit - 1 and allocates
// maxLen + 1 bytes, so writing the terminator at [limit] runs one byte past
// the end of the block. It corrupted the heap silently and aborted later --
// "free(): invalid size" -- when the dialog was destroyed, which made it look
// like a TVision bug rather than ours.
//
// Open the dialog, dismiss it, repeat -- which now also exercises the modal
// session stack: begin/finish bookkeeping, the promise, and destroying the
// view from the pump. Under TVNODE_ASAN=1 the bad write is caught on the first
// round; without ASAN it takes a few, if it aborts at all.

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

async function run() {
  while (round < ROUNDS) {
    round += 1;
    await openOne();
  }
  tv.quit();
}

function openOne() {
  return tv.dialog({
    title: `Round ${round}`,
    rect: [10, 5, 70, 13],
    items: [
      { id: 'input', type: 'inputLine', rect: [3, 3, 55, 4], maxLen: 200,
        value: 'x'.repeat(199) },
      { type: 'button', rect: [20, 5, 30, 7], title: 'OK', cmd: 'ok', default: true },
    ],
  });
}

run();
