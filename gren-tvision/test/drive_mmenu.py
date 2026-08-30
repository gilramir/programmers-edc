#!/usr/bin/env python3
"""examples/mmenu -- tvision/examples/mmenu, in Gren.

The C++ original needed a TMenuBar subclass, an array of TMenu*, a new
broadcast command and a handleEvent override to change the menu bar at runtime.
Here the menu bar is part of the view, so the whole mechanism is one number in
the model -- and what this test checks is that changing that number really does
replace the bar on screen.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLE = os.path.join(ROOT, "examples", "mmenu")
RUNTIME = os.path.join(ROOT, "..", "gren-tvision-runtime", "bin", "gren-tui.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv


def bar(screen):
    """The menu bar is the first line of the screen."""
    return screen.split("\n")[0]


def main():
    check = Checks()
    env = dict(os.environ, TERM="xterm-256color")
    app = Pty(node_argv(RUNTIME, "main.js"), env, cwd=EXAMPLE)

    app.pump(2.0)
    first = app.render()
    check("the first menu bar is drawn",
          all(x in bar(first) for x in ("Next menu", "Menu One", "File")), bar(first))
    check("a plain command sits on the bar", "Next menu" in bar(first),
          "the first entry is an Item, not a pull-down")
    check("the model says which bar is showing", "Menu bar 1 of 3" in first)
    check("the status line came from the view", "Alt-N Next menu" in first)

    # Alt-N is the original's cmCycle. In Gren it adds one to a number.
    app.send(b"\x1bn", settle=1.2)
    second = app.render()
    check("the menu bar was replaced", "Menu Two" in bar(second) and "Edit" in bar(second),
          bar(second))
    check("the old menu bar is gone", "Menu One" not in bar(second), bar(second))
    check("the model followed", "Menu bar 2 of 3" in second)

    # A command from a pull-down on the *new* bar still arrives.
    app.send(b"\x1bm", settle=0.6)     # Menu Two
    app.send(b"o", settle=1.0)         # One
    check("a command from the replaced bar reached update",
          "Last command: one" in app.render(),
          "the swapped-in menu is not wired up")

    # Round the houses and back to the first.
    app.send(b"\x1bn", settle=0.8)
    check("third bar", "Compile" in bar(app.render()), bar(app.render()))
    app.send(b"\x1bn", settle=0.8)
    back = app.render()
    check("cycles back to the first", "Menu bar 1 of 3" in back and "File" in bar(back),
          bar(back))

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("exit code 0", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
