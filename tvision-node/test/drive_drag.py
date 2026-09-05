#!/usr/bin/env python3
"""Moving and resizing a window, and Node still running while it happens.

Turbo Vision does all five of those gestures -- the title bar, both grow
corners, a middle-click on the body, and `cmResize` off the Window menu -- in
`TView::dragView`, which is `do { getEvent(event); } while(...)`. Under the pump
that nested loop is Node's event loop stopped: no timers, no promises, no
subscriptions, no renders. `JsWindow::dragView` overrides it into a state the
pump feeds instead, and this is what says so.

**The counter is the real assertion.** `ticks:` in the window is painted by a
plain setInterval, so a number that climbs while the window is being held is
Node getting a turn mid-gesture -- which is the whole of what was broken, and
which no amount of looking at the frame would show.

**The second one is the CPU.** `eventTimeoutMs` is 0, because the pump must
never block; a nested loop under that setting polls without ever sleeping and
spins a core flat. That is measurable and nothing else here is: the mode off
the Window menu ends only on Enter or Esc, and on a maximized window every
arrow key is pinned by the size limits, so a hung app and a working one draw the
identical screen. It was reported as a hang, and it was diagnosed from
`/proc/<pid>/stat` before it was diagnosed from anything on screen.

The close box keeps its own nested loop (tframe.cpp:157) and so do the stock
widgets, because those end when the finger comes up. What they must not do any
more is spin, and the last section here is about that rather than about the
box.
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from harness import Pty, Checks, node_argv

# Ctrl-F5 and F5 in xterm's encoding. The modifier is the `;5`, which is what
# `TERM=xterm-256color` sends and what termio.cpp reads back out.
CTRL_F5 = b"\x1b[15;5~"
UP, DOWN, RIGHT = b"\x1b[A", b"\x1b[B", b"\x1b[C"
# Shift-arrow is what turns a move into a grow: TView::change consults kbShift.
SHIFT_RIGHT = b"\x1b[1;2C"
ESC, ENTER = b"\x1b", b"\r"

# 100% of one core is 100 ticks a second. Idle is one or two; the bug was 100.
# Twenty is far above anything this app does and far below a spin, so it does
# not need a quiet machine to be right.
SPIN = 20


def cpu_ticks(pid):
    """User plus system jiffies. Fields 14 and 15 of /proc/<pid>/stat."""
    fields = open(f"/proc/{pid}/stat").read().split()
    return int(fields[13]) + int(fields[14])


def cpu_rate(app, seconds=1.5):
    before = cpu_ticks(app.pid)
    started = time.time()
    app.pump(seconds)
    return (cpu_ticks(app.pid) - before) / (time.time() - started)


def frame(app):
    """(row, col) of the window's top-left corner, and whether it is dragging.

    `sfDragging` is drawn as a single-line frame where a selected window has a
    double one (TFrame::draw), and that is the only thing on screen that says
    the mode is on at all.
    """
    for row, line in enumerate(app.display().text().splitlines()):
        for corner, dragging in (("╔", False), ("┌", True)):
            col = line.find(corner)
            if col >= 0:
                return row, col, dragging
    return None, None, False


def ticks(app):
    """The counter setInterval paints, or -1 if it is not on screen."""
    for line in app.display().text().splitlines():
        if "ticks:" in line:
            return int(line.split("ticks:")[1].split()[0])
    return -1


def main():
    check = Checks()
    env = dict(os.environ, TERM="xterm-256color")
    app = Pty(node_argv(os.path.join(HERE, "regress_drag.js")), env, cwd=ROOT)

    app.pump(2.0)
    row, col, dragging = frame(app)
    check("the window is up", row is not None, app.render())
    check("and is not dragging", not dragging, f"frame at {row},{col}")
    idle = cpu_rate(app)
    check("idle does not spin", idle < SPIN, f"{idle:.0f} ticks/s")

    # ---------------------------------------------------------------- #
    #  The mode off the Window menu: the one that was a hang            #
    # ---------------------------------------------------------------- #

    app.send(CTRL_F5, settle=0.6)
    _, _, dragging = frame(app)
    check("Ctrl-F5 starts the mode", dragging, "frame is still double-lined")

    before = ticks(app)
    busy = cpu_rate(app)
    check("dragging does not spin", busy < SPIN, f"{busy:.0f} ticks/s")
    check("Node keeps running while dragging", ticks(app) > before,
          f"ticks stuck at {before}")

    start_row, start_col, _ = frame(app)
    for _ in range(2):
        app.send(DOWN, settle=0.3)
    for _ in range(3):
        app.send(RIGHT, settle=0.3)
    moved_row, moved_col, _ = frame(app)
    check("arrows move the window",
          (moved_row, moved_col) == (start_row + 2, start_col + 3),
          f"{start_row},{start_col} -> {moved_row},{moved_col}")

    # The menu bar, which the mode is supposed to swallow -- this is what a
    # user reported as "none of the menus work", and it is correct.
    app.send(b"\x1bw", settle=0.5)
    check("the mode swallows the menu bar", "Resize/move" not in app.render(),
          "the Window menu opened mid-drag")

    app.send(ENTER, settle=0.6)
    kept_row, kept_col, dragging = frame(app)
    check("Enter ends the mode", not dragging, "frame is still single-lined")
    check("and keeps where it was dragged to",
          (kept_row, kept_col) == (moved_row, moved_col),
          f"{moved_row},{moved_col} -> {kept_row},{kept_col}")
    after = cpu_rate(app)
    check("and stops spinning", after < SPIN, f"{after:.0f} ticks/s")

    # Esc is the other way out, and it puts the window back.
    app.send(CTRL_F5, settle=0.6)
    for _ in range(3):
        app.send(UP, settle=0.3)
    up_row, _, _ = frame(app)
    check("Esc had something to undo", up_row == kept_row - 3,
          f"{kept_row} -> {up_row}")
    app.send(ESC, settle=0.6)
    back_row, back_col, dragging = frame(app)
    check("Esc ends the mode", not dragging, "frame is still single-lined")
    check("and puts the window back", (back_row, back_col) == (kept_row, kept_col),
          f"{kept_row},{kept_col} -> {back_row},{back_col}")

    # Shift is the difference between moving and growing, and it is the half of
    # dragView that a move never exercises.
    width_before = _window_width(app)
    app.send(CTRL_F5, settle=0.6)
    for _ in range(4):
        app.send(SHIFT_RIGHT, settle=0.3)
    app.send(ENTER, settle=0.6)
    check("Shift-arrow grows instead of moving",
          _window_width(app) == width_before + 4,
          f"{width_before} -> {_window_width(app)}")
    same_row, same_col, _ = frame(app)
    check("and leaves the corner where it was",
          (same_row, same_col) == (back_row, back_col),
          f"{back_row},{back_col} -> {same_row},{same_col}")

    # ---------------------------------------------------------------- #
    #  The mouse, which is the same loop reached from the frame         #
    # ---------------------------------------------------------------- #

    row, col, _ = frame(app)
    # Press on the title bar and hold, without releasing: this is the state the
    # nested loop used to sit in.
    app.send(f"\x1b[<0;{col + 10};{row + 1}M".encode(), settle=0.3)
    before = ticks(app)
    held = cpu_rate(app)
    check("holding the title bar does not spin", held < SPIN, f"{held:.0f} ticks/s")
    check("Node keeps running while the button is down", ticks(app) > before,
          f"ticks stuck at {before}")

    app.send(f"\x1b[<32;{col + 13};{row + 3}M".encode(), settle=0.4)
    dragged_row, dragged_col, dragging = frame(app)
    check("the window follows the pointer",
          (dragged_row, dragged_col) == (row + 2, col + 3),
          f"{row},{col} -> {dragged_row},{dragged_col}")
    check("and says so with its frame", dragging, "frame is not single-lined")

    app.send(f"\x1b[<0;{col + 13};{row + 3}m".encode(), settle=0.5)
    up_row, up_col, dragging = frame(app)
    check("the release ends the drag", not dragging, "frame is still single-lined")
    check("and leaves the window where it was let go",
          (up_row, up_col) == (dragged_row, dragged_col),
          f"{dragged_row},{dragged_col} -> {up_row},{up_col}")

    # The bottom-right grow corner: dmDragGrow rather than dmDragMove, which is
    # a different branch of the same override.
    row, col, _ = frame(app)
    width_before = _window_width(app)
    height_before = _window_height(app)
    bottom = row + height_before - 1
    right = col + width_before - 1
    app.drag([(right + 1, bottom + 1), (right + 4, bottom + 3)], settle=0.5)
    check("the grow corner resizes rather than moves",
          _window_width(app) == width_before + 3
          and _window_height(app) == height_before + 2,
          f"{width_before}x{height_before} -> "
          f"{_window_width(app)}x{_window_height(app)}")
    still_row, still_col, _ = frame(app)
    check("and leaves the top-left corner alone",
          (still_row, still_col) == (row, col),
          f"{row},{col} -> {still_row},{still_col}")

    # The bottom-*left* corner is `dmDragGrowLeft`, the third mouse branch and
    # the one worth a check of its own: it is the only one that keeps a
    # rectangle across the gesture rather than recomputing from origin and
    # size, because the right edge has to stay where it was while the left one
    # follows the pointer. A transcription slip would live exactly here.
    row, col, _ = frame(app)
    width_before = _window_width(app)
    height_before = _window_height(app)
    check("there is room to grow leftwards", col >= 3, f"window at column {col}")
    bottom = row + height_before - 1
    app.drag([(col + 1, bottom + 1), (col - 1, bottom + 3)], settle=0.5)
    grown_row, grown_col, _ = frame(app)
    check("the left corner grows leftwards and downwards",
          _window_width(app) == width_before + 2
          and _window_height(app) == height_before + 2,
          f"{width_before}x{height_before} -> "
          f"{_window_width(app)}x{_window_height(app)}")
    check("and the right edge stays where it was",
          grown_col == col - 2 and grown_row == row,
          f"{row},{col} -> {grown_row},{grown_col}")

    # ---------------------------------------------------------------- #
    #  What is deliberately still a nested loop                         #
    # ---------------------------------------------------------------- #

    row, col, _ = frame(app)
    app.send(f"\x1b[<0;{col + 3};{row + 1}M".encode(), settle=0.3)
    box = cpu_rate(app)
    check("holding the close box does not spin either", box < SPIN,
          f"{box:.0f} ticks/s")
    # Dragged off the box, so the window survives to be exited from.
    app.send(f"\x1b[<32;{col + 20};{row + 1}M".encode(), settle=0.2)
    app.send(f"\x1b[<0;{col + 20};{row + 1}m".encode(), settle=0.5)
    check("and letting go away from it does not close the window",
          frame(app)[0] is not None, app.render())

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("exit code 0", code == 0, f"exit={code}")

    return check.report(app)


def _window_width(app):
    """The width of the frame's top edge, corners included."""
    for line in app.display().text().splitlines():
        for left, right in (("╔", "╗"), ("┌", "┐")):
            a, b = line.find(left), line.find(right)
            if a >= 0 and b > a:
                return b - a + 1
    return -1


def _window_height(app):
    rows = app.display().text().splitlines()
    top = bottom = None
    for i, line in enumerate(rows):
        if top is None and ("╔" in line or "┌" in line):
            top = i
        if top is not None and ("╚" in line or "└" in line):
            bottom = i
            break
    return -1 if top is None or bottom is None else bottom - top + 1


if __name__ == "__main__":
    sys.exit(main())
