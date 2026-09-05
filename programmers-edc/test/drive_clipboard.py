#!/usr/bin/env python3
"""One clipboard, reached from both sides of the binding.

There are two ways text gets onto predc's clipboard and two ways it comes off,
and they belong to different layers:

  * the **model's** -- `Tui.copyToClipboard` and `Tui.readClipboard`, which are
    `y` and `p` in the tools;
  * **Turbo Vision's** -- `cmCut`, `cmCopy` and `cmPaste`, which `TInputLine`
    and `TEditor` answer for whatever holds the caret, and which predc binds to
    Shift-Del, Ctrl-Ins and Shift-Ins on its status line.

Until 2026-09-03 those were two different stores. The binding keeps its own
because `TClipboard::localText` is a private static whose only reader hands
what it finds to `TEventQueue::setPasteText` -- there is no way to get a string
out of that class -- and the views went on using `TClipboard` anyway. So a `y`
in one window and a `Shift-Ins` in a field filled and read different places.

**The seam only shows where there is no system clipboard to meet in**, because
both stores are fallbacks: with a real one, or a terminal that answers an
`OSC 52` read, both paths go there and agree. Which is why this driver never
claims `OSC 52` support and removes `DISPLAY` -- it is an ssh session, in other
words, and that is the case the bug was in.

It is its own suite rather than a section of `drive_hex.py` because it needs
that: the moment a driver claims a terminal that answers reads, every paste
becomes a query the driver has to answer, and the fallback these two share is
no longer what is being tested.
"""

import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

SHIFT_INS = b"\x1b[2;2~"
CTRL_INS = b"\x1b[2;5~"
SHIFT_DEL = b"\x1b[3;2~"
DEL = b"\x1b[3~"
TAB = b"\t"


def line_at(app, row):
    return app.render().split("\n")[row]


# The decoder's entry row, and its first decoded row. Row 4 is the Clear
# button's shadow and row 5 the column header -- `drive_unicode.py` says why a
# button costs a row -- so the rows start one lower than the arithmetic in this
# file used to assume.
FIELD_ROW = 3
FIRST_ROW = 6
STATUS_ROW = 21


def field(app):
    """The Unicode decoder's entry row."""
    return line_at(app, FIELD_ROW)


def typed(app):
    """Just what is in that field, without the furniture on either side.

    Three things share the row now -- the label, the Clear button and the
    reading -- so this trims at whichever comes first rather than at the `(` of
    `(*) Text`, which the button sits in front of.
    """
    row = field(app)
    if "Bytes" not in row:
        return ""
    rest = row.split("Bytes", 1)[1]
    return rest.split("Clear")[0].split("(")[0].strip()


def status(app):
    return line_at(app, STATUS_ROW).strip("║░ ─└┘")


def to_field(app):
    """`Alt-B` is the field's label. A no-op when the field already has the
    caret, which matters because a field selects its whole value when it
    *gains* one -- see `clear_field`."""
    app.send(b"\x1bb", settle=0.6)


def clear_field(app):
    """Leave and come back, so there is a selection, then `Del`, which is the
    key that honours one (`tinputli.cpp:399`)."""
    app.send(TAB, settle=0.4)
    to_field(app)
    app.send(DEL, settle=0.7)


def main():
    check = Checks()

    env = dict(os.environ, TERM="xterm-256color",
               HOME=tempfile.mkdtemp(prefix="predc-home-"))
    env.pop("XDG_CONFIG_HOME", None)
    # No display, and -- unlike every other suite here -- no `OSC 52` claim
    # either. Nothing outside this process has a clipboard.
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    app = Pty(node_argv(LAUNCHER), env, cwd=tempfile.mkdtemp(prefix="predc-clip-"))
    app.pump(2.5)

    app.send(b"\x1bu", settle=1.2)
    check("the Unicode decoder is open", "Unicode" in line_at(app, 2),
          line_at(app, 2))

    # 1. Turbo Vision's own commands, on a field, in both directions. Neither
    #    key is bound by Turbo Vision itself -- it will not choose Ctrl-C for
    #    anybody -- so these work because predc's status line names them, which
    #    is the thing magiblot/tvision#178 is somebody discovering the hard way.
    app.send(b"CAFEBABE", settle=0.8)
    check("what was typed is in the field", typed(app) == "CAFEBABE", typed(app))
    app.send(TAB, settle=0.4)
    to_field(app)                                   # regain the caret: selects all
    app.send(CTRL_INS, settle=0.9)
    clear_field(app)
    check("the field is empty before the paste", typed(app) == "", typed(app))
    app.send(SHIFT_INS, settle=1.0)
    check("Ctrl-Ins and Shift-Ins copy and paste in an input line",
          typed(app) == "CAFEBABE", typed(app))

    #    Cut is the same copy with the selection taken out, and Turbo Vision
    #    exposes no way to ask for that delete from outside -- `deleteSelect`,
    #    `saveState` and `checkValid` are all private -- so the binding asks in
    #    the only vocabulary there is, which is `Del` with a selection out.
    app.send(TAB, settle=0.4)
    to_field(app)
    app.send(SHIFT_DEL, settle=1.0)
    check("Shift-Del cuts, leaving the field empty", typed(app) == "", typed(app))
    app.send(SHIFT_INS, settle=1.0)
    check("and what it cut is what pastes back", typed(app) == "CAFEBABE",
          typed(app))

    # 2. The seam itself. `y` is the *model's* copy -- Tui.copyToClipboard --
    #    and Shift-Ins is Turbo Vision's paste. One clipboard now; two before.
    clear_field(app)
    app.send(b"48 69", settle=0.8)
    app.send(TAB, settle=0.4)
    app.send(b"\x1b[C", settle=0.7)                 # the radio: read it as hex
    check("48 69 read as hex is two ASCII characters",
          "U+0048" in line_at(app, FIRST_ROW) and "U+0069" in line_at(app, FIRST_ROW + 1),
          line_at(app, FIRST_ROW) + " / " + line_at(app, FIRST_ROW + 1))
    app.send(TAB, settle=0.5)                       # onto the rows
    app.send(b"y", settle=1.0)
    check("y copied the code points, and says nothing confirmed taking them",
          "Copied 2 code points" in status(app) and "did not confirm" in status(app),
          status(app))

    clear_field(app)
    app.send(SHIFT_INS, settle=1.2)
    check("Shift-Ins pastes what the *model* copied -- one store, not two",
          typed(app) == "U+0048 U+0069", typed(app))

    # 3. And back the other way: a field's copy is what the model reads.
    clear_field(app)
    app.send(b"beef", settle=0.8)
    app.send(TAB, settle=0.4)
    to_field(app)
    app.send(CTRL_INS, settle=1.0)
    app.send(TAB, settle=0.4)
    app.send(TAB, settle=0.6)                       # onto the rows, for `p`
    app.send(b"p", settle=1.2)                      # Tui.readClipboard
    check("p reads back what a field copied, which is the same store again",
          "pasted text" in line_at(app, 2) and "(4 bytes)" in line_at(app, 2),
          line_at(app, 2))
    # One row per *character*, so "beef" is four of them.
    check("and the bytes are the ones the field held",
          all("U+006" + d in line_at(app, FIRST_ROW + i)
              for i, d in enumerate("2556")),
          " / ".join(line_at(app, FIRST_ROW + i).strip("║░ ▲▓") for i in range(4)))

    app.send(b"\x1bx", settle=1.0)
    check("Alt-X exits, and cleanly", app.wait() == 0)

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
