// Shared declarations for the Turbo Vision <-> Node binding.
//
// napi.h must come before <tvision/tv.h>: tvision's Borland compatibility
// headers define Boolean/True/False and a pile of macros that V8's headers do
// not enjoy meeting.

#pragma once

#include <napi.h>

#define Uses_TApplication
#define Uses_TButton
#define Uses_TCheckBoxes
#define Uses_TCluster
#define Uses_TCommandSet
#define Uses_TDrawBuffer
#define Uses_TRadioButtons
#define Uses_TDeskTop
#define Uses_TDialog
#define Uses_TEvent
#define Uses_TInputLine
#define Uses_TKeys
#define Uses_TLabel
#define Uses_TListViewer
#define Uses_TMenu
#define Uses_TMenuBar
#define Uses_TMenuItem
#define Uses_TProgram
#define Uses_TRect
#define Uses_TScreen
#define Uses_TSItem
#define Uses_TScrollBar
#define Uses_TStaticText
#define Uses_TStatusDef
#define Uses_TStatusItem
#define Uses_TStatusLine
#define Uses_TSubMenu
#define Uses_TFrame
#define Uses_TWindow
#include <tvision/tv.h>

#include <string>
#include <unordered_map>
#include <vector>

namespace tvnode {

/* ------------------------------------------------------------------ */
/*  Commands                                                          */
/* ------------------------------------------------------------------ */

// JS names commands with strings; TVision wants ushorts. Names of built-ins
// map to the real constants so that {cmd: 'quit'} does what a Turbo Vision
// user expects (TApplication handles it) instead of arriving in JS as a
// mystery.
//
// The numbering is not free choice: `TView::commandEnabled` is
//
//     return Boolean((command > 255) || curCommandSet.has(command));
//
// so **a command above 255 can never be disabled**. User commands therefore
// start at 110 -- clear of TVision's own 0-99 and of cmFileFocused (102), the
// only one it defines higher -- and only spill over into the always-enabled
// range once 255 is used up.
constexpr ushort kUserCmdFirst = 110;
constexpr ushort kUserCmdLast = 255;
constexpr ushort kUserCmdOverflow = 1000;

class CommandRegistry {
public:
    CommandRegistry() { reset(); }

    void reset()
    {
        byName.clear();
        byCode.clear();
        next = kUserCmdFirst;
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
        // An item with no command -- a status line hint, a submenu header --
        // gets 0 (cmValid), which nothing dispatches on. Interning "" would
        // hand out a real user command and deliver stray onCommand('') calls.
        if (name.empty())
            return 0;
        auto it = byName.find(name);
        if (it != byName.end())
            return it->second;
        if (next > kUserCmdLast && next < kUserCmdOverflow)
            next = kUserCmdOverflow;   // these can no longer be disabled
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
    ushort next = kUserCmdFirst;
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
    virtual void focusItem(short item) override;

    void setItems(std::vector<std::string> newItems);
    const std::vector<std::string> &getItems() const { return items; }

private:
    std::vector<std::string> items;
    std::string viewId;
};

// One run of characters on a canvas line, painted in one colour.
//
// `fg` and `bg` are the sixteen BIOS colours, or -1 for "whatever this view's
// palette says". Half of one is meaningful on its own: a span that names a
// foreground and leaves the background at -1 keeps the window's own
// background, which is how a calendar marks today without picking a colour
// scheme.
struct CanvasSpan {
    std::string text;
    int fg = -1;
    int bg = -1;
};

using CanvasLine = std::vector<CanvasSpan>;

// A view whose contents come from JavaScript.
//
// tvdemo's TTable and TCalendarView are plain TView subclasses that implement
// draw() themselves; nothing in the stock widget set can express them. This is
// the equivalent hole in the binding, and the one that matters most for Gren:
// an Elm-architecture app wants to render its own content, not only assemble
// prefabricated controls.
class JsCanvas : public TView {
public:
    JsCanvas(const TRect &bounds, std::string id, int aColorIndex,
             bool selectable, bool blockCursorShape) noexcept;

    virtual void draw() override;
    virtual void handleEvent(TEvent &event) override;

    void setLines(std::vector<CanvasLine> newLines);
    void setCursorAt(int x, int y, bool visible);

private:
    std::vector<CanvasLine> lines;
    std::string viewId;
    int colorIndex;
};

// TCluster keeps its state in a protected `value`, so reading and writing a
// check box from JS means either getData/setData with a raw byte buffer, or a
// subclass. A subclass is harder to get wrong.
class JsCheckBoxes : public TCheckBoxes {
public:
    JsCheckBoxes(const TRect &bounds, TSItem *items, uint32_t aCount) noexcept
        : TCheckBoxes(bounds, items), count(aCount)
    {
    }

    uint32_t bits() const { return value; }
    void setBits(uint32_t v) { value = v; drawView(); }

    // TCluster keeps its labels in a protected collection, and JS wants an
    // array of the right length back.
    const uint32_t count;
};

class JsRadioButtons : public TRadioButtons {
public:
    JsRadioButtons(const TRect &bounds, TSItem *items) noexcept
        : TRadioButtons(bounds, items)
    {
    }

    uint32_t selected() const { return value; }
    void setSelected(uint32_t v) { value = v; drawView(); }
};

// Turbo Vision builds the menu bar and the status line inside the application
// constructor, from static callbacks -- but that is only where they *start*.
// TMenuView keeps its TMenu in a protected member and TStatusLine keeps its
// TStatusDef chain the same way, so a subclass can swap either at runtime.
// tvision's own mmenu example does exactly this for menus; these two make the
// menu bar and the status line part of the view rather than fixed
// configuration.
class JsMenuBar : public TMenuBar {
public:
    JsMenuBar(const TRect &bounds, TMenu *aMenu) noexcept
        : TMenuBar(bounds, aMenu)
    {
    }

    void replace(TMenu *newMenu)
    {
        delete menu;   // exactly what ~TMenuBar does
        menu = newMenu;
        drawView();
    }
};

class JsStatusLine : public TStatusLine {
public:
    JsStatusLine(const TRect &bounds, TStatusDef &aDefs) noexcept
        : TStatusLine(bounds, aDefs)
    {
    }

    void replace(TStatusDef *newDefs)
    {
        // ~TStatusLine's loop, written out because disposeItems is private.
        while (defs != nullptr)
            {
            TStatusDef *def = defs;
            defs = defs->next;
            TStatusItem *item = def->items;
            while (item != nullptr)
                {
                TStatusItem *next = item->next;
                delete item;
                item = next;
                }
            delete def;
            }

        defs = newDefs;
        items = nullptr;

        // update() refreshes `items` from `defs` only when the help context
        // has changed, and ours never does. A value nothing uses forces it.
        helpCtx = 0xFFFE;
        update();
        drawView();
    }
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

    // Dialogs report their outcome by resolving a promise, so they must not
    // also fire onClose. Plain windows must: the user can close one from its
    // frame, and a declarative layer that does not hear about it will keep
    // believing the window is open.
    bool reportClose = true;
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
void dispatchKey(const std::string &id, const std::string &key);

// Queued, not dispatched, for the same reason ~JsWindow's notification is: a
// list box's highlight moves both when the user walks through it and when
// setItems() rebuilds it, and the second of those runs inside a JS call that
// is itself inside the render. Calling back into JS from there would re-enter
// the diff while it is halfway through building a window.
void noteFocused(const std::string &id, int index, const std::string &text);

// Queued, not dispatched. ~JsWindow runs deep inside TVision -- from
// TWindow::close(), from the desktop's own destructor -- and calling into JS
// there hands the application a window that is half gone: the id still
// resolves, so a declarative layer reacting to the notification can call
// close() on it a second time. The pump drains the queue between events, where
// nothing is mid-destruction.
void noteWindowClosed(const std::string &id);
void dispatchClick(const std::string &id, int x, int y);

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

// A canvas's `lines`. Each entry is either a plain string -- the whole line in
// the view's own colour -- or an array of {text, fg, bg} spans. The string
// form is not a shortcut bolted on afterwards: it is what every canvas looked
// like before colour existed, and keeping it means a canvas that does not care
// about colour never has to mention it.
std::vector<CanvasLine> getCanvasLines(const Napi::Value &v);

// Fills a window from a JS `items` array; ids are registered against windowId
// so closing the window forgets them all. Returns the first view that can take
// focus, in declaration order -- see applyInitialFocus.
TView *buildItems(const Napi::Env &env, JsWindow *win, const Napi::Value &items,
                  const std::string &windowId);

// Turbo Vision focuses the *last* view inserted, because insert() prepends and
// the first in z-order wins. In a list written top to bottom that is the last
// thing you wrote -- the Cancel button -- so a dialog opens with the caret
// nowhere near the field the user is going to type in. A declarative API
// should not inherit an artifact of insertion order, so the first focusable
// view in the list gets focus instead, and `focus: "<id>"` overrides it.
void applyInitialFocus(const Napi::Object &spec, TView *firstSelectable);
void applyCursors(const Napi::Env &env, const Napi::Value &items);

// Values of every addressable input inside a window, as {id: value}.
Napi::Object collectValues(const Napi::Env &env, const std::string &windowId);

void registerViewApi(Napi::Env env, Napi::Object exports);

} // namespace tvnode
