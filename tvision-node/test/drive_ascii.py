#!/usr/bin/env python3
"""examples/ascii.js -- a view whose contents come from JavaScript.

The chart is a `canvas`: JS supplies the lines, TVision paints them, keystrokes
come back to JS by name, and the selection lives in a JS variable. That round
trip is what milestone 3 will need for anything Gren renders itself.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Pty, Checks, node_argv

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = os.path.join(ROOT, "build", "drive-ascii.log")


def decimal(screen):
    m = re.search(r"Dec\s+(\d+)", screen)
    return int(m.group(1)) if m else None


def main():
    check = Checks()
    if os.path.exists(LOG):
        os.remove(LOG)

    env = dict(os.environ, TERM="xterm-256color", TVISION_LOG=LOG)
    app = Pty(node_argv(os.path.join(ROOT, "examples", "ascii.js")), env, cwd=ROOT)

    app.pump(1.5)
    first = app.render()
    check("chart window drawn", "ASCII Chart" in first)
    check("canvas painted by JS", "@ABCDEFGHIJKLMNOPQRSTUVWXYZ" in first)
    check("code page 437, not Unicode's idea of it", "☺☻♥" in first,
          "row 0 should be the CP437 dingbats")
    check("starts on character 0", decimal(first) == 0, str(decimal(first)))

    # Arrows: two right, four down = 1 + 4*32 = 129.
    app.send(b"\x1b[C", settle=0.3)
    app.send(b"\x1b[B" * 4, settle=0.6)
    check("arrow keys reach JS", decimal(app.render()) == 129,
          f"got {decimal(app.render())}")

    # Any printable key jumps to that character, as the original does.
    app.send(b"A", settle=0.5)
    check("printable keys reach JS", decimal(app.render()) == 65,
          f"got {decimal(app.render())}")

    app.send(b"\x1b[H", settle=0.5)   # Home
    check("named keys reach JS", decimal(app.render()) == 0,
          f"got {decimal(app.render())}")

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("exit code 0", code == 0, f"exit={code}")
    check("onExit saw the JS-side model",
          "last selection was 0" in app.screen(), app.screen()[-200:])

    logged = open(LOG).read() if os.path.exists(LOG) else ""
    check("keys arrived by name",
          "key: Right" in logged and "key: Down" in logged and "key: Home" in logged,
          repr(logged[:300]))

    return check.report(app, extra="--- log ---\n" + logged.rstrip()[:400])


if __name__ == "__main__":
    sys.exit(main())
