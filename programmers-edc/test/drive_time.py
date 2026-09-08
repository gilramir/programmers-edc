#!/usr/bin/env python3
"""predc's time converter: one instant, several wall clocks, all editable.

Four things are being tested and only the first is arithmetic.

**The conversions are the IANA database's and not ours.** Gren does no calendar
work at all here -- `bin/timezones.js` does it behind a port pair, because a
time zone is not an offset and the only thing on the machine that knows the
difference is the tz database compiled into node's `Intl`. So the checks below
are about zones with rules that a fixed offset gets wrong: Kathmandu is +05:45
and was +05:30 in 1970, Chicago is two different offsets in the same year, and
the second Sunday in March has no 02:30 in it.

**A row that does not exist is said out loud.** 02:30 on a spring-forward
morning, and the 31st of April, are the same mistake wearing two hats -- a wall
clock that names no instant -- and both come back naming what they became. A
converter that quietly showed you an hour you did not ask for would be the hex
viewer's sniffing problem in another costume.

**The field being typed in is never written back to.** The digits stay where
they were put while every other row moves, which is what a caret needs to
survive a recomputation on every keystroke.

**The picker's two levels and its filter are one mechanism.** An area is a
saved search: choosing `Asia` types `Asia/` into Find, and typing narrows
further. There is no precedence rule to get wrong because there is only one
piece of state.

`TZ` is set for the whole run, which is what makes "the machine's own zone"
a testable claim rather than a fact about the machine the suite happens to be
on. node honours it, `Intl.DateTimeFormat().resolvedOptions().timeZone` reports
it, and `Time.getZoneName` is what predc reads.

**Three lists side by side means three wheels.** A wheel turn is not a
positional event in Turbo Vision, so the picker's rightmost scroll bar used to
answer for the whole window and the list under the pointer never moved. The
checks below turn the wheel over two of the three panes and read which one
went.

This suite also pins a bug it found in the binding: `TInputLine`'s constructor
takes a *limit* and stores `maxLen = limit - 1`, so a field declared four
characters wide held three and a four-digit year came out as `202`. Every check
below that reads a year would fail without the fix in `views.cc`.

Splitting the picker out left this file the converter itself: the conversions
that are the whole point, and the live clock, which is the same window in the
mode that throws the pinned instant away. The picker is `drive_time_picker.py`
and `drive_time_moves.py`; see `time_common.py` for why there are three.
"""

import sys

from time_common import (
    Checks, WHEN, add_zone, click_button, clock, field_at, launch, message,
    open_picker, posix, posix_at, posix_value, retype, row,
)


def window_edge(app):
    """The column the converter's frame starts in, and the row its title is on.

    The title sits in the top line of the frame, so the corner to its left is
    the window's left edge -- which is the only part of a window's position a
    driver can see, and all this needs to see. Not `lstrip()`: what is to the
    left of a window is the desktop's hatching and not spaces.
    """
    for r, line in enumerate(app.render().split("\n")):
        if "Time converter" not in line:
            continue
        for corner in ("\u2554", "\u250c"):   # double frame when focused, single when not
            if corner in line:
                return line.index(corner), r + 1
    return None, None


def main():
    check = Checks()
    app, home = launch()


    screen = app.render()
    check("predc time opened the converter", "Time converter" in screen, screen)

    # With no config file, the list is the machine's own zone and nothing else
    # -- and that comes from `Time.getZoneName`, not from a port. `Time.here`
    # could not answer it: its own doc comment says it hands back `Etc/GMT-5`
    # and never `America/Chicago`.
    check("it starts in the machine's own zone",
          row(app, "America/Chicago") is not None, screen)
    check("UTC is there whether or not anybody asked",
          row(app, "UTC") is not None, screen)

    # "Defaults to now" cannot be checked against a constant, so it is checked
    # against the shape of the answer and the fact that it is not zero.
    opened = clock(app, "UTC")
    check("and at a plausible now", opened is not None and int(opened[0]) >= 2026,
          str(opened))
    check("with a POSIX to match", posix(app) is not None and posix(app) > 1_700_000_000,
          str(posix(app)))

    # Leaning on a digit key used to close predc: an instant past what a
    # `Date` can hold made every `Intl` call throw, and a throw inside a port
    # subscription kills the process with the terminal still in its alternate
    # screen. It is a sentence now.
    retype(app, posix_at(app), "9" * 20, settle=1.4)
    check("a number too big for a calendar is a sentence, not a crash",
          "further from 1970" in message(app), message(app))
    check("and predc is still running", "Time converter" in app.render(), app.render())

    # A POSIX timestamp typed in moves every row. This is the direction people
    # actually use: a number out of a log file, read as a time somewhere.
    retype(app, posix_at(app), str(WHEN), settle=1.4)
    check("a POSIX typed in reaches UTC",
          clock(app, "UTC") == ("2026", "09", "01", "19", "32"), str(clock(app, "UTC")))
    check("and Chicago, at its summer offset",
          clock(app, "America/Chicago") == ("2026", "09", "01", "14", "32"),
          str(row(app, "America/Chicago")))
    check("which is named as well as numbered",
          "CDT" in (row(app, "America/Chicago")[5]),
          row(app, "America/Chicago")[5])

    # Typing into a zone's own fields moves the instant and every other row.
    retype(app, field_at(app, "America/Chicago", 3), "09", settle=1.4)
    check("an hour typed into Chicago moves Chicago",
          clock(app, "America/Chicago") == ("2026", "09", "01", "09", "32"),
          str(clock(app, "America/Chicago")))
    check("and drags UTC with it",
          clock(app, "UTC") == ("2026", "09", "01", "14", "32"), str(clock(app, "UTC")))
    check("and the POSIX with that", posix(app) == WHEN - 5 * 3600, str(posix(app)))

    # Out of range is a sentence, not a silent clamp and not an instant.
    before = clock(app, "UTC")
    retype(app, field_at(app, "America/Chicago", 3), "99", settle=1.0)
    check("an impossible hour says so", "is 0 to 23" in message(app), message(app))
    check("and moves nothing", clock(app, "UTC") == before, str(clock(app, "UTC")))

    # The spring-forward gap. 02:30 does not happen in Chicago on 2026-03-08,
    # and the honest answer names what it became rather than showing an hour
    # nobody asked for.
    retype(app, posix_at(app), str(WHEN), settle=1.2)
    retype(app, field_at(app, "America/Chicago", 0), "2026", settle=1.0)
    retype(app, field_at(app, "America/Chicago", 1), "03", settle=1.0)
    retype(app, field_at(app, "America/Chicago", 2), "08", settle=1.0)
    retype(app, field_at(app, "America/Chicago", 4), "30", settle=1.0)
    retype(app, field_at(app, "America/Chicago", 3), "02", settle=1.4)
    check("a time daylight saving skipped is reported",
          "does not exist" in message(app), message(app))
    check("and it pushes forward, not back",
          "03:30" in message(app), message(app))

    # The same machinery catches a date that is not a date, which is the point
    # of leaving the day range at 1-31: the one place that knows how long April
    # is should be the one place that is asked.
    retype(app, field_at(app, "America/Chicago", 1), "04", settle=1.0)
    retype(app, field_at(app, "America/Chicago", 2), "31", settle=1.4)
    check("and so is the 31st of April", "does not exist" in message(app), message(app))


    # ---- the caret survives a window the model rebuilds ----
    #
    # Adding a zone gives the converter another row, and a row added is
    # structural -- nothing can insert a view into a window but a rebuild. The
    # rebuild used to put the caret back in the first field, so a user who was
    # part-way through typing a date came back to the wrong one. Chicago's row
    # rather than UTC's because a zone is appended above UTC and that row
    # really does move.
    at = field_at(app, "America/Chicago", 2)      # the day field
    app.click(at[0], at[1], settle=0.6)
    before = app.cursor()
    check("the caret is in the field that was clicked",
          before[1] == at[1] - 1, str((before, at)))

    open_picker(app)
    add_zone(app, "Asia/Seoul")
    click_button(app, "Done")
    check("adding a zone gave the converter another row",
          row(app, "Asia/Seoul") is not None, app.render())
    # The *field*, not the column inside it: a rebuilt input line is a new one
    # and its caret starts at the end of its value, which for a two-digit day
    # is two columns along from where the click left it.
    # `field_at` is 1-based and `cursor` is 0-based, so the day's two digits are
    # at[0]-1 and at[0], and at[0]+1 is the column the caret sits in past the
    # last one.
    caret = app.cursor()
    check("and the caret is still in the field it was in",
          caret[1] == before[1] and at[0] - 1 <= caret[0] <= at[0] + 1,
          str((before, caret, at)))

    # ---- the live clock ----
    #
    # Last, because it throws away the instant everything above was pinned to:
    # a clock is the machine's own time and nothing else.
    #
    # What is checked here is that the mode is live, that it is read-only and
    # that it stops. What is *not* checked is the minute turning over, and the
    # reason is arithmetic rather than principle: the tick fires on the second
    # and recomputes on the minute, so a driver that waited for one would wait
    # up to sixty seconds and this suite is already the slowest of the
    # twenty-nine. It was verified by hand instead, and the evidence is in
    # FINDINGS.md -- the recomputation landed on POSIX 1788351000, which is a
    # multiple of sixty, so the tick is not merely firing, it is firing on the
    # boundary.
    #
    # The POSIX line is what makes the cheap half checkable at all. It counts
    # seconds where the clocks count minutes, so three seconds of waiting is
    # enough to prove the subscription is alive.
    app.send(b"\x1bl", settle=2.0)
    check("Alt-L turns the converter into a clock",
          "Time converter -- live" in app.render(), app.render())
    started = posix_value(app)
    app.pump(3.0)
    check("whose POSIX line counts seconds on its own",
          posix_value(app) - started >= 2,
          str((started, posix_value(app))))

    year = row(app, "UTC")[0]
    where = field_at(app, "UTC", 0)
    app.click(where[0], where[1], settle=0.5)
    app.send(b"1999", settle=0.8)
    check("and whose fields are read-only, being static text and not fields",
          row(app, "UTC")[0] == year, str(row(app, "UTC")))

    # ---- and the window stays where the user dragged it ----
    #
    # Recorded rather than imagined: a session where the converter was dragged
    # a few columns right and the clock then switched off, whose only visible
    # effect should have been a button's caption changing. The window jumped
    # back to where it had opened. `~L~ive clock` becoming `~S~top clock` is a
    # structural change -- a button's caption has no call that changes it in
    # place -- so the differ rebuilds the window, and it was rebuilding it at
    # the rectangle in the model's description. The model never hears about a
    # drag it does not store, and this one does not store it.
    left, title_row = window_edge(app)
    app.drag([(left + 20, title_row), (left + 23, title_row), (left + 26, title_row)])
    dragged, _ = window_edge(app)
    check("the converter can be dragged by its title bar", dragged > left,
          str((left, dragged)))

    app.send(b"\x1bs", settle=2.0)
    check("and stopping the clock leaves it where it was dragged to",
          window_edge(app)[0] == dragged, str((dragged, window_edge(app)[0])))

    check("Alt-S gives the converter back",
          "Time converter -- live" not in app.render() and "Time converter" in app.render(),
          app.render())
    stopped = posix_value(app)
    app.pump(3.0)
    check("and the clock stops with it", posix_value(app) == stopped,
          str((stopped, posix_value(app))))

    retype(app, field_at(app, "UTC", 0), "1999", settle=1.2)
    check("and the fields take typing again", row(app, "UTC")[0] == "1999",
          str(row(app, "UTC")))

    app.send(b"\x1bx", settle=1.0)
    check("Alt-X exits", app.wait(timeout=6) == 0, "")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
