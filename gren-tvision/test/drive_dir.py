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

        app.send(b"\x1bx", settle=1.0)
        code = app.wait(timeout=6)
        check("exit code 0", code == 0, f"exit={code}")

        return check.report(app)
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
