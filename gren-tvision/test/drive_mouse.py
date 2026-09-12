#!/usr/bin/env python3
"""examples/mouse -- tvdemo's mouse options dialog, in Gren.

This is the first example with a scroll bar the model owns, and the test drives
it every way it moves: arrows, Home and End, a page click and a drag on the
thumb. What comes back is a `Scrolled` event with a value, and the model turns
that straight around into `setDoubleClickDelay`.

The point of the dialog is that the setting is real, so the test proves it the
way a person would: the same two clicks, at the same speed, are one double
click at a long delay and two separate clicks at a short one.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLE = os.path.join(ROOT, "examples", "mouse")
from harness_path import RUNTIME  # finds harness.py and gren-tui.js, here or in an install

from harness import Pty, Checks, node_argv

# The window's frame is at screen (20, 5). The tester strip is at (3, 3)
# inside it and the scroll bar on the row below.
TESTER_ROW = 8
BAR_ROW = 9
BAR_LEFT = 23           # the ◄ arrow, screen column


def delay(app):
    m = re.search(r"delay\s+(\d+) ticks", app.render())
    return int(m.group(1)) if m else None


def counts(app):
    m = re.search(r"singles (\d+)\s+doubles (\d+)", app.render())
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def double_click(app, col, row, gap=0.35, settle=0.7):
    """Two presses at the same spot, `gap` apart.

    The pause is real rather than nominal: TVision timestamps a mouse event
    when it *reads* it, so two reports sitting in the pty buffer together look
    simultaneous however far apart they were written. Pumping between them is
    what makes the gap something the library can measure -- and 0.35s is
    comfortably inside a 20-tick delay (1.1s) and outside a 1-tick one
    (55ms), which is the whole demonstration."""
    app.send(f"\x1b[<0;{col};{row}M".encode(), settle=0.1)
    app.send(f"\x1b[<0;{col};{row}m".encode(), settle=gap)
    app.send(f"\x1b[<0;{col};{row}M".encode(), settle=0.1)
    app.send(f"\x1b[<0;{col};{row}m".encode(), settle=settle)


def main():
    check = Checks()
    env = dict(os.environ, TERM="xterm-256color")
    app = Pty(node_argv(RUNTIME, "main.js"), env, cwd=EXAMPLE)

    app.pump(2.5)
    screen = app.render()
    check("mouse dialog drawn", "Mouse options" in screen, screen)
    check("the scroll bar was drawn", "◄" in screen and "►" in screen, screen)
    check("it starts at the delay the model asked for", delay(app) == 8, str(delay(app)))

    # The tester canvas says takesFocus = False, so the scroll bar is the first
    # view that can hold the caret and has it before anyone presses anything.
    app.send(b"\x1b[C" * 3, settle=0.8)
    check("arrows move the bar and the model hears about it", delay(app) == 11,
          str(delay(app)))
    app.send(b"\x1b[D", settle=0.6)
    check("and back", delay(app) == 10, str(delay(app)))

    app.send(b"\x1b[F", settle=0.6)
    check("End goes to the maximum", delay(app) == 20, str(delay(app)))
    app.send(b"\x1b[H", settle=0.6)
    check("Home goes to the minimum", delay(app) == 1, str(delay(app)))

    # magiblot's TScrollBar diverges from Borland's here, and it is worth
    # knowing: a click anywhere that is not an arrow does *not* page -- it
    # takes the thumb straight to the pointer, and drags it from there. So
    # `pageStep` is reached only from the keyboard.
    app.click(BAR_LEFT + 22, BAR_ROW + 1, settle=0.8)
    near_end = delay(app)
    check("a click on the bar takes the thumb to the pointer", near_end >= 16,
          str(near_end))
    app.click(BAR_LEFT + 3, BAR_ROW + 1, settle=0.8)
    check("...wherever the pointer is", delay(app) <= 4, str(delay(app)))

    # Ctrl-Left and Ctrl-Right are what page on a horizontal bar, by the
    # pageStep the model asked for.
    app.send(b"\x1b[H", settle=0.6)
    app.send(b"\x1b[1;5C", settle=0.7)
    check("Ctrl-Right pages by pageStep", delay(app) == 5, str(delay(app)))
    app.send(b"\x1b[1;5D", settle=0.7)
    check("and Ctrl-Left pages back", delay(app) == 1, str(delay(app)))

    # Now the demonstration. At the shortest delay the two clicks are two
    # clicks; at the longest they are one double click, and the strip changes
    # colour to say so.
    app.send(b"\x1b[H", settle=0.6)
    before = counts(app)
    double_click(app, BAR_LEFT + 2, TESTER_ROW + 1)
    after = counts(app)
    check("at a 1-tick delay the pair counts as two single clicks",
          after == (before[0] + 2, before[1]), f"{before} -> {after}")

    display = app.display()
    plain = (display.fg_at(BAR_LEFT, TESTER_ROW), display.bg_at(BAR_LEFT, TESTER_ROW))

    app.send(b"\x1b[F", settle=0.8)
    check("back to the longest delay", delay(app) == 20, str(delay(app)))
    before = counts(app)
    double_click(app, BAR_LEFT + 2, TESTER_ROW + 1)
    after = counts(app)
    check("at a 20-tick delay the same pair is one double click",
          after == (before[0] + 1, before[1] + 1), f"{before} -> {after}")

    display = app.display()
    lit = (display.fg_at(BAR_LEFT, TESTER_ROW), display.bg_at(BAR_LEFT, TESTER_ROW))
    check("and the strip changed colour", lit != plain, f"{plain} -> {lit}")

    # Reset puts the bar back where the model says, which is the other
    # direction: a value written from the model moves the thumb.
    app.send(b"\x1br", settle=0.9)
    check("Reset moves the thumb from the model", delay(app) == 8, str(delay(app)))
    check("and clears the counts", counts(app) == (0, 0), str(counts(app)))

    app.click(24, 6, settle=1.0)
    check("the window closed and stayed closed",
          "Mouse options" not in app.render().split("\n")[5], app.render())
    app.send(b"\x1bm", settle=1.0)
    check("Alt-M reopened it", "Mouse options" in app.render().split("\n")[5])

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("exit code 0", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
