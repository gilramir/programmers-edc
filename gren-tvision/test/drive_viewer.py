#!/usr/bin/env python3
"""examples/viewer -- tvdemo's file viewer, in Gren.

`TFileViewer` is a `TScroller`: a view that owns a `delta`, is told a `limit`,
and paints the slice at `delta` when `scrollDraw()` says to. All of that is one
idea -- which part of the content is on screen -- kept inside the view because
the view is the only thing that can redraw fast enough.

Here it is two fields and a slice, so what this test does is move them from
both directions: from the keyboard, which goes through the model, and by
dragging the scroll bars, which comes back as `Scrolled` and then goes through
the model. Whichever way it is pushed, the text and both thumbs agree, because
there is only one copy of the number.

The horizontal bar is the one worth having: `mouse` has a horizontal scroll bar
too, but as a slider. This is one doing the job it was named for, and it is the
same view -- which way a scroll bar points is decided by its rectangle.
"""

import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLE = os.path.join(ROOT, "examples", "viewer")
from harness_path import RUNTIME  # finds harness.py and gren-tui.js, here or in an install

from harness import Pty, Checks, node_argv

# The window is at desktop (1, 1) and the canvas one row and two columns
# inside, so the first line of text is here. Sixteen rows, seventy columns.
TEXT = (3, 3)
HEIGHT, WIDTH = 16, 70

LINES = 200
WIDEST = 120

# The file ends in a newline, so its last line is an empty one -- which is what
# String.lines gives back and what any editor shows.
SHOWN = LINES + 1


def fixture(path):
    """Lines that say where they are, and one that is wider than the window."""
    with open(path, "w") as f:
        for n in range(1, LINES + 1):
            body = f"line-{n:04d}"
            if n == 7:
                body += "." * (WIDEST - len(body) - len("right-edge")) + "right-edge"
            f.write(body + "\n")


def top_line(app):
    """The first line of text on screen."""
    return app.render().split("\n")[TEXT[1]][TEXT[0]:TEXT[0] + WIDTH].rstrip()


def report(app):
    m = re.search(r"line (\d+) of (\d+)\s+column (\d+)\s+widest (\d+)", app.render())
    return tuple(int(g) for g in m.groups()) if m else None


def main():
    check = Checks(
        replays=(
            "each case rewrites the file being viewed, so by the end there is one "
            "file and several sessions, and a tape carries none of its contents"
        )
    )
    root = tempfile.mkdtemp(prefix="tvview-")
    try:
        path = os.path.join(root, "sample.txt")
        fixture(path)
        env = dict(os.environ, TERM="xterm-256color")
        app = Pty(node_argv(RUNTIME, "main.js", path), env, cwd=EXAMPLE)

        app.pump(2.5)
        check("the file's name is the window title", "sample.txt" in app.render(),
              app.render())
        check("it starts at the top", top_line(app) == "line-0001", top_line(app))
        check("and it read the whole file, widest line included",
              report(app) == (1, SHOWN, 1, WIDEST), str(report(app)))

        # Both scroll bars are drawn, and the horizontal one only exists
        # because a line is wider than the window.
        screen = app.render()
        check("a vertical scroll bar", "▲" in screen and "▼" in screen, screen)
        check("and a horizontal one", "◄" in screen and "►" in screen, screen)

        app.send(b"\x1b[B" * 3, settle=0.8)
        check("Down scrolls the text", top_line(app) == "line-0004", top_line(app))

        app.send(b"\x1b[6~", settle=0.8)
        check("PgDn moves a screenful", top_line(app) == f"line-{4 + HEIGHT:04d}",
              top_line(app))

        app.send(b"\x1b[F", settle=0.8)
        check("End goes to the last screenful",
              top_line(app) == f"line-{SHOWN - HEIGHT + 1:04d}", top_line(app))

        app.send(b"\x1b[H", settle=0.8)
        check("Home comes back", report(app)[0] == 1, str(report(app)))

        # Sideways. Line 7 is the only one wide enough to have anything out
        # there, so it is the one to check.
        app.send(b"\x1b[B" * 6, settle=0.8)
        check("line 7 is on top", top_line(app).startswith("line-0007"), top_line(app))
        check("and its right-hand end is off screen",
              "right-edge" not in top_line(app), top_line(app))
        app.send(b"\x1b[C" * (WIDEST - WIDTH), settle=1.2)
        check("scrolling right brings it into view", "right-edge" in top_line(app),
              top_line(app))
        check("and the column caught up", report(app)[2] == WIDEST - WIDTH + 1,
              str(report(app)))

        # The other direction: drag a scroll bar and the model hears about it.
        # The vertical bar is in the column right of the text.
        #
        # Twice, and this is the rule rather than a workaround: a view that can
        # take focus and has not got it spends the first click taking it, the
        # same way an inactive window spends one being activated. The canvas
        # holds the caret here, so the bar's first click never reaches it.
        app.send(b"\x1b[H", settle=0.6)          # back to the left margin
        bar_col = TEXT[0] + WIDTH
        app.click(bar_col + 1, TEXT[1] + HEIGHT - 2, settle=0.4)
        app.click(bar_col + 1, TEXT[1] + HEIGHT - 2, settle=1.0)
        moved = report(app)
        check("clicking near the bottom of the bar scrolls most of the way down",
              moved[0] > SHOWN // 2, str(moved))
        check("and the text agrees with the bar",
              top_line(app).startswith(f"line-{moved[0]:04d}"), top_line(app))

        app.send(b"\x1bx", settle=1.0)
        code = app.wait(timeout=6)
        check("exit code 0", code == 0, f"exit={code}")

        return check.report(app)
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
