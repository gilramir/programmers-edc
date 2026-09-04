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
"""

import os
import re
import sys
import tempfile
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

# 2026-09-01T19:32:00Z. Chosen because it is inside US daylight saving, so
# Chicago is -05:00 rather than the -06:00 a fixed-offset table would carry,
# and because Kathmandu's +05:45 is a quarter hour no whole-hour arithmetic
# reaches.
WHEN = 1788291120


def row(app, zone):
    """One zone's line, as (year, month, day, hour, minute, trailing text)."""
    for line in app.render().split("\n"):
        if zone not in line:
            continue
        m = re.search(
            re.escape(zone) + r"\s+(\d{4})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*(.*?)\s*[║│]",
            line,
        )
        if m:
            return (m.group(1), m.group(2), m.group(3), m.group(4), m.group(5),
                    m.group(6).strip())
    return None


def clock(app, zone):
    """Just the five numbers, which is what most of these checks are about."""
    got = row(app, zone)
    return got[:5] if got else None


def posix(app):
    for line in app.render().split("\n"):
        m = re.search(r"POSIX\s+(-?\d+)", line)
        if m:
            return int(m.group(1))
    return None


def message(app):
    """The two lines under the POSIX box: what went wrong, or what an instant
    turned into.

    Read by position rather than by keyword, because the longest thing it says
    wraps -- "2026-03-08 02:30 does not exist in America/Chicago -- read as
    2026-03-08 03:30." is seventy-eight characters and the window is sixty --
    and a keyword search finds the complaint while missing the answer."""
    lines = app.render().split("\n")
    for i, line in enumerate(lines):
        if re.search(r"POSIX\s+-?\d+", line):
            return " ".join(
                lines[j].strip("░│║ ") for j in (i + 2, i + 3) if j < len(lines)
            ).strip()
    return ""


def field_at(app, zone, which):
    """Where a row's field is on the screen, so the driver can click into it.

    `which` is 0..4 for year, month, day, hour, minute. Found by searching the
    rendered line rather than computed from the layout: the layout is the thing
    under test."""
    for r, line in enumerate(app.render().split("\n")):
        if zone not in line:
            continue
        m = re.search(
            re.escape(zone) + r"\s+(\d{4})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})",
            line,
        )
        if m:
            return (m.start(which + 1) + 1, r + 1)
    return None


def posix_value(app):
    """The number on the POSIX line, which in clock mode is a second hand."""
    m = re.search(r"POSIX\s+(-?\d+)", app.render())
    return int(m.group(1)) if m else None


def posix_at(app):
    for r, line in enumerate(app.render().split("\n")):
        m = re.search(r"POSIX\s+(-?\d+)", line)
        if m:
            return (m.start(1) + 1, r + 1)
    return None


def retype(app, where, text, settle=1.0):
    """Click into a field, clear it, and type.

    `Delete` and not `Backspace`: a click puts the caret where it was clicked,
    and these clicks land on the first character, where there is nothing behind
    the caret to rub out. Delete eats forwards from wherever it is, so it
    empties the field whatever the click did.

    The clearing is part of what is being tested rather than a way around it --
    every one of those keystrokes recomputes the whole table, and a field that
    is briefly empty must leave the other rows alone."""
    app.click(where[0], where[1], settle=0.6)
    app.send(b"\x1b[3~" * 24, settle=0.8)
    app.send(text.encode(), settle=settle)


def type_in_find(app, text, clear=False):
    """Type into the Find box.

    Clicking well past the end of the text puts the caret at the end of it,
    which is exactly what makes an area's prefix and a typed narrowing one box
    rather than two: `Asia/` then `seo` is `Asia/seo`."""
    for r, line in enumerate(app.render().split("\n")):
        if "Find" in line:
            app.click(line.index("Find") + 30, r + 1, settle=0.6)
            if clear:
                app.send(b"\x1b[3~" * 40, settle=0.6)
                app.send(b"\x7f" * 40, settle=0.6)
            app.send(text.encode(), settle=1.4)
            return True
    return False


def space_on(app, entry):
    """Commit a list entry from the keyboard, which is how the picker is meant
    to be driven: the three buttons carry no caption hotkeys, because `~A~dd`
    would bind Alt-A and the status line already has that for the ASCII chart.
    Space on a `ListBox` sends `Selected`, which is the whole answer."""
    for r, line in enumerate(app.render().split("\n")):
        if entry in line:
            app.click(line.index(entry) + 1, r + 1, settle=0.8)
            app.send(b" ", settle=1.4)
            return True
    return False


def click_button(app, caption):
    for r, line in enumerate(app.render().split("\n")):
        if caption in line:
            app.click(line.index(caption) + 1, r + 1, settle=1.2)
            return True
    return False


def picker_heading(app):
    """The row the picker's three column headings are on, zero-based."""
    lines = app.render().split("\n")
    for r, line in enumerate(lines):
        if all(h in line for h in ("Area", "Zone", "Displaying")):
            return r, line
    return None, None


def pane(app, head):
    """One of the picker's three lists, top to bottom.

    Sliced out by column rather than searched for by name, because the whole
    question here is which of the three a zone was read from -- and a zone that
    has been chosen is in two of them at once. The headings sit at the same
    left edge as the lists under them, so the heading row is the ruler."""
    r, heading = picker_heading(app)
    edges = [heading.index(h) for h in ("Area", "Zone", "Displaying")]
    edges.append(heading.rindex("║"))
    lo = heading.index(head)
    hi = edges[edges.index(lo) + 1]
    out = []
    for line in app.render().split("\n")[r + 1:]:
        # The scroll bar lives in the column beside its list and is inside this
        # slice; its glyphs and the window's own frame come off the ends.
        cell = line[lo:hi].strip(" ░│║▲▼■▒▓")
        if not cell:
            break
        out.append(cell)
    return out


def pane_point(app, head, nth=2):
    """A point inside one of the picker's lists, `nth` rows below its
    heading, for the wheel to be turned over."""
    r, heading = picker_heading(app)
    return (heading.index(head) + 3, r + 1 + nth)


def click_in(app, head, entry, settle=1.0):
    """Click an entry in one of the picker's three lists, by column.

    Not `line.index(entry)`: a zone that has been chosen is on the screen in
    two of the three lists at once, and which one was clicked is the question
    every check below this is asking."""
    r, heading = picker_heading(app)
    for i, cell in enumerate(pane(app, head)):
        if cell == entry:
            app.click(heading.index(head) + 2, r + 2 + i, settle=settle)
            return True
    return False


def burst_wheel(app, col, row, turns):
    """Every turn in one write, which is how a real wheel arrives.

    `app.wheel` settles between turns and a hand does not: the whole point of
    the check below is a queue of events the model is several renders behind,
    and one event at a time never builds one.
    """
    os.write(app.fd, (f"\x1b[<65;{col};{row}M" * turns).encode())
    app.pump(1.5)


def find_text(app):
    """What is in the Find box, without the count that shares its line."""
    for line in app.render().split("\n"):
        if "Find" in line:
            return re.split(r"\s{2,}", line[line.index("Find") + 4:].strip())[0]
    return None


def config_path(home):
    return os.path.join(home, ".config", "predc", "config.toml")


def config_of(home):
    path = config_path(home)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return tomllib.load(f)


def main():
    check = Checks()
    home = tempfile.mkdtemp(prefix="predc-home-")
    # TZ pins "the machine's own zone", which is otherwise a fact about
    # whoever is running the suite. A temporary HOME so that no config file
    # but this driver's own is read -- predc writes its zones the moment they
    # change, and a suite that inherited a real one would be testing somebody's
    # preferences.
    env = dict(os.environ, TERM="xterm-256color", TZ="America/Chicago", HOME=home)
    env.pop("XDG_CONFIG_HOME", None)
    app = Pty(node_argv(LAUNCHER) + ["time"], env, cwd=ROOT)
    app.pump(3.0)

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

    # ---- the picker ----
    retype(app, posix_at(app), str(WHEN), settle=1.2)
    app.send(b"\x1bz", settle=1.5)
    check("Alt-Z opens the zone picker", "Time zones" in app.render(), app.render())
    check("with every zone node knows", "418" in app.render(), app.render())
    check("and no filter to start with", "Africa/Abidjan" in app.render(), app.render())

    # An area is a saved search rather than a second axis: choosing one writes
    # its prefix into Find, and there is no rule about which of the two wins
    # because there is only one of them.
    for r, line in enumerate(app.render().split("\n")):
        if "Asia 82" in line:
            app.click(line.index("Asia 82") + 2, r + 1, settle=1.2)
            break
    check("choosing an area types its prefix", "Asia/" in app.render(), app.render())
    check("and the list is only that area", "Africa/Abidjan" not in app.render(),
          app.render())

    # ... and typing narrows it further, in the same box.
    type_in_find(app, "seo")
    check("typing after it narrows further", "Asia/Seoul" in app.render(), app.render())
    check("to exactly one", " 1 of 418" in app.render(), app.render())

    space_on(app, "Asia/Seoul")
    # Checked against the config file rather than the screen, and that is not a
    # dodge: the picker is now correctly in front of the converter, so the row
    # it just added is behind it. The file is written the moment the list
    # changes, so it is the earliest and the strongest evidence there is.
    check("Space on the zone list adds it, and it is written down at once",
          (config_of(home) or {}).get("timezones") == ["America/Chicago", "Asia/Seoul"],
          str(config_of(home)))
    # And the key predc has just invented arrives explained, with a blank line
    # holding its block off the key above it. That is what the config file is
    # TOML for, and it is a property of what `Config.apply` asks for rather
    # than of anything the converter did -- so this is the one place in the
    # suite that reads the file as text.
    written = open(config_path(home)).read()
    check("the key it invented arrives with a sentence saying what it is for",
          "\n\n# The time zones the time converter shows" in written, repr(written))

    # A quarter-hour zone, which is the case a whole-hour offset table gets
    # wrong and the reason the offset crosses the port in minutes rather than
    # hours. Nepal is +05:45 now and was +05:30 until 1986.
    #
    # Spelled `Katmandu` because that is what `Intl.supportedValuesOf` calls
    # it -- the canonical list still carries a handful of legacy spellings,
    # while `Intl` itself accepts the modern alias. So a config file with
    # `Asia/Kathmandu` in it works and cannot be found by browsing, which is a
    # fact about the database rather than about predc.
    type_in_find(app, "Katmandu", clear=True)
    space_on(app, "Asia/Katmandu")
    check("and a second one goes on the end, in the order they were chosen",
          (config_of(home) or {}).get("timezones")
          == ["America/Chicago", "Asia/Seoul", "Asia/Katmandu"],
          str(config_of(home)))

    # ---- the wheel turns the list it is pointing at ----
    #
    # A wheel turn is not a positional event: `views.h` defines
    # `positionalEvents = evMouse & ~evMouseWheel`, so `TGroup::handleEvent`
    # never asks which view is under the pointer -- it offers the turn to every
    # view in z-order until one clears it, and `TScrollBar` is the only stock
    # view that asks for `evMouseWheel` at all. The frontmost bar therefore
    # answered for the whole window, and the frontmost is the last one
    # inserted: turning the wheel over the zone list scrolled `Displaying`, two
    # panes to the right, while the list under the pointer sat still. In a
    # window that is one list and its bar the old rule is invisible and right;
    # it takes three lists side by side to see it. `PaneScrollBar` in
    # `tvnode.h` is the answer -- a list's own bar takes the wheel only over
    # its own list.
    type_in_find(app, "Asia/", clear=True)
    zones = pane(app, "Zone")
    chosen = pane(app, "Displaying")
    check("the whole area is on offer again", zones[0] == "Asia/Aden", str(zones))
    check("with the three chosen zones beside it",
          chosen == ["America/Chicago", "Asia/Seoul", "Asia/Katmandu"], str(chosen))

    # Four turns and not one: a turn is three `arrowStep`s and the list is nine
    # rows deep, so the first three only move the highlight down inside what is
    # already on the screen. Nothing above the tenth row can prove anything.
    where = pane_point(app, "Zone")
    app.wheel(where[0], where[1], turns=4)
    check("the wheel scrolls the list under the pointer",
          pane(app, "Zone")[0] != zones[0], str(pane(app, "Zone")))
    check("and not the one two panes over",
          pane(app, "Displaying") == chosen, str(pane(app, "Displaying")))

    # The area list under the pointer, which says the same thing from the other
    # end and says it in text: choosing an area writes its prefix into Find, so
    # a wheel that reaches the areas at all is a wheel that changes the box.
    before = find_text(app)
    where = pane_point(app, "Area")
    app.wheel(where[0], where[1], turns=1)
    check("an area under the pointer answers for itself",
          find_text(app) != before, str((before, find_text(app))))

    # ---- the buttons act on the highlight, and the highlight is C++'s ----
    #
    # A list box's highlight lives in Turbo Vision, and `Focused` is the only
    # way a model that cannot call into it finds out where the highlight went.
    # `Selected` carries an index of its own, so `Space` and a double click
    # were always right; the buttons read the model's copy, and nothing wrote
    # to it between one `Selected` and the next. So Add added whichever row
    # the last filter reset had left it pointing at -- the first one -- however
    # far down the list the highlight had since been clicked or wheeled.
    type_in_find(app, "Asia/", clear=True)
    zones = pane(app, "Zone")
    wanted = zones[2]
    click_in(app, "Zone", wanted)
    click_button(app, "Add >>")
    check("Add adds the row the highlight is on, not the first one",
          (config_of(home) or {}).get("timezones")
          == ["America/Chicago", "Asia/Seoul", "Asia/Katmandu", wanted],
          str(config_of(home)) + " wanted " + wanted)

    # And the other list, whose highlight is a second copy of the same bug.
    click_in(app, "Displaying", "Asia/Seoul")
    click_button(app, "<< Remove")
    check("Remove removes the row the highlight is on, not the first one",
          (config_of(home) or {}).get("timezones")
          == ["America/Chicago", "Asia/Katmandu", wanted],
          str(config_of(home)))

    # Seoul back, and the borrowed zone off again, so that the checks after
    # Done have the three rows they read -- in a different order, which none of
    # them looks at. `Space` for the add, which is the route that was never
    # broken, and the button for the remove, which is the route that was.
    type_in_find(app, "Asia/Seoul", clear=True)
    # `click_in` and not `space_on`, which searches the whole line: the name is
    # now in the Find box as well, and the box is the first place it is found.
    click_in(app, "Zone", "Asia/Seoul")
    app.send(b" ", settle=1.4)
    click_in(app, "Displaying", wanted)
    click_button(app, "<< Remove")
    check("and the borrowed zone comes off the same way",
          (config_of(home) or {}).get("timezones")
          == ["America/Chicago", "Asia/Katmandu", "Asia/Seoul"],
          str(config_of(home)))

    # ---- the wheel, and the echo that used to drag the list back ----
    #
    # A list box's highlight is moved by two parties. The user moves it and is
    # reported; the model moves it by rendering a `focused`. Reporting the
    # second as well as the first was a loop -- the model writes the highlight,
    # hears that it moved, stores what it hears, writes it again -- and it was
    # invisible until the mouse wheel, which arrives as a burst of events the
    # model is several renders behind. Every echo of a stale index dragged the
    # list back to where it had been, so a click landed on a row that was no
    # longer under the pointer, and the zone that got added was one the user
    # had never seen.
    #
    # The check is a burst, then a click on a row read off the screen, and the
    # question is whether what was committed is the row that was clicked.
    type_in_find(app, "America/", clear=True)
    r, heading = picker_heading(app)
    zone_col = heading.index("Zone")
    before_wheel = pane(app, "Zone")
    burst_wheel(app, zone_col + 3, r + 3, 10)
    scrolled = pane(app, "Zone")
    check("a burst on the wheel scrolls the list under the pointer",
          scrolled != before_wheel, f"{scrolled} == {before_wheel}")

    aimed = scrolled[3]
    app.click(zone_col + 2, r + 2 + 3, settle=1.5)
    check("and the list stays where the wheel left it when a row is clicked",
          pane(app, "Zone") == scrolled, f"{pane(app, 'Zone')} != {scrolled}")

    app.send(b" ", settle=1.4)
    check("so the zone that arrives is the one that was under the pointer",
          (config_of(home) or {}).get("timezones", [])[-1] == aimed,
          f"{(config_of(home) or {}).get('timezones')} does not end in {aimed}")

    # Put the list back to the three the checks below read.
    click_in(app, "Displaying", aimed)
    click_button(app, "<< Remove")
    check("and the borrowed zone comes off again",
          (config_of(home) or {}).get("timezones")
          == ["America/Chicago", "Asia/Katmandu", "Asia/Seoul"],
          str(config_of(home)))

    # ---- Move Up and Move Down ----
    #
    # The order of the Displaying list is the order the converter shows the
    # zones in, and it was the order they happened to be added in with no way
    # to change it. These act on the same highlight the Remove button does.
    click_in(app, "Displaying", "Asia/Seoul")
    click_button(app, "Move Up")
    check("Move Up moves the highlighted row one place",
          (config_of(home) or {}).get("timezones")
          == ["America/Chicago", "Asia/Seoul", "Asia/Katmandu"],
          str(config_of(home)))

    click_button(app, "Move Up")
    check("and the highlight travels with the row, so twice is two places",
          (config_of(home) or {}).get("timezones")
          == ["Asia/Seoul", "America/Chicago", "Asia/Katmandu"],
          str(config_of(home)))

    # The check that pins a Gren trap rather than a picker one: `Array.get`
    # indexes from the *end* when the index is negative, so `Array.get -1` is
    # the last row and never `Nothing`. Move Up on the top row therefore
    # swapped the first zone with the last one, which is neither a move nor a
    # no-op. The bounds test in `move` is written out for this reason.
    click_button(app, "Move Up")
    check("and off the top is a no-op, not a swap with the bottom",
          (config_of(home) or {}).get("timezones")
          == ["Asia/Seoul", "America/Chicago", "Asia/Katmandu"],
          str(config_of(home)))

    click_button(app, "Move Down")
    check("and Move Down is the same the other way",
          (config_of(home) or {}).get("timezones")
          == ["America/Chicago", "Asia/Seoul", "Asia/Katmandu"],
          str(config_of(home)))

    click_button(app, "Done")
    check("Done closes the picker", "Time zones" not in app.render(), app.render())

    # With the picker out of the way, the rows it chose can be read. All three
    # are the same instant, which is the whole claim of the window.
    check("the chosen zones are all at the one instant",
          clock(app, "Asia/Seoul") == ("2026", "09", "02", "04", "32")
          and clock(app, "UTC") == ("2026", "09", "01", "19", "32"),
          str(clock(app, "Asia/Seoul")) + " " + str(clock(app, "UTC")))

    # Seoul has no abbreviation in en-US -- CLDR only carries them for North
    # America -- and `GMT+9` is the offset column spelled differently, so the
    # row shows the offset alone rather than the same fact twice.
    check("a zone with no abbreviation shows its offset alone",
          row(app, "Asia/Seoul")[5] == "+09:00", str(row(app, "Asia/Seoul")))
    check("a zone at a quarter past the hour is exact",
          row(app, "Asia/Katmandu")[5] == "+05:45", str(row(app, "Asia/Katmandu")))
    check("and its clock is quarter-hour offset from UTC",
          clock(app, "Asia/Katmandu") == ("2026", "09", "02", "01", "17"),
          str(clock(app, "Asia/Katmandu")))

    # Emptying the list is a choice and has to survive a restart, which is the
    # whole reason the config field is a `Maybe` rather than an array: an empty
    # array means "the user removed them all" and an absent key means "predc
    # has never been told", and they render differently.
    app.send(b"\x1bz", settle=1.5)
    for _ in range(3):
        click_button(app, "<< Remove")
    check("and an emptied list is written as empty",
          (config_of(home) or {}).get("timezones") == [], str(config_of(home)))

    click_button(app, "Done")
    check("every zone can be removed",
          row(app, "America/Chicago") is None and row(app, "Asia/Seoul") is None,
          app.render())
    check("UTC stays anyway, because it was never on the list",
          row(app, "UTC") is not None, app.render())

    # ---- Cancel puts back the list the picker opened on ----
    #
    # The picker applies every add and remove to the converter as it happens,
    # which is what makes it a workspace rather than a form. So there is no
    # draft to throw away and Cancel cannot be "do not commit": it is an undo,
    # back to what the converter was showing when the picker opened. The
    # config file follows without being told, because the shell writes it
    # whenever the two disagree.
    app.send(b"\x1bz", settle=1.5)
    type_in_find(app, "Asia/Seoul")
    click_in(app, "Zone", "Asia/Seoul")
    app.send(b" ", settle=1.4)
    # The config file and not the screen, for the same reason the first add was
    # checked that way: the picker is correctly in front of the converter, so
    # the row it just added is behind it. The screen is read after Cancel,
    # when there is nothing in the way.
    check("a zone added after the list was emptied is written down",
          (config_of(home) or {}).get("timezones") == ["Asia/Seoul"],
          str(config_of(home)))

    click_button(app, "Cancel")
    check("Cancel closes the picker", "Time zones" not in app.render(), app.render())
    check("and puts back the list it opened on",
          (config_of(home) or {}).get("timezones") == [], str(config_of(home)))
    check("so the row it added is gone again",
          row(app, "Asia/Seoul") is None, app.render())

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

    app.send(b"\x1bs", settle=2.0)
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

    # A second run, on the config the first one wrote: an empty list stays
    # empty rather than springing back to the machine's zone.
    again = Pty(node_argv(LAUNCHER) + ["time"], env, cwd=ROOT)
    again.pump(3.0)
    check("an emptied list stays empty across a restart",
          row(again, "America/Chicago") is None, again.render())
    check("with UTC and POSIX still there",
          row(again, "UTC") is not None and posix(again) is not None, again.render())
    again.send(b"\x1bx", settle=1.0)
    again.wait(timeout=6)

    return check.report(again)


if __name__ == "__main__":
    sys.exit(main())
