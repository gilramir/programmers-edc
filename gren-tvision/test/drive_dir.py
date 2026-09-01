#!/usr/bin/env python3
"""examples/dir -- tvdir, in Gren.

Two things this test is really about.

`TOutline` was never wrapped. The plan of record had tvdir down as needing a
new widget, because a tree view *is* a widget in C++: `TOutlineViewer` owns a
`TNode` chain, decides which rows are visible and draws the box graphics
itself. A model that re-renders needs none of it -- the visible rows are a fold
over a `type Node`, and a plain `ListBox` shows them. So what this drives is a
list box, and what it checks is that expanding and collapsing behave like a
tree.

And nothing blocks. `TDirWindow`'s constructor scans the whole drive, which is
why the original has to put up a "Please Wait" window and call
`TScreen::flushScreen()` by hand. Here a directory is read when it is opened,
`FileSystem.listDirectory` is a task, and the interface stays live throughout.

And the history drop-down beside the Change Dir field is driven at the end:
`THistory` is the first widget the package-helper shape could not answer, and
the list in it is the model's rather than Turbo Vision's process-wide buffer.

The tree it is pointed at is built here rather than found, so the rows are
known exactly.
"""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLE = os.path.join(ROOT, "examples", "dir")
RUNTIME = os.path.join(ROOT, "..", "gren-tvision-runtime", "bin", "gren-tui.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

# The tree list is at (2, 1) inside a window at (1, 1), and screen row 0 is the
# menu bar, so the first row of the tree is here. It is 23 columns wide.
TREE = (3, 3)
TREE_WIDTH = 23
FILES = (31, 3)
FILES_WIDTH = 43


def build_fixture(root):
    """A tree with a known shape and known file counts.

        root/
          alpha/          three files
            deep/         one file
          beta/           no files
          gamma/          two files
          top.txt, other.txt
    """
    for path in ("alpha/deep", "beta", "gamma"):
        os.makedirs(os.path.join(root, path))
    files = {
        "": ["top.txt", "other.txt"],
        "alpha": ["a1.txt", "a2.txt", "a3.txt"],
        "alpha/deep": ["d1.txt"],
        "gamma": ["g1.txt", "g2.txt"],
    }
    for where, names in files.items():
        for name in names:
            open(os.path.join(root, where, name), "w").close()


def column(app, at, width, rows=14):
    """One pane's visible rows, trimmed."""
    screen = app.render().split("\n")
    return [screen[at[1] + i][at[0]:at[0] + width].rstrip() for i in range(rows)]


def tree(app):
    return [row for row in column(app, TREE, TREE_WIDTH) if row]


def files(app):
    return [row.strip() for row in column(app, FILES, FILES_WIDTH) if row.strip()]


def box_edges(screen, title):
    """(left, right) frame columns of the open dialog with this title."""
    for line in screen.split("\n"):
        if title in line and "╔" in line and "╗" in line:
            return (line.index("╔"), line.rindex("╗"))
    return None


def chooser(app):
    """The rows of the Change Dir dialog's list box.

    The dialog is 58 wide and centred on an 80-column desktop, so its list
    starts three columns inside its own left frame.
    """
    screen = app.render().split("\n")
    left = None
    for line in screen:
        if "Change directory" in line and "╔" in line:
            left = line.index("╔")
    if left is None:
        return []
    return [row for row in
            (screen[r][left + 3:left + 50].strip() for r in range(7, 15)) if row]


def arrow(app):
    """Where the history drop-down's arrow is, 1-based for Pty.click."""
    for row, line in enumerate(app.render().split("\n")):
        col = line.find("\u2590\u2193\u258c")
        if col >= 0:
            return (col + 2, row + 1)
    return None


def dropdown(app):
    """The rows of the history drop-down, once it is open.

    It is a window inside the dialog, so it is the first frame on screen whose
    left edge is right of the dialog's own.
    """
    screen = app.render().split("\n")
    dialog_left = top = left = None
    for row, line in enumerate(screen):
        if "Change directory" in line and "\u2554" in line:
            dialog_left = line.index("\u2554")
        elif dialog_left is not None and top is None and "\u2554" in line \
                and line.index("\u2554") > dialog_left:
            top, left = row, line.index("\u2554")
    if top is None:
        return []
    right = screen[top].index("\u2557", left)
    return [row for row in
            (screen[r][left + 1:right].strip() for r in range(top + 1, top + 7))
            if row]


def main():
    check = Checks()
    root = tempfile.mkdtemp(prefix="tvdir-")
    try:
        build_fixture(root)
        env = dict(os.environ, TERM="xterm-256color")
        app = Pty(node_argv(RUNTIME, "main.js", root), env, cwd=EXAMPLE)

        app.pump(2.5)
        check("the window is titled with the path it was given",
              root in app.render(), app.render())

        # FileSystem.initialize is awaited in init, currentWorkingDirectory is
        # skipped because a path was given, and the first listing is a task
        # that has landed by now.
        rows = tree(app)
        check("the root is expanded and its subdirectories are listed",
              [r.strip() for r in rows] == ["▾ " + os.path.basename(root),
                                            "▸ alpha", "▸ beta", "▸ gamma"],
              str(rows))
        names = [r.strip()[2:] for r in rows[1:]]
        check("directories are sorted", names == sorted(names), str(names))
        check("the files pane shows the root's files, sorted",
              files(app) == ["other.txt", "top.txt"], str(files(app)))

        # Down moves the highlight, which loads that directory -- a Focused
        # event, a task, and a render, with nothing blocking in between.
        app.send(b"\x1b[B", settle=1.0)
        check("moving the highlight loads that directory's files",
              files(app) == ["a1.txt", "a2.txt", "a3.txt"], str(files(app)))
        check("and the title follows the highlight",
              os.path.join(root, "alpha") in app.render(), app.render())

        # Space expands. The child was never read until now, which is the whole
        # difference from a constructor that scans the drive.
        app.send(b" ", settle=1.2)
        rows = [r.strip() for r in tree(app)]
        check("Space expands the directory under the highlight",
              rows == ["▾ " + os.path.basename(root), "▾ alpha", "▸ deep",
                       "▸ beta", "▸ gamma"], str(rows))

        app.send(b"\x1b[B", settle=1.2)
        check("and the child is a directory like any other",
              files(app) == ["d1.txt"], str(files(app)))

        # Collapsing removes the whole subtree from the rows, which is a fold
        # over the model rather than anything the list box knows about.
        app.send(b"\x1b[A", settle=0.6)
        app.send(b" ", settle=1.0)
        rows = [r.strip() for r in tree(app)]
        check("collapsing takes the subtree with it",
              rows == ["▾ " + os.path.basename(root), "▸ alpha", "▸ beta",
                       "▸ gamma"], str(rows))

        # An empty directory says so rather than showing the last one's files.
        app.send(b"\x1b[B", settle=1.2)
        check("an empty directory shows <no files>",
              files(app) == ["<no files>"], str(files(app)))

        app.send(b"\x1b[B", settle=1.2)
        check("and the next one shows its own",
              files(app) == ["g1.txt", "g2.txt"], str(files(app)))

        # The one part of tvdir that was never ported, because there was no
        # way to ask for a path. TChDirDialog reads the directory from inside
        # itself; here listing one is a Task, so Alt-C is two steps -- read,
        # then show -- and Tui.fileDialog is only the layout.
        app.send(b"\x1bc", settle=1.5)
        opened = app.render()
        check("Change dir opened a chooser", "Change directory" in opened, opened)
        check("listing the directories it was given, and `..`",
              chooser(app) == ["..", "alpha", "beta", "gamma"], str(chooser(app)))
        edges = box_edges(opened, "Change directory")
        check("and it centres itself on the desktop",
              edges is not None and abs(edges[0] - (79 - edges[1])) <= 1,
              f"frame at {edges} of 80 columns")

        # Walking into one. A dialog is not part of `view` and nothing patches
        # it while it is up, so this is a second listing and a second dialog --
        # which in `update` is the same two lines that opened the first.
        app.send(b"\x1b[B", settle=0.4)
        app.send(b"\x1bo", settle=1.5)
        check("Open walked into the highlighted directory",
              chooser(app) == ["..", "deep"], str(chooser(app)))
        check("and the path it shows came with it",
              os.path.join(root, "alpha") in app.render(), app.render())

        # `..` is the first row of the reopened dialog and the highlight starts
        # there, so Chdir goes back up -- and the tree re-roots on the answer.
        app.send(b"\x1bc", settle=1.5)
        check("Chdir closed it and the tree re-rooted",
              "Change directory" not in app.render()
              and [r.strip() for r in tree(app)][0] == "▾ " + os.path.basename(root),
              str(tree(app)))

        # And down again, to prove the answer is a path rather than a direction.
        app.send(b"\x1bc", settle=1.5)
        app.send(b"\x1b[B", settle=0.4)
        app.send(b"\x1bc", settle=1.5)
        rows = [r.strip() for r in tree(app)]
        check("choosing a subdirectory re-roots the tree there",
              rows == ["▾ alpha", "▸ deep"], str(rows))

        # The history drop-down. Turbo Vision keeps this list in one buffer
        # shared by the whole program and adds to it behind the program's back;
        # here it is a field on the model that only `update` writes to, so what
        # is in it is exactly the two directories Chdir has been answered with,
        # newest first.
        app.send(b"\x1bc", settle=1.5)
        at = arrow(app)
        check("the field has a history arrow beside it", at is not None,
              app.render())
        app.click(at[0], at[1], settle=1.2)
        check("clicking it drops down what Chdir has been answered with",
              dropdown(app) == [os.path.join(root, "alpha"), root],
              str(dropdown(app)))

        # Choosing one writes it into the field, which is a Changed event on
        # the *field* -- the drop-down has no event of its own, because what
        # happened is that the input line's value changed.
        app.send(b"\x1b[B", settle=0.4)
        app.send(b"\r", settle=1.0)
        check("choosing an entry puts it in the field",
              root in app.render().split("\n")[5], app.render())

        # And the field beats the highlight, which is what TChDirDialog does
        # and the only thing that makes a remembered path mean anything: the
        # list beside it is showing alpha's subdirectories, not this.
        app.send(b"\x1bc", settle=1.5)
        rows = [r.strip() for r in tree(app)]
        check("Chdir took the path from the field, not the list",
              rows == ["\u25be " + os.path.basename(root), "\u25b8 alpha",
                       "\u25b8 beta", "\u25b8 gamma"], str(rows))

        # Answered with a path already in the list, so it moves to the front
        # rather than appearing twice.
        app.send(b"\x1bc", settle=1.5)
        app.click(arrow(app)[0], arrow(app)[1], settle=1.2)
        check("a repeat moves to the front instead of doubling up",
              dropdown(app) == [root, os.path.join(root, "alpha")],
              str(dropdown(app)))
        app.send(b"\x1b", settle=0.5)
        app.send(b"\x1b", settle=0.8)

        # And the caret opens in the Name field, which is the first view in
        # `Tui.fileDialog`'s array that can hold one. It has not always been:
        # the array was built with `Array.append`, which makes its first
        # argument the *postfix*, so the buttons were listed first, the dialog
        # opened on OK and the field was two Tabs away. This is the check that
        # was missing -- everything above drives the dialog with arrow keys and
        # a mouse, and none of it can tell where the caret is.
        app.send(b"\x1bc", settle=1.5)
        app.send(b"zz", settle=0.6)
        check("the caret opens in the Name field, so typing reaches it",
              "zz" in app.render().split("\n")[5], app.render().split("\n")[5])
        app.send(b"\x1b", settle=0.8)

        app.send(b"\x1bx", settle=1.0)
        code = app.wait(timeout=6)
        check("exit code 0", code == 0, f"exit={code}")

        return check.report(app)
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
