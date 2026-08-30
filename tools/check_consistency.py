#!/usr/bin/env python3
"""Cross-check the four places a widget has to be spelled out.

Adding a view type means editing a Gren union, a Gren encoder, a JavaScript
patcher and a C++ builder. Miss one and nothing complains: the encoder just
omits a branch, or the patcher ignores a type, and the widget silently does not
appear or silently stops updating. Nothing in any one language can catch that,
so this walks all four and compares them.

It also checks the event names in both directions, the messages the port
carries in both directions, the callbacks the runtime hands the binding, the
binding's exported surface against the part of it the protocol can reach, and
the protocol version on both sides.

Exits non-zero on a mismatch. Types the binding supports but the Gren API does
not expose yet are reported as coverage, not as errors -- that list is the
to-do list.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TUI_GREN = os.path.join(ROOT, "gren-tvision", "src", "Tui.gren")
TVNODE_H = os.path.join(ROOT, "tvision-node", "src", "tvnode.h")
DIFF_JS = os.path.join(ROOT, "gren-tvision-runtime", "diff.js")
TUI_JS = os.path.join(ROOT, "gren-tvision-runtime", "tui.js")
VIEWS_CC = os.path.join(ROOT, "tvision-node", "src", "views.cc")
APP_CC = os.path.join(ROOT, "tvision-node", "src", "app.cc")
INDEX_JS = os.path.join(ROOT, "tvision-node", "index.js")


def read(path):
    with open(path) as f:
        return f.read()


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------

def gren_view_variants(src):
    """The constructors of `type View`."""
    block = re.search(r"\ntype View\n(.*?)\n\n\n", src, re.S)
    if not block:
        return []
    return re.findall(r"^\s*[=|]\s*(\w+)", block.group(1), re.M)


# `Grows` is the one constructor of `View` that is not a widget: it wraps
# another view to say which of its edges follow the window, and encodes as a
# `grow` field on the view it wraps rather than as a wire type of its own. It
# therefore has no branch in the four-layer walk and never will. Naming it here
# rather than loosening the walk is what keeps the walk exact for the other
# nine -- and check 2b below verifies that the wrapper really is plumbed, so
# this line is an exemption rather than a hole.
WRAPPER_VARIANTS = {"Grows"}


def gren_encoder_types(src):
    """{constructor: wire type string} from encodeViewFields' branches."""
    block = re.search(r"encodeViewFields view =\n(.*?)(?=\n\n\n\S)", src, re.S)
    if not block:
        return {}
    out = {}
    branches = re.split(r"\n        (?=\w+ v ->)", block.group(1))
    for branch in branches:
        name = re.match(r"\s*(\w+) v ->", branch)
        wire = re.search(r'"type", value = Encode\.string "(\w+)"', branch)
        if name and wire:
            out[name.group(1)] = wire.group(1)
    return out


def js_mutable_types(src):
    block = re.search(r"const MUTABLE = \{(.*?)\n\};", src, re.S)
    return set(re.findall(r"^\s*(\w+):", block.group(1), re.M)) if block else set()


def js_patch_types(src):
    block = re.search(r"function patchView\(before, after\) \{(.*?)\n  \}", src, re.S)
    return set(re.findall(r"case '(\w+)':", block.group(1))) if block else set()


def cc_builder_types(src):
    block = re.search(r"TView \*buildItems\((.*?)\n\}\n", src, re.S)
    return set(re.findall(r'type == "(\w+)"', block.group(1))) if block else set()


def cc_callbacks(src):
    """The callback names tv.start() knows how to install."""
    return set(re.findall(r'std::make_pair\("(on\w+)"', src))


def js_guarded_callbacks(src):
    """The ones index.js wraps, so that a rejected promise cannot escape."""
    return set(re.findall(r"^\s*(on\w+): guard\(", src, re.M))


def js_used_callbacks(src):
    """The ones the Gren runtime actually passes to tv.start()."""
    block = re.search(r"tv\.start\(\{(.*?)\n          \}\);", src, re.S)
    return set(re.findall(r"^\s*(on\w+):", block.group(1), re.M)) if block else set()


def gren_builtin_commands(src):
    """The command names Tui's docs promise Turbo Vision handles itself."""
    block = re.search(r"Built-in command names work here too:(.*?)Turbo\n", src, re.S)
    return set(re.findall(r'`"(\w+)"`', block.group(1))) if block else set()


def cc_builtin_commands(src):
    """The ones CommandRegistry::reset actually interns."""
    block = re.search(r"builtins\[\] = \{(.*?)\};", src, re.S)
    return set(re.findall(r'\{"(\w+)",\s*cm\w+\}', block.group(1))) if block else set()


def gren_event_kinds(src):
    # eventDecoder is the last thing in the file, so this runs to the end.
    block = re.search(r"eventDecoder =\n(.*)", src, re.S)
    return set(re.findall(r'^\s+"(\w+)" ->', block.group(1), re.M)) if block else set()


def js_event_kinds(src):
    # `send({ type: 'x' ... })`, on one line or spread over several. Anchored
    # on send( so the debug tracer's own object literal is not mistaken for a
    # message.
    return set(re.findall(r"send\(\s*\{[^{}]*?type: '(\w+)'", src, re.S))


def gren_outbound_kinds(src):
    """{kind: True} for every message a `ports.toJs` call site can send.

    Anchored on the call site rather than on the string literal: every view in
    `encodeView` also has a `"type"` key, and a list that mixed the two would
    have to be pruned by hand -- which is how `doubleClickDelay` stayed out of
    this check for four protocol versions. The kind is the first `"type"` key
    inside the message object, so a site that has none is reported rather than
    skipped.
    """
    kinds = set()
    blind = 0
    for site in re.finditer(r"ports\.toJs\b", src):
        tail = src[site.end():site.end() + 400]
        kind = re.search(r'\{ key = "type", value = Encode\.string "(\w+)" \}', tail)
        if kind:
            kinds.add(kind.group(1))
        else:
            blind += 1
    return kinds, blind


def js_binding_exports(src):
    """The names `require('tvision-node')` hands out."""
    block = re.search(r"module\.exports = \{(.*?)\n\};", src, re.S)
    return set(re.findall(r"^  (\w+)[,:]", block.group(1), re.M)) if block else set()


def js_binding_calls(src):
    """The binding functions the Gren runtime actually calls."""
    return set(re.findall(r"\btv\.(\w+)\(", src))


def js_outbound_kinds(src):
    block = re.search(r"switch \(message\.type\) \{(.*?)\n    \}", src, re.S)
    return set(re.findall(r"case '(\w+)':", block.group(1))) if block else set()


# --------------------------------------------------------------------------

problems = []
notes = []


def require(condition, message):
    if not condition:
        problems.append(message)


def main():
    tui_gren = read(TUI_GREN)
    diff_js = read(DIFF_JS)
    tui_js = read(TUI_JS)
    views_cc = read(VIEWS_CC)
    app_cc = read(APP_CC)
    index_js = read(INDEX_JS)
    tvnode_h = read(TVNODE_H)

    variants = gren_view_variants(tui_gren)
    encoded = gren_encoder_types(tui_gren)
    mutable = js_mutable_types(diff_js)
    patched = js_patch_types(diff_js)
    built = cc_builder_types(views_cc)

    require(variants, "could not find `type View` in Tui.gren")
    require(built, "could not find the type dispatch in views.cc buildItems")

    # 1. Every Gren constructor is encoded.
    for name in variants:
        if name in WRAPPER_VARIANTS:
            continue
        require(name in encoded, f"View.{name} has no branch in encodeViewFields")

    # 2b. The wrapper, whose exemption above is only worth having if both ends
    #     of it are really there: Tui has to encode through it, and the builder
    #     has to read the field it produces. Miss either and every `Grows` in
    #     every program is silently ignored -- which is the exact failure this
    #     file exists for, and the one the exemption would otherwise hide.
    for name in sorted(WRAPPER_VARIANTS & set(variants)):
        require(re.search(rf"\n        {name} v ->\n            encodeViewFields",
                          tui_gren),
                f"View.{name} is exempt from the type walk but encodeViewFields "
                f"has no branch that unwraps it -- every {name} would encode as "
                f"nothing")
    require(re.search(r'growFields mode =.*?"grow"', tui_gren, re.S),
            "Tui does not encode a 'grow' field, so Grows carries nothing")
    require('it.Has("grow")' in views_cc,
            "views.cc never reads the 'grow' field -- a Grows would encode "
            "correctly and change nothing on screen")

    # 2. Everything Gren emits, the binding can build.
    for name, wire in encoded.items():
        require(wire in built,
                f"encodeView emits type '{wire}' (View.{name}) "
                f"but views.cc buildItems does not handle it")

    # 3. Anything with mutable fields must have a patcher, and vice versa.
    for wire in mutable - patched:
        problems.append(f"diff.js lists '{wire}' as mutable but patchView ignores it "
                        f"-- it will render once and then never update")
    for wire in patched - mutable:
        problems.append(f"diff.js patches '{wire}' but does not list it as mutable "
                        f"-- every change rebuilds the window instead")

    # 4. A patched type must be one the Gren side can actually produce.
    for wire in patched - set(encoded.values()):
        problems.append(f"diff.js patches '{wire}', which no Gren view encodes")

    # 5. Events, both directions.
    gren_events = gren_event_kinds(tui_gren)
    js_events = js_event_kinds(tui_js)
    for kind in js_events - gren_events:
        problems.append(f"the runtime sends event '{kind}' that Tui's decoder "
                        f"does not understand -- it arrives as Unknown")
    for kind in gren_events - js_events:
        notes.append(f"Tui decodes event '{kind}' that the runtime never sends")

    # 6. Outbound messages, both directions.
    gren_out, blind_sites = gren_outbound_kinds(tui_gren)
    js_out = js_outbound_kinds(tui_js)
    require(gren_out, "could not find any ports.toJs call site in Tui.gren")
    require(not blind_sites,
            f"{blind_sites} ports.toJs call site(s) in Tui.gren send a message whose "
            f"`type` this file cannot read -- it is sending something unchecked")
    for kind in gren_out - js_out:
        problems.append(f"Tui sends '{kind}' but the runtime's switch ignores it "
                        f"-- it falls through `default` and nothing happens")
    for kind in js_out - gren_out:
        notes.append(f"the runtime handles message '{kind}' that Tui never sends")

    # 6b. The protocol is the only way into the binding, so an exported
    #     function no message reaches is a capability no Gren program can use.
    #     This is the check that was missing: #10 below compares *view types*,
    #     and nothing compared the twenty functions index.js exports against
    #     the handful the runtime calls. screenSize() and focus() sat there,
    #     implemented and unreachable, across eleven examples and four
    #     protocol versions, and every layer was individually consistent.
    exported = js_binding_exports(index_js)
    called = js_binding_calls(tui_js) | js_binding_calls(diff_js)
    require(exported, "could not find module.exports in tvision-node/index.js")
    require(called, "could not find any tv.* call in the runtime")
    # Three exceptions, each with a reason rather than a shrug.
    #
    #   log        -- for the runtime's own debugging. The terminal belongs to
    #                 TVision, so console.log() draws garbage over the app.
    #                 Not a Gren capability at all.
    #   screenSize -- superseded. It reports the *screen*, and what a window's
    #                 rectangle is written in is the desktop, which the Resized
    #                 event carries without being asked.
    #   getValue   -- superseded, and this one was a decision. It reads a live
    #                 view's value, and making it reachable would have meant
    #                 the protocol's first query-and-response. The Changed
    #                 event answers the same need by telling the model instead,
    #                 which is the shape Focused and Scrolled already set, and
    #                 leaves every message one-way.
    #   messageBox -- tvision-node's own convenience for JavaScript callers,
    #                 and used by its examples. A message box is a dialog, so
    #                 the Gren package builds its own (Tui.messageBox) out of
    #                 the dialog message rather than reaching for this one --
    #                 which is why closing that gap added nothing to the
    #                 protocol at all.
    unreachable_on_purpose = {"log", "screenSize", "getValue", "messageBox"}
    for name in sorted(called - exported):
        problems.append(f"the runtime calls tv.{name}(), which index.js does not "
                        f"export -- it would throw the first time it ran")
    for name in sorted(exported - called - unreachable_on_purpose):
        notes.append(f"the binding exports {name}(), and no message in the protocol "
                     f"reaches it -- no Gren program can ask for it")

    # 7. Callbacks. A name the binding does not know is not an error anywhere:
    #    the addon ignores the extra key, the event simply never arrives, and
    #    nothing at all is reported. Exactly what this file is for.
    accepted = cc_callbacks(app_cc)
    guarded = js_guarded_callbacks(index_js)
    used = js_used_callbacks(tui_js)
    require(accepted, "could not find the callback table in app.cc")
    require(used, "could not find the tv.start() call in tui.js")

    # onExit and onError are handled by index.js's pump and never reach C++.
    for name in used - accepted - {"onExit", "onError"}:
        problems.append(f"tui.js passes {name} to tv.start(), which app.cc does "
                        f"not install -- it would silently never fire")
    for name in accepted - guarded:
        problems.append(f"index.js does not guard {name} -- a callback of that "
                        f"name rejecting would go unreported")
    for name in accepted - used:
        notes.append(f"the binding offers {name}, the Gren runtime does not use it")

    # 8. Built-in command names. A name the registry does not know is not an
    #    error anywhere: it is interned as an ordinary user command, the menu
    #    entry draws, and "tile" arrives in the model as an event instead of
    #    tiling the desktop. Exactly the kind of silence this file is for.
    promised = gren_builtin_commands(tui_gren)
    interned = cc_builtin_commands(tvnode_h)
    require(promised, "could not find the built-in command list in Tui.gren's docs")
    require(interned, "could not find CommandRegistry's builtins table in tvnode.h")
    for name in sorted(promised - interned):
        problems.append(f"Tui's docs promise the built-in command '{name}', which "
                        f"CommandRegistry does not intern -- it would be handed out "
                        f"as an ordinary user command and arrive as an event")
    # And the other way round, which is the worse half: a name the registry
    # takes and the docs do not mention is a name an application will pick in
    # good faith. Turbo Vision then handles it, the model is never told, and
    # the menu entry appears to do nothing at all. examples/watch called a
    # command "cancel" and lost it exactly this way.
    for name in sorted(interned - promised):
        problems.append(f"CommandRegistry interns '{name}', which Tui's docs do not "
                        f"list as built in -- an application that picks that name "
                        f"gets a command Turbo Vision silently swallows")

    # 9. One protocol number, two languages.
    gren_protocol = re.search(r"protocolVersion =\n    (\d+)", tui_gren)
    js_protocol = re.search(r"const PROTOCOL = (\d+);", tui_js)
    require(gren_protocol and js_protocol, "could not find the protocol version on both sides")
    if gren_protocol and js_protocol:
        require(gren_protocol.group(1) == js_protocol.group(1),
                f"protocol mismatch: Tui.gren says {gren_protocol.group(1)}, "
                f"the runtime says {js_protocol.group(1)}")

    # 10. Coverage: what the binding can do that Gren cannot ask for yet.
    for wire in sorted(built - set(encoded.values())):
        notes.append(f"the binding supports '{wire}', the Gren API does not expose it yet")

    # ---------------------------------------------------------------- report
    width = max((len(v) for v in encoded.values()), default=10) + 2
    print(f"{'view type':<{width}} {'Gren':<6} {'encoder':<9} {'patcher':<9} binding")
    for wire in sorted(set(encoded.values()) | built):
        name = next((n for n, w in encoded.items() if w == wire), None)
        mark = lambda ok: "  ok  " if ok else "  --  "
        print(f"{wire:<{width}} {mark(name in variants if name else False):<6}"
              f" {mark(name is not None):<9} {mark(wire in patched):<9} {mark(wire in built)}")

    if notes:
        print()
        for note in notes:
            print(f"note: {note}")

    if problems:
        print()
        for problem in problems:
            print(f"FAIL: {problem}")
        print(f"\n{len(problems)} inconsistency(ies)")
        return 1

    print("\nconsistent across Gren, the runtime and the binding")
    return 0


if __name__ == "__main__":
    sys.exit(main())
