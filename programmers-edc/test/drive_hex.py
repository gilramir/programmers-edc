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

Marking, yanking and pasting are `drive_hex_marks.py`, `drive_hex_yank.py` and
`drive_hex_paste.py` -- see `hex_common.py` for why they are four files. This
one keeps the `p`-before-anything-was-copied check, because it is the driver
that never copies anything.
"""

import os
import sys

from hex_common import (
    ALT_F3, ASCII_AT, Checks, FIRST_ROW, HEX_AT, ROWS, SCROLL_AT, allow_osc52,
    bytes_menu, click_at, double_click_in_list, dump_rows, find_row,
    first_offset, fixtures, frame_width, go_to, launch, line_at, offsets,
    open_file, paste, resize, rows, status, where,
)


def main():
    check = Checks()
    work = fixtures()
    app = launch(work)

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

    #    `p` here, before this driver has claimed a terminal that answers an
    #    `OSC 52` read query and before anything has been copied -- which
    #    together are the state a real ssh session is permanently in. Nothing
    #    was asked: the helper programs are skipped for want of a `DISPLAY`,
    #    and the query is not written unless the terminal proved it answers
    #    one, which tmux never does. So the sentence has to name the terminal
    #    rather than the clipboard, because those two send somebody to
    #    different places and only one of them helps.
    #
    #    It has to be *here* and not later: the fallback is this program's own
    #    last copy, so after any check that copies something, `p` succeeds.
    app.send(b"p", settle=1.2)
    check("with no terminal willing to answer, p blames the terminal and not "
          "the clipboard",
          "will not hand the clipboard over" in status(app), status(app))
    check("and points at the one way in that needs no clipboard at all",
          "Type bytes" in status(app), status(app))

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


    #     Everything above ran with a terminal that had claimed nothing, which
    #     is what the `p` check at the top is about. From here on it has, so
    #     that the paste at the end of the next section can be answered.
    allow_osc52(app)

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
