# Working in this repo

[README.md](README.md) says what this is. Two files are load-bearing and worth
reading before changing anything: **[FINDINGS.md](FINDINGS.md)** (why things are
the way they are) and **[gren-tvision/examples/README.md](gren-tvision/examples/README.md)**
(the plan of record — what is ported, what each port forced into the API, and
what is left).

## Everything runs inside devbox

`gren` and node 22 are not on `PATH` otherwise.

```sh
devbox run check      # ~5s, no terminal. Run it constantly.
devbox run test       # the above plus every pty driver -- ~35s
devbox run test:asan  # the same drivers under AddressSanitizer -- ~1m
devbox run gren -- <example> [args]
```

The pty drivers run several at a time, through `tools/run_tests.py`. They are
almost entirely asleep -- typing at a pty and waiting for a repaint -- so
running them in parallel took the suite from three and a half minutes to the
length of its slowest single driver, which is the number that matters and the
only one worth watching. **A driver that grows past the rest of them stops
being a suite and becomes the wall clock**: `drive_hex.py` reached 208s of a
229s run with fifteen of sixteen cores idle behind it, and was split into four
(208.7s to 71.9s; the suite is 149.6s). Measure before splitting -- its phases
were 45s, 31s and 61s against a dozen that were seconds -- and see
`hex_common.py` for the shape a split takes. **`drive_time.py` at 125.2s is
the wall clock now**, and is the next one. That script can also be run
directly, which is what to do while working on one:

```sh
devbox run -- python3 tools/run_tests.py entries   # just this one
devbox run -- python3 tools/run_tests.py -j1       # one at a time
```

`check` and `test` must both be green before a commit, and `test:asan` too for
anything that touches C++. After editing `tvision-node/src/`, rebuild with
`(cd tvision-node && npx node-gyp build)` inside devbox.

Format Gren sources after editing them, especially after scripted edits — those
reliably produce indentation the compiler accepts and a person would not.

## Adding a view type means editing four places

A Gren union, a Gren encoder, the JavaScript patcher, and the C++ builder. Miss
one and nothing complains — the widget silently does not appear, or silently
stops updating. `tools/check_consistency.py` (run by `check`) walks all four and
compares them, and it is the only thing that can.

## Before adding an API, check what Turbo Vision already has

`tools/audit_api.py` (run by `check`) walks every public member of every wrapped
Turbo Vision class, **and the flag bits by name**, against
`tools/decisions.tsv` — one line per member saying what was decided about it.
A member with no line fails the check. `--todo` prints the open gaps and
nothing else.

It exists because coverage used to be decided by porting examples, which finds
only what an example happened to need. Every gap after the coverage list
"emptied" was a *member* of a class that was already wrapped — `maxLen` off by
one, a scroll bar with no `ofFirstClick`, no motion event to hear a drag with —
and each was found by writing an application, which is the most expensive place
to find anything.

Two things about the file are the point rather than bookkeeping:

  - **`used` is not `bound`.** "The binding calls it" is not "a Gren program can
    ask for it", and conflating the two is what produced the claim that the
    widget set was complete while four capabilities were missing.
  - **The flag bits are audited separately**, because a member-level walk sees
    one member called `options` and calls it covered. `ofFirstClick` is a bit.

**When adding a capability, the question that decides its shape is who moves
the state.** Turbo Vision, if it belongs to `TView` and is therefore true of
every widget → a wrapper, like `Grows`/`Enabled`/`Visible`. The model → a field
on the view. The user → an *event*, never a field, because a field the user can
move is one the model writes back over them. Nobody — a fact that changes under
both → also an event, because asking for it would be the synchronous query this
port has never had.

**A field the model writes must not come back as the user's event**, which is
the corollary and the one that has actually bitten. A list's `focused` is a
field *and* an event, because both parties move it, and the binding reported
the model's own writes as `Focused` — so the model stored what it heard and
wrote it back, and only the values agreeing kept it from looping. A mouse wheel
is a burst the model is several renders behind, the values stopped agreeing,
and the list snapped back to a stale index between the eye and the finger. The
exception is worth keeping too: a write the widget could not honour — a
`focused` past the end of a shortened list — *is* reported, because that is a
disagreement rather than an action, and it settles in one round.

## The porting workflow

Every C++ example is ported, so this is history rather than a to-do — but it is
how the API got its shape and the discipline still applies to anything new.
Each port forced an improvement that staring at the binding did not. After a
port, write up what it forced in **both** `examples/README.md` and `FINDINGS.md`
before moving on: the reason a design is the way it is stops being recoverable
within a day. Same for anything the audit above turns up.

An example is also where a new capability gets *used* rather than merely
demonstrated — with a rule that means something in that program, since a field
nothing exercises is a field that quietly stops working.

Every example is also a pty test (`gren-tvision/test/drive_<name>.py`). There is
no list to add it to: `tools/run_tests.py` treats every `test/drive*.py` under
`tvision-node` and `gren-tvision` as a suite, so writing the file is enough.

**A pty driver tests the build, not the source.** Rebuild the example after
editing it, or the driver runs the old `main.js` and fails in a way that looks
exactly like the feature not working.

**Driving an `InputLine` has two traps and both cost a check that silently does
nothing** (`tvision/source/tvision/tinputli.cpp:380`). A field selects its whole
value when it *gains* the caret and not while it has it, so `Alt-`its-label is a
no-op when it is already focused — leave and come back to get a fresh selection.
And `Del` honours a selection while `Backspace` with none deletes one character,
so emptying a field is leave, return, `Del`. Also remember that a field which is
the first selectable view has the caret when the window opens, which takes the
single-letter commands away from the canvas until `Tab` gets there.

Two rules for checking that something is unavailable, which are opposites for a
reason. A disabled **view** is checked by what it *refuses* — type at it and
find the characters absent — because the colour it draws in belongs to the
palette and reads the same either way. A disabled **menu entry** is checked by
its colour, compared against an enabled entry's, because an entry is only ever
looked at, so how it looks is what it does.

The fastest layer is `gren-tvision-runtime/test/diff.test.js`: pure-logic tests
of the patch paths against a fake binding, in milliseconds and with no terminal.
Anything about *what the differ decides to call* belongs there rather than in a
driver.

## Git

No remote; history is a linear chain on `main` and committing there directly is
the workflow. Commit messages are long and narrative — the finding, not just the
change — and end with the check count. Match the ones already in `git log`.

`tvision/` is a **submodule** of gilramir/tvision, a fork of the upstream C++
library, pinned to its `patches` branch — upstream master plus the fixes
upstream has not taken yet, one commit each, each also a `fix/...` topic branch
for its PR. There is no patch directory: what the submodule is checked out at
is what gets built. A fix that lands upstream means deleting both its branches
and moving the pin. README says the rest.
