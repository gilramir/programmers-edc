"""Drive a Turbo Vision app through a pty and read what it drew.

A TUI cannot be tested by piping stdin: the addon refuses to start unless
stdin/stdout are a terminal, and it draws with cursor addressing rather than
lines of text. So we allocate a pty, give it a size -- 80x25 unless a test asks
for another, which most of the examples' rectangles assume -- type at it, and
strip the escape sequences back out of what comes off the other end.

`screen()` returns everything written since the process started, not the
current screen contents -- which is what we want for "did this ever appear"
and for watching a value change over time.
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

COLS, ROWS = 80, 25

# CSI / OSC / single-char escapes. Enough to turn a TVision screen dump into
# something we can run substring checks against.
ANSI = re.compile(
    rb"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][B0]|\x1b[=><]"
)


class Pty:
    def __init__(self, argv, env=None, cwd=None, size=(COLS, ROWS)):
        env = env or dict(os.environ)
        cols, rows = size
        # The emulator replays the whole byte stream from the start on every
        # render, so a grid that changed size mid-replay would have to be
        # rewound. It is sized to the largest the terminal ever gets instead:
        # everything written before a resize fits in it, and TVision repaints
        # the whole screen afterwards, so nothing stale survives.
        self.cols, self.rows = cols, rows
        self.widest, self.tallest = cols, rows
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            if cwd:
                os.chdir(cwd)
            os.execvpe(argv[0], argv, env)
            os._exit(127)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.buf = b""

    def resize(self, cols, rows, settle=1.5):
        """Resize the terminal, the way dragging a window's corner does.

        The ioctl is what a real terminal emulator does; the SIGWINCH is what
        the kernel sends alongside it, and TVision is listening for it. Without
        the signal the size changes and nothing notices.
        """
        self.cols, self.rows = cols, rows
        self.widest, self.tallest = max(self.widest, cols), max(self.tallest, rows)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        os.kill(self.pid, signal.SIGWINCH)
        self.pump(settle)

    def pump(self, seconds):
        """Read for `seconds`, keeping everything."""
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
        """Everything ever written, escapes stripped. Good for "did X appear"."""
        return ANSI.sub(b"", self.buf).decode("utf-8", "replace")

    def display(self):
        """The screen as it stands now: text, cursor and colour together.

        Replay the whole stream every time: the buffers here are small and a
        stateful emulator that could drift is not worth the debugging.
        """
        screen = Screen(cols=self.widest, rows=self.tallest).feed(
            self.buf.decode("utf-8", "replace")
        )
        # Replaying at the largest size the terminal ever had means a terminal
        # that later *shrank* still holds what it drew when it was bigger.
        # A real one would have thrown those cells away, and TVision only
        # repaints inside the current size, so crop to it.
        return screen.crop(self.cols, self.rows)

    def render(self):
        """What the screen looks like *now*. Good for "what does X say"."""
        return self.display().text()

    def cursor(self):
        """Where the terminal's own cursor is now, as (col, row), zero-based.

        Turbo Vision moves the hardware cursor to whatever the focused view
        asks for, which for a canvas is the only way its selection shows up at
        all -- there is nothing on the screen to grep for.
        """
        screen = self.display()
        return (screen.col, screen.row)

    def send(self, data, settle=0.6):
        os.write(self.fd, data)
        self.pump(settle)

    def click(self, col, row, settle=0.5, button=0):
        """One click at 1-based (col, row), in SGR mouse encoding.

        TVision turns on modes 1000, 1002 and 1006 at startup, so it is
        listening for these -- which makes the close box, the scroll bars and
        list selection reachable from a test.

        `button` is the SGR code: 0 is the left button and 2 is the right one,
        which is the one a context menu is opened with.
        """
        self.send(f"\x1b[<{button};{col};{row}M".encode(), settle=0.15)
        self.send(f"\x1b[<{button};{col};{row}m".encode(), settle=settle)

    def right_click(self, col, row, settle=0.5):
        self.click(col, row, settle=settle, button=2)

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

    def kill(self):
        try:
            os.kill(self.pid, signal.SIGKILL)
            os.waitpid(self.pid, 0)
        except OSError:
            pass


def node_argv(script, *args):
    """["node", script] -- or the ASAN wrapper when TVNODE_ASAN=1.

    An addon linked with -fsanitize=address cannot be dlopen'd into a plain
    node: "ASan runtime does not come first in initial library list". The
    runtime has to be preloaded, which is what test/asan.sh does. Every driver
    goes through here so an ASAN build does not silently fail to start and
    look like an application bug.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    node = ["node"]
    if os.environ.get("TVNODE_ASAN") == "1":
        node = [os.path.join(here, "asan.sh"), "node"]
    return node + [script] + list(args)


def asan_enabled():
    return os.environ.get("TVNODE_ASAN") == "1"


class Checks:
    def __init__(self):
        self.failures = []

    def __call__(self, name, ok, detail=""):
        print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f"   ({detail})" if detail and not ok else ""))
        if not ok:
            self.failures.append(name)
        return ok

    def report(self, app=None, extra=None):
        print()
        if extra:
            print(extra)
        if self.failures:
            if app is not None:
                print("--- screen ---")
                print(app.render())
            print(f"\n{len(self.failures)} failed: {', '.join(self.failures)}")
            return 1
        print("all checks passed")
        return 0


def latest_int(text, pattern):
    """Highest number matched by `pattern` anywhere in the output so far."""
    found = [int(m) for m in re.findall(pattern, text)]
    return max(found) if found else None


class Screen:
    """A very small terminal emulator.

    Needed because TVision repaints only the cells that changed: a counter
    ticking from 11 to 12 emits a cursor move and the two digits, so grepping
    the byte stream for "ticks: 12" finds nothing. To watch a value change you
    have to keep an actual screen.

    Handles what TVision emits: cursor addressing, relative moves, erases,
    text, and the SGR colours -- the last of those because a canvas can paint
    a span in a colour of its own, and for something like a calendar marking
    today, the colour is the entire visible difference. Mode changes,
    OSC/DCS/APC strings and the like are parsed only well enough to be
    skipped.
    """

    def __init__(self, cols=COLS, rows=ROWS):
        self.cols, self.rows = cols, rows
        self.reset()

    def crop(self, cols, rows):
        """Throw away everything outside a `cols` x `rows` terminal."""
        if cols == self.cols and rows == self.rows:
            return self
        self.grid = [row[:cols] for row in self.grid[:rows]]
        self.attrs = [row[:cols] for row in self.attrs[:rows]]
        self.cols, self.rows = cols, rows
        self._clamp()
        return self

    def reset(self):
        self.grid = [[" "] * self.cols for _ in range(self.rows)]
        # Per cell, the (foreground, background) in force when it was written.
        # None is the terminal's default, which is what SGR 39/49 restore.
        self.attrs = [[(None, None)] * self.cols for _ in range(self.rows)]
        self.fg = self.bg = None
        self.row = self.col = 0

    def fg_at(self, col, row):
        """The foreground colour of one cell: 30-37, 90-97, or None."""
        return self.attrs[row][col][0]

    def bg_at(self, col, row):
        """The background colour of one cell: 40-47, 100-107, or None."""
        return self.attrs[row][col][1]

    def fg_run(self, col, row, width):
        """The foreground colours of `width` cells, left to right."""
        return [self.fg_at(col + i, row) for i in range(width)]

    def _clamp(self):
        self.row = max(0, min(self.rows - 1, self.row))
        self.col = max(0, min(self.cols - 1, self.col))

    def _put(self, ch):
        if self.col >= self.cols:
            self.col = self.cols - 1
        self.grid[self.row][self.col] = ch
        self.attrs[self.row][self.col] = (self.fg, self.bg)
        self.col += 1
        if self.col >= self.cols:
            self.col = self.cols - 1

    def feed(self, text):
        i, n = 0, len(text)
        while i < n:
            ch = text[i]

            if ch == "\x1b":
                i = self._escape(text, i)
                continue

            i += 1
            if ch == "\r":
                self.col = 0
            elif ch == "\n":
                self.row += 1
                self._clamp()
            elif ch == "\b":
                self.col = max(0, self.col - 1)
            elif ch == "\t":
                self.col = min(self.cols - 1, (self.col // 8 + 1) * 8)
            elif ch in ("\x07", "\x00"):
                pass
            elif ch >= " ":
                self._put(ch)
        return self

    def _escape(self, text, i):
        n = len(text)
        if i + 1 >= n:
            return n
        kind = text[i + 1]

        if kind == "[":                       # CSI
            j = i + 2
            while j < n and not ("@" <= text[j] <= "~"):
                j += 1
            if j >= n:
                return n
            self._csi(text[i + 2:j], text[j])
            return j + 1

        if kind in "]P_^":                    # OSC / DCS / APC / PM: skip to ST
            j = i + 2
            while j < n:
                if text[j] == "\x07":
                    return j + 1
                if text[j] == "\x1b" and j + 1 < n and text[j + 1] == "\\":
                    return j + 2
                j += 1
            return n

        if kind in "()#":                     # charset selection: two more bytes
            return i + 3
        return i + 2                          # ESC =, ESC >, ESC M, ...

    def _csi(self, params, final):
        if params.startswith("?"):            # private modes: alt screen etc.
            return
        nums = [int(p) if p.isdigit() else 0 for p in params.split(";")] or [0]

        if final in "Hf":
            self.row = (nums[0] or 1) - 1
            self.col = (nums[1] if len(nums) > 1 else 1) or 1
            self.col -= 1
            self._clamp()
        elif final == "A":
            self.row -= nums[0] or 1
        elif final == "B":
            self.row += nums[0] or 1
        elif final == "C":
            self.col += nums[0] or 1
        elif final == "D":
            self.col -= nums[0] or 1
        elif final == "G":
            self.col = (nums[0] or 1) - 1
        elif final == "d":
            self.row = (nums[0] or 1) - 1
        elif final == "K":
            if nums[0] == 0:
                for c in range(self.col, self.cols):
                    self.grid[self.row][c] = " "
            elif nums[0] == 1:
                for c in range(0, self.col + 1):
                    self.grid[self.row][c] = " "
            else:
                self.grid[self.row] = [" "] * self.cols
        elif final == "J":
            if nums[0] == 2:
                self.grid = [[" "] * self.cols for _ in range(self.rows)]
            elif nums[0] == 0:
                for c in range(self.col, self.cols):
                    self.grid[self.row][c] = " "
                for r in range(self.row + 1, self.rows):
                    self.grid[r] = [" "] * self.cols
        elif final == "m":
            self._sgr(params)
        self._clamp()

    def _sgr(self, params):
        """Enough of Select Graphic Rendition to tell two colours apart.

        TVision emits the basic and bright colour codes directly -- 30-37 and
        90-97 for foregrounds, 40-47 and 100-107 for backgrounds -- so there is
        no need to interpret bold as brightness. `ESC[m` with no parameters is
        a reset, exactly like `ESC[0m`.
        """
        for num in [int(p) if p.isdigit() else 0 for p in (params or "0").split(";")]:
            if num == 0:
                self.fg = self.bg = None
            elif 30 <= num <= 37 or 90 <= num <= 97:
                self.fg = num
            elif 40 <= num <= 47 or 100 <= num <= 107:
                self.bg = num
            elif num == 39:
                self.fg = None
            elif num == 49:
                self.bg = None

    def text(self):
        return "\n".join("".join(row).rstrip() for row in self.grid)
