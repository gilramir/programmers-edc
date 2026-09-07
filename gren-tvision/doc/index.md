# gren-tvision documentation

Turbo Vision terminal UIs, as the Elm architecture. Four documents, and they
answer different questions.

  - **[Turbo Vision, from Gren](widgets.md)** -- what you are programming
    against. The programming model, the anatomy of the screen, the conventions
    that will surprise anybody who has not used Turbo Vision before, and every
    widget in the inventory described from the Gren side. Start here if you
    want to write a program. Runnable snippets and screenshots are being added
    to each widget entry.

  - **[How a Gren program ends up on Turbo Vision](architecture.md)** -- how it
    works underneath. The four layers, why a Gren package cannot own its own
    ports, what Turbo Vision forced into the design, and the event loop problem
    that shaped the rest of it. Read this if you are changing the binding, or
    if you want to know why the API looks the way it does.

  - **[Driving a C or C++ library from Gren](native.md)** -- the general
    problem, of which this binding is one instance. The three doors out of a
    Gren program and which one is yours, the four ways C can reach Node and
    how to choose, how to get a handle on a compiled Gren program, how to
    design a protocol that only ever tells, how to make a library with its own
    main loop into a guest of Node's, and what goes wrong building the addon.
    Read this if you have some other library in mind.

  - **[The clipboard, from a terminal program](clipboard.md)** -- the five
    stores unix calls "the clipboard" and which one Turbo Vision touches (only
    ever `CLIPBOARD`, never the mouse selection), why a *paste* over ssh is a
    harder problem than a copy and has no setting behind it, the two completely
    different mechanisms both called pasting, what `Copied.toSystem = False`
    actually claims, the one line of `.tmux.conf` that is usually the answer to
    the copy, and the field that is the only answer to the paste. Read it the
    first time somebody says the copy only works inside your program, and again
    the first time they say a paste does nothing at all.

Alongside these, in the repository:

  - [`../src/Tui.gren`](../src/Tui.gren) -- the API reference, as doc comments.
  - [`../examples/README.md`](../examples/README.md) -- the plan of record:
    every ported example, and what each one forced into the API.
  - [`../../FINDINGS.md`](../../FINDINGS.md) -- running notes on what turned
    out to be true, including the things that were not what we expected.
