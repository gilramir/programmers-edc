// Widgets, the id registry, and the JS calls that create and mutate them.

#include "tvnode.h"
#include "keys.h"

#include <cstring>

namespace tvnode {

CommandRegistry g_commands;
ViewRegistry g_views;

/* ------------------------------------------------------------------ */
/*  Widgets                                                           */
/* ------------------------------------------------------------------ */

void JsListBox::getText(char *dest, short item, short maxLen)
{
    if (item < 0 || (size_t) item >= items.size())
        {
        *dest = EOS;
        return;
        }
    strncpy(dest, items[item].c_str(), maxLen);
    dest[maxLen] = EOS;
}

void JsListBox::selectItem(short item)
{
    TListViewer::selectItem(item);
    if (item >= 0 && (size_t) item < items.size())
        dispatchSelect(viewId, item, items[item]);
}

void JsListBox::setItems(std::vector<std::string> newItems)
{
    items = std::move(newItems);
    setRange((short) items.size());
    if (!items.empty())
        focusItem(0);
    drawView();
}

JsWindow::~JsWindow()
{
    // The user can close a window from its frame, and TVision destroys the
    // children with it. This is the only place that reliably runs in every
    // one of those paths.
    g_views.forgetWindow(windowId);
}

void JsWindow::handleEvent(TEvent &event)
{
    TDialog::handleEvent(event);

    // TDialog ends a modal dialog only for cmOK, cmCancel, cmYes and cmNo
    // (tdialog.cpp:77-90), so a button carrying one of our own commands would
    // otherwise do nothing at all. Non-modal windows want the opposite: leave
    // the command alone so it reaches the application and then JS.
    if (event.what == evCommand && event.message.command >= kUserCmdBase &&
        (state & sfModal) != 0)
        {
        endModal(event.message.command);
        clearEvent(event);
        }
}

/* ------------------------------------------------------------------ */
/*  Reading JS values                                                 */
/* ------------------------------------------------------------------ */

std::string getString(const Napi::Object &o, const char *key,
                      const std::string &dflt)
{
    if (!o.Has(key))
        return dflt;
    Napi::Value v = o.Get(key);
    return v.IsUndefined() || v.IsNull() ? dflt : v.ToString().Utf8Value();
}

bool getBool(const Napi::Object &o, const char *key, bool dflt)
{
    if (!o.Has(key))
        return dflt;
    Napi::Value v = o.Get(key);
    return v.IsUndefined() || v.IsNull() ? dflt : v.ToBoolean().Value();
}

int getInt(const Napi::Object &o, const char *key, int dflt)
{
    if (!o.Has(key))
        return dflt;
    Napi::Value v = o.Get(key);
    return v.IsUndefined() || v.IsNull() ? dflt : v.ToNumber().Int32Value();
}

TKey getKey(const Napi::Env &env, const Napi::Object &o, const char *key,
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
TRect getRect(const Napi::Env &env, const Napi::Object &o, const char *where)
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

// TInputLine's constructor takes a *limit* and stores maxLen = limit - 1, with
// a buffer of maxLen + 1 bytes -- so the last writable index is the object's
// own maxLen, not the limit that was passed in. Writing at [limit] is one byte
// past the end of the heap block: it corrupts the next chunk's header and
// aborts much later, when the dialog is destroyed ("free(): invalid size").
// Both callers go through here so the off-by-one cannot come back.
static void setInputText(TInputLine *input, const std::string &text)
{
    strncpy(input->data, text.c_str(), input->maxLen);
    input->data[input->maxLen] = EOS;
    input->selectAll(True);
}

static std::vector<std::string> getStringArray(const Napi::Value &v)
{
    std::vector<std::string> out;
    if (!v.IsArray())
        return out;
    Napi::Array a = v.As<Napi::Array>();
    for (uint32_t i = 0; i < a.Length(); ++i)
        out.push_back(a.Get(i).ToString().Utf8Value());
    return out;
}

/* ------------------------------------------------------------------ */
/*  Building a window's contents                                      */
/* ------------------------------------------------------------------ */

void buildItems(const Napi::Env &env, JsWindow *win, const Napi::Value &value,
                const std::string &windowId)
{
    if (value.IsUndefined() || value.IsNull())
        return;
    if (!value.IsArray())
        throw Napi::Error::New(env, "tvision: items must be an array");

    Napi::Array items = value.As<Napi::Array>();
    for (uint32_t i = 0; i < items.Length(); ++i)
        {
        Napi::Object it = items.Get(i).As<Napi::Object>();
        std::string type = getString(it, "type");
        std::string id = getString(it, "id");
        TView *made = nullptr;

        if (type == "staticText")
            {
            made = new JsStaticText(getRect(env, it, "staticText"),
                                    getString(it, "text").c_str());
            }
        else if (type == "button")
            {
            ushort cmd = g_commands.intern(getString(it, "cmd", "cancel"));
            ushort flags = getBool(it, "default") ? bfDefault : bfNormal;
            made = new TButton(getRect(env, it, "button"),
                               getString(it, "title").c_str(), cmd, flags);
            }
        else if (type == "inputLine")
            {
            int maxLen = getInt(it, "maxLen", 128);
            TInputLine *input =
                new TInputLine(getRect(env, it, "inputLine"), maxLen);
            std::string initial = getString(it, "value");
            if (!initial.empty())
                setInputText(input, initial);
            made = input;
            }
        else if (type == "label")
            {
            // A label points at another view, which therefore has to have been
            // listed before it.
            std::string forId = getString(it, "for");
            ViewRef *target = g_views.find(forId);
            if (target == nullptr)
                throw Napi::Error::New(env, "tvision: label for unknown id '" +
                                                forId + "' (list it before the "
                                                        "label)");
            made = new TLabel(getRect(env, it, "label"),
                              getString(it, "text").c_str(), target->view);
            }
        else if (type == "listBox")
            {
            if (id.empty())
                throw Napi::Error::New(env, "tvision: a listBox needs an id");
            TScrollBar *sb = win->standardScrollBar(sbVertical | sbHandleKeyboard);
            JsListBox *list =
                new JsListBox(getRect(env, it, "listBox"), sb, id);
            if (it.Has("items"))
                list->setItems(getStringArray(it.Get("items")));
            made = list;
            }
        else
            {
            throw Napi::Error::New(env, "tvision: unknown item type '" + type + "'");
            }

        win->insert(made);
        if (!id.empty())
            g_views.addView(id, made, type, windowId);
        }
}

Napi::Object collectValues(const Napi::Env &env, const std::string &windowId)
{
    Napi::Object out = Napi::Object::New(env);
    const std::vector<std::string> *ids = g_views.idsOf(windowId);
    if (ids == nullptr)
        return out;

    for (const std::string &id : *ids)
        {
        ViewRef *ref = g_views.find(id);
        if (ref == nullptr)
            continue;
        if (ref->kind == "inputLine")
            out.Set(id, Napi::String::New(env, ((TInputLine *) ref->view)->data));
        else if (ref->kind == "listBox")
            {
            JsListBox *list = (JsListBox *) ref->view;
            out.Set(id, Napi::Number::New(env, list->focused));
            }
        }
    return out;
}

/* ------------------------------------------------------------------ */
/*  JS surface: windows and mutation                                  */
/* ------------------------------------------------------------------ */

static void requireRunning(const Napi::Env &env, const char *fn)
{
    if (!g_running)
        throw Napi::Error::New(env, std::string("tvision: ") + fn +
                                        "() can only be called while the "
                                        "application is running");
}

// tv.window(spec) -- a non-modal window on the desktop. Returns its id.
static Napi::Value Window(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    requireRunning(env, "window");

    if (!info[0].IsObject())
        throw Napi::TypeError::New(env, "tvision: window(spec) needs a spec object");
    Napi::Object spec = info[0].As<Napi::Object>();

    static int serial = 0;
    std::string id = getString(spec, "id");
    if (id.empty())
        id = "window" + std::to_string(++serial);
    if (g_views.has(id))
        throw Napi::Error::New(env, "tvision: id '" + id + "' is already in use");

    JsWindow *win = new JsWindow(getRect(env, spec, "window"),
                                 getString(spec, "title").c_str(), id);
    g_views.addWindow(id, win);

    try
        {
        buildItems(env, win, spec.Get("items"), id);
        }
    catch (...)
        {
        g_views.forgetWindow(id);
        TObject::destroy(win);
        throw;
        }

    TProgram::deskTop->insert(win);
    return Napi::String::New(env, id);
}

// tv.setText(id, text) -- static text, in place.
static Napi::Value SetText(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ViewRef *ref = g_views.find(info[0].ToString().Utf8Value());
    if (ref == nullptr || ref->kind != "staticText")
        return Napi::Boolean::New(env, false);

    ((JsStaticText *) ref->view)->setText(info[1].ToString().Utf8Value());
    return Napi::Boolean::New(env, true);
}

// tv.setItems(id, [...]) -- replace a list box's contents.
static Napi::Value SetItems(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ViewRef *ref = g_views.find(info[0].ToString().Utf8Value());
    if (ref == nullptr || ref->kind != "listBox")
        return Napi::Boolean::New(env, false);

    ((JsListBox *) ref->view)->setItems(getStringArray(info[1]));
    return Napi::Boolean::New(env, true);
}

// tv.getValue(id) -- the text of an input line, or the focused index of a list.
static Napi::Value GetValue(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ViewRef *ref = g_views.find(info[0].ToString().Utf8Value());
    if (ref == nullptr)
        return env.Null();

    if (ref->kind == "inputLine")
        return Napi::String::New(env, ((TInputLine *) ref->view)->data);
    if (ref->kind == "listBox")
        return Napi::Number::New(env, ((JsListBox *) ref->view)->focused);
    return env.Null();
}

// tv.setValue(id, text) -- set an input line's text.
static Napi::Value SetValue(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ViewRef *ref = g_views.find(info[0].ToString().Utf8Value());
    if (ref == nullptr || ref->kind != "inputLine")
        return Napi::Boolean::New(env, false);

    TInputLine *input = (TInputLine *) ref->view;
    setInputText(input, info[1].ToString().Utf8Value());
    input->drawView();
    return Napi::Boolean::New(env, true);
}

// tv.exists(id) -- ids go away on their own when a window closes, so asking is
// the normal thing to do before touching one.
static Napi::Value Exists(const Napi::CallbackInfo &info)
{
    return Napi::Boolean::New(info.Env(),
                              g_views.has(info[0].ToString().Utf8Value()));
}

// tv.focus(id) -- bring a window to the front, or focus a control.
static Napi::Value Focus(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    std::string id = info[0].ToString().Utf8Value();

    if (JsWindow *win = g_views.findWindow(id))
        {
        win->select();
        win->focus();
        return Napi::Boolean::New(env, true);
        }
    if (ViewRef *ref = g_views.find(id))
        {
        ref->view->focus();
        return Napi::Boolean::New(env, true);
        }
    return Napi::Boolean::New(env, false);
}

// tv.close(id) -- close a window, as its close box would.
static Napi::Value Close(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    JsWindow *win = g_views.findWindow(info[0].ToString().Utf8Value());
    if (win == nullptr)
        return Napi::Boolean::New(env, false);

    win->close();   // destroys the window, which unregisters its ids
    return Napi::Boolean::New(env, true);
}

void registerViewApi(Napi::Env env, Napi::Object exports)
{
    exports.Set("window", Napi::Function::New(env, Window));
    exports.Set("setText", Napi::Function::New(env, SetText));
    exports.Set("setItems", Napi::Function::New(env, SetItems));
    exports.Set("getValue", Napi::Function::New(env, GetValue));
    exports.Set("setValue", Napi::Function::New(env, SetValue));
    exports.Set("exists", Napi::Function::New(env, Exists));
    exports.Set("focus", Napi::Function::New(env, Focus));
    exports.Set("close", Napi::Function::New(env, Close));
}

} // namespace tvnode
