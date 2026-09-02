#!/usr/bin/env python3
"""The time converter's JavaScript half, checked without a terminal.

Not a pty driver, despite the name: `tools/run_tests.py` treats every
`test/drive*.py` as a suite and there is no list to register one in, so this is
what a node test looks like from where the runner is standing.

It is separate from `drive_time.py` because the two ask different questions.
That one is about the window -- what a keystroke does, which row moves, where
the caret stays. This one is about the IANA time zone database: that Nepal was
+05:30 in 1970 and is +05:45 now, that a Chicago morning in March is missing an
hour and a Chicago morning in November has one twice, that year 70 means 70 and
not 1970. Driving a terminal to ask those would be slower and would tell you
less about which half was wrong.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKS = os.path.join(HERE, "timezones.checks.js")


def main():
    done = subprocess.run(
        ["node", CHECKS],
        cwd=HERE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    sys.stdout.write(done.stdout.decode("utf-8", "replace"))
    return done.returncode


if __name__ == "__main__":
    sys.exit(main())
