#!/usr/bin/env python3
"""The Gren scheme, swept. See `ink_common.py`.

The light one, and therefore the one worth having: every ink the other two
schemes use is a bright hue, and a bright hue on a light ground is the pair
that disappears.
"""

import sys

from ink_common import sweep

if __name__ == "__main__":
    sys.exit(sweep("gren", "Gren"))
