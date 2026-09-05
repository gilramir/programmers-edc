#!/usr/bin/env python3
"""predc's hex viewer: yanking, the first thing in predc that speaks to another
program at all.

With no display in the environment the clipboard is the terminal's, and the
terminal is this driver -- so what predc copied is on the wire, base64'd into
an `OSC 52`, and can be read back and compared with the bytes it was looking
at.

This driver deliberately does **not** call `allow_osc52` in its setup: the
first checks below are about the sentence predc prints when nothing has
confirmed the copy, which is the true statement over ssh. The claim is sent
part-way through, by the check that is about the claim.

The megabyte is here too, which is why this is the one driver that asks
`fixtures` for `big.bin`. `forget_copies` drops the payloads out of the replay
buffer once they have been read -- four megabytes of base64 that `display()`
would otherwise replay on every check after them.

Split out of `drive_hex.py`; see `hex_common.py` for why.
"""

import sys

from hex_common import (
    Checks, SIZE, bytes_menu, copied, fixtures, forget_copies, launch,
    open_file, open_viewer, status,
)


def main():
    check = Checks()
    work = fixtures(big=True)
    app = launch(work)
    open_viewer(app)
    open_file(app, "sample.bin")

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

    #     A mark bigger than the 16 KB chunk, which this used to refuse with
    #     the size of the chunk in the message -- a sentence about predc's
    #     insides rather than about the file. It reads the range for the
    #     purpose now, so the whole forty kilobytes come back, and the check
    #     is arithmetic: the fixture's byte at offset n is n % 256, so the
    #     text is 40960 pairs beginning 00 01 02 and ending FF.
    app.send(b"V", settle=0.6)
    app.send(b"\x1b[1;5F", settle=1.2)              # Ctrl-End
    mark = len(app.buf)
    app.send(b"y", settle=2.5)
    took = copied(app, mark)
    check("a mark bigger than the chunk is read from the file and copied whole",
          len(took) == SIZE * 3 - 1, f"{len(took)} chars, wanted {SIZE * 3 - 1}")
    check("and it is the right bytes at both ends of it",
          took.startswith("00 01 02 03") and took.endswith("FD FE FF"),
          repr(took[:11] + " ... " + took[-11:]))
    check("with no question asked, because forty kilobytes is not worth one",
          "Copied 40960 bytes as hex" in status(app), status(app))
    forget_copies(app)

    #     Past a megabyte it asks, with the two numbers that make it a
    #     question: the range in bytes, and what that turns into as text.
    #     `big.bin` is one byte over the line on purpose.
    open_file(app, "big.bin", settle=2.0)
    app.send(b"V", settle=0.6)
    app.send(b"\x1b[1;5F", settle=1.5)              # Ctrl-End
    app.send(b"y", settle=1.2)
    screen = app.render()
    check("a copy past a megabyte asks first", "Copy it?" in screen, screen)
    check("and the question carries the size of the range",
          "1048577 bytes" in screen, screen)
    check("and what it becomes as text, which is the number nobody has in "
          "their head", "3 MB of text" in screen, screen)

    #     No is not a refusal: the mark is still out, so the answer to "that
    #     is more than I meant" is to shrink it rather than to make it again.
    mark = len(app.buf)
    app.send(b"\x1bn", settle=1.2)
    check("No copies nothing", copied(app, mark) == "", repr(copied(app, mark)))
    check("and leaves the mark where it was",
          "MARK" in status(app), status(app))

    app.send(b"y", settle=1.2)
    app.send(b"\x1by", settle=6.0)
    check("Yes copies the whole megabyte",
          "Copied 1048577 bytes as hex" in status(app), status(app))
    forget_copies(app)
    app.send(b"\x1b", settle=0.5)

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
