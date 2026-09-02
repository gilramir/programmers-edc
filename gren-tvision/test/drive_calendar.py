#!/usr/bin/env python3
"""examples/calendar -- tvdemo's calendar, in Gren.

The month is a canvas, and today is the one thing on it painted in a colour of
its own. That colour is the whole point of the port, so most of this asserts on
it: `display().fg_at()` reads the foreground the terminal actually received,
which is the only place a `Tui.ink` span leaves a trace.

The other thing worth testing is that the calendar is testable at all. The C++
`TCalendarView` calls localtime() in its constructor and therefore *is* today,
with no way to ask it for another month. Here today is a field, so walking away
from it and back is an ordinary model change -- and the test can check that
today stops being highlighted when you leave the month.
"""

import datetime
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLE = os.path.join(ROOT, "examples", "calendar")
RUNTIME = os.path.join(ROOT, "..", "gren-tvision-runtime", "bin", "gren-tui.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

# The window sits at desktop (1, 1) and the canvas one cell inside its frame,
# so canvas (0, 0) is here. Screen row 0 is the menu bar.
ORIGIN = (2, 3)


def heading(screen):
    """The month and year the canvas is showing, as (name, year)."""
    m = re.search(r"([A-Z][a-z]+)\s+(\d{4})\s+▲", screen)
    return (m.group(1), int(m.group(2))) if m else (None, None)


def highlighted(display):
    """Every cell on the canvas painted in something other than the body
    colour, as (col, row) pairs -- which is how "today" shows up and nothing
    else does."""
    body = display.fg_at(ORIGIN[0], ORIGIN[1] + 1)   # the "Su Mo Tu ..." row
    return [
        (x, y)
        for y in range(2, 8)
        for x in range(0, 20)
        if display.fg_at(ORIGIN[0] + x, ORIGIN[1] + y) != body
    ]


def main():
    check = Checks()
    today = datetime.date.today()
    env = dict(os.environ, TERM="xterm-256color")
    app = Pty(node_argv(RUNTIME, "main.js"), env, cwd=EXAMPLE)

    app.pump(2.5)
    first = app.render()
    check("calendar window drawn", "Calendar" in first, first)

    # Time.here and Time.now are tasks, so the first render happens before
    # either has answered and the window is not in the view yet. By now they
    # have, and the month is the real one.
    check("the clock arrived and the month is today's",
          heading(first) == (MONTHS[today.month - 1], today.year),
          f"{heading(first)} != {(MONTHS[today.month - 1], today.year)}")

    # Today is a span with a foreground of its own. Nothing else on the canvas
    # names a colour, so the highlighted cells are exactly today's cell -- two
    # digits and the space the span carries with them.
    marked = highlighted(app.display())
    check("today is painted in a colour of its own", len(marked) > 0,
          "no cell differed from the body colour")
    row = app.render().split("\n")[ORIGIN[1] + marked[0][1]] if marked else ""
    at = marked[0][0] if marked else -1
    check("and it is today",
          row[ORIGIN[0] + at:ORIGIN[0] + at + 3].strip().startswith(str(today.day)),
          f"marked {marked}, row {row!r}")

    # Down is next month, Up is previous -- and leaving the month takes the
    # highlight with it, because "today" is compared against what is showing
    # rather than baked into the view.
    app.send(b"\x1b[B", settle=0.8)
    nxt = app.render()
    expected = (MONTHS[today.month % 12], today.year + (1 if today.month == 12 else 0))
    check("Down moves to the next month", heading(nxt) == expected,
          f"{heading(nxt)} != {expected}")
    check("and today is no longer marked", highlighted(app.display()) == [],
          str(highlighted(app.display())))

    app.send(b"\x1b[A", settle=0.8)
    check("Up comes back", heading(app.render()) == (MONTHS[today.month - 1], today.year),
          str(heading(app.render())))
    check("and today is marked again", len(highlighted(app.display())) > 0)

    # The header's arrows, at the columns calendar.cpp puts them, and pointing
    # the way they move: up is back, down is forward, the same as the keys.
    # They were the other way round until magiblot/tvision#229 -- which this
    # port filed -- was fixed upstream, and this suite asserted the quirk.
    app.click(ORIGIN[0] + 18 + 1, ORIGIN[1] + 0 + 1, settle=0.8)
    check("clicking the down arrow moves forward", 
          heading(app.render()) == expected, str(heading(app.render())))
    app.click(ORIGIN[0] + 15 + 1, ORIGIN[1] + 0 + 1, settle=0.8)
    check("and the up arrow moves back",
          heading(app.render()) == (MONTHS[today.month - 1], today.year),
          str(heading(app.render())))

    # Twelve steps back is the same month a year earlier, which is the thing
    # the C++ view cannot be asked for at all.
    app.send(b"\x1b[A" * 12, settle=1.2)
    check("a year back is the same month, one year earlier",
          heading(app.render()) == (MONTHS[today.month - 1], today.year - 1),
          str(heading(app.render())))

    app.send(b"\x1bt", settle=0.8)
    check("Alt-T comes home to today",
          heading(app.render()) == (MONTHS[today.month - 1], today.year),
          str(heading(app.render())))

    # Closing from the frame has to reach the model, or the next render puts
    # the window straight back.
    app.click(5, 3, settle=1.0)
    check("the window closed and stayed closed", "Calendar" not in app.render().split("\n")[2],
          app.render())

    app.send(b"\x1bs", settle=1.0)
    check("Alt-S reopened it", "Calendar" in app.render().split("\n")[2])

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("exit code 0", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
