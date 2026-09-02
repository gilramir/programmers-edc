# gren-tvision documentation

Turbo Vision terminal UIs, as the Elm architecture. Three documents, and they
answer different questions.

  - **[Turbo Vision, from Gren](widgets.md)** -- what you are programming
    against. The programming model, the anatomy of the screen, the conventions
    that will surprise anybody who has not used Turbo Vision before, and every
    widget in the inventory described from the Gren side. Start here if you
    want to write a program. Runnable snippets and screenshots are being added
    to each widget entry.

  - **[How a Gren program ends up on Turbo Vision](architecture.md)** -- how it
    works underneath. The four layers, why a Gren package cannot own its own
    ports, what it takes to reach a 1994 C++ library from a language with no
    FFI, and the event loop problem that shaped the rest of the design. Read
    this if you are changing the binding, or if you want to know why the API
    looks the way it does.

  - **[The clipboard, from a terminal program](clipboard.md)** -- why a copy
    reaches the rest of the machine sometimes and not others, what
    `Copied.toSystem = False` actually claims, and the one line of `.tmux.conf`
    that is usually the answer. Read this the first time somebody says the copy
    only works inside your program.

Alongside these, in the repository:

  - [`../src/Tui.gren`](../src/Tui.gren) -- the API reference, as doc comments.
  - [`../examples/README.md`](../examples/README.md) -- the plan of record:
    every ported example, and what each one forced into the API.
  - [`../../FINDINGS.md`](../../FINDINGS.md) -- running notes on what turned
    out to be true, including the things that were not what we expected.
