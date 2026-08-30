// Shared declarations for the Turbo Vision <-> Node binding.
//
// napi.h must come before <tvision/tv.h>: tvision's Borland compatibility
// headers define Boolean/True/False and a pile of macros that V8's headers do
// not enjoy meeting.

#pragma once

#include <napi.h>

#define Uses_TApplication
#define Uses_TButton
#define Uses_TCommandSet
#define Uses_TDeskTop
#define Uses_TDialog
#define Uses_TEvent
#define Uses_TInputLine
#define Uses_TKeys
#define Uses_TLabel
#define Uses_TListViewer
#define Uses_TMenuBar
#define Uses_TMenuItem
#define Uses_TProgram
#define Uses_TRect
#define Uses_TScreen
#define Uses_TScrollBar
#define Uses_TStaticText
#define Uses_TStatusDef
#define Uses_TStatusItem
#define Uses_TStatusLine
#define Uses_TSubMenu
#define Uses_TWindow
#include <tvision/tv.h>

#include <string>
#include <unordered_map>
#include <vector>

namespace tvnode {

/* ------------------------------------------------------------------ */
/*  Commands                                                          */
/* ------------------------------------------------------------------ */

// JS names commands with strings; TVision wants ushorts. User commands start
// well clear of TVision's own range. Names of built-ins map to the real
// constants so that {cmd: 'quit'} does what a Turbo Vision user expects
// (TApplication handles it) instead of arriving in JS as a mystery.
constexpr ushort kUserCmdBase = 1000;

class CommandRegistry {
public:
    CommandRegistry() { reset(); }

    void reset()
    {
        byName.clear();
        byCode.clear();
        next = kUserCmdBase;
        static const struct { const char *name; ushort code; } builtins[] = {
            {"quit", cmQuit},     {"close", cmClose},   {"zoom", cmZoom},
            {"resize", cmResize}, {"next", cmNext},     {"prev", cmPrev},
            {"menu", cmMenu},     {"help", cmHelp},     {"ok", cmOK},
            {"cancel", cmCancel}, {"yes", cmYes},       {"no", cmNo},
        };
        for (auto &b : builtins)
            {
            byName[b.name] = b.code;
            byCode[b.code] = b.name;
            }
    }

    ushort intern(const std::string &name)
    {
        auto it = byName.find(name);
        if (it != byName.end())
            return it->second;
        ushort code = next++;
        byName[name] = code;
        byCode[code] = name;
        return code;
    }

    const std::string *nameOf(ushort code) const
    {
        auto it = byCode.find(code);
        return it == byCode.end() ? nullptr : &it->second;
    }

private:
    std::unordered_map<std::string, ushort> byName;
    std::unordered_map<ushort, std::string> byCode;
    ushort next = kUserCmdBase;
};

/* ------------------------------------------------------------------ */
/*  Widgets                                                           */
/* ------------------------------------------------------------------ */

// Everything JS can address by id needs to be mutable in place. Milestone 3
// wants to diff a declarative tree against what is on screen and patch it;
// a create-and-forget API would force it to tear down and rebuild windows on
// every model change, which fights TVision's retained focus state.

class JsStaticText : public TStaticText {
public:
    JsStaticText(const TRect &bounds, TStringView aText) noexcept
        : TStaticText(bounds, aText)
    {
    }

    // Matches what TStaticText's own constructor and destructor do with
    // 'text': newStr() in, delete[] out (tstatict.cpp).
    void setText(const std::string &s)
    {
        delete[] (char *) text;
        text = newStr(s.c_str());
        drawView();
    }
};

class JsListBox : public TListViewer {
public:
    JsListBox(const TRect &bounds, TScrollBar *scrollBar, std::string id) noexcept
        : TListViewer(bounds, 1, nullptr, scrollBar), viewId(std::move(id))
    {
    }

    virtual void getText(char *dest, short item, short maxLen) override;
    virtual void selectItem(short item) override;

    void setItems(std::vector<std::string> newItems);
    const std::vector<std::string> &getItems() const { return items; }

private:
    std::vector<std::string> items;
    std::string viewId;
};

class JsWindow : public TDialog {
public:
    JsWindow(const TRect &bounds, TStringView title, std::string id) noexcept
        : TWindowInit(&TDialog::initFrame), TDialog(bounds, title),
          windowId(std::move(id))
    {
    }

    ~JsWindow();

    virtual void handleEvent(TEvent &event) override;

    std::string windowId;
};

/* ------------------------------------------------------------------ */
/*  View registry                                                     */
/* ------------------------------------------------------------------ */

struct ViewRef {
    TView *view = nullptr;
    std::string kind;
    std::string windowId;
};

// Ids are the whole point, and the danger is dangling pointers: TVision
// destroys a window's children with it, and the user can close a window from
// its frame without telling us. JsWindow's destructor is what keeps this
// honest -- it drops the window and everything in it.
class ViewRegistry {
public:
    void addWindow(const std::string &id, JsWindow *w) { windows[id] = w; }
    void addView(const std::string &id, TView *v, const std::string &kind,
                 const std::string &windowId)
    {
        views[id] = ViewRef{v, kind, windowId};
        byWindow[windowId].push_back(id);
    }

    void forgetWindow(const std::string &id)
    {
        auto it = byWindow.find(id);
        if (it != byWindow.end())
            {
            for (const std::string &viewId : it->second)
                views.erase(viewId);
            byWindow.erase(it);
            }
        windows.erase(id);
    }

    ViewRef *find(const std::string &id)
    {
        auto it = views.find(id);
        return it == views.end() ? nullptr : &it->second;
    }

    JsWindow *findWindow(const std::string &id)
    {
        auto it = windows.find(id);
        return it == windows.end() ? nullptr : it->second;
    }

    const std::vector<std::string> *idsOf(const std::string &windowId) const
    {
        auto it = byWindow.find(windowId);
        return it == byWindow.end() ? nullptr : &it->second;
    }

    bool has(const std::string &id) const
    {
        return views.count(id) != 0 || windows.count(id) != 0;
    }

    void clear()
    {
        views.clear();
        byWindow.clear();
        windows.clear();
    }

private:
    std::unordered_map<std::string, ViewRef> views;
    std::unordered_map<std::string, JsWindow *> windows;
    std::unordered_map<std::string, std::vector<std::string>> byWindow;
};

/* ------------------------------------------------------------------ */
/*  Globals                                                           */
/* ------------------------------------------------------------------ */

extern CommandRegistry g_commands;
extern ViewRegistry g_views;
extern bool g_running;

// Dispatch into JS. Errors thrown by JS callbacks are captured rather than
// propagated: unwinding a C++ exception through TVision's frames would leave
// the terminal in raw mode with a half-drawn dialog on it.
void dispatchCommand(const std::string &name);
void dispatchSelect(const std::string &id, int index, const std::string &text);

/* ------------------------------------------------------------------ */
/*  Reading JS values                                                 */
/* ------------------------------------------------------------------ */

std::string getString(const Napi::Object &o, const char *key,
                      const std::string &dflt = "");
bool getBool(const Napi::Object &o, const char *key, bool dflt = false);
int getInt(const Napi::Object &o, const char *key, int dflt);
TKey getKey(const Napi::Env &env, const Napi::Object &o, const char *key,
            const std::string &where);
TRect getRect(const Napi::Env &env, const Napi::Object &o, const char *where);

// Fills a window from a JS `items` array. Returns nothing; ids are registered
// against windowId so closing the window forgets them all.
void buildItems(const Napi::Env &env, JsWindow *win, const Napi::Value &items,
                const std::string &windowId);

// Values of every addressable input inside a window, as {id: value}.
Napi::Object collectValues(const Napi::Env &env, const std::string &windowId);

void registerViewApi(Napi::Env env, Napi::Object exports);

} // namespace tvnode
