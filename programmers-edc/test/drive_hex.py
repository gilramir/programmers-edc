#!/usr/bin/env python3
"""predc's hex dump viewer: a file it never loads.

The thing being tested is the reading strategy. The viewer holds the file's
size and one 16 KB chunk around wherever the cursor is, and reads the rest
through `FileSystem.readFileStream` with a `Between { start, end }` -- Node's
`createReadStream({start, end})`. So the interesting checks here are the ones
that jump past the first chunk: `Ctrl-End` on a forty kilobyte file, and a Go
To of an offset in the middle of it. If the bytes on screen are right there,
the paging works, and the same code opens a file of any size.

The fixture is forty kilobytes of `i % 256`, which makes every assertion
arithmetic: the byte at offset *n* is `n % 256`, and the row at a multiple of
256 is the whole table over again.

One check here is about the *package* rather than this tool. A dialog opens
with the caret on the first view in its `views` array that can hold one, and
`Tui.fileDialog` used to list its buttons first by accident, so it opened on OK
and typing a path did nothing. That is fixed in the package; "the Name field
takes what is typed at it" is the check that says so, and it is worth keeping
here because an order in an array is exactly the kind of thing a later edit
reshuffles without meaning to.
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


def menu(app, item):
    """Open a pull-down by clicking its name on the bar."""
    bar = app.render().split("\n")[0]
    app.click(bar.index(item) + 1, 1, settle=0.6)


def copied(app, mark):
    """What the last OSC 52 written since `mark` carried."""
    found = re.findall(rb"\x1b\]52;;([A-Za-z0-9+/=]*)\x07", app.buf[mark:])
    return base64.b64decode(found[-1]).decode() if found else ""


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


def main():
    check = Checks()
    work = tempfile.mkdtemp(prefix="predc-hex-")
    with open(os.path.join(work, "sample.bin"), "wb") as f:
        f.write(bytes(i % 256 for i in range(SIZE)))
    with open(os.path.join(work, "small.bin"), "wb") as f:
        f.write(b"Hello, hex!")
    with open(os.path.join(work, "empty.bin"), "wb") as f:
        pass

    # A temporary HOME, so that this driver reads no config file but the one
    # it did not write. predc remembers its colour scheme in
    # `$HOME/.config/predc/`, and a suite that inherited the real one would
    # pass or fail depending on which theme the person running it happens to
    # like -- which is exactly what happened once, when a scratch script left a
    # `"gren"` behind and four colour checks in two suites started failing
    # against a program that was working perfectly.
    env = dict(os.environ, TERM="xterm-256color",
               HOME=tempfile.mkdtemp(prefix="predc-home-"))
    env.pop("XDG_CONFIG_HOME", None)
    # And no display, which is not tidiness either. Turbo Vision reaches the
    # system clipboard through `wl-copy`, `xsel` or `xclip` before it falls
    # back to asking the terminal, and with a display set this suite would
    # write to the clipboard of whoever ran it. Without one the copy is an
    # `OSC 52` on the wire, which is the half a pty can read.
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    app = Pty(node_argv(LAUNCHER), env, cwd=work)
    app.pump(2.5)

    # 1. The tool opens empty, and says how to give it something to look at.
    app.send(b"\x1bd", settle=1.2)
    screen = app.render()
    check("Alt-D opened the hex viewer", "Hex Dump" in screen, screen.split("\n")[1])
    check("and it brought its own menu with it", "Bytes" in screen.split("\n")[0],
          screen.split("\n")[0])
    check("the column header is there before any file is",
          "00 01 02 03 04 05 06 07  08 09 0A 0B 0C 0D 0E 0F" in screen, screen)
    check("and the empty dump says what to do about it",
          "Nothing open" in screen, screen)

    # 2. The file dialog. Typing into it is the package check described above.
    bytes_menu(app, b"o", settle=1.0)
    check("Open file... opened the dialog", "Open file" in app.render(), app.render())
    check("and it listed the directory the program was run in",
          "sample.bin" in app.render(), app.render())
    app.send(b"sample", settle=0.8)
    check("the caret is in the Name field, not the list",
          any("sample" in row and "↓" in row for row in app.render().split("\n")),
          app.render())
    app.send(b".bin", settle=0.6)
    app.send(b"\r", settle=1.8)

    # 3. What forty kilobytes of `i % 256` looks like.
    screen = app.render()
    check("the title carries the name and the size",
          "sample.bin" in screen.split("\n")[1] and "40960" in screen.split("\n")[1],
          screen.split("\n")[1])
    check("the first row is offset zero",
          rows(app)[0].startswith("00000000  00 01 02 03 04 05 06 07  08 09 0A 0B 0C 0D 0E 0F"),
          rows(app)[0])
    check("the offsets go up by sixteen",
          offsets(app)[:3] == ["00000000", "00000010", "00000020"], str(offsets(app)[:3]))
    check("printable bytes are printed",
          rows(app)[3].endswith("0123456789:;<=>?"), rows(app)[3])
    check("and unprintable ones are not",
          rows(app)[0].endswith("·" * 16), rows(app)[0])

    # 4. The two lines underneath: every base, and the byte's ASCII name.
    check("the offset line names the byte in every base",
          where(app).startswith("Offset 00000000 (0)") and "Hex 00" in where(app)
          and "Bin 0000 0000" in where(app), where(app))
    check("and the line under it says what the byte is called",
          status(app).startswith("NUL") and "Ctrl-@" in status(app), status(app))

    # 5. Moving. The cursor is painted *and* the hardware cursor follows it,
    #    which is the only part a test can read directly.
    check("the caret starts on the first byte", app.cursor() == (HEX_AT, FIRST_ROW),
          str(app.cursor()))
    app.send(b"\x1b[C", settle=0.7)
    check("Right moves one byte", where(app).startswith("Offset 00000001 (1)"), where(app))
    check("and the byte it lands on is named",
          status(app).startswith("SOH"), status(app))
    app.send(b"\x1b[B", settle=0.7)
    check("Down moves one row", where(app).startswith("Offset 00000011 (17)"), where(app))
    check("and the caret went with it", app.cursor() == (HEX_AT + 3, FIRST_ROW + 1),
          str(app.cursor()))
    display = app.display()
    check("the selected byte is painted, not merely pointed at",
          display.bg_at(HEX_AT + 3, FIRST_ROW + 1) == 47
          and display.fg_at(HEX_AT + 3, FIRST_ROW + 1) == 34,
          f"fg={display.fg_at(HEX_AT + 3, FIRST_ROW + 1)} "
          f"bg={display.bg_at(HEX_AT + 3, FIRST_ROW + 1)}")
    check("and so is its half of the printable column",
          display.bg_at(ASCII_AT + 1, FIRST_ROW + 1) == 47,
          str(display.bg_at(ASCII_AT + 1, FIRST_ROW + 1)))

    # 6. A screenful at a time. Sixteen rows of sixteen is 256 bytes, so a
    #    PgDn on this fixture lands on the same table over again.
    app.send(b"\x1b[6~", settle=0.8)
    check("PgDn scrolls by a screenful", offsets(app)[0] == "00000100", str(offsets(app)[:2]))
    check("and the byte under the cursor keeps its place in the window",
          where(app).startswith("Offset 00000111 (273)"), where(app))
    check("and the fixture repeats, so the bytes prove the offset",
          rows(app)[0].endswith("·" * 16) and rows(app)[0][10:21] == "00 01 02 03",
          rows(app)[0])
    app.send(b"\x1b[5~", settle=0.8)
    check("PgUp comes back", offsets(app)[0] == "00000000", str(offsets(app)[:2]))

    # 7. Past the first chunk, which is the whole point. 16 KB is read at a
    #    time and the end of the file is at 40 KB, so nothing here has been in
    #    memory before.
    bytes_menu(app, b"e")
    check("End of file goes to the last byte",
          where(app).startswith("Offset 00009FFF (40959)"), where(app))
    check("and the bytes there are read, not guessed",
          rows(app)[ROWS - 1].startswith("00009FF0  F0 F1 F2 F3 F4 F5 F6 F7  F8 F9 FA FB FC FD FE FF"),
          rows(app)[ROWS - 1])
    check("the last row is the bottom row: nothing is scrolled past the end",
          offsets(app)[ROWS - 1] == "00009FF0", str(offsets(app)[-2:]))
    bytes_menu(app, b"t")
    check("Top of file comes back to zero",
          where(app).startswith("Offset 00000000 (0)") and offsets(app)[0] == "00000000",
          where(app))

    # 8. Go to an offset, in either base. 0x1234 is inside the second chunk.
    go_to(app, "0x1234")
    check("Go to offset takes hex", where(app).startswith("Offset 00001234 (4660)"),
          where(app))
    check("and the byte there is the one the fixture put there",
          "Hex 34" in where(app), where(app))
    check("the row it asked for is on screen, not at the top of it",
          "00001230" in offsets(app) and offsets(app)[0] != "00001230",
          str(offsets(app)))
    go_to(app, "300")
    check("and it takes decimal too", where(app).startswith("Offset 0000012C (300)"),
          where(app))

    # 9. A message stays up. The calculator's lesson: `update` used to wipe its
    #    hint on the next keystroke, so nobody ever read it.
    go_to(app, "0x", settle=1.0)
    check("a bad offset is reported", status(app).startswith("Not an offset"), status(app))
    app.send(b"\x1b[C", settle=0.7)
    check("and the report survives the next keystroke",
          status(app).startswith("Not an offset"), status(app))

    # 10. The mouse picks a byte, in either column.
    row_two = offsets(app)[2]
    click_at(app, ASCII_AT + 5, FIRST_ROW + 2)
    picked = where(app)
    check("a click in the printable column picks that byte",
          int(picked.split("(")[1].split(")")[0]) == int(row_two, 16) + 5,
          f"{picked} on row {row_two}")
    click_at(app, HEX_AT + 9, FIRST_ROW + 2)
    check("a click in the hex column picks the same way",
          int(where(app).split("(")[1].split(")")[0]) == int(row_two, 16) + 3,
          where(app))

    # 11. The scroll bar, on one click and not two. The caret is on the canvas
    #     -- everything above put it there -- and `TView::handleEvent` swallows
    #     a mouse-down on a selectable view that has not got it, unless the
    #     view says the first click counts. `JsScrollBar` says so, and this is
    #     the check that says it still does: a bar you have to click twice is a
    #     bar whose behaviour depends on something no screen shows.
    #     The bottom row of the bar is its down arrow -- the bar and the dump
    #     are the same height -- so this is one arrowStep, and it used to take
    #     two clicks to get it.
    go_to(app, "0")
    click_at(app, SCROLL_AT, FIRST_ROW + ROWS - 1)
    check("one click on the scroll bar scrolls the dump",
          offsets(app)[0] == "00000010", str(offsets(app)[:2]))
    check("and drags the cursor along, so the lines below still describe "
          "something on screen",
          where(app).startswith("Offset 00000010 (16)"), where(app))

    #     A click on the bar itself takes the thumb to the pointer rather than
    #     paging -- magiblot's divergence from Borland's, which pages -- so the
    #     same click twice is the same offset twice, and that is the check that
    #     tells the two apart.
    click_at(app, SCROLL_AT, FIRST_ROW + ROWS // 2)
    landed = offsets(app)[0]
    check("a click on the bar goes where the pointer is, not a page down",
          landed not in ("00000000", "00000010"), landed)
    click_at(app, SCROLL_AT, FIRST_ROW + ROWS // 2)
    check("and clicking the same place again is the same place",
          offsets(app)[0] == landed, f"{landed} -> {offsets(app)[0]}")

    # The caret is on the bar now, and it takes two clicks to get it back to
    # the dump -- a canvas is selectable and says nothing about first clicks,
    # so it is the case the scroll bar no longer is.
    click_at(app, HEX_AT, FIRST_ROW)
    click_at(app, HEX_AT, FIRST_ROW)
    check("clicking the dump takes the caret back",
          where(app).startswith("Offset " + offsets(app)[0]), where(app))

    # 12. The window resizes in one direction and not the other.
    #
    #     Two halves, and both have to be there. `Grows` on the canvas is what
    #     makes it taller -- Turbo Vision does that arithmetic in
    #     `TGroup::changeBounds` -- and the `WindowResized` event is what tells
    #     the model how many rows it now has. Without the first it is sixteen
    #     rows of dump in a taller window; without the second it is a taller
    #     canvas with sixteen rows of dump in it and blank space below.
    #
    #     Ctrl-F5 is the Window menu's Resize/move, and shifted arrows are how
    #     `TView::dragView` resizes rather than moves. Shift-Left is the one
    #     that matters here: the window already spans the terminal, so widening
    #     is the desktop's limit rather than the window's, and narrowing is the
    #     thing `resize = Tui.resizeHeight` has to refuse.
    go_to(app, "0")
    width = frame_width(app)
    resize(app, b"\x1b[1;2A" * 5)
    check("the dump shrank with the window", dump_rows(app) == 11, dump_rows(app))
    check("and the lines that describe the byte came with it",
          find_row(app, "Offset 00000000") == 3 + 11 + 1,
          find_row(app, "Offset 00000000"))

    app.send(b"\x1b[6~", settle=0.9)
    check("a page is now eleven rows and not sixteen",
          first_offset(app) == "000000B0", first_offset(app))

    resize(app, b"\x1b[1;2D" * 3)
    check("the window refuses to be made narrower", frame_width(app) == width,
          f"{frame_width(app)} != {width}")

    resize(app, b"\x1b[1;2B" * 5)
    check("and grows back to sixteen rows", dump_rows(app) == 16, dump_rows(app))
    go_to(app, "0")

    # 13. Highlighting, which is vim's visual mode with sixteen bytes to a
    #     row: `v` marks, the *cursor* is the far end of the mark, and one of
    #     `1`-`6` paints what is marked. The colours are Borland's -- the
    #     marker on 104, red on 41, green on 42 -- because this driver runs
    #     with an empty HOME and that is the scheme predc opens in.
    app.send(b"4", settle=0.6)
    check("a colour with nothing marked says what is missing",
          "Nothing is marked" in status(app), status(app))

    app.send(b"v", settle=0.6)
    check("v starts a mark, and the mark is one byte long",
          status(app).startswith("MARK") and "1 byte " in status(app), status(app))
    check("and the way out of the mode stays on the screen while the mode is",
          "Esc cancel" in status(app), status(app))

    app.send(b"\x1b[C" * 3, settle=0.7)
    check("the arrows move the far end", "4 bytes" in status(app), status(app))
    display = app.display()
    check("the marked bytes are painted in both columns",
          display.bg_at(HEX_AT, FIRST_ROW) == 104
          and display.bg_at(ASCII_AT, FIRST_ROW) == 104,
          f"hex={display.bg_at(HEX_AT, FIRST_ROW)} "
          f"ascii={display.bg_at(ASCII_AT, FIRST_ROW)}")
    check("and the cursor shows through the mark, so the mode cannot lose it",
          display.bg_at(HEX_AT + 9, FIRST_ROW) == 47,
          str(display.bg_at(HEX_AT + 9, FIRST_ROW)))

    #     The six keys are drawn wearing what they paint, which is the only
    #     way a line can answer "which one is yellow". Reading the colours off
    #     the digits is also the only assertion that could tell this legend
    #     from the words it replaced.
    legend = line_at(app, STATUS_ROW).find("1  2  3  4  5  6")
    swatches = ([display.bg_at(legend + 3 * i, STATUS_ROW) for i in range(6)]
                if legend > 0 else [])
    check("the legend paints the number keys rather than naming a range of them",
          swatches == [41, 42, 43, 45, 46, 100], f"at {legend}: {swatches}")

    app.send(b"1", settle=0.6)
    display = app.display()
    check("a number paints the mark and ends the mode",
          not status(app).startswith("MARK"), status(app))
    check("the range keeps its colour in both columns",
          display.bg_at(HEX_AT, FIRST_ROW) == 41
          and display.bg_at(ASCII_AT, FIRST_ROW) == 41,
          f"hex={display.bg_at(HEX_AT, FIRST_ROW)} "
          f"ascii={display.bg_at(ASCII_AT, FIRST_ROW)}")
    check("and the line under the dump names the colour the byte is wearing",
          "Red" in status(app), status(app))

    app.send(b"\x1b[C", settle=0.6)
    check("the byte the cursor moved off is painted too, now nothing covers it",
          app.display().bg_at(HEX_AT + 9, FIRST_ROW) == 41,
          str(app.display().bg_at(HEX_AT + 9, FIRST_ROW)))
    check("and a byte outside the range wears nothing",
          "Red" not in status(app), status(app))

    #     `V` is the same mark snapped out to whole rows, which is the shape a
    #     hex dump is actually read in.
    app.send(b"\x1b[B", settle=0.6)
    app.send(b"V", settle=0.6)
    check("V marks the whole row the cursor is on",
          status(app).startswith("MARK ROWS") and "16 bytes" in status(app), status(app))
    app.send(b"\x1b[B", settle=0.6)
    check("and grows a row at a time", "32 bytes" in status(app), status(app))
    app.send(b"2", settle=0.6)
    display = app.display()
    check("both rows are painted end to end",
          display.bg_at(HEX_AT, FIRST_ROW + 1) == 42
          and display.bg_at(ASCII_AT + 15, FIRST_ROW + 2) == 42,
          f"first={display.bg_at(HEX_AT, FIRST_ROW + 1)} "
          f"last={display.bg_at(ASCII_AT + 15, FIRST_ROW + 2)}")
    check("and the offset column is not: it is the ruler, not the data",
          display.bg_at(LEFT, FIRST_ROW + 1) != 42,
          str(display.bg_at(LEFT, FIRST_ROW + 1)))

    #     The mouse moves the far end as well, and that is not a feature that
    #     was written: a click moves the cursor, and the cursor *is* the far
    #     end of the mark.
    app.send(b"\x1b[1;5H", settle=0.7)
    check("Ctrl-Home is the top of the file", where(app).startswith("Offset 00000000"),
          where(app))
    app.send(b"v", settle=0.6)
    click_at(app, ASCII_AT + 5, FIRST_ROW)
    check("a click while marking extends the mark rather than ending it",
          "6 bytes" in status(app), status(app))

    app.send(b"\x1b", settle=0.6)
    check("Esc drops the mark", "MARK" not in status(app), status(app))
    check("and paints nothing",
          app.display().bg_at(HEX_AT + 15, FIRST_ROW) not in (104, 41, 42),
          str(app.display().bg_at(HEX_AT + 15, FIRST_ROW)))

    app.send(b"\x1b[H", settle=0.6)
    check("Home is back inside the first range", "Red" in status(app), status(app))
    app.send(b"d", settle=0.6)
    check("d takes the paint off the range under the cursor",
          "Red" not in status(app), status(app))
    check("and the bytes go back to plain",
          app.display().bg_at(HEX_AT + 3, FIRST_ROW) not in (41, 104),
          str(app.display().bg_at(HEX_AT + 3, FIRST_ROW)))
    check("while the range it was not asked about is untouched",
          app.display().bg_at(HEX_AT, FIRST_ROW + 1) == 42,
          str(app.display().bg_at(HEX_AT, FIRST_ROW + 1)))

    #     An offset means nothing in another file, so loading one drops them.
    #     Loading the *same* one again is the same thing and easier to assert.
    open_file(app, os.path.join(work, "sample.bin"))
    check("opening a file drops every highlight in the old one",
          app.display().bg_at(HEX_AT, FIRST_ROW + 1) != 42,
          str(app.display().bg_at(HEX_AT, FIRST_ROW + 1)))

    #     The menu is the other half of it. It names every key and binds none
    #     of them -- the canvas has focus and eats plain letters, so a `v`
    #     bound here would take the letter away from the thing it is for --
    #     and both ends run the same four functions.
    bytes_menu(app, b"h")
    screen = app.render()
    check("the Highlight submenu lists the colours and the keys that pick them",
          "Green" in screen and "Mark from here" in screen, screen)
    app.send(b"m", settle=0.7)
    check("Mark from here starts the same mark v does",
          status(app).startswith("MARK"), status(app))
    app.send(b"\x1b[C" * 2, settle=0.6)
    bytes_menu(app, b"h3", settle=1.0)
    check("and a colour off the menu paints it",
          app.display().bg_at(HEX_AT, FIRST_ROW) == 43,
          str(app.display().bg_at(HEX_AT, FIRST_ROW)))
    bytes_menu(app, b"hc", settle=1.0)
    check("Clear all takes every highlight off",
          app.display().bg_at(HEX_AT, FIRST_ROW) != 43,
          str(app.display().bg_at(HEX_AT, FIRST_ROW)))

    # 14. Yanking, which is the first thing in predc that speaks to another
    #     program at all. With no display in the environment the clipboard is
    #     the terminal's, and the terminal is this driver -- so what predc
    #     copied is on the wire, base64'd into an `OSC 52`, and can be read
    #     back and compared with the bytes it was looking at.
    app.send(b"\x1b[1;5H", settle=0.6)              # Ctrl-Home
    app.send(b"v", settle=0.5)
    app.send(b"\x1b[C" * 3, settle=0.7)
    mark = len(app.buf)
    app.send(b"y", settle=0.9)
    check("y copies the marked bytes as hex", copied(app, mark) == "00 01 02 03",
          repr(copied(app, mark)))
    check("and the line under the dump says what it did",
          "Copied 4 bytes as hex" in status(app), status(app))
    check("and says the terminal did not confirm it -- which is the true "
          "statement, since the OSC 52 above went out regardless",
          "did not confirm" in status(app), status(app))
    check("and the mark is spent, the way vim spends one",
          "MARK" not in status(app), status(app))

    #     With nothing marked it takes the highlight under the cursor, which
    #     is what makes a highlight worth more than its colour: mark it once,
    #     and it is a range to come back to.
    app.send(b"\x1b[1;5H", settle=0.6)              # Ctrl-Home
    app.send(b"v", settle=0.5)
    app.send(b"\x1b[C", settle=0.5)
    app.send(b"1", settle=0.7)
    mark = len(app.buf)
    app.send(b"y", settle=0.9)
    check("with nothing marked, y takes the highlight the cursor is in",
          copied(app, mark) == "00 01", repr(copied(app, mark)))

    #     A dump is rows, so copying one takes whole rows however the range
    #     was made -- and the printable column is full stops, because what is
    #     on the other end of a clipboard may be ASCII only.
    mark = len(app.buf)
    bytes_menu(app, b"d", settle=1.0)
    check("Copy as a dump takes the whole row the highlight is on",
          copied(app, mark) ==
          "00000000  00 01 02 03 04 05 06 07  08 09 0A 0B 0C 0D 0E 0F  " + "." * 16,
          repr(copied(app, mark)))

    #     A terminal that says it can do OSC 52 properly changes the sentence,
    #     because now something else did take it. `ESC]60;allowWindowOps` is
    #     what TVision reads as that claim.
    app.send(b"\x1b]60;allowWindowOps\x07", settle=0.6)
    app.send(b"y", settle=0.9)
    check("and with a terminal that takes it, the caveat goes away",
          "Copied" in status(app) and "did not confirm" not in status(app),
          status(app))

    #     And the one thing a viewer that never holds its file cannot do.
    app.send(b"V", settle=0.6)
    app.send(b"\x1b[1;5F", settle=1.2)              # Ctrl-End
    app.send(b"y", settle=0.9)
    check("a mark bigger than the chunk is refused, and says by how much",
          "40960 bytes" in status(app) and "16384" in status(app), status(app))
    app.send(b"\x1b", settle=0.5)
    bytes_menu(app, b"hc", settle=1.0)

    # 15. Pasting, which is the other half of the clipboard and the second way
    #     of getting something to look at. The driver has claimed OSC 52
    #     support by now, so the clipboard is the terminal's -- and the
    #     terminal is this file, which can put whatever it likes on it.
    asked = paste(app, "Hello, hex!")
    check("p asks the clipboard for text", asked)
    check("and what comes back is shown as its bytes",
          rows(app)[0].startswith("00000000  48 65 6C 6C 6F 2C 20 68  65 78 21"), rows(app)[0])
    check("with the printable column to match",
          rows(app)[0].rstrip().endswith("Hello, hex!"), rows(app)[0])
    check("the title says what it is looking at and how big it is",
          "pasted text" in line_at(app, 1) and "(11 bytes)" in line_at(app, 1),
          line_at(app, 1))
    check("and the rows past the end of it are blank",
          rows(app)[1].strip() == "", repr(rows(app)[1]))

    #     The same text read the other way. Two commands and no sniffing:
    #     `beef` and `cafe` and `decade` are words as well as hex, so a program
    #     that guesses is a program that is silently wrong about what it shows.
    paste(app, "de ad be ef", key=b"P")
    check("P reads the clipboard as hex digits rather than as characters",
          rows(app)[0].startswith("00000000  DE AD BE EF"), rows(app)[0])
    check("and says so in the title",
          "pasted hex" in line_at(app, 1) and "(4 bytes)" in line_at(app, 1),
          line_at(app, 1))

    #     Separators are whatever produced the text felt like using.
    paste(app, "0x48,0x69", key=b"P")
    check("commas and 0x are separators, not data",
          rows(app)[0].startswith("00000000  48 69") and "(2 bytes)" in line_at(app, 1),
          rows(app)[0])

    #     And what it will not do, which is the interesting half: a dump with
    #     its offsets and its printable column still on it is *nearly* hex, and
    #     keeping the hex and dropping the rest would read both columns as
    #     data. It refuses and says which character stopped it.
    paste(app, "00000000  48 65 6C 6C  Hell", key=b"P")
    check("a dump pasted as hex is refused rather than half read",
          "not a hex digit" in status(app), status(app))
    check("and what was on the screen is still on the screen",
          "(2 bytes)" in line_at(app, 1), line_at(app, 1))

    paste(app, "abc", key=b"P")
    check("an odd number of digits is refused too, with the count",
          "3 hex digits" in status(app), status(app))

    paste(app, "")
    check("and an empty clipboard says that instead of showing nothing",
          "nothing on the clipboard" in status(app), status(app))

    # 16. A file smaller than the window, and one with nothing in it at all.
    #
    #     Opened with a double click on its name rather than by typing it,
    #     which is the `chooses` field on the dialog's list box: committing an
    #     entry sends the command the first button carries, so the dialog ends
    #     with `ok` and the model reads the row out of `values` exactly as it
    #     does when OK is pressed. Nothing in predc knows a double click
    #     happened, and that is the point of doing it that way.
    double_click_in_list(app, "small.bin")
    check("a small file is one row", rows(app)[0].startswith("00000000  48 65 6C 6C 6F"),
          rows(app)[0])
    check("and the rows past the end of it are blank",
          rows(app)[1].strip() == "", repr(rows(app)[1]))
    check("its name and size are in the title",
          "small.bin" in line_at(app, 1) and "(11 bytes)" in line_at(app, 1),
          line_at(app, 1))
    app.send(b"\x1b[F", settle=0.7)
    check("End goes to the end of the row, and no further than the file",
          where(app).startswith("Offset 0000000A (10)"), where(app))

    open_file(app, os.path.join(work, "empty.bin"))
    check("an empty file says so rather than looking broken",
          "empty" in status(app).lower(), status(app))
    check("and draws no rows at all", all(row.strip() == "" for row in rows(app)),
          repr(rows(app)[0]))

    # 17. It is a window like any other: closing it forgets it, and the menu
    #     it brought with it goes too.
    app.send(ALT_F3, settle=1.2)
    check("Alt-F3 closed the window", "Hex Dump" not in app.render(), app.render())
    check("and its menu left the bar with it",
          "Bytes" not in app.render().split("\n")[0], app.render().split("\n")[0])
    app.send(b"\x1bd", settle=1.0)
    check("reopening starts fresh", "Nothing open" in app.render(), app.render())
    check("and says the two ways of giving it something",
          "Open file" in app.render() and "paste" in app.render(), app.render())

    #     Which is the case a paste has to work in: it is one of the two ways
    #     of opening something, so it cannot be a thing you can only do to a
    #     file that is already open.
    paste(app, "hi")
    check("a paste with nothing open opens something",
          rows(app)[0].startswith("00000000  68 69"), rows(app)[0])

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("Alt-X exits, and cleanly", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
