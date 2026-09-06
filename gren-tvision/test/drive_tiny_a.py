#!/usr/bin/env python3
"""The first half of the small-terminal sweep. See `tiny_common.py`."""

import sys

from tiny_common import sweep

if __name__ == "__main__":
    sys.exit(sweep(lambda label: label < "m"))
