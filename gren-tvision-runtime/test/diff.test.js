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
    built: [],
    window(spec) {
      open.add(spec.id);
      // The whole spec as well as the call, because what a rebuilt window is
      // built *at* is a thing worth asserting and the id alone cannot say it.
      this.built.push(spec);
      calls.push(['window', spec.id]);
    },
    close: (id) => {
      open.delete(id);
      calls.push(['close', id]);
    },
    setTitle: (id, title) => calls.push(['setTitle', id, title]),
    setBounds: (id, rect) => calls.push(['setBounds', id, rect]),
    setText: (id, text) => calls.push(['setText', id, text]),
    setValue: (id, value) => calls.push(['setValue', id, value]),
    setItems: (id, items) => calls.push(['setItems', id, items]),
    setLines: (id, lines) => calls.push(['setLines', id, lines]),
    setCursor: (id, x, y, visible) => calls.push(['setCursor', id, x, y, visible]),
    setScroll: (...args) => calls.push(['setScroll', ...args]),
    setViewEnabled: (id, on) => calls.push(['setViewEnabled', id, on]),
    setWindowFlags: (id, flags) => calls.push(['setWindowFlags', id, flags]),
    setViewVisible: (id, on) => calls.push(['setViewVisible', id, on]),
    bringToFront: (id) => calls.push(['bringToFront', id]),
    setListTop: (id, top) => calls.push(['setListTop', id, top]),
    setItemsEnabled: (id, flags) => calls.push(['setItemsEnabled', id, flags]),
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
  differ.apply([win({ items: [{ ...win().items[0], id: 'other' }] })]);
  assert.deepEqual(tv.calls, [['close', 'w'], ['window', 'w']]);
});

test('a resized window is moved in place, not rebuilt', () => {
  // Rebuilding it would throw away the caret, the scroll position and the
  // list highlight -- and would skip TGroup::changeBounds, which is the only
  // thing that resolves a child view's growMode. A model that lays out
  // against the terminal size sends a new rectangle on every resize, so this
  // is the common case rather than the rare one.
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([win()]);
  tv.calls.length = 0;
  differ.apply([win({ rect: [1, 1, 50, 10] })]);
  assert.deepEqual(tv.calls, [['setBounds', 'w', [1, 1, 50, 10]]]);
});

test('a window the model leaves where it was is not moved', () => {
  // The other half, and the one that lets Tile and Cascade survive: Turbo
  // Vision moves windows without telling anyone, and the model goes on
  // sending the rectangle it started with. Comparing against the last spec
  // applied rather than against the screen is what keeps that from snapping
  // the window back on the next render.
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([win()]);
  tv.calls.length = 0;
  differ.apply([win()]);
  assert.deepEqual(tv.calls, []);
});

// predc's time converter, whose Live clock button toggles its own caption:
// `~L~ive clock` becomes `~S~top clock`.
const clockWin = (over = {}) => ({
  id: 'w',
  title: 'Time',
  rect: [1, 1, 69, 18],
  items: [
    { type: 'button', id: 'b', rect: [28, 12, 42, 14], title: '~L~ive clock', cmd: 'clock' },
  ],
  ...over,
});

const stopped = (over = {}) =>
  clockWin({
    items: [
      { type: 'button', id: 'b', rect: [28, 12, 42, 14], title: '~S~top clock', cmd: 'clock' },
    ],
    ...over,
  });

// A window with a row added to it, which is structural however small: nothing
// can insert a view into a window but a rebuild.
const withRow = (over = {}) =>
  clockWin({
    items: [
      { type: 'button', id: 'b', rect: [28, 12, 42, 14], title: '~L~ive clock', cmd: 'clock' },
      { type: 'staticText', id: 'r', rect: [2, 10, 40, 11], text: 'UTC' },
    ],
    ...over,
  });

test('a button caption is patched, not rebuilt', () => {
  // It used to be structural, and the window predc's time converter rebuilt
  // for it went back to the model's rectangle and put the caret in the first
  // field. Both were in one recorded session, in that order.
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([clockWin()]);
  tv.calls.length = 0;

  differ.apply([stopped()]);
  assert.deepEqual(tv.calls, [['setText', 'b', '~S~top clock']]);
});

test('but a button whose command changed is still a new button', () => {
  // The caption says what pressing it does; the command *is* what pressing it
  // does, and there is no call that changes one. A model that swaps it is
  // asking for a different button and gets one.
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([clockWin()]);
  tv.calls.length = 0;

  differ.apply([
    clockWin({
      items: [
        { type: 'button', id: 'b', rect: [28, 12, 42, 14], title: '~L~ive clock', cmd: 'other' },
      ],
    }),
  ]);
  assert.deepEqual(tv.calls, [['close', 'w'], ['window', 'w']]);
});

test('a rebuilt window comes back where the user dragged it', () => {
  // Recorded, not imagined: /tmp/002.rec is a session where the time
  // converter was dragged from x=1 to x=6 and then the Live clock was
  // switched off, whose only visible effect should have been a button's
  // caption. The window jumped back to x=1, because a rebuild built it at the
  // rectangle in the description and the model had never heard of the drag.
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([clockWin()]);
  differ.windowMoved('w', [6, 1, 74, 18]);
  tv.calls.length = 0;
  tv.built.length = 0;

  differ.apply([withRow()]);
  assert.deepEqual(tv.calls, [['close', 'w'], ['window', 'w']]);
  assert.deepEqual(tv.built[0].rect, [6, 1, 74, 18]);
  assert.equal(tv.built[0].items.length, 2);
});

test('but the model moving it in the same render wins, and is not undone later', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([clockWin()]);
  differ.windowMoved('w', [6, 1, 74, 18]);
  tv.built.length = 0;

  differ.apply([withRow({ rect: [20, 4, 88, 21] })]);
  assert.deepEqual(tv.built[0].rect, [20, 4, 88, 21]);

  // And the drag is forgotten: a second rebuild goes where the model last
  // said, not back to where the user had it two renders ago.
  tv.built.length = 0;
  differ.apply([clockWin({ rect: [20, 4, 88, 21] })]);   // a row taken away again
  assert.deepEqual(tv.built[0].rect, [20, 4, 88, 21]);
});

test('and a setBounds forgets the drag too', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([clockWin()]);
  differ.windowMoved('w', [6, 1, 74, 18]);
  tv.calls.length = 0;

  // Same shape, new rectangle: moved in place rather than rebuilt.
  differ.apply([clockWin({ rect: [20, 4, 88, 21] })]);
  assert.deepEqual(tv.calls, [['setBounds', 'w', [20, 4, 88, 21]]]);

  tv.built.length = 0;
  differ.apply([withRow({ rect: [20, 4, 88, 21] })]);
  assert.deepEqual(tv.built[0].rect, [20, 4, 88, 21]);
});

test('a window the user closed and the model reopens forgets where they had it', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([clockWin()]);
  differ.windowMoved('w', [6, 1, 74, 18]);
  tv.open.delete('w');
  differ.windowClosed('w');
  tv.built.length = 0;

  differ.apply([clockWin()]);
  assert.deepEqual(tv.built[0].rect, [1, 1, 69, 18]);
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
    items: [{ type: 'listBox', id: 'l', rect: [2, 1, 30, 8], items, focused: 0 }],
  });

  differ.apply([listed(['a', 'b'])]);
  tv.calls.length = 0;
  differ.apply([listed(['a', 'b'])]);
  assert.deepEqual(tv.calls, [], 'equal arrays are not a change');
  differ.apply([listed(['a', 'b', 'c'])]);
  assert.deepEqual(tv.calls, [
    ['setItems', 'l', ['a', 'b', 'c']],
    ['setValue', 'l', 0],
  ]);
});

// Clusters and the list box highlight: state the user can change behind the
// model's back, which is exactly the case that must not be written back on
// every render.
const form = (over = {}) => ({
  id: 'f',
  title: 'Form',
  rect: [1, 1, 40, 10],
  items: [
    { type: 'checkBoxes', id: 'kind', rect: [2, 2, 20, 4], items: ['a', 'b'], value: [true, false] },
    { type: 'radioButtons', id: 'sex', rect: [22, 2, 38, 4], items: ['m', 'f'], value: 0 },
    { type: 'listBox', id: 'keys', rect: [2, 5, 20, 8], items: ['x', 'y'], focused: 0 },
  ],
  ...over,
});

const withItem = (index, over) => {
  const spec = form();
  spec.items = spec.items.map((view, i) => (i === index ? { ...view, ...over } : view));
  return spec;
};

test('cluster values are written only when the model changed them', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([form()]);
  tv.calls.length = 0;

  differ.apply([form()]);
  assert.deepEqual(tv.calls, [], 'a re-render must not undo what the user ticked');

  const ticked = withItem(0, { value: [true, true] });
  differ.apply([ticked]);
  assert.deepEqual(tv.calls, [['setValue', 'kind', [true, true]]]);

  tv.calls.length = 0;
  const chosen = { ...ticked, items: ticked.items.map((v, i) => (i === 1 ? { ...v, value: 1 } : v)) };
  differ.apply([chosen]);
  assert.deepEqual(tv.calls, [['setValue', 'sex', 1]], 'only the field that changed');
});

test('a cluster changing value does not rebuild the window', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([form()]);
  tv.calls.length = 0;
  differ.apply([withItem(0, { value: [false, true] })]);
  assert.ok(
    !tv.calls.some(([call]) => call === 'window'),
    'a ticked box is content, not structure'
  );
});

test('the highlight is set after the items that reset it', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([form()]);
  tv.calls.length = 0;

  // Both at once: setItems puts the highlight back on row 0, so the model's
  // choice has to be applied afterwards or it is lost.
  differ.apply([withItem(2, { items: ['y', 'x'], focused: 1 })]);
  assert.deepEqual(tv.calls, [
    ['setItems', 'keys', ['y', 'x']],
    ['setValue', 'keys', 1],
  ]);
});

test('a highlight the model does not move is left alone', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([form()]);
  tv.calls.length = 0;
  differ.apply([form()]);
  assert.deepEqual(tv.calls, [], 'the arrow keys own the highlight until the model says otherwise');
});

test('a canvas cursor is moved, and nulling it hides one', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  const chart = (cursorAt) => ({
    id: 'w',
    title: 'Chart',
    rect: [1, 1, 40, 10],
    items: [{ type: 'canvas', id: 'c', rect: [2, 1, 34, 9], lines: ['ab'], cursorAt }],
  });

  differ.apply([chart([0, 0])]);
  tv.calls.length = 0;

  differ.apply([chart([0, 0])]);
  assert.deepEqual(tv.calls, [], 'an unmoved cursor is not rewritten');

  differ.apply([chart([3, 2])]);
  assert.deepEqual(tv.calls, [['setCursor', 'c', 3, 2, true]]);

  tv.calls.length = 0;
  differ.apply([chart(null)]);
  assert.deepEqual(tv.calls, [['setCursor', 'c', 0, 0, false]], 'null means no cursor');
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
  assert.equal(sameShape(a, win({ rect: [1, 1, 50, 10] })), true, 'a rect is patchable');
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

test('a value the user changed is not written back to them', () => {
  // The controlled-input problem. The model is told what the user typed, keeps
  // it (which is the point of being told) and renders it straight back. If the
  // differ compared that against the value it last *applied*, it would see a
  // difference and write it into the field the user is typing in.
  const tv = fakeTv();
  const differ = createDiffer(tv);
  const field = (value) =>
    win({ items: [{ type: 'inputLine', id: 'f', rect: [2, 1, 30, 2], maxLen: 40, value }] });

  differ.apply([field('')]);
  tv.calls.length = 0;

  differ.valueChanged('f', 'ab');   // what the view now says
  differ.apply([field('ab')]);      // the model, echoing it back
  assert.deepEqual(tv.calls, []);
});

test('a value the model changed is still written', () => {
  // The other half: being told what the user typed must not make the field
  // read-only. A model that transforms what it was given -- upper-casing it,
  // rejecting a character -- has to be able to say so.
  const tv = fakeTv();
  const differ = createDiffer(tv);
  const field = (value) =>
    win({ items: [{ type: 'inputLine', id: 'f', rect: [2, 1, 30, 2], maxLen: 40, value }] });

  differ.apply([field('')]);
  tv.calls.length = 0;

  differ.valueChanged('f', 'ab');
  differ.apply([field('AB')]);
  assert.deepEqual(tv.calls, [['setValue', 'f', 'AB']]);
});

test('a change to an id no window has is ignored rather than thrown on', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([win()]);
  differ.valueChanged('nobody', 'x');   // must not throw
  tv.calls.length = 0;
  differ.apply([win()]);
  assert.deepEqual(tv.calls, []);
});

// --- the menu bar and status line ------------------------------------------

test('the first chrome is recorded, not applied', () => {
  // The application is built out of the first render, menu bar included, so
  // the differ must not also try to replace what does not exist yet.
  const tv = fakeTv();
  tv.setMenuBar = () => assert.fail('must not replace the menu bar before startup');
  tv.setStatusLine = () => assert.fail('must not replace the status line before startup');
  const differ = createDiffer(tv);
  assert.equal(differ.chrome([{ title: 'File' }], []), false, 'the first call reports "not applied"');
});

test('an unchanged menu bar is left alone', () => {
  const tv = fakeTv();
  tv.setMenuBar = () => assert.fail('nothing changed');
  tv.setStatusLine = () => assert.fail('nothing changed');
  const differ = createDiffer(tv);
  const menu = [{ title: 'File', key: 'Alt-F', items: [] }];
  differ.chrome(menu, []);
  assert.equal(differ.chrome(menu, []), true);
});

test('a changed menu bar is replaced, and only it', () => {
  const calls = [];
  const tv = fakeTv();
  tv.setMenuBar = (m) => calls.push(['setMenuBar', m[0].title]);
  tv.setStatusLine = () => calls.push(['setStatusLine']);
  const differ = createDiffer(tv);
  const status = [{ text: '~Alt-X~ Exit', key: 'Alt-X', cmd: 'quit' }];

  differ.chrome([{ title: 'One' }], status);
  differ.chrome([{ title: 'Two' }], status);
  assert.deepEqual(calls, [['setMenuBar', 'Two']], 'the status line did not change');

  differ.chrome([{ title: 'Two' }], [{ text: 'other', key: '', cmd: '' }]);
  assert.deepEqual(calls, [['setMenuBar', 'Two'], ['setStatusLine']]);
});


// A scroll bar's value and its range are one thing to TScrollBar, which clamps
// the first against the second. Setting them separately can put the thumb
// somewhere neither side asked for, so the diff has to know when to send both.

const bar = (over = {}) => ({
  type: 'scrollBar',
  id: 's',
  rect: [3, 4, 30, 5],
  value: 8,
  min: 1,
  max: 20,
  pageStep: 4,
  arrowStep: 1,
  ...over,
});

test('a scroll bar the model moves is patched, not rebuilt', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([win({ items: [bar()] })]);
  tv.calls.length = 0;
  differ.apply([win({ items: [bar({ value: 12 })] })]);
  assert.deepEqual(tv.calls, [['setValue', 's', 12]]);
});

test('a scroll bar the model leaves alone is left alone', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([win({ items: [bar()] })]);
  tv.calls.length = 0;
  differ.apply([win({ items: [bar()] })]);
  assert.deepEqual(tv.calls, []);
});

test('a changed range sends the value with it, in one call', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([win({ items: [bar()] })]);
  tv.calls.length = 0;
  differ.apply([win({ items: [bar({ value: 40, max: 100 })] })]);
  assert.deepEqual(tv.calls, [['setScroll', 's', 40, 1, 100, 4, 1]],
    'value and range separately would let TScrollBar clamp one against the other');
});


// The bug the directory tree found: a list box whose items change lands its
// highlight on row zero, whatever the model said, and the model then hears
// about a move it never asked for.

const listWin = (items, focused) =>
  win({ items: [{ type: 'listBox', id: 'l', rect: [2, 1, 30, 10], items, focused }] });

test('a rebuilt list has its highlight put back, even when the model did not move it', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([listWin(['a', 'b', 'c'], 1)]);
  tv.calls.length = 0;
  differ.apply([listWin(['a', 'b', 'b1', 'c'], 1)]);
  assert.deepEqual(tv.calls, [
    ['setItems', 'l', ['a', 'b', 'b1', 'c']],
    ['setValue', 'l', 1],
  ], 'setItems resets the highlight to 0, so `focused` has to be re-sent');
});

test('a list whose items did not change is not re-focused', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([listWin(['a', 'b', 'c'], 1)]);
  tv.calls.length = 0;
  differ.apply([listWin(['a', 'b', 'c'], 1)]);
  assert.deepEqual(tv.calls, []);
});


// `enabled`, `top` and `enabledItems` -- the three fields the API audit found
// missing and the reason it exists. All three are patched rather than
// structural, which is the part worth testing here: a window rebuilt to grey a
// button out would throw away what was typed into the field beside it.

test('greying a view out patches it rather than rebuilding the window', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  const button = (enabled) => win({
    items: [{ type: 'button', id: 'ok', rect: [2, 1, 12, 3], title: 'OK', enabled }],
  });
  differ.apply([button(true)]);
  tv.calls.length = 0;
  differ.apply([button(false)]);
  assert.deepEqual(tv.calls, [['setViewEnabled', 'ok', false]]);
});

test('a view that never mentions enabled is enabled, and is not written to', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  // `undefined` and `true` mean the same thing, so a model that starts naming
  // the field must not read as a change -- and one that never names it must
  // never be written to at all.
  const plain = win({ items: [{ type: 'button', id: 'ok', rect: [2, 1, 12, 3], title: 'OK' }] });
  const said = win({
    items: [{ type: 'button', id: 'ok', rect: [2, 1, 12, 3], title: 'OK', enabled: true }],
  });
  differ.apply([plain]);
  tv.calls.length = 0;
  differ.apply([said]);
  assert.deepEqual(tv.calls, []);
});

test('a list scrolls under its highlight without being rebuilt', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  const list = (top) => win({
    items: [{ type: 'listBox', id: 'l', rect: [2, 1, 20, 8],
              items: ['a', 'b', 'c'], focused: 0, chooses: '', columns: 1, top }],
  });
  differ.apply([list(0)]);
  tv.calls.length = 0;
  differ.apply([list(2)]);
  assert.deepEqual(tv.calls, [['setListTop', 'l', 2]]);
});

test('the top is written after the highlight, because moving one moves the other', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  const list = (items, top) => win({
    items: [{ type: 'listBox', id: 'l', rect: [2, 1, 20, 8],
              items, focused: 1, chooses: '', columns: 1, top }],
  });
  differ.apply([list(['a', 'b', 'c'], 0)]);
  tv.calls.length = 0;
  differ.apply([list(['a', 'b', 'c', 'd'], 2)]);
  const order = tv.calls.map((c) => c[0]);
  assert.deepEqual(order, ['setItems', 'setValue', 'setListTop']);
});

test("a cluster's own boxes are greyed one at a time", () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  const boxes = (available) => win({
    items: [{ type: 'checkBoxes', id: 'c', rect: [2, 1, 20, 5],
              items: ['a', 'b'], value: [false, false], enabledItems: available }],
  });
  differ.apply([boxes([true, true])]);
  tv.calls.length = 0;
  differ.apply([boxes([true, false])]);
  assert.deepEqual(tv.calls, [['setItemsEnabled', 'c', [true, false]]]);
});

test('the number of columns is structural, because a list cannot be re-divided', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  const list = (columns) => win({
    items: [{ type: 'listBox', id: 'l', rect: [2, 1, 20, 8],
              items: ['a'], focused: 0, chooses: '', columns, top: 0 }],
  });
  differ.apply([list(1)]);
  tv.calls.length = 0;
  differ.apply([list(2)]);
  assert.deepEqual(tv.calls, [['close', 'w'], ['window', 'w']]);
});

test('taking a window\'s close box away is a redraw, not a rebuild', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([win({ canClose: true })]);
  tv.calls.length = 0;
  differ.apply([win({ canClose: false })]);
  assert.deepEqual(tv.calls, [
    ['setWindowFlags', 'w', { canClose: false, canMove: true }],
  ]);
});

test('a window that never mentions its flags is not written to', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([win()]);
  tv.calls.length = 0;
  differ.apply([win({ canClose: true, canMove: true })]);
  assert.deepEqual(tv.calls, []);
});

test('hiding a view keeps it, where leaving it out would rebuild the window', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  const withHistory = (visible) => win({
    items: [
      { type: 'staticText', id: 't', rect: [2, 1, 30, 2], text: 'hello' },
      { type: 'history', id: 'h', for: 't', items: ['a'], visible },
    ],
  });
  differ.apply([withHistory(false)]);
  tv.calls.length = 0;
  differ.apply([withHistory(true)]);
  assert.deepEqual(tv.calls, [['setViewVisible', 'h', true]]);
});

test('taking a view out of the render is still a rebuild, which is the difference', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  differ.apply([win({
    items: [
      { type: 'staticText', id: 't', rect: [2, 1, 30, 2], text: 'hello' },
      { type: 'history', id: 'h', for: 't', items: ['a'] },
    ],
  })]);
  tv.calls.length = 0;
  differ.apply([win()]);
  assert.deepEqual(tv.calls, [['close', 'w'], ['window', 'w']]);
});

test('hidden and disabled are two fields and do not disturb each other', () => {
  const tv = fakeTv();
  const differ = createDiffer(tv);
  const both = (visible, enabled) => win({
    items: [{ type: 'button', id: 'b', rect: [2, 1, 12, 3], title: 'Go', visible, enabled }],
  });
  differ.apply([both(true, true)]);
  tv.calls.length = 0;
  differ.apply([both(false, false)]);
  assert.deepEqual(tv.calls, [
    ['setViewEnabled', 'b', false],
    ['setViewVisible', 'b', false],
  ]);
});

test('an editor may set autoIndent, and changing it rebuilds', () => {
  // Structural on purpose: it is not in MUTABLE, so a model that changes its
  // mind gets a new editor -- and an editor is the one view that loses its
  // contents when rebuilt, which is exactly why this must be a decision the
  // model makes once rather than a thing it toggles.
  const tv = fakeTv();
  const differ = createDiffer(tv);
  const ed = (autoIndent) => win({
    items: [{ type: 'editor', id: 'e', rect: [2, 1, 40, 8], autoIndent }],
  });
  differ.apply([ed(false)]);
  tv.calls.length = 0;
  differ.apply([ed(true)]);
  assert.deepEqual(tv.calls, [['close', 'w'], ['window', 'w']]);
});
