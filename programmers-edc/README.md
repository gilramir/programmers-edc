This is a small TUI tool that has little tools that a programmer needs now
and then.

# v1

## RPN Calculator

RPN (reverse polish notation) calculator
integers can be given in decimal, hex, or binary.
integer results can be shown in decimal, hex, or binary
handles floating point (base 10)

## Hex dump viewer

Not a hex editor; just a viewer, but one that the user can
highlight ranges for being able to distinguish different ranges
of bytes during investigation.
User can paste bytes/text, or read af file.
Contents are shown in class hex dump format, with offsets, hex, and printable
ASCII rendering.
User may highlight sections a different color; useful if they are studying the
hex dump and need to highlight

## Time conversion
enter time as posix timestamp, or different rfc formats
convert posix to rfc
show same times in multiple timezones
user can choose which timezones to always display by default
options are save to a config file
(e.g., myself I need to use Austin, Seoul, San Jose (California), and Bangalore
timezones)

## ASCII chart

exactly what it says, ASCII only. control characters should also have their
proper ASCII name.

# i8n support
Menus and dialogues support i18n. My default is English. I need to supply
Korean too.

# v2

## Watcher/Alarm/Timer
Run some command every N seconds, and with it exits with some value, run
another command. (like, email me)
Or do that command at time T, or after T seconds.


## Unicode encodings

Decodes bytes (or, string representation of hex bytes)
as utf-8 or utf-16


## Calender view

I want to be able to see a small monthly calendar, so I can see
what days of the week each date falls on.
It should also show the work week number for that month/year.



# Building and running

    devbox run predc          # build and run
    devbox run -- python3 tools/run_tests.py shell   # its pty tests

predc is written as an ordinary, independent application: it depends on
gren-tvision the way anybody else's program would, through `gren.json`, and it
has its own launcher rather than borrowing the package's `gren-tui` bin.

Two things about it are temporary, and both are temporary for the same reason
-- nothing is published yet:

  - `gren.json` names the package as `"local:../gren-tvision"`, and
    `package.json` names the runtime as `"file:../gren-tvision-runtime"`. Those
    become version ranges the day the two are released.
  - the pty tests borrow `harness.py` and the parallel runner from the repo
    predc happens to sit in, because there is not yet a distributable way for a
    consumer to drive a Turbo Vision program through a pty.

## Layout

    bin/predc.js      the launcher: resolves main.js against itself, not the cwd
    src/Main.gren     the shell -- menu bar, status line, About, which tools are open
    src/Tool/         one module per tool, each handing back a Tui.Window
    src/Ascii.gren    what ASCII says about a byte, shared by two of the tools
    src/Theme.gren    the three colour schemes, and the inks the tools paint with
    src/Config.gren   the one thing predc remembers between runs
    test/drive_*.py   one pty driver per tool, plus the shell and the themes

## Highlighting a hex dump

`v` marks from the cursor, `V` marks whole rows, and one of `1`-`6` paints what
is marked; `Esc` drops the mark and `d` takes the paint off the range under the
cursor. While a mark is out, the line under the dump carries the six keys
drawn in the colours they paint, because `1-6` is a range of numbers and not an
answer to which one is yellow. Everything that moves the cursor -- arrows, `PgDn`, `Ctrl-End`, a click
on either column, **Bytes | Go to offset** -- moves the far end of the mark,
because the far end *is* the cursor. **Bytes | Highlight** is the same six
things on a menu, for finding them the first time.

The keys are vim's two visual modes rather than `Shift`-arrows or vim's third
one, and that is a fact about terminals rather than a preference:
`Ctrl-Shift-V` is the paste binding of every terminal emulator worth naming and
never reaches a program at all. FINDINGS has the measurements.

Ranges are offsets into the file that is open, so opening another one drops
them, and closing the window drops the whole tool the way it drops every other
one here. Where two overlap the newer one shows; taking it off puts the older
one back.

## Pasting

`p` fills the window from the clipboard as text -- the bytes the string is made
of -- and `P` reads the same clipboard as *hex digits*, so `de ad be ef` and
`0x48,0x69` and a line of `48656C6C6F` all become the bytes they spell. Both
are on **Bytes**, and both work with nothing open, because pasting is one of
the two ways of giving this thing something to look at.

Two commands rather than one that decides for itself, and that is deliberate:
`beef`, `cafe`, `decade` and `0123456789` are all words somebody might paste
and all valid hex. A program that guesses is a program that is sometimes
silently wrong about what it is showing you, which is the one thing a hex dump
must never be.

For the same reason `P` refuses anything that is not hex rather than keeping
the hex and dropping the rest -- so a whole `xxd` dump, offsets and printable
column included, is refused with the character that stopped it rather than read
as data in three places at once.

## Copying

`y` copies what is marked as hex -- `00 01 02 03` -- and **Bytes | Copy as a
dump** copies the same range as the rows on the screen, offsets and printable
column included. With nothing marked, both take the highlight the cursor is
sitting in, which is the other reason to paint one.

Two things it will tell you rather than guess about. The system clipboard is
`wl-copy`, `xsel`, `xclip` or the terminal itself, and when none of them will
take the text predc keeps it anyway and says so -- copy and paste between two
of predc's own tools still work. And the viewer holds 16 KB of the file at a
time, so a mark dragged across more of it than that is refused with the number,
rather than copied with a hole in it.

## Colors

Three schemes, on **Tools | Colors**: Borland, Dark and Gren. The choice is
written to `$XDG_CONFIG_HOME/predc/config.json` (or `~/.config/predc/`) the
moment it is made, and read back before the first frame of the next run.

A scheme is two things, and `src/Theme.gren` is where the split is explained.
`Tui.Theme` is everything gren-tvision draws -- the desktop, the menu bar, the
frames, the dialogs -- and can be 24-bit. `Theme.Inks` is what the tools' own
canvases paint with, which a theme cannot reach and which is one of the sixteen
colours a terminal has always had. Borland's is built out of those sixteen, so
it follows whatever the terminal is set to; Dark and Gren name their colours
exactly, because "whatever this terminal calls black" is not a foundation for a
dark scheme.
