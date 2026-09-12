#!/usr/bin/env python3
"""Photograph the `TWindow::zoom` bug in upstream's own tvdemo.

The pictures in `docs/upstream-zoomrect-origin.md`, taken the way every other
screenshot in this repository is taken -- a real program at a real pty, replayed
into `harness.Screen` and blitted by `tools/shot.py`. Nothing is drawn by hand,
which for a bug report is the whole point: the empty desktop in `3-gone.png` is
what tvdemo actually painted.

It photographs **two builds of tvdemo one commit apart**, which is what makes
the pair an argument rather than an anecdote. `patches~1` has every other fix
this fork carries -- #235's `calcBounds` clamp included, without which the
terminal resize itself would misplace the window and muddy the picture -- and
`patches` adds the `TWindow::zoom` commit and nothing else.

Building the two is not part of `devbox run check` and never will be; it wants
two worktrees and two copies of the library, four minutes all in:

    cd tvision-node/tvision
    git worktree add /tmp/wt-bug patches~1
    git worktree add /tmp/wt-fix patches
    cd -
    devbox run -- bash docs/build-tvdemo.sh /tmp/wt-bug
    devbox run -- bash docs/build-tvdemo.sh /tmp/wt-fix
    devbox run -- python3 docs/shots-zoomrect.py /tmp/wt-bug /tmp/wt-fix

All of this -- the script, the builder and the images -- goes away with the
report, the day the bug has an issue number.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tvision-node", "test"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from harness import Pty          # noqa: E402
from shot import shot            # noqa: E402

IMG = os.path.join(HERE, "img", "upstream-zoomrect")

# xterm's encodings, the same constants drive_drag.py uses.
CTRL_F5 = b"\x1b[15;5~"
F5 = b"\x1b[15~"
SHIFT_LEFT, SHIFT_UP = b"\x1b[1;2D", b"\x1b[1;2A"
RIGHT, DOWN = b"\x1b[C", b"\x1b[B"
ENTER = b"\r"

WIDE, TALL = 100, 30


def frame(app):
    """(left, right) columns of the topmost window frame, or (None, None).

    `right` is None when the window's right-hand corner is off the screen,
    which is one of the things being photographed.

    Both spellings: a window is double-lined while it owns the caret and
    single-lined while `Ctrl-F5` is moving it.
    """
    for line in app.display().text().splitlines():
        for left, right in (("╔", "╗"), ("┌", "┐")):
            a = line.find(left)
            if a >= 0:
                b = line.find(right, a)
                return a, (b + 1 if b > a else None)
    return None, None


def place(app):
    """tvdemo's file window opens maximized. Put it somewhere ordinary.

    Ctrl-F5, forty columns wide and eighteen rows tall, flush against the
    right-hand edge and three rows down -- which is the rectangle the report
    names: (60, 4, 100, 22) on a hundred-column terminal.
    """
    app.send(CTRL_F5, settle=0.8)
    app.send(SHIFT_LEFT * 60, wait=3.0)
    app.send(SHIFT_UP * 10, wait=2.0)
    app.send(RIGHT * 60, wait=3.0)
    app.send(DOWN * 3, wait=1.5)
    app.send(ENTER, settle=0.8)


def run(tvdemo, width, out, keep_placed=False):
    """Place, zoom, resize to `width`, un-zoom. Photograph the last of those."""
    demo = os.path.join(os.path.dirname(tvdemo), "examples", "tvdemo")
    env = dict(os.environ, TERM="xterm-256color", TVNODE_TAPES="0")
    app = Pty([tvdemo, "fileview.cpp"], env, cwd=demo, size=(WIDE, TALL))
    try:
        app.pump(2.5)
        place(app)
        placed = frame(app)
        if keep_placed:
            shot(app, os.path.join(IMG, "1-placed.png"))

        app.send(F5, settle=1.0)
        zoomed = frame(app)

        app.resize(width, TALL)
        followed = frame(app)
        if keep_placed:
            shot(app, os.path.join(IMG, "2-maximized.png"))

        app.send(F5, settle=1.0)
        restored = frame(app)
        shot(app, os.path.join(IMG, out))
        return placed, zoomed, followed, restored
    finally:
        app.kill()


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    bug = os.path.join(sys.argv[1], "tvdemo")
    fix = os.path.join(sys.argv[2], "tvdemo")
    for path in (bug, fix):
        if not os.path.exists(path):
            print(f"no tvdemo at {path} -- see this file's docstring")
            return 2

    os.makedirs(IMG, exist_ok=True)
    bad = 0

    def says(name, got, want):
        nonlocal bad
        ok = got == want
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got}"
              + ("" if ok else f", wanted {want}"))

    print("patches~1 (no zoom fix), un-zoomed on a 60-column terminal:")
    placed, zoomed, followed, restored = run(bug, 60, "3-gone.png",
                                             keep_placed=True)
    says("placed flush right", placed, (60, 100))
    says("zoomed to the whole desktop", zoomed, (0, 100))
    says("and follows the terminal down", followed, (0, 60))
    says("un-zoomed: no frame on the screen at all", restored, (None, None))

    print("patches~1, un-zoomed on an 80-column terminal:")
    _, _, _, restored = run(bug, 80, "4-half.png")
    says("un-zoomed: starts at 60, right edge off the screen",
         restored, (60, None))

    print("patches (with the zoom fix), un-zoomed on 60 columns:")
    _, _, _, restored = run(fix, 60, "5-patched.png")
    says("un-zoomed: forty columns, still flush right", restored, (20, 60))

    print(f"\n{'every shot says what it should' if not bad else str(bad) + ' wrong'}"
          f" -- {IMG}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
