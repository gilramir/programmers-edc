# The clipboard, from a terminal program

The short version, for somebody whose copy did not arrive:

> A terminal program cannot reach the clipboard by itself. It either runs a
> helper program (`wl-copy`, `xsel`, `xclip`) that talks to a **display**, or
> it hands the text to **the terminal** as an escape sequence and hopes the
> terminal is willing. Over ssh only the second can work, and the usual thing
> standing in the way of it is tmux, which by default swallows it.
> `set -g set-clipboard on` is the fix.

The rest of this explains why, because the failure is silent at every layer and
the boolean you get back means less than it looks like.

## What "the clipboard" even is

There is no such thing as *the* clipboard on unix. There are:

  - **X11 selections.** `CLIPBOARD` is what Ctrl-C and Ctrl-V use; `PRIMARY` is
    what a mouse selection fills and the middle button pastes; there are also
    ancient *cut buffers*. They are not the same store, and a program that
    writes one has not written the others.
  - **The Wayland clipboard**, which is a different protocol again, reached
    through the compositor.
  - **The terminal's idea of the clipboard**, which is whatever the terminal
    emulator does when a program asks it. This is the only one that exists
    inside an ssh session, because it belongs to the machine the *human* is
    sitting at rather than the machine the program is running on.

All three require a *connection to a display*, except the last. That single
fact is the whole story of the paragraphs below.

## What Turbo Vision does, in order

`THardwareInfo::setClipboardText` is two attempts
(`source/platform/unixcon.cpp`):

```cpp
bool UnixConsoleAdapter::setClipboardText(TStringView text) noexcept
{
    if (UnixClipboard::setClipboardText(text))
        return true;
    if (TermIO::setClipboardText(con, text, inputState))
        return true;
    ...
}
```

### 1. A helper program, if there is a display

`UnixClipboard` tries `wl-copy`, then `xsel`, then `xclip` (and `pbcopy` on
macOS), by spawning it and writing the text to its stdin. Each is guarded:

```cpp
{wlCopyArgv,   "WAYLAND_DISPLAY"},
{xselCopyArgv, "DISPLAY"},
{xclipCopyArgv, "DISPLAY"},
```

```cpp
static bool commandIsAvailable(const Command &cmd)
{
    return (!cmd.requiredEnv || !getEnv<TStringView>(cmd.requiredEnv).empty())
        && executable_exists(cmd.argv[0]);
}
```

**The environment variable is checked before the executable.** With no
`DISPLAY` and no `WAYLAND_DISPLAY` this whole half is skipped, however many of
those programs are installed. That is not a bug: over ssh the display that
`xclip` would talk to is the *far* machine's, and setting a clipboard nobody is
sitting in front of is worse than doing nothing.

So: this route works when a program runs in a terminal on the same machine as
the user's desktop session, and never otherwise.

### 2. The terminal, with `OSC 52`

Failing that, Turbo Vision writes an escape sequence carrying the text,
base64'd, straight to the terminal:

    ESC ] 52 ; ; <base64 of the text> BEL

The terminal is then supposed to put it on the clipboard of the machine *it* is
running on. This is the only mechanism that can cross an ssh connection, and it
is what you are relying on whenever you copy inside a remote editor.

Two things about it are worth knowing, and one of them surprises everybody.

**The sequence is always written, even when the function returns `false`.**
From `source/platform/termio.cpp`, with Turbo Vision's own comment:

```cpp
con.write(buf, prefix.size() + b64.size() + suffix.size());
// Return false when there is no full OSC 52 support, even though we always
// make the request. This way, we can still use the internal clipboard.
return state.hasFullOsc52;
```

**`hasFullOsc52` is about *reading*, not writing.** It is set only when the
terminal has proved it will hand the clipboard *back*: a kitty capability
reply, an answer to an `OSC 52` query, or xterm reporting `allowWindowOps` in
an `OSC 60`. Almost no terminal volunteers any of those, and several that
happily accept a write refuse a read on purpose -- a program that can read your
clipboard can read the password you copied into it a minute ago.

The consequence is the one that costs people afternoons:

> **`Copied.toSystem == False` means "nothing confirmed taking it", not
> "nothing took it".** The bytes went out. Whether they landed is between the
> terminal and whatever sits between you and it.

A program that prints a sentence about this on a status line should say the
terminal did not confirm, not that the copy failed. `programmers-edc` says
`the terminal did not confirm it`, and it is the model to copy.

## Reading is a different problem

`Tui.readClipboard` is a request answered later by a `ClipboardText` event
rather than a function that returns a string, and that shape is forced:

  - the helper-program route runs a subprocess and waits for its output;
  - the terminal route sends `ESC ] 52 ; ; ? BEL` and the answer comes back
    **through the input stream**, arriving like a keystroke, several events
    later.

`fromSystem = False` on the event means what came back is this program's own
last copy, because nothing outside answered. Reading fails far more often than
writing does, and for a good reason: it is the direction with a security
question attached.

`TClipboard`, Turbo Vision's own class, is deliberately not used by this
binding -- its `requestText` feeds the answer to `TEventQueue::setPasteText`,
i.e. as *keystrokes at the focused view*, which is useless to a model that
wants the bytes.

## What actually happens in each environment

| Where you are | `wl-copy`/`xsel`/`xclip` | `OSC 52` | What to do |
| --- | --- | --- | --- |
| Local X11 session | works | not needed | nothing |
| Local Wayland session | works (`wl-copy`) | not needed | nothing |
| ssh, no tmux | skipped: no `DISPLAY` | the only route | allow `OSC 52` in your terminal |
| ssh, inside tmux | skipped | swallowed by default | `set -g set-clipboard on` |
| Local, inside tmux, no display vars | skipped | swallowed by default | as above |
| Linux virtual console | skipped | nothing to receive it | there is no clipboard to reach |

## tmux

tmux is between the program and the terminal, so it decides whether the
sequence gets through. Its option is `set-clipboard`, and its default is
`external`, whose manual page entry can honestly be read both ways:

> If set to `on`, tmux will both accept the escape sequence to create a buffer
> and attempt to set the terminal clipboard. If set to `external`, tmux will
> attempt to set the terminal clipboard but ignore attempts by applications to
> set tmux buffers.

Measured, on tmux 3.4, with an application inside a pane writing exactly the
sequence Turbo Vision writes and an `xterm*` terminal outside:

    set-clipboard = external   forwarded to the outer terminal: no    tmux buffer: none
    set-clipboard = on         forwarded to the outer terminal: yes   tmux buffer: set
    set-clipboard = off        forwarded to the outer terminal: no    tmux buffer: none

`external` means *tmux's own* copy-mode yanks set the outer clipboard; an
application's `OSC 52` is dropped on the floor. Only `on` passes it through --
and as a bonus it also lands in a tmux buffer, so `prefix ]` pastes it too.

```tmux
# ~/.tmux.conf
set -g set-clipboard on
```

Forwarding also needs tmux to believe the outer terminal can do it, which it
decides from the `Ms` terminfo capability. tmux ships that knowledge for
`xterm*`; check with:

```sh
tmux show -g terminal-features       # xterm*:clipboard means it will forward
```

and if the terminal outside sets some other `TERM`, add it:

```tmux
set -ga terminal-features ',<your-term>:clipboard'
```

GNU `screen` is the same kind of obstacle with none of the same settings: it
has no `OSC 52` forwarding at all.

## The terminal at the far end

Even with tmux out of the way, the terminal has to be willing to write your
clipboard on an application's say-so. Where to look:

  - **kitty** -- `clipboard_control`; writing is allowed by default, reading
    asks.
  - **xterm** -- `allowWindowOps` (off by default) and `disallowedWindowOps`.
  - **Alacritty** -- an `osc52` setting; recent versions allow copy only.
  - **foot**, **WezTerm**, **iTerm2**, **Windows Terminal** -- allowed, with a
    setting to turn it off.
  - **VTE-based terminals** (GNOME Terminal, Tilix, Terminator) -- support
    arrived late; an older one ignores the sequence entirely.

Check your own in one line, with no program involved:

```sh
printf '\033]52;c;%s\007' "$(printf 'hello clipboard' | base64)"
```

Then try to paste. If that does nothing, no terminal program on that machine
will ever reach your clipboard, and the thing to fix is the terminal (or tmux),
not the program. Run it inside and outside tmux to find out which of the two is
eating it.

One footnote for the confused: Turbo Vision writes the sequence with an **empty
selection field** (`OSC 52 ; ; ...`). xterm's own documentation says an empty
field means `s0` -- SELECT and cut buffer 0 -- rather than `c` for the
clipboard, while most other terminals treat it as the clipboard anyway. If a
middle-click paste works and Ctrl-V does not, that is what happened.

## The rule underneath all of this

A boolean returned by a platform layer is worth exactly what it was measured
with. `setClipboardText` answers *"did the platform confirm?"*, and it is
tempting for every layer above to write that down as *"did it work?"*. Those
are not the same claim, and the difference is the entire content of this page.

## Where to go next

  - [`../src/Tui.gren`](../src/Tui.gren) -- `copyToClipboard`, `readClipboard`,
    and the `Copied` and `ClipboardText` events.
  - [`architecture.md`](architecture.md) -- how a request becomes a message on
    the port and an answer comes back as an event.
  - `tvision-node/test/drive_clip.py` in the repository -- a pty test that
    plays the part of a terminal with full `OSC 52` support, answering the
    read query by hand. It is the shortest description of the protocol there
    is.
