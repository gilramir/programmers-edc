'use strict';

// In the spirit of tvision/examples/tvforms: a data-entry form, plus the two
// menu features mmenu exists to show off.
//
// What this exercises that the earlier demos did not:
//   * check boxes and radio buttons -- TCluster keeps its state in a protected
//     `value`, a bitmask for check boxes and an index for radio buttons
//   * labels bound to a control, so Alt-<letter> focuses the field
//   * submenus inside submenus
//   * enabling and disabling a command, everywhere it appears at once

const tv = require('..');

// Hotkeys are a flat namespace inside a dialog: the first control that claims
// Alt-<letter> gets it. "~P~hone" on both the label and a radio button means
// the radio wins and the field is unreachable. Worse, the *status line's*
// hotkeys are global and beat even a modal dialog -- Alt-N below would have
// been eaten by the status line's "New" -- so the fields are Alt-M and Alt-H.
const INTERESTS = ['~T~erminals', '~R~etrocomputing', 'Pa~s~cal', '~C~++'];
const CONTACT = ['~E~mail', '~P~hone', 'N~o~ne'];

const records = [];

function formDialog(initial) {
  return tv.dialog({
    title: initial ? 'Edit record' : 'New record',
    rect: [12, 3, 68, 20],
    items: [
      { id: 'name', type: 'inputLine', rect: [16, 2, 52, 3], maxLen: 40,
        value: initial ? initial.name : '' },
      { type: 'label', rect: [3, 2, 15, 3], text: 'Na~m~e', for: 'name' },

      { id: 'phone', type: 'inputLine', rect: [16, 4, 52, 5], maxLen: 24,
        value: initial ? initial.phone : '' },
      { type: 'label', rect: [3, 4, 15, 5], text: 'P~h~one', for: 'phone' },

      { id: 'interests', type: 'checkBoxes', rect: [3, 7, 26, 11],
        items: INTERESTS,
        value: initial ? initial.interests : [true, false, false, false] },
      { type: 'label', rect: [3, 6, 26, 7], text: 'Interests', for: 'interests' },

      { id: 'contact', type: 'radioButtons', rect: [30, 7, 52, 10],
        items: CONTACT, value: initial ? initial.contact : 0 },
      { type: 'label', rect: [30, 6, 52, 7], text: 'Contact by', for: 'contact' },

      { type: 'button', rect: [14, 12, 26, 14], title: '~O~K', cmd: 'ok', default: true },
      { type: 'button', rect: [30, 12, 42, 14], title: 'Cancel', cmd: 'cancel' },
    ],
  });
}

async function newRecord() {
  const answer = await formDialog(null);
  tv.log('form:', answer);
  if (answer.cmd !== 'ok') return;

  records.push({
    name: answer.values.name,
    phone: answer.values.phone,
    interests: answer.values.interests,   // array of booleans
    contact: answer.values.contact,       // index
  });

  // One record is enough to make these worth offering.
  tv.setEnabled('list', true);
  tv.setEnabled('clear', true);
  showRecords();
}

function plain(s) {
  return s.replace(/~/g, '');
}

function describe(rec, i) {
  // 74 columns. A canvas silently truncates, so the widths are budgeted:
  // 4 + 19 + 13 + 10 leaves room for the interests in brackets.
  const likes = INTERESTS.filter((_, n) => rec.interests[n]).map(plain).join(', ');
  return `${String(i + 1).padStart(2)}. ${(rec.name || '(no name)').padEnd(18)}` +
         ` ${(rec.phone || '').padEnd(12)} via ${plain(CONTACT[rec.contact]).padEnd(6)}` +
         (likes ? ` [${likes}]` : '');
}

function showRecords() {
  if (!tv.exists('recordsWin')) {
    tv.window({
      id: 'recordsWin',
      title: 'Records',
      rect: [1, 2, 79, 16],
      items: [
        { id: 'records', type: 'canvas', rect: [2, 1, 76, 11], selectable: false, color: 6 },
      ],
    });
  }
  tv.setLines('records', records.length
    ? records.map(describe)
    : ['(no records yet -- File > New record)']);
}

tv.start({
  menuBar: [
    {
      title: '~F~ile',
      key: 'Alt-F',
      items: [
        { title: '~N~ew record...', cmd: 'new', key: 'Alt-N', shortcut: 'Alt-N' },
        { title: '~L~ist records', cmd: 'list', key: 'Alt-L', shortcut: 'Alt-L' },
        { separator: true },
        // A submenu inside a submenu -- the thing mmenu is for.
        {
          title: '~S~amples',
          key: 'Alt-S',
          items: [
            { title: '~A~da Lovelace', cmd: 'sampleAda' },
            { title: '~G~race Hopper', cmd: 'sampleGrace' },
            {
              title: '~M~ore',
              items: [
                { title: '~N~iklaus Wirth', cmd: 'sampleNiklaus' },
                { title: '~A~nders Hejlsberg', cmd: 'sampleAnders' },
              ],
            },
          ],
        },
        { separator: true },
        { title: '~C~lear', cmd: 'clear' },
        { title: 'E~x~it', cmd: 'quit', key: 'Alt-X', shortcut: 'Alt-X' },
      ],
    },
  ],

  statusLine: [
    { text: '~Alt-X~ Exit', key: 'Alt-X', cmd: 'quit' },
    { text: '~Alt-N~ New', key: 'Alt-N', cmd: 'new' },
    { text: '~Alt-L~ List', key: 'Alt-L', cmd: 'list' },
    { text: '', key: 'F10', cmd: 'menu' },
  ],

  async onCommand(cmd) {
    tv.log('command:', cmd);

    switch (cmd) {
      case 'new':
        return newRecord();

      case 'list':
        return showRecords();

      case 'clear':
        records.length = 0;
        tv.setEnabled('list', false);
        tv.setEnabled('clear', false);
        return showRecords();

      case 'sampleAda':
      case 'sampleGrace':
      case 'sampleNiklaus':
      case 'sampleAnders': {
        const who = {
          sampleAda: ['Ada Lovelace', '1815'],
          sampleGrace: ['Grace Hopper', '1906'],
          sampleNiklaus: ['Niklaus Wirth', '1934'],
          sampleAnders: ['Anders Hejlsberg', '1960'],
        }[cmd];
        const answer = await formDialog({
          name: who[0], phone: who[1],
          interests: [true, true, cmd === 'sampleNiklaus', cmd === 'sampleAnders'],
          contact: 0,
        });
        if (answer.cmd === 'ok') {
          records.push({
            name: answer.values.name, phone: answer.values.phone,
            interests: answer.values.interests, contact: answer.values.contact,
          });
          tv.setEnabled('list', true);
          tv.setEnabled('clear', true);
          showRecords();
        }
        return undefined;
      }

      default:
        return undefined;
    }
  },

  onExit() {
    console.log(`form demo exited with ${records.length} record(s)`);
    for (const [i, r] of records.entries()) console.log(describe(r, i));
  },
});

// Nothing to list or clear until there is a record: greyed out in the menu and
// on the status line, both, from one call.
tv.setEnabled('list', false);
tv.setEnabled('clear', false);
showRecords();
