#!/usr/bin/env python3
"""Start a packed predc at a real pty, open a tool, and check what it drew.

Runs *inside* the verification container, so it is standard library only and
deliberately not `tvision-node/test/harness.py`: the point of this file is that
nothing but the tarball and a stock Node image is present, and mounting the
repo's own test harness in would quietly undo that.

**The escapes have to come off before anything is searched for.** A menu title
is drawn as two runs -- the hot key in an accent colour, the rest in the
ordinary one -- so `File` reaches the pty as `F`, an SGR, then `ile`, and a
search for the word finds nothing while the program is working perfectly. That
cost a wrong answer once here: only `RPN Calculator`, which has no hot key,
matched.
"""

import fcntl
import os
import pty
import re
import select
import struct
import sys
import termios
import time

WANTED = ["File", "Tools", "Options", "Help", "Alt-X Exit",
          "RPN Calculator", "base dec"]


def main(exe):
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        os.environ["COLORTERM"] = "truecolor"
        os.execv(exe, [exe])
    # Before it draws: Turbo Vision reads the size at startup, and a pty that
    # was never sized reports zero rows.
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))

    buf = bytearray()

    def drain(seconds):
        end = time.time() + seconds
        while time.time() < end:
            if select.select([fd], [], [], 0.2)[0]:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    return
                if not chunk:
                    return
                buf.extend(chunk)

    drain(4.0)
    os.write(fd, b"\x1br")      # Alt-R, the RPN calculator
    drain(2.0)
    os.write(fd, b"\x1bx")      # Alt-X, exit
    drain(1.5)
    os.waitpid(pid, 0)

    text = buf.decode("utf-8", "replace")
    text = re.sub(r"\x1b\][^\x07\x1b]*(\x07|\x1b\\)", "", text)   # OSC
    text = re.sub(r"\x1bP[^\x1b]*\x1b\\", "", text)               # DCS
    text = re.sub(r"\x1b\[[0-9;?<>]*[a-zA-Z]", "", text)          # CSI
    text = re.sub(r"\x1b[=>()#][0-9A-Za-z]?", "", text)           # the rest

    missing = [want for want in WANTED if want not in text]
    for want in WANTED:
        print("   %-16s %s" % (want, "ok" if want in text else "MISSING"))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(os.path.abspath(sys.argv[1])))
