#!/usr/bin/env python3
"""examples/entries -- a Turbo Vision application written in Gren.

Every check here crosses the whole stack -- Gren model, JSON over a port, the
diff in tui.js, the N-API binding, TVision, and the terminal -- and back.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # the Gren package
EXAMPLE = os.path.join(ROOT, "examples", "entries")
from harness_path import RUNTIME  # finds harness.py and gren-tui.js, here or in an install

from harness import Pty, Checks, latest_int, node_argv

TICKS = r"ticks: (\d+)"


def active(screen, title):
    """Is the window with this title the active one?

    Turbo Vision draws the active window's frame with a double line and every
    other window's with a single one, which is the only evidence on screen of
    where focus went -- and the two windows here share their top row, so this
    reads the frame run immediately left of the title rather than the row.
    """
    for line in screen.split("\n"):
        at = line.find(title)
        if at < 0:
            continue
        i = at - 1
        while i >= 0 and line[i] == " ":
            i -= 1
        if i >= 0 and line[i] in "═─":
            return line[i] == "═"
    return None

# The list window's close box. Window rectangles are *desktop* coordinates, so
# y=1 is the second row under the menu bar -- screen row 3, counting from 1.
CLOSE_BOX = (5, 3)


def corners(screen):
    """The frame columns of the two windows, which share a row.

    The list window is on the left, so of the two right-hand corners on that
    row the leftmost is its; the clock is on the right, so of the two left-hand
    corners the rightmost is its. Either corner is doubled when its window is
    the active one, hence both characters in each set.
    """
    found = {}
    for line in screen.split("\n"):
        if "Entries (" in line:
            found["list_right"] = min(i for i, c in enumerate(line) if c in "┐╗")
        if " Gren " in line and ("┌" in line or "╔" in line):
            found["clock_left"] = max(i for i, c in enumerate(line) if c in "┌╔")
            found["clock_right"] = max(i for i, c in enumerate(line) if c in "┐╗")
    return found


def row_of(screen, text):
    """Which screen row `text` is on, or -1."""
    for i, line in enumerate(screen.split("\n")):
        if text in line:
            return i
    return -1


def bottom_of_list(screen):
    """The screen row of the list window's bottom frame.

    The leftmost window on the screen, so it is the one whose bottom-left
    corner is the first thing on its row -- which stays true when it is zoomed
    and starts at column zero rather than column one.
    """
    rows = screen.split("\n")
    return max((i for i, l in enumerate(rows) if l.lstrip("░ ")[:1] in ("└", "╚")),
               default=-1)


def zoom_box(screen, title):
    """(col, row) of the zoom box on a window's frame, 0-based.

    Turbo Vision only draws it on the *active* window, so the window has to
    have been brought forward first.
    """
    for row, line in enumerate(screen.split("\n")):
        if title in line and "[↑]" in line:
            return (line.index("[↑]"), row)
    return None


def box_edges(screen, title):
    """(left, right) frame columns of the active dialog with this title.

    A dialog has the focus, so its frame is the doubled one, and the title row
    is the only place both of its corners appear.
    """
    for line in screen.split("\n"):
        if title in line and "╔" in line and "╗" in line:
            return (line.index("╔"), line.rindex("╗"))
    return None


def clear_menu(app):
    """Entries > Clear, which is the third line of the first pull-down."""
    bar = app.render().split("\n")[0]
    at = bar.index("Entries")
    app.click(at + 1, 1, settle=0.6)
    app.click(at + 3, 6, settle=1.0)


def resizes(check):
    """A second application, in a terminal that is not 80x25 and then changes.

    Every example here used to hardcode 80x25 and there was no way not to:
    screenSize() was in the binding with no message to carry it. This one is
    told, by a Resized event that arrives once at startup and again whenever
    the terminal changes.
    """
    env = dict(os.environ, TERM="xterm-256color")
    app = Pty(node_argv(RUNTIME, "main.js"), env, cwd=EXAMPLE, size=(100, 30))
    try:
        app.pump(2.0)
        at100 = app.render()
        check("a 100-column terminal is laid out as 100 columns",
              corners(at100).get("list_right") == 65,
              f"corners {corners(at100)}")
        check("the panel is against the right-hand edge, wherever it is",
              corners(at100).get("clock_right") == 98,
              f"corners {corners(at100)}")
        check("and the desktop's full height is used",
              bottom_of_list(at100) == 22, f"bottom {bottom_of_list(at100)}")

        # The event arrives again, and the model lays out again. Turbo Vision
        # moves the windows itself first -- a window is gfGrowRel, so it is
        # rescaled proportionally before anyone is told -- and then the model's
        # own rectangles replace that.
        app.resize(120, 40)
        at120 = app.render()
        check("growing the terminal re-laid the windows out",
              corners(at120).get("list_right") == 85, f"corners {corners(at120)}")
        check("the panel followed the new right-hand edge",
              corners(at120).get("clock_right") == 118, f"corners {corners(at120)}")
        check("and the new height too", bottom_of_list(at120) == 32,
              f"bottom {bottom_of_list(at120)}")

        # And the views inside followed, which is a second mechanism and not the
        # same one: the model gave these a `Grows`, the differ resized the
        # window in place instead of rebuilding it, and TGroup::changeBounds
        # moved the edges that were told to follow. Rebuild the window instead
        # and every child comes back at the rectangle the model wrote down.
        off_foot = lambda s: bottom_of_list(s) - row_of(s, "Add...")
        check("a pinned button stayed the same distance off the window's foot",
              off_foot(at120) == off_foot(at100) == 2,
              f"{off_foot(at100)} rows at 100x30, {off_foot(at120)} at 120x40")
        check("and the list box stretched into the space above it",
              row_of(at120, "Selected:") - row_of(at100, "Selected:") == 10,
              f"the caption moved {row_of(at120, 'Selected:') - row_of(at100, 'Selected:')} "
              f"rows for a window that grew 10")

        # And shrinking is the same event with smaller numbers.
        app.resize(80, 25)
        at80 = app.render()
        check("shrinking it back gives the 80-column layout exactly",
              corners(at80).get("list_right") == 45
              and corners(at80).get("clock_right") == 78
              and bottom_of_list(at80) == 17
              and row_of(at80, "Add...") == 15,
              f"corners {corners(at80)} bottom {bottom_of_list(at80)} "
              f"button {row_of(at80, 'Add...')}")

        app.send(b"\x1bx", settle=1.0)
        check("exit code 0 after three sizes", app.wait(timeout=6) == 0)
    finally:
        app.kill()


def arrow(app):
    """Where the filter box's history arrow is, 1-based for Pty.click."""
    for row, line in enumerate(app.render().split("\n")):
        col = line.find("\u2590\u2193\u258c")
        if col >= 0:
            return (col + 2, row + 1)
    return None


def dropdown(app, at):
    """The rows of the open history drop-down, given where its arrow is.

    It opens one row above the field and one column left of it, so its top
    frame is the row above the arrow -- and it is the innermost box there,
    hence the rindex.
    """
    screen = app.render().split("\n")
    top = at[1] - 2
    left = screen[top].rindex("\u2554")
    right = screen[top].index("\u2557", left)
    # To the bottom frame and not a fixed six rows. Six was right only while
    # the binding copied Borland's `field.b.y + 7`, which is the same window
    # whatever the list holds; it is sized from the list now, so a short list
    # makes a short window and counting six reads past the end of it.
    end = next((r for r in range(top + 1, len(screen))
                if "\u255a" in screen[r][left:right + 1]), top + 1)
    return [row for row in
            (screen[r][left + 1:right].strip() for r in range(top + 1, end))
            if row]


def main():
    check = Checks()
    env = dict(os.environ, TERM="xterm-256color")
    app = Pty(node_argv(RUNTIME, "main.js"), env, cwd=EXAMPLE)

    # 1. The first screen is a render of the Gren model.
    app.pump(2.0)
    first = app.render()
    check("windows came from view : Model -> Ui", "Entries (3)" in first)
    check("list contents came from the model",
          all(x in first for x in ("Turbo Vision", "Borland", "Gren")))
    check("menu bar and status line came from Gren",
          "Entries" in first and "Alt-A Add" in first)

    # 2. Time.every is an ordinary subscription, and it drives the screen.
    before = latest_int(app.render(), TICKS)
    app.pump(3.2)
    after = latest_int(app.render(), TICKS)
    check("a Gren subscription repaints the TUI",
          before is not None and after is not None and after > before,
          f"ticks {before} -> {after}")

    # 3. Opening a dialog is a Cmd; its result comes back as a Msg.
    app.send(b"\x1ba", settle=1.2)
    check("dialog opened by a Cmd", "Add an entry" in app.render())

    during_before = latest_int(app.render(), TICKS)
    app.pump(3.2)
    during_after = latest_int(app.render(), TICKS)
    check("Gren keeps running behind a modal dialog", during_after > during_before,
          f"ticks stuck at {during_before}")

    app.send(b"Elm", settle=0.4)
    app.send(b"\r", settle=1.2)          # OK is the default button
    added = app.render()
    check("dialog result reached update", "Entries (4)" in added,
          "the model did not grow")
    check("the new entry was rendered", "Elm" in added, "list was not patched")

    # A dialog hands the caret back to whatever had it before, which is not
    # necessarily the list the entry just went into. Tui.focus names a view
    # here rather than a window, and TView::focus walks up its owner chain --
    # so the window it is in becomes the active one.
    check("the caret went to the list the entry went into",
          active(added, "Entries (4)"),
          "the dialog gave focus back to whatever had it before")

    # 4. An event from a view becomes a Msg, and the answer is patched back in.
    # Home, then Down, is the second entry wherever the click happened to land.
    # Space selects; Enter does nothing.
    app.click(6, 5)
    app.send(b"\x1b[H", settle=0.3)
    app.send(b"\x1b[B", settle=0.3)
    app.send(b" ", settle=1.0)
    check("selection round-tripped through the model",
          "Selected: Borland" in app.render(), app.render()[12 * 81:14 * 81])

    # 5. The user closes a window from its frame. Without the onClose event the
    #    model would still believe it is open and the next render would put it
    #    straight back.
    app.click(*CLOSE_BOX)
    app.pump(2.0)                        # let a tick force another render
    check("closing a window told the model", "Entries (" not in app.render(),
          "the window came back, so WindowClosed never arrived")

    # 6. And the model can put it back -- with the caret, which is the half a
    #    render cannot express. This is also the deferred path: the focus
    #    message names a window the same update creates, and an update's Cmd
    #    and its render are one Cmd.batch, so the message can leave before the
    #    window it names exists.
    app.send(b"\x1bl", settle=1.2)
    reopened = app.render()
    check("the model can reopen it", "Entries (4)" in reopened)
    check("and focus a window the same update created",
          active(reopened, "Entries (4)"),
          "the focus arrived before the render that built the window")

    # 7. The gap this closed: Alt-L on a window that was already open did
    #    nothing at all. The flag was already True, the render found no
    #    difference, and the window stayed where it was. Take the focus away
    #    with a click and ask for it back.
    #
    #    Answered by `Tui.bringToFront` since the API audit, where it used to
    #    be `Tui.focus`. Both pass these two checks, because a Turbo Vision
    #    window carries `ofTopSelect` and focusing one raises it -- but the
    #    command means "show me that window", and saying so is better than
    #    relying on a flag on a class to make the other sentence come true.
    app.click(50, 3, settle=0.8)
    check("clicking the clock window activated it", active(app.render(), "Gren"))
    app.send(b"\x1bl", settle=1.2)
    raised = app.render()
    check("Alt-L raises a window that is already open",
          active(raised, "Entries (4)"), "the list did not come forward")
    check("and the window it came forward over went quiet",
          active(raised, "Gren") is False)

    # 8. A control in an ordinary window, which is the thing this API could
    #    not see before protocol 8: Turbo Vision reports neither a keystroke
    #    nor a cluster, so a program read a field when a *dialog* was answered
    #    and at no other moment. The filter box is a `Changed` event, a field
    #    on the model, and a `view` that reads it.
    #
    #    Both characters go in one write on purpose. They are read in one pass
    #    of the pump, and the race that hides behind them is the whole reason
    #    the C++ collapses a burst into one notification and the runtime
    #    records what the view reported before the model is asked. With
    #    neither, the render for the first keystroke lands after the second has
    #    been typed, writes the stale value back, and -- because a value the
    #    model sets used to arrive through selectAll -- leaves the field
    #    selected so that the next key replaces all of it.
    app.send(b"or", settle=1.2)
    filtered = app.render()
    check("typing in an ordinary window reached the model",
          "or" in filtered.split("\n")[3], filtered.split("\n")[3])
    check("and the model filtered the list with it",
          "Entries (1)" in filtered and "Borland" in filtered
          and "Turbo Vision" not in filtered,
          filtered)

    # One backspace deletes one character. It is the assertion this whole
    # mechanism exists to make true.
    app.send(b"\x7f", settle=1.2)
    check("a backspace deletes one character, not the field",
          "Entries (2)" in app.render(),
          app.render().split("\n")[3])

    app.send(b"\x7f", settle=1.2)
    check("and emptying the box brings the whole list back",
          "Entries (4)" in app.render(), app.render())

    # 8b. The history drop-down on that same filter box.
    #
    #     Turbo Vision keeps this list in one buffer shared by the whole
    #     program and adds to it behind the program's back, on focus loss.
    #     Here it is a field on the model that only `update` writes to, and
    #     what `update` writes is "a filter you actually chose something out
    #     of" -- a rule no history block could express.
    #
    #     Two things are being driven here that the Change Dir dialog cannot
    #     drive. Appending to the list is a *patch*: the window keeps its
    #     caret, its highlight and its selection caption across it, which a
    #     rebuild would take. And the clock keeps ticking while the drop-down
    #     is open, which is the whole reason it is not a nested event loop --
    #     `THistory::handleEvent` calls `owner->execView()`, and doing that
    #     here would stop Node's loop dead for as long as the list was up.
    # Before the first filter is remembered there is nothing behind the arrow,
    # so the arrow is not drawn -- `Visible`, which is sfVisible and not the
    # same thing as leaving the view out of the render. Leaving it out would be
    # a structural change, and the window would be torn down and rebuilt the
    # moment a filter was remembered, taking the caret with it.
    check("a history arrow with nothing behind it is not drawn",
          arrow(app) is None, app.render())

    app.send(b"e", settle=1.2)
    app.send(b"\t", settle=0.6)
    app.send(b" ", settle=1.0)
    check("choosing from a filtered list is what remembers the filter",
          "Selected: Gren" in app.render(), app.render())
    check("and that is what puts the arrow there", arrow(app) is not None,
          app.render())

    app.send(b"\x1b[Z", settle=0.6)
    app.send(b"\x7f", settle=0.8)
    app.send(b"n", settle=1.0)
    app.send(b"\t", settle=0.6)
    app.send(b" ", settle=1.0)
    app.send(b"\x1b[Z", settle=0.6)
    check("a second filter, and a second thing chosen out of it",
          "Entries (3)" in app.render() and "Selected: Turbo Vision" in app.render(),
          app.render())

    at = arrow(app)
    check("the filter box still has its history arrow", at is not None,
          app.render())
    app.click(at[0], at[1], settle=1.2)
    check("it drops down the filters that found something, newest first",
          dropdown(app, at) == ["n", "e"], str(dropdown(app, at)))

    # The claim the whole design of this widget rests on.
    ticks_before = latest_int(app.render(), TICKS)
    app.pump(3.2)
    ticks_after = latest_int(app.render(), TICKS)
    check("Gren keeps running behind the drop-down too",
          ticks_after > ticks_before, f"ticks stuck at {ticks_before}")

    # And choosing one is a Changed event on the *field*: the drop-down has no
    # event of its own, because what happened is that the field's value moved.
    app.send(b"\x1b[B", settle=0.5)
    app.send(b"\r", settle=1.2)
    picked = app.render()
    check("choosing an entry refilters the list through the model",
          "Entries (2)" in picked and "Gren" in picked and "Elm" in picked
          and "Borland" not in picked, picked)
    check("and the window kept the selection it had all along",
          "Selected: Turbo Vision" in picked, picked)

    # One backspace empties the whole field, where one backspace above deleted
    # a single character. That is not an inconsistency: an entry chosen out of
    # the history arrives *selected*, exactly as Borland leaves it, because the
    # next thing typed is meant to replace it. A value the model set never is,
    # for the opposite reason.
    app.send(b"\x7f", settle=1.2)
    check("a history pick arrives selected, so one backspace clears it",
          "Entries (4)" in app.render(), app.render())

    # 9. The other half of the same mechanism, and the half the model is not
    #    involved in at all. Clicking the frame's zoom box is Turbo Vision's
    #    own command: it never reaches the model, so every rectangle the model
    #    goes on sending is the one it was already sending and the differ has
    #    nothing to do. What moves the views inside is TGroup::changeBounds
    #    resolving the growMode each of them was given.
    box = zoom_box(app.render(), "Entries (")
    check("the active window's frame has a zoom box", box is not None, raised)
    app.click(box[0] + 2, box[1] + 1, settle=1.2)
    zoomed = app.render()
    check("the zoom box filled the desktop with it", bottom_of_list(zoomed) == 23,
          f"bottom frame at row {bottom_of_list(zoomed)}")
    check("the list box stretched with the window",
          row_of(zoomed, "Selected:") == 20,
          f"the caption is on row {row_of(zoomed, 'Selected:')}")
    check("and the button rode the bottom edge down",
          bottom_of_list(zoomed) - row_of(zoomed, "Add...") == 2,
          f"button on {row_of(zoomed, 'Add...')}, frame on {bottom_of_list(zoomed)}")

    # The clock guarantees a render a second, and none of them knows the window
    # was zoomed. If the differ compared rectangles against the screen rather
    # than against the last spec it applied, this is where it would snap back.
    app.pump(2.0)
    check("and the renders that keep arriving do not undo it",
          bottom_of_list(app.render()) == 23,
          f"bottom frame back at row {bottom_of_list(app.render())}")

    # 10. A message box, which is a dialog the *package* builds rather than the
    #     binding. Turbo Vision's own messageBox() is a library function
    #     because it calls execView, the nested loop this pump exists instead
    #     of; here it is a DialogSpec, so nothing new reaches the protocol and
    #     the answer comes back as an ordinary DialogClosed.
    clear_menu(app)
    asking = app.render()
    check("Clear asks first", "Throw away all" in asking, asking)
    edges = box_edges(asking, "Clear")
    check("and the box centres itself on the desktop",
          edges is not None and abs(edges[0] - (79 - edges[1])) <= 1,
          f"frame at {edges} of 80 columns")
    check("with the two buttons it was given",
          "Yes" in asking and "No" in asking, asking)

    # "yes" and "no" are built-in command names, so the buttons close the box
    # by themselves and the model is told which one did it.
    app.send(b"\x1bn", settle=1.0)
    check("No leaves everything alone",
          "Throw away all" not in app.render() and "Entries (4)" in app.render(),
          app.render())

    clear_menu(app)
    app.send(b"\x1by", settle=1.0)
    check("Yes empties the list", "Entries (0)" in app.render(), app.render())

    # The filter box is wrapped in `Enabled` on there being something to
    # filter, so an empty list is also the check on a view with no command
    # being made unavailable -- which `setEnabled` cannot do, because what it
    # takes hold of is the command.
    #
    # Asserted by what it does rather than by its colour. A disabled view draws
    # in the palette's grey, and reading that off the screen is a check about
    # the palette; Turbo Vision handing it no keystroke at all is the part the
    # model asked for, and it is the half a screenshot cannot show.
    app.send(b"zz", settle=0.7)
    check("and the filter box takes no keystrokes with nothing to filter",
          "zz" not in app.render(), app.render().split("\n")[2])

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("exit code 0", code == 0, f"exit={code}")

    resizes(check)

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
