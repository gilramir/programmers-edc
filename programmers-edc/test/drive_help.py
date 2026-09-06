#!/usr/bin/env python3
"""The help window, which has two pages and one window id.

**What is in here** is the inventory: ten tools, three lines each, with the
Alt-key that opens one from anywhere and the word that opens it on the way in.
The last of those is why the page pays for itself -- a menu can show a name and
a key and no menu can show a command line. Section 0 below checks the page
against the two lists it is a copy of: the tools' own menu entries, by way of
`tests/src/HelpTests.gren` in milliseconds, and `predc --help`, which is
checked here because `Cli.gren` keeps its words inside a parser rather than in
a list anything can read.

**Copying and pasting** is the rest of this file, and the window that answers
for *this* machine.

The subject is confusing enough that a page of prose is not an answer: there
are six stores unix calls the clipboard, Turbo Vision touches one of them, a
mouse selection fills a different one, over ssh none is reachable and no
setting changes that, and the thing that does work is not a clipboard
operation at all. So the window opens with what this session *is* rather than
with the background.

Most of that comes out of the environment. One part cannot: whether a terminal
will hand its clipboard back is in no variable, and it is the fact that decides
whether `p` can ever work. So the window asks for the clipboard when it opens
and reads `fromSystem` off the answer -- a measurement, not a table lookup --
and this driver checks it both ways round by being a terminal that refuses and
then a terminal that answers.

Two processes, because the environment is fixed when one starts: one dressed as
an ssh session inside tmux, one dressed as a local X11 session.
"""

import base64
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

F1 = b"\x1bOP"
PGDN = b"\x1b[6~"
END = b"\x1b[F"
ALT_F3 = b"\x1b\x1bOR"

def base_env():
    env = dict(os.environ, TERM="xterm-256color",
               HOME=tempfile.mkdtemp(prefix="predc-home-"))
    env.pop("XDG_CONFIG_HOME", None)
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    for name in ("SSH_CONNECTION", "SSH_TTY", "SSH_CLIENT", "TMUX", "STY"):
        env.pop(name, None)
    return env


TITLES = ("Copying and pasting", "What is in here")


def frame(app):
    """(first row, last row) of the window's own border, on screen.

    Found rather than assumed, because the whole point of the window is that
    its height is the desktop's: a driver with `ROWS = 17` in it would be
    testing the terminal this file was written on.

    Either title, because there is one window and the title is the page: the
    two entries on the Help menu open the same `windowId` and the second one
    re-renders the first rather than adding a window.
    """
    rows = app.render().split("\n")
    top = next((i for i, r in enumerate(rows)
                if any(t in r for t in TITLES)), None)
    if top is None:
        return None
    bottom = next((i for i in range(top + 1, len(rows)) if "\u2514" in rows[i]), None)
    return None if bottom is None else (top, bottom)


def text(app):
    """The window's visible text, one string per row, frame trimmed."""
    edges = frame(app)
    if edges is None:
        return []
    screen = app.render().split("\n")
    # One row in from the top border, and one short of the blank row above the
    # bottom one.
    return [screen[i][5:74].rstrip() for i in range(edges[0] + 1, edges[1] - 1)]


def page(app):
    return "\n".join(text(app))


def start(env):
    app = Pty(node_argv(LAUNCHER), env, cwd=tempfile.mkdtemp(prefix="predc-help-"))
    app.pump(2.5)
    return app


def answer_clipboard(app, body, settle=1.2):
    """Play a terminal that answers an OSC 52 read query.

    Returns whether predc actually asked -- which over a terminal that has not
    claimed support it will not have, and that is the case the window is for.
    """
    mark = len(app.buf)
    app.send(F1, settle=0.8)
    asked = b"\x1b]52;;?\x07" in app.buf[mark:]
    app.send(b"\x1b]52;;" + base64.b64encode(body.encode()) + b"\x07", settle=settle)
    return asked


def open_menu(app, name):
    bar = app.render().split("\n")[0]
    app.click(bar.index(name) + 1, 1, settle=0.7)


def click_entry(app, text, settle=0.9):
    for row, line in enumerate(app.render().split("\n")):
        if text in line and "\u2502" in line:
            app.click(line.index(text) + 1, row + 1, settle=settle)
            return True
    return False


def whole_page(app):
    """Every line of the page, by paging to the bottom and keeping what is new.

    The window is as tall as the desktop and both pages are longer than that,
    so nothing that asks "is X on this page" can look at one screenful. `End`
    would reach the last screen and skip the middle.
    """
    app.send(b"\x1b[H", settle=0.7)
    seen = list(text(app))
    for _ in range(12):
        before = list(text(app))
        app.send(PGDN, settle=0.5)
        if text(app) == before:
            break
        seen += text(app)
    return "\n".join(seen)


def main():
    check = Checks()

    # 0. The inventory page, and the two lists it is a copy of.
    #
    #    It is a copy because `Help` cannot import the tools -- `Tool.Unicode`
    #    imports `Help` for `pasteHint`, so the other direction is a cycle --
    #    and a copy nothing checks is a copy that goes stale. The titles and
    #    the Alt-keys are checked against the tools' own menu items by
    #    `tests/src/HelpTests.gren`, which is a leaf and can import both, in
    #    milliseconds. What is left for this file is the third column: the
    #    command-line word, which has no other copy in the program to compare
    #    against because `Cli.gren` keeps its words inside an
    #    `Argparse.Parser.App` rather than in a list. `predc --help` prints
    #    them, so that is the copy to check against.
    env = base_env()
    app = start(env)

    open_menu(app, "Help")
    menu = app.render()
    check("the Help menu offers the inventory as well as the clipboard page",
          "What is in here" in menu and "Copying and pasting" in menu, menu)
    #    Order, not just presence: this is the entry somebody opens the menu
    #    looking for, and the clipboard page is the one they are *sent* to.
    rows = app.render().split("\n")
    at = lambda title: next(i for i, r in enumerate(rows) if title in r)
    check("with the inventory first", at("What is in here") < at("Copying and pasting"),
          "\n".join(rows[at("What is in here") - 1:at("Copying and pasting") + 1]))

    #    Opening it must not ask the terminal for its clipboard. The probe is a
    #    real OSC 52 read going out on the wire, and it belongs to the question
    #    "why will this not paste" rather than to "what tools are there".
    mark = len(app.buf)
    check("the inventory opens", click_entry(app, "What is in here", settle=1.4))
    check("under its own title", "What is in here" in app.render().split("\n")[2],
          app.render().split("\n")[2])
    check("and asking what is here does not ask the terminal for its clipboard",
          b"\x1b]52;;?\x07" not in app.buf[mark:])

    listing = whole_page(app)
    listed = re.findall(r"^  (\S.{0,21}?)\s{2,}(Alt-\w)\s+predc (\w+)",
                        listing, re.M)
    words = {name: word for name, _key, word in listed}
    keys = {name: key for name, key, _word in listed}
    check("it lists ten tools", len(words) == 10, str(sorted(words)))
    check("with an Alt-key for each", len(keys) == 10, str(sorted(keys.items())))
    #    Every name says something a menu title does not: the ASCII chart is a
    #    grid of 128, the calculator is exact, the decoder names what is wrong.
    for phrase in ("Ctrl- chord", "2^64-1", "never loads the file",
                   "daylight saving", "U+FFFD", "week it is in",
                   "sniffed", "v4 UUID", "not refreshable", "outlive the terminal"):
        check(f"and what it is for, not only what it is called: {phrase!r}",
              phrase in listing, listing)
    check("the shell's own keys are on it too",
          "F6" in listing and "Alt-F3" in listing and "Alt-X" in listing, listing)
    check("and it points at the other page for the clipboard",
          "its own subject: F1" in listing, listing)

    #    The third column against the only other place the words exist.
    printed = subprocess.run(node_argv(LAUNCHER, "--help"),
                             capture_output=True, env=env).stdout.decode()
    for name, word in sorted(words.items()):
        check(f"predc --help knows the command the page gives for {name}",
              re.search(rf"^\s+predc {word}$", printed, re.M) is not None,
              f"{word!r} is not a command in --help")
    #    And the other direction, which is the one that catches a *new* tool:
    #    a command added to the parser and not to the page. A set because
    #    --help prints its commands twice, once as the common ones and once as
    #    the full list.
    offered = set(re.findall(r"^\s+predc (\w+)$", printed, re.M))
    check("and the page names every command predc --help offers",
          offered == set(words.values()),
          f"only in --help: {sorted(offered - set(words.values()))}; "
          f"only on the page: {sorted(set(words.values()) - offered)}")

    #    One window, two pages: F1 from here swaps the page rather than
    #    stacking a second window on the desktop.
    app.send(F1, settle=1.4)
    check("F1 from the inventory turns it into the clipboard page",
          "Copying and pasting" in app.render().split("\n")[2],
          app.render().split("\n")[2])
    check("and there is still only one help window",
          app.render().count("What is in here") == 0, app.render())
    app.send(ALT_F3, settle=0.9)
    app.send(b"\x1bx", settle=1.0)
    check("that session exits cleanly", app.wait() == 0)

    # 1. Dressed as an ssh session inside tmux, with a terminal that answers
    #    nothing -- which is the session the window exists for.
    env = base_env()
    env["SSH_CONNECTION"] = "10.0.0.1 51234 10.0.0.2 22"
    env["TMUX"] = "/tmp/tmux-1000/default,4242,0"
    app = start(env)

    app.send(F1, settle=1.5)
    check("F1 opens it", "Copying and pasting" in app.render().split("\n")[2],
          app.render().split("\n")[2])
    check("and it opens on this session rather than on the background",
          text(app)[0] == "THIS SESSION", repr(text(app)[0]))
    check("which it read out of the environment",
          "Over ssh, inside tmux." in page(app) and "TERM=xterm-256color" in page(app),
          page(app))
    check("and it says the helper programs are not even tried",
          "No DISPLAY" in page(app) and "far end's" in page(app), page(app))

    #    The measured half. Nothing has claimed OSC 52 support, so Turbo Vision
    #    does not write the read query at all and the answer is this program's
    #    own last copy -- `fromSystem` false, which is the fact that settles it.
    check("it measured that nothing outside answered",
          "nothing outside this program answered" in page(app), page(app))
    check("and says plainly that no setting will change it",
          "no setting that changes this" in page(app), page(app))

    # 2. It scrolls, and the whole of it is reachable.
    check("the top of the window is not the end of it",
          "WHAT TO PRESS" in page(app), page(app))
    #    A screenful is however many rows the window turned out to have, so the
    #    check is against that rather than against a number: page down once,
    #    then start again and press Down as many times as there are rows, and
    #    the two have to land on the same lines.
    on_screen = len(text(app))
    app.send(PGDN, settle=0.7)
    paged = text(app)
    app.send(b"\x1b[H", settle=0.6)
    app.send(b"\x1b[B" * on_screen, settle=1.0)
    check("PgDn moves by exactly what is on the screen, whatever that is",
          paged == text(app), f"{on_screen} rows: {paged[0]!r} vs {text(app)[0]!r}")
    app.send(END, settle=0.7)
    check("End reaches the last line, which points at the long version",
          "doc/clipboard.md" in page(app), page(app))
    check("and the six stores are named on the way there",
          "X11 PRIMARY" in page(app) and "X11 CLIPBOARD" in page(app), page(app))

    # 3. What to press, which is the point of the window and is therefore on
    #    the *first* screenful, under the verdict and above everything else.
    app.send(b"\x1b[H", settle=0.7)          # Home
    check("the answer that always works is on the first screen, unscrolled",
          "Ctrl-Shift-V" in page(app), page(app))
    app.send(PGDN, settle=0.7)
    check("and it warns that a plain middle-click will not do it",
          "middle-click" in page(app), page(app))
    #    The one other line that knows where it is: prefix ] is the answer for
    #    somebody inside tmux and noise for everybody else.
    check("inside tmux it gets a row of its own for prefix ]",
          "From tmux" in page(app), page(app))

    # 3b. And the height is the desktop's, which is the whole reason `frame`
    #     above goes looking rather than assuming. A tall pane should show more
    #     of a long document, not the same seventeen rows with empty desktop
    #     under them.
    def height():
        edges = frame(app)
        return None if edges is None else edges[1] - edges[0] + 1

    app.resize(100, 45)
    app.pump(1.2)
    tall = height()
    check("a taller terminal makes a taller window", tall == 42, str(tall))
    check("and more of the document is on it at once", len(text(app)) == 39,
          str(len(text(app))))
    app.resize(80, 24)
    app.pump(1.2)
    check("and shrinking it back shrinks the window", height() == 21, str(height()))
    check("which is still more than the twenty-four-row terminal had before",
          len(text(app)) == 18, str(len(text(app))))

    #     And it has to *fit*. The window is `textRows + 3` tall and sits one
    #     row down, so a floor on the row count is a floor that hangs off the
    #     bottom of a short desktop -- which a friendlier-looking three did, on
    #     an eight-row terminal, drawing a window with no bottom border.
    app.resize(80, 8)
    app.pump(1.2)
    edges = frame(app)
    rows = app.render().split("\n")
    check("on an eight-row terminal the window still has a bottom border",
          edges is not None, "no frame found")
    check("and it is above the status line rather than under it",
          edges is not None and edges[1] <= len(rows) - 2,
          f"{edges} of {len(rows)} rows")
    app.resize(80, 24)
    app.pump(1.2)

    app.send(ALT_F3, settle=1.0)
    check("Alt-F3 closes it", "Copying and pasting" not in app.render(),
          app.render().split("\n")[2])
    app.send(b"\x1bx", settle=1.0)
    check("and that session exits cleanly", app.wait() == 0)

    # 4. A terminal that *does* answer, which is the other half of the
    #    measurement. `ESC]60;allowWindowOps` is what TVision reads as the
    #    claim, and after it the window's question is a real query on the wire.
    app = start(base_env())
    app.send(b"\x1b]60;allowWindowOps\x07", settle=0.6)
    check("with a terminal that answers, the window's question goes out",
          answer_clipboard(app, "whatever is on the clipboard"))
    check("and it reports that reading works here",
          "answered a clipboard" in page(app) and "p and P work here" in page(app),
          page(app))
    check("without the ssh line, since this session has none",
          "Over ssh" not in page(app), page(app))
    app.send(PGDN, settle=0.7)
    app.send(PGDN, settle=0.7)
    #    "prefix ]" on its own is no good as a check: the section on the two
    #    mechanisms names it too, for everybody. The *row* is what is
    #    conditional.
    check("and with no tmux there is no row for it",
          "From tmux" not in page(app), page(app))

    #    And it asks again on each opening rather than caching: tmux's
    #    set-clipboard and kitty's clipboard_control are live settings, so a
    #    window opened *because* one just changed must not answer from a cache.
    app.send(ALT_F3, settle=0.9)
    check("reopening asks the terminal again", answer_clipboard(app, "second"))

    app.send(b"\x1bx", settle=1.0)
    check("Alt-X exits, and cleanly", app.wait() == 0)

    # 5. And the branch a local user sees, which is the other sentence about
    #    the helper programs. `:99` is a display nobody is running, so xclip
    #    and xsel fail rather than reaching whoever is running this suite --
    #    the wording is what is being checked, not the clipboard.
    env = base_env()
    env["DISPLAY"] = ":99"
    app = start(env)
    app.send(F1, settle=1.5)
    check("with a display, it says the helper programs are tried",
          "DISPLAY is set" in page(app) and "xsel and xclip" in page(app),
          page(app))
    check("and does not go on about the far end, there not being one",
          "far end's" not in page(app), page(app))
    check("nor claim an ssh session",
          "This machine, no multiplexer." in page(app), page(app))
    app.send(b"\x1bx", settle=1.0)
    check("that session exits cleanly too", app.wait() == 0)

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
