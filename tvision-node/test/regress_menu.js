'use strict';

// Regression: a menu item that names no command.
//
// TVision reads `command == 0` as "this item is a submenu", and `TMenuItem`
// keeps the two readings in a union -- `union { const char *param; TMenu
// *subMenu; }` -- so a plain item with command 0 offers its *shortcut string*
// wherever a `TMenu *` is expected. The one that kills you is
// `TMenuView::findHotKey` (tmnuview.cpp:567):
//
//     if( p->command == 0 )
//         if( (T = findHotKey( p->subMenu->items, key )) != 0 )
//
// with no null check, reached from `TMenuView::handleEvent` (:531), which runs
// `hotKey()` on *every* evKeyDown. The menu bar is `ofPreProcess`, so it sees
// every key before anything else does -- which is why the crash lands on the
// first keystroke after such a menu is installed, whatever has focus, and
// looks like a bug in whatever was being typed.
//
// The binding therefore never builds one: an item with no command gets
// `kCmdNothing` and is disabled.

const tv = require('..');

tv.start({
  menuBar: [
    {
      title: '~F~ile',
      items: [
        // The item under test: named, no command, not a submenu.
        { title: 'nothing at all', cmd: '' },
        { title: 'E~x~it', cmd: 'quit', key: 'Alt-X', shortcut: 'Alt-X' },
      ],
    },
  ],
  statusLine: [{ text: '~Alt-X~ Exit', key: 'Alt-X', cmd: 'quit' }],
  onCommand() {},
  onExit() {
    console.log('menu regression: survived the keystrokes');
    process.exit(0);
  },
});

// Nothing else to do: the driver types, and typing is the whole test.
