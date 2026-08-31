// Turn JS key names ("Alt-X", "F10", "Ctrl-Enter") into TVision key codes.
//
// TVision's kb* constants are IBM PC scan codes, so they are not contiguous
// and cannot be computed from a character. For modified letters we let the
// library do it: TKey('X', kbAltShift) == kbAltX (see tkeys.h:174). For named
// keys there is no shortcut, hence the table.

#pragma once

#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace tvnode {

// The canonical name for each key code -- one entry per key, used when
// reporting a keystroke back to JS. namedKeys() below adds the aliases people
// write when *binding* a key; naming has to pick exactly one.
inline const std::vector<std::pair<const char *, ushort>> &canonicalKeys()
{
    static const std::vector<std::pair<const char *, ushort>> table = {
        {"Esc", kbEsc},       {"Enter", kbEnter},   {"Tab", kbTab},
        {"Space", ' '},       {"Backspace", kbBack},
        {"Ins", kbIns},       {"Del", kbDel},       {"Home", kbHome},
        {"End", kbEnd},       {"PgUp", kbPgUp},     {"PgDn", kbPgDn},
        {"Up", kbUp},         {"Down", kbDown},     {"Left", kbLeft},
        {"Right", kbRight},
        {"F1", kbF1},   {"F2", kbF2},   {"F3", kbF3},   {"F4", kbF4},
        {"F5", kbF5},   {"F6", kbF6},   {"F7", kbF7},   {"F8", kbF8},
        {"F9", kbF9},   {"F10", kbF10}, {"F11", kbF11}, {"F12", kbF12},
    };
    return table;
}

// Named keys, matched case-insensitively. Aliases are deliberate: people write
// "Esc" and "Escape", "PgDn" and "PageDown".
inline const std::unordered_map<std::string, ushort> &namedKeys()
{
    static const std::unordered_map<std::string, ushort> table = {
        {"esc", kbEsc},         {"escape", kbEsc},
        {"enter", kbEnter},     {"return", kbEnter},
        {"tab", kbTab},         {"space", ' '},
        {"backspace", kbBack},  {"back", kbBack},
        {"ins", kbIns},         {"insert", kbIns},
        {"del", kbDel},         {"delete", kbDel},
        {"home", kbHome},       {"end", kbEnd},
        {"pgup", kbPgUp},       {"pageup", kbPgUp},
        {"pgdn", kbPgDn},       {"pagedown", kbPgDn},
        {"up", kbUp},           {"down", kbDown},
        {"left", kbLeft},       {"right", kbRight},
        {"f1", kbF1},   {"f2", kbF2},   {"f3", kbF3},   {"f4", kbF4},
        {"f5", kbF5},   {"f6", kbF6},   {"f7", kbF7},   {"f8", kbF8},
        {"f9", kbF9},   {"f10", kbF10}, {"f11", kbF11}, {"f12", kbF12},
    };
    return table;
}

inline std::string toLower(std::string s)
{
    for (char &c : s)
        c = (char) tolower((unsigned char) c);
    return s;
}

// "Alt-X", "Ctrl-Shift-F5", "F10", "" (no key). Returns false on an
// unrecognized name so the caller can report *which* key string was bad --
// silently binding nothing is the worst outcome here, because the menu still
// draws and the key just never fires.
inline bool parseKey(const std::string &spec, TKey &out)
{
    if (spec.empty())
        {
        out = TKey();
        return true;
        }

    ushort mods = 0;
    size_t pos = 0;
    for (;;)
        {
        size_t dash = spec.find_first_of("-+", pos);
        if (dash == std::string::npos)
            break;
        std::string mod = toLower(spec.substr(pos, dash - pos));
        if (mod == "alt")
            mods |= kbAltShift;
        else if (mod == "ctrl" || mod == "control")
            mods |= kbCtrlShift;
        else if (mod == "shift")
            mods |= kbShift;
        else
            break; // Not a modifier: the '-' belongs to the base key itself.
        pos = dash + 1;
        }

    std::string base = spec.substr(pos);
    if (base.empty())
        return false;

    auto it = namedKeys().find(toLower(base));
    if (it != namedKeys().end())
        {
        out = TKey(it->second, mods);
        return true;
        }

    if (base.size() == 1)
        {
        out = TKey((uchar) toupper((unsigned char) base[0]), mods);
        return true;
        }

    return false;
}

// The reverse of parseKey: what to call a keystroke when handing it to JS.
// TKey normalizes, so Ctrl-A arrives as code 'A' with kbCtrlShift set whether
// the terminal sent 0x0001 or a modifier report.
inline std::string keyName(const TEvent &event)
{
    TKey key(event.keyDown.keyCode, event.keyDown.controlKeyState);

    std::string name;
    if (key.mods & kbCtrlShift)
        name += "Ctrl-";
    if (key.mods & kbAltShift)
        name += "Alt-";
    if (key.mods & kbShift)
        name += "Shift-";

    for (const auto &entry : canonicalKeys())
        if (entry.second == key.code)
            return name + entry.first;

    // The character the event carries, *before* the key code it was
    // normalised into. `TKey` uppercases letters on purpose (tkey.cpp): it is
    // a key identity, so that Ctrl-A and Ctrl-a are one key. That is right for
    // a shortcut table and wrong for a program being typed at -- reading the
    // character off `key.code` reported every letter as a capital, which no
    // example noticed because the one that types a letter types "A".
    //
    // Modified keys are unaffected: Alt-X arrives as kbAltX, whose low byte is
    // zero, so it falls through to the key code below and keeps its name.
    uchar ch = event.keyDown.charScan.charCode;
    if (ch >= 32 && ch < 127)
        return name + std::string(1, (char) ch);

    if (key.code >= 32 && key.code < 127)
        return name + std::string(1, (char) key.code);

    // A key event can carry its character in `text` and nowhere else, and this
    // is not a rare case. TVision decides that three consecutive printable
    // characters are a paste (`minPasteEventCount`, config.h) and then blanks
    // the key code of every event it flagged -- `keyDown.keyCode = 0`,
    // tevent.cpp -- so that pasted text cannot trigger menu accelerators. The
    // character survives only in `text`.
    //
    // Three is a low bar: anybody typing quickly trips it, and so does a pty
    // test that writes more than two bytes at once. Without this, the whole
    // burst arrives as "0x0000".
    TStringView text = event.keyDown.getText();
    if (text.size() > 0)
        {
        // CR and CRLF become LF on that path (tevent.cpp again), so name those
        // the way the same keys are named when nobody called them a paste.
        if (text.size() == 1 && text[0] == '\n')
            return name + "Enter";
        if (text.size() == 1 && text[0] == '\t')
            return name + "Tab";
        if (text.size() > 1 || (uchar) text[0] >= 32)
            return name + std::string(text.data(), text.size());
        }

    char buf[16];
    snprintf(buf, sizeof buf, "0x%04x", (unsigned) key.code);
    return name + buf;
}

} // namespace tvnode
