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
    test/drive_*.py   one pty driver per tool, plus one for the shell
