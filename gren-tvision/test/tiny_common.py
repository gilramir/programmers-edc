#!/usr/bin/env python3
"""Every program in the repo, started on a terminal too small for it.

Rectangles here are mostly constants -- a chart is sixteen rows of eight
columns and there is no more of it -- and a constant is a bet that the terminal
is at least that big. The bet has been lost twice already, both times on the
same shape: the help window's floor asked for a window ending one row past the
bottom of an eight-row desktop, and the environment list sized itself from a
desktop the model had not been told about yet. Neither crashed. Both drew
something wrong, quietly, on a machine somebody was actually using.

So this asks the cheapest version of the question, of everything at once: start
it in a tmux pane the size of a postage stamp, and then make the pane a normal
size again. Three properties, none of which needs to know what the program is:

  - **It is still running.** A rectangle that cannot be satisfied is a
    `TWindow` constructor with `b.y < a.y`, and what that does is not defined
    anywhere.
  - **Its window is whole once the terminal is big enough for it again.** Not
    "nothing was drawn outside the terminal", which cannot be asked -- a
    terminal clips, so there is nothing out there to find. What a rectangle
    bigger than its desktop leaves behind is a *hole*: a top border running to
    the last column with no corner on the end of it, or no bottom border at
    all, which is what the help window's floor produced on an eight-row
    terminal and what `TView::calcBounds` produced on every round trip until
    `JsWindow` overrode it.
  - **It comes back.** Growing the terminal again has to leave a screen that
    still has its menu bar and its status line, because the interesting failure
    is not the small size, it is the state a program is left in afterwards.

And the harness's own invariant rides along: nothing drawn in the colour behind
it, on screens nobody had ever looked at.

Two suites over one module, split alphabetically, because sixteen programs
started and resized three times each is a hundred and eight seconds and the
slowest suite in the repo is ninety-three. The split is by name and not by
anything meaningful: every program here costs the same, since the cost is
sleeping while a terminal settles rather than anything either half does.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLES = os.path.join(ROOT, "examples")
PREDC = os.path.join(ROOT, "..", "programmers-edc", "bin", "predc.js")
from harness_path import RUNTIME  # finds harness.py and gren-tui.js, here or in an install

from harness import Pty, Checks, node_argv

# Twenty-four by eight. Turbo Vision refuses to draw a window under six rows,
# and the desktop here is six: a menu bar, a status line and four rows between
# them. Small enough that no window in the repo fits at its declared size, and
# not so small that the answer is trivially "nothing is drawn".
TINY = (24, 8)
BACK = (100, 30)


def apps():
    """Every program in the repo, as (label, argv, cwd)."""
    found = []
    for name in sorted(os.listdir(EXAMPLES)):
        example = os.path.join(EXAMPLES, name)
        if os.path.isfile(os.path.join(example, "main.js")):
            found.append((name, node_argv(RUNTIME, "main.js"), example))
    # predc lives in this repository and not in the package, so in the
    # exported package repository it is not there at all. The examples above
    # are found by looking for a main.js; this is the same rule applied to the
    # one program that is not an example.
    if os.path.isfile(PREDC):
        found.append(("predc", node_argv(PREDC), ROOT))
    return found


def clipped(app):
    """Why the active window's frame is incomplete, or None if it is whole.

    Asking whether anything was drawn *outside* the terminal cannot work, and
    it is worth saying why because it is the obvious version of this check and
    it passes on everything. A terminal clips: a program that addresses column
    ninety of an eighty-column screen has those cells thrown away, and
    `Pty.display` crops for the same reason. There is nothing out there to
    find.

    What is left on the screen is a *hole*. A window whose rectangle hangs off
    the right-hand edge draws its top border to the last column and no `╗`; one
    that hangs off the bottom has no lower border at all -- which is what the
    help window's floor produced on an eight-row terminal, and what a rectangle
    computed against a desktop that has since changed produces at any size.

    The *active* window only, the one with the double frame: windows overlap,
    and a corner hidden behind another window is not a missing corner.
    """
    lines = app.render().split("\n")
    tops = [r for r, line in enumerate(lines) if "╔" in line]
    if not tops:
        return None                      # nothing open: nothing to be wrong
    top = tops[0]
    if "╗" not in lines[top]:
        return f"top border has no right corner: {lines[top]!r}"
    left, right = lines[top].index("╔"), lines[top].rindex("╗")
    # The bottom corners of a window that can be resized are `└` and `┘` and
    # not `╚` and `╝`: `TFrame::draw` puts the grow handles there, so the
    # bottom border of a draggable window is drawn in a different alphabet
    # from its top one.
    lower, ender = "╚└", "╝┘"
    # Anchored to the top-left corner's own column, and not "the next row with
    # a `╚` in it". The ASCII chart's contents are box-drawing characters --
    # `╚` is one of the two hundred and fifty-six things it is *for* -- so a
    # search by character finds the chart and calls the window broken.
    for row in range(top + 1, len(lines)):
        if left < len(lines[row]) and lines[row][left] in lower:
            if right >= len(lines[row]) or lines[row][right] not in ender:
                return f"bottom border has no right corner: {lines[row]!r}"
            return None
    return f"no bottom border under {lines[top]!r}"


def sweep(pick):
    """Run the sweep over the programs `pick` selects, by label."""
    check = Checks()
    env = dict(os.environ, TERM="xterm-256color")

    for label, argv, cwd in apps():
        if not pick(label):
            continue
        app = Pty(argv, env, cwd=cwd, size=TINY)
        app.pump(2.0)
        drawn = app.render()
        check(f"{label} is still running on a {TINY[0]}x{TINY[1]} terminal",
              app.alive(), drawn)
        check(f"and {label} drew something on it", drawn.strip() != "", drawn)
        # Nothing about the frame at this size, on purpose, and not because
        # the check is inconvenient. A window declared as a constant rectangle
        # wider or taller than the desktop *is* clipped, and that is what a
        # constant rectangle means: `TGroup::insert` does not fit one, and
        # neither does this port, because shrinking a window the model asked
        # for would be the port overruling it. A window the model pinned with
        # no `Tui.resizable` is the same case one step further -- `sizeLimits`
        # reports no maximum for it at all, so nothing may clamp it.
        #
        # The defect is not the small terminal. It is what a *resize* does to
        # the rectangle afterwards, which is what the loop below asks.

        # Twice, because the scaling is lossy in one direction and the second
        # round is where a rectangle that has already drifted drifts again.
        trips = 0
        for size in (BACK, TINY, BACK):
            app.resize(*size, settle=1.1)
            if size == TINY:
                continue        # see above: still too small to hold the window
            trips += 1
            check(f"and {label}'s window is whole at {size[0]}x{size[1]} after "
                  f"{'one round trip' if trips == 1 else 'two'}",
                  clipped(app) is None, str(clipped(app)))

        grown = app.render().split("\n")
        check(f"and {label} still has a menu bar afterwards",
              grown[0].strip() != "", repr(grown[0]))
        check(f"and {label} still has a status line",
              grown[-1].strip() != "", repr(grown[-1]))

        app.send(b"\x1bx", settle=0.8)
        code = app.wait(timeout=6)
        check(f"and {label} exits cleanly from there", code == 0, f"exit={code}")

    return check.report()

