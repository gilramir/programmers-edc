#!/usr/bin/env python3
"""examples/clip.js -- the system clipboard, both directions.

The interesting thing about testing a clipboard is that it can be done at all.
On unix Turbo Vision reaches the system clipboard two ways: it runs `wl-copy`,
`xsel`, `xclip` or WSL's `clip.exe` if one of them is there, and otherwise it
asks the *terminal*, with `OSC 52`. The second one is an escape sequence out
and an escape sequence back, which is exactly what a pty test can see and
answer -- so this drives a real round trip without a clipboard, a display or a
window manager anywhere near it.

**`DISPLAY` and `WAYLAND_DISPLAY` are removed from the environment**, and that
is not tidiness. With either of them set and `xclip` installed, the subprocess
path wins and this suite would write to the clipboard of whoever is running it.
(On macOS there is nothing to unset -- `pbcopy` has no environment guard -- so
this test would want a different arrangement there.)

The two halves:

  * With nothing answering, `setClipboard` returns false and the text is kept
    inside the process. That is not a failure and the program says so: copy and
    paste inside one program still work, and the check is that the text comes
    back.
  * A terminal that says it supports OSC 52 changes both answers. TVision
    decides that from a reply to one of the capability queries it writes at
    startup, and `\x1b]60;allowWindowOps\x07` is the cheapest of them
    (`termio.cpp`, parseOSC). After it, a copy is a real `OSC 52` on the wire
    with the text base64'd into it, and a paste is a query this driver answers.
"""

import base64
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Pty, Checks, node_argv

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# What the terminal says when it is asked whether window operations are
# allowed. TVision takes it as "this terminal can do OSC 52 properly".
SUPPORTS_OSC52 = b"\x1b]60;allowWindowOps\x07"

# What a terminal writes back when asked for the clipboard.
def osc52(text):
    return b"\x1b]52;;" + base64.b64encode(text.encode()) + b"\x07"


# The window is at desktop (8, 4), so its frame is screen row 5 and column 8;
# the field and the report are at window rows 2 and 4.
FIELD_ROW = 7
REPORT_ROW = 9

ALT_C = b"\x1bc"
ALT_V = b"\x1bv"


def line(app, row):
    return app.render().split("\n")[row][9:70].strip()


def field(app):
    return line(app, FIELD_ROW)


def report(app):
    return line(app, REPORT_ROW)


def copies_of(app, text):
    """How many times an OSC 52 carrying this text is on the wire."""
    want = b"\x1b]52;;" + base64.b64encode(text.encode())
    return app.buf.count(want)


def main():
    check = Checks()

    env = dict(os.environ, TERM="xterm-256color")
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    app = Pty(node_argv(os.path.join(ROOT, "examples", "clip.js")), env, cwd=ROOT)
    app.pump(1.5)

    screen = app.render()
    check("the example started", "Clipboard" in screen, screen.split("\n")[1])
    check("with something in the field", field(app) == "hello", field(app))

    # 1. No helper program and a terminal that has said nothing. The OSC is
    #    written anyway -- TVision cannot know it was ignored -- and the answer
    #    is that nobody else got it.
    app.send(ALT_C, settle=0.8)
    check("copy writes an OSC 52 whether or not anything is listening",
          copies_of(app, "hello") == 1, str(copies_of(app, "hello")))
    check("and says the text went no further than this program",
          "here only" in report(app), report(app))

    # 2. ...which is exactly what makes the fallback worth having: it comes
    #    back. The field is emptied first, so that "it came back" is a change.
    app.send(b"\x1b[F", settle=0.3)            # End, so the field is not replaced
    app.send(b"\x7f" * 5, settle=0.5)          # five backspaces
    check("the field is empty", field(app) == "", field(app))
    app.send(ALT_V, settle=0.8)
    check("paste gives back what this program copied", field(app) == "hello", field(app))
    check("and says where it came from",
          "from this program" in report(app), report(app))

    # 3. A terminal that answers. One reply to a capability query changes what
    #    both halves do, without restarting anything.
    app.send(SUPPORTS_OSC52, settle=0.6)
    app.send(b"\x1b[F", settle=0.3)
    app.send(b" world", settle=0.6)
    check("the field takes typing", field(app) == "hello world", field(app))

    app.send(ALT_C, settle=0.8)
    check("the copy is on the wire with the text in it",
          copies_of(app, "hello world") == 1, str(copies_of(app, "hello world")))
    check("and now it reports that other programs can see it",
          "to the system clipboard" in report(app), report(app))

    # 4. And a paste is a question the terminal answers. This is the whole
    #    reason the Gren side of it is a request and an event rather than a
    #    getter: the answer arrives long after the call that asked for it.
    before = len(app.buf)
    app.send(ALT_V, settle=0.8)
    check("paste asks the terminal for the clipboard",
          b"\x1b]52;;?\x07" in app.buf[before:], repr(app.buf[before:][-60:]))
    app.send(osc52("from the terminal"), settle=0.9)
    check("and the terminal's answer lands in the field",
          field(app) == "from the terminal", field(app))
    check("and is reported as somebody else's text",
          "from the system clipboard" in report(app), report(app))

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("exit code 0", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
