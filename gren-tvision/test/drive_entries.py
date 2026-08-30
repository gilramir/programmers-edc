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

    # 4. An event from a view becomes a Msg, and the answer is patched back in.
    # The first click on an inactive window is spent activating it, so the
    # keyboard does the actual choosing: Home, then Down, is the second entry
    # wherever the click happened to land. Space selects; Enter does nothing.
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

    # 6. And the model can put it back.
    app.send(b"\x1bl", settle=1.2)
    check("the model can reopen it", "Entries (4)" in app.render())

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("exit code 0", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
