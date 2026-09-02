#!/usr/bin/env python3
"""predc's command line: the tool you came for, open when the screen arrives.

Every other driver here starts the program and then works the menus. This one
never gets that far in three of its cases, which is the point of it: a
`--help` has to print into a pipe or a pager and leave the terminal exactly as
it found it, and the only thing that can promise that is a program that decides
before it paints. `Tui.defineProgramOrExit` is the promise and this file is
what holds it to it -- `\\x1b[?1049h` is the alternate screen, and TVision
writes it the moment it starts.

The rest is the ordinary claim: `predc hex sample.bin` is the dump you would
have reached through the file dialog, and `predc` on its own is still the empty
desktop it always was.
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

# What Turbo Vision writes on its way in. Any of them in the byte stream means
# the program took the terminal, which is the thing a `--help` must not do.
PAINTED = (b"\x1b[?1049h", b"\x1b[?1000h", b"\x1b[2J")


def scratch():
    """A HOME of its own, so no driver reads the colour scheme another wrote.
    (`drive_shell.py` explains what that cost the first time.)"""
    env = dict(os.environ, TERM="xterm-256color",
               HOME=tempfile.mkdtemp(prefix="predc-home-"))
    env.pop("XDG_CONFIG_HOME", None)
    return env


def start(env, cwd, *args, settle=2.5):
    app = Pty(node_argv(LAUNCHER, *args), env, cwd=cwd)
    app.pump(settle)
    return app


def leave(check, app, name):
    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check(f"{name} exits cleanly", code == 0, f"exit={code}")


def painted(app):
    return [seq for seq in PAINTED if seq in app.buf]


def main():
    check = Checks()
    env = scratch()
    work = tempfile.mkdtemp(prefix="predc-cli-")
    with open(os.path.join(work, "sample.bin"), "wb") as f:
        f.write(bytes(i % 256 for i in range(512)))

    # 1. No arguments is what it always was. An empty argument list means the
    #    help text to `Argparse.Parser.run`, and `predc` on its own does not
    #    mean that -- so Main checks for it before the parser sees it, and this
    #    is the check that says so.
    app = start(env, work)
    screen = app.render()
    check("bare predc still opens the desktop",
          "File" in screen.split("\n")[0], screen.split("\n")[0])
    check("and nothing is open on it",
          not any("─" in row or "═" in row for row in screen.split("\n")[1:24]),
          "\n".join(screen.split("\n")[1:6]))
    leave(check, app, "predc")

    # 2. One command per tool, and the window is there in the first frame --
    #    no menu was walked to get it.
    app = start(env, work, "ascii")
    check("predc ascii opens the chart", "ASCII" in app.render(), app.render())
    leave(check, app, "predc ascii")

    app = start(env, work, "calc")
    screen = app.render()
    check("predc calc opens the calculator", "RPN" in screen, screen)
    check("and its own menu came with it", "Calc" in screen.split("\n")[0],
          screen.split("\n")[0])
    leave(check, app, "predc calc")

    app = start(env, work, "hex")
    screen = app.render()
    check("predc hex opens the viewer", "Hex Dump" in screen, screen)
    check("with nothing in it, like the menu's", "Nothing open" in screen, screen)
    leave(check, app, "predc hex")

    # 3. The one that is worth having: a file on the command line is the file
    #    dialog you did not have to walk.
    app = start(env, work, "hex", "sample.bin")
    screen = app.render()
    check("predc hex FILE names the file in the title",
          "sample.bin" in screen.split("\n")[1] and "512" in screen.split("\n")[1],
          screen.split("\n")[1])
    check("and the dump is of that file",
          any(row.lstrip("║░ ").startswith("00000000  00 01 02 03") for row in screen.split("\n")),
          screen)
    leave(check, app, "predc hex FILE")

    # 4. A name that is not a file is a complaint on the viewer's own message
    #    line, not a program that refuses to start. The dump is where the
    #    person is looking.
    app = start(env, work, "hex", "nosuch.bin")
    screen = app.render()
    check("a missing file still opens the viewer", "Hex Dump" in screen, screen)
    check("and the reason is on its message line",
          "ENOENT" in screen or "no such" in screen.lower(), screen)
    leave(check, app, "predc hex MISSING")

    # 4b. And a directory is not a mistake either: `statFile` answers with
    #     what the name is, and a directory has always meant "list it". So
    #     `predc hex ~/dumps` is the file dialog already standing in the right
    #     place, which nobody designed and everybody would want.
    app = start(env, work, "hex", ".")
    screen = app.render()
    check("a directory opens the file dialog there",
          "Open file" in screen and "sample.bin" in screen, screen)
    app.send(b"\x1b", settle=0.6)
    leave(check, app, "predc hex DIR")

    # 5. --help prints and leaves, and the terminal never hears from Turbo
    #    Vision at all. Under a pty, which is the case where it would.
    app = Pty(node_argv(LAUNCHER, "--help"), env, cwd=work)
    code = app.wait(timeout=8)
    check("--help exits 0", code == 0, f"exit={code}")
    check("--help prints the intro and the commands",
          "every-day carry" in app.render() and "predc hex" in app.render(),
          app.render()[:200])
    check("--help never started Turbo Vision", painted(app) == [], repr(painted(app)))
    check("and it is coloured, because a terminal is watching",
          b"\x1b[36m" in app.buf or b"\x1b[96m" in app.buf, repr(app.buf[:80]))

    app = Pty(node_argv(LAUNCHER, "--version"), env, cwd=work)
    code = app.wait(timeout=8)
    check("--version is the version and nothing else",
          code == 0 and app.render().strip() == "0.1.0", app.render().strip())

    # NO_COLOR is the rule argparse's own runner follows, and predc has to
    # follow it by hand: it cannot use that runner, because that runner ends
    # in a process that exits and predc's ends in one that paints.
    app = Pty(node_argv(LAUNCHER, "--help"), dict(env, NO_COLOR="1"), cwd=work)
    app.wait(timeout=8)
    check("NO_COLOR takes the colour out", b"\x1b[36m" not in app.buf,
          repr(app.buf[:80]))

    # 6. A word that is not a command: stderr, exit 1, and still no screen.
    app = Pty(node_argv(LAUNCHER, "frobnicate"), env, cwd=work)
    code = app.wait(timeout=8)
    check("an unknown command exits 1", code == 1, f"exit={code}")
    check("and says what to try instead", "predc --help" in app.render(), app.render())
    check("and never started Turbo Vision either", painted(app) == [], repr(painted(app)))

    # A pty cannot tell stdout from stderr -- they are the same file. The one
    # thing that can is a pipe, which is also the case where the width is 80
    # because nothing is there to ask.
    done = subprocess.run(node_argv(LAUNCHER, "frobnicate"),
                          env=env, cwd=work, capture_output=True, timeout=20)
    check("the complaint goes to stderr, not stdout",
          done.stdout == b"" and b"frobnicate" in done.stderr,
          f"out={done.stdout[:40]!r} err={done.stderr[:40]!r}")
    done = subprocess.run(node_argv(LAUNCHER, "--help"),
                          env=env, cwd=work, capture_output=True, timeout=20)
    check("and the help goes to stdout", b"every-day carry" in done.stdout,
          done.stdout[:60])
    check("with no colour in it, because a pipe is not watching",
          b"\x1b[" not in done.stdout, repr(done.stdout[:80]))
    check("and wrapped to eighty, which is what a pipe is worth",
          max(len(line) for line in done.stdout.decode().split("\n")) <= 80,
          max(done.stdout.decode().split("\n"), key=len))

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
