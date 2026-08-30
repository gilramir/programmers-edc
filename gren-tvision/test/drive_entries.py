#!/usr/bin/env python3
"""examples/entries -- a Turbo Vision application written in Gren.

Every check here crosses the whole stack -- Gren model, JSON over a port, the
diff in tui.js, the N-API binding, TVision, and the terminal -- and back.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # the Gren package
EXAMPLE = os.path.join(ROOT, "examples", "entries")
RUNTIME = os.path.join(ROOT, "..", "gren-tvision-runtime", "bin", "gren-tui.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, latest_int, node_argv

TICKS = r"ticks: (\d+)"


def active(screen, title):
    """Is the window with this title the active one?

    Turbo Vision draws the active window's frame with a double line and every
    other window's with a single one, which is the only evidence on screen of
    where focus went -- and the two windows here share their top row, so this
    reads the frame run immediately left of the title rather than the row.
    """
    for line in screen.split("\n"):
        at = line.find(title)
        if at < 0:
            continue
        i = at - 1
        while i >= 0 and line[i] == " ":
            i -= 1
        if i >= 0 and line[i] in "═─":
            return line[i] == "═"
    return None

# The list window's close box. Window rectangles are *desktop* coordinates, so
# y=1 is the second row under the menu bar -- screen row 3, counting from 1.
CLOSE_BOX = (5, 3)


def main():
    check = Checks()
    env = dict(os.environ, TERM="xterm-256color")
    app = Pty(node_argv(RUNTIME, "main.js"), env, cwd=EXAMPLE)

    # 1. The first screen is a render of the Gren model.
    app.pump(2.0)
    first = app.render()
    check("windows came from view : Model -> Ui", "Entries (3)" in first)
    check("list contents came from the model",
          all(x in first for x in ("Turbo Vision", "Borland", "Gren")))
    check("menu bar and status line came from Gren",
          "Entries" in first and "Alt-A Add" in first)

    # 2. Time.every is an ordinary subscription, and it drives the screen.
    before = latest_int(app.render(), TICKS)
    app.pump(3.2)
    after = latest_int(app.render(), TICKS)
    check("a Gren subscription repaints the TUI",
          before is not None and after is not None and after > before,
          f"ticks {before} -> {after}")

    # 3. Opening a dialog is a Cmd; its result comes back as a Msg.
    app.send(b"\x1ba", settle=1.2)
    check("dialog opened by a Cmd", "Add an entry" in app.render())

    during_before = latest_int(app.render(), TICKS)
    app.pump(3.2)
    during_after = latest_int(app.render(), TICKS)
    check("Gren keeps running behind a modal dialog", during_after > during_before,
          f"ticks stuck at {during_before}")

    app.send(b"Elm", settle=0.4)
    app.send(b"\r", settle=1.2)          # OK is the default button
    added = app.render()
    check("dialog result reached update", "Entries (4)" in added,
          "the model did not grow")
    check("the new entry was rendered", "Elm" in added, "list was not patched")

    # A dialog hands the caret back to whatever had it before, which is not
    # necessarily the list the entry just went into. Tui.focus names a view
    # here rather than a window, and TView::focus walks up its owner chain --
    # so the window it is in becomes the active one.
    check("the caret went to the list the entry went into",
          active(added, "Entries (4)"),
          "the dialog gave focus back to whatever had it before")

    # 4. An event from a view becomes a Msg, and the answer is patched back in.
    # Home, then Down, is the second entry wherever the click happened to land.
    # Space selects; Enter does nothing.
    app.click(6, 5)
    app.send(b"\x1b[H", settle=0.3)
    app.send(b"\x1b[B", settle=0.3)
    app.send(b" ", settle=1.0)
    check("selection round-tripped through the model",
          "Selected: Borland" in app.render(), app.render()[12 * 81:14 * 81])

    # 5. The user closes a window from its frame. Without the onClose event the
    #    model would still believe it is open and the next render would put it
    #    straight back.
    app.click(*CLOSE_BOX)
    app.pump(2.0)                        # let a tick force another render
    check("closing a window told the model", "Entries (" not in app.render(),
          "the window came back, so WindowClosed never arrived")

    # 6. And the model can put it back -- with the caret, which is the half a
    #    render cannot express. This is also the deferred path: the focus
    #    message names a window the same update creates, and an update's Cmd
    #    and its render are one Cmd.batch, so the message can leave before the
    #    window it names exists.
    app.send(b"\x1bl", settle=1.2)
    reopened = app.render()
    check("the model can reopen it", "Entries (4)" in reopened)
    check("and focus a window the same update created",
          active(reopened, "Entries (4)"),
          "the focus arrived before the render that built the window")

    # 7. The gap this closed: Alt-L on a window that was already open did
    #    nothing at all. The flag was already True, the render found no
    #    difference, and the window stayed where it was. Take the focus away
    #    with a click and ask for it back.
    app.click(50, 3, settle=0.8)
    check("clicking the clock window activated it", active(app.render(), "Gren"))
    app.send(b"\x1bl", settle=1.2)
    raised = app.render()
    check("Alt-L raises a window that is already open",
          active(raised, "Entries (4)"), "the list did not come forward")
    check("and the window it came forward over went quiet",
          active(raised, "Gren") is False)

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("exit code 0", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
