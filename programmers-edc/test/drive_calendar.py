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


def go_to(app, year, month):
    """Navigate to a month, counting from wherever today put us.

    Nothing here may assume what month it is, so the driver reads the heading
    and works it out -- which also exercises the two keys that move by a year.
    """
    at = heading(app)
    assert at is not None, "the calendar never said which month it was showing"
    want = year * 12 + (month - 1)
    have = at[0] * 12 + (at[1] - 1)
    while have - want >= 12:
        app.send(b"\x1b[5~", settle=0.2)      # PgUp: a year back
        have -= 12
    while want - have >= 12:
        app.send(b"\x1b[6~", settle=0.2)      # PgDn: a year on
        have += 12
    while have > want:
        app.send(b"\x1b[A", settle=0.2)
        have -= 1
    while have < want:
        app.send(b"\x1b[B", settle=0.2)
        have += 1
    app.pump(0.4)
    return heading(app)


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
