#!/usr/bin/env python3
"""Photograph predc's desktop, once in each of its three colour schemes.

Three pictures, and what varies between them is deliberately two things at
once: the scheme, and which tools are open. A colour scheme is not a swatch
here -- `Theme` is a *palette* the package draws with and a set of *inks* the
tools' own canvases paint with, and the second half is invisible unless
something is painted. So each shot opens tools that paint: a hex dump with
coloured ranges in it, a chart with a selected cell, a converter with rows.

    devbox run -- python3 docs/shots.py             # all three, ~40s
    devbox run -- python3 docs/shots.py midnight    # just this one

**Nothing here touches your config file.** predc keeps its scheme and its zone
list in `$XDG_CONFIG_HOME/predc/config.toml`, falling back to
`$HOME/.config/...`, so each shot runs against a temporary `HOME` with a
config file this script wrote -- which is how every pty driver under
`programmers-edc/test/` already isolates itself, and is why predc needs no
flag for it. Writing the file rather than driving Options ▸ Colors is worth a
sentence: a scheme chosen from the menu leaves the menu bar highlighted and the
pull-down's shadow on the desktop for a moment, and a scheme read from a file
is simply the scheme the program started in.

All three are reproducible byte for byte, which is the reason the time
converter is pinned to an instant and given a zone list rather than being
photographed as it found the machine. `stable=False` exists for the shot that
cannot be, and none of these is.
"""

import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PREDC = os.path.join(ROOT, "programmers-edc")
LAUNCHER = os.path.join(PREDC, "bin", "predc.js")
IMG = os.path.join(HERE, "img")

sys.path.insert(0, os.path.join(ROOT, "tvision-node", "test"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from harness import Pty, node_argv
import cp437
import shot

# The desktop every shot is taken on. Bigger than eighty by twenty-five so
# that two windows fit side by side without either being shrunk to a stub --
# predc's tools size themselves from the desktop, so this is also the number
# that decides how much of a dump or a chart is on the screen.
SIZE = (100, 30)

# No tapes: a shot is not a test, and recording one costs a replay per boot.
#
# `COLORTERM=truecolor` because two of the three schemes are `Rgb` throughout.
# Without it TVision quantises them to the sixteen colours and the picture is
# of a palette nobody chose. No `DISPLAY`, so that a copy would go to the
# terminal rather than to the clipboard of whoever ran this; nothing here
# copies, and it costs nothing to keep the promise anyway.
BASE_ENV = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor",
                TVNODE_TAPES="0")
for _stale in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "DISPLAY", "WAYLAND_DISPLAY"):
    BASE_ENV.pop(_stale, None)

ENTER, HOME, DELETE = b"\r", b"\x1b[H", b"\x1b[3~"
DOWN, RIGHT, BACKTAB = b"\x1b[B", b"\x1b[C", b"\x1b[Z"
# Shifted arrows resize in Turbo Vision's size/move mode; Ctrl-F5 enters it.
SHIFT_UP, CTRL_F5 = b"\x1b[1;2A", b"\x1b[15;5~"

wanted = set(sys.argv[1:])
taken = []


# ------------------------------------------------------------------ running


def boot(theme, *args, config="", cwd=None, settle=2.6):
    """predc in `theme`, on a HOME nobody else has written to.

    `config` is more lines for the file -- the zone list, in the one shot that
    has an opinion about zones. `TZ` is pinned for the same reason a driver
    pins it: "the machine's own zone" is otherwise a fact about the machine
    this was run on, and it would be in the picture.
    """
    home = tempfile.mkdtemp(prefix="predc-shot-")
    os.makedirs(os.path.join(home, ".config", "predc"))
    with open(os.path.join(home, ".config", "predc", "config.toml"), "w") as f:
        f.write('theme = "%s"\n%s' % (theme, config))
    env = dict(BASE_ENV, HOME=home, TZ="America/Chicago")
    app = Pty(node_argv(LAUNCHER, *args), env,
              cwd=cwd or tempfile.mkdtemp(prefix="predc-shot-cwd-"), size=SIZE)
    app.pump(settle)
    return app


def quit(app):
    app.send(b"\x1bx", settle=0.4)
    app.kill()


def take(app, name, rect=None, stable=True, **kw):
    path = shot.shot(app, os.path.join(IMG, name + ".png"), rect, **kw)
    taken.append((name, stable))
    print("  %-24s %7d bytes%s"
          % (name + ".png", os.path.getsize(path), "" if stable else "   (not stable)"))


def wants(*names):
    return not wanted or wanted & set(names)


# ------------------------------------------------------- moving windows about


def reshape(app, move=b"", size=b""):
    """Turbo Vision's own resize/move mode, which the model never hears about.

    `Ctrl-F5` enters it, plain arrows move the window and shifted ones resize
    it, `Enter` commits. Both bursts are `wait=` rather than a settle: twenty
    presses of the same key are twenty events the pump chews through in
    batches, and the screen is perfectly still between two of them.
    """
    app.send(CTRL_F5, settle=0.6)
    if size:
        app.send(size, wait=0.2 + 0.05 * len(size))
    if move:
        app.send(move, wait=0.2 + 0.05 * len(move))
    app.send(ENTER, settle=1.0)


def bar(app, title):
    """Open a pull-down by clicking its name on the bar.

    Clicked rather than Alt-keyed because a tool's own menu title carries no
    underlined letter on purpose -- an open tool owns its Alt key for as long
    as its window is up, and `Tool.Encode` gave one back for exactly that.
    """
    line = app.render().split("\n")[0]
    app.click(line.index(title) + 1, 1, settle=0.6)


def raise_window(app, title):
    """Click a window's title bar, which brings it to the front and takes the
    caret with it. The frame's row is found rather than counted, because the
    window under it may have been moved by then."""
    for row, line in enumerate(app.render().split("\n")):
        if title in line and ("═" in line or "─" in line):
            app.click(line.index(title) + 1, row + 1, settle=1.0)
            return
    raise AssertionError("no window titled %r:\n%s" % (title, app.render()))


# ---------------------------------------------------------------- Borland
#
# The scheme predc opens in, and the two tools that are small enough to sit
# beside each other without either being resized: the chart on the left, the
# calculator moved clear of it on the right.


def borland():
    app = boot("borland")

    app.send(b"\x1ba", settle=1.3)
    # Nine to the right of NUL is the tab, which is the character that makes
    # the point of the bottom two lines: a control code has a name, an escape
    # and four bases, and none of that is what the grid can show.
    app.send(RIGHT * 9, wait=0.8)

    app.send(b"\x1br", settle=1.3)
    reshape(app, move=RIGHT * 34 + DOWN * 6)

    # The stack, in hex, which is the base this calculator exists for. A value
    # is *read* in the base showing, so Tab comes first: `dead_beef` is a
    # number here and would be refused in decimal.
    app.send(b"\t", settle=0.7)
    app.send(b"dead_beef\r", settle=0.7)
    app.send(b"ff00\r", settle=0.7)
    app.send(b"&", settle=0.7)
    app.send(b"cafe\r", settle=0.7)
    # Left on the entry line rather than pushed, so that the picture has the
    # prompt in it as well as the stack.
    app.send(b"10", settle=0.7)

    take(app, "predc-borland")
    quit(app)


# ---------------------------------------------------------------- Midnight
#
# The dark scheme, and the tool with the most inks in it. Four ranges of a PNG
# header are painted in four of the six highlight colours -- which is the one
# thing in this program that a *palette* cannot reach, because a `Tui.Span`
# names a `Tui.Hue` and there is nothing between it and the terminal.


PNG = (b"\x89PNG\r\n\x1a\n"
       b"\x00\x00\x00\rIHDR\x00\x00\x02\x00\x00\x00\x01\x40\x08\x06"
       b"\x00\x00\x00\x1f\x8f\xc6\xd4"
       b"\x00\x00\x00\x19tEXtSoftware\x00predc, the hex dump viewer\x00\x8a\x1c\x2f")


def mark(app, offset, span, colour):
    """Go to an offset and paint the next `span + 1` bytes.

    `v` is the mark, the cursor is its far end, and one of `1`-`6` paints what
    is marked and leaves the mode. Going there by **Bytes ▸ Go to** rather
    than by arrows: the offset is the thing being said, and counting to it
    would make the picture depend on where the previous mark finished.
    """
    bar(app, "Bytes")
    app.send(b"g", settle=0.9)
    app.send(offset.encode(), settle=0.5)
    app.send(ENTER, settle=1.0)
    app.send(b"v", settle=0.5)
    app.send(RIGHT * span, wait=0.7)
    app.send(colour, settle=0.7)


def midnight():
    work = tempfile.mkdtemp(prefix="predc-shot-png-")
    with open(os.path.join(work, "banner.png"), "wb") as out:
        out.write(PNG)
    app = boot("midnight", "hex", "banner.png", cwd=work)

    # Eighty bytes is five rows, so the window can lose two thirds of its
    # height and still hold the whole file -- which is what makes room for the
    # decoder underneath it rather than behind it.
    reshape(app, size=SHIFT_UP * 8)
    # The signature, the chunk length, the chunk type, and the keyword inside
    # the text chunk: the four spans somebody reading a PNG by hand would
    # actually mark, in four colours, which is the argument for the feature.
    mark(app, "0x0", 7, b"1")
    mark(app, "0x8", 3, b"2")
    mark(app, "0xC", 3, b"3")
    mark(app, "0x25", 3, b"4")

    app.send(b"\x1bu", settle=1.4)
    # Hex input rather than text: the bytes are the subject, and typing `é` at
    # a pty puts two bytes through an input line one character at a time.
    # `Tab` reaches the Text/Hex radio, `Right` picks Hex, `Tab` comes back.
    app.send(b"\t", settle=0.6)
    app.send(RIGHT, settle=0.8)
    app.send(BACKTAB, settle=0.6)
    app.send(b"63 61 66 C3 A9 20 C2 BF 71 75 C3 A9 3F", settle=1.4)
    # The field is narrower than what was typed, so it is scrolled one
    # group to the left and the first byte is off it. `Home` is the whole
    # fix, and it is worth doing: the picture is of a field with bytes in
    # it, and the bytes it should start with are the ones it starts with.
    app.send(HOME, settle=0.7)
    # Down past the dump and a little to the right of it, and shortened by as
    # much as it moved: two windows that do not overlap say more about a
    # desktop than two that do, and there is room here for exactly that.
    reshape(app, size=SHIFT_UP * 8, move=RIGHT * 14 + DOWN * 13)

    # The dump is the subject, so it goes back in front -- and a window that
    # is not in front draws a single-cornered frame, which is the only thing
    # on the screen that says which one has the keyboard.
    raise_window(app, "Hex Dump")

    take(app, "predc-midnight")
    quit(app)


# ---------------------------------------------------------------- Gren
#
# The light scheme, on the two tools whose windows are mostly text -- which is
# where a light scheme is either right or quietly wrong. Every colour in it was
# picked as a contrast ratio against paper; this is the picture that shows it.


# 2026-09-01T19:32:00Z, which is the instant `time_common.py` pins for the
# same two reasons: it is inside US daylight saving, so Chicago is -05:00
# rather than the -06:00 a fixed-offset table would carry, and Kolkata's
# +05:30 is a half hour no whole-hour arithmetic reaches.
WHEN = b"1788291120"

ZONES = ('timezones = ["America/Chicago", "America/Los_Angeles", '
         '"Europe/Berlin", "Asia/Kolkata", "Asia/Seoul"]\n')


def gren():
    app = boot("gren", "time", config=ZONES, settle=3.0)

    # Typing an instant into the POSIX box is also what stops the clock, so
    # this is the one keystroke that makes the shot reproducible. The field is
    # found on the screen rather than counted to, and cleared with `Delete`
    # because a click puts the caret at the front of what is there.
    where = None
    for row, line in enumerate(app.render().split("\n")):
        found = re.search(r"POSIX\s+(-?\d+)", line)
        if found:
            where = (found.start(1) + 1, row + 1)
            break
    assert where is not None, app.render()
    app.click(*where, settle=0.7)
    app.send(DELETE * 16, wait=0.9)
    app.send(WHEN, settle=1.4)

    app.send(b"\x1bj", settle=1.4)
    app.send(b"Turbo Vision, from Gren", settle=1.2)
    reshape(app, size=SHIFT_UP * 2, move=DOWN * 16)

    take(app, "predc-gren")
    quit(app)


SECTIONS = [
    ("borland", borland, ("predc-borland",)),
    ("midnight", midnight, ("predc-midnight",)),
    ("gren", gren, ("predc-gren",)),
]


def main():
    print("shots into %s" % os.path.relpath(IMG, os.getcwd()))
    for name, run, names in SECTIONS:
        if wants(name, *names):
            print("%s:" % name)
            run()
    print("%d shots, %d of them reproducible"
          % (len(taken), sum(1 for _, stable in taken if stable)))
    # A character CP437 has no code for is drawn `?`, which in a screenshot is
    # indistinguishable from a program that meant to draw one. Saying so here
    # is the difference between a picture that is wrong and a picture that is
    # wrong and nobody was told.
    if cp437.unknown:
        print("not in the font, drawn as `?`: %s"
              % " ".join(sorted(cp437.unknown)))


if __name__ == "__main__":
    main()
