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

// The highlight, as opposed to a committed selection. TVision's own examples
// read `list->focused` whenever they need it -- tvforms' Edit button does
// exactly that -- and a model that cannot call into C++ has to be told
// instead.
void JsListBox::focusItem(short item)
{
    TListViewer::focusItem(item);
    if (item >= 0 && (size_t) item < items.size())
        noteFocused(viewId, item, items[item]);
}

void JsListBox::setItems(std::vector<std::string> newItems)
{
    items = std::move(newItems);
    setRange((short) items.size());
    if (!items.empty())
        focusItem(0);   // reported too: the highlight really did move
    drawView();
}

JsCanvas::JsCanvas(const TRect &bounds, std::string id, int aColorIndex,
                   bool selectable, bool blockCursorShape) noexcept
    : TView(bounds), viewId(std::move(id)), colorIndex(aColorIndex)
{
    growMode = 0;
    if (selectable)
        {
        options |= ofSelectable;
        eventMask |= evKeyboard;   // TView masks keyboard events off by default
        if (blockCursorShape)
            blockCursor();
        }
}

// A span's colour, resolved against the one the view's palette gives it. A
// span that names neither half paints in the palette colour, which is what
// every canvas did before spans existed; naming one half keeps the other.
static TColorAttr spanColor(const CanvasSpan &span, TColorAttr base)
{
    if (span.fg < 0 && span.bg < 0)
        return base;
    TColorAttr attr = base;
    if (span.fg >= 0)
        attr.setForeground(TColor(TColorBIOS((uint8_t) span.fg)));
    if (span.bg >= 0)
        attr.setBackground(TColor(TColorBIOS((uint8_t) span.bg)));
    return attr;
}

void JsCanvas::draw()
{
    TDrawBuffer b;
    TColorAttr color = getColor((ushort) colorIndex);

    for (int y = 0; y < size.y; ++y)
        {
        b.moveChar(0, ' ', color, (ushort) size.x);
        if (y < (int) lines.size())
            {
            // moveStr returns the number of *cells* it wrote, which is not the
            // length of the string: magiblot's TVision draws Unicode, and a
            // box-drawing character is one cell where its UTF-8 is three
            // bytes. Advancing by anything else puts every span after the
            // first in the wrong column.
            ushort at = 0;
            for (const CanvasSpan &span : lines[y])
                {
                if (at >= (ushort) size.x)
                    break;
                at += b.moveStr(at, TStringView(span.text),
                                spanColor(span, color));
                }
            }
        writeLine(0, (short) y, (short) size.x, 1, b);
        }
}

void JsCanvas::handleEvent(TEvent &event)
{
    TView::handleEvent(event);

    // A focused canvas consumes its keys, the way tvdemo's TTable does. If JS
    // wants a key to fall through it should not make the canvas selectable.
    if (event.what == evKeyDown && (state & sfFocused) != 0)
        {
        dispatchKey(viewId, keyName(event));
        clearEvent(event);
        }
    else if (event.what == evMouseDown)
        {
        TPoint spot = makeLocal(event.mouse.where);
        dispatchClick(viewId, spot.x, spot.y,
                      (event.mouse.eventFlags & meDoubleClick) != 0);
        clearEvent(event);
        }
}

void JsCanvas::setLines(std::vector<CanvasLine> newLines)
{
    lines = std::move(newLines);
    drawView();
}

void JsScrollBar::scrollDraw()
{
    TScrollBar::scrollDraw();
    noteScrolled(viewId, value);
}

void JsCanvas::setCursorAt(int x, int y, bool visible)
{
    setCursor(x, y);
    if (visible)
        showCursor();
    else
        hideCursor();
}

JsWindow::~JsWindow()
{
    // The user can close a window from its frame, and TVision destroys the
    // children with it. This is the only place that reliably runs in every
    // one of those paths.
    // Unregister before notifying, so nothing can look this window up again.
    g_views.forgetWindow(windowId);
    if (reportClose)
        noteWindowClosed(windowId);
}

void JsWindow::handleEvent(TEvent &event)
{
    TDialog::handleEvent(event);

    // TDialog ends a modal dialog only for cmOK, cmCancel, cmYes and cmNo
    // (tdialog.cpp:77-90), so a button carrying one of our own commands would
    // otherwise do nothing at all. Non-modal windows want the opposite: leave
    // the command alone so it reaches the application and then JS.
    if (event.what == evCommand && event.message.command >= kUserCmdFirst &&
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

// Each entry is a string (the whole line, in the view's colour) or an array
// of {text, fg, bg}. Anything else is dropped rather than thrown on: a canvas
// is repainted on every render, and a throw here would take down the pump.
std::vector<CanvasLine> getCanvasLines(const Napi::Value &v)
{
    std::vector<CanvasLine> out;
    if (!v.IsArray())
        return out;
    Napi::Array rows = v.As<Napi::Array>();
    for (uint32_t y = 0; y < rows.Length(); ++y)
        {
        Napi::Value row = rows.Get(y);
        CanvasLine line;
        if (row.IsArray())
            {
            Napi::Array spans = row.As<Napi::Array>();
            for (uint32_t i = 0; i < spans.Length(); ++i)
                {
                Napi::Value entry = spans.Get(i);
                if (entry.IsString())
                    {
                    line.push_back(CanvasSpan{entry.ToString().Utf8Value(), -1, -1});
                    continue;
                    }
                if (!entry.IsObject())
                    continue;
                Napi::Object span = entry.As<Napi::Object>();
                line.push_back(CanvasSpan{getString(span, "text"),
                                          getInt(span, "fg", -1),
                                          getInt(span, "bg", -1)});
                }
            }
        else if (!row.IsUndefined() && !row.IsNull())
            {
            line.push_back(CanvasSpan{row.ToString().Utf8Value(), -1, -1});
            }
        out.push_back(std::move(line));
        }
    return out;
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

// TSItem is a singly linked list built back to front.
// Check boxes are a bitmask in TVision and an array of booleans in JS.
static uint32_t checkedBits(const Napi::Value &value)
{
    uint32_t bits = 0;
    if (!value.IsArray())
        return bits;
    Napi::Array a = value.As<Napi::Array>();
    for (uint32_t i = 0; i < a.Length() && i < 32; ++i)
        if (a.Get(i).ToBoolean().Value())
            bits |= (uint32_t) 1 << i;
    return bits;
}

static Napi::Array checkedArray(const Napi::Env &env, uint32_t bits, uint32_t count)
{
    Napi::Array out = Napi::Array::New(env, count);
    for (uint32_t i = 0; i < count; ++i)
        out.Set(i, Napi::Boolean::New(env, (bits & ((uint32_t) 1 << i)) != 0));
    return out;
}

static TSItem *makeItemChain(const Napi::Env &env, const Napi::Value &value,
                             const char *what, uint32_t &count)
{
    std::vector<std::string> labels = getStringArray(value);
    if (labels.empty())
        throw Napi::Error::New(env, std::string("tvision: ") + what +
                                        " needs a non-empty items array");
    TSItem *head = nullptr;
    for (size_t i = labels.size(); i-- > 0;)
        head = new TSItem(labels[i].c_str(), head);
    count = (uint32_t) labels.size();
    return head;
}

/* ------------------------------------------------------------------ */
/*  Building a window's contents                                      */
/* ------------------------------------------------------------------ */

TView *buildItems(const Napi::Env &env, JsWindow *win, const Napi::Value &value,
                  const std::string &windowId)
{
    TView *firstSelectable = nullptr;
    if (value.IsUndefined() || value.IsNull())
        return firstSelectable;
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
            TButton *button = new TButton(getRect(env, it, "button"),
                                          getString(it, "title").c_str(), cmd,
                                          flags);
            // A keypad -- tvdemo's calculator, a toolbar -- wants buttons that
            // can be pressed but never hold the caret, because something else
            // in the window is reading the keyboard. That is exactly what the
            // C++ calculator does to its twenty buttons, and clearing
            // ofSelectable is how.
            if (!getBool(it, "focusable", true))
                button->options &= ~ofSelectable;
            made = button;
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
            if (it.Has("focused"))
                list->focusItemNum((short) getInt(it, "focused", 0));
            made = list;
            }
        else if (type == "canvas")
            {
            if (id.empty())
                throw Napi::Error::New(env, "tvision: a canvas needs an id");
            // A cursor position implies a cursor: asking for one is the only
            // reason to care what shape it is.
            Napi::Value at = it.Has("cursorAt") ? it.Get("cursorAt") : env.Null();
            JsCanvas *canvas =
                new JsCanvas(getRect(env, it, "canvas"), id,
                             getInt(it, "color", 6),
                             getBool(it, "selectable", true),
                             getString(it, "cursor") == "block" || at.IsArray());
            if (it.Has("lines"))
                canvas->setLines(getCanvasLines(it.Get("lines")));
            if (getBool(it, "framed"))
                canvas->options |= ofFramed;
            made = canvas;
            }
        else if (type == "scrollBar")
            {
            if (id.empty())
                throw Napi::Error::New(env, "tvision: a scrollBar needs an id");
            JsScrollBar *bar =
                new JsScrollBar(getRect(env, it, "scrollBar"), id);
            // setParams in one go: TScrollBar clamps the value against the
            // range, so setting them separately can leave the thumb somewhere
            // neither side asked for.
            bar->setParams(getInt(it, "value", 0), getInt(it, "min", 0),
                           getInt(it, "max", 100), getInt(it, "pageStep", 10),
                           getInt(it, "arrowStep", 1));
            made = bar;
            }
        else if (type == "checkBoxes")
            {
            uint32_t count = 0;
            TSItem *chain = makeItemChain(env, it.Get("items"), "checkBoxes", count);
            JsCheckBoxes *boxes =
                new JsCheckBoxes(getRect(env, it, "checkBoxes"), chain, count);
            if (it.Has("value"))
                boxes->setBits(checkedBits(it.Get("value")));
            made = boxes;
            }
        else if (type == "radioButtons")
            {
            uint32_t count = 0;
            TSItem *chain = makeItemChain(env, it.Get("items"), "radioButtons", count);
            JsRadioButtons *radio =
                new JsRadioButtons(getRect(env, it, "radioButtons"), chain);
            (void) count;
            radio->setSelected((uint32_t) getInt(it, "value", 0));
            made = radio;
            }
        else
            {
            throw Napi::Error::New(env, "tvision: unknown item type '" + type + "'");
            }

        win->insert(made);
        if (firstSelectable == nullptr && (made->options & ofSelectable) != 0)
            firstSelectable = made;
        if (!id.empty())
            g_views.addView(id, made, type, windowId);
        }

    return firstSelectable;
}

// Cursors are placed after the window is on screen, not while it is being
// built. TVision moves the hardware cursor when a view is *focused*, and a
// view that has not been inserted yet cannot be: setting it during
// construction leaves the position on the object and never on the terminal.
void applyCursors(const Napi::Env &env, const Napi::Value &value)
{
    if (!value.IsArray())
        return;

    Napi::Array items = value.As<Napi::Array>();
    for (uint32_t i = 0; i < items.Length(); ++i)
        {
        Napi::Object it = items.Get(i).As<Napi::Object>();
        if (getString(it, "type") != "canvas" || !it.Has("cursorAt"))
            continue;
        Napi::Value at = it.Get("cursorAt");
        if (!at.IsArray())
            continue;
        ViewRef *ref = g_views.find(getString(it, "id"));
        if (ref == nullptr || ref->kind != "canvas")
            continue;

        Napi::Array xy = at.As<Napi::Array>();
        ((JsCanvas *) ref->view)
            ->setCursorAt(xy.Get((uint32_t) 0).ToNumber().Int32Value(),
                          xy.Get((uint32_t) 1).ToNumber().Int32Value(), true);
        }
}

void applyInitialFocus(const Napi::Object &spec, TView *firstSelectable)
{
    std::string wanted = getString(spec, "focus");
    if (!wanted.empty())
        {
        if (ViewRef *ref = g_views.find(wanted))
            {
            ref->view->focus();
            return;
            }
        }
    if (firstSelectable != nullptr)
        firstSelectable->focus();
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
            out.Set(id, Napi::Number::New(env, ((JsListBox *) ref->view)->focused));
        else if (ref->kind == "checkBoxes")
            {
            JsCheckBoxes *boxes = (JsCheckBoxes *) ref->view;
            out.Set(id, checkedArray(env, boxes->bits(), boxes->count));
            }
        else if (ref->kind == "radioButtons")
            out.Set(id, Napi::Number::New(env,
                                          ((JsRadioButtons *) ref->view)->selected()));
        else if (ref->kind == "scrollBar")
            out.Set(id, Napi::Number::New(env, ((JsScrollBar *) ref->view)->value));
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

    TView *firstSelectable = nullptr;
    try
        {
        firstSelectable = buildItems(env, win, spec.Get("items"), id);
        }
    catch (...)
        {
        g_views.forgetWindow(id);
        TObject::destroy(win);
        throw;
        }

    TProgram::deskTop->insert(win);
    applyInitialFocus(spec, firstSelectable);
    applyCursors(env, spec.Get("items"));
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

// tv.setTitle(id, text) -- a window's title, in place.
//
// Worth having rather than rebuilding: a title that shows a count changes on
// every update, and tearing a window down to change it loses focus and
// z-order -- the exact thing a declarative layer exists to avoid.
static Napi::Value SetTitle(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    JsWindow *win = g_views.findWindow(info[0].ToString().Utf8Value());
    if (win == nullptr)
        return Napi::Boolean::New(env, false);

    // Same ownership rules as TStaticText's text: newStr in, delete[] out.
    delete[] (char *) win->title;
    win->title = newStr(info[1].ToString().Utf8Value().c_str());
    if (win->frame != nullptr)
        win->frame->drawView();
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
    if (ref->kind == "checkBoxes")
        {
        JsCheckBoxes *boxes = (JsCheckBoxes *) ref->view;
        return checkedArray(env, boxes->bits(), boxes->count);
        }
    if (ref->kind == "radioButtons")
        return Napi::Number::New(env, ((JsRadioButtons *) ref->view)->selected());
    return env.Null();
}

// tv.setValue(id, value) -- an input line's text, a cluster's state, or the
// highlighted row of a list box.
static Napi::Value SetValue(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ViewRef *ref = g_views.find(info[0].ToString().Utf8Value());
    if (ref == nullptr)
        return Napi::Boolean::New(env, false);

    if (ref->kind == "inputLine")
        {
        TInputLine *input = (TInputLine *) ref->view;
        setInputText(input, info[1].ToString().Utf8Value());
        input->drawView();
        return Napi::Boolean::New(env, true);
        }
    if (ref->kind == "listBox")
        {
        // The other half of onFocus: the highlight is something the model can
        // read *and* set, which is what makes a re-sorted list able to keep
        // the record the user was looking at.
        ((JsListBox *) ref->view)->focusItemNum((short) info[1].ToNumber().Int32Value());
        return Napi::Boolean::New(env, true);
        }
    if (ref->kind == "checkBoxes")
        {
        ((JsCheckBoxes *) ref->view)->setBits(checkedBits(info[1]));
        return Napi::Boolean::New(env, true);
        }
    if (ref->kind == "radioButtons")
        {
        ((JsRadioButtons *) ref->view)
            ->setSelected((uint32_t) info[1].ToNumber().Uint32Value());
        return Napi::Boolean::New(env, true);
        }
    if (ref->kind == "scrollBar")
        {
        ((JsScrollBar *) ref->view)->setValue(info[1].ToNumber().Int32Value());
        return Napi::Boolean::New(env, true);
        }
    return Napi::Boolean::New(env, false);
}

// tv.setScroll(id, value, min, max, pageStep, arrowStep) -- the whole of a
// scroll bar at once, because TScrollBar clamps the value against the range
// and setting the two separately can land the thumb somewhere neither side
// asked for.
static Napi::Value SetScroll(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ViewRef *ref = g_views.find(info[0].ToString().Utf8Value());
    if (ref == nullptr || ref->kind != "scrollBar")
        return Napi::Boolean::New(env, false);

    ((JsScrollBar *) ref->view)
        ->setParams(info[1].ToNumber().Int32Value(),
                    info[2].ToNumber().Int32Value(),
                    info[3].ToNumber().Int32Value(),
                    info[4].ToNumber().Int32Value(),
                    info[5].ToNumber().Int32Value());
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

// tv.setLines(id, [...]) -- repaint a canvas.
static Napi::Value SetLines(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ViewRef *ref = g_views.find(info[0].ToString().Utf8Value());
    if (ref == nullptr || ref->kind != "canvas")
        return Napi::Boolean::New(env, false);

    ((JsCanvas *) ref->view)->setLines(getCanvasLines(info[1]));
    return Napi::Boolean::New(env, true);
}

// tv.setCursor(id, x, y, visible) -- the hardware cursor inside a canvas, in
// the view's own coordinates. This is how tvdemo's ASCII table shows which
// character is selected.
static Napi::Value SetCursor(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ViewRef *ref = g_views.find(info[0].ToString().Utf8Value());
    if (ref == nullptr || ref->kind != "canvas")
        return Napi::Boolean::New(env, false);

    bool visible = info.Length() < 4 || info[3].ToBoolean().Value();
    ((JsCanvas *) ref->view)
        ->setCursorAt(info[1].ToNumber().Int32Value(),
                      info[2].ToNumber().Int32Value(), visible);
    return Napi::Boolean::New(env, true);
}

// tv.setEnabled(cmd, on) -- grey a command out everywhere it appears. Menus
// and status lines pick this up on the next idle, via cmCommandSetChanged.
static Napi::Value SetEnabled(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ushort cmd = g_commands.intern(info[0].ToString().Utf8Value());
    if (info[1].ToBoolean().Value())
        TView::enableCommand(cmd);
    else
        TView::disableCommand(cmd);
    return Napi::Boolean::New(env, true);
}

void registerViewApi(Napi::Env env, Napi::Object exports)
{
    exports.Set("setLines", Napi::Function::New(env, SetLines));
    exports.Set("setTitle", Napi::Function::New(env, SetTitle));
    exports.Set("setCursor", Napi::Function::New(env, SetCursor));
    exports.Set("setScroll", Napi::Function::New(env, SetScroll));
    exports.Set("setEnabled", Napi::Function::New(env, SetEnabled));
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
