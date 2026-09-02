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


def menu(app, item, entry):
    """Open a pull-down by clicking its name, then click the `entry`-th line in
    it (1-based). Row 0 is the menu bar and row 1 is the box's own border, so
    the first entry is on row 2 -- which is row 3 to `click`."""
    bar = app.render().split("\n")[0]
    at = bar.index(item)
    app.click(at + 1, 1, settle=0.6)
    app.click(at + 3, entry + 2, settle=0.9)


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
          all(x in rows[0] for x in ("File", "Window", "Help")), rows[0])
    check("the status line is the bottom row",
          all(x in rows[24] for x in ("Exit", "ASCII", "Time", "Close")), rows[24])
    # A status line is truncated at the terminal's width without a word about
    # it, so a bar that has grown one entry too long is a bar that quietly
    # stops mentioning how to close a window. Zoom and Next came off for the
    # fourth tool; this is what stops the fifth from pushing Close off too.
    check("and it fits in eighty columns", len(rows[24].rstrip()) < 80,
          f"{len(rows[24].rstrip())} columns: {rows[24]}")
    check("Zoom and Next are the two that came off", 
          "Zoom" not in rows[24] and "Next" not in rows[24], rows[24])
    check("the desktop is empty until a tool is opened",
          not any("─" in row or "═" in row for row in rows[1:24]),
          "\n".join(rows[1:6]))

    # About is a message box, so it centres itself -- which is the only thing
    # in the shell that needs the desktop's size, and therefore the only
    # evidence that `Resized` reached the model at startup.
    menu(app, "Help", 1)
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
    menu(app, "Help", 1)
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

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("Alt-X exits, and cleanly", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
