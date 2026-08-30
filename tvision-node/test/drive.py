#!/usr/bin/env python3
"""Milestone 1: hello.js, the blocking form."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Pty, Checks, node_argv

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = os.path.join(ROOT, "build", "drive.log")


def main():
    check = Checks()
    if os.path.exists(LOG):
        os.remove(LOG)

    env = dict(os.environ, TERM="xterm-256color", TVISION_LOG=LOG)
    app = Pty(node_argv(os.path.join(ROOT, "examples", "hello.js")), env, cwd=ROOT)

    # 1. It starts and draws its chrome.
    app.pump(1.5)
    first = app.screen()
    check("menu bar drawn", "Hello" in first)
    check("status line drawn", "Alt-X Exit" in first)

    # 2. Alt-G opens the greeting dialog. In a terminal Alt-<key> arrives as
    #    ESC followed by the key.
    app.send(b"\x1bg", settle=1.0)
    dialog = app.screen()
    check("dialog title", "Hello, World!" in dialog)
    check("dialog static text", "How are you?" in dialog)
    check("dialog buttons",
          all(b in dialog for b in ("Terrific", "Ok", "Lousy", "Cancel")),
          "buttons missing")

    # 3. Tab off the initially-focused button (Cancel -- TVision focuses the
    #    last view inserted) so we exercise a real answer, then press it.
    #    Space presses the focused button; Enter would fire the *default*
    #    button (cmDefault broadcast) and this dialog, like hello.cpp's, has
    #    no bfDefault button -- so Enter here does nothing at all.
    #    The messageBox that follows is the interesting part: it is JS calling
    #    back into C++ from inside a C++ callback into JS, with a modal dialog
    #    already on the stack.
    app.send(b"\t", settle=0.5)
    app.send(b" ", settle=1.0)
    check("messageBox from inside the callback",
          "You said you feel" in app.screen(),
          "no messageBox after pressing a button")
    app.send(b"\r", settle=0.6)   # dismiss the messageBox
    app.send(b"\x1b", settle=0.4) # and anything still on top

    # 4. Alt-X quits and onExit runs.
    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)

    check("process exited", code is not None, "still running")
    check("exit code 0", code == 0, f"exit={code}")
    check("onExit ran", "tvision app exited cleanly" in app.screen())

    # 5. The JS callback saw the command and the dialog's answer.
    logged = open(LOG).read() if os.path.exists(LOG) else ""
    check("onCommand fired", "command: greet" in logged, repr(logged[:200]))
    check("dialog result returned to JS",
          any(f"answer: {a}" in logged for a in ("terrific", "fine", "lousy")),
          repr(logged[:200]))

    return check.report(app, extra="--- log ---\n" + (logged.rstrip() or "(empty)"))


if __name__ == "__main__":
    sys.exit(main())
