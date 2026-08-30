#!/usr/bin/env python3
"""examples/edit -- tvedit, in Gren.

The milestone the coverage list called "not a gap", and what it is really
about is where the state lives.

Every other example in this suite owns its state in the model and re-renders
it. A document is the first thing too big for that -- `view` runs on every
tick of every subscription, and a file has no business in a render message --
so the editor owns the buffer and the program owns the file. The document
crosses the port twice per file, in through `setEditorText` and out through
`readEditor`, and what arrives in between is an `Edited` event carrying three
numbers.

So the checks come in three groups. That the editing works at all; that the
caret and the modified flag reach the model on every keystroke while the
document does not; and that a render cannot overwrite what the user typed,
because there is nothing in the render to overwrite it with.
"""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLE = os.path.join(ROOT, "examples", "edit")
RUNTIME = os.path.join(ROOT, "..", "gren-tvision-runtime", "bin", "gren-tui.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

F2 = b"\x1bOQ"
SHIFT_DOWN = b"\x1b[1;2B"
CTRL_INS = b"\x1b[2;5~"
SHIFT_INS = b"\x1b[2;2~"
CTRL_END = b"\x1b[1;5F"


def body(app, rows=6):
    """The editor's visible lines, trimmed of the frame and the scroll bar."""
    screen = app.render().split("\n")
    return [screen[3 + i][2:40].rstrip() for i in range(rows)]


def caption(app):
    """The line:column caption, which is the model's text and not the view's."""
    for line in app.render().split("\n"):
        stripped = line[2:60].strip()
        if ":" in stripped[:6] and stripped[0].isdigit():
            return stripped
    return ""


def title(app):
    for line in app.render().split("\n"):
        if "note.txt" in line and ("╔" in line or "┌" in line):
            return line
    return ""


def main():
    check = Checks()
    work = tempfile.mkdtemp(prefix="tvedit-")
    try:
        target = os.path.join(work, "note.txt")
        open(target, "w").write("alpha\nbeta\ngamma\n")

        env = dict(os.environ, TERM="xterm-256color")
        app = Pty(node_argv(RUNTIME, "main.js", target), env, cwd=EXAMPLE)
        app.pump(2.5)

        # 1. The document went in through setEditorText, which is a Cmd the
        #    model issued when its read Task landed -- not part of any render.
        check("the file was read and put into the editor",
              body(app, 3) == ["alpha", "beta", "gamma"], str(body(app, 3)))
        check("and the caret starts at the top", caption(app).startswith("1:1"),
              caption(app))
        check("an unmodified document has no marker in the title",
              "note.txt" in title(app) and "*" not in title(app), title(app))

        # 2. Every keystroke reports, and what it reports is three numbers.
        app.send(b"\x1b[B", settle=0.5)
        check("moving the caret reaches the model", caption(app).startswith("2:1"),
              caption(app))
        app.send(b"XYZ", settle=0.8)
        check("typing goes into the editor's own buffer",
              body(app, 3) == ["alpha", "XYZbeta", "gamma"], str(body(app, 3)))
        check("and the column followed it", caption(app).startswith("2:4"),
              caption(app))
        check("the model was told the document is modified",
              "*" in title(app), title(app))

        # 3. A render cannot undo the user's typing, because a render carries
        #    no document. This is the same assertion the filter box makes about
        #    an input line, one size up: resizing forces a re-render of
        #    everything, and the editor's contents are not in it to be resent.
        app.resize(100, 30)
        app.pump(1.2)
        check("a re-render does not touch what was typed",
              body(app, 3) == ["alpha", "XYZbeta", "gamma"], str(body(app, 3)))
        frame = app.render().split("\n")[2]
        check("and the window grew with the terminal",
              frame.rindex("╗") == 98, f"right frame at {frame.rindex('╗')} of 100")
        # And the editor grew inside it, which is `Grows` and not the model:
        # the rectangle the model sends never changed.
        bar = [r for r in app.render().split("\n") if "▲" in r]
        check("and the editor's scroll bar rode the new right edge with it",
              bar and bar[0].index("▲") == 96, str(bar[:1]))
        app.resize(80, 25)
        app.pump(1.2)

        # 4. Saving is two steps, because writing a file is a Task: "save" is
        #    the one editor command deliberately left out of the built-in
        #    names, so it arrives as an event, and the answer comes back as
        #    EditorText.
        app.send(F2, settle=1.5)
        check("F2 wrote the document to disk",
              open(target).read() == "alpha\nXYZbeta\ngamma\n",
              repr(open(target).read()))
        check("and the modified marker cleared",
              "*" not in title(app), title(app))

        # 5. The clipboard and undo are Turbo Vision's, reached by its own keys
        #    and by built-in command names -- neither passes through `update`.
        app.send(b"\x1b[1;5H", settle=0.5)      # Ctrl-Home, back to the top
        app.send(SHIFT_DOWN, settle=0.5)
        app.send(CTRL_INS, settle=0.5)          # copy the first line
        app.send(CTRL_END, settle=0.5)
        app.send(SHIFT_INS, settle=0.8)         # paste it at the end
        check("copy and paste work on the editor's own clipboard",
              body(app, 4) == ["alpha", "XYZbeta", "gamma", "alpha"],
              str(body(app, 4)))

        # Undo from the Edit menu. `"undo"` is a built-in command name, so it
        # reaches the editor without the model handling it at all -- the same
        # bargain demo's Windows menu makes.
        app.send(b"\x1be", settle=0.8)
        app.send(b"\r", settle=1.0)
        check("Undo from the menu never passed through the model",
              body(app, 4) == ["alpha", "XYZbeta", "gamma", ""],
              str(body(app, 4)))

        app.send(b"\x1bx", settle=1.0)
        code = app.wait(timeout=6)
        check("exit code 0", code == 0, f"exit={code}")

        return check.report(app)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
