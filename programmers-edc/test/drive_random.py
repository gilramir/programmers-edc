#!/usr/bin/env python3
"""predc's random values: v4 UUIDs, and random bytes as hex, base64 or a number.

This is the one tool whose window is not a function of its model, and most of
what is checked here is that claim held in both directions.

**It has to change when nothing did.** Press *Again* with every control
untouched and the values must all be different, which is the opposite of what
every other driver in this directory asserts. The bytes come from
`Crypto.getRandomUInt8Values` -- `crypto.getRandomValues`, the platform's
CSPRNG -- through a `Task`, so they are stored in the model rather than worked
out from it, and that storing is the whole design.

**It must not change when only the spelling did.** Switching between UUID, Hex,
Base64 and Integer re-spells the draw that is already there; it does not ask for
new bytes. The check for that is exact rather than incidental: the hex of a row,
with the two nibbles a v4 UUID is required to fix put back, is the UUID
character for character. If switching rolled again the two would agree only by
accident, and never twice.

Which is also the demonstration the tool exists to make. A v4 UUID is not
sixteen random bytes. It is sixteen random bytes with six of their bits spent
saying which kind of UUID it is, and this is the one place a person can watch
those six bits get spent.
"""

import base64
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

# What the summary line says, per kind, so that `parts` can tell it from a
# value. One phrase per branch of `Tool.Random.summary`, and adding a kind
# without adding its phrase here makes the footer read as a fourth value --
# which is what happened when Integer was added, and is why this is a list with
# a name rather than an `or` buried in the loop.
FOOTER = ("version 4", "random bytes", "unsigned integers")


def inside(app):
    """Every row between the window's two side walls."""
    return [line.split("║")[1].rstrip()
            for line in app.render().split("\n") if line.count("║") >= 2]


def parts(app):
    """(values, footer, message).

    The canvas starts at the fifth row inside the frame -- three for the radio
    cluster and a blank -- and the footer is the row that names what the values
    are. Anything after the footer is the message line. Found by what the rows
    say rather than by counting them, because the count of values is the thing
    half these checks are about.
    """
    values, footer, message = [], "", ""
    for row in inside(app)[4:]:
        text = row.strip()
        if not text:
            continue
        if any(phrase in text for phrase in FOOTER):
            footer = text
        elif footer:
            message = text
        else:
            values.append(text)
    return values, footer, message


def stamped(hexed):
    """The same bytes, with the six bits a v4 UUID is not allowed to choose.

    RFC 9562: the high nibble of byte 6 is the version and the top two bits of
    byte 8 are the variant. Everything else is the draw untouched.
    """
    raw = bytearray.fromhex(hexed)
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return raw.hex()


def put(app, label, text, settle=1.6):
    """Put `text` in the number field that follows `label`.

    Clicked rather than tabbed to, and cleared by hand: a click moves the caret
    to where it was clicked and leaves no selection, so the field has to be
    emptied a character at a time. The other way in -- `Alt` and the label's
    underlined letter -- is what selects the whole value, and these two labels
    do not have one to underline. Every `Alt` letter in predc is spoken for;
    `Tool.Random` says which four were left and where they went.
    """
    line = app.render().split("\n")[3]
    start = line.index(label) + len(label) + 1
    app.click(start + 4, 4, settle=0.7)
    app.send(b"\x08" * 4, settle=0.7)
    app.send(text.encode(), settle=settle)


def menu(app, name):
    bar = app.render().split("\n")[0]
    app.click(bar.index(name) + 1, 1, settle=0.6)


def entry(app, text, settle=1.2):
    for row, line in enumerate(app.render().split("\n")):
        if text in line and "│" in line:
            app.click(line.index(text) + 1, row + 1, settle=settle)
            return True
    return False


def main():
    check = Checks()
    env = dict(os.environ, TERM="xterm-256color",
               HOME=tempfile.mkdtemp(prefix="predc-home-"))
    env.pop("XDG_CONFIG_HOME", None)
    # Started from the command line, which is also the check that `predc
    # random` is a real subcommand and that its `init` task ran before the
    # first frame rather than after it.
    app = Pty(node_argv(LAUNCHER, "random"), env, cwd=ROOT)
    app.pump(2.5)

    values, footer, message = parts(app)
    check("predc random opens with values already made, and no key pressed",
          len(values) == 5, values)
    check("all five are v4 UUIDs by shape",
          all(UUID4.match(v) for v in values), values)
    check("and they are five different ones", len(set(values)) == 5, values)
    check("the footer says what they are", "5 UUIDs, version 4" in footer, footer)
    check("and nothing went wrong", message == "", message)

    # The one assertion no other driver in this directory makes.
    was = values
    app.send(b"\r", settle=1.4)
    values, footer, _ = parts(app)
    check("Enter presses Again, because Again is the default button",
          len(values) == 5, values)
    check("and it is a new draw with nothing changed -- which is the point",
          not (set(values) & set(was)), (was, values))

    # The count field holds the caret when the window opens, and a field
    # selects its whole value when it *gains* the caret -- so this replaces the
    # 5 rather than making it 35.
    app.send(b"3", settle=1.4)
    values, footer, _ = parts(app)
    check("the count field has the caret at open, so a digit replaces its value",
          len(values) == 3, values)
    check("and the footer counts what is there", "3 UUIDs" in footer, footer)

    # A disabled view is skipped by Tab, so one Tab out of the count field
    # lands on the cluster rather than on the width field -- which is what
    # `Enabled False` is claiming when the kind is UUID.
    app.send(b"\t", settle=0.7)
    app.send(b"\x1b[B", settle=1.4)
    uuids = values
    values, footer, _ = parts(app)
    check("Tab skips the width field while UUID is picked, so Down reaches Hex",
          "(•) Hex" in "\n".join(inside(app)), inside(app)[:3])
    check("and the hex is the same three values, not three new ones",
          len(values) == 3 and all(re.match(r"^[0-9a-f]{32}$", v) for v in values),
          values)
    check("byte for byte the same draw: the hex, stamped with the six bits a "
          "v4 UUID fixes, is the UUID",
          [stamped(v) for v in values] == [u.replace("-", "") for u in uuids],
          (uuids, values))
    check("and the footer changed with it", "3 x 16 random bytes" in footer, footer)

    # And once more, to base64. Still the same bytes.
    hexed = values
    menu(app, "Generate")
    entry(app, "Base64")
    values, footer, _ = parts(app)
    check("base64 is the third spelling of that same draw",
          [base64.b64decode(v).hex() for v in values] == hexed, (hexed, values))

    # And the fourth: the same bytes as one unsigned big-endian number.
    #
    # Sixteen bytes is a thirty-nine-digit value, which is past a double by
    # eighty-six bits and past a Gren `Int` by more -- so this is `BigInt`
    # underneath, and `int(v)` on this side is what says the digits are all
    # there rather than the first seventeen and a rounding.
    menu(app, "Generate")
    entry(app, "Integer")
    values, footer, _ = parts(app)
    check("the integers are decimal and nothing else",
          len(values) == 3 and all(re.match(r"^[0-9]+$", v) for v in values),
          values)
    check("and each one is that same draw read as one big-endian number",
          [int(v) for v in values] == [int(h, 16) for h in hexed], (hexed, values))
    check("exactly, at sixteen bytes, which no Int in Gren can hold",
          all(int(v) >= 2 ** 53 for v in values) and max(len(v) for v in values) > 30,
          values)
    check("and the footer says what decides the range",
          "3 unsigned integers, 16 bytes wide" in footer, footer)

    # The width, reached the long way round the Tab ring -- count, width,
    # cluster, Again, Copy -- which is four Tabs from the cluster and arrives
    # with the whole value selected.
    menu(app, "Generate")
    entry(app, "Hex")
    put(app, "Bytes each", "8")
    values, footer, _ = parts(app)
    check("the width field is reachable once the kind is not UUID",
          all(len(v) == 16 for v in values), values)
    check("and the footer says how wide", "3 x 8 random bytes" in footer, footer)

    # More than fits. The canvas is eight rows and holds seven values and a
    # footer, so asking for forty is the ordinary case rather than an edge one
    # -- and the thing under test is that it *says* so, which is what every
    # other fixed space in this program does not.
    put(app, "How many", "40")
    values, footer, message = parts(app)
    check("more values than rows: the ones that fit are drawn",
          len(values) == 7, values)
    check("and the footer counts the ones that are not",
          "40 x 8 random bytes" in footer and "33 more below" in footer, footer)
    check("the footer fits the canvas, which is the bug it is about",
          len(footer) <= 76, f"{len(footer)}: {footer}")

    # Past the cap: clamped and told, rather than either alone.
    put(app, "How many", "999")
    values, footer, message = parts(app)
    check("999 is clamped to what the tool will make",
          "64 x 8 random bytes" in footer, footer)
    check("and the complaint says so out loud", "64 at a time is the most." in message,
          message)

    # Copy. The clipboard cannot be read back here, so what is checked is that
    # the tool asked and heard an answer -- the same shape the calculator's
    # driver settles for, and for the same reason.
    menu(app, "Generate")
    entry(app, "Copy them all")
    _, _, message = parts(app)
    check("Copy puts them on the clipboard and says which answer it got",
          message.startswith("Copied"), message)

    # The menu's Again is the button's Again.
    values, _, _ = parts(app)
    menu(app, "Generate")
    entry(app, "Again")
    fresh, _, _ = parts(app)
    check("the menu rolls too, and rolls something else",
          len(fresh) == len(values) and not (set(fresh) & set(values)),
          (values, fresh))

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("Alt-X exits, and cleanly", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
