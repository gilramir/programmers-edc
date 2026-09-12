# The clipboard, from a terminal program

Three questions get asked about this and they have three different answers.
Find yours here and read the part it points at; the rest of the page is why.

> **"My copy did not arrive."** A terminal program cannot reach the clipboard
> by itself. It either runs a helper (`wl-copy`, `xsel`, `xclip`) that talks to
> a **display**, or it hands the text to **the terminal** as an escape sequence
> and hopes. Over ssh only the second can work, and the usual thing in the way
> is tmux, which by default swallows it. `set -g set-clipboard on` is the fix.
> → [What Turbo Vision does](#what-turbo-vision-does-in-order), [tmux](#tmux)

> **"My paste did not arrive."** Different problem, no fix. Over ssh a terminal
> program cannot *read* the clipboard and no setting makes it — the line above
> is about copying out. What works is letting the **terminal** paste: give the
> user a field and let them press `Ctrl-Shift-V`, because a terminal paste is
> keystrokes and keystrokes always arrive.
> → [Two different things called paste](#two-different-things-are-called-paste)

> **"I selected text with the mouse and the program cannot see it."** It never
> will, and not only over ssh. Turbo Vision reads the X11 **CLIPBOARD**
> selection and never **PRIMARY**, which is the one a mouse drag fills. Paste
> it into a field instead — `Shift`+middle-click, or your terminal's paste key.
> → [There is no such thing as *the* clipboard](#there-is-no-such-thing-as-the-clipboard)

The rest of this explains all three, because the failure is silent at every
layer and the boolean you get back means less than it looks like.

---

## There is no such thing as *the* clipboard

On unix there are at least five stores that people call "the clipboard", and
they are not the same store.

| Store | Filled by | Pasted with | Lives on |
| --- | --- | --- | --- |
| X11 **`CLIPBOARD`** | an explicit Copy — `Ctrl-C`, a menu | `Ctrl-V` | the machine with the display |
| X11 **`PRIMARY`** | *selecting text with the mouse* | middle-click | the machine with the display |
| X11 **cut buffers** | almost nothing, since about 1990 | `Shift`+middle in xterm | the machine with the display |
| **Wayland's** clipboard | an explicit Copy | `Ctrl-V` | the compositor |
| The **terminal's** idea of one | an application's `OSC 52`, or the terminal's own Copy | the terminal's paste key | **the machine the human is at** |
| **tmux buffers** | tmux copy-mode, or an `OSC 52` tmux chose to keep | `prefix ]` | wherever tmux runs |

Two facts about that table do most of the damage.

**The last row is the only one that survives ssh.** Every other store belongs
to a display or a multiplexer on one side or the other of the connection. A
program running on a remote host has no display, and the clipboard a person
wants is on the machine they are sitting at, which the program cannot reach
except by asking the terminal.

**A mouse selection and a copy are different things.** Selecting text with the
mouse fills `PRIMARY`. Pressing Copy fills `CLIPBOARD`. They are separate
stores with separate contents, and a program that reads one has not read the
other.

### Which one does Turbo Vision touch?

`CLIPBOARD`, only, always — on every platform, in both directions.
From `source/platform/unixclip.cpp`:

```cpp
constexpr const char *wlCopyArgv[]    = {"wl-copy", 0};
constexpr const char *xselCopyArgv[]  = {"xsel", "--input", "--clipboard", 0};
constexpr const char *xclipCopyArgv[] = {"xclip", "-in", "-selection", "clipboard", 0};
constexpr const char *wlPasteArgv[]   = {"wl-paste", "--no-newline", 0};
constexpr const char *xselPasteArgv[] = {"xsel", "--output", "--clipboard", 0};
constexpr const char *xclipPasteArgv[]= {"xclip", "-out", "-selection", "clipboard", 0};
```

There is no `--primary` anywhere in the library. So:

> **A mouse-drag selection is not readable by a Turbo Vision program, even on
> the same machine, even with `xclip` installed and a display present.** It is
> in the wrong store, and nothing in the library asks for that store.

This is worth being blunt about because of what the instinct — *"ah, selection
versus clipboard, that must be it"* — gets right and wrong at the same time.
The distinction is real, and locally it is exactly the answer. Over ssh it is
not the thing that failed, because the request never gets far enough to care
which selection it wanted. Two true facts, failing at two different layers, and
fixing the one you can see does not help.

### One footnote that explains a real symptom

Turbo Vision writes `OSC 52` with an **empty selection field** — `OSC 52 ; ;
<base64>`. xterm's own documentation says an empty field means `s0`, which is
SELECT plus cut buffer 0, rather than `c` for the clipboard. Most other
terminals treat empty as the clipboard anyway. If a middle-click paste works
and `Ctrl-V` does not, that is what happened.

---

## Two different things are called paste

This is the distinction that makes the rest of the page make sense. When
somebody says "paste into the program", they may mean either of two mechanisms
that have nothing in common.

**1. The program asks for the clipboard.** `Tui.readClipboard`, or the `cmPaste`
command on a focused field. The program initiates it, and it needs a route to a
clipboard: a helper subprocess, or an escape sequence the terminal answers.
**Over ssh both routes are shut**, for reasons in the next section — and what
comes back instead is the program's *own last copy*, which is why this half
appears to start working the moment you copy something and never reaches your
desktop at all.

**2. The terminal types the clipboard at the program.** `Ctrl-Shift-V`,
`Shift-Insert`, middle-click, tmux's `prefix ]`. The human initiates it, the
terminal reads its *own* clipboard, and the text arrives down the pty as
ordinary keystrokes. **Nothing can stop this working**, because it is not a
clipboard operation from the program's point of view at all — it is typing.

Turbo Vision even knows it happened: it turns bracketed paste on at startup
(`\x1B[?2004h`) and flags every key in the burst with `kbPaste`. But it is still
a burst of key events aimed at whatever holds the caret.

So the practical rule for a program that has to work over ssh:

> **Give the user somewhere to paste into.** An `InputLine`, or an `Editor`.
> Route (1) is what fails; route (2) needs a target and nothing else.

`programmers-edc` does this in two shapes, and they are not the same widget on
purpose. Its Unicode decoder has a field *in the window*, read live, because a
paste is that tool's only source of bytes. Its hex viewer puts one in a
*dialog*, because that tool's normal source is a file — a live field there
would be a second source competing with the model's, and one stray keystroke
would take away the open file and every highlight on it.

### Middle-click is a special case, and it will surprise you

Middle-click is the classic "paste the selection" gesture, and inside a Turbo
Vision program it does not paste. The library turns on mouse reporting at
startup (`\x1B[?1000h`, `\x1B[?1002h`, `\x1B[?1006h`, `termio.cpp:282`), so the
terminal hands the click to the application instead of acting on it — and the
application has its own ideas:

  - on a window frame, a middle-click **moves the window** (`tframe.cpp:195`);
  - in an editor, it **drag-scrolls** the text (`teditor1.cpp:540`).

`Shift`+middle-click bypasses mouse reporting in most terminals and pastes
`PRIMARY` as keystrokes, which does work. Same for `Shift`+drag if you want to
select text out of the screen with mouse reporting on.

---

## What Turbo Vision does, in order

### Writing: `THardwareInfo::setClipboardText`

Two attempts (`source/platform/unixcon.cpp`).

**1. A helper program, if there is a display.** `UnixClipboard` tries `wl-copy`,
then `xsel`, then `xclip` (and `pbcopy` on macOS), by spawning it and writing
the text to its stdin. Each is guarded:

```cpp
{wlCopyArgv,    "WAYLAND_DISPLAY"},
{xselCopyArgv,  "DISPLAY"},
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
those programs are installed. That is not a bug: over ssh the display `xclip`
would talk to is the *far* machine's, and setting a clipboard nobody is sitting
in front of is worse than doing nothing.

**2. The terminal, with `OSC 52`.** Failing that, Turbo Vision writes the text,
base64'd, straight to the terminal:

    ESC ] 52 ; ; <base64 of the text> BEL

This is the only mechanism that can cross an ssh connection. Two things about
it are worth knowing, and one surprises everybody.

**The sequence is always written, even when the function returns `false`.**
From `source/platform/termio.cpp`, with Turbo Vision's own comment:

```cpp
con.write(buf, prefix.size() + b64.size() + suffix.size());
// Return false when there is no full OSC 52 support, even though we always
// make the request. This way, we can still use the internal clipboard.
return state.hasFullOsc52;
```

**And `hasFullOsc52` is about *reading*, not writing.** So:

> **`Copied.toSystem == False` means "nothing confirmed taking it", not
> "nothing took it".** The bytes went out. Whether they landed is between the
> terminal and whatever sits between you and it.

A program that prints a sentence about this on a status line should say the
terminal did not confirm, not that the copy failed. `programmers-edc` says
`the terminal did not confirm it`, and it is the model to copy.

### Reading: a different problem, and a harder one

`Tui.readClipboard` is a request answered later by a `ClipboardText` event
rather than a function that returns a string, and that shape is forced:

  - the helper-program route runs a subprocess and waits for its output;
  - the terminal route sends a query and the answer comes back **through the
    input stream**, arriving like a keystroke, several events later.

`fromSystem = False` on the event means what came back is this program's own
last copy, because nothing outside answered.

**Over ssh it does not merely fail — it is never attempted.** The helper half is
skipped for want of a `DISPLAY`, as above. The terminal half is this, in full
(`source/platform/termio.cpp:913`):

```cpp
static bool requestOsc52Clipboard(ConsoleCtl &con, InputState &state) noexcept
{
    if (state.hasFullOsc52)
    {
        TStringView seq = "\x1B]52;;?\x07";
        con.write(seq.data(), seq.size());
        return true;
    }
    return false;
}
```

The query is not written unless `hasFullOsc52` is already set. Only three things
set it, all from replies to queries Turbo Vision writes at startup
(`termio.cpp:313`):

| Reply | Written when |
| --- | --- |
| a kitty `XTGETTCAP` answer naming `read-clipboard` | `TERM` is anything but alacritty/foot |
| an unsolicited `OSC 52` answer | `TERM` contains `alacritty` or `foot` — those get a direct `OSC 52 ; ; ?` |
| `OSC 60` reporting `allowWindowOps` | xterm, alongside the kitty query |

There is a fourth route that comes first and is not `OSC 52` at all:
**far2l terminal extensions** (`requestFar2lClipboard`, tried before the
`OSC 52` path). A terminal speaking that protocol has a real clipboard API and
reading works properly. Almost nothing speaks it.

Reading fails far more often than writing, and for a good reason: **it is the
direction with a security question attached.** A program that can read your
clipboard can read the password you copied into it a minute ago. Several
terminals that cheerfully accept a write refuse a read on purpose.

> **`set -g set-clipboard on` does not help here.** It is about writing. There
> is no tmux or terminal setting that makes a remote program read your
> clipboard. The honest thing for a program to say is that *the terminal will
> not hand it over* — not that the clipboard is empty, because those two send a
> person to different places and only one of them helps.

---

## tmux

tmux sits between the program and the terminal, so it decides whether anything
gets through. Its option is `set-clipboard`, and its default is `external`,
whose manual page can honestly be read both ways:

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
application's `OSC 52` is dropped on the floor. Only `on` passes it through —
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

**None of that is about reading.** tmux does not answer an `OSC 52` query, does
not forward one, and reports none of the capabilities that would make Turbo
Vision send one. Inside tmux, `hasFullOsc52` is false and stays false.

What tmux *does* give you is route (2): `prefix ]` pastes a tmux buffer into the
pane as keystrokes, and that lands in a field like any other typing. So on a
remote host inside tmux, the working recipe is `prefix [` to select, `prefix ]`
to paste into the program's field — never the program's own paste command.

GNU `screen` is the same kind of obstacle with none of the same settings: it has
no `OSC 52` forwarding at all.

---

## The terminal at the far end

Even with tmux out of the way, the terminal has to be willing.

  - **kitty** — `clipboard_control`; writing is allowed by default, reading
    asks. This is the realistic way to make a *read* work over ssh.
  - **xterm** — `allowWindowOps` (off by default) and `disallowedWindowOps`.
  - **Alacritty** — an `osc52` setting; recent versions allow copy only.
  - **foot**, **WezTerm**, **iTerm2**, **Windows Terminal** — writes allowed,
    with a setting to turn them off.
  - **VTE-based** (GNOME Terminal, Tilix, Terminator) — support arrived late; an
    older one ignores the sequence entirely.

---

## What actually happens, everywhere

| Where you are | Program copies | Program pastes (`readClipboard`, `cmPaste`) | Terminal pastes into a field |
| --- | --- | --- | --- |
| Local X11 | `xclip`/`xsel` → `CLIPBOARD` | works, reads `CLIPBOARD` | works |
| Local Wayland | `wl-copy` | works, `wl-paste` | works |
| Local, mouse-selected text | — | **never** — that is `PRIMARY` | works |
| Local inside tmux, no display vars | `OSC 52`, swallowed by default | **never** | works |
| ssh, no tmux, ordinary terminal | `OSC 52`, if the terminal allows | **never** — no query is sent | works |
| ssh, no tmux, kitty with reads on | `OSC 52` | **works** | works |
| ssh, inside tmux | `OSC 52`, swallowed by default | **never** | works (`prefix ]`) |
| Linux virtual console | nothing to receive it | never | there is no clipboard at all |

The last column never fails. That is the whole practical conclusion of this
page.

---

## What this binding does about it

### One store, and why it could not be a wrapper

Turbo Vision keeps a fallback clipboard of its own in `TClipboard::localText`,
for exactly the case above where no system clipboard answers. This binding
keeps a second one (`g_clipboardLocal` in `tvision-node/src/app.cc`) and **does
not use `TClipboard` at all**. That is not duplication for its own sake; the
class cannot be wrapped:

```cpp
class TClipboard {
public:
    static void setText(TStringView text) noexcept;
    static void requestText() noexcept;
private:
    static char *localText;
    static size_t localTextLength;
};
```

`localText` is a private static with no accessor and no `friend`. The only
reader is `requestText()`, which returns `void` and hands what it finds to
`TEventQueue::setPasteText` — a function that does not give you a string, it
queues a buffer that `getPasteEvent` drains one character at a time as
`evKeyDown` events with `kbPaste` set. **There is no expression that gets text
out of that class.** Which is right for an input line and useless for a Gren
model that wants a `String` to decode.

There is also a bug in it worth not inheriting: `setText` stores locally *only
when the platform refused*, so on a machine where copying works `localText`
holds a stale copy — and a later paste that falls back to it pastes something
from two copies ago rather than nothing. `putOnClipboard` stores first,
unconditionally, and cannot do that.

### So the rule is: no view may reach `TClipboard` either

`TInputLine` and `TEditor` both route `cmCut`, `cmCopy` and `cmPaste` through
`TClipboard` by default. That made **two clipboards** — a `y` in one window and
a `Shift-Ins` in a field filled and read different stores — and the seam was
invisible for months because both stores are *fallbacks*: wherever a real system
clipboard exists, neither is touched and the two paths meet in it. It shows up
exactly where there is nothing to meet in, which is every ssh session.

`JsInputLine` and `JsEditor` therefore answer the three commands themselves,
out of the one store, and never delegate them. Two accept functions carry the
difference — a model gets a string, a view gets keystrokes — and TVision's own
single callback slot does the routing, so a `cmPaste` and a `readClipboard` in
flight together degrade to "the last thing that asked gets the answer", which is
the only correlation the `OSC 52` protocol offers.

### The commands, and the keys nobody binds

`"clipboard.cut"`, `"clipboard.copy"` and `"clipboard.paste"` are built-in
command names. They act on whatever holds the caret — **an `InputLine` as much
as an `Editor`**, since both react to those commands and both light and gray
them as a selection comes and goes. `"editor.clear"`, `"editor.undo"` and
`"editor.selectAll"` are the editor's alone.

> **Turbo Vision binds no keys to cut, copy and paste, deliberately** — picking
> `Ctrl-C` for somebody would be picking wrong for somebody else. So a program
> that names no keys has fields that cannot copy or paste at all, and nothing
> reports it. This catches people out often enough to be an open issue upstream
> (magiblot/tvision#178), where the answer is that hardcoding shortcuts would be
> worse.

`TEditor` is the exception that hides it: its own keymap turns `Ctrl-Ins`,
`Shift-Ins` and `Shift-Del` into the commands (`teditor1.cpp:84`), so an editor
appears to work while every input line in the same program does not. Three
invisible status entries fix it everywhere:

```gren
, { text = "", key = "Shift-Del", cmd = "clipboard.cut" }
, { text = "", key = "Ctrl-Ins", cmd = "clipboard.copy" }
, { text = "", key = "Shift-Ins", cmd = "clipboard.paste" }
```

An entry with no text draws nothing and costs no columns, and a status entry is
`ofPreProcess`, so it is offered every keystroke before an open modal dialog
sees it — which is what carries these into a dialog's fields.

A copy made *in a field* arrives at the model as an ordinary `Copied` event, for
the same reason one made by the model does: whether anything outside confirmed
taking it is worth saying, and it is equally unknown either way.

---

## Working out which layer is failing

One line, no program involved, tests whether a **write** gets through:

```sh
printf '\033]52;c;%s\007' "$(printf 'hello clipboard' | base64)"
```

Then try to paste. If nothing happens, no terminal program on that machine will
ever reach your clipboard, and the thing to fix is the terminal or tmux, not the
program. Run it inside and outside tmux to find out which of the two is eating
it.

There is **no equivalent test for reading**, and that is the point: a query the
terminal ignores looks exactly like a terminal that is thinking about it. What
you can check is whether Turbo Vision thinks reading is possible at all — if
`ClipboardText.fromSystem` is `False`, no query was sent, and no amount of
configuration below that line will change it.

`tvision-node/test/drive_clip.py` plays the part of a terminal with full
`OSC 52` support, answering the read query by hand; it is the shortest
description of the protocol there is.
`programmers-edc/test/drive_clipboard.py` is the other end — a session with no
display and no `OSC 52` claim, which is an ssh session, checking that the
model's copy and a field's paste still meet.

---

## The rule underneath all of this

A boolean returned by a platform layer is worth exactly what it was measured
with. `setClipboardText` answers *"did the platform confirm?"*, and it is
tempting for every layer above to write that down as *"did it work?"*. Those are
not the same claim, and the difference is most of this page.

The same shape one level up: "there is nothing on the clipboard" and "nobody
answered when I asked for the clipboard" are not the same claim either, and only
one of them is ever true over ssh.

## Where to go next

  - [`../src/Tui.gren`](../src/Tui.gren) — `copyToClipboard`, `readClipboard`,
    the `Copied` and `ClipboardText` events, and the built-in command names.
  - [`widgets.md`](widgets.md) — `InputLine` and `Editor`, and what each answers.
  - [`architecture.md`](architecture.md) — how a request becomes a message on
    the port and an answer comes back as an event.
