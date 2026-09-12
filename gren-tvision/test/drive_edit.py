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

So the checks come in four groups. That the editing works at all; that the
caret and the modified flag reach the model on every keystroke while the
document does not; that a render cannot overwrite what the user typed, because
there is nothing in the render to overwrite it with; and that searching is two
steps, because a search needs a string and asking for one is a dialog.
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
F4 = b"\x1bOS"
SHIFT_DOWN = b"\x1b[1;2B"
CTRL_INS = b"\x1b[2;5~"
SHIFT_INS = b"\x1b[2;2~"
CTRL_END = b"\x1b[1;5F"


def field_row(app):
    """The Find dialog's `Text` row, which is the one with the input line on it.

    Read by its label rather than by counting rows, and asserted on *by itself*
    rather than by looking for the text anywhere on the screen -- the document
    behind the dialog says `alpha` too, so a check that searched the whole
    render would pass with an empty field.
    """
    for row in app.render().split("\n"):
        if "Text" in row and "to find" not in row:
            return row
    return None


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
    check = Checks(
        replays=(
            "the document is a file on disk, and the session edits and saves it: "
            "a replay reads what the session left, not what it started from"
        )
    )
    work = tempfile.mkdtemp(prefix="tvedit-")
    try:
        target = os.path.join(work, "note.txt")
        open(target, "w").write("alpha\nbeta\ngamma\nalpha\n")

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
              open(target).read() == "alpha\nXYZbeta\ngamma\nalpha\n",
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
              body(app, 5) == ["alpha", "XYZbeta", "gamma", "alpha", "alpha"],
              str(body(app, 5)))

        #    And into an *input line*, which is the same three commands and was
        #    not always the same clipboard. `TInputLine` reacts to cmCut, cmCopy
        #    and cmPaste exactly as `TEditor` does, so **Edit | Paste** with the
        #    Find dialog up puts what the editor copied into the field -- which
        #    is a real thing to want here, since what you search for is usually
        #    something you are looking at.
        #
        #    It went nowhere until the binding stopped letting views reach
        #    `TClipboard`: that class keeps a fallback store of its own, so a
        #    field and the model filled and read different clipboards on any
        #    machine without a system one. `docs/clipboard.md` has the whole of
        #    it. The Alt keys work from inside a modal dialog because a menu
        #    bar is `ofPreProcess` and is offered every keystroke first.
        app.send(b"\x1bs", settle=0.7)          # Search menu
        app.send(b"f", settle=0.9)              # Find...
        check("the Find dialog is up with an empty field",
              field_row(app) is not None and "alpha" not in field_row(app),
              repr(field_row(app)))
        app.send(SHIFT_INS, settle=1.0)
        check("Shift-Ins fills the dialog's input line from the same clipboard "
              "the editor copied to",
              "alpha" in field_row(app), repr(field_row(app)))
        app.send(b"\x1b", settle=0.7)           # cancel the dialog

        # The Edit menu is told the truth on every keystroke now, out of the
        # three facts `Edited` carries beside the caret. Nothing had a way to
        # ask for these before the API audit, so Undo and Cut were lit whether
        # or not they would do anything.
        #
        # A greyed menu entry draws in the palette's grey, which is what this
        # reads -- unlike a disabled *view*, an entry is only ever looked at,
        # so how it looks is what it does.
        app.send(b"\x1be", settle=0.8)
        menu = app.render()
        undo_row = [i for i, r in enumerate(menu.split("\n")) if "Undo" in r][0]
        cut_row = [i for i, r in enumerate(menu.split("\n")) if "Cut" in r][0]
        undo_ink = app.display().fg_at(
            menu.split("\n")[undo_row].index("Undo"), undo_row)
        cut_ink = app.display().fg_at(
            menu.split("\n")[cut_row].index("Cu"), cut_row)
        # Compared against each other rather than against a number: which grey
        # a disabled entry is drawn in belongs to the palette, and the claim
        # here is that the two entries are in different states -- there is
        # something to undo and there is nothing selected to cut.
        check("Undo and Cut are drawn differently, because only one would do "
              "anything", undo_ink != cut_ink, f"both {undo_ink}")
        check("and it is Cut that is greyed", cut_ink == 90, str(cut_ink))
        app.send(b"\x1b", settle=0.5)

        # The Insert key is the user's and not the model's, so overwrite mode
        # is a fact the model is told rather than one it sets -- and the status
        # line says it where every editor since 1983 has.
        check("the status line starts in insert mode", "INS" in app.render(),
              app.render().split("\n")[-2])
        app.send(b"\x1b[2~", settle=0.6)
        check("and the Insert key is reported, not merely obeyed",
              "OVR" in app.render(), app.render().split("\n")[-2])
        app.send(b"\x1b[2~", settle=0.6)
        check("and back again", "INS" in app.render(), app.render().split("\n")[-2])

        # Undo from the Edit menu. `"undo"` is a built-in command name, so it
        # reaches the editor without the model handling it at all -- the same
        # bargain demo's Windows menu makes.
        app.send(b"\x1be", settle=0.8)
        app.send(b"\r", settle=1.0)
        check("Undo from the menu never passed through the model",
              body(app, 5) == ["alpha", "XYZbeta", "gamma", "alpha", ""],
              str(body(app, 5)))

        # 6. Search, which is two steps for the same reason saving is: it needs
        #    something only the model has. Saving needs a file and writing one
        #    is a Task; searching needs a string and asking for one is a
        #    dialog. So "find" is not a built-in command name -- Turbo Vision's
        #    cmFind would ask editorDialog for the string, and editorDialog is
        #    deliberately inert here because every prompt it raises is a
        #    message box, which is a nested event loop.
        #
        #    Start from a known document rather than whatever the clipboard
        #    left behind.
        app.send(b"\x1b[1;5H", settle=0.5)      # Ctrl-Home, back to the top
        app.send(b"\x1bs", settle=0.8)
        check("the Search menu opened",
              "Find" in app.render() and "Search again" in app.render(),
              app.render())
        app.send(b"\r", settle=1.2)
        check("Find is a dialog the program put up, not Turbo Vision's",
              "Case sensitive" in app.render() and "Whole words only" in app.render(),
              app.render())
        app.send(b"alpha", settle=0.5)
        app.send(b"\r", settle=1.2)
        check("and the answer came back as an event the model acted on",
              "found" in caption(app) and caption(app).startswith("1:6"),
              caption(app))

        # Search again is the program issuing the same command twice, because
        # the search string is a thing only it has.
        app.send(b"\x1b[18~", settle=1.2)
        check("Search again ran the same search from where the caret is",
              caption(app).startswith("4:6"), caption(app))
        app.send(b"\x1b[18~", settle=1.2)
        check("and says so in the program's own words when there are no more",
              "not found" in caption(app), caption(app))

        # Replace all means the *document*, which is a small divergence from
        # Turbo Vision: its own runs from the caret, so after the search above
        # ran off the end it would replace nothing.
        app.send(b"\x1bs", settle=0.8)
        app.send(b"\x1b[B", settle=0.4)
        app.send(b"\r", settle=1.2)
        check("Replace is the same dialog with one more field",
              "With" in app.render(), app.render())
        app.send(b"alpha", settle=0.4)
        app.send(b"\t", settle=0.4)
        app.send(b"OMEGA", settle=0.4)
        app.send(b"\r", settle=1.5)
        check("Replace all replaced every match in the document",
              body(app, 5) == ["OMEGA", "XYZbeta", "gamma", "OMEGA", ""],
              str(body(app, 5)))
        check("and reported how many",
              "2 replaced" in caption(app), caption(app))

        # 7. Go to line, which is where the caret stops belonging to the
        #    keyboard alone. `setEditorText` puts it at the top and nothing
        #    else could move it, so a program that rewrote a document it had
        #    just read could not put the reader back with it.
        app.send(b"\x1b[1;5H", settle=0.5)      # Ctrl-Home
        app.send(F4, settle=1.2)
        check("Go to line is a dialog too, because a line number is a thing "
              "only the model can ask for",
              "Go to line" in app.render(), app.render())
        app.send(b"\x08" * 4, settle=0.4)
        app.send(b"3", settle=0.4)
        app.send(b"\r", settle=1.2)
        check("and the caret went there, counting from one the way a person "
              "does",
              caption(app).startswith("3:1"), caption(app))

        # A line past the end is the last line, because setEditorCaret is
        # clamped by the walk that finds it rather than by a check -- which is
        # what Down does, and what a caret restored into a document that got
        # shorter has to do.
        app.send(F4, settle=1.2)
        app.send(b"\x08" * 4, settle=0.4)
        app.send(b"999", settle=0.4)
        app.send(b"\r", settle=1.2)
        check("a line past the end is the last line rather than an error",
              caption(app).startswith("5:1"), caption(app))
        check("and the caption says which line that turned out to be, because "
              "the model was told by an Edited event rather than assuming",
              "5:1" in caption(app), caption(app))

        app.send(b"\x1bx", settle=1.0)
        code = app.wait(timeout=6)
        check("exit code 0", code == 0, f"exit={code}")

        return check.report(app)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
