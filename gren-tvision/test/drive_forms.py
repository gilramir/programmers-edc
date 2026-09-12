#!/usr/bin/env python3
"""examples/forms -- tvision/examples/tvforms, in Gren.

What this is really testing is the highlight. The C++ original reads
`list->focused` at the moment Edit is pressed; a Gren model cannot call into
C++, so the highlight has to travel in both directions -- out as a `Focused`
event when the user moves, back in as the list box's `focused` field when the
model decides where it should be. Nearly every check below fails if either
direction is broken.

The rest of it is the form: labels bound to controls by id, a group of check
boxes, a group of radio buttons, and values that come back through one
`DialogClosed`.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLE = os.path.join(ROOT, "examples", "forms")
from harness_path import RUNTIME  # finds harness.py and gren-tui.js, here or in an install

from harness import Pty, Checks, node_argv

F2, F3, F8 = b"\x1bOQ", b"\x1bOR", b"\x1b[19~"
DOWN, ESC = b"\x1b[B", b"\x1b"


def detail(screen):
    """The right-hand window, which is only ever a picture of the model."""
    return "\n".join(line[46:] for line in screen.split("\n"))


def main():
    check = Checks()
    env = dict(os.environ, TERM="xterm-256color")
    app = Pty(node_argv(RUNTIME, "main.js"), env, cwd=EXAMPLE)

    app.pump(2.0)
    first = app.render()
    check("the seeded records are listed", "Helton, Andrew" in first and
          "Whitcom, Hana O." in first, first)
    check("sorted by name, as TDataCollection is",
          first.index("Stern, Peter") < first.index("Whitcom, Hana O.") <
          first.index("White, Natalie"), "out of order")
    check("the status line stays off Alt-letters", "F2 New" in first and
          "F3 Edit" in first, "the form's own hotkeys would be unreachable")

    # 1. The highlight starts at the top, and the detail window is drawn from
    #    the model -- so what it says is what the model believes.
    check("the model knows what is highlighted",
          "Helton, Andrew" in detail(first), detail(first))
    check("a check box group came back as several flags",
          "Business, Personal" in detail(first), detail(first))

    # 2. Arrow keys move the highlight, and only a Focused event can tell the
    #    model about it.
    app.send(DOWN, settle=0.4)
    app.send(DOWN, settle=0.6)
    moved = detail(app.render())
    check("the highlight reached the model", "Whitcom, Hana O." in moved, moved)
    check("the whole record followed it", "Nate's girlfriend" in moved, moved)

    # 3. Edit acts on the highlighted record. This is the check the Focused
    #    event exists for: without it the form would open on record 0.
    app.send(F3, settle=1.0)
    form = app.render()
    check("Edit opened the highlighted record",
          "Edit record" in form and "Whitcom, Hana O." in form, form)
    check("labels are bound to their controls", "Name" in form and "Company" in form)
    check("check boxes drawn", "[ ] Business" in form and "[X] Personal" in form,
          "the cluster did not take the model's flags")
    check("radio buttons drawn", "( ) Male" in form and "(•) Female" in form,
          "the radio group did not take the model's index")

    app.send(ESC, settle=0.8)
    check("Escape closed the form", "Edit record" not in app.render())

    # 4. A new record, filled in through the label hotkeys the original uses.
    #    Alt-N reaches the Name field only because nothing global claims it.
    app.send(F2, settle=1.0)
    check("New opened an empty form", "New record" in app.render())
    app.send(b"\x1bn", settle=0.4)
    app.send(b"Aardvark, Anne", settle=0.4)
    app.send(b"\x1bc", settle=0.4)
    app.send(b"Zoo", settle=0.4)
    # The last piece of gap (8), and the only half of it that says nothing
    # back. Letters typed into the phone field never reach it, so there is no
    # keystroke to report and no way for the model to have an opinion --
    # `allowed` says what the field takes and TFilterValidator rejects the rest
    # before the edit lands. Without it a model told about every value change
    # still could not have refused a character.
    app.send(b"\x1bp", settle=0.4)     # Phone
    app.send(b"555abc123", settle=0.6)
    check("a filtered field drops the characters it was not given",
          "555123" in app.render() and "555abc" not in app.render(),
          app.render())

    app.send(b"\x1bt", settle=0.4)     # Type: the check box group
    app.send(DOWN, settle=0.3)
    app.send(b" ", settle=0.3)         # Space ticks it; Enter would not
    app.send(b"\x1bg", settle=0.4)     # Gender: the radio group
    app.send(DOWN, settle=0.3)
    filled = app.render()
    check("Alt-letter hotkeys reached the fields",
          "Aardvark, Anne" in filled and "Zoo" in filled, filled)
    check("Space ticked the second box", "[X] Personal" in filled, filled)

    # The third kind of cluster, and the one the other two could not express:
    # three states per box rather than two. Space cycles and wraps, which is
    # the whole of its behaviour -- and the packing behind it is Turbo
    # Vision's, one 32-bit word for the lot.
    app.send(b"\x1bh", settle=0.4)     # Reach: the multi-state group
    check("a multi-state cluster starts on the state it was given",
          "[ ] Morning" in app.render(), app.render())
    app.send(b" ", settle=0.4)
    check("Space moves a box to the next state, not just on and off",
          "[?] Morning" in app.render(), app.render())
    app.send(b" ", settle=0.4)
    app.send(b" ", settle=0.4)
    check("and the third press wraps back to the first",
          "[ ] Morning" in app.render(), app.render())
    app.send(b" ", settle=0.4)         # leave it on `?`

    app.send(b"\r", settle=1.2)        # Enter presses the default button
    saved = app.render()
    check("the form closed", "New record" not in saved)
    check("the record was collected", "Aardvark, Anne" in saved, saved)
    check("and sorted to the top",
          saved.index("Aardvark, Anne") < saved.index("Helton, Andrew"), saved)
    check("the count in the title followed", "Phone Numbers (5)" in saved, saved)
    check("and what got through the filter is what was collected",
          "555123" in saved, saved)
    check("the multi-state cluster came back as one state per box",
          "Morning [?]  Evening [ ]" in saved, saved)

    # 5. The highlight followed the record to its new row -- the model wrote it
    #    back after the list was rebuilt, which resets it to row 0.
    landed = detail(saved)
    check("the highlight followed the saved record",
          "Aardvark, Anne" in landed and "Zoo" in landed, landed)
    check("both cluster values round-tripped",
          "Business, Personal" in landed and "Female" in landed, landed)

    # 6. Empty the collection. Delete acts on the highlight too, so this walks
    #    down the list on its own.
    for _ in range(5):
        app.send(F8, settle=0.6)
    emptied = app.render()
    check("every record was deleted", "Phone Numbers (0)" in emptied, emptied)
    check("the model noticed it is empty", "F2 adds one." in detail(emptied),
          detail(emptied))

    # 7. With nothing to edit, the command is disabled -- everywhere at once,
    #    which is the only reason the status line key does nothing here.
    app.send(F3, settle=0.8)
    check("a disabled command does not fire", "Edit record" not in app.render(),
          "Edit opened a form for a record that does not exist")

    app.send(F2, settle=1.0)
    check("New is still enabled", "New record" in app.render())
    app.send(ESC, settle=0.8)

    app.send(b"\x1bx", settle=1.0)
    code = app.wait(timeout=6)
    check("exit code 0", code == 0, f"exit={code}")

    return check.report(app)


if __name__ == "__main__":
    sys.exit(main())
