#!/usr/bin/env python3
"""A field the model writes must not come back as the user's event.

The rule was written down after the wheel bug -- a `ListBox`'s highlight is
moved by two parties, the binding reported both, and a model that stored what
it heard wrote back what it stored. It was invisible for as long as the two
values agreed, which they do for an arrow key and do not for a burst, so the
list snapped back to a stale index between the eye and the finger with 935
green checks behind it.

`JsListBox::setFocused` gained a `quiet` flag. **Nothing checked the other
five widgets**, and there is no reason a widget added next year would get it
right by itself: the failure is silent, it needs a burst to show, and every
screen involved looks correct throughout.

So this asks the question of all of them at once, in the only place it can be
asked -- the flag is in C++ and the fast layer's fake binding cannot see it.
`regress_echo.js` does one programmatic write per key and counts every callback
it hears; a driver presses a key and reads the counter.

**And the exception, which is why this is not simply "assert silence".** A
write the widget could not honour -- a `focused` past the end of a list that
has just been shortened -- *is* reported, because that is a disagreement rather
than an action, and it settles in one round: the model stores the row it was
given, asks for that row next time, and gets it. Silence there is the tree that
collapses itself when a branch is expanded. So one of the checks below asserts
that the counter *did* move, and it is the load-bearing one.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from harness import Pty, Checks, node_argv


def heard(app):
    """The fixture's count of callbacks, or -1 if it is not on screen."""
    for line in app.display().text().splitlines():
        if "heard:" in line:
            return int(line.split("heard:")[1].split()[0])
    return -1


def quiet(check, app, key, what):
    """Press `key`, which makes one programmatic write, and hear nothing."""
    was = heard(app)
    app.send(key.encode(), settle=0.6)
    check(f"writing {what} says nothing back to the model",
          heard(app) == was, f"heard went {was} -> {heard(app)}")


def main():
    check = Checks()
    env = dict(os.environ, TERM="xterm-256color")
    app = Pty(node_argv(os.path.join(HERE, "regress_echo.js")), env, cwd=ROOT)

    app.pump(2.0)
    check("the window is up", "Echo" in app.render(), app.render())
    check("with a counter in it", heard(app) >= 0, app.render())

    # The canvas has the caret -- it is the first selectable view -- so the
    # letters reach `onKey` rather than being typed into anything.
    start = heard(app)
    check("and nothing has been heard yet", start == 0, str(start))

    # 1. The one that was broken, and the reason the silence is not the
    #    write being ignored: the list really does move.
    quiet(check, app, "f", "a list box's highlight")
    quiet(check, app, "g", "it again, to a different row")
    check("and the highlight really did move",
          "row 7" in app.render(), app.render())
    app.send(b"r", settle=0.6)

    # 2. The rest of the widget set, none of which was ever asked.
    quiet(check, app, "i", "a shorter list under a highlight that still fits")
    app.send(b"r", settle=0.6)
    quiet(check, app, "t", "a list box's top row")
    quiet(check, app, "b", "a scroll bar's thumb")
    check("and the thumb really did move",
          "heard" in app.render(), app.render())
    quiet(check, app, "x", "an input line's text")
    check("and the text really was written", "written" in app.render(),
          app.render())
    quiet(check, app, "c", "a check box's ticks")
    check("and the tick really was made", "[X] one" in app.render(),
          app.render())
    quiet(check, app, "e", "a view's enabled flag")

    # 3. The exception, twice, because there are two ways to ask a list for a
    #    row it has not got. Silence in either would leave the model believing
    #    a highlight that is not there.
    was = heard(app)
    app.send(b"k", settle=0.8)
    check("but a highlight the list could not honour IS reported, because that "
          "is a disagreement rather than an action",
          heard(app) > was, f"heard stuck at {was}")
    line = [l for l in app.render().split("\n") if "heard:" in l]
    check("and what it reports is the row it landed on",
          bool(line) and "=1" in line[0], str(line))

    app.send(b"r", settle=0.6)
    app.send(b"g", settle=0.6)                 # highlight row 7 of ten
    was = heard(app)
    app.send(b"i", settle=0.8)                 # four rows: seven is gone
    check("and a list shortened out from under its highlight reports too",
          heard(app) > was, f"heard stuck at {was}")

    # 4. Last, because it costs the keystroke after it. `setViewVisible` ends
    #    in `TView::setState(sfVisible)`, which calls `owner->resetCurrent()`,
    #    and the caret being re-chosen eats the next key -- which is a fact
    #    about showing any selectable view and not about this fixture. It is
    #    here at the end so that it is a fact rather than a mystery: the first
    #    version of this driver had it in the middle and lost every check
    #    after it, silently, because a key that reaches nothing is quiet and
    #    quiet is what these checks are looking for.
    quiet(check, app, "v", "a view's visible flag")

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=8)
    check("Alt-X exits, and cleanly", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
