#!/usr/bin/env python3
"""Photograph every widget, by running the examples that already use them.

Each shot boots a real example at a real pty -- the same harness the pty
drivers use -- keys it into the state the documentation is describing, and
crops the screen to what it is describing. Nothing here is a mock-up. If a
widget stops drawing, its picture stops drawing too.

    devbox run -- python3 gren-tvision/doc/shots.py            # all of them
    devbox run -- python3 gren-tvision/doc/shots.py listbox    # just these

Windows are **found rather than counted**: `box(app, "Edit record")` returns
the screen rectangle of the innermost frame containing that text, so a shot
survives an example laying itself out differently, and a window that failed to
open is an error here rather than a crop of the desktop. What is still written
down is the rectangle of a *view* inside its window, because that is a number
in the example's source and there is nothing on the screen to find it by --
`inside(box, ...)` takes the same `{x1,y1,x2,y2}` the Gren source does.

One shot is marked `stable=False`, because what it photographs is a clock.
Every other image here is reproducible byte for byte.
"""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)                              # gren-tvision
ROOT = os.path.dirname(PKG)
RUNTIME = os.path.join(PKG, "..", "gren-tvision-runtime", "bin", "gren-tui.js")
IMG = os.path.join(HERE, "img")

sys.path.insert(0, os.path.join(ROOT, "tvision-node", "test"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from harness import Pty, node_argv
import cp437
import shot

# No tapes. A shot is not a test: recording one costs a replay per boot and
# asserts nothing the drivers do not already assert.
ENV = dict(os.environ, TERM="xterm-256color", TVNODE_TAPES="0")

ESC = b"\x1b"
UP, DOWN = b"\x1b[A", b"\x1b[B"
TAB, BACKTAB = b"\t", b"\x1b[Z"
BACKSPACE, ENTER = b"\x7f", b"\r"
F2, F3 = b"\x1bOQ", b"\x1bOR"

wanted = set(sys.argv[1:])
taken = []


# ----------------------------------------------------------- finding things

# The corners of a Turbo Vision frame. The two sets are not the two frames: an
# active window draws a doubled top and a single-cornered bottom -- `╔` up
# there and `└` down here -- so a corner from either set can close a frame
# begun by the other, and matching them in pairs finds nothing at all.
TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT = "\u250c\u2554", "\u2510\u2557", "\u2514\u255a"


def frames(screen):
    """Every framed rectangle on the screen, as (x1, y1, x2, y2)."""
    found = []
    for y in range(screen.rows):
        for x in range(screen.cols):
            if screen.grid[y][x] not in TOP_LEFT:
                continue
            right = next((c for c in range(x + 1, screen.cols)
                          if screen.grid[y][c] in TOP_RIGHT), None)
            bottom = next((r for r in range(y + 1, screen.rows)
                           if screen.grid[r][x] in BOTTOM_LEFT), None)
            if right is not None and bottom is not None:
                found.append((x, y, right + 1, bottom + 1))
    return found


def box(app, text, shadow=False):
    """The screen rectangle of the frame `text` is drawn inside.

    Of the frames that contain it, the one whose top-left corner is nearest --
    which is the innermost, and is not the smallest. Windows overlap: the
    dialog in front of a list window is *bigger* than the window it covers,
    and every row of that window's rectangle picks up the dialog's text
    through it, so "the smallest frame containing this" answers with the
    window underneath.

    A shadow is two columns wide and one row tall and belongs to the window
    that cast it, so `shadow=True` takes it in.
    """
    screen = app.display()
    at = next((("".join(screen.grid[y]).find(text), y)
               for y in range(screen.rows)
               if text in "".join(screen.grid[y])), None)
    if at is None:
        raise AssertionError("%r is not on the screen:\n%s" % (text, app.render()))
    x, y = at
    holding = [f for f in frames(screen)
               if f[0] <= x < f[2] and f[1] <= y < f[3]]
    if not holding:
        raise AssertionError("%r is on the screen but not in a frame:\n%s"
                             % (text, app.render()))
    x1, y1, x2, y2 = min(holding, key=lambda f: (y - f[1]) + (x - f[0]))
    if shadow:
        return (x1, y1, min(x2 + 2, screen.cols), min(y2 + 1, screen.rows))
    return (x1, y1, x2, y2)


def inside(where, view):
    """A view's rectangle, which is relative to its window's frame."""
    x1, y1 = where[0], where[1]
    return (x1 + view["x1"], y1 + view["y1"], x1 + view["x2"], y1 + view["y2"])


def find(app, text):
    """Where a run of characters is on the screen, 1-based, for `click`."""
    for y, line in enumerate(app.render().split("\n")):
        x = line.find(text)
        if x >= 0:
            return x + 1, y + 1
    raise AssertionError("%r is not on the screen:\n%s" % (text, app.render()))


# ------------------------------------------------------------------ running


def boot(name, *args, size=(80, 25), settle=2.2):
    app = Pty(node_argv(RUNTIME, "main.js", *args), ENV,
              cwd=os.path.join(PKG, "examples", name), size=size)
    app.pump(settle)
    return app


def quit(app):
    app.send(b"\x1bx", settle=0.4)
    app.kill()


def wants(*names):
    return not wanted or wanted & set(names)


def take(app, name, rect=None, stable=True, **kw):
    path = shot.shot(app, os.path.join(IMG, name + ".png"), rect, **kw)
    taken.append((name, stable))
    print("  %-22s %6d bytes%s"
          % (name + ".png", os.path.getsize(path), "" if stable else "   (a clock)"))


# ---------------------------------------------------------------- forms
#
# The whole cluster family in one dialog, which is why most of the widget shots
# come from here: labels bound to fields, check boxes, radio buttons and
# multi-state boxes, all holding a record the model put in them.


def forms():
    app = boot("forms")

    take(app, "screen")
    # The list plus the column to its right, where a `ListBox` puts its own
    # scroll bar. The highlight is on it because the list is the first
    # selectable view in the window and so has the caret.
    take(app, "listbox",
         inside(box(app, "Phone Numbers"),
                {"x1": 1, "y1": 1, "x2": 30, "y2": 13}))

    # A click on its title bar brings the right-hand window forward, which is
    # not vanity: the window in front draws its shadow across the frame of the
    # one behind, and in a crop this narrow that shadow is the left-hand
    # column. `click` counts from one, as a terminal's mouse report does, so
    # row 2 is the frame and not the menu bar -- and clicking the frame rather
    # than a row inside the window leaves the list's highlight where it is,
    # which every shot below still depends on.
    app.click(61, 2, settle=0.8)
    take(app, "statictext", box(app, "Record"))
    app.click(21, 2, settle=0.8)

    app.send(b"\x1bf", settle=0.9)
    take(app, "menubar", (0, 0, box(app, "New record")[2], 8))
    app.send(ESC, settle=0.5)

    take(app, "statusline", (0, 24, 80, 25))

    # F3 edits the highlighted record, so every field arrives with something in
    # it -- and the first field takes the caret and selects its whole value,
    # which is `TInputLine`'s own behaviour on gaining focus.
    app.send(F3, settle=1.2)
    form = box(app, "Edit record")
    take(app, "dialog", form, cursor=True)
    take(app, "label", inside(form, {"x1": 1, "y1": 1, "x2": 39, "y2": 8}),
         cursor=True)
    # The phone field, which is the one with an `allowed` set on it.
    take(app, "inputline", inside(form, {"x1": 1, "y1": 8, "x2": 39, "y2": 9}),
         pad=1)
    take(app, "checkboxes", inside(form, {"x1": 10, "y1": 10, "x2": 25, "y2": 13}))
    take(app, "radiobuttons", inside(form, {"x1": 25, "y1": 10, "x2": 39, "y2": 13}))
    # Two columns wider than the buttons, because a button's shadow is drawn
    # to the right of it and a crop of the rectangle alone cuts it in half.
    take(app, "button", inside(form, {"x1": 12, "y1": 17, "x2": 40, "y2": 19}))

    # Two states are what a `CheckBoxes` can already say. Alt-H focuses the
    # cluster and Space cycles a box through " ", "?" and "X" and wraps, so
    # this leaves one box on the state that is the reason the widget exists and
    # the other on a plain tick.
    app.send(b"\x1bh", settle=0.5)
    app.send(b" ", settle=0.3)
    app.send(b" ", settle=0.4)
    app.send(DOWN, settle=0.3)
    app.send(b" ", settle=0.3)
    app.send(b" ", settle=0.4)
    take(app, "multicheckboxes",
         inside(form, {"x1": 1, "y1": 14, "x2": 28, "y2": 17}))

    app.send(ESC, settle=0.6)
    quit(app)


# ---------------------------------------------------------------- entries


def entries():
    app = boot("entries")
    # The clock window opens second and so has the caret. Alt-L raises the list
    # -- which is what makes its frame the doubled one, and what puts the caret
    # in the filter field the next few keys type into.
    app.send(b"\x1bl", settle=1.0)

    take(app, "window", box(app, "Entries (", shadow=True))

    # A filter is remembered when something is chosen out of it, so each of
    # these is: type, Tab to the list, Space to commit, Tab back. Nothing is in
    # the drop-down until the model puts it there, and the arrow is not drawn
    # until there is.
    for text in (b"bor", b"gren"):
        app.send(text, settle=0.9)
        app.send(TAB, settle=0.4)
        app.send(b" ", settle=0.9)
        app.send(BACKTAB, settle=0.4)
        # A burst of the same key is a burst of events rather than a moving
        # screen, so this waits the whole time rather than settling.
        app.send(BACKSPACE * len(text), wait=1.0)
    # Where the window is has to be answered before the drop-down is opened:
    # the list comes up over the title the window would be found by.
    where = box(app, "Entries (")
    # The arrow is `▐↓▌` and the button is its middle column. Searching for the
    # three together matters: the list box below has a `▼` of its own on its
    # scroll bar, and clicking that moves the highlight instead.
    col, row = find(app, "\u2590\u2193\u258c")
    app.click(col + 1, row, settle=1.2)
    take(app, "history", inside(where, {"x1": 0, "y1": 0, "x2": 45, "y2": 7}))
    app.send(ESC, settle=0.6)
    app.send(BACKSPACE, settle=0.8)

    app.send(b"\x1ba", settle=1.2)
    app.send(b"Gren", settle=0.6)
    take(app, "dialogtyped", box(app, "Add an entry"), cursor=True)
    app.send(ESC, settle=0.6)

    # Alt-E opens the menu; Clear has no hot key of its own, so its letter
    # picks it out of the pull-down.
    app.send(b"\x1be", settle=0.8)
    app.send(b"c", settle=1.2)
    take(app, "messagebox", box(app, "Throw away"))

    # Answering Yes empties the list and greys the command out with
    # `setEnabled`, everywhere it appears. A disabled entry is checked by its
    # colour and not by what it refuses, because an entry is only ever looked
    # at -- so this is the shot that says what "greyed out" means here.
    app.send(b"y", settle=1.2)
    app.send(b"\x1be", settle=1.0)
    # Off the disabled entry, so that what greys it out is its own colour
    # rather than the highlight it happened to open under.
    app.send(UP, settle=0.5)
    take(app, "disabled", box(app, "Clear"))
    app.send(ESC, settle=0.6)
    quit(app)


def grows():
    """The same window in two terminals, which is the whole of `Grows`."""
    narrow = boot("entries")
    narrow.send(b"\x1bl", settle=1.0)
    take(narrow, "grows-80", box(narrow, "Entries ("))
    quit(narrow)

    wide = boot("entries", size=(100, 30))
    wide.send(b"\x1bl", settle=1.0)
    take(wide, "grows-100", box(wide, "Entries ("))
    quit(wide)


# ---------------------------------------------------------------- the rest


def hello():
    app = boot("hello")
    app.send(b"\x1bg", settle=1.2)
    take(app, "buttons", box(app, "How are you?"))
    app.send(ESC, settle=0.5)
    quit(app)


def mmenu():
    """A plain command sitting on the bar, beside two pull-downs."""
    app = boot("mmenu")
    take(app, "menucommand", (0, 0, 40, 1))
    quit(app)


def mouse():
    app = boot("mouse")
    app.send(b"\x1bm", settle=1.2)
    where = box(app, "Mouse double click")
    take(app, "scrollbar", inside(where, {"x1": 1, "y1": 2, "x2": 33, "y2": 6}))
    app.send(ESC, settle=0.5)
    quit(app)


def ascii_chart():
    app = boot("ascii")
    take(app, "canvas", box(app, "ASCII Chart"), cursor=True)
    quit(app)


def editor():
    work = tempfile.mkdtemp(prefix="tvshot-")
    try:
        path = os.path.join(work, "notes.txt")
        with open(path, "w") as out:
            out.write(
                "-- The editor owns its document, and the model owns the file.\n"
                "\n"
                "view : Model -> Ui\n"
                "update : Msg -> Model -> { model : Model, command : Cmd Msg }\n"
                "\n"
                "Everything else here is a function of the model and is\n"
                "re-rendered from it. A document is the first thing too big\n"
                "for that.\n")
        app = boot("edit", path)
        take(app, "editor", box(app, "notes.txt"))
        quit(app)
    finally:
        shutil.rmtree(work, True)


def directory():
    """A fixed path rather than a temp one: it is in the window's title."""
    root = os.path.join(tempfile.gettempdir(), "gren-tvision-shots")
    shutil.rmtree(root, True)
    for path in ("src/Tui", "doc", "examples"):
        os.makedirs(os.path.join(root, path))
    for where, names in {
        "": ["README.md", "gren.json"],
        "src": ["Tui.gren"],
        "doc": ["widgets.md", "architecture.md"],
    }.items():
        for name in names:
            open(os.path.join(root, where, name), "w").close()

    app = boot("dir", root, settle=2.6)
    # There is no tree widget and none is needed: the model owns the structure,
    # the visible rows are a fold over it, and a `ListBox` displays them. This
    # is the picture of that paragraph.
    take(app, "tree", box(app, "gren-tvision-shots"))

    app.send(b"\x1bc", settle=1.6)
    take(app, "filedialog", box(app, "Change directory"))
    app.send(ESC, settle=0.6)
    quit(app)


def palette():
    """The sixteen colours a `Span` can name, each said in its own colour."""
    app = boot("palette")
    take(app, "colours", box(app, "Colours, said out loud"))
    quit(app)


def demo():
    app = boot("demo", settle=2.6)

    # Tile is one of the command names Turbo Vision handles itself. The menu is
    # opened by clicking its title, because this bar's entries carry no Alt key
    # of their own.
    app.click(*find(app, "Windows"), settle=0.8)
    app.send(b"t", settle=1.2)
    take(app, "tile", stable=False)

    # Two right clicks and not one: the first is spent activating the window,
    # which is `TView::handleEvent`'s rule for a click on anything that has not
    # got the focus.
    app.right_click(11, 11, wait=1.0)
    app.right_click(11, 11, wait=1.2)
    take(app, "popup", box(app, "Alt-F3"))
    app.send(ESC, settle=0.8)

    # An overlay is on the application rather than on the desktop, so it is in
    # screen coordinates and row 0 is the menu bar's own row. Two rows, to show
    # that it is sitting above a window rather than in one.
    take(app, "overlay", (58, 0, 80, 3), stable=False)
    quit(app)


SECTIONS = [
    ("forms", forms, ("screen", "statictext", "listbox", "menubar", "statusline",
                      "dialog", "label", "inputline", "checkboxes",
                      "radiobuttons", "multicheckboxes", "button")),
    ("entries", entries, ("window", "history", "dialogtyped", "messagebox",
                          "disabled")),
    ("grows", grows, ("grows-80", "grows-100")),
    ("hello", hello, ("buttons",)),
    ("mmenu", mmenu, ("menucommand",)),
    ("mouse", mouse, ("scrollbar",)),
    ("ascii", ascii_chart, ("canvas",)),
    ("edit", editor, ("editor",)),
    ("dir", directory, ("filedialog", "tree")),
    ("palette", palette, ("colours",)),
    ("demo", demo, ("tile", "popup", "overlay")),
]


def main():
    print("shots into %s" % os.path.relpath(IMG, os.getcwd()))
    for name, run, names in SECTIONS:
        if wants(name, *names):
            print("%s:" % name)
            run()
    print("%d shots, %d of them reproducible"
          % (len(taken), sum(1 for _, stable in taken if stable)))
    # A character CP437 has no code for is drawn as `?`, which in a screenshot
    # is indistinguishable from a program that meant to draw one. Saying so
    # here is the difference between a picture that is wrong and a picture that
    # is wrong and nobody was told.
    if cp437.unknown:
        print("not in the font, drawn as `?`: %s"
              % " ".join(sorted(cp437.unknown)))


if __name__ == "__main__":
    main()
