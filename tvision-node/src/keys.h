// Turn JS key names ("Alt-X", "F10", "Ctrl-Enter") into TVision key codes.
//
// TVision's kb* constants are IBM PC scan codes, so they are not contiguous
// and cannot be computed from a character. For modified letters we let the
// library do it: TKey('X', kbAltShift) == kbAltX (see tkeys.h:174). For named
// keys there is no shortcut, hence the table.

#pragma once

#include <string>
#include <unordered_map>

namespace tvnode {

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

} // namespace tvnode
