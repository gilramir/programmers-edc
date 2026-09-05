#!/usr/bin/env python3
"""predc's hex viewer: highlighting, which is vim's visual mode with sixteen
bytes to a row.

`v` marks, the *cursor* is the far end of the mark, and one of `1`-`6` paints
what is marked. The colours are Borland's -- the marker on 104, red on 41,
green on 42 -- because this driver runs with an empty HOME and that is the
scheme predc opens in.

Three things here are about Turbo Vision rather than about predc, and they are
the ones worth the length. A drag has to start a mark without breaking a plain
click, which is why the mark begins on the first *motion* and not on the press.
The first click on a canvas that is not its window's selected view is spent
putting the selection back, so a drag begun with that click marks nothing --
reachable only because the window has a scroll bar in it, which is a second
thing to point at. And the menu names every key and binds none of them,
because the canvas has focus and eats plain letters.

Split out of `drive_hex.py`; see `hex_common.py` for why.
"""

import os
import sys

from hex_common import (
    ASCII_AT, Checks, FIRST_ROW, HEX_AT, LEFT, SCROLL_AT, STATUS_ROW,
    bytes_menu, click_at, drag_over, fixtures, go_to, launch, line_at,
    open_file, open_viewer, status, where,
)


def main():
    check = Checks()
    work = fixtures()
    app = launch(work)
    open_viewer(app)
    open_file(app, "sample.bin")
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

    #     And the mouse can draw the mark as well as move its far end. The
    #     press is an ordinary click and starts nothing -- clicking to move
    #     the cursor has to go on working -- so it is the first cell the
    #     pointer crosses that turns it into a mark, anchored where the press
    #     landed. Byte 2 of the first row to byte 6 of the second is
    #     22 - 2 + 1 = 21 bytes.
    drag_over(app, [(HEX_AT + 6, FIRST_ROW),
                    (HEX_AT + 12, FIRST_ROW),
                    (HEX_AT + 18, FIRST_ROW + 1)])
    check("dragging starts a mark that was never asked for with v",
          status(app).startswith("MARK") and "21 bytes" in status(app), status(app))
    check("and the legend comes with it, because the mark is the same mark",
          "1  2  3  4  5  6" in status(app), status(app))

    app.send(b"3", settle=0.7)
    display = app.display()
    # Byte 5 of the second row and not byte 6, which is where the drag stopped
    # and is therefore wearing the cursor: the cursor shows *through* a colour,
    # which is checked further up and is the reason a mark cannot be lost.
    check("a colour paints what the mouse drew, on both rows it crossed",
          display.bg_at(HEX_AT + 6, FIRST_ROW) == 43
          and display.bg_at(HEX_AT + 15, FIRST_ROW + 1) == 43,
          f"start={display.bg_at(HEX_AT + 6, FIRST_ROW)} "
          f"end={display.bg_at(HEX_AT + 15, FIRST_ROW + 1)}")
    check("and stops where the press was, not at the start of the row",
          display.bg_at(HEX_AT, FIRST_ROW) != 43,
          str(display.bg_at(HEX_AT, FIRST_ROW)))

    #     The drag has to leave a plain click alone, which is the whole reason
    #     the mark begins on the first motion rather than on the press.
    click_at(app, HEX_AT + 30, FIRST_ROW + 3)
    check("a click after all that is still just a click",
          "MARK" not in status(app), status(app))
    app.send(b"d", settle=0.6)
    go_to(app, "0")
    app.send(b"d", settle=0.6)

    #     The first click on a canvas that is not its window's selected view is
    #     spent putting the selection back on it, and does not reach the model.
    #     That is Turbo Vision's `TView::handleEvent` and it is a decision to
    #     keep it: a window with a scroll bar in it has two things the user can
    #     be pointing at, and a click that both moved the selection and acted
    #     would act on a view the user had not been looking at.
    #
    #     The bar is what makes this reachable. With one selectable view in the
    #     window the canvas is always the selected one, so the case never
    #     arises -- which is why it went unnoticed until a drag needed the
    #     press.
    go_to(app, "0")
    click_at(app, HEX_AT + 6, FIRST_ROW + 2)
    moved = where(app)
    check("a click reaches the canvas while it holds the selection",
          "00000022" in moved, moved)

    click_at(app, SCROLL_AT, FIRST_ROW)
    parked = where(app)
    click_at(app, HEX_AT + 12, FIRST_ROW + 5)
    check("and the first one back from the scroll bar is spent on the selection",
          where(app) == parked, f"{where(app)} != {parked}")
    click_at(app, HEX_AT + 12, FIRST_ROW + 5)
    check("while the second one does what a click does",
          where(app) != parked, where(app))

    #     Which means a drag begun with that click is a selection and not a
    #     drag: the press is what creates the capture, and this press never
    #     happened as far as the model is concerned.
    click_at(app, SCROLL_AT, FIRST_ROW)
    before = where(app)
    drag_over(app, [(HEX_AT + 6, FIRST_ROW + 1),
                    (HEX_AT + 12, FIRST_ROW + 1),
                    (HEX_AT + 18, FIRST_ROW + 2)])
    check("a drag begun with the focusing click marks nothing",
          "MARK" not in status(app), status(app))
    check("and moves nothing either",
          where(app) == before, f"{where(app)} != {before}")

    #     Hand the canvas back before going on, which takes two clicks and not
    #     one -- as the checks above have just finished proving. The
    #     sections below type at it and read the top row, so both the selection
    #     and the offset have to go back where they were found.
    click_at(app, HEX_AT, FIRST_ROW)
    click_at(app, HEX_AT, FIRST_ROW)
    go_to(app, "0")

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


    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
