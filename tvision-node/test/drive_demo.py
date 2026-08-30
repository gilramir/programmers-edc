#!/usr/bin/env python3
"""Milestone 2: the pumped form.

The interesting checks here are not "did a window appear" but "did Node keep
working while the window was up" -- a clock painted by setInterval, and a
directory listing produced by await fs.readdir(). Under milestone 1's blocking
run(), neither could happen at all.

The last check codifies the known wart rather than papering over it: a modal
dialog is a nested event loop inside TVision, so it freezes Node solid.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Pty, Checks, latest_int, node_argv

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = os.path.join(ROOT, "build", "drive-demo.log")

TICKS = r"ticks: (\d+)"


def main():
    check = Checks()
    if os.path.exists(LOG):
        os.remove(LOG)

    env = dict(os.environ, TERM="xterm-256color", TVISION_LOG=LOG)
    app = Pty(node_argv(os.path.join(ROOT, "examples", "demo.js")), env, cwd=ROOT)

    # 1. start() returned and the app is up -- which already means Node's loop
    #    is the one running, because nothing else would be pumping it.
    app.pump(1.5)
    first = app.screen()
    check("menu bar drawn", "File" in first and "View" in first)
    check("status line drawn", "Alt-D Directory" in first)

    # 2. The clock window, and then the point of the whole milestone: the
    #    screen changes on its own, from a JS setInterval, while TVision is up.
    app.send(b"\x1bc", settle=1.2)
    check("clock window opened", "Clock" in app.render())

    before = latest_int(app.render(), TICKS)
    app.pump(3.2)
    after = latest_int(app.render(), TICKS)
    check("setInterval repaints the TUI", before is not None and after is not None and after > before,
          f"ticks {before} -> {after}")

    # 3. Async I/O: the listing is produced by await fs.readdir().
    app.send(b"\x1bd", settle=1.5)
    listing = app.render()
    check("directory window opened", "Directory:" in listing)
    check("listing came from fs.readdir", "package.json" in listing and "binding.gyp" in listing,
          "expected this package's own files")
    check("listing reports its own count", "read while the UI ran" in listing,
          "the info line is only 41 columns wide -- did the text outgrow it?")

    # 4. Selecting an entry goes JS -> await fs.stat -> back into the view.
    app.send(b"\x1b[B", settle=0.4)   # Down, off the "../" row
    app.send(b" ", settle=1.2)        # Space selects; TListViewer ignores Enter
                                      # entirely (tlstview.cpp), just like
                                      # TButton does.
    described = app.render()
    check("selection statted asynchronously",
          "bytes" in described or "directory" in described,
          "info line never updated")

    # 5. Modality without the freeze. The dialog takes all the input -- that
    #    is what modal means -- but the clock behind it keeps ticking, because
    #    it is driven by the pump rather than by a nested loop inside TVision.
    app.send(b"\x1bg", settle=1.0)
    check("modal dialog opened", "Go to directory" in app.render())

    # Read the counter only once the dialog is up: the second between sending
    # the key and the dialog opening is still live, and the clock ticks in it.
    before_modal = latest_int(app.render(), TICKS)
    app.pump(3.2)
    during = latest_int(app.render(), TICKS)
    check("node keeps running behind a modal dialog", during > before_modal,
          f"ticks stuck at {before_modal} -- is the dialog nesting a loop again?")
    # And the dialog really was modal: keys went to it, not to the app behind
    # it -- Alt-D would otherwise have opened the directory window over the top.
    check("input went to the dialog, not the app",
          "Go to directory" in app.render())
    app.send(b"\x1b", settle=1.0)     # cancel

    app.pump(1.0)
    after_modal = latest_int(app.render(), TICKS)
    check("still ticking after the dialog closes", after_modal > during,
          f"ticks {during} -> {after_modal}")

    # 6. Quit through the status line, and let onExit run.
    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("process exited", code is not None, "still running")
    check("exit code 0", code == 0, f"exit={code}")

    tail = app.screen()
    m = re.search(r"ticks while it ran: (\d+)", tail)
    check("onExit ran with a live tick count", m is not None and int(m.group(1)) > 2,
          m.group(0) if m else "no onExit line")

    logged = open(LOG).read() if os.path.exists(LOG) else ""
    check("commands and selections reached JS",
          "command: openClock" in logged and "select: dirList" in logged,
          repr(logged[:300]))

    return check.report(app, extra="--- log ---\n" + (logged.rstrip()[:800] or "(empty)"))


if __name__ == "__main__":
    sys.exit(main())
