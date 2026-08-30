#!/usr/bin/env python3
"""examples/palette -- tvision's palette example, in Gren.

`palette.cpp` is three levels of indirection: a view's palette indexes the
window's, which indexes the application's, which holds the byte the terminal
finally gets. The Gren port says the byte. So what this test asserts is that
the six lines come out in the six colours the C++ chain resolves to -- which is
the only way to check a port whose subject was the machinery it removed.

The seventh line is the joke. `palette.cpp` writes attribute 5 straight into
the draw buffer and comments that it "bypasses the palettes"; here it is
indistinguishable from the six above it, because there are none to bypass.

The second window is the other half: a canvas that names no colour still takes
the window's, which is how nearly every canvas in these examples paints.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLE = os.path.join(ROOT, "examples", "palette")
RUNTIME = os.path.join(ROOT, "..", "gren-tvision-runtime", "bin", "gren-tui.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

# The palette window is at desktop (4, 1) with its canvas one cell inside and
# one column further in, so the first coloured line is here.
FIRST = (7, 3)

# What cpTestView -> cpTestWindow -> cpTestAppC adds up to, as SGR: the BIOS
# attribute's low nibble is the foreground and its high nibble the background.
# 0x3E is bright yellow on cyan, and so on down the window.
EXPECTED = [
    ("3E", 93, 46),
    ("2D", 95, 42),
    ("72", 32, 47),
    ("5F", 97, 45),
    ("68", 90, 43),
    ("4E", 93, 41),
]

# The line that "bypasses the palettes": attribute 5, magenta on black.
BYPASS = (35, 40)


def main():
    check = Checks()
    env = dict(os.environ, TERM="xterm-256color")
    app = Pty(node_argv(RUNTIME, "main.js"), env, cwd=EXAMPLE)

    app.pump(2.5)
    screen = app.render()
    check("both windows drawn",
          "Colours, said out loud" in screen and "Saying nothing" in screen, screen)

    display = app.display()
    for row, (attr, fg, bg) in enumerate(EXPECTED):
        line = screen.split("\n")[FIRST[1] + row]
        check(f"line {row + 1} names attribute {attr}", f"colour is {attr}" in line,
              repr(line))
        got = (display.fg_at(FIRST[0], FIRST[1] + row),
               display.bg_at(FIRST[0], FIRST[1] + row))
        check(f"and is painted {fg} on {bg}", got == (fg, bg), f"{got} != {(fg, bg)}")

    # Six different colours, not six lines that happen to say different things.
    seen = {(display.fg_at(FIRST[0], FIRST[1] + row),
             display.bg_at(FIRST[0], FIRST[1] + row)) for row in range(6)}
    check("all six are distinct", len(seen) == 6, str(sorted(seen)))

    got = (display.fg_at(FIRST[0], FIRST[1] + 6), display.bg_at(FIRST[0], FIRST[1] + 6))
    check("the line that 'bypasses the palettes' is magenta on black",
          got == BYPASS, f"{got} != {BYPASS}")

    # And the window below: a canvas that says nothing about colour is painted
    # in whatever the window's own palette gives it, which is not any of the
    # seven above.
    plain = (display.fg_at(FIRST[0], 15), display.bg_at(FIRST[0], 15))
    check("a canvas that names no colour follows the window",
          plain not in seen and plain != BYPASS, str(plain))

    # The original's About box, `\003` centring markers and all.
    app.send(b"\x1ba", settle=1.2)
    about = app.render()
    check("Alt-A opens the About box", "About" in about, about)
    check("its text is centred by TStaticText, not by us",
          "PALETTE EXAMPLE" in about and "Borland C++ Tech Support" in about, about)
    app.send(b" ", settle=0.9)
    check("and OK closes it", "PALETTE EXAMPLE" not in app.render())

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("exit code 0", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
