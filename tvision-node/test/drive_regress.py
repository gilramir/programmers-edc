#!/usr/bin/env python3
"""Memory regressions, run under AddressSanitizer.

Requires an ASAN build:  npx node-gyp rebuild -- -Dasan=1
"""

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Pty, Checks, node_argv, asan_enabled

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main():
    check = Checks()

    # asan.sh points ASAN_OPTIONS at build/asan.<pid>; a report is a file, not
    # a string we have to fish out of a repainting terminal.
    reports = os.path.join(ROOT, "build", "asan.*")
    for stale in glob.glob(reports):
        os.remove(stale)

    env = dict(os.environ, TERM="xterm-256color")
    if not asan_enabled():
        print("note: TVNODE_ASAN=1 not set -- running as a plain functional "
              "test, with no memory checking")
    app = Pty(node_argv(os.path.join(HERE, "regress_inputline.js")), env, cwd=ROOT)

    app.pump(2.0)
    check("dialog opened", "Round 1" in app.render(), app.screen()[-300:])

    # The OK button is the default one, so Enter presses it.
    for _ in range(6):
        app.send(b"\r", settle=0.7)

    code = app.wait(timeout=10)
    out = app.screen()

    found = glob.glob(reports)
    check("no AddressSanitizer report", not found,
          open(found[0]).read()[:900] if found else "")
    check("all rounds survived", "survived 5 dialogs" in out, out[-300:])
    check("exit code 0", code == 0, f"exit={code}")

    # A menu item that names no command, and then a single keystroke.
    #
    # TVision reads `command == 0` as "this item is a submenu" and unions
    # `param` with `subMenu`, so such an item offers its shortcut string
    # wherever a `TMenu *` is wanted. `TMenuView::findHotKey` (tmnuview.cpp:567)
    # follows it with no null check, and `handleEvent` (:531) calls that on
    # every evKeyDown -- through a menu bar that is `ofPreProcess` and so sees
    # every key first. One keystroke, whatever has focus.
    for stale in glob.glob(reports):
        os.remove(stale)
    menu = Pty(node_argv(os.path.join(HERE, "regress_menu.js")), env, cwd=ROOT)
    menu.pump(2.0)
    check("the menu with a command-less item drew",
          "File" in menu.render().split("\n")[0], menu.render().split("\n")[0])
    # One plain key is the whole test. `wait` reaps, so it is asked once and
    # the exit code carries the answer: -11 is the crash, 0 is Alt-X.
    menu.send(b"a", settle=0.8)
    menu.send(b"\x1bx", settle=0.8)
    menu_code = menu.wait(timeout=8)
    check("a keystroke through a command-less menu item did not kill it",
          menu_code != -11, f"exit={menu_code}")
    menu_found = glob.glob(reports)
    check("no AddressSanitizer report from the menu", not menu_found,
          open(menu_found[0]).read()[:900] if menu_found else "")
    check("and it exited cleanly on Alt-X", menu_code == 0, f"exit={menu_code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
