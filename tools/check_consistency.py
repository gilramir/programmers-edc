#!/usr/bin/env python3
"""Cross-check the four places a widget has to be spelled out.

Adding a view type means editing a Gren union, a Gren encoder, a JavaScript
patcher and a C++ builder. Miss one and nothing complains: the encoder just
omits a branch, or the patcher ignores a type, and the widget silently does not
appear or silently stops updating. Nothing in any one language can catch that,
so this walks all four and compares them.

It also checks the event names in both directions and the protocol version on
both sides of the port.

Exits non-zero on a mismatch. Types the binding supports but the Gren API does
not expose yet are reported as coverage, not as errors -- that list is the
to-do list.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TUI_GREN = os.path.join(ROOT, "gren-tvision", "src", "Tui.gren")
DIFF_JS = os.path.join(ROOT, "gren-tvision-runtime", "diff.js")
TUI_JS = os.path.join(ROOT, "gren-tvision-runtime", "tui.js")
VIEWS_CC = os.path.join(ROOT, "tvision-node", "src", "views.cc")


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


def gren_encoder_types(src):
    """{constructor: wire type string} from encodeView's branches."""
    block = re.search(r"encodeView view =\n(.*?)\n\n\nencodeMenu", src, re.S)
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
    return set(re.findall(r'"type", value = Encode\.string "(\w+)"', src)) - {"render"} | {"render"}


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

    variants = gren_view_variants(tui_gren)
    encoded = gren_encoder_types(tui_gren)
    mutable = js_mutable_types(diff_js)
    patched = js_patch_types(diff_js)
    built = cc_builder_types(views_cc)

    require(variants, "could not find `type View` in Tui.gren")
    require(built, "could not find the type dispatch in views.cc buildItems")

    # 1. Every Gren constructor is encoded.
    for name in variants:
        require(name in encoded, f"View.{name} has no branch in encodeView")

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

    # 6. Outbound messages.
    gren_out = gren_outbound_kinds(tui_gren) & {"render", "dialog", "quit", "setEnabled"}
    js_out = js_outbound_kinds(tui_js)
    for kind in gren_out - js_out:
        problems.append(f"Tui sends '{kind}' but the runtime's switch ignores it")

    # 7. One protocol number, two languages.
    gren_protocol = re.search(r"protocolVersion =\n    (\d+)", tui_gren)
    js_protocol = re.search(r"const PROTOCOL = (\d+);", tui_js)
    require(gren_protocol and js_protocol, "could not find the protocol version on both sides")
    if gren_protocol and js_protocol:
        require(gren_protocol.group(1) == js_protocol.group(1),
                f"protocol mismatch: Tui.gren says {gren_protocol.group(1)}, "
                f"the runtime says {js_protocol.group(1)}")

    # 8. Coverage: what the binding can do that Gren cannot ask for yet.
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
