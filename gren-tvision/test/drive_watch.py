#!/usr/bin/env python3
"""examples/watch -- the one example that is not a port.

What it is really testing is that the outside world can reach a Turbo Vision
program. `TProgram::getEvent` reads a keyboard and a mouse and nothing else, so
no C++ example here could react to anything but a keystroke;
`FileSystem.watchRecursive` is an ordinary `Sub`, and the proof is that
*writing a file from this test* makes the application do something.

The other three claims:

  - several children run at once and finish out of order. Asserted on the order
    the output was appended in rather than on a snapshot taken mid-flight,
    which is a race -- the pane is append-only, so the order the lines are in
    is the order the children produced them, and no sleep has to be timed;
  - a burst of writes causes exactly one run, because of the debounce;
  - a running child can be killed, and says so.

Nothing here spawns anything but shell built-ins. Under `test:asan` the
sanitizer is preloaded through `LD_PRELOAD` and a child inherits it, so a real
program would run instrumented and write its reports into our build directory.

That inheritance has one sharp edge, and it is why this test passes
`--shell=bash`. Node's `shell: true` runs `/bin/sh` by name, and `/bin/sh` on
this machine is the distribution's, linked against the distribution's glibc --
while the preloaded `libasan.so` comes out of the nix store and drags nix's
glibc in behind it. The system binary cannot satisfy that, so under ASAN
*every* child dies before `main` with `version GLIBC_ABI_DT_X86_64_PLT not
found`. A shell taken off `PATH` is the toolchain's own and has no such
problem. Nothing about this reaches a user: it takes an `LD_PRELOAD` from one
libc and a program from another, which only a sanitizer run inside a devbox
shell arranges.
"""

import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLE = os.path.join(ROOT, "examples", "watch")
RUNTIME = os.path.join(ROOT, "..", "gren-tvision-runtime", "bin", "gren-tui.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv, asan_enabled

# Three jobs share the desktop, so each window is seven rows tall and its pane
# is five. Window n's title is on screen row 1 + 7n.
SLOT = 7


# A window's title row carries a close box too when the window is the active
# one, so the state is picked out by name rather than by being the first thing
# in brackets.
TITLE = re.compile(r"\[(?:ok|idle|running|waiting|cancelled|exit -?\d+)\][^\u2500\u2550]*")


def titles(app):
    """The three window titles, which is where each job's state is."""
    rows = app.render().splitlines()
    out = []
    for slot in range(3):
        row = rows[1 + slot * SLOT] if 1 + slot * SLOT < len(rows) else ""
        m = TITLE.search(row)
        out.append(m.group(0).strip() if m else "")
    return out


def pane(app, slot):
    """A job's five rows of output. Column 76 is its scroll bar."""
    rows = app.render().splitlines()
    body = []
    for i in range(2 + slot * SLOT, 2 + slot * SLOT + 5):
        if i < len(rows):
            body.append(rows[i][1:76].strip())
    return [line for line in body if line]


def counters(app):
    m = re.search(r"(\d+) changes\s+(\d+) runs", app.render())
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def main():
    check = Checks(
        replays=(
            "the commands it spawns and the directory it watches are Tasks "
            "rather than messages: a child process's output crosses no port, "
            "so it is on no tape"
        )
    )
    watched = tempfile.mkdtemp(prefix="tvwatch-")
    try:
        with open(os.path.join(watched, "seed.txt"), "w") as f:
            f.write("seed\n")

        env = dict(os.environ, TERM="xterm-256color")
        shell = ["--shell=bash"] if asan_enabled() else []
        app = Pty(
            node_argv(
                RUNTIME, "main.js", watched, *shell,
                "echo alpha",
                "sleep 0.5; echo beta; exit 3",
                "sleep 30",
            ),
            env,
            cwd=EXAMPLE,
        )

        app.pump(2.5)
        check("one window per command, titled with the command",
              [t.split("] ", 1)[-1] for t in titles(app)]
              == ["echo alpha", "sleep 0.5; echo beta; exit 3", "sleep 30"],
              str(titles(app)))
        check("nothing has run yet",
              all(t.startswith("[idle]") for t in titles(app)), str(titles(app)))

        # ---- a write on disk reaches the program -------------------------
        #
        # This is the whole example in one assertion: the test, not the user,
        # makes something happen.
        before = counters(app)
        with open(os.path.join(watched, "touched.txt"), "w") as f:
            f.write("hello\n")
        app.pump(1.2)
        after = counters(app)
        check("writing a file made the program run its commands",
              after[1] == before[1] + 1 and after[0] > before[0],
              f"{before} -> {after}")

        # The fast one is done; the slow ones are not. That is not a race:
        # 0.5s and 30s against the 1.2s we have already waited.
        state = titles(app)
        check("the fast command has finished", state[0].startswith("[ok]"), str(state))
        check("its output was captured", pane(app, 0) == ["alpha"], str(pane(app, 0)))
        check("the interface answered while a child was running",
              state[2].startswith("[running]") and "Alt-C Cancel" in app.render(),
              str(state))

        app.pump(1.2)
        state = titles(app)
        check("a non-zero exit is reported as one",
              state[1].startswith("[exit 3]"), str(state))
        check("the slow command's output arrived", pane(app, 1) == ["beta"],
              str(pane(app, 1)))

        # Colour is the only thing that says which of several windows went
        # wrong, and everything this binding makes is a TDialog underneath, so
        # the window is grey and the eight bright hues are the wrong half:
        # LightGreen on grey is barely there and LightGray is invisible.
        # 32 and 31 are the dark green and dark red that are readable on it.
        screen = app.display()
        check("a job's output is painted in the dark half of the palette",
              (screen.fg_at(1, 2), screen.fg_at(1, 2 + SLOT)) == (32, 31),
              f"{screen.fg_at(1, 2)} then {screen.fg_at(1, 2 + SLOT)}")
        # Two children finished while a third is still going. Run sequentially
        # that is impossible, and the margin is the third one's thirty seconds
        # rather than a gap someone has to time.
        check("the commands ran concurrently",
              state[0].startswith("[ok]")
              and state[1].startswith("[exit 3]")
              and state[2].startswith("[running]"),
              str(state))

        # ---- a burst of writes is one run --------------------------------
        before = counters(app)
        for i in range(5):
            with open(os.path.join(watched, f"burst{i}.txt"), "w") as f:
                f.write("x\n")
        app.pump(1.5)
        after = counters(app)
        check("five writes in a burst caused exactly one run",
              after[1] == before[1] + 1, f"{before} -> {after}")
        check("but every one of them was seen",
              after[0] >= before[0] + 5, f"{before} -> {after}")

        # ---- cancelling kills the child ----------------------------------
        app.send(b"\x1bc", settle=1.0)          # Alt-C
        app.pump(0.8)
        state = titles(app)
        check("cancelling a running child says so",
              state[2].startswith("[cancelled]"), str(state))

        # ---- and the run command still works -----------------------------
        before = counters(app)
        app.send(b"\x1br", settle=1.2)          # Alt-R
        after = counters(app)
        check("Run now starts a run without anything changing on disk",
              after[1] == before[1] + 1 and after[0] == before[0],
              f"{before} -> {after}")
        check("a re-run clears the previous output and fills it again",
              pane(app, 0) == ["alpha"], str(pane(app, 0)))

        app.send(b"\x1bx", settle=0.8)          # Alt-X
        code = app.wait(timeout=10)
        check("exited cleanly, with a child still running", code == 0, str(code))

        return check.report(app)
    finally:
        shutil.rmtree(watched, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
