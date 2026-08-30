#!/usr/bin/env python3
"""examples/demo -- tvdemo's shell, in Gren.

The parts of tvdemo that are about the application rather than about one of the
demos inside it: several windows, the `Windows` menu, the event viewer and the
clock.

What this really tests is a boundary. `Tile`, `Cascade`, `Zoom` and `Next` move
windows around, and none of them reach the model -- Turbo Vision does them and
says nothing. So the test drives them from the menu and checks the windows
moved, while the model goes on rendering the same rectangles it started with.
If `view` were re-asserting positions, tiling would snap straight back.

It also checks the bug this example found: `"tile"` and `"cascade"` were
documented as built-in command names and were not interned as such, so they
arrived in the model as ordinary events and moved nothing.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLE = os.path.join(ROOT, "examples", "demo")
RUNTIME = os.path.join(ROOT, "..", "gren-tvision-runtime", "bin", "gren-tui.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

F2 = b"\x1bOQ"


def frames(app):
    """Where each note window's title bar is, as {title: (col, row)}."""
    found = {}
    for row, line in enumerate(app.render().split("\n")):
        for m in re.finditer(r"(Note \d+)", line):
            # Only the frame line has box characters around the title.
            if "─" in line or "═" in line:
                found.setdefault(m.group(1), (m.start(), row))
    return found


def log(app):
    """The event viewer's lines."""
    rows = app.render().split("\n")
    return [rows[r][42:77].strip() for r in range(3, 18)]


def menu(app, item, entry):
    """Open a pull-down by clicking its name, then click the `entry`-th line in
    it (1-based). Row 0 is the menu bar and row 1 is the box's own border, so
    the first entry is on row 2 -- which is row 3 to `click`."""
    bar = app.render().split("\n")[0]
    at = bar.index(item)
    app.click(at + 1, 1, settle=0.6)
    app.click(at + 3, entry + 2, settle=0.9)


def press(app, label):
    """Click a button by its caption, wherever it currently is. Buttons only
    answer their hotkey while their window is the active one, and half of this
    test is about windows moving.

    Twice, because the first click on an inactive window is spent activating it
    and never reaches the control underneath."""
    for row, line in enumerate(app.render().split("\n")):
        at = line.find(label)
        if at >= 0:
            app.click(at + 2, row + 1, settle=0.4)
            app.click(at + 2, row + 1, settle=0.9)
            return True
    return False


def main():
    check = Checks()
    env = dict(os.environ, TERM="xterm-256color")
    app = Pty(node_argv(RUNTIME, "main.js"), env, cwd=EXAMPLE)

    app.pump(2.5)
    screen = app.render()
    check("the menu bar came from the view",
          all(x in screen.split("\n")[0] for x in ("File", "Windows", "Options")),
          screen.split("\n")[0])
    check("two notes and the event viewer are on the desktop",
          len(frames(app)) == 2 and "Event Viewer" in screen, str(frames(app)))

    # The clock is a status item, so it is on the last line and it moves.
    status = app.render().split("\n")[24]
    check("the clock is in the status line", re.search(r"\d\d:\d\d:\d\d", status),
          status)
    first_time = re.search(r"\d\d:\d\d:\d\d", status).group(0)
    app.pump(1.6)
    later = re.search(r"\d\d:\d\d:\d\d", app.render().split("\n")[24])
    check("and it ticks", later and later.group(0) != first_time,
          f"{first_time} -> {later and later.group(0)}")

    app.send(F2, settle=0.8)
    check("F2 opens another note", len(frames(app)) == 3, str(frames(app)))

    # Every one of those went through the model, so the viewer has them.
    check("the event viewer recorded the command",
          any("Command new" in line for line in log(app)), str(log(app)))

    # The viewer can be stopped, which is what the original's title says.
    check("Stop is on the viewer", press(app, "Stop"))
    check("Stop renames the viewer", "Event Viewer (Stopped)" in app.render(),
          app.render())
    frozen = log(app)
    app.send(F2, settle=0.8)
    check("and nothing is recorded while it is stopped", log(app) == frozen,
          f"{frozen} -> {log(app)}")
    press(app, "Start")
    press(app, "Clear")
    check("Clear empties it", all(line == "" for line in log(app)), str(log(app)))

    # The colours dialog is five radio buttons, because a colour dialog is a
    # form and what it sets is a field.
    menu(app, "Options", 1)
    check("the colours dialog opened", "Note colour" in app.render(), app.render())
    app.send(b"\x1b[B", settle=0.4)
    app.send(b"\r", settle=0.9)
    check("and it closed", "Note colour" not in app.render(), app.render())

    # Now the part this example exists for.
    before = frames(app)
    menu(app, "Windows", 5)          # Tile
    tiled = frames(app)
    check("Tile moved the windows", tiled != before, f"{before} -> {tiled}")
    check("and all four are visible once tiled, which they were not before",
          len(tiled) == 4 and len(before) < 4,
          f"{sorted(before)} -> {sorted(tiled)}")

    # Nothing about tiling reached the model: it is Turbo Vision's own command
    # and never arrives as an event.
    check("Tile did not arrive in the model as an event",
          not any("Command tile" in line for line in log(app)), str(log(app)))

    # ...and the model has gone on rendering the rectangles it started with,
    # which does not drag anything back. The clock guarantees a render a
    # second, so waiting is enough to prove it.
    app.pump(2.0)
    after = frames(app)
    check("renders keep arriving and the tiled windows stay put", after == tiled,
          f"{tiled} -> {after}")

    menu(app, "Windows", 6)          # Cascade
    cascaded = frames(app)
    check("Cascade moved them again", cascaded != tiled, f"{tiled} -> {cascaded}")

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("exit code 0", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
