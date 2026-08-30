'use strict';

// Unit tests for the diff layer, against a fake binding.
//
// Every one of these corresponds to a bug that actually happened. They run in
// milliseconds and need no terminal, which is the whole argument for having
// pulled diff.js out of the runtime.

const test = require('node:test');
const assert = require('node:assert');

const { createDiffer, sameShape } = require('../diff');

/** Records what the runtime asked the binding to do. */
function fakeTv(initiallyOpen = []) {
  const open = new Set(initiallyOpen);
  const calls = [];
  return {
    calls,
    open,
    exists: (id) => open.has(id),
    window: (spec) => {
      open.add(spec.id);
      calls.push(['window', spec.id]);
    },
    close: (id) => {
      open.delete(id);
      calls.push(['close', id]);
    },
    setTitle: (id, title) => calls.push(['setTitle', id, title]),
    setText: (id, text) => calls.push(['setText', id, text]),
    setValue: (id, value) => calls.push(['setValue', id, value]),
    setItems: (id, items) => calls.push(['setItems', id, items]),
    setLines: (id, lines) => calls.push(['setLines', id, lines]),
  };
}

const win = (over = {}) => ({
  id: 'w',
  title: 'Title',
  rect: [1, 1, 40, 10],
  items: [{ type: 'staticText', id: 't', rect: [2, 1, 30, 2], text: 'hello' }],
  ...over,
});

test('a window in the view but not on screen is created', () => {
  const tv = fakeTv();
  createDiffer(tv).apply([win()]);
  assert.deepEqual(tv.calls, [['window', 'w']]);
});

test('a window that leaves the view is closed', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([win()]);
  tv.calls.length = 0;
  differ.apply([]);
  assert.deepEqual(tv.calls, [['close', 'w']]);
});

test('an unchanged view is not touched', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([win()]);
  tv.calls.length = 0;
  differ.apply([win()]);
  assert.deepEqual(tv.calls, [], 'a re-render of the same UI should do nothing');
});

test('changed text is patched, not rebuilt', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([win()]);
  tv.calls.length = 0;
  differ.apply([
    win({ items: [{ type: 'staticText', id: 't', rect: [2, 1, 30, 2], text: 'goodbye' }] }),
  ]);
  assert.deepEqual(tv.calls, [['setText', 't', 'goodbye']]);
});

test('a changed title is patched, not rebuilt', () => {
  // The bug: "Entries (3)" -> "Entries (4)" tore the window down on every
  // update, losing focus and z-order.
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([win()]);
  tv.calls.length = 0;
  differ.apply([win({ title: 'Title (2)' })]);
  assert.deepEqual(tv.calls, [['setTitle', 'w', 'Title (2)']]);
});

test('a structural change rebuilds the window', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([win()]);
  tv.calls.length = 0;
  differ.apply([win({ rect: [1, 1, 50, 10] })]);
  assert.deepEqual(tv.calls, [['close', 'w'], ['window', 'w']]);
});

test('an input line is written only when the model changed it', () => {
  // The bug this prevents: the user types, the model does not know, and the
  // next render writes the stale model value back over their keystrokes.
  const tv = fakeTv();
  const differ = createDiffer(tv);
  const field = (value) => win({
    items: [{ type: 'inputLine', id: 'f', rect: [2, 1, 30, 2], maxLen: 40, value }],
  });

  differ.apply([field('')]);
  tv.calls.length = 0;

  differ.apply([field('')]);          // the user has been typing; the model has not changed
  assert.deepEqual(tv.calls, [], 'an unchanged model value must not be written back');

  differ.apply([field('set by the model')]);
  assert.deepEqual(tv.calls, [['setValue', 'f', 'set by the model']]);
});

test('list and canvas contents are compared by value', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  const listed = (items) => win({
    items: [{ type: 'listBox', id: 'l', rect: [2, 1, 30, 8], items }],
  });

  differ.apply([listed(['a', 'b'])]);
  tv.calls.length = 0;
  differ.apply([listed(['a', 'b'])]);
  assert.deepEqual(tv.calls, [], 'equal arrays are not a change');
  differ.apply([listed(['a', 'b', 'c'])]);
  assert.deepEqual(tv.calls, [['setItems', 'l', ['a', 'b', 'c']]]);
});

test('a window the user closed is reopened by the next render', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([win()]);
  tv.open.delete('w'); // the user closed it from its frame
  tv.calls.length = 0;
  differ.apply([win()]);
  assert.deepEqual(tv.calls, [['window', 'w']]);
});

test('our own closes are not reported as the user closing a window', () => {
  // The bug: the runtime closed a window to rebuild it, the notification came
  // back asynchronously, and the program was told the user had closed it --
  // so the model dropped a window it had just asked for.
  const closed = [];
  const tv = fakeTv();
  const differ = createDiffer(tv, (id) => closed.push(id));

  differ.apply([win()]);
  differ.apply([]);                 // we close it
  differ.windowClosed('w');         // ... and the notification arrives later
  assert.deepEqual(closed, [], 'a close we asked for must not be reported');

  differ.windowClosed('w');         // now the user closes one
  assert.deepEqual(closed, ['w'], 'a close we did not ask for must be reported');
});

test('sameShape ignores the mutable fields and nothing else', () => {
  const a = win();
  assert.equal(sameShape(a, win({ title: 'other' })), true, 'title is patchable');
  assert.equal(
    sameShape(a, win({ items: [{ ...a.items[0], text: 'other' }] })),
    true,
    'text is patchable'
  );
  assert.equal(
    sameShape(a, win({ items: [{ ...a.items[0], id: 'other' }] })),
    false,
    'an id is structural'
  );
  assert.equal(sameShape(undefined, a), false, 'nothing is not the same shape as something');
});
