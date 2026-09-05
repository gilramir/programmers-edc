#!/usr/bin/env python3
"""predc's shell: the menu bar, the status line, the About box, and exit.

There are no tools in it yet, which makes this the one test that can say what
the shell costs on its own. Everything it checks is the part of the program
that will still be true when four tools are open on top of it.

It runs `bin/predc.js` and not gren-tvision's `gren-tui` bin, deliberately: the
launcher is part of what an application is, and it is where the time
converter's `Intl` port pair is subscribed. If the launcher stops resolving the
runtime -- or stops attaching that second pair -- this is what says so.
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


def menu(app, item, letter, settle=0.9):
    """Open a pull-down by clicking its name, then pick an entry by the letter
    it underlines.

    By the letter and **not** by counting lines, which is the rule the hex
    viewer's driver already writes down and this one learned the same way:
    adding **Copying and pasting** to the Help menu moved About down two rows
    and broke three checks that were about neither.
    """
    bar = app.render().split("\n")[0]
    app.click(bar.index(item) + 1, 1, settle=0.6)
    app.send(letter, settle=settle)


def box_edges(screen, title):
    """(left, right) frame columns of the active dialog with this title."""
    for line in screen.split("\n"):
        if title in line and "╔" in line and "╗" in line:
            return (line.index("╔"), line.rindex("╗"))
    return None


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
    screen = app.render()
    rows = screen.split("\n")

    check("the launcher started the app", "File" in rows[0], rows[0])
    check("the menu bar came from the view",
          all(x in rows[0] for x in ("File", "Tools", "Options", "Window", "Help")),
          rows[0])
    check("the status line is the bottom row",
          all(x in rows[24] for x in ("Exit", "Close", "Paste", "F1")), rows[24])
    # A status line is truncated at the terminal's width without a word about
    # it -- worse, an entry that does not fit is dropped whole and in silence
    # -- so a bar that has grown one entry too long is a bar that quietly stops
    # mentioning how to close a window. That is what took the tools off it
    # altogether and put the paste hint there instead; the hint measures itself
    # against the width it is given, and `drive_statusbar.py` is where the
    # ladder and the four situations are checked. Here it is only that the bar
    # fits, because this file is about the shell.
    check("and it fits in eighty columns", len(rows[24].rstrip()) < 80,
          f"{len(rows[24].rstrip())} columns: {rows[24]}")
    check("no tool is on it, because a list that cannot grow is not a list",
          not any(t in rows[24] for t in ("ASCII", "RPN", "Hex", "Time", "Unicode")),
          rows[24])
    check("Zoom and Next are not on it either",
          "Zoom" not in rows[24] and "Next" not in rows[24], rows[24])
    check("the desktop is empty until a tool is opened",
          not any("─" in row or "═" in row for row in rows[1:24]),
          "\n".join(rows[1:6]))

    # About is a message box, so it centres itself -- which is the only thing
    # in the shell that needs the desktop's size, and therefore the only
    # evidence that `Resized` reached the model at startup.
    menu(app, "Help", b"a")
    about = app.render()
    check("About opened", "every-day carry" in about, about)
    edges = box_edges(about, "About")
    check("and it centred itself on the desktop",
          edges is not None and abs(edges[0] - (79 - edges[1])) <= 1,
          f"frame at {edges} of 80 columns")

    app.send(b"\r", settle=0.9)
    check("and OK closed it", "every-day carry" not in app.render(), app.render())

    # The desktop is 80x23 when the model has not been told otherwise, and the
    # About box would be off-centre afterwards if Resized never arrived. Shrink
    # the terminal and open it again: same test, a size the default cannot fake.
    app.resize(70, 20)
    menu(app, "Help", b"a")
    edges = box_edges(app.render(), "About")
    check("Resized reaches the model: the box re-centres on the new width",
          edges is not None and abs(edges[0] - (69 - edges[1])) <= 1,
          f"frame at {edges} of 70 columns")
    app.send(b"\r", settle=0.9)

    # A key that came off the bar still works, because the Window menu carries
    # the same shortcut and `TMenuBar` is `ofPreProcess` exactly as
    # `TStatusLine` is. Worth a check rather than a comment: it is the whole
    # reason dropping two entries was safe.
    app.send(b"\x1ba", settle=1.2)
    check("a tool opens", "ASCII" in app.render() and "0_" in app.render(), app.render())
    app.send(b"\x1b\x1b[13~", settle=1.2)
    check("and Alt-F3 still closes it, off the status line and onto the menu's",
          "0_" not in app.render(), app.render())

    # The fifth tool is the case that comment anticipated. There is no room for
    # it on the status line, so its `Alt-U` is the accelerator on its *menu*
    # entry -- and the test that matters is with another tool's canvas holding
    # the focus, because a focused canvas eats plain letters and would eat this
    # one too if the menu bar were not `ofPreProcess`.
    app.send(b"\x1bd", settle=1.4)
    check("the hex viewer takes the focus", "Hex Dump" in app.render(), app.render())
    # The last row, not row 24: the terminal was made 70x20 a few lines up and
    # never put back, which is exactly the kind of thing a hard-coded row
    # number does not survive.
    check("and the status line has no room for a fifth tool on it",
          "Unicode" not in app.render().split("\n")[-1], app.render().split("\n")[-1])
    app.send(b"\x1bu", settle=1.4)
    check("Alt-U opens the decoder anyway, from the menu entry's own key, "
          "past a canvas that has the focus",
          "Unicode" in app.render(), app.render())
    app.send(b"\x1b\x1b[13~", settle=1.0)
    app.send(b"\x1b\x1b[13~", settle=1.0)

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("Alt-X exits, and cleanly", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
