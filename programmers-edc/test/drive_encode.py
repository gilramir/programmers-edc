#!/usr/bin/env python3
"""predc's encode/decode: four transforms, both ways, nothing guessed.

Base64, percent-encoding, C string escapes and HTML entities. The checks below
are the eight combinations plus the refusals, and two of them are about the
shape of the tool rather than the arithmetic.

**Nothing is sniffed.** `SGVsbG8=` is valid base64 and also a plausible word;
`%41` is percent-encoding and also three characters; `\\n` is one character or
two. Which transform and which direction are both chosen, which is the hex
viewer's `p`/`P` rule applied to eight cases instead of two, and the driver
switches them through the menu rather than assuming a default.

**A control character cannot be compared against the screen.** A canvas has no
tab stops and Turbo Vision paints control characters as CP437 glyphs, so `\t`
decoded comes out as `○` -- correctly one character, and not one a test can
match against `"\t"`. The count line under the answer is what those checks read
instead.

**A Tab cannot be typed into an input line** -- it moves the focus, which is
what an input line is for -- so the C-string *encode* direction cannot be
driven by typing a control character, and neither can a newline. That is a real
limitation of the tool and not of the test: escaping is reached by pasting, and
unescaping by typing, which is the direction anybody actually wants at a
keyboard. The check below tests it the way it can be used.
"""

import base64
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv


def menu(app, name):
    bar = app.render().split("\n")[0]
    app.click(bar.index(name) + 1, 1, settle=0.6)


def entry(app, text, settle=0.8):
    for row, line in enumerate(app.render().split("\n")):
        if text in line and "│" in line:
            app.click(line.index(text) + 1, row + 1, settle=settle)
            return True
    return False


def out(app):
    """The first canvas row -- the answer, or the sentence saying why not."""
    rows = [l.split("║")[1] for l in app.render().split("\n") if l.count("║") >= 2]
    body = [r.strip() for r in rows
            if r.strip() and "( )" not in r and "(•)" not in r]
    return body[0] if body else ""


def radios(app):
    """Which of each cluster is picked, as the two marked labels."""
    picked = []
    for line in app.render().split("\n"):
        if "(•)" in line:
            for part in line.split("(•)")[1:]:
                picked.append(part.split("(")[0].strip())
    return picked


def go(app, kind, way, text):
    menu(app, "Transform")
    entry(app, kind)
    menu(app, "Transform")
    entry(app, way)
    app.send(b"\x1bi", settle=0.5)              # Alt-I reaches the Input field
    app.send(b"\x1b[3~" * 60, wait=0.3)
    app.send(text.encode(), settle=0.9)
    return out(app)


def main():
    check = Checks()
    env = dict(os.environ, TERM="xterm-256color",
               HOME=tempfile.mkdtemp(prefix="predc-home-"))
    env.pop("XDG_CONFIG_HOME", None)
    app = Pty(node_argv(LAUNCHER), env, cwd=tempfile.mkdtemp())
    app.pump(2.0)

    app.send(b"\x1bj", settle=1.5)
    check("Alt-J opens it", "Encode / decode" in app.render(), app.render())
    check("with all four transforms drawn, not two",
          all(k in app.render() for k in ("Base64", "URL", "C string", "HTML")),
          [l for l in app.render().split("\n") if "Base64" in l])
    check("and it says what to do before anything is typed",
          "Type or paste" in out(app), out(app))

    # 1. Base64, both ways, against Python's own answer.
    plain = "Hello, hex!"
    check("base64 encodes what Python encodes",
          go(app, "Base64", "Encode", plain)
          == base64.b64encode(plain.encode()).decode(),
          out(app))
    check("and decodes it back",
          go(app, "Base64", "Decode", base64.b64encode(plain.encode()).decode())
          == plain, out(app))

    # Padding is the half of base64 that gets written wrong: three bytes need
    # none, two need one `=`, one needs two.
    for text in ("abc", "ab", "a"):
        want = base64.b64encode(text.encode()).decode()
        check(f"base64 pads {len(text)} byte(s) the way base64 does: {want}",
              go(app, "Base64", "Encode", text) == want, out(app))

    # 2. Percent-encoding, and the reserved set it is fussy about.
    check("percent-encoding escapes everything outside the unreserved set",
          go(app, "URL / percent", "Encode", "a b&c=d/e") == "a%20b%26c%3Dd%2Fe",
          out(app))
    check("and leaves the unreserved set alone",
          go(app, "URL / percent", "Encode", "aZ0-._~") == "aZ0-._~", out(app))
    check("and decodes back", go(app, "URL / percent", "Decode", "a%20b%26c") == "a b&c",
          out(app))

    # 3. C strings. Typing reaches the decode direction; a Tab cannot be typed.
    # Not compared against a literal tab: a canvas cannot draw one, and
    # Turbo Vision paints control characters as CP437 glyphs -- `a\tb` decodes
    # to three characters and comes out as `a○b`. The count line is what says
    # the decode happened, and it is the assertion that does not depend on how
    # an unprintable character is drawn.
    go(app, "C string", "Decode", "a\\tb")
    check("a C escape becomes one character, not two",
          "3 characters out" in app.render()
          and "a\\tb" not in out(app), out(app))
    check("and \\x41 is A", go(app, "C string", "Decode", "\\x41") == "A", out(app))
    check("while a quote and a backslash survive the round trip out",
          go(app, "C string", "Encode", 'say "hi"') == 'say \\"hi\\"', out(app))

    # 4. HTML, named and numeric.
    check("HTML escapes the five that matter",
          go(app, "HTML entities", "Encode", "<a href='x'>&")
          == "&lt;a href=&#39;x&#39;&gt;&amp;", out(app))
    check("and reads named and numeric entities back",
          go(app, "HTML entities", "Decode", "&lt;a&gt;&amp;&#65;") == "<a>&A",
          out(app))

    # 5. The refusals, which say which character stopped them.
    check("base64 that is not base64 says which character",
          "Not base64: !" in go(app, "Base64", "Decode", "not!base64"), out(app))
    check("a percent with nothing after it says so",
          "percent-encoded" in go(app, "URL / percent", "Decode", "a%"), out(app))
    check("an escape that is not one says which",
          "Not an escape: \\q" in go(app, "C string", "Decode", "\\q"), out(app))
    check("an entity that is not one says which",
          "Not an entity: &nope;" in go(app, "HTML entities", "Decode", "&nope;"),
          out(app))

    # 6. The clusters are the state, so the menu and the radios agree.
    menu(app, "Transform")
    entry(app, "~U~RL" if entry(app, "URL / percent") is None else "URL / percent")
    check("choosing from the menu moves the radio",
          "URL" in radios(app), str(radios(app)))

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("Alt-X exits", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
