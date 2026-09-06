#!/usr/bin/env python3
"""The second half of the small-terminal sweep, and predc. See `tiny_common.py`."""

import sys

from tiny_common import sweep

if __name__ == "__main__":
    sys.exit(sweep(lambda label: label >= "m"))
