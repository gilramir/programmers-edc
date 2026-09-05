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

**Done** -- see "Reading bytes as Unicode" below.


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
    predc unicode         ... with the Unicode decoder open
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
    src/Help.gren     the one window that is not a tool: Help | Copying and
                      pasting, which measures this session and explains it
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

**Numbers go in and out of it.** `v` pastes into what you are typing and `y`
copies the top of the stack -- which is the point of exact 64-bit arithmetic,
since the numbers worth being exact about are the ones nobody wants to retype.

A pasted number is a *typed* number: it lands in the entry rather than on the
stack, `Enter` still pushes it, and you can go on typing after it. It is read
in the base showing and refused otherwise, so `0xFF` pasted into a decimal
calculator is an error with a sentence and not 255 -- the same refusal to guess
that gives the hex viewer separate `p` and `P`. The one thing it forgives is
predc's own prefix: `y` in hex copies `0x4996_02d2`, and pasting that back
works, because the `0x` of the base you are already in is dropped.

For any level other than the top, **Calc | Copy** lists the stack with each
value written beside its number, so the menu showing what will be copied is the
menu you choose from -- and **All of it** takes the lot, one to a line, deepest
first. The keys are on the display's bottom line, which now reads
`Tab base, w width, y copy, v paste` and spends all thirty-four columns of it.

**What it says after a copy is deliberately conditional.** With a terminal that
confirms taking the text you get `Copied to the clipboard.`; with one that does
not you get `Copied; F1 if it does not paste.` — because the `OSC 52` goes out
either way and predc cannot know whether anything downstream took it. Inside
tmux the default `set-clipboard external` swallows it and answers nothing, so
the second sentence is the *normal* one there even when the copy worked. It is
not a failure, and it does not say it is.

`v` rather than `p`, which is the hex viewer's paste key: `p` here has been
Drop since the day the calculator was written, and a key that throws away the
top of your stack when you meant to paste is the worst possible place to be
consistent. Neither `y` nor `v` is a hex digit, which is what makes them free.

## Highlighting a hex dump

`v` marks from the cursor, `V` marks whole rows, and one of `1`-`6` paints what
is marked; `Esc` drops the mark and `d` takes the paint off the range under the
cursor. While a mark is out, the line under the dump carries the six keys
drawn in the colours they paint, because `1-6` is a range of numbers and not an
answer to which one is yellow. Everything that moves the cursor -- arrows, `PgDn`, `Ctrl-End`, a click
on either column, **Bytes | Go to offset** -- moves the far end of the mark,
because the far end *is* the cursor. **Bytes | Highlight** is the same six
things on a menu, for finding them the first time.

**Dragging marks too**, and it is the same mark: press on a byte, pull, and
what the pointer crosses is marked, ready for a colour. A plain click still
just moves the cursor -- the mark begins on the first cell the pointer *moves*
to, anchored where the press landed, so nothing was taken away from clicking.
Dragging off the window is harmless and does not scroll: a terminal reports
motion while the pointer is moving and not while it is held still, so mark to
the edge, `PgDn`, and go on marking. The mark is still out and the cursor is
still its far end.

The keys are vim's two visual modes rather than `Shift`-arrows or vim's third
one, and that is a fact about terminals rather than a preference:
`Ctrl-Shift-V` is the paste binding of every terminal emulator worth naming and
never reaches a program at all. FINDINGS has the measurements.

Ranges are offsets into the file that is open, so opening another one drops
them, and closing the window drops the whole tool the way it drops every other
one here. Where two overlap the newer one shows; taking it off puts the older
one back.

## The status line says how to paste

The bottom row is `Alt-X Exit`, `Alt-F3 Close`, and a sentence about pasting.
No tools, which is a change the fifth one forced: every tool that went on the
bar had to come off again when the next arrived, and the Unicode decoder never
fitted at all, so a bar listing four of five was already wrong about what predc
has. All five carry their `Alt` key on the **Tools** menu and every one still
works from inside a tool, because a menu bar is offered each key before the
window under it -- the same rule that lets `Alt-F3` out of a focused canvas.

What the room bought is the question predc is asked most, on the screen all the
time instead of behind a key somebody has to know to press. **The sentence
knows where it is running**, because the answer genuinely differs:

| | |
|---|---|
| inside tmux | `Paste  Ctrl-Shift-V, Shift-Ins, tmux prefix ]   F1` |
| inside screen | `Paste  Ctrl-Shift-V, Shift-Ins, screen Ctrl-a ]   F1` |
| with a display | `Paste  Ctrl-Shift-V, Shift-Ins, or p   F1 why` |
| over bare ssh | `Paste  Ctrl-Shift-V or Shift-Ins, not p   F1 why` |

**And it knows how much room it has**, which is the other half and the one that
is easy to miss. A terminal's width changes while the program is running, and
`TStatusLine` draws an entry only if it fits and says nothing when it does not
-- so a sentence written for eighty columns does not get truncated at sixty, it
*disappears*, on exactly the terminal where somebody most needs it. The bar is
therefore a ladder: the longest version that fits is the one drawn, measured
rather than counted, down through `Paste  Shift-Ins   F1` and `F1 paste` to
nothing at all. Even the last rung keeps `F1` working, because a status entry
with no text costs no columns and is still offered every keystroke.

`F1` opens [Copying and pasting](#pasting), which is the page-long version.

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

### Pasting a dump back in

**Bytes | Paste a dump** is the third of them, and it is the one that takes
what `P` refuses: `xxd`, `xxd -g1`, `hexdump -C`, `od -A x -t x1z`, and what
**Copy as a dump** above puts on the clipboard. A dump out of a bug report goes
straight back to being bytes.

It is the only entry on that menu with no key beside it, deliberately. `p` and
`P` are how this thing gets something to look at; pasting a dump back is
something done once, with a bug report, which is a thing to find on a menu
rather than to have in the fingers.

### Typing them instead

**Bytes | Type bytes...** is the fourth way, and the only one that never goes
near the clipboard: a field, a radio saying whether it holds text or hex
digits, and the same two readings `p` and `P` use -- the same refusals too, in
the same words, because it is the same two functions.

It has no key beside it and it is not a convenience. Over ssh the three above
cannot work at all, and "Pasting over ssh" below is the whole of why. A
terminal paste lands in that field, which is the point of it.

There are two readings and not three: a dump is several lines and an input line
is one, so **Paste a dump** is not offered here. A dump still arrives through
the clipboard, or as a file.

**A dump says how wide it is, and it says it in the offset column.** The gap
between one line's offset and the next is exactly how many bytes that line
carried, so nothing has to work out where the hex stops and the printable
column starts -- take that many pairs and stop. Which is the whole difficulty,
because this is a real line of a real dump:

    00000000  62 65 65 66 62 65 65 66  62 65 65 66 62 65 65 66  beefbeefbeefbeef

and every rule that reads it by looking at it reads twenty-four bytes off a row
of sixteen. A rule about two spaces does no better -- the dumps above put a
double space in the middle of the hex field.

Two things follow, and both are the price of not guessing:

  - **A dump of one line is refused.** One offset is not two, so there is
    nothing to subtract -- and one line is exactly the case where a printable
    column cannot be told from more hex.
  - **A short last line is read only as far as the full lines' hex reached**,
    or as far as its own hex runs, whichever stops first. The first of those is
    what `xxd` and `hexdump` pad for; the second is for `od`, which does not
    pad but fences its printable column in `>` and `<`.

A `*` is read rather than refused. `hexdump` writes one for a run of identical
rows, and the offsets either side of it say exactly how many rows it stands
for, so expanding it is reading the format and not guessing at it -- any dump
of a file with a zeroed region has one. A dump that is *nothing but* a `*` says
so instead, because then nothing is left that says how wide a row was.

The bytes start at zero whatever the dump's own offsets were, and the message
line says what they were:

    Read 256 bytes, from a dump of 00001000-000010FF.

Anything that is not one of these -- a hole between two offsets, offsets of
different widths, bare hex with no offsets at all -- is refused and named,
which is the same discipline as `P`'s and for the same reason.

## Copying

`y` copies what is marked as hex -- `00 01 02 03` -- and **Bytes | Copy as a
dump** copies the same range as the rows on the screen, offsets and printable
column included. With nothing marked, both take the highlight the cursor is
sitting in, which is the other reason to paint one.

The viewer holds 16 KB of the file at a time, and a mark can be the whole file
-- `v`, `Ctrl-End` -- so a copy larger than that is read from the file for the
purpose. There is no ceiling on it. What there is, past a megabyte, is a
question:

    That is 4201984 bytes -- about 17 MB of text.
    Copy it?

Two numbers because they are two different sizes, and the second is the one
nobody has in their head: a byte is three characters as hex and rather more
than four as a dump. Under the megabyte nothing is asked, which is why the
number does not have to be defensible the way a refusal's would -- being asked
costs one keypress, so it can be wrong either way and nobody is stopped from
doing anything.

**No is not a refusal**: the mark is still out afterwards, so the answer to
"that is more than I meant" is to shrink it rather than to make it again.

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

### The window that explains all this

**Help | Copying and pasting** (`F1`) is the whole of the section below, in the
program, for the person who is not going to read a README. It opens on *this*
session rather than on the background:

    THIS SESSION

      Over ssh, inside tmux.   TERM=screen-256color
      No DISPLAY, no WAYLAND_DISPLAY: xclip, xsel and wl-copy are not
      tried at all -- the display they would talk to is the far end's.

      Measured: nothing outside this program answered a clipboard
      read, so p and P cannot reach your clipboard here.
      There is no setting that changes this. Paste with the terminal
      instead -- the next section is how.

**Measured, not guessed.** The environment settles most of it, but whether a
*terminal* will hand its clipboard back is in no variable -- and it is the fact
that decides whether `p` can ever work. So the window asks for the clipboard
when it opens and reads `fromSystem` off the answer. It asks again on each
opening rather than caching, because `set-clipboard` and kitty's
`clipboard_control` are live settings and a window somebody opened *because*
they just changed one should not be answering out of a cache.

**It is as tall as the desktop will let it be.** The text is a hundred-odd
lines, so on any terminal anybody has it is the screen that decides how much of
it is visible at once -- a forty-row pane shows thirty-nine rows of it, not the
seventeen that fit an eighty-by-twenty-four terminal. It follows the terminal
as that changes, and it is still `Tui.resizeHeight`, so dragging it stays
possible and stays put.

What to press comes first and why comes second, which is the opposite of how
this subject is usually written down. Underneath that are the two mechanisms
both called pasting, what the tmux line does and does not fix, a row per
environment, and the six stores unix calls a clipboard.

### Pasting over ssh

That line is about **copying out**. Reading the clipboard *in* is a different
problem with no configuration behind it, and on a remote machine `p` and `P`
cannot work at all:

  - `wl-paste`, `xsel` and `xclip` are skipped before they are looked for,
    because Turbo Vision checks `WAYLAND_DISPLAY` and `DISPLAY` first and over
    ssh neither is set. That is right rather than unfortunate -- the clipboard
    they would read is the far machine's.
  - The `OSC 52` read query **is not even written** unless the terminal has
    already proved it will answer one, which it does by a kitty capability
    reply, an unsolicited `OSC 52`, or xterm's `allowWindowOps`. tmux sends
    none of those and forwards none of them.

So the request comes back with predc's own last copy -- nothing, usually --
and there is no setting that changes it. Reading is the direction with a
security question attached: a program that can read your clipboard can read
the password you put there a minute ago, and terminals that accept a write
refuse a read on purpose.

When that happens predc says **the terminal will not hand the clipboard over**
rather than that the clipboard is empty, because those send you to different
places and only one of them helps.

One thing about it will look like it is working and is not: what comes back
when nothing outside answered is *this program's own last copy*, which is what
makes a copy in one predc window and a paste in another work on a machine with
no clipboard at all. So over ssh `p` does nothing until you press `y`, and
pastes your own code points back for ever after. It is not reaching your
desktop and never will.

**What always works is typing, and a terminal paste is typing.** `Ctrl-Shift-V`,
`Shift-Insert` and tmux's `prefix ]` all send keystrokes down the pty, so both
tools that take bytes have somewhere for them to land: the field along the top
of the Unicode window, and **Bytes | Type bytes...** in the hex viewer. Two
different shapes because the two tools differ in where their bytes normally
come from -- the decoder has no source but a paste, while the viewer has files,
and a live field there would let one stray keystroke take away the open file
and every highlight on it.

A middle click is the exception and it will surprise you: predc turns on mouse
reporting, so the terminal hands the click to the program rather than pasting,
and on a window frame it *moves the window*. `Shift`+middle-click goes round
that and pastes.

### And predc's own clipboard, between its own windows

`Shift-Del`, `Ctrl-Ins` and `Shift-Ins` cut, copy and paste in every field here
-- the Unicode decoder's, **Type bytes**, **Go to offset**, the file dialog's
name box. They are on the status line with no text beside them, which costs no
columns and is the only way they can exist: Turbo Vision binds no keys to cut,
copy and paste itself, so a program that names none has fields that cannot do
either and nothing says so.

What that buys is a round trip with no terminal in it at all. `y` in the
Unicode decoder puts `U+0048 U+00E9` on predc's clipboard; `Shift-Ins` in the
hex viewer's **Type bytes** field takes them straight back out. That works on a
machine with no clipboard of any kind, which is what a remote host is, and it
did not work until the binding stopped letting Turbo Vision's own views keep a
second clipboard nobody could see -- `gren-tvision/doc/clipboard.md` has the
whole of that, and it is the best explanation of this subject in the repo.

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
does not: `~A~dd` would bind Alt-A and the ASCII chart already has it, on the
Tools menu. So the buttons are the mouse's, `Space` on either list is the
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

The list is written to `config.toml` the moment it changes, and the converter
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

## Reading bytes as Unicode

**Tools | Unicode decoder** (`Alt-U`) was the tool that would not fit on the
status line, and it is the reason none of them are there now: a bar listing
four tools out of five is a bar that has stopped saying what predc has. Every
tool's `Alt` key is on its menu entry, which works from anywhere for the same
reason `Alt-F3` does -- a menu bar is offered every key before the window under
it gets one.

Give it bytes and it shows one character to a row: where it starts, the bytes
it was made of, its code point, the character itself, and a word about what it
is. `8` reads them as UTF-8, `l` and `b` as UTF-16 in either order, and `y`
puts the code points on the clipboard as `U+0048 U+00E9 U+1F600`, which is the
one thing here that nothing else on the machine will give you.

**The field along the top is where the bytes come from**, and it has the caret
when the window opens because this tool starts with nothing to look at. Type
into it and the rows follow every keystroke; the radio beside it says whether
what is in there is text or hex digits, and changing it re-reads the same
field the other way. `C0 80` typed as hex is the overlong; the same six
characters as text are six ASCII letters. Nothing sniffs.

    Bytes  C0 80 ED A0 80                          ( ) Text  (*) Hex

    offset    bytes         code     char what it is
    00000000  C0 80         --            overlong: 2 bytes for U+0000
    00000002  ED A0 80      --            U+D800 is a surrogate, not UTF-8

A lone digit at the end is a byte you are halfway through typing rather than a
mistake: it is left out of the rows and said on the line below. A stray
character is refused at once, because `z` is not halfway through anything.

`p` and `P` still paste text and hex from the clipboard, and the hex viewer's
two commands still reach here -- but the field is the one route that works
everywhere, and "Pasting over ssh" below is why that sentence had to be
written. The single-letter commands go to the field until `Tab` reaches the
rows; every one of them is on the **Encoding** menu, which is what makes that
survivable. `Alt-B` goes back to the field from anywhere in the window.

Nothing is guessed. UTF-16 is two commands rather than one that looks at the
first two bytes, because a byte order mark is a choice somebody made and not a
fact about the bytes -- half the UTF-16 in the world has none. A `FF FE` that
turns up is named as what it is.

### The point of it is the rows that are wrong

    00000000  48            U+0048   H    ASCII
    00000001  C3 A9         U+00E9   é    Latin-1 supplement
    00000003  C0 80         --            overlong: 2 bytes for U+0000
    00000005  ED A0 80      --            U+D800 is a surrogate, not UTF-8
    00000008  F0 9F 98 80   U+1F600  😀    plane 1, outside the BMP
    0000000C  E2 82         --            E2 starts 3 bytes and only 2 are left

Every decoder on the machine will read those bytes for you. Almost none will
tell you that `C0 80` is an overlong encoding of `U+0000` rather than a null --
the oldest way there is past a filter looking for a literal zero byte -- or
that `ED A0 80` is a surrogate, which is how a half-converted UTF-16 string
gives itself away, or *which* of two bytes was the one that ran out.
`TextDecoder`, in node and in every browser, answers all of those with `U+FFFD`
and moves on. That is right for a program and useless for a person trying to
find out why a file will not load.

So the decoders are written out by hand in `src/Tool/Unicode.gren`, and what
they hand back is either a code point or a sentence. The line under the rows
counts both: `19 characters, 3 of them broken` is an answer, where `19
characters` is arithmetic.

Two Gren bugs are relevant and both are worked around rather than waited on.
`String.Parser.Advanced` hands its predicate the leading surrogate of a non-BMP
character instead of the character ([core#138][138]), so there is no parser in
here -- the decoders walk an `Array Int`. And the literal `\u{FFFF}` compiles
to two code units ([compiler#384][384]); only that one code point is affected,
`U+FFFD` is fine, and there is no such literal in the file.

[138]: https://github.com/gren-lang/core/issues/138
[384]: https://github.com/gren-lang/compiler/issues/384

### What it made the test harness learn

`harness.py`'s little terminal emulator advanced exactly one column per
character, which was fine for fifteen examples of boxes and ASCII and is wrong
the moment a decoder shows you `한`. It counts East Asian Wide and Fullwidth as
two columns now, and **Ambiguous as one** -- which is not a detail, because
`é`, `│`, `·` and `▲` are all Ambiguous and every box Turbo Vision draws is
made of them.

That was also the thing standing in front of testing anything translated, so
i18n is one step less expensive than it was.

## Colors

Three schemes, on **Options | Colors**: Borland, Midnight and Gren. The choice is
written to `$XDG_CONFIG_HOME/predc/config.toml` (or `~/.config/predc/`) the
moment it is made, and read back before the first frame of the next run.

A scheme is two things, and `src/Theme.gren` is where the split is explained.
`Tui.Theme` is everything gren-tvision draws -- the desktop, the menu bar, the
frames, the dialogs -- and can be 24-bit. `Theme.Inks` is what the tools' own
canvases paint with, which a theme cannot reach and which is one of the sixteen
colours a terminal has always had. Borland's is built out of those sixteen, so
it follows whatever the terminal is set to; Midnight and Gren name their colours
exactly, because "whatever this terminal calls black" is not a foundation for a
dark scheme.

## The config file

`$XDG_CONFIG_HOME/predc/config.toml`, or `~/.config/predc/config.toml`. It has
two keys in it, and predc writes it the moment either one changes rather than
at exit -- a setting that survives only a tidy close is a setting that gets
lost, and predc is a program people close with Alt-X.

```toml
# Which colour scheme predc opens in: borland, midnight, or gren.
theme = "midnight"

# The time zones the time converter shows, in the order it
# shows them. Delete the key to go back to this machine's own
# zone; an empty list shows UTC and POSIX alone.
timezones = ["America/Chicago", "Asia/Seoul"]
```

It was JSON and is now TOML, for the comments -- both the ones above, which
predc writes when it invents a key, and the ones you write yourself. Which
turns out to be a claim about the *writing* rather than the format: a program
that serialises its model over the file deletes every word you put in it the
next time you pick a colour.

So predc does not serialise. `Config.save` reads the file back off the disk,
edits the document it parsed, and writes that out --
[gren-toml](https://github.com/gilramir/gren-toml) keeps the whitespace and the
comments as text in its AST, so everything the edit did not touch comes back
byte for byte. Your comments stay where you put them, a key predc has never
heard of survives, and an edit you made in `$EDITOR` while predc was running is
not written over.

Setting a value that has not changed does nothing at all, which matters most
for the key predc is *not* changing. Setting a value replaces the whitespace
inside it, so a list you spread over four lines with a note against each zone:

```toml
timezones = [
  "Asia/Seoul",     # them
  "America/Chicago" # me
]
```

would otherwise come back as one line -- on the key you had not touched,
because you picked a colour.

The one thing it will not do is repair a file. A TOML syntax error means predc
starts in the defaults and then leaves the file completely alone: a typo is
worth less than the rest of the page it is on, and the setting you lost comes
back the next time you choose it.
