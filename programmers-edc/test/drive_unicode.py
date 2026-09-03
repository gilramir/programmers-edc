#!/usr/bin/env python3
"""predc's Unicode decoder: the characters, and the things that are wrong.

Two suites' worth of interest in one file. The first is ordinary: bytes go in,
characters come out, and three encodings read the same bytes three ways.

The second is the reason the tool exists. Every decoder on the machine will
read `C0 80` for you and answer `U+FFFD`; almost none will say it is an
overlong encoding of `U+0000`, which is the oldest way there is past a filter
looking for a literal zero byte. So the checks that matter here are the ones
about `Broken`: the overlong, the surrogate in UTF-8, the lead byte whose
continuations ran out, and the lone surrogate in UTF-16.

**This is also the first driver in the repo that reads a wide character.**
`harness.py`'s `Screen._put` advanced exactly one column per character until
2026-09-02, so `한` slid every column after it one place left and no assertion
about them could hold. It counts East Asian Wide and Fullwidth as two now --
and Ambiguous as one, which is not a detail, because `é`, `│` and `▲` are all
Ambiguous and every box a Turbo Vision program draws is made of them.

The check that pins it is "the note column starts in the same place on every
row": one row's char is `H`, another's is `한`, and if the emulator counted
either of them wrong the two would not line up.
"""

import base64
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

# The window sits at desktop (0, 1), so its frame is screen row 2, the column
# header is row 3 and the first decoded row is row 4.
FIRST_ROW = 4
ROWS = 14
LEFT = 1
NOTE_AT = LEFT + 38          # where "what it is" begins, on every row
STATUS_ROW = FIRST_ROW + ROWS + 1


def line_at(app, row):
    return app.render().split("\n")[row]


def rows(app):
    lines = app.render().split("\n")
    return [lines[FIRST_ROW + i][LEFT:LEFT + 76] for i in range(ROWS)]


def status(app):
    return line_at(app, STATUS_ROW).strip("║░ ─")


def title(app):
    return line_at(app, 2)


def menu(app, item):
    bar = app.render().split("\n")[0]
    app.click(bar.index(item) + 1, 1, settle=0.6)


def encoding_menu(app, keys, settle=0.8):
    """Open the Encoding pull-down and drive it by the letters it underlines.

    Which is how every menu is reached in this repo, and for the reason
    `drive_hex.py` writes down: counting lines breaks the moment an entry is
    added somewhere above the one being aimed at.
    """
    menu(app, "Encoding")
    app.send(keys, settle=settle)


def paste(app, text, key=b"p", settle=1.0):
    """Press a paste key and answer the OSC 52 it sends.

    The driver has claimed OSC 52 support, so the clipboard is the terminal's
    -- and the terminal is this file, which can put whatever it likes on it.
    """
    mark = len(app.buf)
    app.send(key, settle=0.6)
    asked = b"\x1b]52;;?\x07" in app.buf[mark:]
    app.send(b"\x1b]52;;" + base64.b64encode(text.encode()) + b"\x07", settle=settle)
    return asked


def copied(app, mark):
    import re
    found = re.findall(rb"\x1b\]52;;([A-Za-z0-9+/=]*)\x07", app.buf[mark:])
    return base64.b64decode(found[-1]).decode() if found else ""


def note_on(row):
    return row[38:].strip()


def main():
    check = Checks()

    env = dict(os.environ, TERM="xterm-256color",
               HOME=tempfile.mkdtemp(prefix="predc-home-"))
    env.pop("XDG_CONFIG_HOME", None)
    # No display, so the clipboard is the terminal's rather than whoever ran
    # this -- the same reason `drive_hex.py` and `drive_clip.py` do it.
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    app = Pty(node_argv(LAUNCHER), env, cwd=tempfile.mkdtemp(prefix="predc-uni-"))
    app.pump(2.5)

    # 1. The tool opens empty and says what to do about it.
    app.send(b"\x1bu", settle=1.2)
    check("Alt-U opened the decoder", "Unicode" in title(app), title(app))
    check("and it says UTF-8 before anything has been pasted",
          "UTF-8" in title(app), title(app))
    check("and it brought its own menu with it",
          "Encoding" in app.render().split("\n")[0], app.render().split("\n")[0])
    check("the empty window says how to give it something",
          "Paste text with p" in rows(app)[0], rows(app)[0])

    app.send(b"\x1b]60;allowWindowOps\x07", settle=0.5)

    # 2. Text, which arrives as the UTF-8 the string is made of. The fixture is
    #    chosen for its widths: ASCII, a two-byte Latin-1 character, two Hangul
    #    syllables that are three bytes and two columns each, and an emoji that
    #    is four bytes and two columns.
    check("p asks the clipboard for text", paste(app, "Hé 한글 😀"))
    check("ASCII is one byte", rows(app)[0].startswith("00000000  48"), rows(app)[0])
    check("and says what it is called",
          note_on(rows(app)[0]) == "ASCII", repr(note_on(rows(app)[0])))
    check("a Latin-1 character is two bytes",
          rows(app)[1].startswith("00000001  C3 A9") and "U+00E9" in rows(app)[1],
          rows(app)[1])
    check("a Hangul syllable is three",
          rows(app)[3].startswith("00000004  ED 95 9C") and "U+D55C" in rows(app)[3],
          rows(app)[3])
    check("and an emoji is four, in a plane of its own",
          "F0 9F 98 80" in rows(app)[6] and "U+1F600" in rows(app)[6],
          rows(app)[6])
    check("and the count is characters, not bytes",
          "7 characters, none of them broken" in status(app), status(app))

    #    The width check, which is what this driver is really pinning: the note
    #    column has to begin in the same place on the ASCII row, the Hangul row
    #    and the emoji row. It only can if the emulator counts a wide character
    #    as two columns and an ambiguous one as one.
    starts = [rows(app)[i].index(note_on(rows(app)[i])) for i in (0, 1, 3, 6)]
    check("every row's note starts in the same column, wide characters and all",
          len(set(starts)) == 1 and starts[0] == 38, str(starts))
    check("and the character itself is on the screen",
          "한" in rows(app)[3] and "😀" in rows(app)[6],
          rows(app)[3] + " / " + rows(app)[6])

    # 3. The broken half, which is the point of the tool. Every one of these is
    #    a thing `TextDecoder` answers with U+FFFD and no explanation.
    paste(app, "48 C0 80 ED A0 80 F5 80 80 80 FE E2 82", key=b"P")
    check("P reads the clipboard as hex bytes",
          "pasted hex" in title(app) and "13 bytes" in title(app), title(app))
    check("C0 80 is named as an overlong encoding of the null it pretends to be",
          "overlong" in rows(app)[1] and "U+0000" in rows(app)[1], rows(app)[1])
    check("and it has no code point, rather than a replacement character",
          "U+" not in rows(app)[1][24:33] and "--" in rows(app)[1], rows(app)[1])
    check("ED A0 80 is named as a surrogate, which is how half-converted "
          "UTF-16 gives itself away",
          "surrogate" in rows(app)[2] and "U+D800" in rows(app)[2], rows(app)[2])
    check("F5 80 80 80 is past the last code point there is",
          "past the last" in rows(app)[3], rows(app)[3])
    check("FE is not a byte anything can start with",
          "never starts" in rows(app)[4], rows(app)[4])
    check("and a lead byte whose continuations ran out says how many were left",
          "starts 3 bytes and only 2 are left" in rows(app)[5], rows(app)[5])
    check("the count says how many are broken, which is the answer somebody "
          "opened this to get",
          "6 characters, 5 of them broken" in status(app), status(app))

    # 4. The same bytes read three ways, which is what makes this a tool rather
    #    than a decoder: nothing about the bytes says which they are.
    paste(app, "41 00 42 00", key=b"P")
    app.send(b"l", settle=0.7)
    check("l reads UTF-16 little-endian", "UTF-16 LE" in title(app), title(app))
    check("and 41 00 42 00 is two Latin letters that way",
          "U+0041" in rows(app)[0] and "U+0042" in rows(app)[1],
          rows(app)[0] + " / " + rows(app)[1])
    app.send(b"b", settle=0.7)
    check("b reads the other order", "UTF-16 BE" in title(app), title(app))
    check("and the same four bytes are two CJK characters that way",
          "U+4100" in rows(app)[0] and "U+4200" in rows(app)[1],
          rows(app)[0] + " / " + rows(app)[1])
    encoding_menu(app, b"8", settle=0.8)
    check("and the menu gets back to UTF-8", "UTF-8" in title(app), title(app))

    # 5. UTF-16's own broken cases, which are about surrogates rather than
    #    about lead bytes -- a different failure with a different sentence.
    paste(app, "3D D8 00 DE", key=b"P")
    app.send(b"l", settle=0.7)
    check("a surrogate pair is one character and four bytes",
          "U+1F600" in rows(app)[0] and "3D D8 00 DE" in rows(app)[0],
          rows(app)[0])
    check("and one character is what the count says",
          "1 character," in status(app), status(app))

    paste(app, "00 DE 3D D8 41", key=b"P")
    app.send(b"l", settle=0.7)
    check("a low surrogate with nothing before it is named as one",
          "low surrogate" in rows(app)[0], rows(app)[0])
    check("a high surrogate with nothing after it is named too",
          "high surrogate" in rows(app)[1], rows(app)[1])

    #    A trailing byte on its own, which is a different complaint: the units
    #    before it were all whole, and this one cannot be.
    paste(app, "41 00 42", key=b"P")
    app.send(b"l", settle=0.7)
    check("and an odd byte at the end is not silently dropped",
          "U+0041" in rows(app)[0] and "one byte left over" in rows(app)[1],
          rows(app)[0] + " / " + rows(app)[1])

    # 6. Copying, which is the one thing this produces that nothing else on the
    #    machine will: the code points in the form they are written in.
    app.send(b"8", settle=0.7)
    paste(app, "48 C3 A9 C0 80", key=b"P")
    mark = len(app.buf)
    app.send(b"y", settle=0.9)
    check("y copies the code points",
          copied(app, mark) == "U+0048 U+00E9 --", repr(copied(app, mark)))
    check("and a broken one is a gap you can see rather than a silent hole",
          "--" in copied(app, mark), repr(copied(app, mark)))
    check("and the line under the rows says what it did",
          "Copied 3 code points" in status(app), status(app))

    # 7. Refusals, which are the hex viewer's and are here for the same reason.
    paste(app, "beefz", key=b"P")
    check("a stray character is refused and named",
          "not a hex digit" in status(app), status(app))
    paste(app, "abc", key=b"P")
    check("an odd number of digits is refused with the count",
          "3 hex digits" in status(app), status(app))
    paste(app, "")
    check("and an empty clipboard says that rather than showing nothing",
          "nothing on the clipboard" in status(app), status(app))

    # 8. It closes like every other tool, and reopening starts fresh.
    app.send(b"\x1b\x1bOR", settle=1.0)          # Alt-F3
    check("Alt-F3 closed the window", "Unicode" not in title(app), title(app))
    check("and its menu left the bar with it",
          "Encoding" not in app.render().split("\n")[0],
          app.render().split("\n")[0])
    app.send(b"\x1bu", settle=1.0)
    check("reopening starts empty, the way closing a tool here means it does",
          "Paste text with p" in rows(app)[0], rows(app)[0])

    app.send(b"\x1bx", settle=1.0)
    check("Alt-X exits, and cleanly", app.wait() == 0)

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
