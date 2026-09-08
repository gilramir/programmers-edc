#!/usr/bin/env python3
"""What of Turbo Vision's public surface the binding does not reach.

`check_consistency.py` asks whether the four layers agree with *each other*.
This asks a different question, and the one that kept being answered late: does
the binding reach what Turbo Vision actually offers? Coverage was decided by
porting the C++ examples one at a time, which finds only what an example
happened to need -- so every gap since has been at the *member* level of a class
that was already wrapped. `TInputLine::maxLen` off by one, `ofFirstClick`
missing from a scroll bar, a list box with no way to say what a double click
means, no motion event to hear a drag with. All four were found by writing an
application, which is an expensive place to find them.

So this walks every public member of every class the binding wraps and compares
it against `decisions.tsv`, which has a line per member saying what was decided
about it. A member that is not in that file is a member nobody has looked at,
and that is what this fails on. Adding a line is cheap; the point is that it is
a line somebody wrote, with a reason, rather than a silence.

    bound      reachable from Gren today
    used       the binding calls it, and it is not itself something a Gren
               program names: geometry, a setter a render goes through. The
               distinction from `bound` is the whole point -- "the C++ mentions
               it" is not "a program can ask for it", and reading it as one is
               how a survey gives false comfort.
    internal   Turbo Vision's own plumbing -- drawing, buffers, stream
               persistence, things a subclass overrides and a caller never
               touches
    skipped    a decision not to wrap it, with the reason after a colon
    todo       a gap somebody has agreed is a gap, with a note after a colon

`todo` lines are reported and do not fail, so the file doubles as the list of
what is left. Run with --todo to see only those.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HEADERS = os.path.join(ROOT, "tvision-node", "tvision", "include", "tvision")
DECISIONS = os.path.join(HERE, "decisions.tsv")

# The classes the binding is answerable for. A class not on this list is one
# nothing has ever wrapped -- the collections, the streams, the help file
# reader, the resource compiler -- and `examples/README.md` is where those are
# argued about, because leaving a whole class out is a design decision and not
# an oversight the size of a member.
WRAPPED = """
TView TGroup TWindow TFrame TDialog TBackground TDeskTop TProgram TApplication
TButton TCluster TCheckBoxes TRadioButtons TMultiCheckBoxes TInputLine TLabel
TStaticText TParamText TScrollBar TScroller TListViewer TListBox TSortedListBox
THistory TMenuBar TMenuBox TMenuView TStatusLine TIndicator TEditor TMemo
TFileEditor TEditWindow TTerminal TOutline TOutlineViewer TStringView
TColorSelector TMonoSelector TColorDialog TFileDialog TDirListBox TChDirDialog
TValidator TFilterValidator TRangeValidator TLookupValidator
TPXPictureValidator TStringLookupValidator TPalette TCommandSet TDrawBuffer
TRect TPoint
""".split()


def class_bodies(text):
    """(name, body) for every class in a header, braces balanced."""
    out = []
    for m in re.finditer(r"\bclass\s+(?:\w+\s+)*?(T\w+)\s*(?::[^{;]*)?\{", text):
        depth = 0
        start = m.end() - 1
        for j in range(start, len(text)):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    out.append((m.group(1), text[start + 1:j]))
                    break
    return out


def public_members(body):
    """(kind, name) for each public member. A class is private by default."""
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    body = re.sub(r"//[^\n]*", "", body)
    access = "private"
    out = []
    for line in body.split("\n"):
        s = line.strip()
        m = re.match(r"^(public|private|protected)\s*:", s)
        if m:
            access = m.group(1)
            continue
        if access != "public" or not s:
            continue
        fn = re.match(r"^(?:virtual\s+|static\s+|inline\s+|constexpr\s+)*"
                      r"(?:[\w:<>,\s*&]+?\s[*&]*)?(~?\w+)\s*\(", s)
        if fn:
            out.append(("fn", fn.group(1)))
            continue
        var = re.match(r"^(?:static\s+|const\s+|mutable\s+)*"
                       r"[\w:<>,\s]+?[*&\s]\s*(\w+)\s*(\[[^\]]*\])?\s*;", s)
        if var:
            out.append(("var", var.group(1)))
    return out


def surface():
    """{class: [(kind, name)]} for every wrapped class, deduplicated."""
    found = {}
    for fn in sorted(os.listdir(HEADERS)):
        if not fn.endswith(".h"):
            continue
        text = open(os.path.join(HEADERS, fn), errors="replace").read()
        for name, body in class_bodies(text):
            if name not in WRAPPED:
                continue
            seen = found.setdefault(name, [])
            for member in public_members(body):
                # A constructor and a destructor are not API in the sense this
                # file means: what a constructor takes is decided member by
                # member above it, and nothing here calls a destructor.
                if member[1] == name or member[1].startswith("~"):
                    continue
                if member not in seen:
                    seen.append(member)
    return found


# Turbo Vision keeps a great deal of its configurability in flag *bits* rather
# than in members -- `options`, `state`, `growMode`, a window's `flags` -- and a
# member-level walk sees one member called `options` and calls it covered. That
# is not a hypothetical blind spot: `ofFirstClick` is a bit, and a scroll bar
# that had to be clicked twice is what finding it cost. So the bits are audited
# by name too, under the pseudo-class `flags`.
def flag_names():
    text = open(os.path.join(HEADERS, "views.h"), errors="replace").read()
    return re.findall(r"^\s{4}((?:sf|of|gf|dm|wf)[A-Za-z]+)\s*=", text, re.M)


# And a third blind spot of the same shape, found the same expensive way.
#
# A *command* is not a member of anything, so the walk above never sees one --
# and Turbo Vision's standard views answer commands they never mention in their
# member list. `TInputLine` handles `cmCut`, `cmCopy` and `cmPaste` exactly as
# `TEditor` does (tinputli.cpp:470), which meant the binding shipped them under
# names beginning `editor.` for months: the one name that made a *field* copy
# and paste announced that it was for something else, so nobody tried it, and
# nothing anywhere could report that. See `doc/clipboard.md`.
#
# The commands are audited by name, under the pseudo-class `commands`. Turbo
# Vision declares them as enumerators rather than constants, in six headers.
def command_names():
    found = []
    for header in ("views.h", "dialogs.h", "editors.h", "stddlg.h",
                   "colorsel.h", "outline.h"):
        text = open(os.path.join(HEADERS, header), errors="replace").read()
        found += re.findall(r"^\s+(cm[A-Z][A-Za-z]*)\s*=", text, re.M)
    return sorted(set(found))


def decisions():
    """{(class, member): (verdict, note)} from the tab-separated file."""
    out = {}
    if not os.path.exists(DECISIONS):
        return out
    for line in open(DECISIONS):
        line = line.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        cls, member, verdict = parts[0], parts[1], parts[2]
        out[(cls, member)] = (verdict, parts[3] if len(parts) > 3 else "")
    return out


VERDICTS = {"bound", "used", "internal", "skipped", "todo"}


def main():
    only_todo = "--todo" in sys.argv

    if not os.path.isdir(HEADERS):
        print(f"audit: no headers at {HEADERS} -- is the submodule checked out?")
        return 1

    known = decisions()
    have = surface()
    have["flags"] = [("var", name) for name in flag_names()]
    have["commands"] = [("var", name) for name in command_names()]

    problems, todos = [], []
    counts = {v: 0 for v in VERDICTS}

    for cls in WRAPPED + ["flags", "commands"]:
        for kind, member in have.get(cls, []):
            verdict, note = known.get((cls, member), (None, ""))
            if verdict is None:
                problems.append(
                    f"{cls}::{member}{'()' if kind == 'fn' else ''} "
                    f"has no line in decisions.tsv")
                continue
            if verdict not in VERDICTS:
                problems.append(f"{cls}::{member} has verdict '{verdict}', "
                                f"which is not one of {sorted(VERDICTS)}")
                continue
            counts[verdict] += 1
            if verdict == "todo":
                todos.append(f"{cls}::{member}  {note}")

    # A decision about something that is no longer there is a decision about
    # nothing, and upstream does move: the calendar bug we reported was fixed
    # in place. Reporting these is how the file stays honest after an update.
    live = {(cls, m) for cls, ms in have.items() for _, m in ms}
    for (cls, member) in sorted(known):
        if (cls in WRAPPED or cls == "flags") and (cls, member) not in live:
            problems.append(f"{cls}::{member} is in decisions.tsv and no "
                            f"longer in the headers")

    if only_todo:
        for line in todos:
            print(line)
        return 0

    total = sum(counts.values())
    print(f"{total} public members and flag bits across "
          f"{len(WRAPPED)} wrapped classes")
    for verdict in ("bound", "used", "internal", "skipped", "todo"):
        print(f"  {verdict:9s} {counts[verdict]}")

    if todos:
        print(f"\n{len(todos)} known gap(s), which do not fail this check:")
        for line in todos:
            print(f"  {line}")

    if problems:
        print()
        for problem in problems:
            print(f"FAIL: {problem}")
        print(f"\n{len(problems)} member(s) nobody has decided about")
        return 1

    print("\nevery public member of every wrapped class has been looked at")
    return 0


if __name__ == "__main__":
    sys.exit(main())
