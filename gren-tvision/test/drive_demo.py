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

And the context menu, which makes the same point from a third direction and
one of its own: the clock has to keep ticking while the menu is open, because
Turbo Vision's own TMenuPopup would have stopped it.
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


def note_box(app, title):
    """(left column, row) of the frame line carrying this note's title."""
    for row, line in enumerate(app.render().split("\n")):
        if title in line and ("\u250c" in line or "\u2554" in line):
            upto = line.index(title)
            return (max(line.rfind("\u250c", 0, upto), line.rfind("\u2554", 0, upto)),
                    row)
    return None


def topmost_note(app):
    """The newest note, which is the one nothing is stacked on top of."""
    for title in sorted(frames(app), reverse=True):
        at = note_box(app, title)
        if at is not None:
            return (title, at)
    return (None, None)


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


def box_edges(screen, title):
    """(left, right) frame columns of the active dialog with this title.

    A dialog is the focused view, so its frame is the doubled one; the title
    row is the only place both corners appear.
    """
    for line in screen.split("\n"):
        if title in line and "╔" in line and "╗" in line:
            return (line.index("╔"), line.rindex("╗"))
    return None


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

    # The clock is an overlay -- a view on the *application*, which is what
    # TClockView is. It sits on the menu bar's row, at the right-hand end,
    # because overlays are in screen coordinates and row 0 is the menu bar's.
    # It used to be a status item, which worked and rebuilt the status line
    # once a second; that is the reason Borland made the clock a view.
    bar = app.render().split("\n")[0]
    check("the clock is a view on the menu bar's row, not a status item",
          re.search(r"\d\d:\d\d:\d\d", bar)
          and not re.search(r"\d\d:\d\d:\d\d", app.render().split("\n")[24]),
          bar)
    check("and it is against the right-hand edge",
          bar.rstrip().endswith(re.search(r"\d\d:\d\d:\d\d", bar).group(0)), bar)
    first_time = re.search(r"\d\d:\d\d:\d\d", bar).group(0)
    app.pump(1.6)
    later = re.search(r"\d\d:\d\d:\d\d", app.render().split("\n")[0])
    check("and it ticks", later and later.group(0) != first_time,
          f"{first_time} -> {later and later.group(0)}")

    # An overlay cannot be covered by a window, which is the difference between
    # a view on the application and a view on the desktop. Zooming a note fills
    # the desktop and leaves the clock where it is.
    at = note_box(app, "Note 2")
    app.click(at[0] + 3, at[1] + 2, settle=0.8)
    app.send(b"\x1b[15~", settle=1.0)          # F5 Zoom
    zoomed = app.render().split("\n")
    check("a zoomed window does not cover it",
          re.search(r"\d\d:\d\d:\d\d", zoomed[0]) is not None, zoomed[0])
    app.send(b"\x1b[15~", settle=1.0)          # and back

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

    # About is a message box now: the same dialog it always was, built by
    # Tui.messageBox instead of by hand. What the helper adds is that it
    # centres itself, which needs the desktop's size -- so this is also the
    # first thing in this example that depends on the Resized event.
    menu(app, "≡", 1)
    about = app.render()
    check("the About box opened", "TURBO VISION DEMO" in about, about)
    edges = box_edges(about, "About")
    # Within a column: the box is 45 wide on an 80-column desktop, and 35
    # columns of margin do not divide in two.
    check("and a message box centres itself on the desktop",
          edges is not None and abs(edges[0] - (79 - edges[1])) <= 1,
          f"frame at {edges} of 80 columns")
    app.send(b"\r", settle=0.9)
    check("and its OK button closed it", "TURBO VISION DEMO" not in app.render())

    # The colours dialog is five radio buttons, because a colour dialog is a
    # form and what it sets is a field.
    menu(app, "Options", 1)
    check("the colours dialog opened", "Note colour" in app.render(), app.render())
    app.send(b"\x1b[B", settle=0.4)
    app.send(b"\r", settle=0.9)
    check("and it closed", "Note colour" not in app.render(), app.render())

    # The context menu. Two right clicks and not one: the first is spent
    # activating the window, which is TView::handleEvent's rule for any click
    # on anything that is not already selected.
    note, at = topmost_note(app)
    check("a note is where its frame says it is", at is not None, app.render())
    app.right_click(at[0] + 3, at[1] + 2, settle=1.0)
    app.right_click(at[0] + 3, at[1] + 2, settle=1.2)
    opened = app.render()
    check("a right click opened a context menu",
          all(re.search(pattern, opened)
              for pattern in (r"Zoom\s+F5", r"Next\s+F6", r"Close\s+Alt-F3")),
          opened)
    check("and the model was told which button it was",
          any("right" in line for line in log(app)), str(log(app)))

    # The reason this is not TMenuPopup. Its execute() is TMenuView::execute(),
    # a getEvent loop, and running one from inside the pump stops Node's event
    # loop -- which the menu bar above still does and this does not. The clock
    # is the witness: a Time.every subscription, ticking behind the open menu.
    ticking = re.search(r"\d\d:\d\d:\d\d", app.render()).group(0)
    app.pump(3.2)
    check("the clock keeps ticking with the menu open",
          re.search(r"\d\d:\d\d:\d\d", app.render()).group(0) != ticking,
          f"clock stuck at {ticking}")

    # Choosing nothing is not observable in the log -- none of the three
    # commands on this menu reaches the model even when it *is* chosen, which
    # is the next check -- so what "nothing happened" means here is that no
    # window moved, zoomed or closed.
    untouched = frames(app)
    app.send(b"\x1b", settle=1.0)
    check("Esc closes it and chooses nothing",
          not re.search(r"Close\s+Alt-F3", app.render())
          and frames(app) == untouched,
          f"{untouched} -> {frames(app)}")

    # And what it chooses is an ordinary command. "zoom" is Turbo Vision's own
    # -- the model does not handle it and never hears about it -- so this is
    # the same assertion the Tile check below makes, arriving by a third route
    # after the menu bar and the F5 key.
    at = note_box(app, note)
    app.right_click(at[0] + 3, at[1] + 2, settle=1.0)
    app.send(b"z", settle=1.2)
    check("a letter picks the entry it underlines, and Zoom zoomed",
          note_box(app, note) == (0, 1), str(note_box(app, note)))
    check("and zooming did not reach the model either",
          not any("Command zoom" in line for line in log(app)), str(log(app)))
    app.send(b"\x1b[15~", settle=1.0)   # F5 again: back where it was

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
