#!/usr/bin/env python3
"""predc's hex viewer: pasting, the other half of the clipboard and the second
way of getting something to look at.

Three commands and no sniffing, which is the discipline the whole section is
about: `beef` and `cafe` and `decade` are words as well as hex, so a program
that guesses is a program that is silently wrong about what it shows. `p` reads
the clipboard as text, `P` as hex digits, and Paste a dump reads a dump -- and
a dump carries its own offsets, so the gap between two of them says exactly how
many bytes the first one held and nothing has to guess where the hex column
stops. The four refusals matter as much as the four formats: a buffer that is
wrong in a way nobody can see is the one thing this must never produce.

Typing bytes is here as well, because it is the same two readings reached
without a clipboard -- and over ssh it is the only one that works.

`allow_osc52` is in the setup because nothing here can be pasted without it.

Split out of `drive_hex.py`; see `hex_common.py` for why.
"""

import sys

from hex_common import (
    Checks, allow_osc52, bytes_menu, copied, fixtures, launch, line_at,
    open_file, open_viewer, paste, paste_dump, rows, status, type_bytes,
)


def main():
    check = Checks()
    work = fixtures()
    app = launch(work)
    open_viewer(app)
    open_file(app, "sample.bin")
    allow_osc52(app)

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

    # 15b. Which is what the third command is for. A dump carries its own
    #      offsets, and the gap between two of them is exactly how many bytes
    #      the first one held -- so nothing has to guess where the hex column
    #      stops and the printable one starts. These are the four formats
    #      somebody actually has on their clipboard.
    check("Paste a dump asks the clipboard too",
          paste_dump(app, "00000000: 4865 6c6c 6f2c 2068 6578 2120 4865 6c6c  Hello, hex! Hell\n"
                          "00000010: 6f2c 2068 6578 210a                      o, hex!.\n"))
    check("an xxd dump is read as the bytes it shows",
          rows(app)[0].startswith("00000000  48 65 6C 6C 6F 2C 20 68  65 78 21 20 48 65 6C 6C"),
          rows(app)[0])
    check("and the title says which of the three pastes made it",
          "pasted dump" in line_at(app, 1) and "(24 bytes)" in line_at(app, 1),
          line_at(app, 1))
    check("and the offsets it had are said once, since the buffer starts at 0",
          "00000000-00000017" in status(app), status(app))

    paste_dump(app, "00000000  48 65 6c 6c 6f 2c 20 68  65 78 21 20 48 65 6c 6c  |Hello, hex! Hell|\n"
                    "00000010  6f 2c 20 68 65 78 21 0a                           |o, hex!.|\n"
                    "00000018\n")
    check("hexdump -C is read too, fences and trailing offset and all",
          "(24 bytes)" in line_at(app, 1) and
          rows(app)[1].startswith("00000010  6F 2C 20 68 65 78 21 0A"),
          line_at(app, 1) + " / " + rows(app)[1])

    paste_dump(app, "000000 48 65 6c 6c 6f 2c 20 68 65 78 21 20 62 65 65 66  >Hello, hex! beef<\n"
                    "000010 6f 2c 20 62 65 65 66 0a  >o, beef.<\n")
    check("od -A x -t x1z too, whose last line is not padded at all",
          "(24 bytes)" in line_at(app, 1), line_at(app, 1))

    #      Which is the check that matters, because `beef` is a word and a
    #      number both, and it is sitting in the printable column of the line
    #      above. A rule about two spaces, or about what looks like hex, reads
    #      it as data; the offsets do not.
    check("and the beef in its printable column is not read as four bytes -- "
          "which would have made it twenty-eight",
          rows(app)[1].startswith("00000010  6F 2C 20 62 65 65 66 0A") and
          rows(app)[1][10:58].strip().endswith("0A"),
          rows(app)[1])

    #      A `*` is `hexdump`'s way of writing "and so on", and the offsets on
    #      either side of it say exactly how many rows it stands for -- so it
    #      is expanded rather than refused. Sixteen bytes, thirty-two more the
    #      star stands for, sixteen, four: sixty-eight.
    paste_dump(app, "00000000  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00  ................\n"
                    "*\n"
                    "00000030  01 02 03 04 05 06 07 08  09 0a 0b 0c 0d 0e 0f 10  ................\n"
                    "00000040  11 12 13 14                                       ....\n")
    check("a * is expanded, because the offsets say how many rows it is",
          "(68 bytes)" in line_at(app, 1), line_at(app, 1))
    check("and what it stood for is the row above it, written out again",
          rows(app)[1].startswith("00000010  00 00 00 00"), rows(app)[1])

    #      And the four refusals, which are the same discipline as `P`'s: a
    #      buffer that is wrong in a way nobody can see is the one thing this
    #      must never produce.
    paste_dump(app, "00000000  62 65 65 66                                       beef\n")
    check("one line of a dump is refused, because one offset is not two",
          "One line is not enough" in status(app), status(app))

    paste_dump(app, "00000000  48 65 6c 6c 6f 2c 20 68  65 78 21 20 48 65 6c 6c  Hello, hex! Hell\n"
                    "00000030  6f 2c 20 68 65 78 21 0a                           o, hex!.\n")
    check("a dump with a hole in it is refused, and says where the hole is",
          "skips from 00000010 to 00000030" in status(app), status(app))

    paste_dump(app, "00000000  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00  ................\n"
                    "*\n00001000\n")
    check("a dump that is nothing but a * says what it cannot know",
          "how wide a row is" in status(app), status(app))

    paste_dump(app, "48 65 6c 6c 6f\n2c 20 68 65 78\n")
    check("and bare hex is refused by the command that wants offsets, which "
          "is the other half of P refusing a dump",
          "not a dump" in status(app), status(app))

    #      The round trip, which is the check the other twelve are for: what
    #      Copy as a dump puts on the clipboard is what Paste a dump reads
    #      back. Three rows of the sample file, whose byte at offset n is
    #      n % 256, out and in again.
    open_file(app, "sample.bin", settle=1.8)
    app.send(b"V", settle=0.5)
    app.send(b"\x1b[B" * 2, settle=0.7)
    mark = len(app.buf)
    bytes_menu(app, b"d", settle=1.2)
    ours = copied(app, mark)
    check("Copy as a dump gave three whole rows", ours.count("\n") == 2, repr(ours))
    paste_dump(app, ours)
    check("and predc reads its own dump back, which is the round trip",
          "(48 bytes)" in line_at(app, 1) and
          rows(app)[2].startswith("00000020  20 21 22 23"),
          line_at(app, 1) + " / " + rows(app)[2])

    paste(app, "")
    check("and an empty clipboard says that instead of showing nothing",
          "nothing on the clipboard" in status(app), status(app))

    # 15b. Bytes typed rather than pasted, which is the same two readings
    #      reached without a clipboard. It matters because over ssh the three
    #      entries above cannot work: no `DISPLAY` means the helper programs
    #      are skipped, and Turbo Vision will not even write the `OSC 52` read
    #      query unless the terminal has proved it answers one, which tmux
    #      never does. Keystrokes always arrive.
    type_bytes(app, "Hello")
    check("Type bytes reads what was typed as text",
          rows(app)[0].startswith("00000000  48 65 6C 6C 6F") and
          "typed text" in line_at(app, 1),
          rows(app)[0] + " / " + line_at(app, 1))
    type_bytes(app, "de ad be ef", hexdigits=True)
    check("and as hex digits when the radio says so",
          rows(app)[0].startswith("00000000  DE AD BE EF") and
          "typed hex" in line_at(app, 1),
          rows(app)[0] + " / " + line_at(app, 1))
    check("which is the difference the radio exists for: those are letters too",
          "(4 bytes)" in line_at(app, 1), line_at(app, 1))
    type_bytes(app, "beefz", hexdigits=True)
    check("and a stray character is refused in the same words P refuses it in",
          "not a hex digit" in status(app), status(app))
    type_bytes(app, "")
    check("an empty field is not a paste of nothing, and says so",
          "Nothing was typed" in status(app), status(app))


    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
