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
F5 = b"\x1b[15~"
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

    zoom_checks(check, env)
    restore_checks(check, env)

    return check.report(app)


def zoom_checks(check, env):
    """A window born filling the desktop, and the un-zoom box it draws.

    Separate program rather than a second window in the same one, so that
    `frame()` above stays the simple thing it is: there is one window on screen
    either way.

    The icon is the assertion as much as the rectangle is. `TFrame::draw` picks
    between `[↑]` and `[↕]` on nothing but whether the window is at its maximum
    size, so a window that cannot un-zoom still draws the un-zoom box -- which
    is what made this reachable at all. Checking the geometry without the icon
    would miss the half of the bug that is a lie rather than a no-op.
    """
    app = Pty(node_argv(os.path.join(HERE, "regress_drag.js"), "maxed"), env,
              cwd=ROOT)
    try:
        app.pump(2.0)
        row, col, _ = frame(app)
        cols, rows = _window_width(app), _window_height(app)
        check("a window sized from onResize fills the desktop",
              (row, col) == (1, 0) and cols == 80 and rows == 23,
              f"at {row},{col} sized {cols}x{rows}")
        check("and draws the un-zoom box, not the zoom box",
              "[↕]" in app.render(), app.render().split("\n")[1])

        # The zoom box is five columns in from the right-hand end of the frame.
        app.click(col + cols - 4, row + 1, settle=0.8)
        small_row, small_col, _ = frame(app)
        small_cols, small_rows = _window_width(app), _window_height(app)
        check("clicking it makes the window smaller than the desktop",
              small_cols < cols and small_rows < rows,
              f"{cols}x{rows} -> {small_cols}x{small_rows}")
        check("three-quarters of it, in fact",
              (small_cols, small_rows) == (60, 17),
              f"{small_cols}x{small_rows}")
        check("centred, so there is desktop on all four sides",
              small_row > row and small_col > col
              and small_col + small_cols < cols,
              f"at {small_row},{small_col}")
        check("and the box becomes the zoom box again",
              "[↑]" in app.render(), app.render().split("\n")[small_row])

        # Back, and back again: the second zoom stores the rectangle the first
        # one restored to, so the pair has to be stable rather than only right
        # the first time.
        app.send(F5, settle=0.8)
        check("F5 maximizes it again",
              (_window_width(app), _window_height(app)) == (cols, rows)
              and "[↕]" in app.render(),
              f"{_window_width(app)}x{_window_height(app)}")
        app.send(F5, settle=0.8)
        check("and F5 again comes back to the same smaller rectangle",
              (frame(app)[0], frame(app)[1]) == (small_row, small_col)
              and (_window_width(app), _window_height(app))
                  == (small_cols, small_rows),
              f"{frame(app)[:2]} {_window_width(app)}x{_window_height(app)}")

        app.send(b"\x1bx", settle=1.0)
        check("the maximized one exits cleanly too", app.wait(timeout=6) == 0)
    finally:
        app.kill()


def restore_checks(check, env):
    """Un-zooming onto a desktop narrower than the one the window was zoomed on.

    `TWindow::zoom` records the window's bounds in `zoomRect` when it maximizes
    and restores them verbatim. `TView::locate` clamps the *size* against
    `sizeLimits` and takes the origin as given -- which is what its other
    callers need, since `moveGrow` has already done its own clamping and the
    Esc path deliberately restores bounds that may hang off an edge. So nothing
    reconciles a rectangle recorded against one desktop with the desktop it is
    being restored onto, and a window zoomed on a wide terminal and un-zoomed
    on a narrow one comes back beside the desktop instead of on it.

    Upstream does this too, and this is the only place the suite looks at zoom
    and resize *in that order* -- which is to say it is the only thing standing
    between `JsWindow::zoom`'s `fittedToDesktop` and quietly not mattering.
    """
    app = Pty(node_argv(os.path.join(HERE, "regress_drag.js")), env, cwd=ROOT)
    try:
        app.pump(2.0)
        row, col, _ = frame(app)
        check("the window opens away from the left edge",
              col == 20 and _window_width(app) == 40,
              f"at {row},{col}, {_window_width(app)} wide")

        app.send(F5, settle=0.8)
        check("F5 fills the desktop with it", _window_width(app) == 80,
              f"{_window_width(app)} wide")

        # Half the columns, while it is maximized. It has to follow the
        # terminal down, or the un-zoom below would be a re-zoom instead.
        app.resize(40, 25)
        check("and it follows the terminal down to half the width",
              _window_width(app) == 40, f"{_window_width(app)} wide")

        # The stored rectangle is columns 20..60 of a desktop that is now 40
        # wide. Restored as recorded it would start at column 20 and run twenty
        # columns off the right-hand side -- a top border with no corner on the
        # end of it, which is exactly the hole tiny_common.py looks for.
        app.send(F5, settle=0.8)
        back_row, back_col, _ = frame(app)
        line = app.display().text().splitlines()[back_row] if back_row is not None else ""
        check("un-zooming puts it back inside the smaller desktop",
              back_col == 0, f"at {back_row},{back_col}: {line!r}")
        check("the same size it was, whole, with both corners on screen",
              _window_width(app) == 40, f"{_window_width(app)} wide: {line!r}")

        app.send(b"\x1bx", settle=1.0)
        check("and it exits cleanly", app.wait(timeout=6) == 0)
    finally:
        app.kill()


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
