'use strict';

// Milestone 1: tvision/hello.cpp, with the C++ parts of it moved into JS.
//
// The menu bar, the status line and the greeting dialog are all described as
// plain JS objects here -- nothing in this file is compiled. Compare with
// tvision/hello.cpp to see what the addon took over.

const tv = require('..');

tv.run({
  menuBar: [
    {
      title: '~H~ello',
      key: 'Alt-H',
      items: [
        { title: '~G~reeting...', cmd: 'greet', key: 'Alt-G' },
        { separator: true },
        { title: 'E~x~it', cmd: 'quit', key: 'Alt-X', shortcut: 'Alt-X' },
      ],
    },
  ],

  statusLine: [
    { text: '~Alt-X~ Exit', key: 'Alt-X', cmd: 'quit' },
    { text: '', key: 'F10', cmd: 'menu' },
  ],

  onCommand(cmd) {
    tv.log('command:', cmd);

    if (cmd === 'greet') {
      // hello.cpp's greetingBox(), rectangle for rectangle.
      const answer = tv.dialog({
        title: 'Hello, World!',
        rect: [25, 5, 55, 16],
        items: [
          { type: 'staticText', rect: [3, 5, 15, 6], text: 'How are you?' },
          { type: 'button', rect: [16, 2, 28, 4], title: 'Terrific', cmd: 'terrific' },
          { type: 'button', rect: [16, 4, 28, 6], title: 'Ok', cmd: 'fine' },
          { type: 'button', rect: [16, 6, 28, 8], title: 'Lousy', cmd: 'lousy' },
          { type: 'button', rect: [16, 8, 28, 10], title: 'Cancel', cmd: 'cancel' },
        ],
      });

      // The original threw the answer away. We can do better -- this is the
      // whole point of the exercise: a TVision dialog result, in JavaScript.
      tv.log('answer:', answer.cmd);
      if (answer.cmd && answer.cmd !== 'cancel') {
        tv.messageBox(`You said you feel ${answer.cmd}.`);
      }
    }
  },
});

// run() returned, so the app has quit and the terminal is ours again.
console.log('tvision app exited cleanly');
