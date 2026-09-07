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

import base64
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv, tape_env

# A whole environment, and nothing inherited. `env -i` in spirit: every count
# below is exact because this is very nearly the entire list the process will
# have, and a machine that happened to export one more variable would otherwise
# move them. Very nearly, and not quite -- see `child_env_size`, which is why no
# count below is written as `len(env)`.
# EUC-KR for two Hangul syllables, and a path with one of them in it. Written
# as lone surrogates because `os.execvpe` encodes a str with the filesystem
# encoding and the `surrogateescape` handler, so `U+DCB0` goes back out as the
# single byte `0xB0` -- which is the only way a test can put bytes in an
# environment that Python itself refuses to call text.
KR = "\udcb0\udca1\udcb0\udca2"

PLANTED = {
    "TERM": "xterm-256color",
    "ZZ_BYTES": KR,
    "ZZ_INSIDE": "/home/" + KR + "/docs",
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


def foot_colours(app, key, word):
    """(key colour, word colour) off the line along the foot.

    The keys down there are the only way to reach the list at all -- the search
    box has the caret when the window opens -- and they were the tail of a
    sentence in a single ink until the line became a canvas the model paints.
    """
    d = app.display()
    for row, line in enumerate(app.render().split("\n")):
        at = line.find(word)
        if at < 0:
            continue
        start = line.rfind(key, 0, at)
        if start < 0:
            continue
        return (d.fg_at(start, row), d.fg_at(at, row))
    return None


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
    app.send(b"\x08" * 32, wait=1.0)


def child_env_size(env):
    """How many variables the program under test will actually have.

    Not `len(env)`. Under `--asan` the launcher is `test/asan.sh`, which
    exports `LD_PRELOAD` and `ASAN_OPTIONS` -- and, being a bash script, hands
    on `PWD` and `SHLVL` too. Four more than were planted, and every count in
    this driver is exact, which is the entire reason it builds an environment
    instead of inheriting one. Under ASAN the whole suite failed on five checks
    that were about filtering rather than about counting.

    So the number is asked for rather than assumed, through the same
    `node_argv` the application is launched with: whatever that wrapper adds
    today, this follows. A `+ 4` would have been right until somebody edited
    `asan.sh`, and would then have been wrong in the configuration nobody runs
    by hand.
    """
    argv = node_argv("-e", "console.log(Object.keys(process.env).length)")
    # And through the environment the harness will hand the program, not the
    # one planted here: it adds `TUI_RECORD_VERBATIM` so that every session is
    # recorded and replayed, which is one more variable on the screen. Same
    # rule as the paragraph above, one wrapper further out.
    out = subprocess.run(argv, env=tape_env(env), capture_output=True,
                         text=True, timeout=60)
    return int(out.stdout.strip())


def last_copy(app):
    """What the most recent copy put on the clipboard.

    A copy is an `OSC 52` on the wire with the text base64'd into it, and it is
    only there because the environment this driver builds has no `DISPLAY` and
    no `WAYLAND_DISPLAY` -- with either of them TVision would try `wl-copy` and
    friends first and write nothing this can read (and would set the real
    clipboard, which a test must not).

    Decoded rather than matched against, because base64 is grouped in threes:
    the encoding of a substring is not a substring of the encoding, so
    searching the wire for a short string finds it only when it is the whole
    payload. That is exactly the difference between checking `y` and checking
    `Y`.
    """
    marker = b"\x1b]52;;"
    at = app.buf.rfind(marker)
    if at < 0:
        return ""
    rest = app.buf[at + len(marker):]
    end = rest.find(b"\x07")
    if end < 0:
        return ""
    return base64.b64decode(rest[:end]).decode("utf-8", "replace")


def cursor_row(app, left):
    """Which screen row the cursor bar is on, by its background.

    The cursor is an ink and not a character -- it is a bar of the selected
    colours across the whole width, which is what makes it findable: no other
    row in the list is painted to the right of its text. So the test is a cell
    well past the longest value, and the answer is the row where that cell
    stops being the window's own background.
    """
    where = app.display()
    ordinary = where.bg_at(left + 60, 3)
    for row, line in enumerate(app.render().split("\n")):
        if line[left:left + 1] == "\u2551" and where.bg_at(left + 60, row) != ordinary:
            return row
    return None


def main():
    check = Checks()
    home = tempfile.mkdtemp(prefix="predc-home-")
    env = dict(PLANTED, HOME=home, PATH=os.environ.get("PATH", "/usr/bin"))

    total = child_env_size(env)

    app = Pty(node_argv(LAUNCHER, "env"), env, cwd=ROOT)
    app.pump(2.5)

    body = listed(app)
    check("predc env opens the list", "Environment" in app.render(), app.render())
    check("every variable is there, and no others",
          status(app).startswith(f"{total} variables"), status(app))
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
          status(app).startswith(f"2 of {total} match \"alpha\""), status(app))

    # The keys at the end of that line are drawn the way the status line at the
    # bottom of the screen draws `Alt-X Exit`: the name of the key in one
    # colour and the word beside it in another. It was one run of one ink, so
    # the keys read as the tail of a sentence -- in the one window where they
    # are the only way out of the search box and into the list.
    shades = foot_colours(app, "Tab", "list")
    check("the keys along the foot are drawn as keys, not as more sentence",
          shades is not None and shades[0] != shades[1], str(shades))
    # ...and the count in front of them is neither of those, because a count is
    # an answer rather than an instruction and goes on being window text.
    d = app.display()
    row = next(r for r, line in enumerate(app.render().split("\n"))
               if "Tab list" in line)
    count = d.fg_at(app.render().split("\n")[row].index("2 of"), row)
    check("and the count in front of them is neither colour",
          shades is not None and count not in shades,
          f"count {count}, hint {shades}")

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
          status(app).startswith(f"{total} variables"), status(app))

    # Nothing matches, and it says so rather than showing an empty box.
    app.send(b"nosuchthing", settle=1.2)
    check("a needle that matches nothing says so",
          "Nothing matches \"nosuchthing\"." in "\n".join(rows(app)), rows(app)[:2])
    check("and the count agrees", status(app).startswith(f"0 of {total}"), status(app))

    menu(app, "Search")
    entry(app, "Show them all")
    check("Show them all is the same as emptying the box",
          box(app) == "" and status(app).startswith(f"{total} variables"),
          (box(app), status(app)))

    # Scrolling, which is now a consequence of the cursor rather than the thing
    # the arrow keys do.
    #
    # **A fixed number of `Down`s is not a test any more.** It was, while every
    # `Down` scrolled by one; now the list moves only when the cursor would
    # leave it, so how many keystrokes that takes depends on how many lines the
    # variables above it wrapped onto -- which depends on the environment. This
    # check used to send three and passed, until `--asan` ran it in an
    # environment with four more variables in it and the third `Down` landed
    # somewhere that did not need to scroll. So: enough to reach the end from
    # anywhere, and the assertion is that it *stopped* there.
    app.send(b"\t\t", settle=0.7)
    first = listed(app)[0]
    app.send(b"\x1b[B", settle=0.7)
    check("Down does not scroll while the cursor is still on screen",
          listed(app)[0] == first, (first, listed(app)[0]))
    app.send(b"\x1b[B" * 60, wait=1.2)
    bottom = listed(app)[0]
    check("but the list follows the cursor off the end of the window",
          bottom != first, (first, bottom))
    app.send(b"\x1b[B" * 10, wait=0.9)
    check("and stops there rather than scrolling past it",
          listed(app)[0] == bottom and listed(app)[-1].strip() != "",
          (bottom, listed(app)[0]))
    app.send(b"\x1b[H", settle=0.9)
    check("Home comes back to the top", listed(app)[0] == first, listed(app)[0])
    app.send(b"\x1b[F", settle=0.9)
    check("End goes to the bottom, and stops there",
          listed(app)[0] != first and listed(app)[-1].strip() != "", listed(app)[-3:])
    app.send(b"\x1b[H", settle=0.9)

    # Copy, and what got copied.
    #
    # The clipboard cannot be read back, but the copy itself is on the wire:
    # with no DISPLAY and no WAYLAND_DISPLAY -- which the environment this
    # driver builds has neither of -- TVision writes an `OSC 52` with the text
    # base64'd into it. So this checks the bytes rather than the status line,
    # which is the difference between "it copied" and "it copied *that*".
    # Filtered to the planted set before any of this, because **which variable
    # is second depends on the environment** -- `--asan` exports four of its
    # own and `ASAN_OPTIONS` sorts between `AA_FIRST` and `HOME`. That is the
    # same mistake as the `Down` counting above, and it was made again in the
    # very next block, so the rule is worth stating twice: a check that names a
    # position in this list has to name a list this driver decides the whole
    # of. Nothing else here begins `ZZ_`.
    app.send(b"/", settle=0.6)
    app.send(b"ZZ_A", settle=1.2)
    app.send(b"\t\t", settle=0.7)
    app.send(b"y", settle=1.2)
    check("y copies the value under the cursor", status(app).startswith("Copied"),
          status(app))
    check("and it is the value alone, not the whole line",
          last_copy(app) == "one", last_copy(app))

    app.send(b"/", settle=0.6)
    app.send(b"\x08" * 8, settle=0.6)
    app.send(b"ZZ_B", settle=1.2)
    app.send(b"\t\t", settle=0.7)
    app.send(b"y", settle=1.2)
    check("and the cursor decides which one",
          last_copy(app) == "two ALPHA three", last_copy(app))

    # Y is the old behaviour, kept because a filtered set is worth copying and
    # a list of bare values would say nothing about which is which. The filter
    # is what makes the expected text writable at all.
    app.send(b"Y", settle=1.2)
    copy = last_copy(app)
    check("Y copies everything shown, as NAME=value",
          copy.startswith("ZZ_BETA=two ALPHA three\n"), repr(copy))
    # And it names the one it cannot write rather than writing the dots off the
    # screen -- which would be the same lie `y` refuses, in a form nobody would
    # check. Leaving the variable out was the other candidate and is worse: a
    # copy of everything shown that quietly is not everything shown.
    check("and names a value it cannot write, with the byte count",
          copy.endswith("ZZ_BYTES=<4 bytes, not text>"), repr(copy))

    # A value that is not text refuses rather than copying its own rendering:
    # the dots on the screen are not what is in the variable, and a clipboard
    # holds text.
    app.send(b"/", settle=0.6)
    app.send(b"ZZ_BYTES", settle=1.2)
    app.send(b"\t\t", settle=0.7)
    before = app.buf.count(b"\x1b]52;;")
    app.send(b"y", settle=1.0)
    check("y refuses a value that is not text, and says where to look",
          "not text" in status(app) and "hex" in status(app), status(app))
    # Nothing new on the wire at all, which is a stronger claim than "not the
    # dots": a refusal that copied something else would pass that one.
    check("and puts nothing on the clipboard",
          app.buf.count(b"\x1b]52;;") == before,
          (before, app.buf.count(b"\x1b]52;;")))
    clear(app)

    # ---------------------------------------------------------------- #
    #  Values that are bytes rather than text                           #
    # ---------------------------------------------------------------- #

    # The whole point of reading `/proc/self/environ`. `process.env` would have
    # handed predc one `U+FFFD` per byte and nothing else, so a check that the
    # dots are dots is a check that the raw block is what the list is built
    # from -- there is no other way for those four bytes to become four of
    # anything.
    clear(app)
    app.send(b"ZZ_", settle=1.2)
    body = listed(app)
    check("a value that is not UTF-8 is shown as bytes, not as damage",
          any(row.startswith("ZZ_BYTES") and row.split()[1] == "...." for row in body),
          body)
    # Four dots for four bytes, and the slashes still slashes: a path with one
    # Korean directory in it still reads as a path.
    check("and the ASCII around it survives, which is what makes it readable",
          any(row.startswith("ZZ_INSIDE") and "/home/..../docs" in row for row in body),
          body)

    # The mark is the ink and not a character, so this is the only way to see
    # it. Compared against a plain row rather than against a constant: what
    # matters is that the two differ, and every theme answers that differently.
    where = app.display()
    left, _, _ = frame(app)
    lines = app.render().split("\n")

    def row_of(name):
        return next(i for i, line in enumerate(lines)
                    if line[left + 1:].startswith(name + " "))

    bytes_row = row_of("ZZ_BYTES")
    plain_row = row_of("ZZ_ALPHA")
    # The first dot is where the bytes are, and the same column on the plain
    # row is inside its value. Read off the screen rather than computed,
    # because the name column is a third of a window of any width.
    value_col = lines[bytes_row].index("....")
    check("a value it cannot show is drawn in a different ink from one it can",
          where.fg_at(value_col, bytes_row) != where.fg_at(value_col, plain_row),
          (where.fg_at(value_col, bytes_row), where.fg_at(value_col, plain_row)))

    # ---------------------------------------------------------------- #
    #  The cursor, and the hex viewer it exists for                     #
    # ---------------------------------------------------------------- #

    app.send(b"\t\t", settle=0.7)
    first = cursor_row(app, left)
    check("the list has a cursor, and it starts at the top of what is shown",
          first is not None
          and app.render().split("\n")[first][left + 1:].startswith("ZZ_ALPHA"),
          first)
    app.send(b"\x1b[B", settle=0.6)
    second = cursor_row(app, left)
    check("Down moves it to the next variable",
          second is not None
          and app.render().split("\n")[second][left + 1:].startswith("ZZ_BETA"),
          second)
    app.send(b"\x1b[A", settle=0.6)
    check("and Up comes back", cursor_row(app, left) == first, cursor_row(app, left))

    # `ZZ_LONG` wraps onto four lines, so it is the check that the cursor
    # counts variables and not rows: one Down off it lands on the variable
    # after it rather than on its own second line.
    app.send(b"\x1b[B" * 4, settle=0.8)
    on = cursor_row(app, left)
    check("a value that wraps is one stop and not four",
          on is not None
          and app.render().split("\n")[on][left + 1:].startswith("ZZ_INSIDE"),
          app.render().split("\n")[on][left + 1:left + 30] if on else None)

    # The reason all of it exists. Narrowed to the one variable so the check
    # is about the bytes rather than about where the cursor happened to be.
    app.send(b"/", settle=0.6)
    app.send(b"BYTES", settle=1.2)
    app.send(b"\t\t", settle=0.7)
    app.send(b"x", settle=1.5)
    check("x sends the value under the cursor to the hex viewer",
          "Hex Dump" in app.render() and "$ZZ_BYTES" in app.render(),
          app.render().split("\n")[1])
    check("and the bytes are the ones that were really in the environment",
          "B0 A1 B0 A2" in app.render(), app.render())
    check("with the size the value really had, not the size of its damage",
          "(4 bytes)" in app.render(), app.render().split("\n")[1])


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

    # And it can be un-maximized, which for a window that fills the terminal
    # from birth is not free: Turbo Vision remembers where to un-zoom *to* by
    # storing the bounds it had before it was zoomed, and a window that was
    # never zoomed by the user has only the bounds it was built at -- the whole
    # terminal. So `zoom()` restored it to exactly where it was and the box did
    # nothing, while the frame went on drawing `[↕]` to say it would. The
    # binding computes one at zoom time now; see `JsWindow::zoom`.
    #
    # Checked here and not only in `tvision-node/test/drive_drag.py` because
    # this window is where it was reported, and because `Tool.Env` is the one
    # tool that sizes itself from the desktop and so the only one that could
    # have hit it.
    check("a window that opens maximized draws the un-zoom box",
          "[↕]" in big.render(), big.render().split("\n")[1])
    big.send(b"\x1b[15~", settle=1.2)      # F5
    check("and F5 really un-maximizes it",
          frame(big)[0] > 0 and frame(big)[1] < 69, frame(big))
    left, right, _ = frame(big)
    check("and the value re-wraps to the un-maximized width, as on a resize",
          run_of_x(big) == (right - left + 1) - 3 - len("ZZ_LONG") - 2,
          f"{run_of_x(big)} in a window {right - left + 1} wide")

    big.send(b"\x1bx", settle=1.0)
    code = big.wait(timeout=6)
    check("and that one exits cleanly too", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
