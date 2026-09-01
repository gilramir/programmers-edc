'use strict';

// The clipboard, both directions.
//
// There is no clipboard example in tvision/examples to port: Turbo Vision's
// own clipboard is `TEditor::clipboard`, a hidden editor that cmCopy and
// cmPaste move text through, and the *system* clipboard arrived much later as
// two functions on THardwareInfo that nothing in the library calls except
// TClipboard. This is those two, wired to a field.
//
// Two things about them are worth seeing here rather than reading about:
//
//   * copying can half-work. `setClipboard` returns false when no system
//     clipboard would take the text -- no `wl-copy`, `xsel` or `xclip`, and a
//     terminal that does not do OSC 52 -- and the text is kept in the process
//     anyway, so a copy and a paste inside this program still work. False
//     means "no other program will see it", which is worth telling the user.
//
//   * pasting is a *request*. A terminal that owns the clipboard is asked for
//     it with an escape sequence and replies through the input stream, so the
//     answer arrives at onClipboard some events later rather than coming back
//     from the call.

const tv = require('..');

function report(text) {
  tv.setText('report', text);
}

tv.start({
  menuBar: [
    {
      title: '~E~dit',
      key: 'Alt-E',
      items: [
        { title: '~C~opy', cmd: 'copy', key: 'Alt-C', shortcut: 'Alt-C' },
        { title: '~P~aste', cmd: 'paste', key: 'Alt-V', shortcut: 'Alt-V' },
        { separator: true },
        { title: 'E~x~it', cmd: 'quit', key: 'Alt-X', shortcut: 'Alt-X' },
      ],
    },
  ],

  statusLine: [
    { text: '~Alt-X~ Exit', key: 'Alt-X', cmd: 'quit' },
    { text: '~Alt-C~ Copy', key: 'Alt-C', cmd: 'copy' },
    { text: '~Alt-V~ Paste', key: 'Alt-V', cmd: 'paste' },
    { text: '', key: 'F10', cmd: 'menu' },
  ],

  onCommand(cmd) {
    if (cmd === 'copy') {
      const text = tv.getValue('text') || '';
      const shared = tv.setClipboard(text);
      report(shared
        ? `copied ${text.length} to the system clipboard`
        : `copied ${text.length} here only`);
    } else if (cmd === 'paste') {
      // Nothing is reported here on purpose: what there is to say is not
      // known yet.
      tv.requestClipboard();
    }
  },

  // The answer, whenever it comes. `fromSystem` is false when what came back
  // is this program's own last copy.
  onClipboard(text, fromSystem) {
    tv.setValue('text', text);
    report(fromSystem
      ? `pasted ${text.length} from the system clipboard`
      : `pasted ${text.length} from this program`);
  },

  onExit() {
    console.log('clipboard example exited');
  },
});

tv.window({
  id: 'clipWin',
  title: 'Clipboard',
  rect: [8, 4, 72, 12],
  items: [
    { id: 'text', type: 'inputLine', rect: [3, 2, 58, 3], maxLen: 200, value: 'hello' },
    { type: 'label', rect: [3, 1, 20, 2], text: '~T~ext', for: 'text' },
    { id: 'report', type: 'staticText', rect: [3, 4, 58, 5], text: 'Alt-C copies, Alt-V pastes' },
  ],
});
