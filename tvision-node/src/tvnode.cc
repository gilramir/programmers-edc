// tvision-node -- milestone 1
//
// A Node addon that puts a Turbo Vision application on the screen, with the
// menu bar, status line and dialogs described from JavaScript.
//
// Scope, deliberately: this is the *blocking* design. tv.run() calls
// TApplication::run() (i.e. TGroup::execute(), tgroup.cpp:173) and does not
// return until the app quits, so Node's event loop is starved for the app's
// lifetime. That is fine for a hello world and wrong for anything with I/O;
// milestone 2 replaces it with a pump driven from libuv, which is why
// TProgram::eventTimeoutMs (app.h:296) and the public TGroup::endState
// (views.h:919) matter. See FINDINGS.md.
//
// napi.h comes first on purpose: tvision's Borland compatibility headers
// define Boolean/True/False and a pile of macros that V8's headers do not
// enjoy meeting.

#include <napi.h>

#define Uses_MsgBox
#define Uses_TApplication
#define Uses_TButton
#define Uses_TDeskTop
#define Uses_TDialog
#define Uses_TEvent
#define Uses_TKeys
#define Uses_TMenuBar
#define Uses_TMenuItem
#define Uses_TProgram
#define Uses_TRect
#define Uses_TScreen
#define Uses_TStaticText
#define Uses_TStatusDef
#define Uses_TStatusItem
#define Uses_TStatusLine
#define Uses_TSubMenu
#include <tvision/tv.h>

#include <unistd.h>

#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

#include "keys.h"

namespace tvnode {

/* ------------------------------------------------------------------ */
/*  Commands                                                          */
/* ------------------------------------------------------------------ */

// JS names commands with strings; TVision wants ushorts. User commands start
// well clear of TVision's own range. Names of built-ins are mapped to the real
// constants so that {cmd: 'quit'} does what a Turbo Vision user expects
// (TApplication handles it) instead of arriving in JS as a mystery.
static const ushort kUserCmdBase = 1000;

class CommandRegistry {
public:
    CommandRegistry()
    {
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

    void reset() { *this = CommandRegistry(); }

private:
    std::unordered_map<std::string, ushort> byName;
    std::unordered_map<ushort, std::string> byCode;
    ushort next = kUserCmdBase;
};

/* ------------------------------------------------------------------ */
/*  Configuration captured from JS                                    */
/* ------------------------------------------------------------------ */

// TProgInit calls initMenuBar/initStatusLine from inside the TApplication
// constructor, and they are plain static functions with no user-data channel.
// So the JS-supplied description has to be parked in a global before the app
// is constructed. This is also why there can only be one app per process --
// TProgram::application, deskTop, menuBar and statusLine are all statics.

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

static AppConfig g_config;
static CommandRegistry g_commands;
static bool g_running = false;

// Set while a JS callback is throwing, so we can unwind the TVision loop and
// rethrow into JS once the terminal has been restored. Throwing a C++
// exception straight through TVision's frames would leave the screen in raw
// mode with a half-drawn dialog on it.
static bool g_hasPendingError = false;
static Napi::Reference<Napi::Value> g_pendingError;
static Napi::FunctionReference g_onCommand;

/* ------------------------------------------------------------------ */
/*  Small JS-reading helpers                                          */
/* ------------------------------------------------------------------ */

static std::string getString(const Napi::Object &o, const char *key,
                             const std::string &dflt = "")
{
    if (!o.Has(key))
        return dflt;
    Napi::Value v = o.Get(key);
    return v.IsUndefined() || v.IsNull() ? dflt : v.ToString().Utf8Value();
}

static bool getBool(const Napi::Object &o, const char *key, bool dflt = false)
{
    if (!o.Has(key))
        return dflt;
    Napi::Value v = o.Get(key);
    return v.IsUndefined() || v.IsNull() ? dflt : v.ToBoolean().Value();
}

static TKey getKey(const Napi::Env &env, const Napi::Object &o, const char *key,
                   const std::string &where)
{
    std::string spec = getString(o, key);
    TKey parsed;
    if (!parseKey(spec, parsed))
        throw Napi::Error::New(env, "tvision: unrecognized key '" + spec +
                                        "' in " + where);
    return parsed;
}

// [x1, y1, x2, y2] -- the same order TRect takes, so examples read like the
// C++ ones they were ported from.
static TRect getRect(const Napi::Env &env, const Napi::Object &o,
                     const char *where)
{
    if (!o.Has("rect"))
        throw Napi::Error::New(env, std::string("tvision: ") + where +
                                        " needs a rect: [x1, y1, x2, y2]");
    Napi::Value v = o.Get("rect");
    if (!v.IsArray())
        throw Napi::Error::New(env, std::string("tvision: ") + where +
                                        " rect must be an array of 4 numbers");
    Napi::Array a = v.As<Napi::Array>();
    if (a.Length() != 4)
        throw Napi::Error::New(env, std::string("tvision: ") + where +
                                        " rect must have exactly 4 numbers");
    int c[4];
    for (uint32_t i = 0; i < 4; ++i)
        c[i] = a.Get(i).ToNumber().Int32Value();
    return TRect(c[0], c[1], c[2], c[3]);
}

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

// Route a user command into JS. Errors are captured rather than propagated:
// see g_pendingError.
static void dispatchToJs(const std::string &name)
{
    if (g_onCommand.IsEmpty() || g_hasPendingError)
        return;

    Napi::Env env = g_onCommand.Env();
    try
        {
        g_onCommand.Call({Napi::String::New(env, name)});
        }
    catch (const Napi::Error &e)
        {
        g_hasPendingError = true;
        g_pendingError = Napi::Reference<Napi::Value>::New(e.Value(), 1);
        }
    catch (const std::exception &e)
        {
        g_hasPendingError = true;
        g_pendingError = Napi::Reference<Napi::Value>::New(
            Napi::Error::New(env, std::string("tvision: ") + e.what()).Value(), 1);
        }

    if (g_hasPendingError && TProgram::application != nullptr)
        {
        // Unwind the event loop so the terminal is restored before the
        // exception surfaces in JS.
        TEvent quit = {};
        quit.what = evCommand;
        quit.message.command = cmQuit;
        TProgram::application->putEvent(quit);
        }
}

void JsApp::handleEvent(TEvent &event)
{
    TApplication::handleEvent(event);

    if (event.what == evCommand && event.message.command >= kUserCmdBase)
        {
        if (const std::string *name = g_commands.nameOf(event.message.command))
            {
            dispatchToJs(*name);
            clearEvent(event);
            }
        }
}

/* ------------------------------------------------------------------ */
/*  Dialogs                                                           */
/* ------------------------------------------------------------------ */

// TDialog only ends a modal dialog for cmOK, cmCancel, cmYes and cmNo
// (tdialog.cpp:77-90). That is why hello.cpp gives all four of its greeting
// buttons cmCancel -- the original could not tell them apart either. Since the
// JS API promises to report *which* button was pressed, user commands have to
// close the dialog too.
class JsDialog : public TDialog {
public:
    JsDialog(const TRect &bounds, TStringView title) noexcept
        : TWindowInit(&TDialog::initFrame), TDialog(bounds, title)
    {
    }

    virtual void handleEvent(TEvent &event) override
    {
        TDialog::handleEvent(event);
        if (event.what == evCommand &&
            event.message.command >= kUserCmdBase &&
            (state & sfModal) != 0)
            {
            endModal(event.message.command);
            clearEvent(event);
            }
    }
};

/* ------------------------------------------------------------------ */
/*  JS surface                                                        */
/* ------------------------------------------------------------------ */

static void requireRunning(const Napi::Env &env, const char *fn)
{
    if (!g_running)
        throw Napi::Error::New(env, std::string("tvision: ") + fn +
                                        "() can only be called while the "
                                        "application is running");
}

// tv.run(config) -- blocks until the application quits.
static Napi::Value Run(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();

    if (g_running)
        throw Napi::Error::New(env, "tvision: run() is already running "
                                    "(one application per process)");
    if (!info[0].IsObject())
        throw Napi::TypeError::New(env, "tvision: run(config) needs a config object");

    // Fail loudly rather than scribbling escape codes into a pipe.
    if (!isatty(STDIN_FILENO) || !isatty(STDOUT_FILENO))
        throw Napi::Error::New(env, "tvision: stdin and stdout must be a terminal "
                                    "(run this in a real terminal, or under a pty)");

    Napi::Object config = info[0].As<Napi::Object>();

    g_config = AppConfig();
    g_commands.reset();
    g_hasPendingError = false;

    if (config.Has("menuBar"))
        parseMenuBar(env, config.Get("menuBar"));
    if (config.Has("statusLine"))
        parseStatusLine(env, config.Get("statusLine"));
    if (config.Has("onCommand"))
        {
        Napi::Value cb = config.Get("onCommand");
        if (!cb.IsFunction())
            throw Napi::TypeError::New(env, "tvision: onCommand must be a function");
        g_onCommand = Napi::Persistent(cb.As<Napi::Function>());
        }

    {
        // Constructing the app takes over the terminal; destroying it gives the
        // terminal back. Nothing between these braces may escape by exception.
        std::unique_ptr<JsApp> app(new JsApp());
        g_running = true;
        app->run();
        g_running = false;
    }

    g_onCommand.Reset();
    g_config = AppConfig();

    if (g_hasPendingError)
        {
        g_hasPendingError = false;
        Napi::Value err = g_pendingError.Value();
        g_pendingError.Reset();
        throw Napi::Error(env, err);
        }

    return env.Undefined();
}

// tv.dialog(spec) -- modal. Returns the name of the command that closed it.
static Napi::Value Dialog(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    requireRunning(env, "dialog");

    if (!info[0].IsObject())
        throw Napi::TypeError::New(env, "tvision: dialog(spec) needs a spec object");
    Napi::Object spec = info[0].As<Napi::Object>();

    TRect bounds = getRect(env, spec, "dialog");
    JsDialog *d = new JsDialog(bounds, getString(spec, "title").c_str());

    if (spec.Has("items"))
        {
        Napi::Array items = spec.Get("items").As<Napi::Array>();
        for (uint32_t i = 0; i < items.Length(); ++i)
            {
            Napi::Object it = items.Get(i).As<Napi::Object>();
            std::string type = getString(it, "type");

            if (type == "staticText")
                {
                d->insert(new TStaticText(getRect(env, it, "staticText"),
                                          getString(it, "text").c_str()));
                }
            else if (type == "button")
                {
                std::string title = getString(it, "title");
                ushort cmd = g_commands.intern(getString(it, "cmd", "cancel"));
                ushort flags = getBool(it, "default") ? bfDefault : bfNormal;
                d->insert(new TButton(getRect(env, it, "button"), title.c_str(),
                                      cmd, flags));
                }
            else
                {
                TObject::destroy(d);
                throw Napi::Error::New(env, "tvision: unknown dialog item type '" +
                                                type + "'");
                }
            }
        }

    ushort result = TProgram::deskTop->execView(d);
    TObject::destroy(d);

    if (const std::string *name = g_commands.nameOf(result))
        return Napi::String::New(env, *name);
    return env.Null();
}

// tv.messageBox(text) -- the stock information box with an OK button.
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

// tv.screenSize() -- so JS can lay dialogs out relative to the terminal.
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
    exports.Set("dialog", Napi::Function::New(env, Dialog));
    exports.Set("messageBox", Napi::Function::New(env, MessageBox));
    exports.Set("quit", Napi::Function::New(env, Quit));
    exports.Set("screenSize", Napi::Function::New(env, ScreenSize));
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
