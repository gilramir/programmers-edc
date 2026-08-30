#!/usr/bin/env python3
"""Memory regressions, run under AddressSanitizer.

Requires an ASAN build:  npx node-gyp rebuild -- -Dasan=1
"""

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Pty, Checks, node_argv, asan_enabled

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main():
    check = Checks()

    # asan.sh points ASAN_OPTIONS at build/asan.<pid>; a report is a file, not
    # a string we have to fish out of a repainting terminal.
    reports = os.path.join(ROOT, "build", "asan.*")
    for stale in glob.glob(reports):
        os.remove(stale)

    env = dict(os.environ, TERM="xterm-256color")
    if not asan_enabled():
        print("note: TVNODE_ASAN=1 not set -- running as a plain functional "
              "test, with no memory checking")
    app = Pty(node_argv(os.path.join(HERE, "regress_inputline.js")), env, cwd=ROOT)

    app.pump(2.0)
    check("dialog opened", "Round 1" in app.render(), app.screen()[-300:])

    # The OK button is the default one, so Enter presses it.
    for _ in range(6):
        app.send(b"\r", settle=0.7)

    code = app.wait(timeout=10)
    out = app.screen()

    found = glob.glob(reports)
    check("no AddressSanitizer report", not found,
          open(found[0]).read()[:900] if found else "")
    check("all rounds survived", "survived 5 dialogs" in out, out[-300:])
    check("exit code 0", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
