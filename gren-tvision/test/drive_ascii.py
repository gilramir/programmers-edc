#!/usr/bin/env python3
"""examples/ascii -- tvdemo's ASCII chart, in Gren.

The chart is a canvas: the model hands over eight strings, Turbo Vision paints
them, and every keystroke comes back as an event. Two numbers in the model are
the whole of the state.

Which character is selected shows up in exactly one place on screen -- the
terminal's own cursor -- so that is what most of this asserts on. There is
nothing else to look at: a canvas has no selection bar and no highlight.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLE = os.path.join(ROOT, "examples", "ascii")
from harness_path import RUNTIME  # finds harness.py and gren-tui.js, here or in an install

from harness import Pty, Checks, node_argv

# The chart window sits at desktop (8, 3) and the canvas 2 columns and 1 row
# inside it, so character (0, 0) is here. The menu bar takes screen row 0.
ORIGIN = (10, 5)


def cell(x, y):
    return (ORIGIN[0] + x, ORIGIN[1] + y)


def decimal(screen):
    m = re.search(r"Dec\s+(\d+)", screen)
    return int(m.group(1)) if m else None


def main():
    check = Checks()
    env = dict(os.environ, TERM="xterm-256color")
    app = Pty(node_argv(RUNTIME, "main.js"), env, cwd=EXAMPLE)

    app.pump(2.0)
    first = app.render()
    check("chart window drawn", "ASCII Chart" in first)
    check("the canvas was painted from the model",
          "@ABCDEFGHIJKLMNOPQRSTUVWXYZ" in first, first)
    check("code page 437, not Unicode's idea of it", "☺☻♥" in first,
          "row 0 should be the CP437 dingbats")
    check("starts on character 0", decimal(first) == 0, str(decimal(first)))
    check("the cursor was placed before anyone touched a key",
          app.cursor() == cell(0, 0), f"{app.cursor()} != {cell(0, 0)}")

    # Arrows: one right, four down = 1 + 4*32 = 129. The model moved, so the
    # runtime patched the cursor -- nothing else on screen changes except the
    # report line.
    app.send(b"\x1b[C", settle=0.3)
    app.send(b"\x1b[B" * 4, settle=0.8)
    check("arrow keys reached the model", decimal(app.render()) == 129,
          f"got {decimal(app.render())}")
    check("and the cursor followed", app.cursor() == cell(1, 4),
          f"{app.cursor()} != {cell(1, 4)}")

    # A printable key jumps to that character, as the original does.
    app.send(b"A", settle=0.6)
    check("a printable key jumps", decimal(app.render()) == 65,
          f"got {decimal(app.render())}")
    check("cursor at 65", app.cursor() == cell(1, 2), f"{app.cursor()}")

    app.send(b"\x1b[H", settle=0.5)
    check("Home goes back to 0", decimal(app.render()) == 0,
          f"got {decimal(app.render())}")

    # A click is in the canvas's own coordinates, which is what makes this one
    # line in the model. Screen (12, 6) is character (2, 1) = 34.
    app.click(cell(2, 1)[0] + 1, cell(2, 1)[1] + 1, settle=0.8)
    check("a click reached the model", decimal(app.render()) == 34,
          f"got {decimal(app.render())}")

    # A drag is a press, motion, and a release. The press lands as a click and
    # every cell after it as a `Dragged`, so the cursor should end up under
    # wherever the pointer stopped -- character (5, 3) = 3*32 + 5 = 101.
    app.drag([(cell(2, 1)[0] + 1, cell(2, 1)[1] + 1),
              (cell(3, 2)[0] + 1, cell(3, 2)[1] + 1),
              (cell(5, 3)[0] + 1, cell(5, 3)[1] + 1)], settle=0.8)
    check("a drag moved the cursor with it", decimal(app.render()) == 101,
          f"got {decimal(app.render())}")
    check("and left it where the pointer stopped", app.cursor() == cell(5, 3),
          f"{app.cursor()} != {cell(5, 3)}")

    # The two halves of the capture, in one gesture. Screen (1, 1) is the
    # top-left corner of the desktop, nowhere near the chart -- Turbo Vision
    # would route a positional event there to whatever is under it, and the
    # canvas would hear nothing. It hears it because the press captured the
    # mouse, and the coordinates it hears are its own and negative, which is
    # what `moveTo`'s clamp turns into character 0.
    app.drag([(cell(4, 4)[0] + 1, cell(4, 4)[1] + 1), (5, 3), (1, 1)],
             settle=0.8)
    check("a drag off the canvas still reaches it", decimal(app.render()) == 0,
          f"got {decimal(app.render())}")
    check("clamped to the first character", app.cursor() == cell(0, 0),
          f"{app.cursor()} != {cell(0, 0)}")

    # Back to 34 for the checks below, which were written before the drag was.
    app.click(cell(2, 1)[0] + 1, cell(2, 1)[1] + 1, settle=0.8)
    check("a click after a drag is still just a click",
          decimal(app.render()) == 34, f"got {decimal(app.render())}")

    # Closing the window from its frame has to reach the model, or the next
    # render puts it straight back. The close box is at the window's top left.
    app.click(12, 5, settle=1.0)
    closed = app.render()
    check("the window closed and stayed closed", "ASCII Chart" not in closed, closed)

    # Reopening rebuilds the window from the model -- selection included, which
    # means the cursor has to be placed on a view that is being built rather
    # than patched.
    app.send(b"\x1ba", settle=1.0)
    again = app.render()
    check("Alt-A reopened it", "ASCII Chart" in again)
    check("the selection survived the window", decimal(again) == 34,
          f"got {decimal(again)}")
    check("and so did the cursor", app.cursor() == cell(2, 1),
          f"{app.cursor()} != {cell(2, 1)}")

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("exit code 0", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
