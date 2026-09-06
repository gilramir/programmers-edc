#!/usr/bin/env python3
"""The nested loops that were left, measured rather than assumed.

`TView::dragView` was rewritten because it was a nested `getEvent` loop with no
exit anyone would guess and no feedback anyone would notice -- it read as a
hang, and it burned a core while it did. The commit that fixed it listed the
loops it deliberately left alone: a button, a check box, a scroll bar, a list
viewer, an input line, the editor, the status line and the close box, all of
them `TView::mouseEvent`, all of them ending when the finger comes up. Only the
close box has ever been driven.

**And the list was one short.** `TGroup::execView` is a nested loop of a second
kind. The menu bar runs in one and the context menu runs in one, and both are
documented -- but so does `THistoryWindow` (thistory.cpp:101), which is opened
from inside `TInputLine::handleEvent` when the user clicks the `▼` beside a
field, and nothing anywhere says what it costs. Two drop-downs in this repo use
it: `predc`'s hex viewer and `examples/dir`.

What each loop is asked here is the pair of questions that told `dragView`
apart from a working program, because a frozen program and a live one draw the
identical screen:

  - **Does it spin?** `eventTimeoutMs` is 0 so that the pump never blocks,
    which inside a nested loop means polling that never sleeps -- 100 ticks of
    CPU a second doing nothing. `NestedLoopTimeout` raises it to 20 for the
    duration of `handleEvent`, and every loop below is reached from there, so
    every one of them should be quiet. Only one of them was ever checked.
  - **Does Node keep running?** `ticks:` in the window is a plain setInterval.
    A number that climbs while a gesture is held is the event loop still
    getting a turn. Some of these are *expected* to freeze -- a modal window
    is modal -- and the point of measuring is to say which, rather than to
    find out the first time somebody's clock stops.
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from harness import Pty, Checks, node_argv

# 100% of one core is 100 ticks a second. Idle is one or two; the bug was 100.
# Twenty is far above anything this app does and far below a spin.
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


def ticks(app):
    """The counter setInterval paints, or -1 if it is not on screen."""
    for line in app.display().text().splitlines():
        if "ticks:" in line:
            return int(line.split("ticks:")[1].split()[0])
    return -1


def press(app, col, row, button=0):
    """Press and hold, without releasing. `release` is the other half."""
    app.send(f"\x1b[<{button};{col};{row}M".encode(), settle=0.2)


def release(app, col, row, button=0):
    app.send(f"\x1b[<{button};{col};{row}m".encode(), settle=0.3)


def find(app, text):
    """1-based (col, row) of `text` on the screen, for Pty.click."""
    for row, line in enumerate(app.render().split("\n")):
        col = line.find(text)
        if col >= 0:
            return col + 1, row + 1
    return None, None


def heard(app):
    """The fixture's count of callbacks, or -1 if it is not on screen."""
    for line in app.display().text().splitlines():
        if "heard:" in line:
            return int(line.split("heard:")[1].split()[0])
    return -1


def held(check, app, what, col, row):
    """Hold something down, measure it, let go, and prove the press landed.

    The last of those is not a formality. A press that missed its widget
    entirely produces a quiet CPU and a live counter, which is exactly what
    these checks are looking for -- so a hold that reached nothing would pass
    every one of them. `heard:` counts the callbacks the gesture caused, and it
    is what says the loop being measured was entered at all.
    """
    was = heard(app)
    press(app, col, row)
    rate = cpu_rate(app)
    release(app, col, row)
    check(f"holding {what} does not spin a core", rate < SPIN, f"{rate:.0f} ticks/s")
    after = cpu_rate(app, seconds=1.0)
    check(f"and letting go of {what} leaves it quiet", after < SPIN,
          f"{after:.0f} ticks/s")
    check(f"and the press reached {what} rather than the desktop",
          heard(app) > was, f"heard stuck at {was}")


def main():
    check = Checks()
    env = dict(os.environ, TERM="xterm-256color")
    app = Pty(node_argv(os.path.join(HERE, "regress_loops.js")), env, cwd=ROOT)

    app.pump(2.0)
    check("the window is up", "Loops" in app.render(), app.render())
    check("with a counter in it", ticks(app) >= 0, app.render())
    check("idle does not spin", cpu_rate(app) < SPIN, app.render())

    # 1. The history drop-down: a modal window inside `TInputLine`'s own event
    #    handler, and the loop nobody wrote down.
    # `▐↓▌` and not `▼`: the history icon is three cells that `THistory::draw`
    # paints itself, and the `▼` on this screen belongs to a scroll bar.
    arrow_col, arrow_row = find(app, "↓")
    check("the field has a history arrow beside it", arrow_col is not None,
          app.render())
    before = ticks(app)
    app.click(arrow_col, arrow_row, settle=0.8)
    dropped = app.render()
    check("clicking it drops the history down",
          "alpha" in dropped and "delta" in dropped, dropped)
    rate = cpu_rate(app)
    during = ticks(app)
    check("an open history drop-down does not spin a core", rate < SPIN,
          f"{rate:.0f} ticks/s")
    # And the half that had never been asked. Borland opens this list with
    # `owner->execView()`, which is `TGroup::execute` -- a nested loop, and the
    # whole of Node stopped for as long as the list is up, the way the menu
    # bar's pull-down still stops it. `JsHistory::openDropDown` calls
    # `openLocalModal` instead, and the comment above it says the model keeps
    # running behind the drop-down. Nothing checked that it does, and nothing
    # could see it either way: a frozen program and a live one draw the same
    # list.
    check("and the model keeps running behind it, which is what openLocalModal "
          "buys and execView would not",
          during > before, f"ticks stuck at {before}")
    app.send(b"\x1b", settle=0.6)
    check("Esc closes it", "alpha" not in app.render(), app.render())
    check("and it is quiet again", cpu_rate(app) < SPIN, app.render())

    # A terminal somebody drags while a modal is on the screen. The rectangle
    # this list was given was computed against the desktop it opened on, so
    # this is the resize that has no obvious right answer -- and the only thing
    # that must not happen is that the program stops.
    app.click(arrow_col, arrow_row, settle=0.8)
    check("the drop-down is up again", "alpha" in app.render(), app.render())
    stopped = ticks(app)
    app.resize(100, 30)
    check("resizing the terminal under an open drop-down does not stop it",
          ticks(app) > stopped, f"ticks stuck at {stopped}")
    check("and does not spin", cpu_rate(app) < SPIN, app.render())
    app.send(b"\x1b", settle=0.6)
    check("and the window is still there afterwards", "Loops" in app.render(),
          app.render())

    # 2. The stock widgets, each of which tracks the mouse in a loop of its
    #    own and each of which ends when the finger comes up. None of them had
    #    ever been held down by a test.
    col, row = find(app, "Press")
    held(check, app, "a button", col, row)

    col, row = find(app, "[ ] one")
    held(check, app, "a check box", col, row)

    col, row = find(app, "row 3")
    held(check, app, "a list box", col, row)

    # A scroll bar's arrow is the one that repeats while it is held, which is
    # why it is the loop most likely to spin: `TScrollBar::handleEvent` tracks
    # the button and steps the value on a timer for as long as it is down.
    col, row = find(app, "▲")
    held(check, app, "a scroll bar's arrow", col, row)

    # And the status line, which was the one that was broken.
    #
    # `F2 Note` and not `Alt-X Exit`: letting go of an item runs its command,
    # and the command on the first one ends the program. A driver that held
    # that one measured a spin and then had nothing left to ask.
    col, row = find(app, "F2 Note")
    held(check, app, "the status line", col, row)

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=8)
    check("Alt-X exits, and cleanly", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
