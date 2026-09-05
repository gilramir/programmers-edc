#!/usr/bin/env python3
"""What the three time-converter drivers share: the launch, the picker setup,
and the helpers that read a converter row off the screen.

`drive_time.py` was 125.2s and became the wall clock of `run_tests.py` the
moment `drive_hex.py` was split off it. Its sections were timed the same way
and came out flat -- 35.9s of conversions, 71.6s spread over six picker
sections, 17.7s of live clock -- so this is a split into three rather than the
four the hex driver wanted, and the arithmetic says why: `drive_unicode.py` is
55.5s, and nothing under that changes the suite.

`TZ` is pinned for the whole run, which is what makes "the machine's own zone"
a testable claim rather than a fact about the machine the suite happens to be
on. node honours it, `Intl.DateTimeFormat().resolvedOptions().timeZone`
reports it, and `Time.getZoneName` is what predc reads.
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
    would bind Alt-A and the ASCII chart already has it. That was the status
    line's when this was written and is the Tools menu's now; the collision is
    the same one either way.
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



def launch():
    """Start `predc time` with a pinned zone and a temporary HOME.

    A temporary HOME so that no config file but this driver's own is read --
    predc writes its zones the moment they change, and a suite that inherited
    a real one would be testing somebody's preferences. Returns `(app, home)`,
    because every check about the zone list reads the file rather than the
    screen.
    """
    home = tempfile.mkdtemp(prefix="predc-home-")
    env = dict(os.environ, TERM="xterm-256color", TZ="America/Chicago", HOME=home)
    env.pop("XDG_CONFIG_HOME", None)
    app = Pty(node_argv(LAUNCHER) + ["time"], env, cwd=ROOT)
    app.pump(3.0)
    return app, home


def relaunch(home):
    """A second `predc time` on the config the first one wrote.

    The same environment as `launch`, pointed at a HOME that already has a
    config file in it -- which is the only way to ask whether an *emptied*
    list stays empty rather than springing back to the machine's own zone.
    """
    env = dict(os.environ, TERM="xterm-256color", TZ="America/Chicago", HOME=home)
    env.pop("XDG_CONFIG_HOME", None)
    app = Pty(node_argv(LAUNCHER) + ["time"], env, cwd=ROOT)
    app.pump(3.0)
    return app


def pin_instant(app):
    """Put the converter on `WHEN`, which every conversion check is against."""
    retype(app, posix_at(app), str(WHEN), settle=1.2)


def open_picker(app, settle=1.5):
    app.send(b"\x1bz", settle=settle)


def add_zone(app, zone):
    """Find a zone and Space it onto the Displaying list."""
    type_in_find(app, zone.split("/")[-1], clear=True)
    space_on(app, zone)


def picker_with_three(app):
    """The state the button checks leave behind, built from nothing.

    `drive_time_moves.py` starts where `drive_time_picker.py` stops, and this
    is that seam written down: the picker open over a Displaying list of
    Chicago, Katmandu and Seoul in that order. Katmandu before Seoul because
    that is the order the button section leaves them in, and the first Move Up
    check reads it.

    Spelled `Katmandu` because that is what `Intl.supportedValuesOf` calls it
    -- the canonical list still carries a handful of legacy spellings, while
    `Intl` itself accepts the modern alias.
    """
    pin_instant(app)
    open_picker(app)
    add_zone(app, "Asia/Katmandu")
    add_zone(app, "Asia/Seoul")
