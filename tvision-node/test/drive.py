#!/usr/bin/env python3
"""Drive the Turbo Vision app through a pty and assert on what it draws.

A TUI cannot be tested by piping stdin: TVision refuses to start unless
stdin/stdout are a terminal, and it draws with cursor addressing rather than
lines of text. So we allocate a pty, fix its size at 80x25 (the dialog
rectangles in hello.js assume it), type at it, and strip the escape sequences
back out of what comes off the other end.
"""

import errno
import fcntl
import os
import pty
import re
import select
import signal
import struct
import sys
import termios
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = os.path.join(HERE, "..", "build", "drive.log")

COLS, ROWS = 80, 25

# CSI / OSC / single-char escapes. Enough to turn a TVision screen dump into
# something we can run substring checks against.
ANSI = re.compile(rb"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][B0]|\x1b[=><]")


class Pty:
    def __init__(self, argv, env):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
            os.execvpe(argv[0], argv, env)
            os._exit(127)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
        self.buf = b""

    def pump(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], max(0, end - time.time()))
            if not r:
                continue
            try:
                chunk = os.read(self.fd, 65536)
            except OSError as e:
                if e.errno in (errno.EIO, errno.EBADF):
                    return
                raise
            if not chunk:
                return
            self.buf += chunk

    def screen(self):
        return ANSI.sub(b"", self.buf).decode("utf-8", "replace")

    def send(self, data, settle=0.6):
        os.write(self.fd, data)
        self.pump(settle)

    def wait(self, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                return os.waitstatus_to_exitcode(status)
            self.pump(0.1)
        os.kill(self.pid, signal.SIGKILL)
        os.waitpid(self.pid, 0)
        return None


failures = []


def check(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f"   ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def main():
    if os.path.exists(LOG):
        os.remove(LOG)

    env = dict(os.environ, TERM="xterm-256color", TVISION_LOG=os.path.abspath(LOG))
    app = Pty(["node", os.path.join(ROOT, "examples", "hello.js")], env)

    # 1. It starts and draws its chrome.
    app.pump(1.5)
    first = app.screen()
    check("menu bar drawn", "Hello" in first)
    check("status line drawn", "Alt-X Exit" in first)

    # 2. Alt-G opens the greeting dialog. In a terminal Alt-<key> arrives as
    #    ESC followed by the key.
    app.send(b"\x1bg", settle=1.0)
    dialog = app.screen()
    check("dialog title", "Hello, World!" in dialog)
    check("dialog static text", "How are you?" in dialog)
    check("dialog buttons", all(b in dialog for b in ("Terrific", "Ok", "Lousy", "Cancel")),
          "buttons missing")

    # 3. Tab off the initially-focused button (Cancel -- TVision focuses the
    #    last view inserted) so we exercise a real answer, then press it. The
    #    messageBox that follows is the interesting part: it is JS calling back
    #    into C++ from inside a C++ callback into JS, with a modal dialog
    #    already on the stack.
    #    Space presses the focused button; Enter would fire the *default*
    #    button (cmDefault broadcast) and this dialog, like hello.cpp's, has
    #    no bfDefault button -- so Enter here does nothing at all.
    app.send(b"\t", settle=0.5)
    app.send(b" ", settle=1.0)
    answered = app.screen()
    check("messageBox from inside the callback", "You said you feel" in answered,
          "no messageBox after pressing a button")
    app.send(b"\r", settle=0.6)   # dismiss the messageBox
    app.send(b"\x1b", settle=0.4) # and anything still on top

    # 4. Alt-X quits, run() returns, and the JS after it runs.
    app.send(b"\x18", settle=0.3)   # Ctrl-X, in case Alt-X is swallowed
    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)

    check("process exited", code is not None, f"still running")
    check("exit code 0", code == 0, f"exit={code}")
    check("ran the code after run()", "tvision app exited cleanly" in app.screen())

    # 5. The JS callback actually saw the command and the dialog's answer.
    logged = open(LOG).read() if os.path.exists(LOG) else ""
    check("onCommand fired", "command: greet" in logged, repr(logged[:200]))
    check("dialog result returned to JS",
          any(f"answer: {a}" in logged for a in ("terrific", "fine", "lousy")),
          repr(logged[:200]))

    print()
    print("--- log ---")
    print(logged.rstrip() or "(empty)")
    if failures:
        print("\n--- last screen ---")
        print(app.screen()[-2000:])
        print(f"\n{len(failures)} failed: {', '.join(failures)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
