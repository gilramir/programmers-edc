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

# The window sits at desktop (0, 1), so its frame is screen row 2 and the entry
# field is row 3. Row 4 is the Clear button's *shadow* -- TButton draws its face
# on every row but the last and the shadow on that one, so a one-row button is
# an invisible button and this window is a row taller than it looks -- row 5 is
# the column header, and the first decoded row is row 6.
FIRST_ROW = 6
ROWS = 14
LEFT = 1
NOTE_AT = LEFT + 38          # where "what it is" begins, on every row
PASTE_ROW = FIRST_ROW + ROWS         # the how-to-paste line, always there
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


def field(app):
    """The entry row: the field's text, the Clear button and the reading."""
    return line_at(app, FIRST_ROW - 3)


def paste_line(app):
    """The line under the rows that says how to get bytes in here."""
    return line_at(app, PASTE_ROW).strip("\u2551\u2591 ")


def to_rows(app):
    """Put the caret on the decoded rows.

    The field is the first selectable view, so it has the caret when the window
    opens -- which is the point of it, and which means the single-letter
    commands do not reach the canvas until something moves the caret off it.

    It goes by way of the field rather than tabbing from wherever it was: two
    tabs is field, radio, rows, and starting from a known place is what makes
    that a fact rather than an assumption about where the last check left it.
    """
    app.send(b"\x1bb", settle=0.4)
    app.send(b"\t\t", settle=0.6)


def _typed_one_digit(app):
    """One hex digit into an empty field decodes to nothing at all, which is
    the case the pending-digit note is really for: there is no count for it to
    hang off, so the rows have to carry it."""
    app.send(b"E", settle=0.8)
    return "One hex digit so far" in rows(app)[0]


def to_field(app):
    """...and back. `Alt-B` is the field's label, which works from anywhere in
    the window rather than depending on how many views are between -- and is a
    no-op when the field already has the caret, which matters just below."""
    app.send(b"\x1bb", settle=0.6)


def clear_field(app):
    """Empty the field.

    Two facts about `TInputLine`, and a driver that knows neither writes a
    check that silently does nothing. Turbo Vision selects the whole value when
    the field *gains* the caret and not while it has it, so this leaves and
    comes back to make a selection. And `Del` is what honours one:
    `Backspace` with no selection deletes the character before the caret, while
    `Del` with a selection deletes all of it (`tinputli.cpp:380`).
    """
    app.send(b"\t", settle=0.4)
    to_field(app)
    app.send(b"\x1b[3~", settle=0.8)


def main():
    check = Checks()

    env = dict(os.environ, TERM="xterm-256color",
               HOME=tempfile.mkdtemp(prefix="predc-home-"))
    env.pop("XDG_CONFIG_HOME", None)
    # No display, so the clipboard is the terminal's rather than whoever ran
    # this -- the same reason `drive_hex.py` and `drive_clip.py` do it.
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    # And a session dressed the same way every time it runs, because the line
    # under the rows says what to press *here* and would otherwise be one
    # sentence on the machine this was written on and another in a bare shell.
    # tmux is the variant to pin: it is the longest of the four and the only
    # one that spends the whole seventy-six columns.
    for name in ("SSH_CONNECTION", "SSH_TTY", "SSH_CLIENT", "STY"):
        env.pop(name, None)
    env["TMUX"] = "/tmp/tmux-1000/default,4242,0"
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
          "Type bytes in the field above" in rows(app)[0], rows(app)[0])
    check("and the field is what has the caret, which is why it says that",
          "( ) Hex" in field(app) and "(\u2022) Text" in field(app), field(app))
    check("and there is a Clear button beside it",
          "Clear" in field(app), field(app))

    #    The line under the rows, which is there before anything has gone
    #    wrong and stays there. What it says depends on the session, and this
    #    driver dresses one so that it is the same sentence every run.
    check("the window says how to paste in this session, without being asked",
          paste_line(app) ==
          "Paste  Ctrl-Shift-V, Shift-Ins, tmux prefix ] into the field.  "
          "F1 for why.", repr(paste_line(app)))
    check("and it fits the columns it has, so the frame is still beside it",
          line_at(app, PASTE_ROW)[78] == "\u2551",
          repr(line_at(app, PASTE_ROW)[70:80]))

    #    And `p`, before this driver has claimed a terminal that will answer an
    #    `OSC 52` read query -- which is the state a real ssh session is
    #    permanently in, since tmux answers none and forwards none. Nothing was
    #    asked and nothing came back, and the sentence has to say which of the
    #    two that was: the clipboard is not empty, the terminal will not open
    #    it. Reached by the menu, because the caret is in the field.
    encoding_menu(app, b"p", settle=1.0)
    check("with no terminal willing to answer, p says so rather than blaming "
          "the clipboard",
          "will not hand the clipboard over" in status(app), status(app))
    check("and the whole sentence fits the line it is written on",
          "instead" in status(app), status(app))

    app.send(b"\x1b]60;allowWindowOps\x07", settle=0.5)

    # 1b. The field, which is the only way into this tool that does not go near
    #     the clipboard -- and therefore the only one that works over ssh, where
    #     no terminal will hand a clipboard back. A terminal paste arrives as
    #     keystrokes, and this is what they land in.
    app.send(b"Hi", settle=0.8)
    check("what is typed is decoded as the bytes the string is made of",
          rows(app)[0].startswith("00000000  48") and "U+0048" in rows(app)[0],
          rows(app)[0])
    check("and the title says the bytes were typed rather than pasted",
          "typed (2 bytes)" in title(app), title(app))

    #     The radio, which is the other half: `beef` and `cafe` are words and
    #     are also hex, so something has to say which was meant.
    app.send(b"\t\x1b[C", settle=0.8)               # Tab to the radio, pick Hex
    check("choosing Hex re-reads the same field as hex digits",
          "(\u2022) Hex" in field(app) and "typed (0 bytes)" not in title(app),
          field(app) + " | " + title(app))
    to_field(app)
    app.send(b"C0 80 ED A0 80", settle=1.0)
    check("and the two things this tool exists for come out of typed hex",
          "overlong" in rows(app)[0] and "surrogate" in rows(app)[1],
          rows(app)[0] + " / " + rows(app)[1])
    check("with the count saying how many are broken",
          "2 characters, 2 of them broken" in status(app), status(app))

    #     Half a byte is not an error. A field is read again on every keystroke
    #     and half of those land on an odd digit, so complaining about them
    #     would be a message flashing under somebody's hands -- but the digit
    #     that was left out is said, because a digit on the screen and not in
    #     the count is exactly the silence this tool exists to break.
    app.send(b" E", settle=0.8)
    check("a lone hex digit at the end is a byte half typed, not a refusal",
          "not hex" not in status(app) and "waiting for its pair" in status(app),
          status(app))
    check("and the bytes before it are still decoded rather than blanked",
          "overlong" in rows(app)[0], rows(app)[0])
    app.send(b"2", settle=0.8)
    check("finishing the byte decodes it",
          "3 characters" in status(app) and "E2" in rows(app)[2], status(app))
    app.send(b"z", settle=0.8)
    check("but a stray character is refused at once, since it is not half of "
          "anything",
          "'z' is not a hex digit" in status(app), status(app))
    check("and the rows keep what they had, which is what the mistake is being "
          "compared against",
          "E2" in rows(app)[2], rows(app)[2])

    #     Back to where the rest of this file expects to be: an empty field,
    #     text again, and the caret on the rows so the letter commands reach
    #     them.
    clear_field(app)
    check("emptying the field empties the window",
          "Nothing to read" in rows(app)[0], rows(app)[0])
    check("and the very first digit of a byte says so on its own",
          _typed_one_digit(app), rows(app)[0])
    clear_field(app)
    app.send(b"\t\x1b[D", settle=0.8)               # radio, back to Text
    to_rows(app)

    # 1c. The Clear button, which exists because emptying the field by hand is
    #     the two-trap dance `clear_field` above has to do -- leave, come back
    #     for a fresh selection, then Del -- and nobody switching a field of
    #     text over to hex should have to know either trap.
    to_field(app)
    app.send(b"beef", settle=0.8)
    check("there is something in the field to clear",
          "typed (4 bytes)" in title(app), title(app))
    app.send(b"\x1bl", settle=0.9)                   # Alt-L, the button's hotkey
    check("Alt-L empties the field from inside it",
          field(app).split("Bytes")[1].strip().startswith("Clear"), field(app))
    check("and the rows go with it, since the field is what they were made of",
          "Nothing to read" in rows(app)[0], rows(app)[0])
    check("and the title stops naming bytes that are no longer there",
          "bytes)" not in title(app), title(app))

    #     The button is not in the tab order. It must not be: the field is
    #     first so that it holds the caret when the window opens, and one Tab
    #     from there has to reach the radio and two the rows, which is what
    #     `to_rows` walks and what every letter command below depends on.
    to_field(app)
    app.send(b"\t", settle=0.6)
    app.send(b"\x1b[C", settle=0.8)                  # Right, which only a radio takes
    check("one Tab from the field reaches the radio and not the button",
          "(\u2022) Hex" in field(app), field(app))
    app.send(b"\x1b[D", settle=0.8)

    #     And it clears a paste, which a field-only Clear would miss: a paste
    #     empties the field on its way in, so there is nothing in the field to
    #     delete and the rows would sit there being the answer to a question
    #     nobody could see any more. Pasted from the rows, because `p` is a
    #     plain letter and the field would eat it.
    to_rows(app)
    paste(app, "H\u00e9")
    check("a paste puts rows up with an empty field",
          "pasted text" in title(app) and "2 characters" in status(app),
          title(app) + " | " + status(app))
    encoding_menu(app, b"c", settle=0.9)
    check("Clear on the menu empties a paste as well",
          "Nothing to read" in rows(app)[0] and "pasted" not in title(app),
          rows(app)[0] + " | " + title(app))

    #     And the plain letter, which is the third way in and the one that only
    #     works where the letter commands work.
    to_field(app)
    app.send(b"Hi", settle=0.8)
    check("something typed again",
          "2 characters" in status(app), status(app))
    to_rows(app)
    app.send(b"c", settle=0.8)
    check("and c on the rows clears it, like every other letter command here",
          "Nothing to read" in rows(app)[0], rows(app)[0])

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
          "Nothing to read" in rows(app)[0], rows(app)[0])
    check("and the field it reopens with is empty too",
          field(app).split("Bytes")[1].strip().startswith("Clear"), field(app))

    app.send(b"\x1bx", settle=1.0)
    check("Alt-X exits, and cleanly", app.wait() == 0)

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
