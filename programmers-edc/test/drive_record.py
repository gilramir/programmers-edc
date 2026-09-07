#!/usr/bin/env python3
"""`predc --record`: the bug report somebody can send instead of describe.

The tape is written by `gren-tvision-runtime/record.js` and the rules about
what goes on it are unit-tested there, in milliseconds, against a recorder with
no terminal under it -- which is where they belong, because what a recorder
must *not* write is a far bigger set than what a person can be driven into
typing. What that layer cannot check is the two ends: that the flag comes off
the command line before `Cli.gren`'s parser (which answers an unknown word with
an exit) ever sees it, and that a real session through a real pty puts real
events on a real file.

So this driver is about the seams:

  - `--record` is the launcher's flag and `env` is the program's command, and
    both are true at once. That is `takeRecordFlags` splicing `process.argv`,
    and there is no cheaper place to find out it stopped working: the symptom
    is `predc: I don't know what --record means`, at which point the person who
    needed the recorder cannot start the program.
  - A secret in the environment of a real run does not come out on the file.
    The measurement that made this a rule is in `record.js` -- `predc env` puts
    the environment block in the render payload verbatim -- and this is the
    same claim made against the actual program rather than a fixture.
  - A note's text does not either, because it travels as `editorText` and that
    is a document rather than a gesture. `--record-verbatim` is the same run
    with the withholding off, which is what makes the pair worth having: one
    check would pass on a recorder that wrote nothing at all.
  - And the person is told, on the way out, what is in the file they now have.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "bin", "predc.js")
GREN_TAPE = os.path.join(ROOT, "..", "gren-tvision-runtime", "bin", "gren-tape.js")
RECORD_JS = os.path.join(ROOT, "..", "gren-tvision-runtime", "record.js")
sys.path.insert(0, os.path.join(ROOT, "..", "tvision-node", "test"))

from harness import Pty, Checks, node_argv

F4 = b"\x1bOS"
ALT_X = b"\x1bx"

# What Turbo Vision writes on its way in; `drive_cli.py` explains the list.
PAINTED = (b"\x1b[?1049h", b"\x1b[?1000h", b"\x1b[2J")

# A value that could only have come from the environment, and a note body that
# could only have come from the editor. Both are looked for in the raw bytes of
# the tape rather than in a parsed field: a leak that arrives through a field
# nobody thought of is exactly the leak worth catching.
SECRET = "hunter2-must-not-be-recorded"
NOTE = "PRIVATE-DIARY-LINE"


def home_with(notes=None):
    """A HOME of its own -- no driver reads the colour scheme another wrote --
    with notes planted in it when asked for."""
    home = tempfile.mkdtemp(prefix="predc-record-")
    if notes:
        where = os.path.join(home, ".local", "share", "predc", "notes")
        os.makedirs(where)
        for name, text in notes.items():
            with open(os.path.join(where, name), "w") as handle:
                handle.write(text)
    return home


def env_for(home):
    return dict(TERM="xterm-256color", HOME=home,
                PATH=os.environ.get("PATH", "/usr/bin"),
                AWS_SECRET_ACCESS_KEY=SECRET)


def tape_path():
    return os.path.join(tempfile.mkdtemp(prefix="predc-tape-"), "bug.tape")


def start(home, *args, settle=2.5):
    app = Pty(node_argv(LAUNCHER, *args), env_for(home), cwd=ROOT)
    app.pump(settle)
    return app


def read_tape(path):
    """The header and the events, with the raw text kept: half the assertions
    here are about a string that must not be in the file at all, and a parsed
    view cannot make that claim."""
    with open(path) as handle:
        raw = handle.read()
    lines = [json.loads(line) for line in raw.split("\n") if line.strip()]
    return lines[0], lines[1:], raw


def out(app):
    """Everything the program wrote, as text.

    Not `render()`: the notice is printed *after* Turbo Vision has given the
    terminal back, so it lands on a screen the emulator has just been told to
    restore and the lines overwrite each other. What was written is the claim,
    not where it came to rest -- and the same is true of a `--help` longer than
    twenty-five rows.
    """
    return app.buf.decode("utf-8", "replace")


def settled(app, path, limit=6.0):
    """Wait for the tape to stop growing rather than sleep on it: the whole
    file is written synchronously, but the events that fill it arrive at the
    pump's pace."""
    end = time.time() + limit
    size = -1
    while time.time() < end:
        app.pump(0.3)
        now = os.path.getsize(path) if os.path.exists(path) else 0
        if now and now == size:
            return now
        size = now
    return size


def main():
    check = Checks()

    # ---- 1. the flag is the launcher's and the command is the program's ---
    #
    # `Cli.gren` has never heard of `--record` and never will: it is spliced
    # out of `process.argv` before Gren is handed it. If that splice stops
    # working the program will not start at all, so this is the first check.
    home = home_with()
    tape = tape_path()
    app = start(home, "--record", tape, "env")
    screen = app.render()
    check("--record does not stop the command coming after it working",
          "Environment" in screen, screen)

    app.send(b"TERM", settle=1.2)
    check("and the program is the program: the search still finds TERM",
          "xterm-256color" in app.render(), app.render())
    check("the tape is being written while the program runs, not on the way out",
          os.path.exists(tape) and os.path.getsize(tape) > 0,
          f"exists={os.path.exists(tape)}")

    app.send(ALT_X, settle=1.0)
    code = app.wait(timeout=8)
    check("a recorded run exits the way an unrecorded one does", code == 0,
          f"exit={code}")

    header, events, raw = read_tape(tape)

    # ---- 2. the header is the half a keystroke log does not have ----------
    #
    # A tape of events replays into a different program without it: the
    # terminal was a different size, the config file said a different theme,
    # the command line named a different tool.
    # Asked of the runtime rather than written here. A literal is a number
    # somebody has to remember to change, and this check is that the tape
    # agrees with the recorder that wrote it -- not that the number is 2.
    written = int(subprocess.run(
        ["node", "-p", f"require('{RECORD_JS}').TAPE"],
        capture_output=True, timeout=20).stdout.strip())
    check("the header says which tape format this is, and it is this build's",
          header["tape"] == written, f"{header.get('tape')} vs {written}")
    check("and which protocol the two halves were speaking, which is the "
          "version skew a replay has to refuse rather than guess at",
          isinstance(header.get("protocol"), int), header.get("protocol"))
    check("it names the program and its version",
          header["program"]["name"] == "predc" and header["program"]["version"],
          header["program"])
    check("the command line is on it, without the flag that was spliced out",
          "env" in header["program"]["argv"]
          and "--record" not in header["program"]["argv"],
          header["program"]["argv"])
    check("so is the terminal, which is the size the program laid itself out "
          "against before any Resized could arrive",
          header["terminal"]["columns"] == 80 and header["terminal"]["rows"] == 25,
          header["terminal"])
    check("and TERM, because half of what a terminal will do is decided by it",
          header["terminal"]["env"]["TERM"] == "xterm-256color",
          header["terminal"]["env"])
    check("the config file is on it too -- predc picks its theme, its week "
          "numbering and its zone list out of that file during init, so a tape "
          "without it replays into a different program",
          "config" in header.get("extra", {})
          and header["extra"]["config"]["path"].endswith("predc/config.toml"),
          header.get("extra"))
    check("and a missing one is recorded as missing rather than as nothing",
          header["extra"]["config"]["problem"] == "ENOENT",
          header["extra"]["config"])

    # ---- 3. what a person can be told they are sending --------------------
    check("the environment is on the tape by name",
          "AWS_SECRET_ACCESS_KEY" in header["envNames"], header["envNames"][:5])
    check("and not by value, which is the promise that makes the file "
          "sendable at all",
          SECRET not in raw, "the secret reached the tape")

    # The other half of the same promise: `predc env` had that value on the
    # screen the whole time, so the only reason it is not on the tape is that
    # renders are fingerprinted rather than written.
    renders = [e for e in events if e.get("out") == "render"]
    check("a render is on the tape as a hash and its window ids",
          renders and set(renders[0]) >= {"hash", "windows"}, renders[:1])
    check("and never as its payload -- which is where the environment block "
          "was, in full, on every frame",
          '"items"' not in raw and '"spans"' not in raw,
          raw[:200])
    check("the same screen twice is the same hash, which is what a replay "
          "checks itself against",
          len({r["hash"] for r in renders}) < len(renders),
          f"{len(renders)} renders, {len({r['hash'] for r in renders})} hashes")

    # ---- 4. and it is a recording, not an empty file ----------------------
    inbound = [e for e in events if "in" in e]
    check("what came in is on the tape", len(inbound) > 0, len(events))
    check("the search that was typed is on it, because a keystroke is the one "
          "thing that cannot be withheld without withholding the bug",
          any(e["in"].get("value") == "TERM" for e in inbound if "in" in e),
          [e["in"] for e in inbound][:6])
    check("every event is stamped, so a replay can be paced and a gap can be "
          "seen", all(isinstance(e.get("t"), int) for e in events), events[:2])
    check("and the tape says how it ended",
          events[-1].get("end") == "exit", events[-1])

    # ---- 5. the notice, which is what makes the feature honest -------------
    #
    # On stderr, after Turbo Vision has given the terminal back. A person who
    # is about to mail a file is told where it is and what is in it.
    tail = out(app)
    check("the way out says where the recording went",
          os.path.basename(tape) in tail, tail[-400:])
    check("and that their keystrokes are in it",
          "everything you typed" in tail, tail[-400:])
    check("and tells them to look before they send it",
          "before you send it" in tail, tail[-400:])

    # ---- 6. a document is not a gesture -----------------------------------
    #
    # A note travels as `editorText`, which is the whole document, and predc
    # reads it on every autosave. It is the largest thing that crosses the
    # boundary inbound and the most private.
    home = home_with({"Alpha.md": NOTE + "\n"})
    tape = tape_path()
    app = start(home, "--record", tape, "notes")
    check("the note is open", NOTE in app.render(), app.render())
    app.send(b"x", settle=1.5)          # an edit, so the autosave reads it back
    settled(app, tape)
    app.send(ALT_X, settle=1.0)
    app.wait(timeout=8)

    header, events, raw = read_tape(tape)
    withheld = [e for e in events if "in" in e and "withheld" in e["in"]]
    check("the document came back through the port and was recorded",
          any(e["in"].get("type") == "editorText" for e in events if "in" in e),
          [e.get("in", {}).get("type") for e in events][:12])
    check("as its length and its hash, not as itself",
          withheld and withheld[0]["in"]["withheld"]["field"] == "text",
          withheld[:1])
    check("so the note's text is nowhere on the tape", NOTE not in raw,
          "the note reached the tape")
    check("but which editor it was is, because that is the bug and not the "
          "diary", any(e["in"].get("id") for e in withheld), withheld[:1])
    check("and the header says it was redacted, so a reader knows why a field "
          "is missing rather than guessing the recorder is broken",
          header["redacted"] is True, header.get("redacted"))
    check("the notice says which of the two runs this was",
          "Clipboard and editor contents were left out" in out(app),
          out(app)[-400:])

    # ---- 7. --record-verbatim is the same run with the withholding off ----
    #
    # Worth its own case rather than trusted: a single "the secret is not on
    # the tape" check passes just as well on a recorder that writes nothing.
    home = home_with({"Alpha.md": NOTE + "\n"})
    tape = tape_path()
    app = start(home, "--record-verbatim", tape, "notes")
    app.send(b"x", settle=1.5)
    settled(app, tape)
    app.send(ALT_X, settle=1.0)
    app.wait(timeout=8)

    header, events, raw = read_tape(tape)
    check("--record-verbatim keeps the document", NOTE in raw,
          "the note did not reach the verbatim tape")
    check("and says so in the header", header["redacted"] is False,
          header.get("redacted"))
    check("and warns louder on the way out",
          "recorded verbatim" in out(app), out(app)[-400:])

    # ---- 8. the flag before a --help is still a --help --------------------
    #
    # The splice happens before the compiled module is even loaded, so the
    # early-exit path -- which never lets Turbo Vision near the terminal -- is
    # unaffected by it. `drive_cli.py` owns that promise; this is the check
    # that recording did not quietly break it.
    home = home_with()
    tape = tape_path()
    app = Pty(node_argv(LAUNCHER, "--record", tape, "--help"), env_for(home), cwd=ROOT)
    code = app.wait(timeout=8)
    check("--record before --help still prints the help", code == 0
          and "every-day carry" in out(app), f"exit={code}")
    check("and Turbo Vision still never started",
          not any(seq in app.buf for seq in PAINTED), repr(app.buf[:60]))
    check("the help says how to record, which is where somebody who has just "
          "hit something will look",
          "--record FILE" in out(app), out(app)[-500:])

    # ---- 9. the failure modes ---------------------------------------------
    done = subprocess.run(node_argv(LAUNCHER, "--record"), env=env_for(home),
                          cwd=ROOT, capture_output=True, timeout=20)
    check("--record with no filename is a complaint, not a file called nothing",
          done.returncode == 2 and b"needs a filename" in done.stderr,
          f"exit={done.returncode} err={done.stderr[:60]!r}")

    done = subprocess.run(node_argv(LAUNCHER, "--record", "/nosuchdir/x.tape", "env"),
                          env=env_for(home), cwd=ROOT, capture_output=True, timeout=20)
    check("a path that cannot be written fails before the screen is taken, "
          "while there is still an ordinary terminal to say so on",
          done.returncode != 0 and b"ENOENT" in done.stderr,
          f"exit={done.returncode} err={done.stderr[:80]!r}")

    # ---- 10. and none of it happens when nobody asked ---------------------
    home = home_with()
    app = start(home, "env")
    app.send(ALT_X, settle=1.0)
    code = app.wait(timeout=8)
    check("an ordinary run still exits 0", code == 0, f"exit={code}")
    check("and says nothing about recording, because nothing was recorded",
          "Recorded to" not in out(app), out(app)[-200:])

    # ---- 11. a tape that can be read is the point of writing one ---------
    #
    # `gren-tape` is unit-tested against tapes built by hand, which is where
    # the shapes worth testing live -- a file with two runs in it, a request
    # nobody answered, a format older than the reader. This is the other seam:
    # the bin, over a file a real session actually produced. `random` because
    # it is the tool that draws from `Crypto`, and a draw is the one thing on
    # a tape that no message carries.
    home = home_with()
    tape = tape_path()
    app = start(home, "--record", tape, "random")
    settled(app, tape)
    app.send(ALT_X, settle=1.0)
    app.wait(timeout=8)

    done = subprocess.run(node_argv(GREN_TAPE, tape), env=env_for(home),
                          cwd=ROOT, capture_output=True, timeout=20)
    report = done.stdout.decode()
    check("gren-tape reads a tape this session wrote", done.returncode == 0,
          done.stderr[:200])
    check("and says which window was opened", "+random" in report, report[:800])
    check("and that a draw happened which a replay cannot reproduce",
          "cannot reproduce" in report, report[:800])
    check("and it names the zone, without which two tools draw a different day",
          "timeZone" not in report and "/" in report.split("runtime")[1][:80],
          report.split("runtime")[1][:80] if "runtime" in report else report[:200])

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
