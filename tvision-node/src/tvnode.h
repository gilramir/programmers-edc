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
#define Uses_TMultiCheckBoxes
#define Uses_TCluster
#define Uses_TCommandSet
#define Uses_TDrawBuffer
#define Uses_TEditor
#define Uses_TRadioButtons
#define Uses_TDeskTop
#define Uses_TDialog
#define Uses_TEvent
#define Uses_TEventQueue
#define Uses_THardwareInfo
#define Uses_TInputLine
#define Uses_TFilterValidator
#define Uses_TValidator
#define Uses_TKeys
#define Uses_TLabel
#define Uses_TListViewer
#define Uses_TMenu
#define Uses_TMenuBar
#define Uses_TMenuBox
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
// A menu entry that names no command. It cannot be 0, and that is not a style
// choice: TVision reads `command == 0` as **"this item is a submenu"**, and
// `TMenuItem` keeps the two readings in a union --
//
//     union { const char *param; TMenu *subMenu; };
//
// so the zero that means "nothing to dispatch" here means "follow the shortcut
// string as a `TMenu *`" there. The one that kills you is
// `TMenuView::findHotKey` (tmnuview.cpp:567):
//
//     if( p->command == 0 )
//         if( (T = findHotKey( p->subMenu->items, key )) != 0 )
//
// with no null check, called from `TMenuView::handleEvent` (:531) on *every*
// evKeyDown -- through a menu bar that is `ofPreProcess` and therefore sees
// every key before anything else. So it is the first keystroke after such a
// menu is built, whatever has focus, and it looks like a crash in whatever was
// being typed. (`~TMenuItem` at :81 and `updateMenu` at :487 read the same 0;
// the destructor would free the string as a `TMenu *`.)
//
// So an item with no command gets this instead, and is disabled, which is what
// "no command" meant anyway: nothing to dispatch and nothing to choose.
// `test/regress_menu.js` is one keystroke away from the crash without it.
constexpr ushort kCmdNothing = 999;

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
            // The prefixed names, and the reason they are prefixed. Everything
            // above is a word a program is unlikely to want -- "cascade",
            // "prev", "yes" -- but these are everyday ones, and a built-in name
            // silently eats the event a program was expecting. The first
            // version of this list interned bare "clear" and broke two examples
            // that already had a Clear of their own; nothing reported it, which
            // is exactly the failure mode the docs warn about.
            //
            // **Two prefixes, because these are two different sets.** The three
            // clipboard commands are handled by `TInputLine` *and* `TEditor`
            // (tinputli.cpp:470 and teditor1.cpp:639), so they belong to any
            // focused field and calling them "editor.*" said the opposite --
            // which meant nobody would ever try the one name that worked. The
            // other three really are the editor's: `TInputLine` has no branch
            // for cmClear, cmUndo or cmSelectAll at all.
            {"clipboard.cut", cmCut},
            {"clipboard.copy", cmCopy},
            {"clipboard.paste", cmPaste},
            // Two absences, both deliberate. "editor.save", because writing a
            // file is a Task and so saving is the model's job -- its command
            // has to arrive as an event. And find/replace, because cmFind and
            // cmReplace do nothing without a search string: TEditor asks for
            // one through editorDialog, which is disabled here (it is
            // messageBox, which is execView, which is the nested loop the
            // menu bar already has too much of). A search needs the model to
            // ask a question, so it is not a name that works on its own.
            {"editor.clear", cmClear},
            {"editor.undo", cmUndo},
            {"editor.selectAll", cmSelectAll},
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

// A scroll bar that takes the mouse wheel only when the pointer is over the
// pane it scrolls -- and the base of every scroll bar in the binding.
//
// The wheel is not a positional event. `views.h` defines
// `positionalEvents = evMouse & ~evMouseWheel`, so `TGroup::handleEvent` does
// not look for the view under the pointer at all: it offers a wheel turn to
// every view in z-order until one clears it, and `TScrollBar` is the only
// stock view that asks for `evMouseWheel`. In a window that is one pane and
// its bar that is exactly right -- the wheel works wherever the pointer is,
// which is what a reader expects. In a window with three lists side by side
// it means the frontmost bar answers for the whole window, and the frontmost
// bar is the last one inserted: in the time zone picker, turning the wheel
// over the zone list scrolled the `Displaying` column beside it and the list
// under the pointer never moved.
//
// So the bar answers for a region instead of for the window -- its own column
// and the pane it belongs to. A window with one list is unchanged, because
// the pointer is over that list.
//
// A null `pane` keeps the old rule, and that is not a fallback: it is the
// right answer for a window whose only scrollable thing is the scroll bar's,
// and it is what a `scrollBar` with no `for` still gets.
class PaneScrollBar : public TScrollBar {
public:
    PaneScrollBar(const TRect &bounds) noexcept : TScrollBar(bounds) {}

    // The view this bar scrolls, or null for a bar that answers for the whole
    // window. Set after construction rather than passed to it, because
    // `TListViewer` wants the bar to exist first -- and because a model-owned
    // bar names its pane by id, which is resolved by the builder.
    TView *pane = nullptr;

    virtual void handleEvent(TEvent &event) override;
};

class JsListBox : public TListViewer {
public:
    // `columns` is TListViewer's own `aNumCols`, and it belongs in the
    // constructor rather than in an assignment afterwards because the base
    // constructor uses it to size the horizontal scroll bar it may make.
    JsListBox(const TRect &bounds, TScrollBar *scrollBar, std::string id,
              short columns = 1) noexcept
        : TListViewer(bounds, columns, nullptr, scrollBar),
          viewId(std::move(id))
    {
    }

    // Which item is drawn on the first row. TListViewer moves this itself to
    // keep the focused item visible and offers no way to say it, because its
    // scroll bar tracks `focused` and not this (tlstview.cpp:159-183).
    //
    // So this is the one place in the binding where the model can put the
    // highlight off screen. That is deliberate: "scroll the list" and "move
    // the highlight" are two sentences, a model that says only the first means
    // only the first, and the next thing that moves the highlight scrolls it
    // back into view of its own accord.
    void setTop(short item)
    {
        if (item < 0)
            item = 0;
        if (range > 0 && item > range - 1)
            item = range - 1;
        if (topItem == item)
            return;
        topItem = item;
        drawView();
    }

    // Move the highlight because the *model* said so, rather than because
    // the user did.
    //
    // The difference is the whole of it. `focusItem` reports every move, which
    // is right for a move the user made and is a feedback loop for one the
    // model made: the model writes the highlight, the write is reported back
    // as a `Focused` event, the model stores what it is told, and its next
    // render writes it again. Nothing stops that but the values happening to
    // agree -- and under a mouse wheel, which arrives as a burst of events the
    // model is several renders behind, they do not agree for a long time. The
    // list ends up wherever an echo of a stale index left it.
    //
    // So a model-driven move says nothing, the same way `setItems`' trip
    // through row zero says nothing, and for the same reason: it is not news
    // to the only party that could be told.
    //
    // Except when it is. `focusItemNum` clamps, so a model that asks for row
    // ten of a list that now has three does not get row ten -- and *that* the
    // model has to hear, or it goes on believing a highlight the list does not
    // have. It cannot loop: the model stores the row it was given, asks for
    // that row next time, and gets it.
    void setFocused(short item);

    virtual void getText(char *dest, short item, short maxLen) override;
    virtual void selectItem(short item) override;
    virtual void focusItem(short item) override;

    void setItems(std::vector<std::string> newItems);
    const std::vector<std::string> &getItems() const { return items; }

    // The command a committed entry sends, or zero for a list that only
    // reports. Inside a modal dialog it is what makes a double click on a
    // file name the same act as pressing OK, which is what TFileDialog does
    // for itself in tfildlg.cpp -- it turns its own cmFileDoubleClicked
    // broadcast into a cmOK and puts it back on the queue. A list box the
    // model built is not a TFileList and has no such broadcast, so the
    // command is named in the render instead.
    ushort chooses = 0;

private:
    std::vector<std::string> items;
    std::string viewId;

    // Set while a move is the model's own doing rather than the user's --
    // `setItems`' trip through row zero, and every `setFocused`. Neither is
    // news to the model, which is where the news would go.
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
    ~JsCanvas();

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
class JsScrollBar : public PaneScrollBar {
public:
    JsScrollBar(const TRect &bounds, std::string id) noexcept
        : PaneScrollBar(bounds), viewId(std::move(id))
    {
        // Not selectable by default -- the one a list box owns should not be
        // in the tab order. One the model asked for by id should be.
        //
        // And `ofFirstClick` with it, or the two together are worse than
        // either alone. `TView::handleEvent` swallows a mouse-down on a
        // selectable view that is not focused unless the view says the first
        // click counts, so a bar that had only been made selectable took the
        // caret on one click and moved on the next -- and nothing on the
        // screen says which of the two the next click is. A list box's own
        // bar has neither option and therefore acts on the first click; a
        // scroll bar is a control whose whole purpose is to be clicked, and
        // making it reachable by Tab must not make it worse with a mouse.
        options |= ofSelectable | ofFirstClick;
    }

    // The model's own writes, silenced -- the same rule and the same reason as
    // `JsListBox::setFocused`.
    //
    // `scrollDraw` is the only notification a `TScrollBar` has, and it runs for
    // *any* change of value: a drag on the thumb and a `setParams` from the
    // builder are indistinguishable inside it. So a bar the model declared with
    // `value: 5` told the model "the user scrolled to 5" before the first
    // frame was on the screen, and `tv.setValue(bar, 12)` came straight back
    // as `scroll bar=12`. Held together, like the list's highlight was, only by
    // the two values agreeing -- and they agree until a burst arrives and the
    // model is several renders behind.
    //
    // Named rather than shadowing `setValue` and `setParams`, which are not
    // virtual: a call through a `TScrollBar*` -- and `TListViewer` makes those
    // for the bar it owns -- would silently get the base and none of this.
    void setValueFromModel(int wanted)
    {
        quiet = true;
        setValue(wanted);
        quiet = false;
        tellModelIfItCouldNot(wanted);
    }

    void setParamsFromModel(int wanted, int aMin, int aMax, int aPgStep,
                            int aArStep)
    {
        quiet = true;
        setParams(wanted, aMin, aMax, aPgStep, aArStep);
        quiet = false;
        tellModelIfItCouldNot(wanted);
    }

    virtual void scrollDraw() override;

private:
    // A write the bar could not honour is reported, because that is a
    // disagreement rather than an action: the model asked for a value outside
    // the range it also set, the bar clamped, and a model that heard nothing
    // would go on believing the number it asked for. It settles in one round.
    void tellModelIfItCouldNot(int wanted);

    bool quiet = false;
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
// The set of characters a field will accept, and nothing else.
//
// TFilterValidator does two jobs, and only one of them belongs here.
// isValidInput() is called from TInputLine::checkValid after every edit and
// rejects the whole edit if the result contains a character outside the set --
// which is Turbo Vision's answer to "reject a keystroke before it reaches the
// field", and the half of gap (8) that a model told about keystrokes still
// could not do.
//
// isValid() is the other job: TInputLine::valid() calls it when the dialog is
// answered and, on failure, calls error() -- which is messageBox(), which is
// execView(), which is a nested event loop. It is overridden away to True for
// two reasons. The loop is one. The other is that the only way a field can
// hold a character its own filter rejects is for the *model* to have put it
// there with setValue, and a value the model set is the model's to validate;
// blocking a dialog over it would be the binding second-guessing the program.
class JsFilterValidator : public TFilterValidator {
public:
    explicit JsFilterValidator(TStringView allowed) noexcept
        : TFilterValidator(allowed)
    {
    }

    virtual Boolean isValid(const char *) override { return True; }
};

// The binding's clipboard, as far as a view is concerned. Both are defined in
// app.cc, next to the store they act on, and both exist so that no view has to
// reach `TClipboard` -- see the long note there for what a second clipboard
// cost and why it could not simply be wrapped.
void clipboardSetFromView(TStringView text);
void clipboardRequestForView();

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
    // A single click chooses. THistoryViewer wants a double click or Enter,
    // which is the convention for a list somebody might be browsing; a
    // drop-down is not being browsed. See the definition.
    virtual void handleEvent(TEvent &event) override;

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

// A cluster whose boxes have more than two states.
//
// TMultiCheckBoxes packs every item's state into the same `value` word a
// TCluster already has, which is why its constructor takes a pair of numbers
// nobody would guess: `selRange` is how many states there are, and `flags` is
// the low byte's bit mask together with the high byte's bits-per-item. Both
// are derivable from the marks -- one character per state, drawn between the
// brackets -- so the model gives the marks and this works the rest out.
//
// The packing is the reason for the ceiling: 32 bits of `value`, so
// items * bitsPerItem must fit, and the builder says so rather than silently
// dropping the last few boxes.
class JsMultiCheckBoxes : public TMultiCheckBoxes {
public:
    JsMultiCheckBoxes(TRect &bounds, TSItem *items, uint32_t aCount,
                      const std::string &theMarks, std::string id) noexcept;

    virtual void handleEvent(TEvent &event) override;

    // The marks are kept here and the base class is given none, which is a
    // workaround for magiblot/tvision#230 rather than a preference:
    // TMultiCheckBoxes copies its `states` string with newStr() -- `new
    // char[]` -- and its destructor frees it with plain `delete`
    // (tmulchkb.cpp:62). AddressSanitizer stops the process over the
    // mismatch, which is how it was found. Passing a null pointer makes
    // newStr() return 0, so the destructor deletes nothing, and draw() is
    // overridden to use the copy above instead.
    virtual void draw() override;

    std::vector<int> states() const;
    void setStates(const std::vector<int> &wanted);

    // How many bits one item's state occupies, given how many marks there are.
    // One for two marks, two for three or four, and so on -- never zero, so
    // that a single-mark cluster is still addressable.
    static int bitsFor(size_t markCount);

    const uint32_t count;

private:
    int bits;
    uint32_t mask;
    std::string marks;
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

// `eventTimeoutMs` is 0 so that the pump's own poll never blocks, which is
// ruinous inside one of Turbo Vision's nested `getEvent` loops: the poll
// returns instantly and the loop spins a core for as long as the gesture
// lasts. This raises it for the duration of one call and puts it back. It is a
// global, so the whole job of this type is making sure it is a global that is
// only ever 20 inside a scope that has already stopped Node.
struct NestedLoopTimeout {
    // Saved and restored rather than set and zeroed, because these nest, and
    // they nest in a way that is not obvious from either call site. A guard
    // that put the timeout back to 0 rather than to what it found would take
    // the sleep away from the loop it was nested *inside* -- and the moment
    // there were two of them that is what happened: holding a check box went
    // from quiet to 101 ticks a second, because `TGroup::handleEvent`
    // distributes an `evBroadcast` to every subview, the status line is one,
    // and a broadcast arriving mid-gesture ran the guard below and zeroed the
    // timeout the cluster's own loop was relying on. Measured: `what=0200`,
    // three times, with the timeout at 20 when it arrived.
    int saved;

    NestedLoopTimeout() : saved(TProgram::eventTimeoutMs)
    {
        TProgram::eventTimeoutMs = 20;
    }

    ~NestedLoopTimeout() { TProgram::eventTimeoutMs = saved; }
};

class JsStatusLine : public TStatusLine {
public:
    JsStatusLine(const TRect &bounds, TStatusDef &aDefs) noexcept
        : TStatusLine(bounds, aDefs)
    {
    }

    // The one nested loop the pump's scope could not reach.
    //
    // `TStatusLine::handleEvent` tracks a held button in `TView::mouseEvent`
    // like every other stock widget -- and unlike every other one it is not
    // reached through `TGroup::handleEvent`. `TProgram::getEvent` dispatches a
    // mouse-down on the status line *itself* (tprogram.cpp:153), inside the
    // pump's own `getEvent` call and therefore outside the scope that raises
    // `eventTimeoutMs` around `target->handleEvent`. So this one loop went on
    // polling with a zero timeout and spun a core flat for as long as the
    // button was held: 99 ticks a second, measured, which is the same defect
    // `dragView` had in the one place the fix for it could not see.
    //
    // Here rather than at the call site because there are two call sites and
    // only one of them is ours.
    void handleEvent(TEvent &event) override
    {
        NestedLoopTimeout sleepsIfItLoops;
        TStatusLine::handleEvent(event);
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

// A context menu that does not run its own event loop.
//
// TMenuPopup would have been the obvious base and cannot be used: its
// execute() is TMenuView::execute(), two hundred lines wrapped around a
// getEvent() loop, and running it from inside the pump's own handleEvent call
// stops Node's event loop for as long as the menu is open. The menu bar has
// always done exactly that -- see FINDINGS -- and it is Turbo Vision's own
// code, so it is left alone; nothing new is built on top of it.
//
// This one is driven by the pump like every other modal here, and that is what
// makes it flat. A submenu is the recursive owner->execView() in the middle of
// that loop; without submenus the whole state machine is a highlight, a click
// and two keys. Turbo Vision's own only context menu -- TEditor's Cut/Copy/
// Paste/Undo (teditor2.cpp:102) -- is flat too.
//
// TMenuBox is kept for the drawing: the frame, the hotkey highlighting, the
// right-aligned shortcut column and the menu palette are all its.
class JsMenuPopup : public TMenuBox {
public:
    JsMenuPopup(const TRect &bounds, TMenu *aMenu) noexcept;

    // What ~TMenuPopup does. TMenuView does not own its menu -- the menu bar's
    // outlives every box that shows it -- but a popup's is built for it.
    ~JsMenuPopup() { delete menu; }

    virtual void handleEvent(TEvent &event) override;

private:
    TMenuItem *itemAt(const TPoint &where);
    void moveTo(TMenuItem *item);
    void walk(bool forward);
    void pick();
    void cancel();

    // A mouse-up only counts once a mouse-down has landed inside. The click
    // that *asked* for this menu is still in flight when it opens -- the model
    // hears the press, answers with a Cmd, and the release arrives after the
    // box is on screen -- so without this the menu would close itself the
    // instant it appeared.
    bool armed = false;
};

// A text editor, and the first view whose contents do not cross the port on
// every render.
//
// Fourteen examples put the state in the model and re-rendered it, and that
// works because the state is small: a list of names, a calendar's month, a
// canvas of a few hundred cells. A document is the first thing where it does
// not. `view` runs on every tick of every subscription, so a `text` field on
// this view would serialise the whole file into the render message once a
// second forever -- and the model would also have to implement insert,
// delete, word-left, undo and the clipboard, which is to say implement
// TEditor.
//
// So the boundary moves, and it moves exactly one step: **TEditor owns the
// buffer, and the model owns the file.** The document crosses the port twice
// per file rather than once per render -- in through setEditorText, out
// through readEditor -- and what the model is told in between is that an edit
// happened and where the cursor is, which is three numbers.
//
// Buffer management is TFileEditor's, without the file: malloc/free/hand-
// rolled realloc, overriding the three virtuals TEditor calls. The base
// constructor's initBuffer() runs before this class exists, so it allocates
// with new[] and the constructor here frees it with TEditor::doneBuffer()
// before allocating its own -- which is what TFileEditor's constructor does,
// for the same reason.
class JsEditor : public TEditor {
public:
    JsEditor(const TRect &bounds, TScrollBar *hScroll, TScrollBar *vScroll,
             std::string id) noexcept;

    virtual void handleEvent(TEvent &event) override;
    virtual void initBuffer() override;
    virtual void doneBuffer() override;
    virtual Boolean setBufSize(uint newSize) override;

    // Replace the whole document, as TFileEditor::loadFile does: size the
    // buffer, drop the text in at the top of it, and start again with an
    // empty undo and a clean modified flag.
    bool setText(const std::string &text);
    std::string getWholeText();

    // Find, or find-and-replace, from the caret forward. Returns how many
    // matches were acted on: 0 or 1 for a find, however many were replaced
    // otherwise.
    //
    // TEditor has cmFind and cmReplace of its own and they are not used,
    // because both begin by asking editorDialog for a search string and
    // editorDialog is deliberately inert here -- every prompt it raises is a
    // messageBox, which is an execView. The model already has the string by
    // the time this is called, so what is left is TEditor::search(), which is
    // public, and the replace loop out of doSearchReplace() with the
    // per-occurrence prompt taken out of it.
    int searchAndReplace(const std::string &what, bool replace,
                         const std::string &replacement, bool matchCase,
                         bool wholeWords, bool all);

    // Put the caret on a line and a column, the two numbers the model was
    // last told by an `Edited` event.
    //
    // It exists because setText() resets the caret to the top, which is a
    // reasonable thing for "here is a different document" to do and the wrong
    // thing for "here is this document, reflowed". A model that rewrites what
    // it just read has to be able to put the reader back where they were, and
    // there was no way to say it.
    //
    // Walked line by line with nextLine() and then across with charPtr(),
    // because a column in TEditor is a *display* column and not a byte -- the
    // same number curPos.x carries, so a caret restored from an Edited event
    // lands where that event said it was. Both are clamped by the walk itself
    // rather than checked: nextLine() stops at bufLen and charPtr() stops at
    // the end of its line, so a line past the end is the last line and a
    // column past the end is the end of that line, which is what every editor
    // does with Down and End.
    //
    // selectMode 0 rather than smExtend, so the selection collapses to the
    // caret: this is a move, not a drag. trackCursor(False) scrolls the least
    // it can to bring it into view, which is what typing there would have done.
    void setCaret(int line, int column)
    {
        uint p = 0;
        for (int i = 0; i < line && p < bufLen; ++i)
            p = nextLine(p);
        setCurPtr(charPtr(p, column < 0 ? 0 : column), 0);
        trackCursor(False);
        noteEditIfChanged();
    }

    // Text in at the caret, replacing the selection. `insertText` is
    // `insertBuffer` with the buffer arithmetic done for us (editors.h:219),
    // so the undo record, the modified flag and the scroll bars all end up
    // where typing the same characters would have left them -- and the model
    // is told afterwards, through the same sandwich every other edit uses.
    bool insertAtCaret(const std::string &text)
    {
        Boolean ok = insertText(text.data(), (uint) text.size(), False);
        noteEditIfChanged();
        return ok == True;
    }

private:
    // Queued only when something the model would notice actually changed --
    // an arrow key that moves the caret within a line reports, one that runs
    // into the end of the buffer does not.
    void noteEditIfChanged();

    std::string viewId;
    bool lastModified = false;
    int lastLine = -1;
    int lastColumn = -1;
    // Seeded to the impossible so that the first notification always goes out:
    // a model that greys Undo needs to be told it is off before anything has
    // happened, not only when something has.
    bool lastCanUndo = true;
    bool lastHasSelection = true;
    bool lastOverwrite = true;
};

class JsWindow : public TDialog {
public:
    JsWindow(const TRect &bounds, TStringView title, std::string id) noexcept
        : TWindowInit(&TDialog::initFrame), TDialog(bounds, title),
          windowId(std::move(id))
    {
    }

    // Which view this window was built focusing, so that "the caret has been
    // moved since" is answerable. Only ever compared against `current`, and
    // both die with the window. See MovedCaret in views.cc.
    TView *builtFocus = nullptr;

    ~JsWindow();

    virtual void handleEvent(TEvent &event) override;

    // Dragging a window, without the nested event loop that Turbo Vision
    // drags it with.
    //
    // `TView::dragView` (tview.cpp:232) is the one place all five routes into
    // moving or resizing a window end up: the frame's title bar, its two grow
    // corners, a middle-click on its body -- all through `TFrame::dragWindow`
    // -- and `cmResize` off the Window menu, through `TWindow::handleEvent`.
    // Every one of them then sits in `do { getEvent(event); } while(...)`
    // until the gesture ends, which is Node's loop stopped for the duration:
    // no timers, no promises, no subscriptions, no renders. The same nested
    // loop `JsMenuPopup` and `openLocalModal` exist to not have.
    //
    // For the mouse that is bad; for `cmResize` it is fatal. That mode ends
    // only on Enter or Esc, it swallows the mouse, the menu bar and Alt-X on
    // the way, and on a *maximized* window the size limits pin every arrow key
    // so not one cell on screen changes -- the only cue is the frame dropping
    // from a double line to a single one. It reads exactly like a hang, and
    // with `eventTimeoutMs` at 0 (app.cc, Start) the poll never sleeps, so it
    // is a hang that burns a core. Found by a user killing it with SIGKILL.
    //
    // dragView is virtual -- "temporary fix for Miller's stuff", views.h:361,
    // and the accident this port is built on -- so overriding it here catches
    // all five routes at once and no frame subclass is needed. It starts a
    // session and returns; the callers all clear the event straight after,
    // which is still exactly right. `draggingWindow()` is what the pump then
    // routes to, the same shape as `mouseCaptureView()` beside it.
    virtual void dragView(TEvent &event, uchar mode, TRect &limits,
                          TPoint minSize, TPoint maxSize) override;

    // One event of a drag in progress, from the pump. Swallows every event it
    // is given, because that is what the loop it replaces did.
    void dragEvent(TEvent &event);

    // The other half of a window that cannot be zoomed: saying so.
    //
    // TWindow::setState *enables* the commands a window supports when it is
    // selected and relies on the previously selected one having disabled its
    // own on the way out -- so a window with no zoom box inherits whatever the
    // last one left enabled, and a program whose first window is fixed-size
    // starts with cmZoom enabled because nothing ever turned it off. The
    // symptom is a lit F5 on the status line that does nothing, which is worse
    // than a greyed one. Upstream has the same gap for any window without
    // wfZoom; here it is reachable from the API, so it is worth closing.
    //
    // cmResize is deliberately not in this. A fixed-size window can still be
    // moved, and cmResize is the move as well as the grow.
    virtual void setState(ushort aState, Boolean enable) override
    {
        TDialog::setState(aState, enable);
        if (enable != False && (aState & sfSelected) != 0 &&
            (flags & wfZoom) == 0)
            {
            TCommandSet cannot;
            cannot += cmZoom;
            disableCommands(cannot);
            }
    }

    // Which of Turbo Vision's three colour sets this window is drawn in.
    // Unlike sizeLimits, this is read afresh every time a view asks for a
    // colour -- getPalette switches on it -- so it can be changed in place.
    //
    // redraw() and not drawView(). A group that has a buffer draws by blitting
    // it (TGroup::draw, tgroup.cpp:128), so drawView() on a window whose
    // colours just changed paints the cached ones straight back and nothing
    // appears to happen. redraw() is drawSubViews, which asks every child for
    // its colour again -- which is the only thing that reaches a palette.
    void setWindowPalette(short which)
    {
        if (palette == which)
            return;
        palette = which;
        redraw();
    }

    // Which of the two dimensions the user is allowed to change.
    //
    // Turbo Vision asks a view for its own limits rather than keeping a rule
    // anywhere central, and every route that could change a window's size goes
    // through this one call: TFrame::dragWindow for the resize handle,
    // TWindow::zoom for the zoom box -- and TFrame::draw, which is why the box
    // stops offering a zoom it cannot do -- TView::locate for setBounds, and
    // TView::calcBounds for growMode following the terminal. Pinning a
    // dimension here pins it on all five, with nothing else to remember.
    //
    // A pinned dimension is pinned at the size the window was *built* at and
    // not at whatever it drifted to, because the model wrote that number.
    virtual void sizeLimits(TPoint &min, TPoint &max) override
    {
        TDialog::sizeLimits(min, max);
        if (!canResizeWidth)
            {
            min.x = builtSize.x;
            max.x = builtSize.x;
            }
        if (!canResizeHeight)
            {
            min.y = builtSize.y;
            max.y = builtSize.y;
            }
    }

    bool canResizeWidth = true;
    bool canResizeHeight = true;
    TPoint builtSize = {0, 0};

    // What `TView::dragView` keeps on the stack of the loop this replaces.
    struct Drag {
        bool active = false;
        bool byMouse = false;
        uchar mode = 0;             // dragView's `mode`: dmDrag* | dmLimit*
        TRect limits = TRect(0, 0, 0, 0);
        TPoint minSize = {0, 0};
        TPoint maxSize = {0, 0};
        // Esc goes back to this. Only the keyboard mode can cancel -- a mouse
        // drag ends where the button came up, as it does everywhere.
        TRect saved = TRect(0, 0, 0, 0);
        // dragView's `p`: what to add to the pointer to get back to the corner
        // the gesture grabbed, computed once from the press.
        TPoint grip = {0, 0};
        // dmDragGrowLeft only, and it has to be kept rather than recomputed:
        // the loop mutates a.x and b.y each turn and leaves b.x and a.y at the
        // values the press saw.
        TRect bounds = TRect(0, 0, 0, 0);
    };
    Drag drag;

    void endDrag();

    // What the resize poll last saw. Seeded when the window is built, so that
    // building one is not itself reported as a resize.
    TRect lastReported = TRect(0, 0, 0, 0);

    // JsWindow derives from TDialog so that a window and a dialog are one
    // class -- but TDialog's constructor takes the window-ness back out:
    // growMode = 0, flags = wfMove | wfClose, ofTileable never set by anything
    // in Turbo Vision except TEditWindow, and -- the one that went unnoticed
    // for eighteen examples -- palette = dpGrayDialog, written over the
    // wpBlueWindow TWindow's own constructor had just set.
    //
    // That last one is why every window in every program built on this was
    // white on light grey: the colours of the Find box in tvedit's screenshot
    // rather than of the editor behind it. A window on the desktop should
    // zoom, resize, grow with the terminal, take part in Tile and Cascade, and
    // be blue, so a non-modal one puts all five back. Modal dialogs never come
    // through here and stay grey, which is the distinction Turbo Vision has
    // always drawn between the two.
    //
    // dpBlueDialog and not wpBlueWindow, though the two are both 0 and either
    // would compile to the same thing. getPalette() here is TDialog's, which
    // switches on the dp* names, and it has to be: a JsWindow can hold buttons,
    // input lines and list boxes, and those ask for palette entries past the
    // eight a cpBlueWindow has. The window sets are the right *idea* and the
    // wrong length, and Borland made the first entries of cpBlueDialog agree
    // with cpBlueWindow precisely so that a dialog could look like a window.
    void beWindow()
    {
        flags = wfMove | wfGrow | wfClose | wfZoom;
        growMode = gfGrowAll | gfGrowRel;
        options |= ofTileable;
        palette = dpBlueDialog;
        zoomRect = getBounds();
        builtSize = size;
        lastReported = getBounds();
    }

    // Somewhere for a window born at its maximum size to un-zoom to.
    //
    // `TWindow::zoom` (twindow.cpp:218) is two branches: at less than the
    // maximum it stores the rectangle it has and maximizes, and at the maximum
    // it locates back to the stored one. `TWindow`'s constructor seeds that
    // store with the rectangle the window was *built* at -- which is right
    // until a window is built filling the desktop, as predc's environment list
    // and anything else that sizes itself from the terminal is. Then the
    // stored rectangle is the desktop, restoring puts the window exactly where
    // it already is, and the zoom box and F5 are both dead.
    //
    // And the frame is advertising otherwise. `TFrame::draw` (tframe.cpp:100)
    // asks `sizeLimits` and draws `unZoomIcon` -- `[↕]` rather than `[↑]` --
    // whenever the window is at its maximum, so the one window that cannot
    // un-zoom is the one drawing the un-zoom box. Same defect as the lit F5
    // that `setState` above exists to prevent, one level down, and worse:
    // there the promise was a menu entry, here it is a control being clicked.
    //
    // The rule is the failure condition itself -- **if restoring would leave
    // the window exactly where it is, there is nowhere to go**, so invent
    // somewhere; otherwise honour what is stored. No flag and no state, and it
    // is right in the cases a flag got wrong: a window built small that became
    // maximal because the *terminal* shrank still restores to the size it was
    // built at, and a window the user zoomed from full-width-and-five-rows
    // still comes back full-width and five rows.
    virtual void zoom() override;

    // The invented one: three-quarters of the desktop, centred, in whichever
    // dimensions the model left free.
    TRect threeQuarters(TPoint minSize, TPoint maxSize) const;

    // A stored rectangle made to fit the desktop it is being restored onto.
    // `TWindow::zoom` hands `zoomRect` straight to `TView::locate`, which
    // clamps the *size* against sizeLimits and takes the origin as given -- so
    // a window zoomed on a wide terminal and un-zoomed on a narrow one comes
    // back the right size and hanging off the right-hand edge, or beside the
    // desktop entirely.
    //
    // `locate` is *not* where that belongs, though it looks like it: TView's
    // own `moveGrow` clamps the origin itself against `dragMode`'s limit bits,
    // and the default `dragMode` is `dmLimitLoY` alone, so a window may
    // deliberately be dragged off three of the four edges -- and `dragView`'s
    // Esc path restores exactly such a rectangle. The stale rectangle is the
    // window's, so the fit is the window's. Upstream has the same hole;
    // reported in doc/upstream-zoomrect-origin.md and patched on the fork's
    // `fix/zoomrect-origin`, and this stays until that lands.
    //
    // `drive_drag.py`'s `restore_checks` is what says this still matters: it
    // is the only place in the suite that zooms and resizes *in that order*,
    // and until it was written this function was load-bearing and unasserted.
    TRect fittedToDesktop(TRect r, TPoint minSize, TPoint maxSize) const;

    // The terminal changing size, which produces the same *symptom* as the
    // one above -- and not, as it turned out, by the same fix: the origin goes
    // unchecked in two places reached by two routes, and only one of them is
    // `calcBounds`.
    //
    // `TView::calcBounds` scales a `gfGrowRel` window's coordinates with the
    // desktop and then calls `fitToLimits` (tview.cpp:158), which clamps the
    // *width and height* against `sizeLimits` and never touches the origin. So
    // a window whose origin has been scaled to column 21 of a hundred-column
    // desktop, with its width clamped to the full hundred, ends at column 121:
    // no right border, no bottom border, and the part that is missing is the
    // part nobody can see. Shrinking a tmux pane to twenty-four columns and
    // dragging it back is enough to produce it, in any Turbo Vision program.
    void calcBounds(TRect &bounds, TPoint delta) override;

    // A window the model says cannot be resized in either direction has no
    // resize handle and no zoom box, because both would be corners the user
    // can grab and nothing would move. One dimension pinned keeps them: a
    // window that only grows downwards is still worth dragging and still worth
    // zooming, and sizeLimits is what makes the zoom full-height rather than
    // full-screen.
    // One of TWindow's flag bits, on or off, with the frame redrawn to match.
    // `TFrame::draw` consults `flags` for which corners it puts a close box and
    // a zoom box in, so nothing else has to be rebuilt.
    void setFlag(ushort bit, bool on)
    {
        ushort was = flags;
        if (on)
            flags |= bit;
        else
            flags &= ~bit;
        if (flags != was && frame != nullptr)
            frame->drawView();
    }

    void setResize(bool width, bool height)
    {
        canResizeWidth = width;
        canResizeHeight = height;
        if (!width && !height)
            flags &= ~(wfGrow | wfZoom);
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

    // The resize poll walks every open window once per pump, which is what
    // lets a size change be noticed whichever of the five routes changed it.
    const std::unordered_map<std::string, JsWindow *> &openWindows() const
    {
        return windows;
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

// And a multi-state cluster's, as one state index per box.
Napi::Array markArray(const Napi::Env &env, const std::vector<int> &states);

void noteChangedText(const std::string &id, const std::string &text);
void noteChangedFlags(const std::string &id, uint32_t bits, uint32_t count);
void noteChangedChoice(const std::string &id, int index);
void noteChangedMarks(const std::string &id, const std::vector<int> &states);

// An Editor was edited, or its caret moved. Queued and coalesced per id like
// the value notes, and for the same reason: typing a word is one note, not one
// per letter. It deliberately does not carry the document -- see JsEditor.
void noteEdited(const std::string &id, bool modified, int line, int column,
                bool canUndo, bool hasSelection, bool overwrite);

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
//
// `rightButton` is the only reason a model would want to know which button was
// pressed, and it is why: a right click is what opens a context menu, and the
// model is the only thing that knows what should be in one.
void dispatchClick(const std::string &id, int x, int y, bool doubled,
                   bool rightButton);

// The pointer moved with a button held, or the button came up and ended the
// gesture. Queued rather than dispatched, and collapsed per canvas, for the
// same reason a scroll bar's positions are: only the latest one means
// anything, and a model that re-rendered on each cell the pointer crossed
// would redraw the window a dozen times per gesture.
void noteDragged(const std::string &id, int x, int y, bool done);

// The view a drag belongs to, or nullptr when no button is down on a canvas.
// The pump consults this instead of letting `TGroup::handleEvent` route by
// where the pointer is now -- see the long note in views.cc for why a drag
// needs a capture and why this one is not Turbo Vision's.
TView *mouseCaptureView();

// The window in the middle of a move or a resize, or nullptr. The pump's third
// routing rule, and the reason JsWindow::dragView can return immediately: a
// gesture that owned the event loop now owns a pointer instead.
JsWindow *draggingWindow();
void clearMouseCapture();

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
TView *buildItems(const Napi::Env &env, TGroup *win, const Napi::Value &items,
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
                    std::function<void(TView *, ushort)> done,
                    bool viewIsGroup = true);

// End it. A modal view normally says it is finished by setting
// TGroup::endState, which only a group has; JsMenuPopup is a TMenuBox, so it
// says so here instead and the session keeps the slot on its behalf.
void endLocalModal(TView *view, ushort command);

void registerViewApi(Napi::Env env, Napi::Object exports);

} // namespace tvnode
