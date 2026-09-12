#!/usr/bin/env python3
"""examples/puzzle -- tvdemo's sliding puzzle, in Gren.

The interesting thing about this one is that the test can *win*.

`TPuzzleView` seeds `rand()` from the wall clock in its constructor and then
makes five hundred moves, so the C++ board is unreachable state: there is no
board you can ask for and no way to know what the answer is. The Gren version
carries its generator in the model, which makes the board a pure function of a
seed and a depth -- so the example takes `--seed=<n>` and `--scramble=<n>`, and
the second run below reproduces the shuffle in eight lines of Python, checks
that the screen agrees, searches for the answer and plays it.

The colours are the other half. Tiles alternate in a checkerboard keyed on the
letter rather than the square, so the pattern is a picture of how scrambled the
board is; solving it drops every tile back to one colour, which is the only
announcement the original makes that you have won.
"""

import os
import sys
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLE = os.path.join(ROOT, "examples", "puzzle")
from harness_path import RUNTIME  # finds harness.py and gren-tui.js, here or in an install

from harness import Pty, Checks, node_argv

SOLVED = "ABCDEFGHIJKLMNO "

# The canvas sits at desktop (2, 2) -- one inside a window at (1, 1) -- and
# screen row 0 is the menu bar, so canvas (0, 0) is here. Each tile is three
# columns wide with its letter in the middle.
ORIGIN = (2, 3)

ARROWS = {"Up": b"\x1b[A", "Down": b"\x1b[B", "Right": b"\x1b[C", "Left": b"\x1b[D"}

# The key names slide a *tile*, so they move the hole the other way. This is
# the original's naming and the Gren port keeps it.
HOLE_MOVES = {"Down": -4, "Up": 4, "Right": -1, "Left": 1}

# A short random walk can wander back to where it started. This seed is one
# where neither the opening shuffle nor the one that follows a win does.
SEED, DEPTH = 1, 6


def board_of(screen):
    """The sixteen squares, read left to right and top to bottom."""
    rows = screen.split("\n")
    out = ""
    for y in range(4):
        row = rows[ORIGIN[1] + y]
        for x in range(4):
            at = ORIGIN[0] + x * 3 + 1
            out += row[at] if at < len(row) else " "
    return out


def moves_of(screen):
    """The move counter, which the canvas paints beside the third row."""
    row = screen.split("\n")[ORIGIN[1] + 2]
    return int(row[ORIGIN[0] + 12:].split("║")[0].strip() or 0)


def coloured(display):
    """How many board cells are painted in the highlight colour."""
    body = display.fg_at(ORIGIN[0] + 16, ORIGIN[1] + 1)   # the "Move" label
    return sum(
        1
        for y in range(4)
        for x in range(12)
        if display.fg_at(ORIGIN[0] + x, ORIGIN[1] + y) != body
    )


def legal(board, key):
    """Where the hole ends up, or None if that key does nothing here."""
    hole = board.index(" ")
    delta = HOLE_MOVES[key]
    to = hole + delta
    if to < 0 or to > 15:
        return None
    if abs(delta) == 1 and to // 4 != hole // 4:
        return None
    return to


def apply(board, key):
    hole = board.index(" ")
    to = legal(board, key)
    if to is None:
        return board
    squares = list(board)
    squares[hole], squares[to] = squares[to], " "
    return "".join(squares)


def shuffled(board, seed, depth=None):
    """The model's own shuffle, in Python: a Lehmer generator and the same four
    directions, walking from wherever the board already is. Being able to write
    this at all is the difference the port made -- against `srand(time(0))`
    inside a constructor there is nothing to write.

    Returns the board and the seed it left off at, because the model keeps
    shuffling from there."""
    for _ in range(depth if depth is not None else DEPTH):
        seed = (seed * 48271 + 1) % 2147483647
        board = apply(board, ["Up", "Down", "Right", "Left"][(seed // 16) % 4])
    return board, seed


def solve(board, limit=12):
    """Breadth-first. Six scramble moves plus six to drive the hole into the
    corner is at most twelve from home, and this bound settles in a fiftieth of
    a second."""
    seen = {board}
    queue = deque([(board, [])])
    while queue:
        state, path = queue.popleft()
        if state == SOLVED:
            return path
        if len(path) >= limit:
            continue
        for key in ARROWS:
            nxt = apply(state, key)
            if nxt != state and nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, path + [key]))
    return None


def start(check, *args):
    env = dict(os.environ, TERM="xterm-256color")
    app = Pty(node_argv(RUNTIME, "main.js", *args), env, cwd=EXAMPLE)
    app.pump(2.5)
    check("puzzle window drawn", "Puzzle" in app.render(), app.render())
    return app


def stop(check, app):
    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("exit code 0", code == 0, f"exit={code}")


def unseeded(check):
    """The default: five hundred moves from a clock-derived seed, which is what
    the C++ constructor does and the only part of this that cannot be
    predicted."""
    app = start(check)
    screen = app.render()

    board = board_of(screen)
    check("all fifteen tiles and the hole are on the board",
          sorted(board) == sorted(SOLVED), repr(board))
    check("the clock seeded a shuffle", board != SOLVED, repr(board))
    check("the move counter starts at zero after a shuffle", moves_of(screen) == 0,
          repr(screen.split("\n")[ORIGIN[1] + 2]))

    # The checkerboard is keyed on the letter, so eight of the sixteen tiles
    # are in the highlight colour whatever order they happen to be in -- eight
    # letters, three columns each.
    check("tiles are painted in two colours", coloured(app.display()) == 24,
          f"{coloured(app.display())} highlighted cells")

    stop(check, app)


def seeded(check):
    """Named seed, named depth: the board is a pure function of both, so
    everything from here is exact."""
    app = start(check, f"--seed={SEED}", f"--scramble={DEPTH}")

    expected, seed = shuffled(SOLVED, SEED)
    check("the seeded board is the one the model's own shuffle produces",
          board_of(app.render()) == expected,
          f"{board_of(app.render())!r} != {expected!r}")

    # Drive the hole into the top-left corner. Three of each is enough from
    # anywhere, and the ones that would push it off the board are exactly the
    # moves that have to do nothing -- so this covers the legal and the blocked
    # path at once.
    counted = 0
    for key in ["Down"] * 3 + ["Right"] * 3:
        if legal(expected, key) is not None:
            counted += 1
        expected = apply(expected, key)
        app.send(ARROWS[key], settle=0.3)
    app.pump(0.5)

    check("the hole reached the corner", expected.index(" ") == 0, repr(expected))
    check("six keys moved the tiles they should have",
          board_of(app.render()) == expected,
          f"{board_of(app.render())!r} != {expected!r}")
    check("and only the legal ones were counted",
          moves_of(app.render()) == counted,
          f"{moves_of(app.render())} != {counted}")

    answer = solve(expected)
    check("the board is solvable within the search bound", answer is not None,
          repr(expected))
    if answer:
        for key in answer:
            app.send(ARROWS[key], settle=0.35)
        app.pump(0.6)
        check("the puzzle was solved", board_of(app.render()) == SOLVED,
              repr(board_of(app.render())))
        check("and every tile dropped back to one colour",
              coloured(app.display()) == 0,
              f"{coloured(app.display())} still highlighted")

    # A solved puzzle takes any key as "again", as the original does -- and
    # since the model kept the generator, the board it comes back with is
    # predictable too. `scramble` walks on from wherever the board is, which
    # here is the solved one it has just reached.
    again, _ = shuffled(SOLVED, seed)
    app.send(ARROWS["Left"], settle=0.9)
    check("a key on a solved board starts a new game",
          board_of(app.render()) == again and moves_of(app.render()) == 0,
          f"{board_of(app.render())!r} != {again!r}")

    stop(check, app)


def main():
    check = Checks()
    unseeded(check)
    seeded(check)
    return check.report()


if __name__ == "__main__":
    sys.exit(main())
