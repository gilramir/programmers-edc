# How this got here

The repository was called `tvision-experiment` until the experiment worked, and
the question it started with was narrow: can a C++ framework that expects to own
the process be driven from Node, and then from a language that cannot call C at
all? Everything in it — the binding, the Gren package, the runtime, and predc on
top of all three — is what answering that turned into.

## The milestones

| | | |
|---|---|---|
| **0** | Does a Node addon built here load, and can it reach a system library? | done |
| **1** | `hello.cpp` as a Node app, with the menus and dialog described in JS | done |
| **2** | A larger demo on a non-blocking event pump, with addressable views | done |
| **2.5** | Modal dialogs that do not stop Node, and more ported demos | done |
| **3** | Gren on top, through ports | done |
| **4** | Every C++ example ported, one at a time, each forcing an API change | done |
| **5** | A program written *for* the API rather than translated into it | done: `watch`, then predc |

Milestone 0 is still in the tree, as `m0-load-test/`: a two-function addon that
calls into ncursesw and proves the toolchain can produce something `node` will
load. It is kept because it is the smallest thing that can fail, and when the
real addon stops loading it is the first thing to try.

## Why the examples

The API did not get its shape from design. Every C++ program in
`tvision/examples/` was ported to Gren one at a time, and each port was chosen
because it needed something the binding did not have yet — a widget, an event, a
way of saying something that the previous shape made impossible.
[`gren-tvision/examples/README.md`](../gren-tvision/examples/README.md) is the
record of that: one section per example, saying what it forced.

Two things followed from doing it that way, and both are still true.

**Porting finds only what an example happened to need.** After the list of C++
programs ran out, every remaining gap was a *member* of a class that was already
wrapped: `maxLen` off by one, a scroll bar with no `ofFirstClick`, no motion
event to hear a drag with. Each of those was found by writing an application,
which is the most expensive place to find anything. So coverage is a checked
fact now rather than a feeling: `tools/audit_api.py` walks every public member
of every wrapped Turbo Vision class, and the flag bits by name, against
`tools/decisions.tsv`, which has one line per member saying what was decided
about it. A member with no line fails `devbox run check`.

**An example is where a capability gets used rather than demonstrated.** A field
that nothing exercises is a field that quietly stops working, so each new
capability went into an example with a rule that means something in that
program, and every example is also a pty test under `test/drive_<name>.py`.

## Where the development record is

[FINDINGS.md](../FINDINGS.md) is the long one: half a megabyte of what turned
out to be true, in the order it turned out, including the things that were not
what we expected. It is archaeology rather than documentation — the place to
look when the question is "why is it like that" and the code does not say.

[`gren-tvision/examples/README.md`](../gren-tvision/examples/README.md) is the
plan of record for the API: what each port forced, and what was deliberately
left out.

[publishing.md](publishing.md) is what shipping a package with a compiled
shared library in it costs — and what it does not: the addon is Node-API, so one
binary works on every Node version, and glibc rather than `node` is the thing
that decides where it runs.
