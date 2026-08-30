#!/usr/bin/env python3
"""examples/calc -- tvdemo's calculator, in Gren.

Two things are being tested here, and only one of them is arithmetic.

The other is `takesFocus`. `TCalculator`'s constructor clears `ofSelectable` on
all twenty of its buttons, because the display view is the thing reading the
keyboard and a focusable keypad would swallow every digit typed at it. Nothing
in the Gren API could say that until this port, so the test types at the
calculator *and* clicks its keys, which only both work if the buttons can be
pressed without taking the caret.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLE = os.path.join(ROOT, "examples", "calc")
RUNTIME = os.path.join(ROOT, "..", "gren-tvision-runtime", "bin", "gren-tui.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

# The window is at desktop (5, 3), so its frame is at screen (5, 4). The
# display sits at (3, 2) inside it and is eighteen columns wide.
DISPLAY = (8, 6)

KEYPAD = ["C", "←", "%", "±",
          "7", "8", "9", "/",
          "4", "5", "6", "*",
          "1", "2", "3", "-",
          "0", ".", "=", "+"]


def button(label):
    """Where to click a keypad key, 1-based, as `Pty.click` wants it."""
    i = KEYPAD.index(label)
    return (5 + (i % 4) * 5 + 2 + 1 + 1, 4 + (i // 4) * 2 + 4 + 1)


def readout(app):
    row = app.render().split("\n")[DISPLAY[1]]
    return row[DISPLAY[0]:DISPLAY[0] + 18].strip()


def main():
    check = Checks()
    env = dict(os.environ, TERM="xterm-256color")
    app = Pty(node_argv(RUNTIME, "main.js"), env, cwd=EXAMPLE)

    app.pump(2.5)
    check("calculator drawn", "Calculator" in app.render(), app.render())
    check("the whole keypad is on screen",
          all(label in app.render() for label in KEYPAD),
          app.render())
    check("it starts at zero", readout(app) == "0", readout(app))

    # The display is a canvas painted in a colour of its own, which is the
    # only thing on screen that says so.
    display = app.display()
    check("the display is painted green on black",
          display.fg_at(DISPLAY[0] + 17, DISPLAY[1]) == 92
          and display.bg_at(DISPLAY[0] + 17, DISPLAY[1]) == 40,
          f"fg={display.fg_at(DISPLAY[0] + 17, DISPLAY[1])} "
          f"bg={display.bg_at(DISPLAY[0] + 17, DISPLAY[1])}")

    # Typing works only because no button holds the caret: with twenty
    # focusable buttons in the window the display would never see a keystroke.
    for keys, expected in [(b"12", "12"), (b"+", "12"), (b"3", "3"),
                           (b"=", "15"), (b"*", "15"), (b"2", "2"),
                           (b"=", "30")]:
        app.send(keys, settle=0.4)
        check(f"typing {keys.decode()!r} shows {expected}", readout(app) == expected,
              f"got {readout(app)!r}")

    # A chain finishes the pending operation before recording the new one,
    # which is the part of calcKey() that is easy to get wrong.
    app.send(b"c", settle=0.4)
    for keys in (b"2", b"+", b"3", b"+", b"4", b"="):
        app.send(keys, settle=0.35)
    check("2 + 3 + 4 = 9", readout(app) == "9", f"got {readout(app)!r}")

    app.send(b"_", settle=0.4)
    check("underscore flips the sign", readout(app) == "-9", f"got {readout(app)!r}")

    app.send(b"c", settle=0.4)
    for keys in (b"1", b"/", b"0", b"="):
        app.send(keys, settle=0.35)
    check("dividing by zero says Error", readout(app) == "Error", f"got {readout(app)!r}")
    app.send(b"7", settle=0.4)
    check("and nothing but C gets out of it", readout(app) == "Error",
          f"got {readout(app)!r}")
    app.send(b"c", settle=0.4)
    check("C gets out of it", readout(app) == "0", f"got {readout(app)!r}")

    # And the same keys by mouse. A button that cannot be focused can still be
    # pressed -- that is the whole distinction.
    for label, expected in [("7", "7"), ("*", "7"), ("6", "6"), ("=", "42")]:
        app.click(*button(label), settle=0.5)
        check(f"clicking {label} shows {expected}", readout(app) == expected,
              f"got {readout(app)!r}")

    # ...and the caret never went anywhere, so typing still reaches the model.
    app.send(b"+", settle=0.35)
    app.send(b"8", settle=0.35)
    app.send(b"\r", settle=0.5)
    check("Enter is =, and typing still works after twenty clicks",
          readout(app) == "50", f"got {readout(app)!r}")

    app.click(9, 5, settle=1.0)
    check("the window closed and stayed closed",
          "Calculator" not in app.render().split("\n")[4], app.render())
    app.send(b"\x1bs", settle=1.0)
    check("Alt-S reopened it", "Calculator" in app.render().split("\n")[4])

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("exit code 0", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
