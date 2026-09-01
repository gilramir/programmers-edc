// The application, the event pump, and the module entry point.
//
// Milestone 1 was the blocking design: tv.run() called TApplication::run() and
// Node's event loop was starved until the app quit. tv.start() + tv.step() is
// the pumped one -- Node's loop drives TVision instead of the other way round,
// so timers, promises and I/O keep working while the TUI is up. Both are kept:
// examples/hello.js still uses run(), examples/demo.js uses the pump.
//
// Why this works, checked in the tvision source before it was written:
//   * TProgram::eventTimeoutMs (app.h:296) is a public static; at 0, getEvent
//     stops blocking.
//   * TGroup::execute() (tgroup.cpp:173) is four lines, and TGroup::endState is
//     public (views.h:919), so one iteration can be hoisted out here.
//   * THardwareInfo::waitForEvents flushes the screen *before* polling
//     (platform/hardware.cpp:105-113), which is on the path even at timeout 0,
//     so the display still repaints.

#include "tvnode.h"
#include "keys.h"

#include <unistd.h>

#include <memory>
#include <vector>

// TGroup::execView sets this while a modal view is up (tgroup.cpp:199). It is
// a plain global with external linkage, defined in tgroup.cpp and declared in
// no header -- so reaching it needs this line and no fork. It is read by
// exactly two places (TView::endModal and the status line's command
// enabling) and by no drawing code, which is what makes hoisting modality out
// of execView safe: windows behind a modal dialog still repaint.
extern TView *TheTopView;

namespace tvnode {

bool g_running = false;

/* ------------------------------------------------------------------ */
/*  Configuration captured from JS                                    */
/* ------------------------------------------------------------------ */

// TProgInit calls initMenuBar/initStatusLine from inside the TApplication
// constructor, and they are plain static functions with no user-data channel.
// So the JS-supplied description has to be parked in a global before the app
// is constructed. This is also why there can only be one app per process --
// TProgram::application, deskTop, menuBar and statusLine are all statics.

namespace {

// mmenu's whole point is submenus inside submenus, so an item that has items
// of its own is one -- the same shape at every level.
struct MenuItemDef {
    bool separator = false;
    std::string title;
    ushort command = 0;
    TKey key;
    std::string shortcut;   // right-aligned hint text, e.g. "Alt-X"
    std::vector<MenuItemDef> items;

    bool isSubMenu() const { return !items.empty(); }
};

struct StatusItemDef {
    std::string text;
    TKey key;
    ushort command = 0;
};

struct AppConfig {
    // A menu bar is just a menu: an entry with entries of its own is a
    // pull-down, and one without is a command sitting on the bar. tvision's
    // mmenu example puts "Next menu" on the bar exactly that way.
    std::vector<MenuItemDef> menus;
    std::vector<StatusItemDef> status;
};

AppConfig g_config;

// An Editor's edit, queued like the value notes. Separate from ChangeNote
// because what it carries is not a value: the document stays where it is and
// what crosses is three numbers.
struct EditNote {
    std::string id;
    bool modified = false;
    int line = 0;
    int column = 0;
};

std::vector<EditNote> g_editNotes;

Napi::FunctionReference g_onCommand;
Napi::FunctionReference g_onSelect;
Napi::FunctionReference g_onFocus;
Napi::FunctionReference g_onScroll;
Napi::FunctionReference g_onKey;
Napi::FunctionReference g_onClick;
Napi::FunctionReference g_onClose;
Napi::FunctionReference g_onResize;
Napi::FunctionReference g_onWindowResize;
Napi::FunctionReference g_onChange;
Napi::FunctionReference g_onEdit;

// Windows are destroyed wholesale when the application goes away; that is not
// news anyone needs, and calling into JS from inside the teardown would be a
// poor idea besides.
bool g_shuttingDown = false;

std::vector<std::string> g_closedWindows;

struct FocusNote {
    std::string id;
    int index;
    std::string text;
};

std::vector<FocusNote> g_focusNotes;

struct ScrollNote {
    std::string id;
    int value;
};

std::vector<ScrollNote> g_scrollNotes;

// node-gyp compiles with -fno-rtti, so there is no dynamic_cast to recover
// these from TProgram::menuBar / statusLine. We made them; we keep them.
JsMenuBar *g_menuBar = nullptr;
JsStatusLine *g_statusLine = nullptr;

// Set while a JS callback is throwing, so we can unwind the TVision loop and
// rethrow into JS once the terminal has been restored.
bool g_hasPendingError = false;
Napi::Reference<Napi::Value> g_pendingError;

bool g_inStep = false;
bool g_quitRequested = false;

// A modal dialog, minus the loop.
//
// TGroup::execView is twenty lines, of which exactly one is a problem: the
// nested p->execute() that blocks until the dialog closes. Everything else is
// bookkeeping -- save some state, mark the view sfModal, make it current, and
// put it all back afterwards. So we do the bookkeeping ourselves and let the
// pump drive the dialog's events, the same way step() already drives the
// application's. Modality is preserved (input goes only to the top modal view)
// and Node's event loop never stops.
struct ModalSession {
    TView *view = nullptr;
    TGroup *host = nullptr;
    std::string id;

    // Set for a modal a *view* opened rather than the model: a history
    // drop-down, and anything else a wrapped widget pops up for itself. When
    // it is set the session has no promise to resolve and no fields to
    // collect -- the callback is the whole result, and it runs while the view
    // is still alive.
    std::function<void(TView *, ushort)> onDone;

    // Saved by beginModal, restored by finishModal -- the same set execView
    // saves and restores.
    ushort saveOptions = 0;
    TGroup *saveOwner = nullptr;
    TView *saveTopView = nullptr;
    TView *saveCurrent = nullptr;
    TCommandSet saveCommands;

    // Set for a dialog the model opened, and null for a drop-down a view
    // opened: those two are the only ways onto this stack, and exactly one of
    // `deferred` and `onDone` is set on any session.
    std::unique_ptr<Napi::Promise::Deferred> deferred;

    // Turbo Vision ends a modal by setting TGroup::endState, and only a group
    // has one. Every modal on this stack was a window until the popup menu,
    // which is a TMenuBox -- so the session says which kind it is holding
    // rather than the pump assuming, and keeps the slot itself for the kind
    // that has nowhere to put it. Reading a TGroup member off a plain TView
    // reads past the end of the object, which is a bug that would have shown
    // up as something else entirely.
    bool viewIsGroup = true;
    ushort ended = 0;

    ushort endState() const
    {
        return viewIsGroup ? ((TGroup *) view)->endState : ended;
    }

    void clearEndState()
    {
        if (viewIsGroup)
            ((TGroup *) view)->endState = 0;
        else
            ended = 0;
    }
};

// A stack: a dialog opened from a dialog is ordinary.
std::vector<std::unique_ptr<ModalSession>> g_modals;

} // namespace

/* ------------------------------------------------------------------ */
/*  Config parsing                                                    */
/* ------------------------------------------------------------------ */

static std::vector<MenuItemDef> parseMenuItems(const Napi::Env &env,
                                               const Napi::Value &value);

static MenuItemDef parseMenuItem(const Napi::Env &env, const Napi::Object &it)
{
    MenuItemDef item;
    if (getBool(it, "separator"))
        {
        item.separator = true;
        return item;
        }
    item.title = getString(it, "title");
    item.key = getKey(env, it, "key", "menu item '" + item.title + "'");
    item.shortcut = getString(it, "shortcut");
    if (it.Has("items"))
        item.items = parseMenuItems(env, it.Get("items"));
    else
        item.command = g_commands.intern(getString(it, "cmd"));
    return item;
}

static std::vector<MenuItemDef> parseMenuItems(const Napi::Env &env,
                                               const Napi::Value &value)
{
    std::vector<MenuItemDef> items;
    if (!value.IsArray())
        throw Napi::Error::New(env, "tvision: menu items must be an array");
    Napi::Array array = value.As<Napi::Array>();
    for (uint32_t i = 0; i < array.Length(); ++i)
        items.push_back(parseMenuItem(env, array.Get(i).As<Napi::Object>()));
    return items;
}

static std::vector<MenuItemDef> parseMenuBar(const Napi::Env &env,
                                             const Napi::Value &value)
{
    return parseMenuItems(env, value);
}


static std::vector<StatusItemDef> parseStatusLine(const Napi::Env &env,
                                                  const Napi::Value &value)
{
    if (!value.IsArray())
        throw Napi::Error::New(env, "tvision: statusLine must be an array");
    Napi::Array items = value.As<Napi::Array>();

    std::vector<StatusItemDef> out;
    for (uint32_t i = 0; i < items.Length(); ++i)
        {
        Napi::Object it = items.Get(i).As<Napi::Object>();
        StatusItemDef item;
        item.text = getString(it, "text");
        item.key = getKey(env, it, "key", "status item '" + item.text + "'");
        item.command = g_commands.intern(getString(it, "cmd"));
        out.push_back(std::move(item));
        }
    return out;
}


/* ------------------------------------------------------------------ */
/*  The application                                                   */
/* ------------------------------------------------------------------ */

/* ------------------------------------------------------------------ */
/*  The application palette                                           */
/* ------------------------------------------------------------------ */

// Turbo Vision's application palette is one hundred and thirty-five colour
// attributes, and every colour on the screen that this package draws rather
// than the model comes out of it. The layout is fixed and is the reason a
// theme can be described in seventeen fields instead of a hundred and
// thirty-five:
//
//      1        the desktop
//      2-7      the menu bar and the status line
//      8-15     the blue window set
//      16-23    the cyan window set
//      24-31    the gray window set
//      32-63    the gray dialog set
//      64-95    the blue dialog set
//      96-127   the cyan dialog set
//      128-135  the help viewer
//
// The window sets are eight entries and the dialog sets are thirty-two, and
// the first eight of a dialog set mean the same things as a window set --
// frame, scroll bar, text -- which is what lets one Panel describe both. A
// JsWindow is a TDialog, so what it actually reads is a *dialog* set; the
// window sets are filled in from the same Panel so that anything reaching them
// (a TWindow this package did not build) is at least consistent.
struct ThemePair {
    TColorAttr attr = {};
};

// One coloured surface: a window, the alternate window, or a dialog.
struct ThemePanel {
    TColorAttr frame;          // an inactive frame, and the surface's ground
    TColorAttr frameActive;
    TColorAttr text;           // body text and static text
    TColorAttr accent;         // hot keys
    TColorAttr selected;       // the focused row, the selected text
    TColorAttr disabled;
    // Buttons and input lines are separate because Turbo Vision colours them
    // separately and is right to: a button is raised and an input line is
    // recessed, and in the stock scheme a grey dialog's buttons are black on
    // green while its fields are white on blue. One `control` for both made
    // every text field look like a button.
    TColorAttr button;
    TColorAttr buttonAccent;
    TColorAttr input;
    TColorAttr inputAccent;
    TColorAttr scrollBar;
};

struct ThemeSpec {
    bool set = false;
    TColorAttr desktop;
    TColorAttr bar;
    TColorAttr barAccent;
    TColorAttr barDisabled;
    TColorAttr barSelected;
    TColorAttr barSelectedDisabled;
    TColorAttr barSelectedAccent;
    ThemePanel window;
    ThemePanel alternate;
    ThemePanel dialog;
};

static ThemeSpec g_theme;

// A window set: eight entries, in Turbo Vision's order.
static void writeWindowSet(TColorAttr *at, const ThemePanel &p)
{
    at[0] = p.frame;         // 1  frame, passive
    at[1] = p.frameActive;   // 2  frame, active
    at[2] = p.frameActive;   // 3  frame icons
    at[3] = p.scrollBar;     // 4  scroll bar page
    at[4] = p.scrollBar;     // 5  scroll bar controls
    at[5] = p.text;          // 6  normal text
    at[6] = p.selected;      // 7  selected text
    at[7] = p.text;          // 8  reserved
}

// A dialog set: thirty-two entries, and the only place the list of them is
// written down.
//
// **Derived from the views rather than from the book.** The first version of
// this took the order from the Turbo Vision Programming Guide and had the list
// viewer two slots late, so a file dialog's rows came out in the scroll bar's
// colours -- which nothing reported, because no test asserted on a list row.
// The authority is each view's own palette string, and every line below is one
// of them:
//
//      cpScrollBar     "\x04\x05\x05"                  tscrlbar.cpp:37
//      cpStaticText    "\x06"                          tstatict.cpp:30
//      cpLabel         "\x07\x08\x09\x09"              tlabel.cpp:28
//      cpButton        "\x0A\x0B\x0C\x0D\x0E\x0E\x0E\x0F"  tbutton.cpp:41
//      cpCluster       "\x10\x11\x12\x12\x1f"          tcluster.cpp:39
//      cpInputLine     "\x13\x13\x14\x15"              tinputli.cpp:84
//      cpHistory       "\x16\x17"                      thistory.cpp:37
//      cpHistoryWindow "\x13\x13\x15\x18\x17\x13\x14"  thistwin.cpp:26
//      cpListViewer    "\x1A\x1A\x1B\x1C\x1D"          tlstview.cpp:30
//      cpInfoPane      "\x1E"                          stddlg.cpp:67
//
// Note that cpCluster's fifth colour is 0x1F, so a disabled check box is slot
// 31 rather than anywhere near the other three -- which is exactly the kind of
// thing a list written from memory gets wrong.
static void writeDialogSet(TColorAttr *at, const ThemePanel &p)
{
    at[0] = p.frame;           // 1  frame, passive
    at[1] = p.frameActive;     // 2  frame, active
    at[2] = p.frameActive;     // 3  frame icons
    at[3] = p.scrollBar;       // 4  scroll bar page
    at[4] = p.scrollBar;       // 5  scroll bar controls
    at[5] = p.text;            // 6  static text
    at[6] = p.text;            // 7  label, normal
    // 8 is the label of the field that has the focus, and it is *emphasis*
    // rather than a selection: the stock scheme brightens the text and leaves
    // it on the panel's ground. Mapping it to `selected` put a coloured block
    // behind the word "Name" in every dialog, which is the sort of thing that
    // looks intentional until it is pointed at.
    at[7] = p.frameActive;     // 8  label, highlighted
    at[8] = p.accent;          // 9  label, shortcut
    at[9] = p.button;          // 10 button, normal
    at[10] = p.button;         // 11 button, default
    at[11] = p.selected;       // 12 button, selected
    at[12] = p.disabled;       // 13 button, disabled
    at[13] = p.buttonAccent;   // 14 button, shortcut
    at[14] = p.frame;          // 15 button, shadow
    at[15] = p.text;           // 16 cluster, normal
    at[16] = p.selected;       // 17 cluster, selected
    at[17] = p.accent;         // 18 cluster, shortcut
    at[18] = p.input;          // 19 input line, normal (and history window)
    at[19] = p.selected;       // 20 input line, selected
    at[20] = p.inputAccent;    // 21 input line, arrows
    at[21] = p.inputAccent;    // 22 history, arrow
    at[22] = p.input;          // 23 history, sides
    at[23] = p.scrollBar;      // 24 history window, scroll bar
    at[24] = p.scrollBar;      // 25 -- reached by nothing in the library
    at[25] = p.text;           // 26 list viewer, normal
    at[26] = p.selected;       // 27 list viewer, focused
    at[27] = p.accent;         // 28 list viewer, selected
    at[28] = p.disabled;       // 29 list viewer, divider
    at[29] = p.text;           // 30 info pane
    at[30] = p.disabled;       // 31 cluster, disabled
    at[31] = p.text;           // 32 -- reached by nothing in the library
}

// The whole thing, in the order above.
static void buildAppPalette(TColorAttr *at, const ThemeSpec &t)
{
    at[0] = t.desktop;
    at[1] = t.bar;
    at[2] = t.barDisabled;
    at[3] = t.barAccent;
    at[4] = t.barSelected;
    // Disabled *and* highlighted, so the ink is the disabled one and the
    // ground is the selected one -- which is what the stock scheme does and
    // what putting barDisabled here straight did not.
    at[5] = t.barSelectedDisabled;
    at[6] = t.barSelectedAccent;
    writeWindowSet(at + 7, t.window);
    writeWindowSet(at + 15, t.alternate);
    writeWindowSet(at + 23, t.dialog);
    writeDialogSet(at + 31, t.dialog);
    writeDialogSet(at + 63, t.window);
    writeDialogSet(at + 95, t.alternate);
    // The help viewer, which this package does not build -- see the note in
    // examples/README about THelpFile -- filled from the window panel so that
    // nothing in the table is left at whatever the stock byte was.
    writeWindowSet(at + 127, t.window);
}

// data[0] is the length and the entries are at [1..135], which is why every
// write below is offset by one (palette.cpp:26).
static TPalette &stockPalette()
{
    static TPalette p(cpAppColor, sizeof(cpAppColor) - 1);
    return p;
}

static TPalette &themedPalette()
{
    static TPalette p(cpAppColor, sizeof(cpAppColor) - 1);
    return p;
}

class JsApp : public TApplication {
public:
    JsApp() noexcept
        : TProgInit(&JsApp::initStatusLine, &JsApp::initMenuBar,
                    &JsApp::initDeskTop)
    {
    }

    virtual void handleEvent(TEvent &event) override;

    // The model's theme, when it sent one, and Turbo Vision's own otherwise.
    //
    // Overwriting a palette in place and forcing a repaint is what tvdemo's
    // own colour dialog does (tvdemo2.cpp:349), and is the only precedent
    // there is for changing a scheme while a program is running.
    virtual TPalette &getPalette() const override
    {
        return g_theme.set ? themedPalette() : stockPalette();
    }

    static TMenuBar *initMenuBar(TRect r);
    static TStatusLine *initStatusLine(TRect r);
};

static std::unique_ptr<JsApp> g_app;

static TMenuItem *makeMenuItem(const MenuItemDef &def);

// Items must be appended while the submenu's `next` is still null: operator+
// walks to the *last* submenu in the chain before inserting, so a nested menu
// has to be built bottom-up.
static void appendItems(TSubMenu *sub, const std::vector<MenuItemDef> &items)
{
    for (const MenuItemDef &def : items)
        {
        // The static type decides the overload. operator+(TSubMenu&, TMenuItem&)
        // puts the entry *inside* this submenu; operator+(TSubMenu&, TSubMenu&)
        // would make it a sibling, which on the menu bar means a whole extra
        // pull-down. makeMenuItem returning TMenuItem* is what keeps this right.
        *sub + *makeMenuItem(def);
        }
}

static TMenuItem *makeMenuItem(const MenuItemDef &def)
{
    if (def.separator)
        return &newLine();

    if (def.isSubMenu())
        {
        TSubMenu *sub = new TSubMenu(def.title.c_str(), def.key);
        appendItems(sub, def.items);
        return sub;
        }

    return new TMenuItem(def.title.c_str(), def.command, def.key, hcNoContext,
                         def.shortcut.empty() ? TStringView()
                                              : TStringView(def.shortcut.c_str()));
}

static TMenu *buildMenu(const std::vector<MenuItemDef> &items)
{
    TMenuItem *head = nullptr;
    for (const MenuItemDef &def : items)
        {
        TMenuItem *made = makeMenuItem(def);
        if (head == nullptr)
            head = made;
        else
            *head + *made;   // sibling chain: the entries along the bar
        }
    return head == nullptr ? nullptr : new TMenu(*head);
}

static TStatusDef *buildStatusDef(const std::vector<StatusItemDef> &items)
{
    if (items.empty())
        return nullptr;

    TStatusDef *def = new TStatusDef(0, 0xFFFF);
    for (const StatusItemDef &item : items)
        *def + *new TStatusItem(item.text.empty()
                                    ? TStringView()
                                    : TStringView(item.text.c_str()),
                                item.key, item.command);
    return def;
}

TMenuBar *JsApp::initMenuBar(TRect r)
{
    r.b.y = r.a.y + 1;
    TMenu *menu = buildMenu(g_config.menus);
    if (menu == nullptr)
        return nullptr;
    g_menuBar = new JsMenuBar(r, menu);
    return g_menuBar;
}

TStatusLine *JsApp::initStatusLine(TRect r)
{
    r.a.y = r.b.y - 1;
    TStatusDef *defs = buildStatusDef(g_config.status);
    if (defs == nullptr)
        return nullptr;
    g_statusLine = new JsStatusLine(r, *defs);
    return g_statusLine;
}

void JsApp::handleEvent(TEvent &event)
{
    TApplication::handleEvent(event);

    if (event.what == evCommand && event.message.command >= kUserCmdFirst)
        {
        if (const std::string *name = g_commands.nameOf(event.message.command))
            {
            dispatchCommand(*name);
            clearEvent(event);
            }
        }
}

/* ------------------------------------------------------------------ */
/*  Calling into JS                                                   */
/* ------------------------------------------------------------------ */

static void noteJsError(const Napi::Env &env, const Napi::Value &error)
{
    g_hasPendingError = true;
    g_pendingError = Napi::Reference<Napi::Value>::New(error, 1);

    if (TProgram::application != nullptr)
        {
        // Unwind the event loop so the terminal is restored before the
        // exception surfaces in JS.
        TEvent quit = {};
        quit.what = evCommand;
        quit.message.command = cmQuit;
        TProgram::application->putEvent(quit);
        }
}

// A handle scope per dispatch matters more than it looks: under the blocking
// run(), we never return to Node, so without one every string handed to a
// callback would pile up for the lifetime of the application.
static void callJs(Napi::FunctionReference &fn, const std::vector<napi_value> &args)
{
    if (fn.IsEmpty() || g_hasPendingError)
        return;

    Napi::Env env = fn.Env();
    try
        {
        fn.Call(args);
        }
    catch (const Napi::Error &e)
        {
        noteJsError(env, e.Value());
        }
    catch (const std::exception &e)
        {
        noteJsError(env,
                    Napi::Error::New(env, std::string("tvision: ") + e.what()).Value());
        }
}

void dispatchCommand(const std::string &name)
{
    if (g_onCommand.IsEmpty() || g_hasPendingError)
        return;

    Napi::Env env = g_onCommand.Env();
    Napi::HandleScope scope(env);
    callJs(g_onCommand, {Napi::String::New(env, name)});
}

void dispatchSelect(const std::string &id, int index, const std::string &text)
{
    if (g_onSelect.IsEmpty() || g_hasPendingError)
        return;

    Napi::Env env = g_onSelect.Env();
    Napi::HandleScope scope(env);
    callJs(g_onSelect, {
                           Napi::String::New(env, id),
                           Napi::Number::New(env, index),
                           Napi::String::New(env, text),
                       });
}

void dispatchKey(const std::string &id, const std::string &key)
{
    if (g_onKey.IsEmpty() || g_hasPendingError)
        return;

    Napi::Env env = g_onKey.Env();
    Napi::HandleScope scope(env);
    callJs(g_onKey, {Napi::String::New(env, id), Napi::String::New(env, key)});
}

void noteFocused(const std::string &id, int index, const std::string &text)
{
    if (g_onFocus.IsEmpty() || g_shuttingDown)
        return;
    g_focusNotes.push_back({id, index, text});
}

// Drained by the pump, between events -- see the note in tvnode.h.
static void flushFocused()
{
    if (g_focusNotes.empty() || g_onFocus.IsEmpty() || g_hasPendingError)
        {
        g_focusNotes.clear();
        return;
        }

    std::vector<FocusNote> notes;
    notes.swap(g_focusNotes);

    Napi::Env env = g_onFocus.Env();
    Napi::HandleScope scope(env);
    for (const FocusNote &note : notes)
        callJs(g_onFocus, {
                              Napi::String::New(env, note.id),
                              Napi::Number::New(env, note.index),
                              Napi::String::New(env, note.text),
                          });
}

void noteScrolled(const std::string &id, int value)
{
    if (g_onScroll.IsEmpty() || g_shuttingDown)
        return;
    // Only the last position matters. A drag on the thumb calls scrollDraw()
    // for every cell it passes, and a model that re-rendered on each of those
    // would be redrawing the window a dozen times per gesture.
    for (ScrollNote &note : g_scrollNotes)
        if (note.id == id)
            {
            note.value = value;
            return;
            }
    g_scrollNotes.push_back({id, value});
}

// Drained by the pump, between events.
static void flushScrolled()
{
    if (g_scrollNotes.empty() || g_onScroll.IsEmpty() || g_hasPendingError)
        {
        g_scrollNotes.clear();
        return;
        }

    std::vector<ScrollNote> notes;
    notes.swap(g_scrollNotes);

    Napi::Env env = g_onScroll.Env();
    Napi::HandleScope scope(env);
    for (const ScrollNote &note : notes)
        callJs(g_onScroll, {Napi::String::New(env, note.id),
                            Napi::Number::New(env, note.value)});
}

// A value the user changed, waiting for the safe point. `bits` is only filled
// in for a cluster; which of the three it is decides what reaches JavaScript.
struct ChangeNote {
    std::string id;
    enum Kind { Text, Flags, Choice, Marks } kind;
    std::string text;
    uint32_t bits = 0;
    uint32_t count = 0;
    int index = 0;
    std::vector<int> states;
};

static std::vector<ChangeNote> g_changeNotes;

// Collapsed per id, like the scroll notes: typing a word is one keystroke per
// letter and the model wants the word, not the letters. What is reported is
// always the current value, so dropping an older one loses nothing.
static void pushChange(const ChangeNote &note)
{
    if (g_onChange.IsEmpty() || g_shuttingDown)
        return;
    for (ChangeNote &existing : g_changeNotes)
        if (existing.id == note.id)
            {
            existing = note;
            return;
            }
    g_changeNotes.push_back(note);
}

void noteChangedText(const std::string &id, const std::string &text)
{
    ChangeNote note;
    note.id = id;
    note.kind = ChangeNote::Text;
    note.text = text;
    pushChange(note);
}

void noteChangedFlags(const std::string &id, uint32_t bits, uint32_t count)
{
    ChangeNote note;
    note.id = id;
    note.kind = ChangeNote::Flags;
    note.bits = bits;
    note.count = count;
    pushChange(note);
}

void noteChangedChoice(const std::string &id, int index)
{
    ChangeNote note;
    note.id = id;
    note.kind = ChangeNote::Choice;
    note.index = index;
    pushChange(note);
}

void noteChangedMarks(const std::string &id, const std::vector<int> &states)
{
    ChangeNote note;
    note.id = id;
    note.kind = ChangeNote::Marks;
    note.states = states;
    pushChange(note);
}

void noteEdited(const std::string &id, bool modified, int line, int column)
{
    if (g_onEdit.IsEmpty() || g_shuttingDown)
        return;
    for (EditNote &existing : g_editNotes)
        if (existing.id == id)
            {
            existing = EditNote{id, modified, line, column};
            return;
            }
    g_editNotes.push_back(EditNote{id, modified, line, column});
}

static void flushEdited()
{
    if (g_editNotes.empty() || g_onEdit.IsEmpty() || g_hasPendingError)
        {
        g_editNotes.clear();
        return;
        }

    std::vector<EditNote> notes;
    notes.swap(g_editNotes);

    Napi::Env env = g_onEdit.Env();
    Napi::HandleScope scope(env);
    for (const EditNote &note : notes)
        callJs(g_onEdit, {Napi::String::New(env, note.id),
                          Napi::Boolean::New(env, note.modified),
                          Napi::Number::New(env, note.line),
                          Napi::Number::New(env, note.column)});
}

static void flushChanged()
{
    if (g_changeNotes.empty() || g_onChange.IsEmpty() || g_hasPendingError)
        {
        g_changeNotes.clear();
        return;
        }

    std::vector<ChangeNote> notes;
    notes.swap(g_changeNotes);

    Napi::Env env = g_onChange.Env();
    Napi::HandleScope scope(env);
    for (const ChangeNote &note : notes)
        {
        Napi::Value value;
        if (note.kind == ChangeNote::Text)
            value = Napi::String::New(env, note.text);
        else if (note.kind == ChangeNote::Flags)
            value = checkedArray(env, note.bits, note.count);
        else if (note.kind == ChangeNote::Marks)
            value = markArray(env, note.states);
        else
            value = Napi::Number::New(env, note.index);
        callJs(g_onChange, {Napi::String::New(env, note.id), value});
        }
}

// How big the desktop was the last time the model was told. Zero means "never
// told", which is what makes the first pass after startup report the real size
// without a special case for it.
static TPoint g_lastDeskSize = {0, 0};

// Polled at the pump's safe point rather than hooked onto cmScreenChanged.
//
// TVision learns about a resize in three different places -- a SIGWINCH, a
// WINDOW_BUFFER_SIZE_EVENT, a setScreenMode() somebody called -- and they all
// end at the same place, which is the desktop having different bounds than it
// had before. Comparing the bounds is true whichever route was taken, and it
// is a comparison of two integers once per pump.
//
// The desktop's size and not the screen's, because a window's rectangle is in
// desktop coordinates. Reporting 80x25 to a model that has to subtract the
// menu bar and the status line for itself would be handing it the arithmetic
// this exists to remove.
static void flushResize()
{
    if (g_onResize.IsEmpty() || g_hasPendingError || g_shuttingDown || !g_app)
        return;

    TPoint size = g_app->deskTop->size;
    if (size.x == g_lastDeskSize.x && size.y == g_lastDeskSize.y)
        return;
    g_lastDeskSize = size;

    Napi::Env env = g_onResize.Env();
    Napi::HandleScope scope(env);
    callJs(g_onResize, {Napi::Number::New(env, size.x),
                        Napi::Number::New(env, size.y)});
}

// The same trick as flushResize, one level down.
//
// A window's bounds can change by five different routes -- the frame's resize
// handle, its zoom box, Tile, Cascade, and growMode carrying it along when the
// terminal changes size -- and there is no single call they share that JS could
// be hung off. What they do share is the window afterwards having different
// bounds than it had before, so this compares, once per pump, per window. It is
// four integer comparisons for each open window and there are never many.
//
// It reports the whole rectangle rather than only the size, because a window
// that was dragged has moved without resizing and the differ still has to know:
// the rect it last applied is what the next render is compared against, and a
// stale one would move the window back under the user.
static void flushWindowResize()
{
    if (g_onWindowResize.IsEmpty() || g_hasPendingError || g_shuttingDown)
        return;

    std::vector<std::pair<std::string, TRect>> moved;
    for (const auto &entry : g_views.openWindows())
        {
        JsWindow *win = entry.second;
        TRect now = win->getBounds();
        if (now == win->lastReported)
            continue;
        win->lastReported = now;
        moved.emplace_back(entry.first, now);
        }
    if (moved.empty())
        return;

    Napi::Env env = g_onWindowResize.Env();
    Napi::HandleScope scope(env);
    for (const auto &it : moved)
        callJs(g_onWindowResize,
               {Napi::String::New(env, it.first),
                Napi::Number::New(env, it.second.a.x),
                Napi::Number::New(env, it.second.a.y),
                Napi::Number::New(env, it.second.b.x),
                Napi::Number::New(env, it.second.b.y)});
}

void noteWindowClosed(const std::string &id)
{
    if (g_onClose.IsEmpty() || g_shuttingDown)
        return;
    g_closedWindows.push_back(id);
}

// Drained by the pump, between events.
static void flushClosedWindows()
{
    if (g_closedWindows.empty() || g_onClose.IsEmpty() || g_hasPendingError)
        {
        g_closedWindows.clear();
        return;
        }

    std::vector<std::string> closed;
    closed.swap(g_closedWindows);

    Napi::Env env = g_onClose.Env();
    Napi::HandleScope scope(env);
    for (const std::string &id : closed)
        callJs(g_onClose, {Napi::String::New(env, id)});
}

void dispatchClick(const std::string &id, int x, int y, bool doubled,
                   bool rightButton)
{
    if (g_onClick.IsEmpty() || g_hasPendingError)
        return;

    Napi::Env env = g_onClick.Env();
    Napi::HandleScope scope(env);
    callJs(g_onClick, {Napi::String::New(env, id), Napi::Number::New(env, x),
                       Napi::Number::New(env, y),
                       Napi::Boolean::New(env, doubled),
                       Napi::Boolean::New(env, rightButton)});
}

/* ------------------------------------------------------------------ */
/*  Modality without the nested loop                                  */
/* ------------------------------------------------------------------ */

// The first half of TGroup::execView (tgroup.cpp:193-205), up to the point
// where it would have called p->execute().
static void beginModal(ModalSession &s)
{
    TGroup *host = s.host;
    TView *p = s.view;

    s.saveOptions = p->options;
    s.saveOwner = p->owner;
    s.saveTopView = TheTopView;
    s.saveCurrent = host->current;
    TView::getCommands(s.saveCommands);

    TheTopView = p;
    p->options = p->options & ~ofSelectable;
    p->setState(sfModal, True);
    host->setCurrent(p, TView::enterSelect);
    if (s.saveOwner == nullptr)
        host->insert(p);
}

// The second half (tgroup.cpp:207-214), after p->execute() would have
// returned.
static void finishModal(ModalSession &s)
{
    TGroup *host = s.host;
    TView *p = s.view;

    if (s.saveOwner == nullptr)
        host->remove(p);
    host->setCurrent(s.saveCurrent, TView::leaveSelect);
    p->setState(sfModal, False);
    p->options = s.saveOptions;
    TheTopView = s.saveTopView;
    TView::setCommands(s.saveCommands);
}

static Napi::Object modalResult(const Napi::Env &env, const std::string &id,
                                ushort result)
{
    // Read the fields before the dialog is destroyed -- afterwards the ids are
    // gone, which is correct and a trap if you forget.
    Napi::Object out = Napi::Object::New(env);
    out.Set("values", collectValues(env, id));
    if (const std::string *name = g_commands.nameOf(result))
        out.Set("cmd", Napi::String::New(env, *name));
    else
        out.Set("cmd", env.Null());
    return out;
}

// Called from the pump, between events -- never from inside the dialog's own
// handleEvent, so destroying the view here is safe.
static void closeTopModal(const Napi::Env &env, ushort result)
{
    std::unique_ptr<ModalSession> s = std::move(g_modals.back());
    g_modals.pop_back();

    finishModal(*s);
    if (s->onDone)
        {
        s->onDone(s->view, result);
        TObject::destroy(s->view);
        return;
        }
    Napi::Object out = modalResult(env, s->id, result);
    TObject::destroy(s->view);   // ~JsWindow unregisters the ids
    s->deferred->Resolve(out);
}

// A modal opened from C++, by a view, with a C++ continuation.
//
// tv.dialog() is the model asking for a modal and being answered with a
// promise. This is the other caller: THistory wants to put a list over the
// field it belongs to and be told what was picked, and the alternative --
// TGroup::execView, which is what Turbo Vision itself does -- runs a nested
// event loop inside the pump's own handleEvent call. That would stop Node's
// loop dead for as long as the drop-down was open: no timers, no promises, no
// subscriptions, no renders. Reusing the stack keeps the one property the
// whole modal design is for, which is that modal means "input goes here" and
// never "the process stops".
void openLocalModal(TGroup *host, TView *view,
                    std::function<void(TView *, ushort)> done, bool viewIsGroup)
{
    auto session = std::make_unique<ModalSession>();
    session->view = view;
    session->host = host;
    session->onDone = std::move(done);
    session->viewIsGroup = viewIsGroup;
    beginModal(*session);
    g_modals.push_back(std::move(session));
}

void endLocalModal(TView *view, ushort command)
{
    for (auto it = g_modals.rbegin(); it != g_modals.rend(); ++it)
        if ((*it)->view == view)
            {
            (*it)->ended = command;
            return;
            }
}

/* ------------------------------------------------------------------ */
/*  The context menu                                                  */
/* ------------------------------------------------------------------ */

JsMenuPopup::JsMenuPopup(const TRect &bounds, TMenu *aMenu) noexcept
    : TMenuBox(bounds, aMenu, nullptr)
{
    // TMenuView leaves `current` at the menu's default, which for a context
    // menu is nothing -- TMenuPopup::execute zeroes it deliberately, on the
    // grounds that a highlighted entry under the pointer looks wrong. Nothing
    // is highlighted here either until the pointer or an arrow key says so.
    current = nullptr;

    // What TMenuView::updateMenu does on cmCommandSetChanged, done once at
    // construction because that is the only moment this menu exists for.
    // Without it a command turned off with tv.setEnabled() would be drawn in
    // the ordinary colour, and only refuse to be chosen when it was.
    for (TMenuItem *p = menu != nullptr ? menu->items : nullptr; p != nullptr;
         p = p->next)
        if (p->name != nullptr)
            p->disabled = commandEnabled(p->command) ? False : True;
}

TMenuItem *JsMenuPopup::itemAt(const TPoint &where)
{
    if (menu == nullptr)
        return nullptr;
    TPoint spot = makeLocal(where);
    for (TMenuItem *p = menu->items; p != nullptr; p = p->next)
        if (p->name != nullptr && getItemRect(p).contains(spot))
            return p;
    return nullptr;
}

void JsMenuPopup::moveTo(TMenuItem *item)
{
    if (item == current)
        return;
    current = item;
    drawView();
}

// Up and down, wrapping, skipping the separators. TMenuView has nextItem and
// prevItem for this and they are private, which is why they are here again --
// and the chain is singly linked, so backwards is a walk from the front.
void JsMenuPopup::walk(bool forward)
{
    if (menu == nullptr || menu->items == nullptr)
        return;

    // Bounded rather than "until it comes back to where it started": a menu
    // of nothing but dividers has no name to land on, and the wrap would go
    // round for ever looking for one.
    int room = 0;
    for (TMenuItem *p = menu->items; p != nullptr; p = p->next)
        ++room;

    TMenuItem *start = current;
    TMenuItem *at = current;
    do
        {
        if (forward)
            at = (at == nullptr || at->next == nullptr) ? menu->items : at->next;
        else
            {
            TMenuItem *before = nullptr;
            for (TMenuItem *p = menu->items; p != nullptr && p != at; p = p->next)
                before = p;
            if (before == nullptr)
                for (before = menu->items; before->next != nullptr;
                     before = before->next)
                    ;
            at = before;
            }
        }
    while (--room > 0 && at != start && at->name == nullptr);
    if (at->name != nullptr)
        moveTo(at);
}

void JsMenuPopup::pick()
{
    if (current == nullptr || current->name == nullptr ||
        current->command == 0 || !commandEnabled(current->command))
        return;
    endLocalModal(this, current->command);
}

void JsMenuPopup::cancel()
{
    endLocalModal(this, cmCancel);
}

// Deliberately not TMenuView::handleEvent. Both of the branches that matter
// there end in do_a_select(), which calls execute() -- the nested loop this
// class exists to not have.
//
// Every event reaches here, including the ones outside the box, because the
// pump sends them straight to the top modal view rather than through the
// desktop. Clicking away is therefore something this can see and act on.
void JsMenuPopup::handleEvent(TEvent &event)
{
    switch (event.what)
        {
        case evMouseDown:
            if (mouseInView(event.mouse.where))
                {
                armed = true;
                moveTo(itemAt(event.mouse.where));
                }
            else
                cancel();
            clearEvent(event);
            break;

        // Only while a button is held: the terminal is put in mode 1002, which
        // reports motion during a drag and not otherwise, so a hover that
        // follows the pointer is not on offer. Turbo Vision's own menus track
        // the same way.
        case evMouseMove:
            if (armed && mouseInView(event.mouse.where))
                moveTo(itemAt(event.mouse.where));
            clearEvent(event);
            break;

        case evMouseUp:
            if (armed)
                {
                if (mouseInView(event.mouse.where) &&
                    itemAt(event.mouse.where) != nullptr)
                    {
                    moveTo(itemAt(event.mouse.where));
                    pick();
                    }
                else
                    cancel();
                }
            clearEvent(event);
            break;

        case evKeyDown:
            switch (event.keyDown.keyCode)
                {
                case kbUp:
                    walk(false);
                    break;
                case kbDown:
                    walk(true);
                    break;
                // Straight to `current` rather than through moveTo, which
                // would draw the menu once with nothing highlighted on the
                // way past.
                case kbHome:
                    current = nullptr;
                    walk(true);
                    break;
                case kbEnd:
                    current = nullptr;
                    walk(false);
                    break;
                case kbEnter:
                    pick();
                    break;
                case kbEsc:
                    cancel();
                    break;
                default:
                    // A letter picks the entry it underlines, the way it does
                    // in a pull-down. Anything else is swallowed rather than
                    // passed on: a modal menu that let keystrokes through to
                    // the window behind it would be a surprising one.
                    if (TMenuItem *p = findItem(event.keyDown.getText()))
                        {
                        moveTo(p);
                        pick();
                        }
                    break;
                }
            clearEvent(event);
            break;

        default:
            break;
        }
}

/* ------------------------------------------------------------------ */
/*  Starting and stopping                                             */
/* ------------------------------------------------------------------ */

static void prepare(const Napi::Env &env, const Napi::Value &value)
{
    if (g_running)
        throw Napi::Error::New(env, "tvision: an application is already running "
                                    "(one per process -- TProgram's state is "
                                    "static)");
    if (!value.IsObject())
        throw Napi::TypeError::New(env, "tvision: config must be an object");

    // Fail loudly rather than scribbling escape codes into a pipe.
    if (!isatty(STDIN_FILENO) || !isatty(STDOUT_FILENO))
        throw Napi::Error::New(env, "tvision: stdin and stdout must be a terminal "
                                    "(run this in a real terminal, or under a pty)");

    Napi::Object config = value.As<Napi::Object>();

    g_config = AppConfig();
    g_commands.reset();
    g_views.clear();
    g_menuBar = nullptr;
    g_statusLine = nullptr;
    g_hasPendingError = false;

    if (config.Has("menuBar"))
        g_config.menus = parseMenuBar(env, config.Get("menuBar"));
    if (config.Has("statusLine"))
        g_config.status = parseStatusLine(env, config.Get("statusLine"));

    for (auto &binding : {std::make_pair("onCommand", &g_onCommand),
                          std::make_pair("onSelect", &g_onSelect),
                          std::make_pair("onFocus", &g_onFocus),
                          std::make_pair("onScroll", &g_onScroll),
                          std::make_pair("onKey", &g_onKey),
                          std::make_pair("onClick", &g_onClick),
                          std::make_pair("onClose", &g_onClose),
                          std::make_pair("onResize", &g_onResize),
                          std::make_pair("onWindowResize", &g_onWindowResize),
                          std::make_pair("onChange", &g_onChange),
                          std::make_pair("onEdit", &g_onEdit)})
        {
        if (!config.Has(binding.first))
            continue;
        Napi::Value cb = config.Get(binding.first);
        if (cb.IsUndefined() || cb.IsNull())
            continue;   // {onSelect: undefined} is ordinary JS, not an error
        if (!cb.IsFunction())
            throw Napi::TypeError::New(env, std::string("tvision: ") +
                                                binding.first +
                                                " must be a function");
        *binding.second = Napi::Persistent(cb.As<Napi::Function>());
        }
}

static void teardown(const Napi::Env &env)
{
    // Settle any dialog still open so its awaiter is not left hanging. The
    // views themselves belong to the desktop and go with the application.
    for (auto it = g_modals.rbegin(); it != g_modals.rend(); ++it)
        if ((*it)->deferred)
            (*it)->deferred->Resolve(modalResult(env, (*it)->id, 0));
    g_modals.clear();
    g_closedWindows.clear();
    g_focusNotes.clear();
    g_scrollNotes.clear();
    TheTopView = nullptr;

    g_shuttingDown = true;
    g_app.reset();          // the destructor gives the terminal back
    g_shuttingDown = false;
    g_menuBar = nullptr;    // destroyed with the application
    g_statusLine = nullptr;
    g_running = false;
    g_quitRequested = false;
    g_views.clear();
    g_onCommand.Reset();
    g_onSelect.Reset();
    g_onFocus.Reset();
    g_onScroll.Reset();
    g_onKey.Reset();
    g_onClick.Reset();
    g_onClose.Reset();
    g_onResize.Reset();
    g_onWindowResize.Reset();
    g_onChange.Reset();
    g_onEdit.Reset();
    g_editNotes.clear();
    g_changeNotes.clear();
    g_lastDeskSize = {0, 0};
    g_config = AppConfig();
}

static void rethrowPendingError(const Napi::Env &env)
{
    if (!g_hasPendingError)
        return;
    g_hasPendingError = false;
    Napi::Value err = g_pendingError.Value();
    g_pendingError.Reset();
    throw Napi::Error(env, err);
}

// There is no blocking run() any more. It was milestone 1's form, and it
// cannot survive dialogs that resolve a Promise: under it Node's event loop
// never runs, so the promise would never settle and the await would deadlock.
// FINDINGS.md keeps the history.

// tv.start(config) -- returns immediately. Nothing happens until step() is
// called, and step() is called from a Node timer, so Node stays in charge.
static Napi::Value Start(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    prepare(env, info[0]);

    TProgram::eventTimeoutMs = 0;    // getEvent must not block: we are a guest
                                     // in Node's loop now.
    g_app.reset(new JsApp());
    g_running = true;
    return env.Undefined();
}

// tv.step() -- one turn of TGroup::execute(), hoisted out of the library.
// Returns the number of events handled, or -1 once the application has quit
// (at which point the terminal has already been restored).
static Napi::Value Step(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    if (!g_app)
        return Napi::Number::New(env, -1);

    if (g_inStep)
        throw Napi::Error::New(env, "tvision: step() re-entered (did a callback "
                                    "call it?)");
    g_inStep = true;

    // Drain what is waiting rather than one event per tick: a paste or a burst
    // of mouse movement would otherwise trickle in at the timer's rate.
    const int kMaxEventsPerTick = 64;
    int handled = 0;
    bool finished = false;

    for (int i = 0; i < kMaxEventsPerTick; ++i)
        {
        // A programmatic quit is honoured here rather than where it was asked
        // for: tv.quit() can be called from a list box's onSelect, which runs
        // inside the dialog's own handleEvent, and tearing the dialog down
        // from there would free it under TVision's feet.
        if (g_quitRequested)
            {
            while (!g_modals.empty())
                closeTopModal(env, cmCancel);
            finished = true;
            break;
            }

        // Recomputed every pass: a callback may have opened or closed a
        // dialog. This is the whole of modality -- events go to the top modal
        // view instead of to the application.
        //
        // A TView and not a TGroup, which it used to be. Every modal here was
        // a window until the popup menu, which is a TMenuBox; handleEvent,
        // eventError and valid are all TView virtuals, and the one thing that
        // was not -- endState -- now belongs to the session. See
        // ModalSession::endState.
        TView *target = g_modals.empty()
                            ? (TView *) g_app.get()
                            : g_modals.back()->view;

        TEvent event;
        g_app->getEvent(event);      // also runs idle() when there is nothing
        if (event.what == evNothing)
            break;

        ++handled;
        target->handleEvent(event);
        // TGroup's, not TView's, and it only ever walks up to the application
        // to be ignored. A popup menu swallows everything it is given, so
        // there is nothing left to report and nowhere for it to go.
        if (event.what != evNothing &&
            (g_modals.empty() || g_modals.back()->viewIsGroup))
            ((TGroup *) target)->eventError(event);

        // Safe point: this event is finished, so whatever it destroyed is
        // fully gone and whatever it moved has settled. Both queues are
        // drained here rather than where they were filled, so that a callback
        // cannot re-enter TVision in the middle of handling an event.
        flushFocused();
        flushScrolled();
        flushClosedWindows();
        flushResize();
        flushWindowResize();

        // The outer half of TGroup::execute(): a command the target considers
        // valid ends it. For the application that means quitting; for a modal
        // dialog it means the dialog is done.
        ushort ending = g_modals.empty() ? g_app->endState
                                         : g_modals.back()->endState();
        if (ending != 0)
            {
            if (target->valid(ending))
                {
                if (g_modals.empty())
                    {
                    finished = true;
                    break;
                    }
                closeTopModal(env, ending);
                }
            else if (g_modals.empty())
                g_app->endState = 0;
            else
                g_modals.back()->clearEndState();
            }
        }

    g_inStep = false;
    flushFocused();
    flushScrolled();
    flushClosedWindows();
    // Once per pump rather than once per event, unlike the others. A burst of
    // keystrokes -- a paste, or simply typing quickly -- is read in one pass of
    // the loop above, and the model wants the word rather than each letter of
    // it. Collapsing them here means one notification and so one render, which
    // is also the difference between the model's answer arriving before the
    // next keystroke and arriving after it.
    flushChanged();
    flushEdited();
    // Again outside the loop: the very first pump after tv.start() usually
    // breaks out on evNothing before reaching the safe point above, and the
    // size the application started at is the one every layout needs first.
    flushResize();
    flushWindowResize();

    if (finished || g_hasPendingError)
        {
        teardown(env);
        rethrowPendingError(env);
        return Napi::Number::New(env, -1);
        }

    return Napi::Number::New(env, handled);
}

/* ------------------------------------------------------------------ */
/*  The rest of the JS surface                                        */
/* ------------------------------------------------------------------ */

static void requireRunning(const Napi::Env &env, const char *fn)
{
    if (!g_running)
        throw Napi::Error::New(env, std::string("tvision: ") + fn +
                                        "() can only be called while the "
                                        "application is running");
}

// tv.dialog(spec) -- modal, and returns a Promise of {cmd, values}.
//
// Modal here means what it means in Turbo Vision: input goes to this dialog
// and nowhere else. It does *not* mean the process stops. The dialog is
// registered with the pump and driven event by event, so timers, promises and
// I/O carry on behind it -- open the demo's Go to dialog and the clock keeps
// running.
static Napi::Value Dialog(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    requireRunning(env, "dialog");

    if (!info[0].IsObject())
        throw Napi::TypeError::New(env, "tvision: dialog(spec) needs a spec object");
    Napi::Object spec = info[0].As<Napi::Object>();

    static int serial = 0;
    std::string id = getString(spec, "id");
    if (id.empty())
        id = "dialog" + std::to_string(++serial);
    if (g_views.has(id))
        throw Napi::Error::New(env, "tvision: id '" + id + "' is already in use");

    auto session = std::make_unique<ModalSession>();
    session->deferred =
        std::make_unique<Napi::Promise::Deferred>(Napi::Promise::Deferred::New(env));
    session->host = TProgram::deskTop;
    session->id = id;

    JsWindow *d = new JsWindow(getRect(env, spec, "dialog"),
                               getString(spec, "title").c_str(), id);
    d->reportClose = false;   // the promise is the dialog's outcome
    session->view = d;
    g_views.addWindow(id, d);

    TView *firstSelectable = nullptr;
    try
        {
        firstSelectable = buildItems(env, d, spec.Get("items"), id);
        }
    catch (...)
        {
        g_views.forgetWindow(id);
        TObject::destroy(d);
        throw;
        }

    beginModal(*session);
    applyInitialFocus(spec, firstSelectable);
    applyCursors(env, spec.Get("items"));
    Napi::Promise promise = session->deferred->Promise();
    g_modals.push_back(std::move(session));
    return promise;
}

// tv.popupMenu({view, x, y, items}) -- a context menu at a point in a view.
//
// The command the user chose is put back on the event queue rather than
// dispatched from here, which is what TMenuView::do_a_select does with the
// command its own loop returned. A built-in like "quit" or "close" is then
// handled by TApplication exactly as it would be from the menu bar, and a name
// of the model's own reaches onCommand by the same route as every other
// command. The model does not have to know where a command came from, and this
// is what makes that true.
static Napi::Value PopupMenu(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    requireRunning(env, "popupMenu");

    if (!info[0].IsObject())
        throw Napi::TypeError::New(env, "tvision: popupMenu(spec) needs a spec "
                                        "object");
    Napi::Object spec = info[0].As<Napi::Object>();

    // The anchor decides the coordinate system, because a context menu is
    // opened from a click and a click arrives in the coordinates of the view
    // that was clicked. Asking the model to convert those to the desktop's
    // would be arithmetic it should never have to do.
    std::string anchorId = getString(spec, "view");
    TView *anchor = nullptr;
    if (ViewRef *ref = g_views.find(anchorId))
        anchor = ref->view;
    else if (JsWindow *win = g_views.findWindow(anchorId))
        anchor = win;
    if (anchor == nullptr)
        throw Napi::Error::New(env, "tvision: popupMenu view '" + anchorId +
                                        "' does not exist");

    std::vector<MenuItemDef> items = parseMenuItems(env, spec.Get("items"));
    for (const MenuItemDef &item : items)
        if (item.isSubMenu())
            throw Napi::Error::New(env, "tvision: a popup menu cannot contain a "
                                        "submenu ('" + item.title + "') -- a "
                                        "submenu is a menu opening inside a "
                                        "menu, and this one is driven by the "
                                        "pump rather than by a loop of its own");
    TMenu *menu = buildMenu(items);
    if (menu == nullptr)
        throw Napi::Error::New(env, "tvision: a popup menu needs at least one "
                                    "item");

    TPoint at = TProgram::deskTop->makeLocal(
        anchor->makeGlobal(TPoint{getInt(spec, "x", 0), getInt(spec, "y", 0)}));

    // From the point to the far corner. TMenuBox sizes itself to its items
    // inside whatever it is given and flips up or left when it does not fit,
    // which is the same rectangle TMenuView::execute hands a submenu.
    TRect room(at.x, at.y, TProgram::deskTop->size.x, TProgram::deskTop->size.y);
    JsMenuPopup *popup = new JsMenuPopup(room, menu);

    openLocalModal(
        TProgram::deskTop, popup,
        [](TView *, ushort result) {
            if (result == 0 || result == cmCancel)
                return;
            TEvent chosen;
            chosen.what = evCommand;
            chosen.message.command = result;
            chosen.message.infoPtr = nullptr;
            TProgram::application->putEvent(chosen);
        },
        false);   // a TMenuBox, so not a group -- see ModalSession::endState

    return env.Undefined();
}

// tv.overlays([...]) -- the views that sit on the *application*, beside the
// desktop rather than on it.
//
// TClockView and THeapView are inserted into TProgram, not into TDeskTop, and
// that is not a detail: the desktop is the patterned area windows live in, and
// a clock in the corner is not in it. tvdemo's clock is a view for exactly
// this reason, and until now the only way to have one here was to put it in
// the status line -- which works, and rebuilds the status line once a second,
// because a status line is replaced whole.
//
// Screen coordinates, because that is TProgram's extent: row 0 is the menu
// bar's row, which is where a clock usually goes. Rebuilt whole rather than
// diffed in place -- the set is small and there is no z-order or focus to
// lose -- while the views *inside* it are patched by id like any others.
static const char *kOverlayOwner = "\x01overlays";

static Napi::Value Overlays(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    requireRunning(env, "overlays");

    // Destroy whatever was there. The registry is what knows which views those
    // were, and forgetWindow is what stops their ids resolving afterwards.
    if (const std::vector<std::string> *ids = g_views.idsOf(kOverlayOwner))
        {
        std::vector<std::string> doomed = *ids;
        for (const std::string &id : doomed)
            if (ViewRef *ref = g_views.find(id))
                TObject::destroy(ref->view);
        }
    g_views.forgetWindow(kOverlayOwner);

    if (!info[0].IsArray())
        return env.Undefined();
    buildItems(env, g_app.get(), info[0], kOverlayOwner);
    applyCursors(env, info[0]);
    return env.Undefined();
}

// tv.quit() -- ask the application to exit, as if the user had chosen Exit.
static Napi::Value Quit(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    requireRunning(env, "quit");

    // Deferred rather than immediate: see the note in step(). Any open dialog
    // is cancelled on the way out.
    g_quitRequested = true;

    TEvent e = {};
    e.what = evCommand;
    e.message.command = cmQuit;
    TProgram::application->putEvent(e);
    return env.Undefined();
}

// tv.setMenuBar(items) -- replace the whole menu bar while running.
//
// Turbo Vision builds it in the application constructor, but that is only
// where it starts: TMenuView keeps its TMenu in a member, and swapping it is
// what tvision's mmenu example does. This is what lets the menu bar be part of
// a declarative view instead of fixed configuration.
static Napi::Value SetMenuBar(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    requireRunning(env, "setMenuBar");

    g_config.menus = parseMenuBar(env, info[0]);
    if (g_menuBar == nullptr)
        return Napi::Boolean::New(env, false);   // started without one

    g_menuBar->replace(buildMenu(g_config.menus));
    return Napi::Boolean::New(env, true);
}

// tv.setStatusLine(items) -- the same, for the status line.
static Napi::Value SetStatusLine(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    requireRunning(env, "setStatusLine");

    g_config.status = parseStatusLine(env, info[0]);
    TStatusDef *defs = buildStatusDef(g_config.status);
    if (g_statusLine == nullptr || defs == nullptr)
        return Napi::Boolean::New(env, false);

    g_statusLine->replace(defs);
    return Napi::Boolean::New(env, true);
}

/* ------------------------------------------------------------------ */
/*  tv.setTheme(theme)                                                */
/* ------------------------------------------------------------------ */

// One colour, either of the sixteen the terminal has always had or a literal
// 24-bit one. The first follows whatever scheme the user has set on their
// terminal, which is a feature and not a shortcut: a theme built out of `Ansi`
// looks like the rest of their machine, and one built out of `Rgb` looks the
// same everywhere. magiblot's TVision quantises an Rgb colour down when the
// terminal cannot do better, so neither is a hard requirement.
static TColor readColor(const Napi::Env &env, const Napi::Value &value,
                        const char *where)
{
    if (value.IsNumber())
        return TColor(TColorBIOS((uint8_t) value.ToNumber().Int32Value()));
    if (value.IsArray())
        {
        Napi::Array rgb = value.As<Napi::Array>();
        if (rgb.Length() == 3)
            return TColor(TColorRGB(
                (uint8_t) rgb.Get(0u).ToNumber().Int32Value(),
                (uint8_t) rgb.Get(1u).ToNumber().Int32Value(),
                (uint8_t) rgb.Get(2u).ToNumber().Int32Value()));
        }
    throw Napi::Error::New(env, std::string("tvision: ") + where +
                                    " must be a colour index or [r, g, b]");
}

// A foreground and a background, as the two-element array the encoder writes.
static TColorAttr readPair(const Napi::Env &env, const Napi::Object &owner,
                           const char *key)
{
    Napi::Value value = owner.Get(key);
    if (!value.IsArray())
        throw Napi::Error::New(env, std::string("tvision: theme.") + key +
                                        " must be [foreground, background]");
    Napi::Array pair = value.As<Napi::Array>();
    if (pair.Length() != 2)
        throw Napi::Error::New(env, std::string("tvision: theme.") + key +
                                        " must be [foreground, background]");
    TColorAttr attr = {};
    attr.setForeground(readColor(env, pair.Get(0u), key));
    attr.setBackground(readColor(env, pair.Get(1u), key));
    return attr;
}

// A foreground on the ground `over` already names, which is how a theme says
// "hot keys are red" without repeating the surface's colour nine times.
static TColorAttr readInk(const Napi::Env &env, const Napi::Object &owner,
                          const char *key, TColorAttr over)
{
    TColorAttr attr = over;
    attr.setForeground(readColor(env, owner.Get(key), key));
    return attr;
}

static ThemePanel readPanel(const Napi::Env &env, const Napi::Object &theme,
                            const char *key)
{
    Napi::Value value = theme.Get(key);
    if (!value.IsObject())
        throw Napi::Error::New(env, std::string("tvision: theme.") + key +
                                        " must be an object");
    Napi::Object o = value.As<Napi::Object>();

    ThemePanel p;
    p.text = readPair(env, o, "text");
    p.frame = readPair(env, o, "frame");
    p.frameActive = readInk(env, o, "frameActive", p.frame);
    p.selected = readPair(env, o, "selected");
    p.button = readPair(env, o, "button");
    p.input = readPair(env, o, "input");
    p.scrollBar = readPair(env, o, "scrollBar");
    // The four that are a foreground on a ground already named: an accent is a
    // hot key in the body text, the other two are hot keys on a button and on
    // an input line, and disabled is text that is still text.
    p.accent = readInk(env, o, "accent", p.text);
    p.buttonAccent = readInk(env, o, "buttonAccent", p.button);
    p.inputAccent = readInk(env, o, "inputAccent", p.input);
    p.disabled = readInk(env, o, "disabled", p.text);
    return p;
}

// tv.setTheme(theme) -- the whole application palette, from the model.
//
// Turbo Vision's palette is a hundred and thirty-five attributes and this is
// seventeen fields, which is the difference between describing a scheme and
// re-implementing an indirection table. buildAppPalette above is where the
// expansion is written down, one line per slot.
static Napi::Value SetTheme(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();

    if (info[0].IsNull() || info[0].IsUndefined())
        {
        g_theme.set = false;
        }
    else
        {
        if (!info[0].IsObject())
            throw Napi::TypeError::New(env, "tvision: setTheme(theme) needs an "
                                            "object");
        Napi::Object o = info[0].As<Napi::Object>();

        ThemeSpec t;
        t.set = true;
        t.desktop = readPair(env, o, "desktop");
        t.bar = readPair(env, o, "bar");
        t.barSelected = readPair(env, o, "barSelected");
        t.barAccent = readInk(env, o, "barAccent", t.bar);
        t.barDisabled = readInk(env, o, "barDisabled", t.bar);
        t.barSelectedAccent = readInk(env, o, "barSelectedAccent",
                                      t.barSelected);
        t.barSelectedDisabled = readInk(env, o, "barDisabled", t.barSelected);
        t.window = readPanel(env, o, "window");
        t.alternate = readPanel(env, o, "alternate");
        t.dialog = readPanel(env, o, "dialog");

        // Only once every field has been read, so that a theme with one bad
        // colour in it leaves the screen alone rather than half repainted.
        g_theme = t;
        buildAppPalette(themedPalette().data + 1, g_theme);
        }

    // Nothing caches a colour -- every view asks getColor on every draw -- so
    // the whole of "apply it" is repainting. setScreenMode at the mode it is
    // already in is what tvdemo's colour dialog does; it re-reads the screen
    // and redraws from the top, which is the only thing that reaches the menu
    // bar, the status line and the desktop as well as the windows.
    if (g_app && g_running)
        g_app->setScreenMode(TScreen::screenMode);
    return Napi::Boolean::New(env, true);
}

// tv.screenSize() -- so JS can lay windows out relative to the terminal.
static Napi::Value ScreenSize(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    requireRunning(env, "screenSize");

    Napi::Object out = Napi::Object::New(env);
    out.Set("width", Napi::Number::New(env, TScreen::screenWidth));
    out.Set("height", Napi::Number::New(env, TScreen::screenHeight));
    return out;
}

// tv.doubleClickDelay(ticks?) -- read, or set, how long TVision will wait
// before deciding two clicks were two clicks. The unit is 1/18.2 of a second,
// which is the original PC timer tick and what TEventQueue::doubleDelay has
// always been counted in. tvdemo's mouse dialog exists to change exactly this.
static Napi::Value DoubleClickDelay(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    if (info.Length() > 0 && info[0].IsNumber())
        {
        int ticks = info[0].ToNumber().Int32Value();
        if (ticks > 0)
            TEventQueue::doubleDelay = (ushort) ticks;
        }
    return Napi::Number::New(env, TEventQueue::doubleDelay);
}

static Napi::Object Init(Napi::Env env, Napi::Object exports)
{
    exports.Set("doubleClickDelay", Napi::Function::New(env, DoubleClickDelay));
    exports.Set("start", Napi::Function::New(env, Start));
    exports.Set("step", Napi::Function::New(env, Step));
    exports.Set("dialog", Napi::Function::New(env, Dialog));
    exports.Set("popupMenu", Napi::Function::New(env, PopupMenu));
    exports.Set("overlays", Napi::Function::New(env, Overlays));
    exports.Set("quit", Napi::Function::New(env, Quit));
    exports.Set("setMenuBar", Napi::Function::New(env, SetMenuBar));
    exports.Set("setStatusLine", Napi::Function::New(env, SetStatusLine));
    exports.Set("setTheme", Napi::Function::New(env, SetTheme));
    exports.Set("screenSize", Napi::Function::New(env, ScreenSize));
    registerViewApi(env, exports);
    return exports;
}

} // namespace tvnode

// NODE_API_MODULE pastes the registration function's name into an identifier,
// so it cannot take a namespace-qualified one.
static Napi::Object InitModule(Napi::Env env, Napi::Object exports)
{
    return tvnode::Init(env, exports);
}

NODE_API_MODULE(tvision, InitModule)
