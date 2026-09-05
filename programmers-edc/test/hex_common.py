#!/usr/bin/env python3
"""What the four hex-viewer drivers share: the fixtures, the launch, and the
helpers that know where the dump is on the screen.

The suite was one driver of a thousand lines, and it was the whole wall clock
of `run_tests.py` -- 208s of a 229s run, with fifteen of sixteen cores idle
waiting for it. The phases it was already divided into were measured, and three
of them were two thirds of it: highlighting 45s, yanking 31s, pasting 61s. They
are separate drivers now, and the suite finishes in the time the longest of
four takes rather than the time all of them take.

The saving is more than the division suggests, because a driver's cost is not
linear in its length. `Pty.display()` replays the whole stream whenever the
buffer changes, so a session pays for its own history on every check: four
short sessions each replay a quarter as much, a quarter as often. That is also
why pasting cost more than highlighting despite being shorter -- it ran later,
against a bigger buffer.

Two orderings inside the old file were held by comments, and are now held by
the process boundary instead, which is the better half of the change:

  - **`p` with nothing ever copied** has to happen before anything copies,
    because predc falls back to its own last copy. It is in `drive_hex.py`,
    which never copies anything.
  - **`ESC]60;allowWindowOps`** is what TVision reads as "this terminal really
    does OSC 52", and nothing can be pasted before it. `allow_osc52` sends it;
    the drivers that paste call it in their setup, and `drive_hex_yank.py`
    does not, because checking the sentence predc prints *without* the claim
    is what that phase opens with.
"""

import base64
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

SIZE = 40960

ALT_F3 = b"\x1b\x1bOR"          # ESC-prefixed F3, which is how a terminal says Alt

# The dump, in screen coordinates. The window sits at desktop (0, 0), so its
# frame is screen row 1; the column header is row 2 and the first dump row is
# row 3. A dump line starts one column in from the frame.
FIRST_ROW = 3
ROWS = 16
LEFT = 1
HEX_AT = LEFT + 10
ASCII_AT = LEFT + 60
SCROLL_AT = LEFT + 77   # one column clear of the ASCII, hard against the frame
WHERE_ROW = 20
STATUS_ROW = 21


def rows(app):
    """The sixteen dump rows, framing stripped."""
    lines = app.render().split("\n")
    return [lines[FIRST_ROW + i][LEFT:LEFT + 76] for i in range(ROWS)]


def line_at(app, row):
    return app.render().split("\n")[row]


def offsets(app):
    return [row[:8] for row in rows(app)]


def where(app):
    return line_at(app, WHERE_ROW).strip("║░ ")


def status(app):
    return line_at(app, STATUS_ROW).strip("║░ ")


def click_at(app, col, row):
    """`Pty.click` counts from one and everything else here counts from zero."""
    app.click(col + 1, row + 1, settle=0.8)


def drag_over(app, path):
    """`Pty.drag` counts from one and everything else here counts from zero."""
    app.drag([(col + 1, row + 1) for col, row in path], settle=0.9)


def menu(app, item):
    """Open a pull-down by clicking its name on the bar."""
    bar = app.render().split("\n")[0]
    app.click(bar.index(item) + 1, 1, settle=0.6)


def copied(app, mark):
    """What the last OSC 52 written since `mark` carried."""
    found = re.findall(rb"\x1b\]52;;([A-Za-z0-9+/=]*)\x07", app.buf[mark:])
    return base64.b64decode(found[-1]).decode() if found else ""


def forget_copies(app):
    """Drop the big `OSC 52` payloads out of the replay buffer.

    `Pty.display()` feeds the whole stream to a fresh emulator on every render,
    deliberately -- "the buffers here are small and a stateful emulator that
    could drift is not worth the debugging". A megabyte copied to the clipboard
    is four megabytes of base64 on the wire, and every check after it replays
    them: it took this suite from half a minute to nearly three.

    None of it is screen output, so taking it back out changes nothing the
    emulator would have drawn. Call it once the copy has been read.
    """
    app.buf = re.sub(rb"\x1b\]52;;[A-Za-z0-9+/=]{1024,}\x07", b"", app.buf)


def paste(app, text, key=b"p", settle=1.1):
    """Press a paste key and answer the OSC 52 it sends.

    Only works once the driver has claimed OSC 52 support, which is what makes
    the clipboard the *terminal's* -- and the terminal is this file, so it can
    put anything it likes on it. Returns whether predc actually asked."""
    mark = len(app.buf)
    app.send(key, settle=0.7)
    asked = b"\x1b]52;;?\x07" in app.buf[mark:]
    app.send(b"\x1b]52;;" + base64.b64encode(text.encode()) + b"\x07", settle=settle)
    return asked


def paste_dump(app, text, settle=1.3):
    """Paste a dump, which is a menu entry and not a key.

    Reached by the letter it underlines, like everything else on this menu --
    which is what stops these checks depending on where the entry sits.
    """
    mark = len(app.buf)
    bytes_menu(app, b"u", settle=0.8)
    asked = b"\x1b]52;;?\x07" in app.buf[mark:]
    app.send(b"\x1b]52;;" + base64.b64encode(text.encode()) + b"\x07", settle=settle)
    return asked


def bytes_menu(app, keys, settle=0.9):
    """Open the Bytes pull-down and drive it with the letters it underlines.

    Which is the only way to reach a *nested* submenu without knowing where the
    second box lands -- and it is why nothing here counts menu lines any more.
    Two entries added to this menu moved Top and End down by three, and the
    four checks that broke were about neither.
    """
    menu(app, "Bytes")
    app.send(keys, settle=settle)


def dump_rows(app):
    """How many rows of the window are dump, counted rather than assumed --
    which is the whole point of the resize checks."""
    return sum(1 for row in app.render().split("\n")
               if len(row) > LEFT + 8 and is_offset(row[LEFT:LEFT + 8]))


def is_offset(text):
    return len(text) == 8 and all(c in "0123456789ABCDEF" for c in text)


def first_offset(app):
    for row in app.render().split("\n"):
        if len(row) > LEFT + 8 and is_offset(row[LEFT:LEFT + 8]):
            return row[LEFT:LEFT + 8]
    return ""


def find_row(app, text):
    for i, row in enumerate(app.render().split("\n")):
        if text in row:
            return i
    return -1


def frame_width(app):
    """The window's own width, from the row its title is on."""
    return len(line_at(app, 1).rstrip("░ "))


def resize(app, arrows):
    """Ctrl-F5 puts the window into Turbo Vision's size/move mode; shifted
    arrows resize rather than move; Enter commits."""
    app.send(b"\x1b[15;5~", settle=0.6)
    for i in range(0, len(arrows), 6):
        app.send(arrows[i:i + 6], settle=0.4)
    app.send(b"\r", settle=1.0)


def open_file(app, name, settle=1.6):
    """File | Open, type a name, press Enter -- OK is the default button."""
    bytes_menu(app, b"o", settle=1.0)
    app.send(name.encode(), settle=0.8)
    app.send(b"\r", settle=settle)


def double_click_in_list(app, name, settle=1.8):
    """Open the dialog and double-click a name in its list.

    The pause between the two presses is real rather than nominal: TVision
    timestamps a mouse event when it *reads* it, so two reports sitting in the
    pty buffer together look simultaneous however far apart they were written.
    0.12s is a human double click and is well inside the default 8-tick
    (440ms) window; 0.45s is outside it, which is worth knowing because it is
    what a driver written with a lazy settle accidentally measures.
    """
    bytes_menu(app, b"o", settle=1.0)
    row = col = None
    for y, line in enumerate(app.render().split("\n")):
        if name in line:
            row, col = y + 1, line.index(name) + 1
            break
    assert row is not None, f"{name} is not in the dialog's list"
    app.send(f"\x1b[<0;{col};{row}M".encode(), settle=0.1)
    app.send(f"\x1b[<0;{col};{row}m".encode(), settle=0.12)
    app.send(f"\x1b[<0;{col};{row}M".encode(), settle=0.1)
    app.send(f"\x1b[<0;{col};{row}m".encode(), settle=settle)


def go_to(app, text, settle=1.4):
    bytes_menu(app, b"g", settle=1.0)
    app.send(text.encode(), settle=0.8)
    app.send(b"\r", settle=settle)


def type_bytes(app, text, hexdigits=False, settle=1.4):
    """**Bytes | Type bytes...**, which is the one way in that never touches
    the clipboard -- and therefore the only one that works over ssh, where no
    terminal will hand a clipboard back and no setting makes it.

    A terminal paste is keystrokes, so keystrokes are what this sends.
    """
    bytes_menu(app, b"b", settle=1.0)
    app.send(text.encode(), settle=0.6)
    if hexdigits:
        app.send(b"\t\x1b[C", settle=0.6)          # Tab to the radio, pick hex
    app.send(b"\r", settle=settle)


def fixtures(big=False):
    """A scratch directory with the files every hex driver reads.

    The fixture is `i % 256`, which makes every assertion arithmetic: the byte
    at offset *n* is `n % 256`, and the row at a multiple of 256 is the whole
    table over again.

    `big.bin` is a megabyte and a byte -- one byte over the point where a copy
    stops being taken for granted, so that the two sides of that line are one
    file apart rather than a judgement about how big is big. Only the yank
    driver needs it, and writing a megabyte is not free, so it is asked for.
    """
    work = tempfile.mkdtemp(prefix="predc-hex-")
    with open(os.path.join(work, "sample.bin"), "wb") as f:
        f.write(bytes(i % 256 for i in range(SIZE)))
    with open(os.path.join(work, "small.bin"), "wb") as f:
        f.write(b"Hello, hex!")
    with open(os.path.join(work, "empty.bin"), "wb") as f:
        pass
    if big:
        with open(os.path.join(work, "big.bin"), "wb") as f:
            f.write(bytes(i % 256 for i in range(1048577)))
    return work


def launch(work):
    """Start predc in `work`, with a temporary HOME and no display.

    A temporary HOME, so that a driver reads no config file but the one it did
    not write. predc remembers its colour scheme in `$HOME/.config/predc/`, and
    a suite that inherited the real one would pass or fail depending on which
    theme the person running it happens to like -- which is exactly what
    happened once, when a scratch script left a `"gren"` behind and four colour
    checks in two suites started failing against a program that was working
    perfectly.

    And no display, which is not tidiness either. Turbo Vision reaches the
    system clipboard through `wl-copy`, `xsel` or `xclip` before it falls back
    to asking the terminal, and with a display set these suites would write to
    the clipboard of whoever ran them. Without one the copy is an `OSC 52` on
    the wire, which is the half a pty can read.
    """
    env = dict(os.environ, TERM="xterm-256color",
               HOME=tempfile.mkdtemp(prefix="predc-home-"))
    env.pop("XDG_CONFIG_HOME", None)
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    app = Pty(node_argv(LAUNCHER), env, cwd=work)
    app.pump(2.5)
    return app


def open_viewer(app, settle=1.2):
    """Alt-D, which is how the hex viewer is opened from anywhere."""
    app.send(b"\x1bd", settle=settle)


def allow_osc52(app, settle=0.6):
    """Tell predc this terminal really does answer an OSC 52 read.

    `ESC]60;allowWindowOps` is what TVision reads as that claim, and until it
    arrives predc will not write the query at all -- which is the state a real
    ssh session is permanently in, and is what `drive_hex.py`'s `p` check is
    about. Anything that pastes has to send this first.
    """
    app.send(b"\x1b]60;allowWindowOps\x07", settle=settle)
