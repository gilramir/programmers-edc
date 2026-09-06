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
import tempfile

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


def resize(app, arrows):
    """Ctrl-F5 is the Window menu's Resize/move; shifted arrows resize rather
    than move in `TView::dragView`; Enter commits."""
    app.send(b"\x1b[15;5~", settle=0.6)
    for i in range(0, len(arrows), 6):
        app.send(arrows[i:i + 6], settle=0.3)
    app.send(b"\r", settle=0.9)


def zoom_attr(app):
    """The colour the Window menu draws its Zoom entry in. Turbo Vision greys
    an item whose command is disabled, and dropping `wfZoom` is what disables
    it -- so this is how "the frame has no zoom box" is visible on the menu."""
    bar = app.render().split("\n")[0]
    app.click(bar.index("Window") + 1, 1, settle=0.7)
    screen = app.display()
    for r, row in enumerate(screen.grid):
        text = "".join(row)
        if "Zoom" in text:
            attr = screen.attrs[r][text.index("Zoom")]
            app.send(b"\x1b", settle=0.4)
            return attr
    app.send(b"\x1b", settle=0.4)
    return None


def zoom_is_greyed(app):
    attr = zoom_attr(app)
    return attr is not None and attr[0] == 90


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


def listed(screen):
    """The list mode's rows, as (dec, hex, oct, sym, name) tuples.

    Matched by their shape rather than by counting rows off the frame, because
    the number of them is the whole point of the mode and changes with the
    terminal.
    """
    out = []
    for line in screen.split("\n"):
        m = re.search(r"\s(\d{1,3})\s+([0-9A-F]{2})\s+(\d{3})\s\s(.{1,4}?)\s\s+(.*?)\s*[│║▲▼▒■]", line)
        if m:
            out.append(tuple(m.group(i) for i in range(1, 6)))
    return out


def main():
    check = Checks()
    # A temporary HOME, so that this driver reads no config file but the one
    # it did not write. predc remembers its colour scheme in
    # `$HOME/.config/predc/`, and a suite that inherited the real one would
    # pass or fail depending on which theme the person running it happens to
    # like -- which is exactly what happened once, when a scratch script left a
    # `"gren"` behind and four colour checks in two suites started failing
    # against a program that was working perfectly.
    env = dict(os.environ, TERM="xterm-256color",
               HOME=tempfile.mkdtemp(prefix="predc-home-"))
    env.pop("XDG_CONFIG_HOME", None)
    app = Pty(node_argv(LAUNCHER), env, cwd=ROOT)

    app.pump(2.5)
    check("the Tools menu is on the bar", "Tools" in app.render().split("\n")[0])
    check("no tool is open until one is asked for", frames(app.render()) == 0)

    # Alt-A is the Tools menu's, and only the menu's, since the tools came off
    # the status line. `TMenuBar` is `ofPreProcess` exactly as `TStatusLine`
    # was, so the key still arrives from a window with a focused canvas in it
    # -- which is the premise of taking it off the bar, and this send is what
    # checks it.
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

    # ...and the selection is painted, not merely pointed at. The terminal's
    # own cursor is the example's only way of showing which cell is selected,
    # and whether it is visible at all is the terminal's business -- a thin
    # bar, a hollow box, a blink turned off. So the model paints the cell.
    d = app.display()
    check("the selected cell is painted, not just under the cursor",
          d.bg_at(*cell(0)) == 47 and d.fg_at(*cell(0)) == 34,
          f"fg {d.fg_at(*cell(0))} on bg {d.bg_at(*cell(0))}")
    check("and only that cell", d.bg_at(*cell(1)) == 44
          and d.bg_at(cell(0)[0] + 1, cell(0)[1]) == 44,
          "the highlight leaked into the gap or the next cell")

    # The control third of the table is painted in a colour of its own, which
    # is a canvas drawing itself in spans. Cell 0 is a control and cell 0x41
    # is not; whatever the two colours are, they must differ.
    # Cell 1 and not cell 0: cell 0 is the selected one, and a highlight would
    # make this pass for the wrong reason.
    grid = app.display()
    control = grid.fg_at(*cell(1))
    printable = grid.fg_at(*cell(0x41))
    check("control codes are painted in their own colour", control != printable,
          f"control fg {control}, printable fg {printable}")

    # And the colours have to be ones a *blue* window can carry. `Hue` names an
    # absolute colour with nothing between it and the terminal, so the model is
    # the only thing that can get this wrong -- and it got it wrong twice, once
    # in each direction. The first version painted bright yellow labels on the
    # light grey ground a window had by accident, around 1.5:1. The second kept
    # the dark blue and dark grey that fixed *that* and then the window became
    # blue, which is where dark blue labels go to disappear entirely. These pin
    # the pair that is readable on blue -- light cyan for the ruler, cyan for
    # the placeholders -- so that a dark hue fails here rather than in
    # someone's eyes.
    check("the row and column labels are light cyan, not a dark hue",
          grid.fg_at(11, 4) == 96 and grid.fg_at(8, 5) == 96,
          f"header fg {grid.fg_at(11, 4)}, label fg {grid.fg_at(8, 5)}")
    check("and the placeholder dots are cyan", control == 36,
          f"control fg {control}")

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

    d = app.display()
    check("and so did the highlight",
          d.bg_at(*cell(7)) == 47 and d.bg_at(*cell(0)) == 44,
          f"cell 7 bg {d.bg_at(*cell(7))}, cell 0 bg {d.bg_at(*cell(0))}")

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
    #    By the letter it underlines and not by counting rows: adding
    #    **Copying and pasting** to the Help menu moved About down two, and the
    #    four checks that broke were about neither.
    bar = app.render().split("\n")[0]
    app.click(bar.index("Help") + 1, 1, settle=0.6)
    app.send(b"a", settle=0.9)
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

    # The window is `resize = Tui.fixedSize`: sixteen rows of eight columns is
    # the whole chart, and a bigger window would be the same chart with a gap
    # round it. Three things follow, and the third is the one that is easy to
    # forget -- a command nothing can act on has to *look* like one.
    frame = [row for row in app.render().split("\n") if "ASCII Chart" in row][0]
    check("a fixed-size window has no zoom box on its frame",
          "[↑]" not in frame and "[↕]" not in frame, frame)
    check("and no resize handle at the foot of it",
          not any("└─" in row for row in app.render().split("\n")),
          app.render())

    before = app.render()
    resize(app, b"\x1b[1;2B" * 3 + b"\x1b[1;2C" * 3)
    check("and Ctrl-F5 plus shifted arrows changes nothing",
          app.render() == before, app.render())

    check("Window | Zoom is greyed out while it is the active window",
          zoom_is_greyed(app), str(zoom_attr(app)))

    # ---- the other chart -------------------------------------------------
    # Two modes over one selected code, which is the reason they are a mode
    # and not two tools: switching keeps your place.
    app.send(b"*", settle=0.8)
    check("back on a printable code before switching",
          numbers(app.render())["dec"] == 0x2A, str(numbers(app.render())))

    app.send(b"\t", settle=1.5)
    rows = listed(app.render())
    check("Tab switches to the long list", "ASCII Chart - list" in app.render(),
          app.render().split("\n")[1])
    check("which is what man ascii prints: dec, hex, oct, and a name",
          "Dec  Hex  Oct  Sym   Name" in app.render(),
          [r for r in app.render().split("\n") if "Dec" in r])
    check("the selected code came with it, so the list opened at 42",
          numbers(app.render())["dec"] == 0x2A, str(numbers(app.render())))
    check("and 42 is one of the rows on screen",
          any(r[0] == "42" and r[3] == "*" for r in rows), rows[:4])

    # A control code's row carries what the grid could only say underneath it.
    app.send(b"\x1b[1;5H", settle=0.6)       # Ctrl-Home is not bound; Home is
    app.send(b"\x1b[H", settle=0.8)
    rows = listed(app.render())
    check("the list starts at 0 and names the control codes",
          rows[0][:4] == ("0", "00", "000", "NUL") and "null" in rows[0][4],
          rows[:2])
    check("with the chord and the escape on the same line, which is the whole "
          "reason to open this mode",
          any(r[0] == "7" and "Ctrl-G" in r[4] and "\\a" in r[4] for r in rows),
          [r for r in rows if r[0] == "7"])

    # A row is one code here and sixteen in the grid, which is the only thing
    # the arrows have to know about the mode.
    app.send(b"\x1b[B", settle=0.8)
    check("Down moves one code in the list, not a row of sixteen",
          numbers(app.render())["dec"] == 1, str(numbers(app.render())))

    app.send(b"\x1b[F", settle=1.0)          # End
    rows = listed(app.render())
    check("End scrolls to the end of a list longer than the window",
          numbers(app.render())["dec"] == 127
          and any(r[0] == "127" and r[3] == "DEL" for r in rows),
          rows[-2:])
    check("and 0 is no longer on screen, which is what scrolling means",
          not any(r[0] == "0" for r in rows), rows[:2])

    # `resize` is the one window-level field the differ cannot patch, so the
    # two modes are two windows -- and this is the difference that makes them
    # so. The grid has nothing more to show and says so; the list does.
    frame = [row for row in app.render().split("\n") if "ASCII Chart" in row][0]
    check("the list window offers a zoom box where the grid offered none",
          "[↑]" in frame or "[↕]" in frame, frame)
    check("and a resize handle at its foot",
          any("└─" in row for row in app.render().split("\n")), app.render())

    # The menu is the other way in, and the only place the mode is *named*.
    # Turbo Vision has no checkable item, so the tick is a character.
    bar = app.render().split("\n")[0]
    app.click(bar.index("Chart") + 1, 1, settle=0.8)
    box = app.render()
    check("the Chart menu ticks the mode you are in",
          "√ List" in box and "√ Grid" not in box,
          [r for r in box.split("\n") if "Grid" in r or "List" in r])
    for row, line in enumerate(box.split("\n")):
        if "Grid" in line and "│" in line:
            app.click(line.index("Grid") + 1, row + 1, settle=1.5)
            break
    check("and choosing the other one from the menu switches too",
          "ASCII Chart - list" not in app.render(), app.render().split("\n")[1])

    app.send(b"\t", settle=1.5)
    app.send(b"\t", settle=1.5)
    check("Tab goes back, and the code is still 127",
          "ASCII Chart - list" not in app.render()
          and numbers(app.render())["dec"] == 127,
          app.render().split("\n")[1])
    check("so the grid is showing DEL again", naming(app.render()).startswith("DEL"),
          naming(app.render()))

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("Alt-X exits from inside the chart, and cleanly", code == 0,
          f"exit={code}")

    # ---- taller if the screen can take it --------------------------------
    # The grid is 48 by 15 whatever the terminal is; the list is not, because
    # there is more of it than fits and a bigger screen should show more.
    small = Pty(node_argv(LAUNCHER, "ascii"), env, cwd=ROOT, size=(80, 24))
    small.pump(2.0)
    small.send(b"\t", settle=1.5)
    short = len(listed(small.render()))
    small.send(b"\x1bx", settle=0.8)
    small.wait(timeout=6)

    tall = Pty(node_argv(LAUNCHER, "ascii"), env, cwd=ROOT, size=(80, 44))
    tall.pump(2.0)
    tall.send(b"\t", settle=1.5)
    long_ = len(listed(tall.render()))
    check("a taller terminal shows more of the list", long_ > short + 15,
          f"{short} rows at 24, {long_} at 44")
    check("and its bottom frame is on the screen rather than under it, which "
          "is what taking the rows off the rectangle rather than the other way "
          "round is for",
          any("└─" in row for row in tall.render().split("\n")),
          tall.render().split("\n")[-3:])
    tall.send(b"\x1bx", settle=0.8)
    check("and that one exits cleanly too", tall.wait(timeout=6) == 0, "exit")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
