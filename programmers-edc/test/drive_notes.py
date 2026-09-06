#!/usr/bin/env python3
"""predc's notes: many small documents, one window, one editor.

The only tool in predc that *keeps* something, and every check here is about a
consequence of that.

**The editor owns the buffer**, so switching notes is a round trip -- the
outgoing document has to come back through `readEditor` before the incoming one
can go out through `setEditorText`. That is why `Space` opens a note and the
arrow keys do not: a highlight that opened notes would start a read on every
row it passed through, and each answer would arrive with a different note
already open. The two checks that say so are "moving the highlight leaves the
editor alone" and "the edit reached the disk before the other note arrived",
and they are the point of the file.

**It saves as you type, because it cannot save when you leave.** `"quit"` is
handled by `TApplication` and never reaches the model, so there is no last
moment to flush in. `saved()` below waits for a file to say what the keyboard
said, with no save key pressed.

**And `Tab` cannot leave the editor** -- `TEditor` inserts `charCode 9` as a
character (`teditor1.cpp:588`) -- which is why the window has `F4` and why
there is a check that a tab really does land in the note.

Two driving conventions, both learned the hard way and both cheap. Enter goes
in a `send` of its own: a burst of `name\\r` written in one go leaves the
dialog open with the Enter unaccounted for, and the *next* Enter closes it, so
a combined write tests one dialog behind. And every wait for the disk is a
pump loop with a deadline rather than a fixed sleep, because a settle long
enough to be safe is pure wall clock on a suite that is already parallel.
"""

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

CTRL_N = b"\x0e"
F2 = b"\x1bOQ"
F4 = b"\x1bOS"
ALT_Q = b"\x1bq"
ALT_F3 = b"\x1b\x1bOR"
DOWN = b"\x1b[B"


def notes_dir(home):
    return os.path.join(home, ".local", "share", "predc", "notes")


def plant(notes):
    """A HOME with a notes directory in it, or without one when `notes` is
    None -- which is how the check that predc makes the directory itself is
    written."""
    home = tempfile.mkdtemp(prefix="predc-notes-")
    if notes is not None:
        os.makedirs(notes_dir(home))
        for name, text in notes.items():
            with open(os.path.join(notes_dir(home), name), "w") as out:
                out.write(text)
    return home


def start(home, *args):
    env = dict(TERM="xterm-256color", HOME=home,
               PATH=os.environ.get("PATH", "/usr/bin"))
    app = Pty(node_argv(LAUNCHER, *args), env, cwd=ROOT)
    app.pump(2.5)
    return app


def body(app):
    """The window's own rows: everything between its side walls.

    Matched on the left wall alone, because the right one is not there -- the
    editor's scroll bar is drawn in the window's last column, which is the
    house style here and is what `Tool.Env`'s driver says about the hex
    viewer.
    """
    return [line for line in app.render().split("\n") if line.startswith("║")]


def status(app):
    """The line along the foot of the window, which is the model's own
    sentence and not the application's status bar."""
    return body(app)[-1][1:].rstrip()


def panes(app):
    """The rows the list and the editor share, without the editor's horizontal
    scroll bar or the status line under it."""
    return body(app)[:-2]


def names(app):
    return [row[1:21].strip() for row in panes(app) if row[1:21].strip()]


def text(app):
    return [row[23:79].rstrip() for row in panes(app)]


def title(app):
    for line in app.render().split("\n"):
        if "╔" in line or "┌" in line:
            return line
    return ""


def saved(app, path, limit=6.0):
    """What a file says once it stops changing, waited for rather than slept
    on.

    The autosave is a subscription that exists only while there is something to
    write, so the wait is over as soon as the file appears with content in it.
    """
    end = time.time() + limit
    seen = ""
    while time.time() < end:
        app.pump(0.3)
        if os.path.exists(path):
            with open(path) as handle:
                now = handle.read()
            if now and now == seen:
                return now
            seen = now
    return seen


def gone(app, path, limit=6.0):
    end = time.time() + limit
    while time.time() < end:
        app.pump(0.3)
        if not os.path.exists(path):
            return True
    return False


def named(app, name, limit=6.0):
    """Wait for a name to reach the list, which is the other end of the same
    round trip: a note is made on the disk and the window learns about it by
    reading the directory again."""
    end = time.time() + limit
    while time.time() < end:
        app.pump(0.3)
        if name in names(app):
            return True
    return False


def menu(app, name):
    bar = app.render().split("\n")[0]
    app.click(bar.index(name) + 1, 1, settle=0.6)


def entry(app, label, settle=1.0):
    for row, line in enumerate(app.render().split("\n")):
        if label in line and "│" in line:
            app.click(line.index(label) + 1, row + 1, settle=settle)
            return True
    return False


def main():
    check = Checks()

    # ---- the ordinary window, on a directory that already has notes -------
    home = plant({"Alpha.md": "first note\n", "Beta.md": "second note\n"})
    here = notes_dir(home)
    app = start(home, "notes")

    check("predc notes opens the window", "Notes" in title(app), title(app))
    check("both notes are in the list", names(app) == ["Alpha", "Beta"], names(app))
    check("and the first one is open, because a blank editor beside a list of "
          "notes reads as though they were not found",
          "Notes - Alpha" in title(app), title(app))
    check("the editor holds that note's text", text(app)[0] == "first note", text(app)[:2])
    check("the foot says how many there are and what the keys do",
          status(app).startswith("2 notes."), status(app))

    # ---- it saves without being told to ----------------------------------
    app.send(b" edited", settle=1.0)
    check("what is typed goes into the note that is open",
          text(app)[0] == " editedfirst note", text(app)[:2])
    check("and reaches the disk with no save key pressed, because quit never "
          "reaches the model and there is no later moment to write in",
          saved(app, os.path.join(here, "Alpha.md")) == " editedfirst note\n",
          open(os.path.join(here, "Alpha.md")).read())

    # ---- the highlight is not the open note ------------------------------
    app.send(F4, settle=0.7)
    app.send(DOWN, settle=0.7)
    check("moving the highlight does not open a note: an editor swap per arrow "
          "key is a race whose answers land in the wrong document",
          "Notes - Alpha" in title(app) and text(app)[0] == " editedfirst note",
          title(app))

    # The colour look this window would not otherwise get, taken here because
    # a list draws its highlight only while it has the caret -- which is what
    # F4 just gave it, and is why this cannot be asserted at the moment the
    # window opens with the editor focused.
    where = app.display()
    check("the highlighted row is painted and its neighbour is not, which is "
          "the only thing on the screen that says where the highlight is",
          where.bg_at(2, 3) != where.bg_at(2, 2),
          f"{where.bg_at(2, 3)} vs {where.bg_at(2, 2)}")

    app.send(b" ", settle=1.5)
    check("Space opens the one the highlight is on",
          "Notes - Beta" in title(app), title(app))
    check("and the editor is holding its text now",
          text(app)[0] == "second note", text(app)[:2])
    check("the note that was open was written on the way out",
          open(os.path.join(here, "Alpha.md")).read() == " editedfirst note\n",
          open(os.path.join(here, "Alpha.md")).read())

    # ---- Tab belongs to the editor ---------------------------------------
    app.send(b"\t", settle=1.0)
    check("Tab puts a tab in the note rather than leaving the editor, which is "
          "why the window has F4",
          saved(app, os.path.join(here, "Beta.md")).startswith("\tsecond note"),
          repr(open(os.path.join(here, "Beta.md")).read()))

    # ---- F2 says so ------------------------------------------------------
    app.send(F2, settle=1.5)
    check("F2 says something even when the autosave has already been round, "
          "because a save key that sometimes does nothing visible is one "
          "nobody believes",
          status(app).startswith("Beta is already saved."), status(app))

    # ---- a name that cannot be a file ------------------------------------
    app.send(CTRL_N, settle=1.0)
    check("Ctrl-N reaches the menu from inside the editor, because the menu "
          "bar is offered every key before the focused view is",
          "New note" in app.render(), status(app))
    app.send(b"bad/name", settle=0.6)
    app.send(b"\r", settle=1.2)
    check("a name with a slash in it is refused, because the name is the "
          "file name", "slash" in status(app), status(app))
    check("and nothing was made", sorted(os.listdir(here)) == ["Alpha.md", "Beta.md"],
          sorted(os.listdir(here)))

    # ---- and one that can ------------------------------------------------
    app.send(CTRL_N, settle=1.0)
    app.send(b"Release checklist", settle=0.6)
    app.send(b"\r", settle=1.5)
    check("a new note is a new file, named the way the note is",
          named(app, "Release checklist")
          and os.path.exists(os.path.join(here, "Release checklist.md")),
          sorted(os.listdir(here)))
    check("it opens, and the list stays sorted",
          "Notes - Release checklist" in title(app)
          and names(app) == ["Alpha", "Beta", "Release checklist"],
          names(app))

    app.send(b"one", settle=1.0)
    check("and the caret is in the editor, because choosing a note is asking "
          "to write in it",
          saved(app, os.path.join(here, "Release checklist.md")) == "one",
          repr(open(os.path.join(here, "Release checklist.md")).read()))

    # ---- a rename keeps what has not been written yet ---------------------
    # Typed and renamed inside the same second, so the rename happens with an
    # edit that no autosave has reached. Re-reading the moved file would put
    # the old text back and lose it; the tool moves the highlight instead.
    app.send(b" two", settle=0.2)
    menu(app, "Note")
    entry(app, "Rename")
    app.send(b"\x08" * 24, settle=0.4)
    app.send(b"Checklist", settle=0.4)
    app.send(b"\r", settle=1.5)
    check("a rename moves the file",
          gone(app, os.path.join(here, "Release checklist.md"))
          and os.path.exists(os.path.join(here, "Checklist.md")),
          sorted(os.listdir(here)))
    check("and the window follows it", "Notes - Checklist" in title(app), title(app))
    check("and the text typed since the last autosave is still there, which "
          "re-reading the moved file would have thrown away",
          text(app)[0] == "one two", text(app)[:2])
    check("so the next save writes all of it",
          saved(app, os.path.join(here, "Checklist.md")) == "one two",
          repr(open(os.path.join(here, "Checklist.md")).read()))

    # ---- delete ----------------------------------------------------------
    menu(app, "Note")
    entry(app, "Delete")
    check("deleting asks first, because a note is a file and there is no "
          "wastebasket", "Delete note" in app.render(), app.render())
    app.send(b"\r", settle=1.2)
    check("and Enter presses Cancel, which is the safe answer",
          os.path.exists(os.path.join(here, "Checklist.md")), sorted(os.listdir(here)))

    menu(app, "Note")
    entry(app, "Delete")
    app.send(b"\t", settle=0.4)
    app.send(b"\r", settle=1.5)
    check("the other button really deletes it",
          gone(app, os.path.join(here, "Checklist.md")), sorted(os.listdir(here)))
    check("and the window moves to what is left rather than sitting empty",
          "Notes - Alpha" in title(app) and names(app) == ["Alpha", "Beta"],
          title(app) + " " + str(names(app)))

    app.send(b"\x1bx", settle=0.6)
    check("it exits cleanly", app.wait(timeout=6) == 0, "exit")

    # ---- the command line ------------------------------------------------
    named_app = start(home, "notes", "Beta")
    check("predc notes <name> opens that note",
          "Notes - Beta" in title(named_app), title(named_app))
    named_app.send(b"\x1bx", settle=0.6)
    named_app.wait(timeout=6)

    missing = start(home, "notes", "nosuch")
    check("a name that is not a note says so rather than inventing one",
          "There is no note called nosuch." in status(missing), status(missing))
    check("and nothing was created", sorted(os.listdir(here)) == ["Alpha.md", "Beta.md"],
          sorted(os.listdir(here)))
    missing.send(b"\x1bx", settle=0.6)
    missing.wait(timeout=6)

    # ---- a machine that has never run it ---------------------------------
    fresh = plant(None)
    empty = start(fresh, "notes")
    check("the notes directory is made rather than complained about",
          os.path.isdir(notes_dir(fresh)), notes_dir(fresh))
    check("and an empty one says what to press",
          status(empty).startswith("No notes yet."), status(empty))

    # Alt-Q, which is the last free letter in the program, and the Tools menu
    # entry that teaches it.
    empty.send(ALT_F3, settle=1.0)
    check("Alt-F3 closes the window", "Notes" not in title(empty), title(empty))
    empty.send(ALT_Q, settle=1.5)
    check("Alt-Q brings it back", "Notes" in title(empty), title(empty))
    empty.send(b"\x1bx", settle=0.6)
    check("and that one exits cleanly too", empty.wait(timeout=6) == 0, "exit")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
