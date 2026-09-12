# What predc was going to be

This is the original feature list for [predc](../programmers-edc/README.md),
kept as it was written: four rounds of "what would be worth having", in the
order they were asked for. Everything in v1 through v4 is built, and each item
says which section of
[predc's README](../programmers-edc/README.md) describes the thing it turned
into. One item was dropped after it was specified, two were declined before
they were, and the i18n note below was never built and never formally dropped.

The point of keeping it is that the difference between the ask and the result is
where the interesting part is: a "small monthly calendar" became a view that
also answers which work week you are in, and a "watcher/alarm/timer" turned out
to be a thing the system already had three of.

# v1

## RPN Calculator

RPN (reverse polish notation) calculator
integers can be given in decimal, hex, or binary.
integer results can be shown in decimal, hex, or binary
handles exact decimals (base 10)

**Done** -- see [The calculator's numbers][calc].

## Hex dump viewer

Not a hex editor; just a viewer, but one that the user can
highlight ranges for being able to distinguish different ranges
of bytes during investigation.
User can paste bytes/text, or read af file.
Contents are shown in class hex dump format, with offsets, hex, and printable
ASCII rendering.
User may highlight sections a different color; useful if they are studying the
hex dump and need to highlight

**Done** -- see [Highlighting a hex dump][hex].

## Time conversion
enter time as posix timestamp, or different rfc formats
convert posix to rfc
show same times in multiple timezones
user can choose which timezones to always display by default
options are save to a config file
(e.g., myself I need to use Austin, Seoul, San Jose (California), and Bangalore
timezones)

**Done** -- see [Converting a time][time].

## ASCII chart

exactly what it says, ASCII only. control characters should also have their
proper ASCII name.

**Done** -- see [The ASCII chart has two of it][ascii], which is v4's second
form of it.

# i8n support
Menus and dialogues support i18n. My default is English. I need to supply
Korean too.

**Not built.** Nothing in predc is translated, and nothing about it was decided
either way.

# v2

## Watcher/Alarm/Timer

**Dropped, 2026-09-05.** Run a command every N seconds, or at time T, and run
another when it exits with some value. Not wanted after all; `cron`, `systemd`
timers and `watch` all do it, and none of the reasons the other tools exist --
one window, no shelling out, a thing you can look at while you work -- were
true of this one.

## Unicode encodings

Decodes bytes (or, string representation of hex bytes)
as utf-8 or utf-16

**Done** -- see [Reading bytes as Unicode][unicode].


## Calender view

I want to be able to see a small monthly calendar, so I can see
what days of the week each date falls on.
It should also show the work week number for that month/year.

**Done** -- see [A month, and which week it is][month].



# v3

Three small things, none of them a tool's worth on its own and all of them
things a person reaches for weekly.

## Finding bytes in a dump

Search the dump for text or for hex digits, and again for the next one.

**Done** -- see [Finding bytes][find].

## Encoding and decoding

base64, percent-encoding, C string escapes, HTML entities, both directions.

**Done** -- see [Encoding and decoding][encode].

## Random values

A v4 UUID, or N random bytes as hex or base64.

**Done** -- see [Random values][random]. An integer spelling was added later, on
the same bytes.

## Environment variables

Every variable predc's own process has, one per line, with a search box and a
case-sensitivity toggle.

**Done** -- see [Environment variables][env].

**Not wanted:** hashes (md5/sha) and a `chmod` bit calculator, both suggested
and both declined.


# v4

## The ASCII chart's long form

The concise grid, and a second mode: the long list `man ascii` prints, one code
per line with dec/hex/oct and a name for everything unprintable. A toggle
between them, and the list as tall as the screen allows.

**Done** -- see [The ASCII chart has two of it][ascii].

## Notes

Many independent free-form notes, each with a name: a list down the left and an
editor pane beside it. A very small OneNote, and no more than that -- no
folders, no tags, no formatting, no search across notes.

Plus a key that reformats the paragraph the caret is in to 80 columns,
regardless of the size of the window.

**Done** -- see [Notes][notes].

[calc]: ../programmers-edc/README.md#the-calculators-numbers
[hex]: ../programmers-edc/README.md#highlighting-a-hex-dump
[time]: ../programmers-edc/README.md#converting-a-time
[ascii]: ../programmers-edc/README.md#the-ascii-chart-has-two-of-it
[unicode]: ../programmers-edc/README.md#reading-bytes-as-unicode
[month]: ../programmers-edc/README.md#a-month-and-which-week-it-is
[find]: ../programmers-edc/README.md#finding-bytes
[encode]: ../programmers-edc/README.md#encoding-and-decoding
[random]: ../programmers-edc/README.md#random-values
[env]: ../programmers-edc/README.md#environment-variables
[notes]: ../programmers-edc/README.md#notes
