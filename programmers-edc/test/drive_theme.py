#!/usr/bin/env python3
"""predc's colour schemes: the two halves of a theme, and the file it remembers.

A theme here is two things that a `Tui.Theme` cannot make into one. The
*palette* is every colour gren-tvision draws -- the desktop, the menu bar, the
frames, the dialogs -- and it goes to the binding as seventeen fields that
become a hundred and thirty-five attributes. The *inks* are what the tools'
own canvases paint with, and a palette cannot reach them: a span names a
`Tui.Hue` and there is nothing between it and the terminal. This driver's job
is to show that both move and that they move together.

The clearest evidence is the Gren theme, which is a light one. Every ink the
other two use is a bright hue, and on a light ground every bright hue is
invisible -- so if the inks did not change with the palette, this is where it
would show. The check is that the chart's ruler is a *dark* hue under Gren and
a bright one under Borland, which is a fact about the model rather than about
any particular colour.

The file predc remembers it in is TOML, and section 6b is here because that is
a format with comments in it. A config file somebody can annotate is a config
file somebody annotates, and predc writes to it on every theme change -- so
what the driver checks is that a hand-written comment, a hand-written blank
line and a key predc has never heard of are all still there after predc has
written the file twice.

Two mechanical notes. `HOME` is a fresh temporary directory, so the first run
has no config file and the checks are not at the mercy of whatever is in the
real one. And `COLORTERM=truecolor` is set because two of the three themes are
`Rgb` throughout: without it TVision quantises them to the sixteen and the
assertions below stop being about what was asked for.
"""

import os
import sys
import tempfile
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv


def start(home, argv_env=None):
    env = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor", HOME=home)
    env.pop("XDG_CONFIG_HOME", None)
    if argv_env:
        env.update(argv_env)
    app = Pty(node_argv(LAUNCHER), env, cwd=tempfile.mkdtemp())
    app.pump(2.5)
    return app


def config_file(home):
    return os.path.join(home, ".config", "predc", "config.toml")


def open_menu(app, name):
    bar = app.render().split("\n")[0]
    app.click(bar.index(name) + 1, 1, settle=0.7)


def click_entry(app, text, settle=0.9):
    """Click the menu line containing `text`, wherever the box put it."""
    for row, line in enumerate(app.render().split("\n")):
        if text in line and "│" in line:
            app.click(line.index(text) + 1, row + 1, settle=settle)
            return True
    return False


def choose(app, theme):
    open_menu(app, "Tools")
    click_entry(app, "Colors", settle=0.7)
    return click_entry(app, theme, settle=1.3)


def surfaces(app):
    """The three places only a palette can reach: the desktop, the menu bar,
    and a window's frame. No `Tui.ink` in this program touches any of them."""
    d = app.display()
    return {
        "desktop": (d.fg_at(75, 12), d.bg_at(75, 12)),
        "bar": (d.fg_at(3, 0), d.bg_at(3, 0)),
        "frame": (d.fg_at(7, 3), d.bg_at(7, 3)),
    }


# The chart's row labels, which are painted with `Theme.Inks.ruler`.
RULER = (11, 4)

# A bright hue is 90-97 as SGR; a dark one is 30-37. Asserting the *class*
# rather than the number is the point: which blue or which cyan is a design
# decision that will change, and "readable on this ground" is not.
def is_bright(fg):
    return isinstance(fg, int) and 90 <= fg <= 97


def is_dark(fg):
    return isinstance(fg, int) and 30 <= fg <= 37


def main():
    check = Checks()
    home = tempfile.mkdtemp(prefix="predc-home-")

    # 1. No config file at all is the first-run case, and it is not an error:
    #    Config.load funnels every failure into the defaults.
    app = start(home)
    check("with no config file it starts in Borland",
          not os.path.exists(config_file(home)), config_file(home))

    app.send(b"\x1ba", settle=1.4)
    borland = surfaces(app)
    borland_ruler = app.display().fg_at(*RULER)
    check("whose desktop is blue on light grey", borland["desktop"] == (34, 47),
          str(borland["desktop"]))
    check("and whose windows are white on blue", borland["frame"] == (97, 44),
          str(borland["frame"]))
    check("and whose chart ruler is a bright hue, as a blue ground needs",
          is_bright(borland_ruler), str(borland_ruler))

    # 2. The menu says which one is in use. Turbo Vision has no checkable menu
    #    item, so it is a character in the title.
    open_menu(app, "Tools")
    click_entry(app, "Colors", settle=0.7)
    box = app.render()
    check("the menu ticks the theme in use",
          any("√" in line and "Borland" in line for line in box.split("\n")),
          [line for line in box.split("\n") if "Borland" in line])
    check("and not the others",
          not any("√" in line and "Midnight" in line for line in box.split("\n")),
          [line for line in box.split("\n") if "Midnight" in line])
    app.send(b"\x1b", settle=0.5)
    app.send(b"\x1b", settle=0.5)

    # 3. Midnight. Every surface moves, and moves to a 24-bit colour -- which
    #    is the whole reason the theme is Rgb rather than Ansi: Black and
    #    DarkGray is the only dark pair the sixteen offer and it is at once too
    #    far apart to read as one surface and too close to be a border.
    check("Tools | Colors | Midnight is reachable", choose(app, "Midnight"))
    dark = surfaces(app)
    for what in ("desktop", "bar", "frame"):
        check(f"Midnight repaints the {what}, which no ink can reach",
              dark[what] != borland[what], f"{dark[what]} == {borland[what]}")
    check("and does it in 24-bit colour, not the nearest of sixteen",
          isinstance(dark["frame"][1], tuple), str(dark["frame"]))

    # 4. ...and it is remembered, on the change rather than at exit: predc is
    #    a program people close with Alt-X or from the window, and a setting
    #    that survives only a tidy exit is a setting that gets lost.
    check("choosing a theme writes the config file",
          os.path.exists(config_file(home)), config_file(home))
    with open(config_file(home), "rb") as f:
        saved = tomllib.load(f)
    check("and says which one", saved == {"theme": "midnight"}, str(saved))
    # The reason the file is TOML rather than JSON: a key predc wrote for the
    # first time arrives with a sentence saying what it is for. A config file
    # whose fields are undocumented is one nobody opens.
    text = open(config_file(home)).read()
    check("and explains the key it just invented",
          any(line.startswith("#") and "colour scheme" in line
              for line in text.split("\n")),
          text)

    # 5. Gren is the light one, and the reason Inks is a record per theme
    #    rather than one set shared by all three.
    check("Tools | Colors | Gren is reachable", choose(app, "Gren"))
    app.send(b"\x1ba", settle=1.0)
    gren = surfaces(app)
    gren_ruler = app.display().fg_at(*RULER)
    check("on a light ground the chart's ruler is a dark hue",
          is_dark(gren_ruler), str(gren_ruler))
    check("which is not the hue either of the other two used",
          gren_ruler != borland_ruler, f"{gren_ruler} == {borland_ruler}")
    check("and the window ground is light, which is what makes that necessary",
          isinstance(gren["frame"][1], tuple) and min(gren["frame"][1]) > 200,
          str(gren["frame"]))

    app.send(b"\x1bx", settle=1.0)
    check("exits cleanly", app.wait(timeout=6) == 0)

    # 6. The whole point of the file: the next run starts where the last one
    #    left off, and does it before the first frame rather than repainting
    #    into it -- which is why the load is three `Init.await`s and not a
    #    command issued after `startProgram`.
    with open(config_file(home), "rb") as f:
        check("the last choice was the one written down",
              tomllib.load(f) == {"theme": "gren"}, open(config_file(home)).read())

    app = start(home)
    app.send(b"\x1ba", settle=1.4)
    check("a second run starts in the theme the first one chose",
          surfaces(app) == gren, f"{surfaces(app)} != {gren}")
    check("inks and all", app.display().fg_at(*RULER) == gren_ruler,
          str(app.display().fg_at(*RULER)))
    app.send(b"\x1bx", settle=1.0)
    app.wait(timeout=6)

    # 6b. What TOML is for. The user opens the file, writes a note to himself,
    #     leaves a blank line, and sets something this version has never heard
    #     of -- and then predc writes the file twice more. Nothing here is
    #     serialised from the model: `Config.save` re-reads the file and
    #     changes the two values in the document it parsed, so everything the
    #     user wrote is still there, in the order and spacing he wrote it.
    #     The timezone list is the sharpest part of it. `Toml.Edit.set`
    #     replaces a value and the whitespace inside it, so writing that array
    #     back would put four hand-arranged lines onto one -- on a key nobody
    #     touched, because somebody picked a colour. `Config.apply` reads what
    #     the document already says and does not write what is not changing.
    hand_written = ('# The other half of the team is in Seoul.\n'
                    'theme = "gren" # light, for the afternoon\n'
                    '\n'
                    'timezones = [\n'
                    '  "Asia/Seoul",     # them\n'
                    '  "America/Chicago" # me\n'
                    ']\n'
                    '\n'
                    '# Not this version, but predc must not eat it.\n'
                    'language = "ko"\n')
    with open(config_file(home), "w") as f:
        f.write(hand_written)

    app = start(home)
    check("Tools | Colors | Midnight is reachable a second time",
          choose(app, "Midnight"))
    check("Tools | Colors | Borland is reachable", choose(app, "Borland"))
    app.send(b"\x1bx", settle=1.0)
    app.wait(timeout=6)

    text = open(config_file(home)).read()
    check("two more writes and the theme is the one last chosen",
          tomllib.loads(text)["theme"] == "borland", text)
    check("the comment above the key it rewrote is still there",
          "# The other half of the team is in Seoul." in text, text)
    check("so is the one on the line itself",
          "# light, for the afternoon" in text, text)
    check("and the key this version does not know survives untouched",
          tomllib.loads(text).get("language") == "ko", text)
    check("a list nobody changed is still on the four lines it was written on",
          '  "Asia/Seoul",     # them\n' in text, repr(text))
    check("the whole file, byte for byte, apart from the one word that moved",
          text == hand_written.replace('"gren"', '"borland"'), repr(text))

    # 6c. The other half of that bargain. A file somebody is halfway through
    #     editing has a typo in it, and the typo is worth less than the rest
    #     of the file is -- so predc reads the defaults and writes nothing at
    #     all, rather than replacing a page of somebody's TOML with two keys.
    broken = ('# Seoul is where the other half of the team is.\n'
              'theme = gren\n')
    with open(config_file(home), "w") as f:
        f.write(broken)
    app = start(home)
    check("a file with a syntax error starts in Borland",
          surfaces(app)["desktop"] == borland["desktop"],
          str(surfaces(app)["desktop"]))
    check("Tools | Colors | Midnight is reachable a third time",
          choose(app, "Midnight"))
    app.send(b"\x1bx", settle=1.0)
    app.wait(timeout=6)
    check("and predc leaves it exactly alone rather than overwriting it",
          open(config_file(home)).read() == broken,
          repr(open(config_file(home)).read()))

    # 6d. Midnight was called Dark, and a config file written before the
    #     rename says `theme = "dark"`. Reading it as Borland would have been
    #     the letter of "a name this version does not know", and would have
    #     taken somebody's colour scheme away for a word predc changed its own
    #     mind about. So the old name is read and never written: the file goes
    #     on saying `dark` until the next time the theme is picked.
    with open(config_file(home), "w") as f:
        f.write('theme = "dark"\n')
    app = start(home)
    check("the name Midnight used to have still opens Midnight",
          surfaces(app)["desktop"] == dark["desktop"],
          f'{surfaces(app)["desktop"]} != {dark["desktop"]}')
    check("and nothing rewrites the file for saying it",
          open(config_file(home)).read() == 'theme = "dark"\n',
          repr(open(config_file(home)).read()))
    check("until the theme is chosen again", choose(app, "Borland"))
    app.send(b"\x1bx", settle=1.0)
    app.wait(timeout=6)
    with open(config_file(home), "rb") as f:
        check("and then it is written under the new one",
              tomllib.load(f) == {"theme": "borland"},
              open(config_file(home)).read())

    # 7. And a file this version cannot make sense of is not worth a dialog in
    #    front of somebody who opened predc to look at a hex dump.
    with open(config_file(home), "w") as f:
        f.write('theme = "chartreuse"')
    app = start(home)
    check("a theme name this version does not know falls back to Borland",
          surfaces(app)["desktop"] == borland["desktop"],
          str(surfaces(app)["desktop"]))

    with open(config_file(home), "w") as f:
        f.write("not toml at all")
    app.send(b"\x1bx", settle=1.0)
    app.wait(timeout=6)
    app = start(home)
    check("and neither does a file that is not TOML",
          surfaces(app)["desktop"] == borland["desktop"],
          str(surfaces(app)["desktop"]))

    app.send(b"\x1bx", settle=1.0)
    check("and that exits cleanly too", app.wait(timeout=6) == 0)

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
