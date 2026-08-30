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
devbox run test       # the above plus every pty driver
devbox run test:asan  # the same drivers under AddressSanitizer
devbox run gren -- <example> [args]
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

## The porting workflow

The API grows by porting one `tvision/examples/` program at a time, because each
port has forced an improvement that staring at the binding did not. After a
port, write up what it forced in **both** `examples/README.md` and `FINDINGS.md`
before moving on: the reason a design is the way it is stops being recoverable
within a day.

Every example is also a pty test (`gren-tvision/test/drive_<name>.py`) and is
registered in `devbox.json`'s `test` and `test:asan` lists.

## Git

No remote; history is a linear chain on `main` and committing there directly is
the workflow. Commit messages are long and narrative — the finding, not just the
change — and end with the check count. Match the ones already in `git log`.

`tvision/` is a gitignored checkout of the upstream C++ library, not part of
this repo.
