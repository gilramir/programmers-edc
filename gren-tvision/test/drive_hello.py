#!/usr/bin/env python3
"""examples/hello -- tvision/hello.cpp, in Gren.

The C++ original discards the answer; this one puts it in the model, so the
check is that a dialog result comes back and gets rendered.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLE = os.path.join(ROOT, "examples", "hello")
from harness_path import RUNTIME  # finds harness.py and gren-tui.js, here or in an install

from harness import Pty, Checks, node_argv


def main():
    check = Checks()
    env = dict(os.environ, TERM="xterm-256color")
    app = Pty(node_argv(RUNTIME, "main.js"), env, cwd=EXAMPLE)

    app.pump(2.0)
    check("menu bar drawn", "Hello" in app.render())
    check("nothing on the desktop yet", "You said" not in app.render())

    app.send(b"\x1bg", settle=1.2)
    dialog = app.render()
    check("greeting box drawn", "Hello, World!" in dialog)
    check("greeting box contents", "How are you?" in dialog and "Terrific" in dialog)

    # The first control in the list gets focus, so Terrific is already focused.
    # Space presses it; Enter would want a default button and there is none,
    # exactly as in hello.cpp.
    app.send(b" ", settle=1.2)
    answered = app.render()
    check("the answer became a window", "You said" in answered,
          "the dialog result never reached the model")
    check("the answer is in the model", "You feel terrific." in answered, answered[8 * 81:12 * 81])

    # `canClose = False`: this window exists exactly while the model has an
    # answer, so a close box would put it straight back on the next render.
    # Checked twice over, because the box being absent and the window refusing
    # to go are two different claims and only the second is what was asked for.
    title_row = [row for row in answered.split("\n") if "You said" in row][0]
    check("a window that cannot be closed has no close box on its frame",
          "[■]" not in title_row, title_row)
    app.send(b"\x1b\x1bOR", settle=0.8)   # Alt-F3, which closes a window
    check("and Alt-F3 leaves it where it is",
          "You said" in app.render(), app.render())

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("exit code 0", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
