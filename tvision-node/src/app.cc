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

Napi::FunctionReference g_onCommand;
Napi::FunctionReference g_onSelect;
Napi::FunctionReference g_onFocus;
Napi::FunctionReference g_onScroll;
Napi::FunctionReference g_onKey;
Napi::FunctionReference g_onClick;
Napi::FunctionReference g_onClose;
Napi::FunctionReference g_onResize;
Napi::FunctionReference g_onChange;

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

class JsApp : public TApplication {
public:
    JsApp() noexcept
        : TProgInit(&JsApp::initStatusLine, &JsApp::initMenuBar,
                    &JsApp::initDeskTop)
    {
    }

    virtual void handleEvent(TEvent &event) override;

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
    enum Kind { Text, Flags, Choice } kind;
    std::string text;
    uint32_t bits = 0;
    uint32_t count = 0;
    int index = 0;
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

void dispatchClick(const std::string &id, int x, int y, bool doubled)
{
    if (g_onClick.IsEmpty() || g_hasPendingError)
        return;

    Napi::Env env = g_onClick.Env();
    Napi::HandleScope scope(env);
    callJs(g_onClick, {Napi::String::New(env, id), Napi::Number::New(env, x),
                       Napi::Number::New(env, y),
                       Napi::Boolean::New(env, doubled)});
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
                    std::function<void(TView *, ushort)> done)
{
    auto session = std::make_unique<ModalSession>();
    session->view = view;
    session->host = host;
    session->onDone = std::move(done);
    beginModal(*session);
    g_modals.push_back(std::move(session));
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
                          std::make_pair("onChange", &g_onChange)})
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
    g_onChange.Reset();
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
        TGroup *target = g_modals.empty()
                             ? (TGroup *) g_app.get()
                             : (TGroup *) g_modals.back()->view;

        TEvent event;
        g_app->getEvent(event);      // also runs idle() when there is nothing
        if (event.what == evNothing)
            break;

        ++handled;
        target->handleEvent(event);
        if (event.what != evNothing)
            target->eventError(event);

        // Safe point: this event is finished, so whatever it destroyed is
        // fully gone and whatever it moved has settled. Both queues are
        // drained here rather than where they were filled, so that a callback
        // cannot re-enter TVision in the middle of handling an event.
        flushFocused();
        flushScrolled();
        flushClosedWindows();
        flushResize();

        // The outer half of TGroup::execute(): a command the target considers
        // valid ends it. For the application that means quitting; for a modal
        // dialog it means the dialog is done.
        if (target->endState != 0)
            {
            if (target->valid(target->endState))
                {
                if (g_modals.empty())
                    {
                    finished = true;
                    break;
                    }
                closeTopModal(env, target->endState);
                }
            else
                target->endState = 0;
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
    // Again outside the loop: the very first pump after tv.start() usually
    // breaks out on evNothing before reaching the safe point above, and the
    // size the application started at is the one every layout needs first.
    flushResize();

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
    exports.Set("quit", Napi::Function::New(env, Quit));
    exports.Set("setMenuBar", Napi::Function::New(env, SetMenuBar));
    exports.Set("setStatusLine", Napi::Function::New(env, SetStatusLine));
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
