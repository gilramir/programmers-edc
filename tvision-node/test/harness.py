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
import unicodedata

COLS, ROWS = 80, 25

# What a menu, a frame and the desktop are drawn out of. None of it is text, so
# none of it can be the hot letter or part of a title.
MENU_FRAME = " ░│┌┐└┘─╔╗╚╝║═[]■↕↑►"

# CSI / OSC / single-char escapes. Enough to turn a TVision screen dump into
# something we can run substring checks against.
ANSI = re.compile(
    rb"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][B0]|\x1b[=><]"
)


# Every `Pty` ever built, so that `Checks.report` can ask all of them what they
# drew. A driver that opens two applications -- `drive_env.py` opens a second
# one at a different size -- gets both swept without saying so.
_ptys = []


def same_colour(fg, bg):
    """Is a glyph in `fg` invisible on a background of `bg`?

    The two halves are written in different vocabularies and only the pairs
    that share one can be compared. Indexed: TVision emits 30-37 and 90-97 for
    a foreground and 40-47 and 100-107 for a background, so the same colour is
    the same number ten apart -- `ink Blue` on a blue window is `fg=34 bg=44`,
    which is the pair that was on the screen for a month. 24-bit: a theme sets
    both halves from the same palette, so equal tuples are the whole of it, and
    `("xterm", n)` compares the same way.

    A mixed pair -- an indexed ink on a 24-bit ground -- is not comparable and
    is not guessed at. It does not arise: a theme colours a window's ground and
    its text together, so either both halves went out as `38;2;r;g;b` or
    neither did.

    `None` is the terminal's own default, which is whatever the user's terminal
    is set to. Two defaults are a readable pair by definition, and one default
    against a colour cannot be judged from here.
    """
    if fg is None or bg is None:
        return False
    if isinstance(fg, tuple) and isinstance(bg, tuple):
        return fg == bg
    if isinstance(fg, int) and isinstance(bg, int):
        return bg == fg + 10
    return False


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
        # The last replay, and what it was a replay of. See `display`.
        self.replayed = None
        # Every distinct (glyph, ink, ground) this application has ever drawn
        # where the ink was the ground. See `display` and `Checks.report`.
        self.invisible = {}
        _ptys.append(self)

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

        Every time, but not more than once per stream. A replay is a pure
        function of the bytes and the size, so a second call with neither of
        them changed can only produce what the first one did -- and a check
        that reads the screen twice, once for the condition and once for the
        message to print if it fails, is the commonest shape in every driver
        here. Keeping the last one is not a stateful emulator: nothing carries
        over between two different buffers, and the moment a byte arrives the
        whole replay happens again from the beginning.
        """
        # The bytes themselves and not their length. A driver may take bytes
        # back *out* of the buffer -- `drive_hex.py` drops the megabyte-long
        # `OSC 52` payloads it has already read -- so two different streams can
        # be the same length, and a key that could not tell them apart would
        # hand back the wrong screen once in a very long while. Hashing a few
        # megabytes is a millisecond; replaying them is most of a second.
        key = (hash(self.buf), len(self.buf), self.cols, self.rows, self.widest, self.tallest)
        if self.replayed is not None and self.replayed[0] == key:
            return self.replayed[1]
        screen = Screen(cols=self.widest, rows=self.tallest).feed(
            self.buf.decode("utf-8", "replace")
        )
        # Replaying at the largest size the terminal ever had means a terminal
        # that later *shrank* still holds what it drew when it was bigger.
        # A real one would have thrown those cells away, and TVision only
        # repaints inside the current size, so crop to it.
        cropped = screen.crop(self.cols, self.rows)
        self.replayed = (key, cropped)
        # Every screen this driver looks at is also asked whether anything on
        # it is invisible. Free, because the replay is memoised and this runs
        # once per distinct stream; universal, because a driver reads the
        # screen for every check it makes and does not have to opt in. The
        # cells nobody asserted on are exactly where a colour that stopped
        # contrasting has always hidden.
        for col, row, ch, fg, bg in cropped.invisible_cells():
            self.invisible.setdefault(
                (ch, fg, bg),
                (col, row, "".join(cropped.grid[row]).rstrip()),
            )
        return cropped

    def render(self):
        """What the screen looks like *now*. Good for "what does X say"."""
        return self.display().text()

    def bar_titles(self):
        """`[(title, hot letter or None)]` for the menu bar, left to right.

        The bar is row zero and `TMenuBar` separates its titles with spaces, so
        a run of non-space characters is one title.
        """
        screen = self.display()
        row = "".join(screen.grid[0])
        found = []
        col = 0
        while col < len(row):
            if row[col] == " ":
                col += 1
                continue
            end = col
            while end < len(row) and row[end] != " ":
                end += 1
            found.append((row[col:end], screen.hot_letter(0, col, end)))
            col = end
        return found

    def menu_entries(self):
        """`[(text, hot letter, accelerator)]` for the pull-down that is open.

        A `TMenuBox` is the only thing on a Turbo Vision screen drawn in single
        lines with text between them, and its accelerator column is printed
        hard against the right-hand edge -- so the entry's own words are
        everything before the last run of two spaces. Separators come back as
        nothing and are dropped.
        """
        screen = self.display()
        found = []
        for row in range(screen.rows):
            line = "".join(screen.grid[row])
            if "│" not in line:
                continue
            first, last = line.index("│"), line.rindex("│")
            if last - first < 4:
                continue
            text = line[first + 1:last].strip()
            if not text or set(text) <= set("─"):
                continue
            parts = text.rsplit("  ", 1)
            found.append((parts[0].strip(),
                          screen.hot_letter(row, first + 1, last),
                          parts[1].strip() if len(parts) == 2 else ""))
        return found

    def active_title(self):
        """The title on the frame of the window that has the focus, or None.

        Turbo Vision draws the active window's frame in double lines and every
        other window's in single ones, so the `╔` is the whole of the question
        -- and it is the only way a driver can tell "that tool came to the
        front" from "that tool is somewhere on the screen".
        """
        for line in self.render().split("\n"):
            if "╔" in line:
                middle = line[line.index("╔"):line.rindex("╗") + 1] if "╗" in line else line
                # The close and zoom boxes are drawn *into* the top border, so
                # they have to come out before the border does: stripping first
                # leaves the bracket behind and a yard of `═` with it.
                return " ".join(re.sub(r"\[.\]", " ", middle).strip("░╔╗═ ").split()) or None
        return None

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

    def drag(self, path, settle=0.5, button=0):
        """Press at the first 1-based (col, row) of `path`, move through the
        rest, and release at the last one.

        Motion is the button code *plus 32*, which is what mode 1002 reports
        while a button is held and what `termio.cpp` reads back out. Without
        the 32 the same sequence is another press, which is a different
        gesture entirely and lands as a second `Clicked`.

        A cell the pointer is already on is not re-reported by a real
        terminal, and the binding drops one anyway, so a path may repeat a
        cell without changing what the program sees. What it must not do is
        skip the press: a drag whose button was never seen going down belongs
        to no view, because the capture is what a press creates.
        """
        col, row = path[0]
        self.send(f"\x1b[<{button};{col};{row}M".encode(), settle=0.15)
        for col, row in path[1:]:
            self.send(f"\x1b[<{button + 32};{col};{row}M".encode(), settle=0.15)
        col, row = path[-1]
        self.send(f"\x1b[<{button};{col};{row}m".encode(), settle=settle)

    def wheel(self, col, row, down=True, turns=1, settle=0.5):
        """Turn the mouse wheel at 1-based (col, row).

        Codes 64 and 65 rather than a button, and a press with no release:
        a wheel has nothing to let go of, and `termio.cpp:541` reads the two
        out of the same SGR sequence a click arrives in. One turn is three
        `arrowStep`s, so a nine-row list needs four of them to move a row.
        """
        code = 65 if down else 64
        for _ in range(turns):
            self.send(f"\x1b[<{code};{col};{row}M".encode(), settle=settle)

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

    def ink(self):
        """One check, per driver, that nothing it saw was invisible.

        Run from `report`, so every driver already makes it. It is one check
        rather than one per cell because it is one defect -- a colour chosen
        against a ground it is no longer drawn on -- and a driver that walks
        past it twenty times has not found twenty of them.

        What it catches is the class the suite was structurally blind to. A
        span whose ink stopped contrasting still draws, so nothing crashes and
        nothing looks wrong except to the eye: the hex viewer's offset column
        was `fg=34 bg=44` for a month, and no check failed because no check
        asserted on cells nobody was looking at.
        """
        seen = []
        for pty in _ptys:
            # By the printed form: a key holds an int for an indexed colour
            # and a tuple for a 24-bit one, and sorting those against each
            # other is a TypeError rather than an order.
            for (ch, fg, bg), (col, row, line) in sorted(pty.invisible.items(), key=str):
                seen.append(f"{ch!r} fg={fg} bg={bg} at ({col},{row}) in {line!r}")
        self("nothing was drawn in the colour behind it", not seen,
             "; ".join(seen[:6]) + (f" ... and {len(seen) - 6} more" if len(seen) > 6 else ""))

    def report(self, app=None, extra=None):
        self.ink()
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


def cell_width(ch):
    """How many columns a character takes on the screen.

    Two for East Asian Wide and Fullwidth -- CJK, and the emoji, which Unicode
    classifies `W`. **One for Ambiguous**, which is not a detail: `é`, `│`, `·`
    and `▲` are all `A`, and every box a Turbo Vision program draws is made of
    them. A terminal only widens those if it is told to, and TVision assumes it
    was not.

    Zero for a combining mark, which is why this returns a number rather than a
    boolean.

    It exists because a decoder that shows you the character it decoded is a
    decoder whose output is half CJK and emoji, and an emulator that counted
    every character as one column would report a screen that slid left by one
    for each of them. This is also what stood in front of testing anything
    translated -- see `programmers-edc/README.md` on i18n.
    """
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


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
        self.wide = [{c for c in row if c + 1 < cols} for row in self.wide[:rows]]
        self.cols, self.rows = cols, rows
        self._clamp()
        return self

    def reset(self):
        self.grid = [[" "] * self.cols for _ in range(self.rows)]
        # The columns holding the *left* half of a double-width character.
        # Without this a wide character is indistinguishable from a character
        # plus a space, and the one thing a real terminal does that the
        # difference matters for -- erasing both halves when either is written
        # over -- cannot be modelled. See `_break_at`.
        self.wide = [set() for _ in range(self.rows)]
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

    def hot_letter(self, row, first, last):
        """The letter Turbo Vision drew as a hot key between two columns.

        There is no underline. A hot letter is drawn in the menu palette's
        *shortcut* colour and everything around it in the ordinary one, so once
        a menu has been rendered the colour is the only place that information
        exists -- which makes this the one question about a menu that cannot be
        answered by reading the text off the screen.

        The odd colour out is the answer: whatever all the ordinary text is in
        occurs many times, and the hot letter's occurs once. `None` when there
        is no single odd cell, which is what a title with no `~` in it looks
        like and is an answer rather than a failure.
        """
        cells = [
            (self.grid[row][col], self.attrs[row][col][0])
            for col in range(first, min(last, self.cols))
            if self.grid[row][col] not in MENU_FRAME
        ]
        counts = {}
        for _, fg in cells:
            counts[fg] = counts.get(fg, 0) + 1
        odd = [ch for ch, fg in cells if counts[fg] == 1]
        return odd[0] if len(odd) == 1 else None

    def invisible_cells(self):
        """Every cell holding a glyph drawn in the colour it is drawn on.

        `(col, row, glyph, fg, bg)` each. A space is not a glyph: the whole
        screen outside a window is spaces in some colour on the same colour's
        ground and none of it is a defect. Everything else is -- a border, a
        digit, a letter -- because a character nobody can see is a character
        that was not drawn, and it draws exactly as happily as one that can.
        """
        found = []
        for row in range(self.rows):
            for col in range(self.cols):
                ch = self.grid[row][col]
                if ch == " ":
                    continue
                fg, bg = self.attrs[row][col]
                if same_colour(fg, bg):
                    found.append((col, row, ch, fg, bg))
        return found

    def fg_run(self, col, row, width):
        """The foreground colours of `width` cells, left to right."""
        return [self.fg_at(col + i, row) for i in range(width)]

    def _clamp(self):
        self.row = max(0, min(self.rows - 1, self.row))
        self.col = max(0, min(self.cols - 1, self.col))

    def _break_at(self, row, col):
        """Erase the double-width character that column `col` is part of.

        This is what a real terminal does and it is the whole reason the wide
        halves are tracked. A double-width character is one glyph across two
        cells; write anything into either of them and the *pair* is gone --
        a terminal blanks both halves rather than leaving a torn one, which is
        what `tmux capture-pane` shows and what this was measured against.

        A model that keeps the left half alive because only the right one was
        written over will pass a check that a CJK character is on the screen
        while the terminal shows a blank, which is exactly the bug this was
        added for.
        """
        for lead in (col, col - 1):
            if lead in self.wide[row]:
                self.wide[row].discard(lead)
                self.grid[row][lead] = " "
                if lead + 1 < self.cols:
                    self.grid[row][lead + 1] = " "

    def _blank(self, row, first, last):
        """Blank cells `first`..`last` inclusive, wide characters and all."""
        self._break_at(row, first)
        self._break_at(row, last)
        for c in range(first, last + 1):
            self.grid[row][c] = " "
            self.wide[row].discard(c)

    def _put(self, ch):
        if self.col >= self.cols:
            self.col = self.cols - 1
        width = cell_width(ch)

        if width == 0:
            # A combining mark belongs to the character before it and takes no
            # column of its own. Written into the same cell, so that cell holds
            # two code points -- which is what it is.
            back = max(0, self.col - 1)
            self.grid[self.row][back] += ch
            return

        self._break_at(self.row, self.col)
        self.grid[self.row][self.col] = ch
        self.attrs[self.row][self.col] = (self.fg, self.bg)
        self.col += 1

        if width == 2 and self.col < self.cols:
            # The right half. A wide character is one code point standing in
            # two columns, so the cell beside it is filled with a space rather
            # than left as whatever was there -- which keeps a row's string
            # index and its column the same number, the thing every driver in
            # this repo counts on. The pair is remembered so that a later write
            # to either half erases both, the way a terminal does.
            self._break_at(self.row, self.col)
            self.wide[self.row].add(self.col - 1)
            self.grid[self.row][self.col] = " "
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
                self._blank(self.row, self.col, self.cols - 1)
            elif nums[0] == 1:
                self._blank(self.row, 0, self.col)
            else:
                self._blank(self.row, 0, self.cols - 1)
        elif final == "J":
            if nums[0] == 2:
                self.grid = [[" "] * self.cols for _ in range(self.rows)]
                self.wide = [set() for _ in range(self.rows)]
            elif nums[0] == 0:
                self._blank(self.row, self.col, self.cols - 1)
                for r in range(self.row + 1, self.rows):
                    self.grid[r] = [" "] * self.cols
                    self.wide[r] = set()
        elif final == "m":
            self._sgr(params)
        self._clamp()

    def _sgr(self, params):
        """Enough of Select Graphic Rendition to tell two colours apart.

        TVision emits the basic and bright colour codes directly -- 30-37 and
        90-97 for foregrounds, 40-47 and 100-107 for backgrounds -- so there is
        no need to interpret bold as brightness. `ESC[m` with no parameters is
        a reset, exactly like `ESC[0m`.

        It also emits `38;2;r;g;b` for a 24-bit colour, which is what a
        `Tui.Rgb` in a theme becomes. Those are stored as an `(r, g, b)` tuple
        rather than a number, so a test can tell one from an indexed colour by
        its type and every existing `== 34` goes on meaning what it meant.
        **Parsing them is not optional.** A parser that skips the parameters it
        does not recognise reads `2`, `240`, `140` and `0` as four separate
        codes, matches none of them, and leaves the *previous* colour in place
        -- so every cell of a truecolor screen reports whatever was last set
        from the sixteen, which looks exactly like a screen that did not
        repaint.
        """
        codes = [int(p) if p.isdigit() else 0 for p in (params or "0").split(";")]
        i = 0
        while i < len(codes):
            num = codes[i]
            if num in (38, 48) and i + 1 < len(codes):
                kind = codes[i + 1]
                if kind == 2 and i + 4 < len(codes):
                    value = (codes[i + 2], codes[i + 3], codes[i + 4])
                    i += 5
                elif kind == 5 and i + 2 < len(codes):
                    value = ("xterm", codes[i + 2])
                    i += 3
                else:
                    i += 2
                    continue
                if num == 38:
                    self.fg = value
                else:
                    self.bg = value
                continue
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
            i += 1

    def text(self):
        return "\n".join("".join(row).rstrip() for row in self.grid)
