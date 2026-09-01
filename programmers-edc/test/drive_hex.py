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

One check here is about the *package* rather than this tool. A modal dialog is
supposed to open with the caret on the first view in it that can hold one, and
does not -- `Tui.fileDialog` opens with its list focused, so typing a path does
nothing. `Tool.Hex` sends a `Tui.focus` of its own right after the dialog, and
"the Name field takes what is typed at it" is what says the workaround is still
needed. When the binding is fixed the line can go and this check stays green.
"""

import os
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


def menu(app, item, entry):
    """Open a pull-down by clicking its name, then click the `entry`-th line in
    it (1-based). Row 0 is the menu bar and row 1 is the box's own border."""
    bar = app.render().split("\n")[0]
    at = bar.index(item)
    app.click(at + 1, 1, settle=0.6)
    app.click(at + 3, entry + 2, settle=0.9)


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
    menu(app, "Bytes", 1)
    app.send(name.encode(), settle=0.8)
    app.send(b"\r", settle=settle)


def go_to(app, text, settle=1.4):
    menu(app, "Bytes", 2)
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

    env = dict(os.environ, TERM="xterm-256color")
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
    menu(app, "Bytes", 1)
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
          display.bg_at(HEX_AT + 3, FIRST_ROW + 1) == 44
          and display.fg_at(HEX_AT + 3, FIRST_ROW + 1) == 97,
          f"fg={display.fg_at(HEX_AT + 3, FIRST_ROW + 1)} "
          f"bg={display.bg_at(HEX_AT + 3, FIRST_ROW + 1)}")
    check("and so is its half of the printable column",
          display.bg_at(ASCII_AT + 1, FIRST_ROW + 1) == 44,
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
    menu(app, "Bytes", 5)
    check("End of file goes to the last byte",
          where(app).startswith("Offset 00009FFF (40959)"), where(app))
    check("and the bytes there are read, not guessed",
          rows(app)[ROWS - 1].startswith("00009FF0  F0 F1 F2 F3 F4 F5 F6 F7  F8 F9 FA FB FC FD FE FF"),
          rows(app)[ROWS - 1])
    check("the last row is the bottom row: nothing is scrolled past the end",
          offsets(app)[ROWS - 1] == "00009FF0", str(offsets(app)[-2:]))
    menu(app, "Bytes", 4)
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

    # 11. The scroll bar. Two clicks and not one: the first is spent taking
    #     the caret off the canvas, which is TView's rule for any focusable
    #     view and not something about scroll bars.
    go_to(app, "0")
    click_at(app, SCROLL_AT, FIRST_ROW + ROWS - 1)
    click_at(app, SCROLL_AT, FIRST_ROW + ROWS - 1)
    check("the scroll bar scrolls the dump", offsets(app)[0] == "00000010",
          str(offsets(app)[:2]))
    check("and drags the cursor along, so the lines below still describe "
          "something on screen",
          where(app).startswith("Offset 00000010 (16)"), where(app))

    # ...and the caret has to be taken back off it the same way, which is why
    # the keys below work again.
    click_at(app, HEX_AT, FIRST_ROW)
    click_at(app, HEX_AT, FIRST_ROW)
    check("clicking the dump takes the caret back",
          where(app).startswith("Offset 00000010 (16)"), where(app))

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

    # 13. A file smaller than the window, and one with nothing in it at all.
    open_file(app, os.path.join(work, "small.bin"))
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

    # 14. It is a window like any other: closing it forgets it, and the menu
    #     it brought with it goes too.
    app.send(ALT_F3, settle=1.2)
    check("Alt-F3 closed the window", "Hex Dump" not in app.render(), app.render())
    check("and its menu left the bar with it",
          "Bytes" not in app.render().split("\n")[0], app.render().split("\n")[0])
    app.send(b"\x1bd", settle=1.0)
    check("reopening starts fresh", "Nothing open" in app.render(), app.render())

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("Alt-X exits, and cleanly", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
