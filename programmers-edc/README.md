This is a small TUI tool that has little tools that a programmer needs now
and then.

# v1

## RPN Calculator

RPN (reverse polish notation) calculator
integers can be given in decimal, hex, or binary.
integer results can be shown in decimal, hex, or binary
handles exact decimals (base 10)

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

    devbox run predc                    # build and run
    devbox run predc -- hex dump.bin    # ... on a file, straight into the viewer
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

## The command line

    predc                 the desktop, with nothing open
    predc ascii           ... with the ASCII chart open
    predc calc            ... with the RPN calculator open
    predc time            ... with the time zone converter open, at this moment
    predc hex [FILE]      ... with the hex viewer open, on FILE if you name one
    predc --help          what the commands are
    predc --version

A command is a shortcut through the Tools menu and nothing more: the program it
opens is the same program, every other tool is still one menu away, and there is
no batch mode. `predc hex dump.bin` exists because somebody who already knows
which file they want should not have to walk a file dialog to it. A name that
is not a file opens the viewer anyway, with the reason on its message line --
the dump is where you are looking, so that is where the complaint belongs. A
name that is a *directory* opens the file dialog standing in it, which nobody
designed: the command line asks the same question the dialog asks, so it gets
the same answer.

The parsing is `gilramir/gren-argparse`, but not its `Argparse.Program` runner,
which is a `Node.SimpleProgram` and therefore the wrong thing to be when the
successful path is a program that paints. `src/Cli.gren` describes the CLI as a
value and `Main.init` matches on the result, which is the manual shape argparse
documents. What that forced into gren-tvision is `Tui.defineProgramOrExit`: a
`--help` has to print into a pipe or a pager without Turbo Vision ever taking
the terminal, and only `init` can decide that, because the first render is what
takes it. FINDINGS.md has the story.

## Layout

    bin/predc.js      the launcher: resolves main.js against itself, not the cwd
    src/Main.gren     the shell -- menu bar, status line, About, which tools are open
    src/Cli.gren      the command line, as a value: one command per tool
    bin/timezones.js  the IANA database, behind a port pair -- the one thing
                      predc needs that Gren has no answer for
    src/Tool/         one module per tool, each handing back a Tui.Window
    src/Ascii.gren    what ASCII says about a byte, shared by two of the tools
    src/Theme.gren    the three colour schemes, and the inks the tools paint with
    src/Config.gren   the one thing predc remembers between runs
    test/drive_*.py   one pty driver per tool, plus the shell, the themes and the CLI

## The calculator's numbers

Both halves are exact. The stack holds `BigInt` for whole numbers and
`BigDecimal` for the rest, both from `gilramir/gren-bignum`, so
`18446744073709551615 2 /` is `9223372036854775807.5` rather than the nearest
double, and `0.1 0.2 +` is `0.3`.

Division promotes rather than truncating -- `10 2 /` is `5` and stays an
integer, `7 2 /` is `3.5` -- and `%` is there for the truncating answer. The
one answer that cannot be exact is a division that does not terminate, and it
is written with a leading `~`: `1 3 /` is `~0.33333333333333333333`. The mark
is carried by everything computed from it, so `1 3 / 3 *` is
`~0.99999999999999999999` rather than a `1` that would be a lie.

It is twenty *significant* digits and not twenty decimal places, which is the
difference between an answer and a row of zeroes when the quotient is smaller
than `1e-19` -- one over the largest `uint64`, say.

A width is a lens rather than a cast: the stack keeps the exact number, and
`u64` or `i64` decides how it is shown and whether it is marked `ovf` for not
fitting. Nothing here is quietly cut down to size.

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

The viewer holds 16 KB of the file at a time, so a mark dragged across more of
it than that is refused with the number rather than copied with a hole in it.

### When the copy does not reach the rest of the machine

`Copied 16 bytes as hex -- the terminal did not confirm it.` means what it
says, and it is weaker than "the copy failed". There are two routes out of a
terminal program and predc takes whichever is there:

  - **`wl-copy`, `xsel` or `xclip`**, which Turbo Vision tries only when
    `WAYLAND_DISPLAY` or `DISPLAY` says there is a display to talk to. **Over
    ssh there is not**, so on a remote machine this half is skipped whether or
    not the programs are installed -- and rightly, because the clipboard it
    would set is the far machine's.
  - **`OSC 52`**, an escape sequence handed to the terminal, which is
    *written every time* and reported as successful only if the terminal has
    proved it also supports reading the clipboard back. Most terminals do not
    answer that, so the message appears even when the copy worked.

The thing that most often eats it is **tmux**, whose default
`set-clipboard external` ignores an application's `OSC 52` and forwards
nothing. Measured on a tmux 3.4 with an `xterm*` terminal outside it:

    set-clipboard = external   forwarded: no    tmux buffer: none
    set-clipboard = on         forwarded: yes   tmux buffer: set
    set-clipboard = off        forwarded: no    tmux buffer: none

So one line in `~/.tmux.conf`:

    set -g set-clipboard on

and, on the terminal at the other end, whatever it calls permission to write
the clipboard (kitty, foot, WezTerm, iTerm2 and Windows Terminal allow it;
xterm wants `allowWindowOps`; Alacritty has an `osc52` setting). Then the same
yank lands in the clipboard of the machine you are sitting at, which is the
whole point of `OSC 52` and the only route that can work over ssh.

Either way predc keeps the text itself, so `y` here and `p` in another of its
tools always work.

gren-tvision's [`doc/clipboard.md`](../gren-tvision/doc/clipboard.md) is the
long version: every environment, what each terminal calls its permission, and a
one-line test that says whether the terminal or tmux is the one eating it.

## Converting a time

The window is one instant read several ways. Every white box is editable and
they are all the same number seen differently, so typing into any of them moves
every other one: a POSIX timestamp out of a log file, a wall clock in Seoul, or
the hour field in Austin.

    ┌─[■]─ Time converter ─────────────────────────────────────────┐
    │                   YYYY   MM   DD    HH   MM                  │
    │ America/Chicago   2026   09   01    14   32   CDT -05:00     │
    │ Asia/Seoul        2026   09   02    04   32       +09:00     │
    │ ──────────────────────────────────────────────────────────── │
    │ UTC               2026   09   01    19   32       +00:00     │
    │ POSIX             1788291120                                 │
    │                                                              │
    │  Now    Zones...    Live clock                               │
    └──────────────────────────────────────────────────────────────┘

**UTC and POSIX are always there** and are not on the configurable list. The
rule across the middle is what separates the zones you chose from the two you
get whether or not you asked. Everything above it is yours, and
**Tools | Time converter** opens on the zone this machine is in until you say
otherwise -- which predc finds out from `Time.getZoneName`, not from a table.

No seconds, because nobody typing a time wants to. The instant underneath is a
whole POSIX timestamp all the same, so pasting `1788291157` shows `14:32` and
keeps the `:37`, and editing a minute field leaves it where it was. The POSIX
box is the only place seconds are visible and it is never rounded.

### Live clock

**Live clock** (`Alt-L`) turns the window into a wall clock. The title says
`Time converter -- live`, every row follows this machine's own time, and the
fields stop being fields: they are static text while the clock is running, so
there is nothing to type into rather than a field that swallows what you type.
**Stop clock** (`Alt-S`) hands the converter back, with whatever instant the
clock had reached still on the screen and editable again.

`Zones...` still works while it is running, which is the point of it: the list
you are watching is the one choice a clock still has.

The POSIX line counts every second and the clocks change on the minute, which
is exactly what each of them is: seconds are what a POSIX timestamp measures,
and the rows have no seconds column to show. Underneath, the tick is once a
second and the recomputation is once a minute -- a minute-long timer would
count from whenever you pressed the button and could leave the window
fifty-nine seconds stale, and a clock that says 10:31 while it is 10:32 is
simply wrong.

### The two mornings a year that are not times

02:30 does not happen in Chicago on the second Sunday in March, and 01:30
happens twice on the first Sunday in November. A converter that has no opinion
about those is quietly wrong two days a year, so predc has one and says it out
loud:

    2026-03-08 02:30 does not exist in America/Chicago -- read as
    2026-03-08 03:30.

An ambiguous time takes the first of the two -- the one the clock read before
it went back -- and a time that never happened is pushed **forward**, because
forward is the direction the clock moved and an answer earlier than what you
typed is the surprising one. The digits you typed stay in the field you typed
them in; it is every other row that moves.

The same sentence catches the 31st of April, and that is deliberate rather than
lucky: the day field will take 1 to 31 in every month, because how long April
is happens to be a question the IANA database already answers and predc has no
business having a second opinion about.

### Choosing which zones

**Zones...** opens a second window -- not a dialog, because a dialog in
gren-tvision cannot be redrawn while it is open and a filter that only applies
when you press a button is not worth having.

    ┌─[■]─ Time zones ─────────────────────────────────────────────────┐
    │ Find  Asia/seo                          1 of 418                 │
    │                                                                  │
    │ Area             Zone                       Displaying           │
    │  All 418      ▲   Asia/Seoul              ▲  America/Chicago   ▲ │
    │  Africa 52    ▒                           ▓  Asia/Seoul        ▒ │
    │  America 144  ▒                           ▓                    ▒ │
    │  Asia 82      ▒                           ▓                    ▒ │
    │                                                                  │
    │ Space adds or removes; an area types its prefix into Find.       │
    │    Add >>       << Remove      Move Up     Move Down              │
    │                                 Done        Cancel               │
    └──────────────────────────────────────────────────────────────────┘

**An area is a saved search and not a second axis.** Choosing `Asia` types
`Asia/` into Find; typing `seo` after it leaves `Asia/seo`. There is one piece
of state and it is on the screen, so the box always says exactly why you are
not looking at the zone you wanted -- which beats a rule about whether the area
or the filter wins, because that rule would be invisible.

The counts are on the area rows because the two levels help very unevenly:
`America` is 144 names and `Arctic` is one. `All` is a row rather than a mode,
which is also what makes opening the window show all 418 -- Turbo Vision
highlights a list's first entry whether or not you asked it to.

The buttons carry no `Alt` letters, for the same reason the calculator's keypad
does not: `~A~dd` would bind Alt-A and the status line already has that for the
ASCII chart. So the buttons are the mouse's, `Space` on either list is the
keyboard's, Enter is Done and Alt-F3 closes the window.

**Add and Remove act on the row the highlight is on**, in the zone list and the
Displaying list respectively -- wherever you left it, with the arrow keys, a
click or the wheel. **Move Up** and **Move Down** act on the same highlight in
the Displaying list, and the highlight travels with the row, so pressing one
twice moves one zone two places rather than moving two zones one place each.

The order of that list is the order the converter reads in, top to bottom, and
before those two buttons it was the order the zones happened to be added in --
changing it meant removing three zones so as to put them back differently.
`UTC` is not in the list and is always last.

The list is written to `config.json` the moment it changes, and the converter
behind the window shows the row as soon as you add it, which is the answer to
"is that the one I meant". **Cancel** is the price of that: since there is no
draft to throw away, it is an undo, back to the list the converter was showing
when the window opened. **Done** and closing the window both keep what is on
the screen -- a close box that discarded five zones you had just watched appear
would be the worse surprise of the two.

Emptying the list entirely is a choice that sticks: an absent `timezones` key
means predc has never been told and starts at this machine's zone, and an empty
array means you removed them all and get UTC and POSIX alone.

One oddity that belongs to the database rather than to predc: the browsable
names are the canonical ones, and a few of those are the old spellings. Nepal
is `Asia/Katmandu` in the list, though `Asia/Kathmandu` works perfectly if you
put it in the config file by hand.

### Where the arithmetic is

Not in Gren. There is no leap-year rule, no month length and no daylight-saving
logic anywhere in `src/`, because a time zone is not an offset and the only
thing on the machine that knows the difference is the IANA database compiled
into node's `Intl`. `bin/timezones.js` is that half, reached over a second port
pair that `bin/predc.js` subscribes to -- which is exactly what the launcher
existed for.

Every reply carries the whole window rather than one row. One request per
keystroke instead of one per zone, and no moment where the table is half
updated because three answers arrived and two have not.

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
