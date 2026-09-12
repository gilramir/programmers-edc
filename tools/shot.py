"""Turn a screen the harness read into a PNG.

The drivers already run a real application at a real pty and replay everything
it drew into `harness.Screen` -- a grid of cells and, per cell, the colours in
force when it was written. That is a framebuffer in every sense except pixels,
so a screenshot is a blit: eight by sixteen bitmap per cell, two colours out of
sixteen, nearest-neighbour scale. No X server, no terminal emulator, no font
configuration, and the same bytes on every machine, which is what lets a
screenshot be checked in and compared rather than eyeballed.

Cropping is the reason to do it this way rather than photographing a terminal.
A documentation screenshot wants the widget, not the eighty columns around it,
and the widget's rectangle is written down in the example's source.

    shot(app, "docs/img/entries.png", rect={"x1": 4, "y1": 2, "x2": 52, "y2": 14})

Rectangles are the same convention as `Tui.Rect`: `x2,y2` is one past the last
cell, so `{x1=0,y1=0,x2=80,y2=25}` is the whole screen.
"""

import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cp437

# The sixteen colours a VGA card had, which is what Turbo Vision's palettes
# deal in and what the terminal running these applications is showing. Naming
# them here rather than sampling somebody's terminal theme is deliberate: a
# screenshot in the documentation should look like the program, not like the
# machine that photographed it.
VGA = [
    (0x00, 0x00, 0x00), (0x00, 0x00, 0xAA), (0x00, 0xAA, 0x00), (0x00, 0xAA, 0xAA),
    (0xAA, 0x00, 0x00), (0xAA, 0x00, 0xAA), (0xAA, 0x55, 0x00), (0xAA, 0xAA, 0xAA),
    (0x55, 0x55, 0x55), (0x55, 0x55, 0xFF), (0x55, 0xFF, 0x55), (0x55, 0xFF, 0xFF),
    (0xFF, 0x55, 0x55), (0xFF, 0x55, 0xFF), (0xFF, 0xFF, 0x55), (0xFF, 0xFF, 0xFF),
]

DEFAULT_FG, DEFAULT_BG = 7, 0

# ANSI's colour order is not VGA's. SGR counts black, red, green, yellow, blue,
# magenta, cyan, white; a VGA palette entry counts black, blue, green, cyan,
# red, magenta, brown, white -- the same eight with the low and high bits of
# the index swapped. Getting this wrong is not subtle and is not an error
# either: every window comes out red on pink and looks deliberate.
ANSI_TO_VGA = [0, 4, 2, 6, 1, 5, 3, 7]


def rgb(code, default):
    """One of the harness's colour readings as an (r, g, b).

    Indexed colours arrive as the SGR number itself -- 30-37 and 90-97 for a
    foreground, 40-47 and 100-107 for a background. A theme's 24-bit colour
    arrives already as a tuple, and an xterm-256 one as ("xterm", n), which
    only the first sixteen entries of are worth resolving here.
    """
    if code is None:
        return VGA[ANSI_TO_VGA[default]]
    if isinstance(code, tuple):
        if code[0] == "xterm":
            n = code[1]
            return VGA[ANSI_TO_VGA[n & 7] + (8 if n & 8 else 0)] if n < 16 \
                else (0x80, 0x80, 0x80)
        return code
    if 30 <= code <= 37 or 40 <= code <= 47:
        return VGA[ANSI_TO_VGA[code % 10]]
    if 90 <= code <= 97 or 100 <= code <= 107:
        return VGA[ANSI_TO_VGA[code % 10] + 8]
    return VGA[ANSI_TO_VGA[default]]


def _rect(rect, screen):
    if rect is None:
        return 0, 0, screen.cols, screen.rows
    if isinstance(rect, dict):
        x1, y1, x2, y2 = rect["x1"], rect["y1"], rect["x2"], rect["y2"]
    else:
        x1, y1, x2, y2 = rect
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(screen.cols, x2), min(screen.rows, y2)
    return x1, y1, x2, y2


def pixels(screen, rect=None, scale=1, cursor=None):
    """The crop as (width, height, rows of RGB bytes), unscaled cells x 8x16."""
    x1, y1, x2, y2 = _rect(rect, screen)
    width = (x2 - x1) * cp437.WIDTH * scale
    lines = []

    for row in range(y1, y2):
        for y in range(cp437.HEIGHT):
            line = bytearray()
            for col in range(x1, x2):
                fg, bg = screen.attrs[row][col]
                ink = rgb(fg, DEFAULT_FG)
                paper = rgb(bg, DEFAULT_BG)
                bits = cp437.rows(screen.grid[row][col])[y]
                if cursor == (col, row) and y >= cp437.HEIGHT - 2:
                    bits = 0xFF
                for x in range(cp437.WIDTH):
                    line += bytes(ink if bits >> (7 - x) & 1 else paper) * scale
            lines += [bytes(line)] * scale

    return width, len(lines), lines


def png(screen, rect=None, scale=2, cursor=None):
    """The crop as the bytes of an 8-bit RGB PNG."""
    width, height, lines = pixels(screen, rect, scale, cursor)
    raw = b"".join(b"\x00" + line for line in lines)

    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def save(path, screen, rect=None, scale=2, cursor=None):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as out:
        out.write(png(screen, rect, scale, cursor))
    return path


def shot(app, path, rect=None, scale=2, cursor=False, pad=0):
    """Photograph a running application.

    `cursor` draws the terminal's own caret where the application put it, which
    is worth having in a picture of an input line and misleading in a picture
    of anything else -- so it is off unless asked for.
    """
    screen = app.display()
    if pad and rect is not None:
        x1, y1, x2, y2 = _rect(rect, screen)
        rect = (x1 - pad, y1 - pad, x2 + pad, y2 + pad)
    return save(path, screen, rect, scale, app.cursor() if cursor else None)


def window(win, view=None):
    """A screen rectangle from the rectangles an example is written in.

    A window's rectangle is in desktop coordinates, one row below the screen's;
    a view's is relative to its window, whose frame is row and column zero. The
    arithmetic is two additions and it is wrong every other time by hand.
    """
    x1 = win["x1"]
    y1 = win["y1"] + 1
    if view is None:
        return (x1, y1, win["x2"], win["y2"] + 1)
    return (x1 + view["x1"], y1 + view["y1"],
            x1 + view["x2"], y1 + view["y2"])
