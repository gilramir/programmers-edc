#!/usr/bin/env python3
"""predc's hex viewer: finding bytes in a file it never loads.

The viewer holds one 16 KB chunk around the cursor and reads the rest through
`Between {start, end}`, so a search is not "scan what is in memory" -- it walks
the file a window at a time, and the two things worth testing are both about
that walk.

**A needle straddling a window boundary is in neither window.** Each window
therefore begins one byte less than the needle before the last one ended, and
the fixture plants `EDGE` at 16382 in a file whose chunk is 16384 -- two bytes
either side of the seam. Without the overlap it is simply never found, and no
smaller file would say so.

**The end of the file is what stops the walk, not the arithmetic.** The first
version stepped to `end - (len - 1)`, which on a last window shorter than that
overlap lands on the start it has just read -- and reads the same three bytes
for ever, saying "Searching..." while it does. `NOPE` on a 40,960-byte file
with 16 KB windows is exactly that case, and the check is that a search which
fails says so rather than never returning.

Text and hex are two commands, as `p` and `P` are: `beef` is four characters
and two bytes and only the reader knows which was meant.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

SIZE = 40960
CHUNK = 16384


def where(app):
    """The offset line, which is what a search moves."""
    for line in app.render().split("\n"):
        if "Offset" in line and "║" in line:
            return line.split("║")[1].strip()
    return ""


def offset(app):
    text = where(app)
    if "(" in text:
        return int(text.split("(")[1].split(")")[0])
    return -1


def message(app):
    for line in app.render().split("\n"):
        if line.count("║") >= 2:
            said = line.split("║")[1].strip()
            if said.startswith(("Not found", "Searching", "Nothing")):
                return said
    return ""


def find(app, text, as_hex=False, settle=2.5):
    app.send(b"/", settle=1.0)
    app.send(text.encode(), settle=0.4)
    if as_hex:
        app.send(b"\t", settle=0.3)
        app.send(b"\x1b[C", settle=0.3)
    app.send(b"\r", settle=settle)


def main():
    check = Checks()
    work = tempfile.mkdtemp(prefix="predc-find-")

    # `i % 256` again, so every byte is arithmetic, with three needles planted:
    # one inside the first chunk, one *across* the chunk seam, and one well
    # past anything the viewer will have loaded.
    data = bytearray(i % 256 for i in range(SIZE))
    data[100:104] = b"HERE"
    data[CHUNK - 2:CHUNK + 2] = b"EDGE"
    data[30000:30004] = b"FARR"
    with open(os.path.join(work, "big.bin"), "wb") as f:
        f.write(bytes(data))

    env = dict(os.environ, TERM="xterm-256color",
               HOME=tempfile.mkdtemp(prefix="predc-home-"))
    env.pop("XDG_CONFIG_HOME", None)
    app = Pty(node_argv(LAUNCHER) + ["hex", "big.bin"], env, cwd=work)
    app.pump(2.5)
    check("the viewer opened on the file", offset(app) == 0, where(app))

    find(app, "HERE")
    check("a needle inside the first chunk is found", offset(app) == 100, where(app))

    # The one the overlap exists for.
    find(app, "EDGE")
    check("and one lying across the chunk boundary, which is the whole test",
          offset(app) == CHUNK - 2, where(app))

    find(app, "FARR")
    check("and one past anything that was ever loaded",
          offset(app) == 30000, where(app))

    # The one the stop condition exists for: this used to loop for ever.
    find(app, "NOPE", settle=4.0)
    check("a needle that is not there says so, rather than searching for ever",
          "Not found" in message(app), message(app) or where(app))

    # Hex is the other reading, and the same bytes.
    app.send(b"\x1b[1;5H", settle=0.8)          # Ctrl-Home
    find(app, "48 45 52 45", as_hex=True)
    check("the same bytes as hex digits find the same place",
          offset(app) == 100, where(app))

    # `n` repeats, and repeats from *after* the cursor rather than on it.
    app.send(b"\x1b[1;5H", settle=0.8)
    find(app, "\\x00")                            # not there as text
    app.send(b"\x1b[1;5H", settle=0.8)
    find(app, "EDGE")
    check("and n needs something to repeat", offset(app) == CHUNK - 2, where(app))
    app.send(b"n", settle=3.0)
    check("n from the last hit finds no second one, and says so",
          "Not found" in message(app), message(app) or where(app))

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=8)
    check("Alt-X exits", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
