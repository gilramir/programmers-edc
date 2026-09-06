#!/usr/bin/env python3
"""Every tool, opened under one colour scheme, with nothing asserted about it.

The checks here are almost all "the window opened", which is not what this
file is for. What it is for is the one check `Checks.report` makes on its own:
that nothing on any screen the driver looked at was drawn in the colour behind
it. `harness.same_colour` is the whole of the assertion and every driver in the
repo now carries it -- but every other driver runs the default scheme, because
that is what a fresh `HOME` gets, so between them they only ever sweep one
ground.

A theme is two halves that a `Tui.Theme` cannot join. The palette recolours
everything gren-tvision draws; the inks are what the tools' own canvases paint
with, and a palette cannot reach a `Tui.Span`. So a scheme change moves the
ground out from under every ink in the program at once, and an ink that stops
contrasting still draws -- which is exactly how the hex viewer's offset column
spent a month at `fg=34 bg=44`, invisible, with a green suite.

Two suites and not three, because Borland is the default and forty-four
drivers already walk it. Midnight and Gren are the grounds nobody sweeps, and
Gren is the interesting one: it is the only light scheme, and on a light ground
every bright hue is a candidate.

The tools are opened and left open. Closing each one would double the driver's
length to test what `drive_shell.py` already tests, and a stack of nine windows
is a fair screen to sweep anyway -- a frame drawn over another window's ink is
one more pair of colours nobody chose together.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv


# The Tools entry to click, the title that then appears on a frame, and what to
# type once it is open so that the tool paints with its own inks rather than
# showing an empty canvas. A window with nothing in it is a window with nothing
# to get wrong.
#
# Clicked by name rather than opened with its `Alt` key, which is not fussiness:
# a tool's own menu goes on the bar while it is open, and a bar title claims its
# `Alt` letter for as long as it is there. `~C~alc` takes `Alt-C` away from the
# time converter, so an `Alt`-driven sweep opens tools in whatever order does
# not collide, and silently stops opening one the day a menu is retitled.
TOOLS = [
    ("ASCII chart", "ASCII", b""),
    ("RPN calculator", "RPN Calculator", b"12\r34\r+"),
    ("Time converter", "Time converter", b""),
    ("Unicode decoder", "Unicode", b"41 c3 a9 e4 b8 ad f0 9f 92 a1"),
    ("Calendar", "Calendar", b""),
    ("Encode / decode", "Encode / decode", b"predc"),
    ("Random values", "Random values", b""),
    ("Environment variables", "Environment", b""),
    ("Hex dump viewer", "Hex Dump", b""),
]


def open_tool(app, entry, settle=1.4):
    """Click `entry` in the Tools pull-down, wherever the box put it."""
    bar = app.render().split("\n")[0]
    app.click(bar.index("Tools") + 1, 1, settle=0.7)
    for row, line in enumerate(app.render().split("\n")):
        if entry in line and "│" in line:
            app.click(line.index(entry) + 1, row + 1, settle=settle)
            return True
    return False


def pairs(app):
    """Every (ink, ground) on the screen now, so a sweep can prove it swept.

    A driver that opened nine empty windows and asserted nothing was invisible
    would pass on a program with no colour in it at all. This is what says the
    screens being swept are painted ones.
    """
    screen = app.display()
    seen = set()
    for row in range(screen.rows):
        for col in range(screen.cols):
            if screen.grid[row][col] != " ":
                seen.add(screen.attrs[row][col])
    return seen


def sweep(key, name):
    check = Checks()
    home = tempfile.mkdtemp(prefix="predc-ink-")
    os.makedirs(os.path.join(home, ".config", "predc"))
    with open(os.path.join(home, ".config", "predc", "config.toml"), "w") as f:
        f.write(f'theme = "{key}"\n')
    # `COLORTERM=truecolor` because two of the three schemes are `Rgb`
    # throughout: without it TVision quantises them to the sixteen, and a sweep
    # of a quantised palette is a sweep of colours nobody chose.
    env = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor", HOME=home)
    env.pop("XDG_CONFIG_HOME", None)
    # Bigger than eighty by twenty-five: the tools that size themselves from
    # the desktop get more of themselves on the screen, and more of a canvas is
    # more inks.
    app = Pty(node_argv(LAUNCHER), env, cwd=tempfile.mkdtemp(), size=(110, 34))

    app.pump(2.5)
    check(f"predc started in the {name} scheme", "File" in app.render().split("\n")[0],
          app.render().split("\n")[0])

    ground = pairs(app)
    check("the empty desktop is painted", len(ground) >= 2, str(sorted(map(str, ground))))

    for entry, title, typed in TOOLS:
        open_tool(app, entry)
        opened = title in app.render()
        check(f"{title} opened", opened, app.render())
        if opened and typed:
            app.send(typed, settle=0.9)
        # Reading the screen is what runs the invariant over it; the count is
        # only here so that a tool that silently stopped painting cannot make
        # this driver pass by having nothing to look at.
        check(f"and {title} painted with something",
              len(pairs(app)) > 2, str(sorted(map(str, pairs(app)))))

    # One dialog, since a dialog is drawn in the *dialog* half of the
    # palette and a window in the window half -- two grounds, and the tools'
    # inks meet both.
    app.send(b"\x1b\x1bOP", settle=1.2)          # F1, the help window
    check("the help window opened", "Help" in app.render(), app.render())

    app.send(b"\x1bx", settle=1.2)
    code = app.wait(timeout=8)
    check("Alt-X exits, and cleanly", code == 0, f"exit={code}")

    return check.report(app)
