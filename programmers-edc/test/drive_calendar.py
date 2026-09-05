#!/usr/bin/env python3
"""predc's calendar: which day a date falls on, and which week it is in.

The month grid is `gren-tvision`'s calendar example, which is tvdemo's
`calendar.cpp` in Gren, so what is worth testing here is the column the port
does not have: the week number, and the setting that decides it.

**A week number means nothing without saying where a week starts**, so the two
are one setting rather than two that could be set to disagree. ISO 8601 starts
weeks on Monday and gives week 1 to the one holding 4 January; the US
convention starts on Sunday and gives week 1 to the one holding 1 January.
Choosing between them moves the columns as well as the numbers, and both halves
are checked below.

**The year boundary is the whole difficulty.** For eleven months the two rules
agree to within a day's shuffling, and then 1 January 2021 is ISO week 53 *of
2020* while 31 December 2019 is ISO week 1 *of 2020*. Those two dates are here
because they are the ones a wrong implementation gets wrong while looking
right all year.

`today` is whenever this runs, so nothing here may assume a month: `go_to`
reads the heading and counts its own way there.
"""

import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def rows(app):
    """The calendar canvas, framing stripped."""
    out = []
    for line in app.render().split("\n"):
        if line.count("║") >= 2:
            inner = line.split("║")[1]
            if inner.strip():
                out.append(inner.rstrip())
    return out


def heading(app):
    """The month on screen, as (year, month), or None before the clock answers."""
    for line in rows(app):
        m = re.match(r"\s*([A-Z][a-z]+) (\d{4})\s*$", line)
        if m and m.group(1) in MONTHS:
            return int(m.group(2)), MONTHS.index(m.group(1)) + 1
    return None


def weeks(app):
    """The week number against each row of dates."""
    found = []
    for line in rows(app):
        m = re.match(r"\s*(\d{1,2})\s\s(.*\d.*)$", line)
        if m:
            found.append(int(m.group(1)))
    return found


def columns(app):
    for line in rows(app):
        if "Wk" in line:
            return line.split()[1:]
    return []


def go_to(app, year, month, name=None):
    """Name a month outright, through the Go to dialog.

    Not by stepping: there is no previous-year key any more, and counting
    twenty presses of Up while reading the heading is exactly the interaction
    that got it taken out. The dialog is also what a driver wants -- one
    question, one answer, and no dependence on what month it is today.
    """
    app.send(b"g", settle=1.0)
    app.send(b"\x1b[3~" * 12, settle=0.3)              # Del clears the field
    app.send((name or str(month)).encode(), settle=0.3)
    app.send(b"\t", settle=0.3)
    app.send(b"\x1b[3~" * 6, settle=0.3)
    app.send(str(year).encode(), settle=0.3)
    app.send(b"\r", settle=1.2)
    return heading(app)


def footer(app):
    """The standing line of keys under the grid, or whatever went wrong."""
    lines = rows(app)
    return lines[-1].strip() if lines else ""


def menu(app, name):
    bar = app.render().split("\n")[0]
    app.click(bar.index(name) + 1, 1, settle=0.7)


def entry(app, text, settle=0.8):
    for row, line in enumerate(app.render().split("\n")):
        if text in line and "│" in line:
            app.click(line.index(text) + 1, row + 1, settle=settle)
            return True
    return False


def start(home, cols=80, rows_=25):
    env = dict(os.environ, TERM="xterm-256color", HOME=home)
    env.pop("XDG_CONFIG_HOME", None)
    app = Pty(node_argv(LAUNCHER), env, cwd=tempfile.mkdtemp(), size=(cols, rows_))
    app.pump(2.0)
    return app


def main():
    check = Checks()
    home = tempfile.mkdtemp(prefix="predc-home-")
    app = start(home)

    # 1. It opens on today, which is the one month it cannot be handed.
    app.send(b"\x1bk", settle=1.5)
    check("Alt-K opens the calendar", "Calendar" in app.render(), app.render())
    opened = heading(app)
    check("and it opens on a month, so the clock answered",
          opened is not None and 2000 < opened[0] < 2200, str(opened))
    check("with a week column and seven days",
          columns(app) == ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"], str(columns(app)))
    # The keys are on the screen, not only on a menu. Somebody who opens a
    # calendar and sees one month has no way to guess that Up and Down move it.
    check("and a standing line saying which keys move it",
          footer(app) == "Up/Down month   g go to   t today", repr(footer(app)))
    check("which fits the canvas it is drawn on", len(footer(app)) <= 34,
          f"{len(footer(app))}: {footer(app)!r}")

    # 2. ISO, at the boundary that is the whole reason the rule is subtle.
    #    1 January 2021 is week 53 -- of 2020 -- and a January that says 1 is
    #    an implementation that has never been near a year boundary.
    check("January 2021 is reachable", go_to(app, 2021, 1) == (2021, 1), str(heading(app)))
    check("and its first week is 53, which belongs to 2020",
          weeks(app)[0] == 53, str(weeks(app)))
    check("and the second is week 1", weeks(app)[1] == 1, str(weeks(app)))

    #    The other end of the same boundary: 31 December 2019 is week 1 of 2020.
    go_to(app, 2019, 12)
    check("December 2019 ends in week 1, which belongs to 2020",
          weeks(app)[-1] == 1, str(weeks(app)))

    #    And an ordinary month, where nothing is at stake.
    go_to(app, 2026, 9)
    check("September 2026 runs from week 36", weeks(app)[0] == 36, str(weeks(app)))
    check("to week 40", weeks(app)[-1] == 40, str(weeks(app)))
    check("and its 1st is a Tuesday, which is where the row starts",
          rows(app)[2].split()[1] == "1" and columns(app)[1] == "Tu",
          rows(app)[2])

    # 3. The other rule moves the columns as well as the numbers, which is the
    #    point of it being one setting: a Monday-first grid numbered from a
    #    Sunday-first rule would be wrong in a way nobody could see.
    menu(app, "Options")
    entry(app, "Week numbers")
    check("the menu ticks the rule in use",
          any("√" in line and "ISO" in line for line in app.render().split("\n")),
          [line for line in app.render().split("\n") if "ISO" in line])
    check("US is reachable", entry(app, "US (Sun"))
    check("and the week now starts on Sunday",
          columns(app) == ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"], str(columns(app)))
    check("with September 2026 still starting in week 36, by the other count",
          weeks(app)[0] == 36, str(weeks(app)))

    #    Where the two rules actually disagree: under the US rule January is
    #    never week 53, because 1 January is always week 1.
    go_to(app, 2021, 1)
    check("and under it January 2021 starts at week 1, not 53",
          weeks(app)[0] == 1, str(weeks(app)))

    # 4b. Naming a month, which is the only way out of this one other than
    #     walking to the next. There is no previous-year key on purpose:
    #     stepping a year at a time is nine presses of one key and eleven of
    #     another, counted by reading the heading each time, which is a poor
    #     answer to "show me March 2019".
    check("PgUp does nothing, because a year key is not a way to choose a year",
          (app.send(b"\x1b[5~", settle=0.5), heading(app))[1] == (2021, 1),
          str(heading(app)))

    app.send(b"g", settle=1.0)
    opened_with = app.render()
    check("g opens the dialog", "Go to month" in opened_with, opened_with)
    check("prefilled with the month on screen, so one field is often the edit",
          "January" in opened_with and "2021" in opened_with, opened_with)
    app.send(b"\x1b", settle=0.9)
    check("and Escape leaves the calendar where it was",
          heading(app) == (2021, 1), str(heading(app)))

    check("a month by name is a month", go_to(app, 2019, None, name="march") == (2019, 3),
          str(heading(app)))
    check("and 1 March 2019 is week 9", weeks(app)[0] == 9, str(weeks(app)))
    check("a three-letter prefix is enough, since no two months share one",
          go_to(app, 2019, None, name="sep") == (2019, 9), str(heading(app)))
    check("and so is a number", go_to(app, 2019, 11) == (2019, 11), str(heading(app)))

    #     And what it refuses, separately, because "not a month" and "not a
    #     year" are different mistakes and one message for both would make a
    #     reader check the field that was fine.
    go_to(app, 2019, None, name="smarch")
    check("a month it cannot read is refused by name",
          "Not a month: smarch" in footer(app), footer(app))
    check("and the calendar has not moved", heading(app) == (2019, 11), str(heading(app)))
    go_to(app, 0, 3)
    check("and a year outside what the arithmetic was checked for is refused",
          "Not a year" in footer(app), footer(app))

    # 4. It is a setting, so it is written down and comes back.
    app.send(b"\x1bx", settle=1.0)
    check("Alt-X exits", app.wait(timeout=6) == 0, "")
    written = open(os.path.join(home, ".config", "predc", "config.toml")).read()
    check("the choice is in the config file", 'weeks = "us"' in written, written)
    # A substring that cannot span the comment's own wrapping, which the last
    # one did -- the sentence is right and the check was reading across a
    # newline and a `# `.
    check("with a sentence saying what it is for",
          "week starts on" in written and "Absent is iso" in written, written)

    app = start(home)
    app.send(b"\x1bk", settle=1.5)
    check("and predc opens that way next time",
          columns(app) == ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"], str(columns(app)))

    #    And choosing the default back takes the key out again rather than
    #    writing `iso`, which is `timezones`'s rule and the reason predc can
    #    promise a hand-written file that it changes only what it was asked to.
    menu(app, "Options")
    entry(app, "Week numbers")
    entry(app, "ISO 8601")
    app.send(b"\x1bx", settle=1.0)
    app.wait(timeout=6)
    back = open(os.path.join(home, ".config", "predc", "config.toml")).read()
    check("choosing ISO back removes the key rather than writing it",
          "weeks" not in back, back)

    # 5. Back on ISO, and `t` comes home. A fresh run, because the section
    #    above closed predc to read what it had written.
    app = start(home)
    app.send(b"\x1bk", settle=1.5)
    check("and the calendar is back on ISO columns",
          columns(app) == ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"], str(columns(app)))
    go_to(app, 2019, 12)
    app.send(b"t", settle=0.8)
    check("t comes back to today", heading(app) == opened, str(heading(app)))

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("and Alt-X exits again", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
