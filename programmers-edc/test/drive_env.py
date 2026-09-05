#!/usr/bin/env python3
"""predc's environment list: every variable this process has, and a filter.

Driven with an environment the driver builds itself, which is the only way any
of this is assertable -- `HOME` and `PATH` are whatever the machine happens to
have, and half these checks are about exact counts. The variables planted below
are named so that the case-sensitivity checks have something to be about:
`ZZ_ALPHA` matches `alpha` only when case is ignored, and `ZZ_BETA` has an
`ALPHA` in its *value* rather than its name.

**The search box filters; it does not jump.** There is no find-next here and no
cursor in the list, and the status line carries the count -- `2 of 41` -- so
that a filtered view is never mistaken for the whole of it. Emptying the box
brings everything back, which is the check that says the tool has no mode to be
stuck in.

**The list is a focused canvas, so it is the end of the tab ring** -- `Tab`
reaches it and `Tab` cannot leave it (`JsCanvas::handleEvent`: a focused canvas
consumes its keys). `/` is the way back to the box, and that is checked here
rather than left to the hint that says so.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

# A whole environment, and nothing inherited. `env -i` in spirit: every count
# below is exact because this is the entire list the process will have, and a
# machine that happened to export one more variable would otherwise move them.
PLANTED = {
    "TERM": "xterm-256color",
    "ZZ_ALPHA": "one",
    "ZZ_BETA": "two ALPHA three",
    "ZZ_EMPTY": "",
    "ZZ_LONG": "x" * 200,
    "ZZ_VERY_LONG_VARIABLE_NAME_INDEED": "short",
    "AA_FIRST": "a",
    "MM_MIDDLE": "m",
}


def frame(app):
    """(left column, right column, row) of the window's top frame line."""
    for row, line in enumerate(app.render().split("\n")):
        if "╔" in line and "╗" in line:
            return (line.index("╔"), line.index("╗"), row)
    return None


def inside(app):
    """The window's own rows, whatever size it is.

    Sliced between the frame's two side walls rather than split on `║` --
    because **the scroll bar sits on the right wall**: every row of the list
    has one `║` and not two, which is the hex viewer's layout and the reason a
    driver that split on the walls found nothing at all here. And by column
    numbers read off the frame rather than hard-coded, because the window fills
    the desktop and the desktop is whatever the terminal is.
    """
    edges = frame(app)
    if edges is None:
        return []
    left, right, _ = edges
    return [line[left + 1:right].rstrip() for line in app.render().split("\n")
            if len(line) > left and line[left] == "║"]


def rows(app):
    """The list rows: below the search box and its blank line, above the
    status line."""
    return inside(app)[2:-1]


def listed(app):
    return [r for r in rows(app) if r.strip()]


def status(app):
    return inside(app)[-1].strip()


def box(app):
    """What is typed in the search box. Read from inside the window and not
    from the whole screen, because the menu bar says *Search* too."""
    for line in inside(app):
        if "Search" in line:
            return line.split("Search")[1].split("[")[0].strip()
    return ""


def ticked(app):
    for line in inside(app):
        if "Match case" in line:
            return "[X]" in line or "[x]" in line
    return False


def menu(app, name):
    bar = app.render().split("\n")[0]
    app.click(bar.index(name) + 1, 1, settle=0.6)


def entry(app, text, settle=1.0):
    for row, line in enumerate(app.render().split("\n")):
        if text in line and "│" in line:
            app.click(line.index(text) + 1, row + 1, settle=settle)
            return True
    return False


def clear(app):
    """Empty the search box.

    Clicked and then rubbed out rather than `/`-then-backspace, because `/`
    only reaches the box from the *list*, and after a trip through the menu bar
    the caret is not reliably in either. A click puts it somewhere known; a
    click past the end of the text puts it at the end, which is the end
    `Backspace` works from. (`Del` would want a selection, and a field only
    selects its whole value when it *gains* the caret from the keyboard.)
    """
    left, _, row = frame(app)
    app.click(left + 9 + 24, row + 2, settle=0.7)
    app.send(b"\x08" * 32, settle=1.0)


def main():
    check = Checks()
    home = tempfile.mkdtemp(prefix="predc-home-")
    env = dict(PLANTED, HOME=home, PATH=os.environ.get("PATH", "/usr/bin"))
    app = Pty(node_argv(LAUNCHER, "env"), env, cwd=ROOT)
    app.pump(2.5)

    body = listed(app)
    check("predc env opens the list", "Environment" in app.render(), app.render())
    check("every variable is there, and no others",
          status(app).startswith(f"{len(env)} variables"), status(app))
    check("sorted by name: the first row is the first name",
          body[0].startswith("AA_FIRST"), body[:3])
    check("name and value are separated by whitespace, and the values line up",
          body[0].startswith("AA_FIRST ") and " a" in body[0], body[0])
    # The layout checks want a view they can see all of, and PATH on this
    # machine is fourteen wrapped lines on its own -- so they are made against
    # the planted variables rather than against whatever is at the top. Which
    # is the filter earning its keep before it has been tested.
    app.send(b"ZZ_", settle=1.2)
    body = listed(app)
    check("a variable set to nothing is still a variable",
          any(r.startswith("ZZ_EMPTY") for r in body), body)

    # A value longer than the window wraps, indented to the value column,
    # rather than being cut off at the frame in silence.
    wrapped = [i for i, r in enumerate(body) if r.startswith("ZZ_LONG")]
    check("a value too wide for the window wraps instead of being cut",
          bool(wrapped) and body[wrapped[0] + 1].startswith("      "),
          body[wrapped[0]:wrapped[0] + 3] if wrapped else body)
    check("and the wrap is indented to where the value starts",
          bool(wrapped)
          and (len(body[wrapped[0] + 1]) - len(body[wrapped[0] + 1].lstrip()))
              == body[wrapped[0]].index("x"),
          body[wrapped[0]:wrapped[0] + 2] if wrapped else body)
    check("and the whole value survives the wrapping",
          "".join(r.strip() for r in body if r.startswith("ZZ_LONG") or r.startswith(" "))
          .replace("ZZ_LONG", "").count("x") == 200,
          [r for r in body if "x" in r][:5])

    # A name past the column width is written whole and its value starts one
    # space after it -- out of line with the rest, which is the honest answer.
    long_name = [r for r in body if r.startswith("ZZ_VERY_LONG")]
    check("a name wider than the column is not truncated",
          bool(long_name) and "ZZ_VERY_LONG_VARIABLE_NAME_INDEED short" in long_name[0],
          long_name)

    clear(app)

    # The filter. Typing goes to the search box, which has the caret at open.
    app.send(b"alpha", settle=1.2)
    check("typing filters, because the box has the caret when the window opens",
          box(app) == "alpha", box(app))
    body = listed(app)
    check("both the name match and the value match are shown",
          len(body) == 2 and body[0].startswith("ZZ_ALPHA")
          and body[1].startswith("ZZ_BETA"), body)
    check("and the status line says how many of how many",
          status(app).startswith(f"2 of {len(env)} match \"alpha\""), status(app))

    # Case. `c` belongs to the list, so this is also the Tab and the `/` back.
    app.send(b"\t\t", settle=0.7)
    app.send(b"c", settle=1.2)
    check("c on the list ticks Match case", ticked(app), inside(app)[0])
    check("and with case mattering, lowercase alpha matches neither",
          'Nothing matches "alpha".' in listed(app)
          and not any(r.startswith("ZZ_") for r in listed(app)), listed(app)[:3])
    check("the status line says case is being matched",
          "matching case" in status(app), status(app))

    app.send(b"/", settle=0.7)
    app.send(b"\x08" * 5, settle=0.7)
    app.send(b"ALPHA", settle=1.2)
    check("/ from the list puts the caret back in the search box",
          box(app) == "ALPHA", box(app))
    body = listed(app)
    check("and with case mattering, ALPHA matches both",
          len(body) == 2, body)

    # Off again, from the menu this time.
    menu(app, "Search")
    entry(app, "Match ~c~ase".replace("~", ""))
    check("the menu's Match case is the same toggle", not ticked(app), inside(app)[0])

    # Empty the box: everything comes back. There is no mode to be stuck in.
    clear(app)
    check("emptying the box brings them all back",
          status(app).startswith(f"{len(env)} variables"), status(app))

    # Nothing matches, and it says so rather than showing an empty box.
    app.send(b"nosuchthing", settle=1.2)
    check("a needle that matches nothing says so",
          "Nothing matches \"nosuchthing\"." in "\n".join(rows(app)), rows(app)[:2])
    check("and the count agrees", status(app).startswith(f"0 of {len(env)}"), status(app))

    menu(app, "Search")
    entry(app, "Show them all")
    check("Show them all is the same as emptying the box",
          box(app) == "" and status(app).startswith(f"{len(env)} variables"),
          (box(app), status(app)))

    # Scrolling. The list is taller than the window with ZZ_LONG in it.
    app.send(b"\t\t", settle=0.7)
    first = listed(app)[0]
    app.send(b"\x1b[B" * 3, settle=0.9)
    check("Down scrolls the list", listed(app)[0] != first, (first, listed(app)[0]))
    app.send(b"\x1b[H", settle=0.9)
    check("Home comes back to the top", listed(app)[0] == first, listed(app)[0])
    app.send(b"\x1b[F", settle=0.9)
    check("End goes to the bottom, and stops there",
          listed(app)[0] != first and listed(app)[-1].strip() != "", listed(app)[-3:])
    app.send(b"\x1b[H", settle=0.9)

    # Copy. What is on the clipboard cannot be read back here, so what is
    # checked is that the tool asked and heard an answer -- the shape the
    # calculator and the random tool both settle for.
    app.send(b"y", settle=1.2)
    check("y copies what is shown", status(app).startswith("Copied"), status(app))

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("Alt-X exits, and cleanly", code == 0, f"exit={code}")

    # And the size, which is what this window is a list in.
    #
    # The complaint that produced all of this: `predc env` on a tall terminal
    # opened a window for a twenty-three-row one and left half the screen
    # empty. The window is sized in `init`, before any `Resized` can have been
    # delivered, so the fix was for the shell to seed its idea of the desktop
    # from `Terminal.initialize` rather than from a guess it would correct a
    # frame later. This is the check that says so: a fresh program on a big
    # terminal, looked at in its **first** frame with no resize event sent.
    big = Pty(node_argv(LAUNCHER, "env"), env, cwd=ROOT, size=(100, 34))
    big.pump(2.5)
    left, right, row = frame(big)
    check("the window fills the terminal in the very first frame",
          (left, right, row) == (0, 99, 1), (left, right, row))
    check("and the list is as tall as the terminal leaves it",
          len(rows(big)) == 34 - 2 - 5, len(rows(big)))

    # The other half: a value wraps at whatever width the window is, so a wide
    # terminal is worth having and not merely tolerated. `ZZ_LONG` is two
    # hundred characters of `x` and nothing else, so the count on its first
    # line *is* the room the value was given -- the canvas less the name
    # column and the two spaces after it.
    def run_of_x(pty):
        for line in rows(pty):
            if line.startswith("ZZ_LONG"):
                return line.count("x")
        return 0

    big.send(b"ZZ_LONG", settle=1.2)
    check("a hundred columns give the value eighty-eight of them",
          run_of_x(big) == 100 - 3 - len("ZZ_LONG") - 2, run_of_x(big))
    big.resize(70, 20)
    check("and seventy columns re-wrap it to fifty-eight, on the resize alone",
          run_of_x(big) == 70 - 3 - len("ZZ_LONG") - 2, run_of_x(big))
    check("the window came with the terminal rather than staying put",
          frame(big)[1] == 69, frame(big))

    big.send(b"\x1bx", settle=1.0)
    code = big.wait(timeout=6)
    check("and that one exits cleanly too", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
