#!/usr/bin/env python3
"""predc's status line: no tools on it, and one sentence about pasting that
fits whatever terminal it finds itself in.

**The tools came off.** Every tool that went on the bar had to come off again
when the next one arrived, and the fifth never fitted at all -- `Alt-U` has
been menu-only since the day the Unicode decoder was written, so a bar listing
four of five tools was already lying about what predc has. All five keep their
Alt-key on the Tools menu, and `TMenuBar` is `ofPreProcess` exactly as
`TStatusLine` is, so the shortcuts still work from a window with a focused
canvas in it. That is the first thing checked here, because "the shortcut still
works" is the whole premise of taking it off the bar.

**The room bought the answer to predc's most-asked question.** Copying and
pasting in a terminal is confusing and every layer of it fails in silence, so
the sentence is on the screen at all times instead of behind a key.

**Two situations, and the checks are about both.** Which routes exist is the
environment's answer -- inside tmux the reliable one is `prefix ]`, with a
display `p` works, over bare ssh `p` can never work and saying so is the point.
How much room there is to say it in is the terminal's, and it changes under the
program: this driver resizes and reads the bar again.

The failure this is really guarding is silent. `TStatusLine::drawSelect` draws
an entry only `if( i + l < size.x )` and has no `else`, so a sentence one column
too long is **dropped whole and without a mark** -- the hint would simply not be
there, on exactly the narrow terminal where somebody most needs it. So the
checks are not only "the right words appear" but "the row still fits", measured
at four widths.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

TOOLS = ["ASCII", "RPN", "Hex", "Time", "Unicode"]


def bar(app):
    """The status line, which is the last row of the terminal."""
    lines = app.render().split("\n")
    return lines[app.rows - 1].rstrip()


def launch(where, cols=80, rows=24):
    """predc in a dressed environment. `where` picks which situation."""
    env = dict(os.environ, TERM="xterm-256color",
               HOME=tempfile.mkdtemp(prefix="predc-home-"))
    env.pop("XDG_CONFIG_HOME", None)
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "TMUX", "STY",
                 "SSH_CONNECTION", "SSH_TTY", "SSH_CLIENT"):
        env.pop(name, None)
    if where == "tmux":
        env["TMUX"] = "/tmp/tmux-1000/default,4242,0"
    elif where == "screen":
        env["STY"] = "4242.pts-0.host"
    elif where == "display":
        env["DISPLAY"] = ":0"
    elif where == "ssh":
        env["SSH_CONNECTION"] = "10.0.0.2 51000 10.0.0.1 22"
    app = Pty(node_argv(LAUNCHER), env, cwd=tempfile.mkdtemp(),
              size=(cols, rows))
    app.pump(2.0)
    return app


def main():
    check = Checks()

    # 1. What is on the bar, and what is deliberately not.
    app = launch("ssh")
    line = bar(app)
    check("Exit is on the bar", "Alt-X" in line and "Exit" in line, line)
    check("and Close, which is the one window operation to be able to find",
          "Alt-F3" in line and "Close" in line, line)
    for tool in TOOLS:
        check(f"and {tool} is not, because a list that cannot grow is not one",
              tool not in line, line)

    # A tool taken off the bar has to still be reachable, and by the same key.
    # `Alt-U` is the one that was never on it: menu-only since it was written,
    # which is the evidence that the bar had stopped listing what predc has.
    app.send(b"\x1bu", settle=1.2)
    check("Alt-U still opens the decoder, off the menu rather than the bar",
          "Unicode" in app.render(), app.render())
    app.send(b"\x1b\x1bOR", settle=1.0)          # Alt-F3
    app.send(b"\x1bd", settle=1.2)
    check("and Alt-D the hex viewer", "Hex Dump" in app.render(), app.render())
    app.send(b"\x1b\x1bOR", settle=1.0)

    # 2. The sentence knows where it is. Bare ssh: `p` is the thing that will
    #    never work here, and naming it is the point rather than an omission.
    line = bar(app)
    check("over bare ssh the bar says what to press",
          "Ctrl-Shift-V" in line and "Shift-Ins" in line, line)
    check("and names p as the one that will not work",
          "not p" in line or "never p" in line or "cannot work" in line, line)
    check("and points at the long answer",
          "F1" in line, line)
    app.send(b"\x1bx", settle=1.0)
    app.wait(timeout=6)

    # 3. Inside tmux the reliable route is tmux's own, and it is named.
    app = launch("tmux")
    line = bar(app)
    check("inside tmux the bar names prefix ]", "prefix ]" in line, line)
    check("and still what to press first", "Ctrl-Shift-V" in line, line)
    check("and F1 survives at eighty columns", "F1" in line, line)

    # 4. The width is the other half, and it moves under the program.
    #    Wider says more; narrower says less; neither overflows.
    app.resize(120, 24)
    wide = bar(app)
    check("a wider terminal says more, not the same",
          len(wide) > len(line), f"{len(line)} -> {len(wide)}")
    check("and spends the room on the sentence rather than on nothing",
          "into a field" in wide, wide)

    app.resize(60, 24)
    narrow = bar(app)
    check("a narrower one says less", len(narrow) < len(line),
          f"{len(line)} -> {len(narrow)}")
    check("and keeps the key that leads to the rest of it",
          "F1" in narrow, narrow)
    check("and keeps Exit, which is the other thing nobody should lose",
          "Exit" in narrow, narrow)

    # The check the silence makes necessary: an entry one column too long is
    # dropped whole and says nothing, so "it fits" has to be asserted and not
    # assumed. Read at every width, including the two above.
    for cols in (40, 60, 80, 100, 132):
        app.resize(cols, 24)
        line = bar(app)
        check(f"the bar fits in {cols} columns", len(line) <= cols,
              f"{len(line)} > {cols}: {line!r}")
        check(f"and is still a bar at {cols}", "Exit" in line, line)

    # 5. F1 off the bar opens the window the sentence is pointing at. The bar
    #    is clickable as well as bound, which is why the hint carries the key
    #    rather than being decoration.
    app.resize(80, 24)
    app.send(b"\x1bOP", settle=1.5)              # F1
    check("F1 opens the copying and pasting help",
          "Copying and pasting" in app.render() or "clipboard" in app.render().lower(),
          app.render())
    app.send(b"\x1bx", settle=1.0)
    app.wait(timeout=6)

    # 6. A display changes the sentence again, because there `p` does work.
    app = launch("display")
    line = bar(app)
    check("with a display the bar offers p", " p " in line or "p " in line, line)
    check("and does not say it cannot work",
          "cannot work" not in line and "never p" not in line, line)
    app.send(b"\x1bx", settle=1.0)
    app.wait(timeout=6)

    # 7. screen is tmux's other half, and the one whose sentence is longest --
    #    so it is the variant that decides the widest rung.
    app = launch("screen", cols=100)
    line = bar(app)
    check("inside screen the bar names its own paste key",
          "Ctrl-a ]" in line, line)
    check("and it fits the hundred columns it was given", len(line) <= 100,
          f"{len(line)}: {line!r}")

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("Alt-X exits", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
