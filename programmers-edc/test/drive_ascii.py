#!/usr/bin/env python3
"""predc's ASCII chart: the first tool, and the first proof that a tool is a
window rather than a program.

gren-tvision has its own ASCII chart in `examples/ascii`, and its driver tests
the same canvas from the same angle -- the cursor is the only place the
selection shows up, so that is what both assert on. What is new here is
everything around it:

  - the chart is 0 to 127, and control codes have their ASCII names, which is
    the reason a programmer opens this rather than the other one;
  - the control third of the table is a different colour, which is a canvas
    painting itself in spans;
  - it lives on a desktop with a shell around it, so closing it, reopening it
    and leaving it open while something else happens all have to work;
  - and the keys that must not be lost still work while the canvas has focus.

That last one is the finding this file exists to pin down. A focused canvas
consumes every key (`JsCanvas::handleEvent` clears the event), so `Alt-F3` and
`Alt-X` reach anything at all only because the menu bar and the status line are
`ofPreProcess` views and are asked first. If that ever changes, a user gets
stuck inside the chart with no way out, and this is what says so.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

ALT_F3 = b"\x1b\x1bOR"          # ESC-prefixed F3, which is how a terminal says Alt

# The window sits at desktop (6, 2) and the canvas 2 columns and 1 row inside
# it; the grid's own header row and 3-column labels are inside that. So code 0
# is here, and each cell is two columns wide.
ORIGIN = (11, 5)


def cell(code):
    return (ORIGIN[0] + (code % 16) * 2, ORIGIN[1] + code // 16)


def numbers(screen):
    """The four bases off the first detail line, as a dict."""
    m = re.search(r"Dec\s+(\d+)\s+Hex\s+(\S+)\s+Oct\s+(\S+)\s+Bin\s+(\d{4} \d{4})",
                  screen)
    return None if m is None else {
        "dec": int(m.group(1)), "hex": m.group(2),
        "oct": m.group(3), "bin": m.group(4),
    }


def naming(screen):
    """The name line, stripped."""
    for line in screen.split("\n"):
        if "║" in line and re.search(r"(NUL|BEL|SP |DEL|Char )", line):
            return line.split("║")[1].strip()
    return ""


def frames(screen):
    return screen.count("ASCII Chart")


def main():
    check = Checks()
    env = dict(os.environ, TERM="xterm-256color")
    app = Pty(node_argv(LAUNCHER), env, cwd=ROOT)

    app.pump(2.5)
    check("the Tools menu is on the bar", "Tools" in app.render().split("\n")[0])
    check("no tool is open until one is asked for", frames(app.render()) == 0)

    # Alt-A is on the status line and on the Tools menu; the status line's is
    # what this sends.
    app.send(b"\x1ba", settle=1.2)
    screen = app.render()
    check("Alt-A opened the chart", frames(screen) == 1, screen)

    # ASCII, and not the code page 437 chart the gren-tvision example draws.
    check("the grid is ASCII", "@ A B C D E F G H I J K L M N O" in screen, screen)
    check("and nothing outside it", "☺" not in screen and "░" in screen)
    check("128 codes, so the last row ends at 7_",
          "7_ p q r s t u v w x y z { | } ~ ·" in screen, screen)

    check("it starts on code 0", numbers(screen) == {
        "dec": 0, "hex": "00", "oct": "000", "bin": "0000 0000"}, str(numbers(screen)))
    check("which is named rather than drawn", naming(screen).startswith("NUL"),
          naming(screen))
    check("with the chord and the C escape",
          "Ctrl-@" in naming(screen) and "\\0" in naming(screen), naming(screen))
    check("the cursor is on the first cell", app.cursor() == cell(0),
          f"{app.cursor()} != {cell(0)}")

    # The control third of the table is painted in a colour of its own, which
    # is a canvas drawing itself in spans. Cell 0 is a control and cell 0x41
    # is not; whatever the two colours are, they must differ.
    grid = app.display()
    control = grid.fg_at(*cell(0))
    printable = grid.fg_at(*cell(0x41))
    check("control codes are painted in their own colour", control != printable,
          f"control fg {control}, printable fg {printable}")

    # Seven to the right is BEL, which is the entry that makes the whole tool
    # worth having: no glyph, a name, a chord and an escape.
    app.send(b"\x1b[C" * 7, settle=0.9)
    check("arrows reach the canvas", numbers(app.render())["dec"] == 7,
          str(numbers(app.render())))
    check("and 7 is BEL, bell, Ctrl-G, \\a",
          all(x in naming(app.render()) for x in ("BEL", "bell", "Ctrl-G", "\\a")),
          naming(app.render()))
    check("the cursor followed", app.cursor() == cell(7),
          f"{app.cursor()} != {cell(7)}")

    # A printable key jumps to itself: the fastest way to ask "what is the code
    # for this character", and the reason the canvas has to eat the keystroke.
    app.send(b"A", settle=0.8)
    check("a printable key jumps to itself", numbers(app.render()) == {
        "dec": 65, "hex": "41", "oct": "101", "bin": "0100 0001"},
        str(numbers(app.render())))
    check("and a printable code is shown as a character, not a name",
          naming(app.render()) == "Char A", naming(app.render()))

    app.send(b"\x1b[F", settle=0.8)          # End
    check("End goes to 127", numbers(app.render())["dec"] == 127,
          str(numbers(app.render())))
    check("which is DEL, and Ctrl-?",
          all(x in naming(app.render()) for x in ("DEL", "delete", "Ctrl-?")),
          naming(app.render()))

    # A click is in the canvas's own coordinates, and undoing the header row
    # and the row labels is the tool's job. 0x2A is '*'.
    at = cell(0x2A)
    app.click(at[0] + 1, at[1] + 1, settle=0.8)
    check("a click picks a cell", numbers(app.render())["dec"] == 0x2A,
          str(numbers(app.render())))

    # Asking for a tool that is already open raises it rather than opening a
    # second one -- which is Tui.focus, the one thing about window order the
    # model is allowed to say.
    app.send(b"\x1ba", settle=1.0)
    check("asking again does not open a second chart", frames(app.render()) == 1,
          app.render())
    check("and the selection is untouched", numbers(app.render())["dec"] == 0x2A,
          str(numbers(app.render())))

    # The shell is still there behind the tool.
    bar = app.render().split("\n")[0]
    at = bar.index("Help")
    app.click(at + 1, 1, settle=0.6)
    app.click(at + 3, 3, settle=0.9)
    check("the shell's About still opens over a tool",
          "every-day carry" in app.render(), app.render())
    app.send(b"\r", settle=0.9)

    # Alt-F3 while the canvas has focus. The canvas eats every key it is given,
    # so this arrives only because the status line is asked first.
    app.send(ALT_F3, settle=1.2)
    check("Alt-F3 closes the tool even though the canvas eats keys",
          frames(app.render()) == 0, app.render())

    # ...and closing it takes the tool's model with it, so reopening starts
    # fresh. That is the shell's `Maybe Tool.Ascii.Model` read literally, and
    # it is a deliberate difference from gren-tvision's example, where the
    # chart is the whole program and keeps its selection behind an `open`
    # flag. Here a closed tool is a tool you are done with. A tool holding
    # something the user *made* rather than merely where they were looking --
    # the hex dump's highlights, when it arrives -- can decide otherwise.
    app.send(b"\x1ba", settle=1.2)
    check("reopening brings the chart back", frames(app.render()) == 1)
    check("and closing it discarded the tool's state",
          numbers(app.render())["dec"] == 0, str(numbers(app.render())))
    check("so the cursor is back on the first cell", app.cursor() == cell(0),
          f"{app.cursor()} != {cell(0)}")

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("Alt-X exits from inside the chart, and cleanly", code == 0,
          f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
