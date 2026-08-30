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

struct MenuItemDef {
    bool separator = false;
    std::string title;
    ushort command = 0;
    TKey key;
    std::string shortcut;   // right-aligned hint text, e.g. "Alt-X"
};

struct SubMenuDef {
    std::string title;
    TKey key;
    std::vector<MenuItemDef> items;
};

struct StatusItemDef {
    std::string text;
    TKey key;
    ushort command = 0;
};

struct AppConfig {
    std::vector<SubMenuDef> menus;
    std::vector<StatusItemDef> status;
};

AppConfig g_config;

Napi::FunctionReference g_onCommand;
Napi::FunctionReference g_onSelect;

// Set while a JS callback is throwing, so we can unwind the TVision loop and
// rethrow into JS once the terminal has been restored.
bool g_hasPendingError = false;
Napi::Reference<Napi::Value> g_pendingError;

bool g_inStep = false;

} // namespace

/* ------------------------------------------------------------------ */
/*  Config parsing                                                    */
/* ------------------------------------------------------------------ */

static void parseMenuBar(const Napi::Env &env, const Napi::Value &value)
{
    if (!value.IsArray())
        throw Napi::Error::New(env, "tvision: menuBar must be an array");
    Napi::Array menus = value.As<Napi::Array>();

    for (uint32_t i = 0; i < menus.Length(); ++i)
        {
        Napi::Object m = menus.Get(i).As<Napi::Object>();
        SubMenuDef sub;
        sub.title = getString(m, "title");
        sub.key = getKey(env, m, "key", "menuBar entry '" + sub.title + "'");

        if (m.Has("items"))
            {
            Napi::Array items = m.Get("items").As<Napi::Array>();
            for (uint32_t j = 0; j < items.Length(); ++j)
                {
                Napi::Object it = items.Get(j).As<Napi::Object>();
                MenuItemDef item;
                if (getBool(it, "separator"))
                    {
                    item.separator = true;
                    sub.items.push_back(item);
                    continue;
                    }
                item.title = getString(it, "title");
                item.command = g_commands.intern(getString(it, "cmd"));
                item.key = getKey(env, it, "key", "menu item '" + item.title + "'");
                item.shortcut = getString(it, "shortcut");
                sub.items.push_back(item);
                }
            }
        g_config.menus.push_back(std::move(sub));
        }
}

static void parseStatusLine(const Napi::Env &env, const Napi::Value &value)
{
    if (!value.IsArray())
        throw Napi::Error::New(env, "tvision: statusLine must be an array");
    Napi::Array items = value.As<Napi::Array>();

    for (uint32_t i = 0; i < items.Length(); ++i)
        {
        Napi::Object it = items.Get(i).As<Napi::Object>();
        StatusItemDef item;
        item.text = getString(it, "text");
        item.key = getKey(env, it, "key", "status item '" + item.text + "'");
        item.command = g_commands.intern(getString(it, "cmd"));
        g_config.status.push_back(std::move(item));
        }
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

TMenuBar *JsApp::initMenuBar(TRect r)
{
    r.b.y = r.a.y + 1;
    if (g_config.menus.empty())
        return nullptr;

    TSubMenu *first = nullptr;
    for (const SubMenuDef &def : g_config.menus)
        {
        TSubMenu *sub = new TSubMenu(def.title.c_str(), def.key);
        // Items must be appended while sub->next is still null: operator+
        // walks to the *last* submenu in the chain before inserting.
        for (const MenuItemDef &item : def.items)
            {
            if (item.separator)
                *sub + newLine();
            else
                *sub + *new TMenuItem(item.title.c_str(), item.command, item.key,
                                      hcNoContext,
                                      item.shortcut.empty()
                                          ? TStringView()
                                          : TStringView(item.shortcut.c_str()));
            }
        if (first == nullptr)
            first = sub;
        else
            *first + *sub;
        }

    return new TMenuBar(r, *first);
}

TStatusLine *JsApp::initStatusLine(TRect r)
{
    r.a.y = r.b.y - 1;
    if (g_config.status.empty())
        return nullptr;

    TStatusDef *def = new TStatusDef(0, 0xFFFF);
    for (const StatusItemDef &item : g_config.status)
        *def + *new TStatusItem(item.text.empty()
                                    ? TStringView()
                                    : TStringView(item.text.c_str()),
                                item.key, item.command);

    return new TStatusLine(r, *def);
}

void JsApp::handleEvent(TEvent &event)
{
    TApplication::handleEvent(event);

    if (event.what == evCommand && event.message.command >= kUserCmdBase)
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
    g_hasPendingError = false;

    if (config.Has("menuBar"))
        parseMenuBar(env, config.Get("menuBar"));
    if (config.Has("statusLine"))
        parseStatusLine(env, config.Get("statusLine"));

    for (auto &binding : {std::make_pair("onCommand", &g_onCommand),
                          std::make_pair("onSelect", &g_onSelect)})
        {
        if (!config.Has(binding.first))
            continue;
        Napi::Value cb = config.Get(binding.first);
        if (!cb.IsFunction())
            throw Napi::TypeError::New(env, std::string("tvision: ") +
                                                binding.first +
                                                " must be a function");
        *binding.second = Napi::Persistent(cb.As<Napi::Function>());
        }
}

static void teardown()
{
    g_app.reset();          // the destructor gives the terminal back
    g_running = false;
    g_views.clear();
    g_onCommand.Reset();
    g_onSelect.Reset();
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

// tv.run(config) -- milestone 1's blocking form. Node's event loop does not
// run at all until the application quits.
static Napi::Value Run(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    prepare(env, info[0]);

    TProgram::eventTimeoutMs = 20;   // TVision's own default: it may block.
    g_app.reset(new JsApp());
    g_running = true;
    g_app->run();

    teardown();
    rethrowPendingError(env);
    return env.Undefined();
}

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
        TEvent event;
        g_app->getEvent(event);      // also runs idle() when there is nothing
        if (event.what == evNothing)
            break;

        ++handled;
        g_app->handleEvent(event);
        if (event.what != evNothing)
            g_app->eventError(event);

        // The outer half of TGroup::execute(): a command that the application
        // considers valid ends it.
        if (g_app->endState != 0)
            {
            if (g_app->valid(g_app->endState))
                {
                finished = true;
                break;
                }
            g_app->endState = 0;
            }
        }

    g_inStep = false;

    if (finished || g_hasPendingError)
        {
        teardown();
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

// tv.dialog(spec) -- modal. Returns {cmd, values}.
//
// Modal means a *nested* TGroup::execute() inside TVision, so this blocks
// Node's event loop until the dialog is dismissed, pump or no pump. Run the
// demo, open File > Go to, and watch the clock stop: that is this comment.
static Napi::Value Dialog(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    requireRunning(env, "dialog");

    if (!info[0].IsObject())
        throw Napi::TypeError::New(env, "tvision: dialog(spec) needs a spec object");
    Napi::Object spec = info[0].As<Napi::Object>();

    static int serial = 0;
    std::string id = "dialog" + std::to_string(++serial);

    JsWindow *d = new JsWindow(getRect(env, spec, "dialog"),
                               getString(spec, "title").c_str(), id);
    try
        {
        buildItems(env, d, spec.Get("items"), id);
        }
    catch (...)
        {
        g_views.forgetWindow(id);
        TObject::destroy(d);
        throw;
        }

    ushort result = TProgram::deskTop->execView(d);

    // Read the fields before the dialog is destroyed -- afterwards the ids are
    // gone, which is the correct behaviour and a trap if you forget.
    Napi::Object out = Napi::Object::New(env);
    out.Set("values", collectValues(env, id));
    if (const std::string *name = g_commands.nameOf(result))
        out.Set("cmd", Napi::String::New(env, *name));
    else
        out.Set("cmd", env.Null());

    TObject::destroy(d);
    return out;
}

// tv.messageBox(text) -- the stock information box with an OK button. Modal,
// with the same caveat as dialog().
static Napi::Value MessageBox(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    requireRunning(env, "messageBox");

    std::string text = info[0].ToString().Utf8Value();
    ushort result = ::messageBox(text.c_str(), mfInformation | mfOKButton);

    if (const std::string *name = g_commands.nameOf(result))
        return Napi::String::New(env, *name);
    return env.Null();
}

// tv.quit() -- ask the application to exit, as if the user had chosen Exit.
static Napi::Value Quit(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    requireRunning(env, "quit");

    TEvent e = {};
    e.what = evCommand;
    e.message.command = cmQuit;
    TProgram::application->putEvent(e);
    return env.Undefined();
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

static Napi::Object Init(Napi::Env env, Napi::Object exports)
{
    exports.Set("run", Napi::Function::New(env, Run));
    exports.Set("start", Napi::Function::New(env, Start));
    exports.Set("step", Napi::Function::New(env, Step));
    exports.Set("dialog", Napi::Function::New(env, Dialog));
    exports.Set("messageBox", Napi::Function::New(env, MessageBox));
    exports.Set("quit", Napi::Function::New(env, Quit));
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
