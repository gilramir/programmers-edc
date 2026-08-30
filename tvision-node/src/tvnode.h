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
#define Uses_TEventQueue
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
#define Uses_THistory
#define Uses_THistoryViewer
#define Uses_THistoryWindow
#include <tvision/tv.h>

#include <functional>
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
            // Handled by TApplication rather than TProgram, which is why they
            // are easy to leave out: nothing complains, the name is interned
            // as an ordinary user command, and "tile" arrives in the model as
            // an event instead of tiling the desktop.
            {"tile", cmTile},     {"cascade", cmCascade},
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

    // setItems() has to move the highlight to row zero before it can be put
    // where the caller wants it. That intermediate position is not news.
    bool quiet = false;
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

// A scroll bar the model owns, rather than the one a list box makes for itself.
//
// TScrollBar announces a change by broadcasting cmScrollBarChanged to its
// owner from scrollDraw(), which is how tvdemo's mouse dialog watches the
// double-click delay. Overriding scrollDraw() is the same trick one level
// down, and it catches every route the value can move by -- arrows, paging, a
// drag on the thumb, or the keyboard.
//
// Whether the bar is horizontal or vertical is not a field: TScrollBar decides
// from its own rectangle, one column wide being vertical.
class JsScrollBar : public TScrollBar {
public:
    JsScrollBar(const TRect &bounds, std::string id) noexcept
        : TScrollBar(bounds), viewId(std::move(id))
    {
        // Not selectable by default -- the one a list box owns should not be
        // in the tab order. One the model asked for by id should be.
        options |= ofSelectable;
    }

    virtual void scrollDraw() override;

private:
    std::string viewId;
};

// An input line that says when the user changed it.
//
// TInputLine has no notification of its own -- Turbo Vision programs read the
// field when the dialog is answered and never before, which is exactly the
// hole this fills for a window that is not a dialog. There is no single method
// every edit goes through either: typing, Backspace, a paste, a click that
// moves the cursor and Ctrl-Y all land in handleEvent. So the comparison is
// made around it, which cannot miss a route.
class JsInputLine : public TInputLine {
public:
    JsInputLine(const TRect &bounds, int aMaxLen, std::string id) noexcept
        : TInputLine(bounds, aMaxLen), viewId(std::move(id))
    {
    }

    virtual void handleEvent(TEvent &event) override;

private:
    std::string viewId;
};

// The drop-down beside an input line -- the list in the model's hands, and the
// pop-up driven by the pump rather than by a nested loop.
//
// Two things about THistory have to be taken back out of it before it can be a
// view in this API, and both are in the classes below.
//
// The list. Turbo Vision keeps history in one process-wide buffer:
// historyAdd() and historyStr() (histlist.cpp) read and write a single fixed
// block, keyed by a uchar, shared by every field in the program, and silently
// dropping the oldest entries when it fills. None of that is reachable from a
// Gren model -- it cannot see the list, bound it, or save it between runs --
// so none of it is used. The items arrive with the render the way a list box's
// do, JsHistoryViewer::getText reads that vector, and recordHistory() is
// overridden to do nothing at all. The widget shows the list; the model
// decides what goes into it.
//
// The loop. THistory::handleEvent calls owner->execView(), which is the one
// thing this binding does not do anywhere else: a nested event loop would
// block Node's for as long as the drop-down is open, stopping every timer,
// promise and subscription the program has. So the open path is written out
// here without that line, and the pop-up is pushed onto the same modal stack
// tv.dialog() uses -- see openLocalModal.
class JsHistoryViewer : public THistoryViewer {
public:
    JsHistoryViewer(const TRect &bounds, TScrollBar *hScroll,
                    TScrollBar *vScroll,
                    const std::vector<std::string> &theItems) noexcept;

    virtual void getText(char *dest, short item, short maxLen) override;

private:
    std::vector<std::string> items;
};

class JsHistoryWindow : public THistoryWindow {
public:
    explicit JsHistoryWindow(const TRect &bounds) noexcept;

    // THistoryWindow builds its viewer through a function pointer held in the
    // virtually-inherited THistInit, which is precisely so that a subclass can
    // supply its own. Borland's signature is the only awkward part: a ushort
    // history id and nothing else, so the items travel in the file-static
    // below rather than through the argument list.
    static TListViewer *initViewer(TRect r, TWindow *win, ushort historyId);
};

class JsHistory : public THistory {
public:
    JsHistory(const TRect &bounds, TInputLine *aLink, std::string id,
              std::string linkId) noexcept
        : THistory(bounds, aLink, 0), viewId(std::move(id)),
          linkViewId(std::move(linkId))
    {
    }

    virtual void handleEvent(TEvent &event) override;

    // The model owns the list, so there is nothing to record. THistory calls
    // this when the field loses focus and again when the drop-down opens.
    virtual void recordHistory(const char *) override {}

    void setItems(std::vector<std::string> newItems)
    {
        items = std::move(newItems);
    }

    const std::vector<std::string> &getItems() const { return items; }

    // Called when the pop-up closes, from the modal stack rather than from
    // inside handleEvent.
    void takeSelection(THistoryWindow *window, ushort result);

private:
    void openDropDown();

    std::vector<std::string> items;
    std::string viewId;
    std::string linkViewId;
};

// TCluster keeps its state in a protected `value`, so reading and writing a
// check box from JS means either getData/setData with a raw byte buffer, or a
// subclass. A subclass is harder to get wrong.
//
// The same handleEvent sandwich as JsInputLine, and for the same reason: a box
// is toggled by Space, by a click, by its hotkey and by the arrow keys moving
// the selection, and `value` afterwards is the only thing all four have in
// common.
class JsCheckBoxes : public TCheckBoxes {
public:
    JsCheckBoxes(const TRect &bounds, TSItem *items, uint32_t aCount,
                 std::string id) noexcept
        : TCheckBoxes(bounds, items), count(aCount), viewId(std::move(id))
    {
    }

    virtual void handleEvent(TEvent &event) override;

    uint32_t bits() const { return value; }
    void setBits(uint32_t v) { value = v; drawView(); }

    // TCluster keeps its labels in a protected collection, and JS wants an
    // array of the right length back.
    const uint32_t count;

private:
    std::string viewId;
};

class JsRadioButtons : public TRadioButtons {
public:
    JsRadioButtons(const TRect &bounds, TSItem *items, std::string id) noexcept
        : TRadioButtons(bounds, items), viewId(std::move(id))
    {
    }

    virtual void handleEvent(TEvent &event) override;

    uint32_t selected() const { return value; }
    void setSelected(uint32_t v) { value = v; drawView(); }

private:
    std::string viewId;
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

    // JsWindow derives from TDialog so that a window and a dialog are one
    // class -- but TDialog's constructor takes the window-ness back out:
    // growMode = 0, flags = wfMove | wfClose, and ofTileable never set by
    // anything in Turbo Vision except TEditWindow. A window on the desktop
    // should zoom, resize, grow with the terminal and take part in Tile and
    // Cascade, so a non-modal one puts all four back.
    void beWindow()
    {
        flags = wfMove | wfGrow | wfClose | wfZoom;
        growMode = gfGrowAll | gfGrowRel;
        options |= ofTileable;
        zoomRect = getBounds();
    }

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

// The user changed a view's value. One of the three, by the kind of value it
// is: text for an input line, a bit per box for a check box cluster, an index
// for radio buttons. Queued and drained at the pump, like every other
// notification a JavaScript call could otherwise re-enter TVision from.
// A cluster's bitfield as an array of `count` booleans.
Napi::Array checkedArray(const Napi::Env &env, uint32_t bits, uint32_t count);

void noteChangedText(const std::string &id, const std::string &text);
void noteChangedFlags(const std::string &id, uint32_t bits, uint32_t count);
void noteChangedChoice(const std::string &id, int index);

// Queued for the same reason, and more urgently: setValue() calls scrollDraw()
// directly, so a render that moves a scroll bar would call back into JS from
// inside the diff.
void noteScrolled(const std::string &id, int value);

// Queued, not dispatched. ~JsWindow runs deep inside TVision -- from
// TWindow::close(), from the desktop's own destructor -- and calling into JS
// there hands the application a window that is half gone: the id still
// resolves, so a declarative layer reacting to the notification can call
// close() on it a second time. The pump drains the queue between events, where
// nothing is mid-destruction.
void noteWindowClosed(const std::string &id);
// `doubled` is TVision's meDoubleClick: the second click of a pair, which the
// first click has already been reported for. tvdemo's mouse dialog exists to
// let you feel where the boundary between the two is.
void dispatchClick(const std::string &id, int x, int y, bool doubled);

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

// Push a view onto the modal stack with a C++ continuation instead of a
// promise -- see the note beside the definition, and JsHistory.
void openLocalModal(TGroup *host, TView *view,
                    std::function<void(TView *, ushort)> done);

void registerViewApi(Napi::Env env, Napi::Object exports);

} // namespace tvnode
