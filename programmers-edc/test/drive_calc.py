#!/usr/bin/env python3
"""predc's RPN calculator: exact integers, four bases, and two tools at once.

Three things are being tested and only the first is the calculator.

**The arithmetic is exact.** 2^64 - 1 is computed and printed in full. A Gren
`Int` cannot hold that number and cannot even divide one that size -- see
gren-lang/compiler#383 -- which is why the stack holds `BigInt` values from
`gilramir/gren-bigint`.

**A keypad and a keyboard share one window.** The display is a canvas with
focus, so every digit typed reaches the model rather than hunting for a button;
the buttons are `takesFocus = False`, which is what stops a click on `+` from
taking the caret and swallowing the next digit. `TCalculator` clears
`ofSelectable` on all twenty of its keys for this reason and never says so.

**Two tools are open at the same time.** That is the claim the whole app exists
to test -- a window is a value, so a program is a list of them -- and it is
checked here rather than asserted in a comment.

This suite also covers a bug in the binding that it found: three consecutive
printable characters are a *paste* as far as TVision is concerned, and it
blanks the key code of anything it decides that about, so the whole burst used
to arrive as "0x0000". Every line below that types more than two characters at
once would fail without that fix, which is most of them.
"""

import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

F6 = b"\x1b[17~"


def stack(app):
    """The five stack levels, deepest first, as {level: text}."""
    found = {}
    for line in app.render().split("\n"):
        m = re.search(r"\s([1-5]): (\S.*?)\s*║", line)
        if m:
            found[int(m.group(1))] = m.group(2).strip()
    return found


def top(app):
    return stack(app).get(1, "")


def mode(app):
    """The two modes, off the line that labels them.

    They used to be a bare `dec exact` at the end of the entry line, and the
    first person to see the calculator asked what the two words meant."""
    for line in app.render().split("\n"):
        m = re.search(r"base (\w+) +width (\S+)", line)
        if m:
            return (m.group(1), m.group(2))
    return None


def set_base(app, want):
    """Tab until the base is the one wanted. The base is model state and
    survives clearing the stack, so a test that assumed decimal after `z`
    would be reading hex."""
    for _ in range(5):
        if mode(app)[0] == want:
            return True
        app.send(b"\t", settle=0.5)
    return False


def press(app, label):
    """Click a keypad button by its caption. The window is already the active
    one everywhere this is used, so one click is enough -- on an inactive
    window the first click is spent raising it."""
    for row, line in enumerate(app.render().split("\n")):
        at = line.find(label)
        if at >= 0:
            app.click(at + 2, row + 1, settle=0.9)
            return True
    return False


def message(app):
    """The last line of the display: an error, or the standing hint that says
    how to change the two modes above it."""
    for row in app.render().split("\n"):
        if "║" in row and ("needs" in row or "divide" in row or "not a number" in row
                           or "changes base" in row):
            return row.split("║")[1].strip()
    return ""


def main():
    check = Checks()
    # A temporary HOME, so that this driver reads no config file but the one
    # it did not write. predc remembers its colour scheme in
    # `$HOME/.config/predc/`, and a suite that inherited the real one would
    # pass or fail depending on which theme the person running it happens to
    # like -- which is exactly what happened once, when a scratch script left a
    # `"gren"` behind and four colour checks in two suites started failing
    # against a program that was working perfectly.
    env = dict(os.environ, TERM="xterm-256color",
               HOME=tempfile.mkdtemp(prefix="predc-home-"))
    env.pop("XDG_CONFIG_HOME", None)
    app = Pty(node_argv(LAUNCHER), env, cwd=ROOT)

    app.pump(2.5)
    app.send(b"\x1br", settle=1.2)
    check("Alt-R opened the calculator", "RPN Calculator" in app.render(), app.render())
    check("and it brought its own menu with it", "Calc" in app.render().split("\n")[0],
          app.render().split("\n")[0])

    # The two modes are labelled, and the line under them says how to change
    # them -- standing, not shown once. The version of this that wiped the hint
    # on the first keystroke left two unexplained words on screen.
    check("the modes say what they are", mode(app) == ("dec", "exact"), str(mode(app)))
    check("and how to change them", "changes base" in message(app), message(app))

    # RPN: type, push, operate. Nothing here is a button.
    app.send(b"255\r16\r*", settle=1.0)
    check("the hint is still there after typing", "changes base" in message(app),
          message(app))
    check("255 16 * is 4080", top(app) == "4080", str(stack(app)))
    check("and the operands are gone", stack(app).get(2) is None, str(stack(app)))

    # The number an Int cannot hold, built by shifting.
    app.send(b"z1\r64\r<1\r-", settle=1.2)
    check("2^64 - 1 is exact", top(app) == "18446744073709551615", str(stack(app)))

    # Tab cycles the base, because in hex the letters a-f are digits and the
    # base cannot be chosen by its initial.
    app.send(b"\t", settle=0.8)
    check("Tab switches to hex", mode(app)[0] == "hex", str(mode(app)))
    check("and the same number is now all ones",
          top(app) == "0xffff_ffff_ffff_ffff", str(stack(app)))
    app.send(b"\t\t", settle=0.8)
    check("Tab keeps going: oct, then bin", mode(app)[0] == "bin", str(mode(app)))
    app.send(b"\t", settle=0.8)
    check("and back to decimal", mode(app)[0] == "dec", str(mode(app)))

    # The widths: a lens on an exact number, not a cast.
    app.send(b"w", settle=0.8)
    check("w switches to a u64 view", mode(app)[1] == "u64", str(mode(app)))
    check("where the value is unchanged", top(app) == "18446744073709551615",
          str(stack(app)))
    app.send(b"w", settle=0.8)
    check("and again to i64", mode(app)[1] == "i64", str(mode(app)))
    check("where the same bits are -1, and said not to fit",
          top(app).startswith("-1") and "ovf" in top(app), str(stack(app)))
    app.send(b"w", settle=0.8)
    check("u32 shows the low half...", mode(app)[1] == "u32" and top(app).startswith("4294967295"),
          f"{mode(app)} {stack(app)}")
    check("...and says the value did not fit", "ovf" in top(app), top(app))
    app.send(b"ww", settle=0.8)
    check("and round to exact again",
          mode(app)[1] == "exact" and top(app) == "18446744073709551615",
          f"{mode(app)} {stack(app)}")

    # Division promotes rather than truncating, which is the decision most
    # likely to be wrong in a hurry.
    app.send(b"z10\r2\r/", settle=1.0)
    check("10 2 / stays an integer", top(app) == "5", str(stack(app)))
    app.send(b"z7\r2\r/", settle=1.0)
    check("7 2 / is not 3", top(app) == "3.5", str(stack(app)))
    app.send(b"z1\r0\r/", settle=1.0)
    check("dividing by zero says so", "divide by zero" in message(app), message(app))
    check("and leaves the stack alone", stack(app).get(1) == "0", str(stack(app)))

    # Bitwise, on numbers wider than a machine word. In hex, `10` is sixteen --
    # which is the whole point of the base being a mode, and was worth one
    # wrong expectation here to be reminded of.
    app.send(b"z", settle=0.5)
    set_base(app, "hex")
    app.send(b"dead_beef\r10\r<", settle=1.2)
    check("hex is typed the way it is written",
          top(app) == "0xdead_beef_0000", str(stack(app)))
    app.send(b"ffff\r&", settle=1.0)
    check("and masked with an and", top(app) == "0x0", str(stack(app)))

    # Stack keys.
    app.send(b"z", settle=0.5)
    set_base(app, "dec")
    app.send(b"1\r2\r3\r", settle=1.0)
    check("three values on the stack", stack(app) == {1: "3", 2: "2", 3: "1"},
          str(stack(app)))
    app.send(b"s", settle=0.7)
    check("s swaps the top two", stack(app)[1] == "2" and stack(app)[2] == "3",
          str(stack(app)))
    app.send(b"p", settle=0.7)
    check("p drops", stack(app) == {1: "3", 2: "1"}, str(stack(app)))
    app.send(b"u", settle=0.7)
    check("u duplicates", stack(app) == {1: "3", 2: "3", 3: "1"}, str(stack(app)))

    # A button acts, and does not take the caret with it: the digit typed
    # straight afterwards still reaches the canvas. `takesFocus = False` is the
    # whole of that, and it is the trap TCalculator avoids by clearing
    # ofSelectable on all twenty of its keys without saying why.
    before = stack(app)
    check("the + button is there", press(app, " + "))
    check("and it added", top(app) == "6", f"{before} -> {stack(app)}")
    app.send(b"9", settle=0.7)
    check("and the keyboard still owns the caret",
          "> 9" in app.render(), app.render())
    app.send(b"\x1b", settle=0.5)

    # `Not` is the one button whose caption is a word rather than the symbol
    # it stands for -- `~` was rejected as a caption because at button size it
    # is a hair away from `-`, and complement-instead-of-subtract is a silent
    # wrong answer. Being the least obvious button, it is the one most worth a
    # check: it complements, so 6 becomes -7, which is what ~x means where no
    # width has been declared.
    check("the Not button is there", press(app, "Not"))
    check("and it complements: ~6 is -7", top(app) == "-7", str(stack(app)))
    check("and it is its own inverse", press(app, "Not") and top(app) == "6",
          str(stack(app)))

    # Two tools at once, which is the case the whole program exists for. They
    # overlap -- where a window starts is the model's only say -- so this
    # checks that each is driven independently rather than that both are
    # wholly visible.
    app.send(b"\x1ba", settle=1.2)
    check("the ASCII chart opens over the calculator", "ASCII Chart" in app.render(),
          app.render())
    app.send(b"\x1b[C" * 3, settle=0.8)
    check("and the keyboard now drives it", "Dec 3" in app.render(), app.render())

    # F6 is Turbo Vision's own: it raises the next window and the model is
    # never told. So this is two checks in one -- that the calculator is still
    # there, and that its state survived a window it knows nothing about being
    # opened, typed into and lifted off it.
    app.send(F6, settle=1.0)
    check("F6 brings the calculator back", "RPN Calculator" in app.render(),
          app.render())
    app.send(b"9", settle=0.7)
    check("with the keyboard", "> 9" in app.render(), app.render())
    check("and everything it had", top(app) == "6", str(stack(app)))

    # A keypad, a stack and two lines of text, all of them a fixed size, so the
    # window is `resize = Tui.fixedSize` and its frame says so: no zoom box, no
    # resize handle, and a Zoom entry that is greyed rather than merely inert.
    frame = [row for row in app.render().split("\n") if "RPN Calculator" in row][0]
    check("a fixed-size window has no zoom box on its frame",
          "[↑]" not in frame and "[↕]" not in frame, frame)

    before = app.render()
    app.send(b"\x1b[15;5~", settle=0.6)
    for _ in range(3):
        app.send(b"\x1b[1;2B", settle=0.3)
        app.send(b"\x1b[1;2C", settle=0.3)
    app.send(b"\r", settle=0.9)
    check("and Ctrl-F5 plus shifted arrows changes nothing",
          app.render() == before, app.render())

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("Alt-X exits with two tools open", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
