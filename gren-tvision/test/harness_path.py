"""Put `harness.py` on `sys.path`, from wherever it is.

**This directory exists twice.** Here it is `gren-tvision/test/` in the
monorepo, where the harness is the master copy at
`../../tvision-node/test/harness.py`. In the exported package repository
(`gilramir/gren-tvision`) there is no monorepo above it -- the export is this
directory and nothing over it -- and the harness is the copy that ships inside
the npm runtime, at `node_modules/gren-tvision-runtime/pty/harness.py`.

So the drivers ask for it rather than naming it, and this is the asking.
The monorepo's sibling is tried first, deliberately: there it is the copy
being worked on, and an installed one would test the last release instead.

`RUNTIME` -- the path to `gren-tui.js`, which is what actually starts a
compiled Gren program -- moves for exactly the same reason and is resolved
here too.

A driver imports this for both:

    from harness_path import RUNTIME
    from harness import Pty, Checks, node_argv

which works with no `sys.path` setup of its own, because Python puts a
script's own directory on the path before running it -- and importing this
module is what puts `harness` there.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CANDIDATES = (
    # The monorepo: gren-tvision/test -> tvision-node/test
    os.path.join(ROOT, "..", "tvision-node", "test"),
    # The exported repository, with the runtime installed into it
    os.path.join(ROOT, "node_modules", "gren-tvision-runtime", "pty"),
    # ...or installed a level up, which is where a workspace would put it
    os.path.join(ROOT, "..", "node_modules", "gren-tvision-runtime", "pty"),
)

for _candidate in CANDIDATES:
    if os.path.exists(os.path.join(_candidate, "harness.py")):
        sys.path.insert(0, _candidate)
        break
else:
    sys.exit(
        "no harness.py found. In this repository it is at "
        "tvision-node/test/harness.py; on its own, run "
        "`npm install gren-tvision-runtime` here and it ships in that package "
        "at pty/harness.py."
    )


# gren-tui.js, which is what starts a compiled Gren program: `main.js` is a
# module that exports `Gren.Main.init` and does not run itself. Same two
# places as the harness, and same order and reason.
_RUNTIMES = (
    os.path.join(ROOT, "..", "gren-tvision-runtime", "bin", "gren-tui.js"),
    os.path.join(ROOT, "node_modules", "gren-tvision-runtime", "bin", "gren-tui.js"),
    os.path.join(ROOT, "..", "node_modules", "gren-tvision-runtime", "bin", "gren-tui.js"),
)

RUNTIME = next((r for r in _RUNTIMES if os.path.exists(r)), _RUNTIMES[0])
