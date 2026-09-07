#!/usr/bin/env python3
"""Every key predc advertises, pressed, in the state that makes it hard.

A menu is a set of promises: an underlined letter says "press me", an
accelerator printed down the right-hand side says "press me from anywhere".
Both are silently breakable, and both were broken here. `~C~alc` on the
calculator's own menu took `Alt-C` away from the time converter for as long as
the calculator was open -- a bar title is matched before any accelerator is
looked for (`tmnuview.cpp:314`) -- and inside the **Tools** pull-down two pairs
of entries shared a letter, so `d` opened the hex viewer whichever of the two
you meant and `v` opened the random generator.

Nothing could see any of it. Every promise draws exactly the same whether it
works or not, and each of the four was found by pressing a key in a state some
other test never happened to be in.

**This driver hard-codes nothing about predc.** It reads the promises off the
screen -- Turbo Vision draws an underlined letter in a colour of its own, which
is the only place that information exists once a menu is rendered -- and then
presses them. `Screen.hot_letter`, `Pty.bar_titles`, `Pty.menu_entries` and
`Pty.active_title` do the reading and live in the harness, because every word
of that is a fact about how Turbo Vision draws a menu rather than about this
program.

Adding a tenth tool adds three checks and no lines, which matters more than it
sounds: a table of "what predc's keys are" written into a test file is a second
place to keep them right, and two places that disagree is the whole class of
bug being tested for.

The three questions, and they are different questions:

  - **Within one pull-down**, does every entry have its own letter?
    `TMenuView::findItem` returns the *first* item whose underlined letter
    matches, so a duplicate is not ambiguous, it is dead. Checked by pressing
    each one and seeing which window turns up: nine entries have to open nine
    different tools.
  - **Across the whole program**, does a menu *bar* title claim a letter that
    is somebody's advertised `Alt` key? The bar wins, so it does not collide,
    it steals.
  - **And with everything open**, does each accelerator still do what the menu
    says it does? The state a shortcut is least likely to have been tried in
    is the one where every other tool is open, because that is when every tool
    menu is on the bar at once.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv


def open_menu(app, name, settle=0.5):
    bar = app.render().split("\n")[0]
    app.click(bar.index(name) + 1, 1, settle=settle)


def main():
    check = Checks(
        replays=(
            "it opens the environment tool, which draws the variables this "
            "process was given -- and the one a replay has to change, HOME, "
            "so that what the program writes lands somewhere safe, is one of "
            "the rows on the screen"
        )
    )
    env = dict(os.environ, TERM="xterm-256color",
               HOME=tempfile.mkdtemp(prefix="predc-keys-"))
    env.pop("XDG_CONFIG_HOME", None)
    app = Pty(node_argv(LAUNCHER), env, cwd=tempfile.mkdtemp(), size=(110, 34))
    app.pump(2.5)

    check("predc started", "Tools" in app.render().split("\n")[0],
          app.render().split("\n")[0])

    # 1. What the Tools menu promises, read off the screen.
    open_menu(app, "Tools")
    tools = app.menu_entries()
    check("the Tools menu has entries to check", len(tools) >= 5,
          str(tools))
    check("every entry on it has an underlined letter",
          all(letter for _, letter, _ in tools),
          str([(t, l) for t, l, _ in tools if not l]))
    letters = [letter.lower() for _, letter, _ in tools if letter]
    check("and no two entries share one, since the first match is the only one",
          len(set(letters)) == len(letters),
          str(sorted(letters)))
    accels = [a for _, _, a in tools if a]
    check("every entry advertises an accelerator too", len(accels) == len(tools),
          str(tools))
    check("and no two entries share one of those either",
          len(set(accels)) == len(accels), str(sorted(accels)))
    app.send(b"\x1b", settle=0.4)

    # 2. Pressing each letter opens a different tool. This is the check that
    #    the letters are *promises* rather than decoration: two entries sharing
    #    one are caught by the count above, but an entry whose letter reaches
    #    nothing at all is only caught here.
    opened = {}
    for text, letter, accel in tools:
        open_menu(app, "Tools")
        app.send(letter.encode(), settle=1.0)
        opened[text] = app.active_title()
        app.send(b"\x1b\x1b[13~", settle=0.7)          # Alt-F3
    check("each letter opens a window",
          all(opened.values()), str(opened))
    check("and the nine of them are nine different windows, "
          "which is what a duplicated letter breaks",
          len(set(opened.values())) == len(opened), str(opened))

    # 3. A menu bar title claims its letter for `Alt`, and beats an
    #    accelerator: `findAltShortcut` is tried before `hotKey`
    #    (tmnuview.cpp:314). So a tool menu whose title underlines a letter
    #    somebody else advertises does not collide with it, it takes it.
    for text, letter, accel in tools:
        open_menu(app, "Tools")
        app.send(letter.encode(), settle=1.0)
    bar = app.bar_titles()
    check("every tool's menu is on the bar now", len(bar) >= 9, str(bar))
    claimed = {letter.lower() for _, letter in bar if letter}
    advertised = {a.split("-")[-1].lower() for a in accels if a.startswith("Alt-")}
    check("no menu bar title takes a letter that is advertised as an Alt key",
          not (claimed & advertised),
          f"bar titles claim {sorted(claimed)}, Alt keys advertised: "
          f"{sorted(advertised)}, both: {sorted(claimed & advertised)}")

    # 4. Every *other* pull-down, now that every tool's menu is on the bar.
    #    One letter per entry per menu, for the same reason: `findItem` walks
    #    the menu that is on the screen and takes the first match. This costs
    #    a click each and no window opening, which is why it is worth doing for
    #    all of them rather than only for the one that had the bug.
    #
    #    Not the submenus. Reaching those means arrowing into them and the
    #    letters inside one are checked the same way by the same rule -- it is
    #    a gap, and it is written down rather than pretended about.
    for title, _ in app.bar_titles():
        open_menu(app, title)
        listed = app.menu_entries()
        if not listed:
            app.send(b"\x1b", settle=0.3)
            continue
        seen = [letter.lower() for _, letter, _ in listed if letter]
        check(f"the {title} menu gives every entry its own letter",
              len(set(seen)) == len(seen),
              f"{sorted(seen)} for {[t for t, _, _ in listed]}")
        app.send(b"\x1b", settle=0.3)

    # 5. And the promise itself, in the state that broke it: every tool open,
    #    every tool menu on the bar, press the key the menu printed. An
    #    accelerator for a tool that is already open brings it to the front,
    #    so the assertion is which window has the double-line frame.
    for text, letter, accel in tools:
        key = accel.split("-")[-1].lower()
        app.send(b"\x1b" + key.encode(), settle=0.9)
        check(f"{accel} raises {opened[text]!r} with every tool open",
              app.active_title() == opened[text],
              f"{accel} raised {app.active_title()!r}")

    app.send(b"\x1bx", settle=1.2)
    code = app.wait(timeout=8)
    check("Alt-X exits, and cleanly", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
