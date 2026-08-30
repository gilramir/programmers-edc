#!/usr/bin/env python3
"""examples/form.js -- clusters, labels, nested submenus, command enabling."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Pty, Checks, node_argv

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = os.path.join(ROOT, "build", "drive-form.log")


def main():
    check = Checks()
    if os.path.exists(LOG):
        os.remove(LOG)

    env = dict(os.environ, TERM="xterm-256color", TVISION_LOG=LOG)
    app = Pty(node_argv(os.path.join(ROOT, "examples", "form.js")), env, cwd=ROOT)

    app.pump(1.5)
    check("records window drawn", "no records yet" in app.render())

    # 1. "List records" is disabled until there is one. A disabled command does
    #    nothing at all, which is the only way to observe it from a screen
    #    scrape -- greying is a colour change, and colour is what we strip.
    app.send(b"\x1bl", settle=0.8)
    logged = open(LOG).read() if os.path.exists(LOG) else ""
    check("a disabled command does not fire", "command: list" not in logged,
          repr(logged))

    # 2. The form itself.
    app.send(b"\x1bn", settle=1.0)
    form = app.render()
    check("form dialog drawn", "New record" in form)
    check("check boxes drawn", "[X] Terminals" in form and "[ ] Pascal" in form,
          "cluster not rendered")
    check("radio buttons drawn", "( ) Phone" in form, "cluster not rendered")

    # 3. Labels are bound to controls: Alt-M focuses Name, Alt-H focuses Phone.
    #    Not Alt-N and Alt-P -- the status line's Alt-N is global and beats even
    #    a modal dialog, and Alt-P is claimed by the Phone radio button. Hotkeys
    #    are one flat namespace and the first claimant wins.
    app.send(b"\x1bm", settle=0.4)
    app.send(b"Ada Lovelace", settle=0.4)
    app.send(b"\x1bh", settle=0.4)
    app.send(b"555-1815", settle=0.4)
    filled = app.render()
    check("label hotkeys focused the fields",
          "Ada Lovelace" in filled and "555-1815" in filled, "typing went elsewhere")

    # 4. A check box hotkey toggles that box.
    app.send(b"\x1br", settle=0.4)
    check("check box hotkey toggled it", "[X] Retrocomputing" in app.render(),
          "Alt-R did not tick the box")

    # 5. Enter presses the default button (OK).
    app.send(b"\r", settle=1.0)
    listed = app.render()
    check("record collected and listed", "Ada Lovelace" in listed and "555-1815" in listed,
          "the record did not reach the window")
    check("cluster values came back",
          "Retrocomputing" in listed and "Terminals" in listed,
          "check box state was not read")
    check("radio value came back", "via Email" in listed, "radio index was not read")

    # 6. With a record in hand, the command is enabled and now fires.
    app.send(b"\x1bl", settle=0.8)
    logged = open(LOG).read()
    check("an enabled command fires", "command: list" in logged, repr(logged[-200:]))

    # 7. A submenu inside a submenu.
    app.send(b"\x1bf", settle=0.5)
    check("submenu marked as one", "Samples" in app.render() and "►" in app.render(),
          "no submenu arrow")
    app.send(b"s", settle=0.5)
    check("nested submenu opened", "Grace Hopper" in app.render(), "submenu did not open")
    app.send(b"m", settle=0.5)
    check("submenu inside the submenu", "Niklaus Wirth" in app.render(),
          "third level did not open")
    app.send(b"\x1b\x1b\x1b", settle=0.5)

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("exit code 0", code == 0, f"exit={code}")
    check("onExit saw the collected record", "1 record(s)" in app.screen(),
          app.screen()[-200:])

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
