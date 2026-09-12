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
being a suite and becomes the wall clock**. It has happened twice:
`drive_hex.py` reached 208.9s of a 229.6s run with fifteen of sixteen cores
idle behind it, and `drive_time.py` was 125.2s and became the wall clock the
moment hex stopped being it. Both are split now -- four drivers over
`hex_common.py`, three over `time_common.py` -- and the suite went 229.6s to
93.9s.

**Time the sections before splitting one.** hex was lopsided (45s, 31s and 61s
in three of seventeen phases) and wanted four files; time was flat (36s, then
72s spread over six picker sections, then 18s) and wanted three.

**And know when to stop, because that point has been passed.** Past about
thirty suites on sixteen cores the run is no longer its slowest member: the sum
matters again, and it puts a floor under the wall clock that no amount of
further splitting goes below. At 53 suites (2026-09-07) the sum is 924.5s,
which over 16 cores is a **57.8s floor** against an 82.6s run and a 40.9s
slowest driver (`programmers-edc/encode`). Splitting anything would buy
essentially nothing.

That was the cheaper driver this file used to ask for, and it was `pump()`
sleeping its whole duration whether or not the app had gone quiet: **a `send`
settles now rather than waits**, returning `QUIET` (200ms) after the terminal
stops talking, which took the run from 150.2s to 82.6s and the sum from 1749.8s
to 924.5s. Three calls in four in this suite are a `settle=` on a `send` or a
`click`, and a settle is by name a wait for the screen to stop moving.

**What must still wait is anything the screen does not show**, and there are
three kinds: an autosave's debounce, a megabyte being copied, a click the model
hears about after the menu is already up. Those pass `wait=n` to `send` instead
and get the whole n. So does **a burst of repeated keys** -- sixty Downs is
sixty events, the pump chews through them in batches, and the screen is
perfectly still between two of them. A bare `pump(n)` has always meant n and
still does.

Re-measure the sum before believing any of these numbers; they were 972.8s and
a 60.8s floor at 37 suites, and 1749.8s at 52. That script can also be run
directly, which is what to do while working on one:

```sh
devbox run -- python3 tools/run_tests.py entries   # just this one
devbox run -- python3 tools/run_tests.py -j1       # one at a time
```

`check` and `test` must both be green before a commit, and `test:asan` too for
anything that touches C++. After editing `tvision-node/src/`, rebuild with
`(cd tvision-node && npx node-gyp build)` inside devbox.

**Turbo Vision is a gyp target now, not a separate cmake build.** There is no
`devbox run lib` and no `build-tvision/`: `tvision-node/binding.gyp` has two
targets, `tvision_lib` (the submodule's 206 sources, from the generated
`tvision-sources.gypi`) and `tvision` (the addon), with a `dependencies` edge
between them. Changing the library relinks the addon, which the cmake split
did not do -- that trap cost a session once and is gone rather than
documented.

Two things follow. `npx node-gyp build` after editing `tvision-node/src/`
still costs two files, because the library's objects are untouched. But
`node-gyp rebuild` now costs 46s rather than 5, so **prefer `configure` plus
`build`** whenever the flags change and the sources have not -- which is what
`test:asan` does, and why the sanitizer cycle is 14s instead of a full
rebuild each way.

**Regenerate `tvision-sources.gypi` after moving the submodule pin**
(`tvision-node/scripts/gen-tvision-sources.py`). `check` fails if it is stale.
The list is committed rather than globbed because a published package's
`binding.gyp` runs on the user's machine, where `<!@(find ...)` is a shell
dependency and on Windows is nothing at all.

**The check count is `grep -cE "^ok|✓"` over `devbox run test`'s output** --
the pty drivers *plus* the JS tests `check` runs first. Counting only lines
beginning `ok` misses the second group and reads as a regression against the
numbers in `git log`.

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
nothing** (`tvision-node/tvision/source/tvision/tinputli.cpp:380`). A field selects its whole
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

**A gesture that missed is quiet, and quiet is what a CPU or liveness check is
looking for.** `drive_loops.py` holds a button, a check box, a list, a scroll
bar and the status line and asks whether each spins a core — and a press that
landed on the desktop instead would have passed every one of those. So the
fixture counts the callbacks it heard, and each hold asserts that number went
up. The same rule applied to the earlier drivers would have caught two aims
that were simply wrong.

**Every driver already checks that nothing it saw was invisible**, and it costs
nothing to keep. `Pty.display` scans each screen it replays for a glyph drawn
in the colour behind it, and `Checks.report` fails on what accumulated — so a
span whose ink stopped contrasting with its ground fails here rather than in
somebody's eyes. Nothing has to be added to a new driver. What *is* worth
adding, whenever a driver opens a window it is not otherwise asserting colour
about, is a look at the screen: the sweep only sees screens a driver read.

The fastest layer is unit tests, in milliseconds and with no terminal, and
there are three of them: `gren-tvision-runtime/test/diff.test.js` for the patch
paths against a fake binding, `gren-tvision/tests/` for the package's pure
logic, and `programmers-edc/tests/` for predc's. All three run in `check` as
well as in `test`. Anything about *what the differ decides to call* belongs in
the first, and anything about *what predc decides to write into its config
file* in the third -- a driver can only reach the states the user interface can
produce, which for a file is a small and lopsided sample of them.

**A test application whose source path includes another program's `src` must
not call its entry module `Main`.** `programmers-edc/tests` has `../src` on the
path so that it can reach `Config`, and predc has a `Main`; calling the suite's
own module `Main` too compiled *predc* into `app`, which ran, found no terminal
and no arguments, and exited 0 in silence. A suite that passes by not running
is the worst failure there is, so the module is `Tests`.

## The widget documentation has screenshots, and they are generated

`gren-tvision/docs/widgets.md` has a picture of every widget, and every one of
them is a photograph of an example rather than a mock-up:

```sh
devbox run -- python3 gren-tvision/docs/shots.py            # all 31, 52s
devbox run -- python3 gren-tvision/docs/shots.py listbox    # just these
```

It boots the example at a pty through the same harness the drivers use, keys it
into the state the documentation is describing, and crops. `tools/shot.py`
turns a `harness.Screen` into a PNG -- 8x16 CP437 bitmaps out of
`tools/cp437.py`, the VGA palette, and a hand-rolled PNG writer, so there is
nothing to install.

**One shot has no example behind it**, and is the exception that proves the
rule: `firstprogram` lifts the "A complete program" block out of
`src/Tui.gren`'s own doc comment, compiles it in a temp directory under `docs/`
and photographs it. Doing that found the documented program did not compile --
`Ui` had grown `theme` and `Window` four fields since it was written, and
nothing had ever fed it to a compiler. A code block in a doc comment is the
only code in the repository nothing builds; this is what builds it.

**Shots find their subject rather than counting to it.** `box(app, "Edit
record")` is the frame that text is drawn inside; only the rectangle of a
*view* within its window is written down, because that number is in the Gren
source and nothing on screen finds it. Two traps, one picture each: `Pty.click`
counts from one, so a window's top frame is row 2 and row 1 is the menu bar;
and a window must be found *before* the thing being photographed covers it,
because a drop-down opens over the title its window would be found by.

Twenty-nine of the 31 are reproducible byte for byte -- the two that are not
have a clock in them, and `take(...)` marks those `stable=False`. A
character CP437 has no glyph for is drawn `?` and **named at the end of the
run**; if a new example draws something new, alias it in `tools/cp437.py`
rather than letting the picture lie.

## Git

The remote is `gilramir/programmers-edc` on GitHub -- the repository was
renamed from `tvision-experiment`, which this working copy is still called.
History is a linear chain on `main` and committing there directly is the
workflow. Commit messages are long and narrative — the finding, not just the
change — and end with the check count. Match the ones already in `git log`.

`tvision-node/tvision/` is a **submodule** of gilramir/tvision, a fork of the
upstream C++ library, pinned to its `patches` branch — upstream master plus the
fixes upstream has not taken yet, one commit each, each also a `fix/...` topic
branch for its PR. It sits inside `tvision-node` rather than at the root
because that is the package that needs it: `npm pack` walks the filesystem, so
a checked-out submodule's files travel in the tarball as ordinary files (its
`.git` does not), and the published package builds from source with nothing
but node-gyp. There is no patch directory: what the submodule is checked out at
is what gets built. A fix that lands upstream means deleting both its branches
and moving the pin. README says the rest.

`gren-tvision/` is the master copy of a package that also has to exist as a
repository of its own, because **a Gren package is a GitHub repository with
semver tags** and nothing else -- there is no registry to upload a tarball to,
so a subdirectory of a monorepo cannot be a dependency.
`tools/export-gren-tvision.sh` is the procedure: a `git subtree split` and a
push of the commit it prints, straight from here, with nothing checked out
anywhere. The export is one-directional -- never edit or commit to it -- and
the one thing that breaks it is **amending or rebasing a commit that has
already gone out**, which changes its split hash and orphans everything after
it. A rewrite outside `gren-tvision/` is invisible to the export.
`docs/publishing.md` has the rest, including why a tag must be bare `1.0.1`.
