// Widgets, the id registry, and the JS calls that create and mutate them.

#include "tvnode.h"
#include "keys.h"

#include <algorithm>
#include <cstdlib>
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
    if (!quiet && item >= 0 && (size_t) item < items.size())
        noteFocused(viewId, item, items[item]);
}

void JsListBox::setItems(std::vector<std::string> newItems)
{
    items = std::move(newItems);
    setRange((short) items.size());
    if (!items.empty())
        {
        // Silently. The highlight really does land on row zero here, but that
        // is an artifact of rebuilding rather than anything that happened: the
        // caller always follows setItems with the position it actually wants,
        // and *that* is reported. Announcing the intermediate zero tells the
        // model its highlight moved somewhere it was never going to stay, and
        // a model that acts on where the highlight is -- opening a directory,
        // say -- acts on the wrong one.
        quiet = true;
        focusItem(0);
        quiet = false;
        }
    drawView();
}

// The sandwich: what it was, let TInputLine do whatever it does, what it is
// now. Nothing else can tell a keystroke that inserted a character from one
// that moved the cursor, and nothing else has to.
void JsInputLine::handleEvent(TEvent &event)
{
    std::string before(data);
    TInputLine::handleEvent(event);
    if (!viewId.empty() && before != data)
        noteChangedText(viewId, data);
}

void JsCheckBoxes::handleEvent(TEvent &event)
{
    uint32_t before = value;
    TCheckBoxes::handleEvent(event);
    if (!viewId.empty() && before != value)
        noteChangedFlags(viewId, value, count);
}

int JsMultiCheckBoxes::bitsFor(size_t markCount)
{
    int bits = 1;
    while (((size_t) 1 << bits) < markCount)
        ++bits;
    return bits;
}

JsMultiCheckBoxes::JsMultiCheckBoxes(TRect &bounds, TSItem *items,
                                     uint32_t aCount,
                                     const std::string &theMarks,
                                     std::string id) noexcept
    : TMultiCheckBoxes(bounds, items, (uchar) theMarks.size(),
                       (ushort) ((bitsFor(theMarks.size()) << 8) |
                                 ((1 << bitsFor(theMarks.size())) - 1)),
                       nullptr),
      count(aCount), bits(bitsFor(theMarks.size())),
      mask((uint32_t) ((1 << bitsFor(theMarks.size())) - 1)), marks(theMarks),
      viewId(std::move(id))
{
    // nullptr above, not theMarks.c_str(): see the note on the class.
}

void JsMultiCheckBoxes::draw()
{
    drawMultiBox(" [ ] ", marks.c_str());
}

std::vector<int> JsMultiCheckBoxes::states() const
{
    std::vector<int> out;
    out.reserve(count);
    for (uint32_t i = 0; i < count; ++i)
        out.push_back((int) ((value >> (bits * i)) & mask));
    return out;
}

void JsMultiCheckBoxes::setStates(const std::vector<int> &wanted)
{
    uint32_t packed = 0;
    for (uint32_t i = 0; i < count && i < wanted.size(); ++i)
        packed |= ((uint32_t) wanted[i] & mask) << (bits * i);
    value = packed;
    drawView();
}

// The same sandwich as the other two clusters, and for the same reason: a box
// is cycled by Space, by a click and by its hotkey, and `value` afterwards is
// the only thing all three have in common.
void JsMultiCheckBoxes::handleEvent(TEvent &event)
{
    uint32_t before = value;
    TMultiCheckBoxes::handleEvent(event);
    if (!viewId.empty() && before != value)
        noteChangedMarks(viewId, states());
}

void JsRadioButtons::handleEvent(TEvent &event)
{
    uint32_t before = value;
    TRadioButtons::handleEvent(event);
    if (!viewId.empty() && before != value)
        noteChangedChoice(viewId, (int) value);
}

/* ------------------------------------------------------------------ */
/*  The history drop-down                                             */
/* ------------------------------------------------------------------ */

static void setInputText(TInputLine *input, const std::string &text);

// The items the window under construction is for.
//
// THistInit's factory takes a TRect, a TWindow and a ushort history id, and
// the history id is the one thing we are not using. Live for exactly the
// length of one JsHistoryWindow constructor, on the single thread TVision
// runs on.
static const std::vector<std::string> *g_pendingHistoryItems = nullptr;

JsHistoryViewer::JsHistoryViewer(const TRect &bounds, TScrollBar *hScroll,
                                 TScrollBar *vScroll,
                                 const std::vector<std::string> &theItems) noexcept
    : THistoryViewer(bounds, hScroll, vScroll, 0), items(theItems)
{
    // THistoryViewer's constructor sized itself against the global history
    // block, which is empty here and stays empty, so everything it worked out
    // there is worked out again against the vector.
    //
    // It also focuses row 1 rather than row 0 when there is more than one
    // entry, because in Borland's design row 0 is the value it just recorded
    // out of the field -- the thing the user is trying to replace. Nothing is
    // recorded here, so row 0 is an ordinary entry and gets the highlight.
    setRange((short) items.size());
    int widest = 0;
    for (const std::string &item : items)
        widest = std::max(widest, (int) strwidth(item.c_str()));
    hScrollBar->setRange(0, widest - size.x + 3);
}

void JsHistoryViewer::getText(char *dest, short item, short maxLen)
{
    if (item < 0 || (size_t) item >= items.size())
        {
        *dest = EOS;
        return;
        }
    strncpy(dest, items[item].c_str(), maxLen);
    dest[maxLen] = EOS;
}

JsHistoryWindow::JsHistoryWindow(const TRect &bounds) noexcept
    : TWindowInit(&THistoryWindow::initFrame),
      THistInit(&JsHistoryWindow::initViewer), THistoryWindow(bounds, 0)
{
    // Both bases are virtual, so it is this constructor's initialiser list
    // that decides which factory runs and not THistoryWindow's -- which is
    // exactly what THistInit is a separate virtual base for.
}

TListViewer *JsHistoryWindow::initViewer(TRect r, TWindow *win, ushort)
{
    static const std::vector<std::string> none;
    r.grow(-1, -1);
    return new JsHistoryViewer(
        r, win->standardScrollBar(sbHorizontal | sbHandleKeyboard),
        win->standardScrollBar(sbVertical | sbHandleKeyboard),
        g_pendingHistoryItems != nullptr ? *g_pendingHistoryItems : none);
}

// THistory::handleEvent with two lines taken out of it.
//
// The evBroadcast branch is gone: it records the field into the global block
// when focus leaves, and the model owns the list. And the open path calls
// openDropDown() where Borland calls owner->execView(), which is the whole
// point -- see the note on the classes in tvnode.h.
void JsHistory::handleEvent(TEvent &event)
{
    TView::handleEvent(event);
    if (event.what == evMouseDown ||
        (event.what == evKeyDown && link != nullptr &&
         ctrlToArrow(event.keyDown.keyCode) == kbDown &&
         (link->state & sfFocused) != 0))
        {
        if (link != nullptr && link->focus())
            openDropDown();
        clearEvent(event);
        }
}

void JsHistory::openDropDown()
{
    if (owner == nullptr || link == nullptr)
        return;

    // Borland's rectangle, unchanged (thistory.cpp:89-98): a column wider than
    // the field on either side, seven rows of list below it, clipped to the
    // group it opens in.
    TRect r = link->getBounds();
    r.a.x--;
    r.b.x++;
    r.a.y--;
    r.b.y += 7;
    r.intersect(owner->getExtent());
    r.b.y--;

    g_pendingHistoryItems = &items;
    JsHistoryWindow *window = new JsHistoryWindow(r);
    g_pendingHistoryItems = nullptr;

    // Captured by id rather than by `this`. The model keeps running behind a
    // modal here -- that is what openLocalModal buys -- so it can close the
    // window this field lives in while the drop-down is still up, and `this`
    // would be a dangling pointer by the time the list answered. ~JsWindow
    // clears the registry, so a lookup that finds nothing is the whole check.
    std::string id = viewId;
    openLocalModal(owner, window, [id](TView *view, ushort result) {
        ViewRef *ref = g_views.find(id);
        if (ref != nullptr && ref->kind == "history")
            ((JsHistory *) ref->view)
                ->takeSelection((THistoryWindow *) view, result);
    });
}

void JsHistory::takeSelection(THistoryWindow *window, ushort result)
{
    if (result != cmOK || link == nullptr)
        return;

    char picked[256];
    window->getSelection(picked);

    std::string before(link->data);
    // Selected, unlike a value the model set: the user chose a whole entry and
    // the next thing they type is meant to replace it. That is Borland's
    // selectAll(True) and it is right here for the same reason it is wrong in
    // setInputTextKeepingCaret.
    setInputText(link, picked);
    link->drawView();
    if (!linkViewId.empty() && before != link->data)
        noteChangedText(linkViewId, link->data);
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
                      (event.mouse.eventFlags & meDoubleClick) != 0,
                      (event.mouse.buttons & mbRightButton) != 0);
        clearEvent(event);
        }
}

void JsCanvas::setLines(std::vector<CanvasLine> newLines)
{
    lines = std::move(newLines);
    drawView();
}

/* ------------------------------------------------------------------ */
/*  The editor                                                        */
/* ------------------------------------------------------------------ */

JsEditor::JsEditor(const TRect &bounds, TScrollBar *hScroll, TScrollBar *vScroll,
                   std::string id) noexcept
    : TEditor(bounds, hScroll, vScroll, nullptr, 0x1000), viewId(std::move(id))
{
    // The base constructor already ran TEditor::initBuffer(), which is
    // new char[] -- the virtual call happened before this class existed. Free
    // it the way it was allocated and start again with ours, which is exactly
    // what TFileEditor's constructor does (tfiledtr.cpp:56).
    TEditor::doneBuffer();
    initBuffer();
    isValid = buffer != nullptr;
    setBufLen(0);
}

void JsEditor::initBuffer()
{
    buffer = (char *) malloc(bufSize);
}

void JsEditor::doneBuffer()
{
    free(buffer);
    buffer = nullptr;
}

// TFileEditor::setBufSize (tfiledtr.cpp:221), which is the only reason that
// class is not just a file loader: TEditor's own returns false for anything
// larger than the buffer it started with, so without this the editor fills up
// and silently stops accepting text.
Boolean JsEditor::setBufSize(uint newSize)
{
    if (newSize == 0)
        newSize = 0x1000;
    else if (newSize > uint(-0x1000))
        newSize = UINT_MAX - 0x1F;
    else
        newSize = (newSize + 0x0FFF) & -0x1000;

    if (newSize != bufSize)
        {
        char *old = buffer;
        if ((buffer = (char *) malloc(newSize)) == nullptr)
            {
            free(old);
            return False;
            }
        // The gap is in the middle, so both ends have to survive the move:
        // everything before the caret from the front, everything after it
        // from the back.
        uint tail = bufLen - curPtr + delCount;
        uint keep = newSize < bufSize ? newSize : bufSize;
        memcpy(buffer, old, keep);
        memmove(&buffer[newSize - tail], &old[bufSize - tail], tail);
        free(old);
        bufSize = newSize;
        gapLen = bufSize - bufLen;
        }
    return True;
}

bool JsEditor::setText(const std::string &text)
{
    if (setBufSize((uint) text.size()) == False)
        return false;
    if (!text.empty())
        memcpy(&buffer[bufSize - text.size()], text.data(), text.size());
    // Resets the caret, the selection, the undo counters and `modified`, and
    // works out the line count and the line-ending style from what is there.
    setBufLen((uint) text.size());
    noteEditIfChanged();
    return true;
}

std::string JsEditor::getWholeText()
{
    std::string out;
    out.resize(bufLen);
    if (bufLen > 0)
        getText(0, TSpan<char>(&out[0], bufLen));
    return out;
}

int JsEditor::searchAndReplace(const std::string &what, bool replace,
                               const std::string &replacement, bool matchCase,
                               bool wholeWords, bool all)
{
    if (what.empty())
        return 0;

    ushort opts = 0;
    if (matchCase)
        opts |= efCaseSensitive;
    if (wholeWords)
        opts |= efWholeWordsOnly;

    // Ctrl-L is TEditor's own Search again and reads these three statics, so
    // a search issued from the model leaves the keyboard shortcut working on
    // the same terms. efPromptOnReplace is deliberately not among the flags:
    // the prompt is editorDialog(edReplacePrompt), which is inert, and a loop
    // that asked would therefore stop at the first match.
    strnzcpy(findStr, what.c_str(), sizeof(findStr));
    strnzcpy(replaceStr, replacement.c_str(), sizeof(replaceStr));
    editorFlags = (ushort) (opts | (replace ? efDoReplace : 0) |
                            (all ? efReplaceAll : 0));

    // "All" means the document, not the rest of it. TEditor's own
    // doSearchReplace runs from the caret either way, which makes Replace All
    // quietly depend on where the caret happens to be -- and after a search
    // that ran off the end, that is nothing at all. Everything else here
    // searches forward from the caret, which is what Find should do.
    if (replace && all)
        setCurPtr(0, 0);

    // search() runs forward from the caret and leaves it at the *end* of the
    // match it selected (setSelect with curStart false), so a repeat finds the
    // next one and a replace cannot match what it just inserted.
    int matches = 0;
    while (search(findStr, opts) == True)
        {
        ++matches;
        if (!replace)
            break;
        lock();
        insertText(replacement.data(), (uint) replacement.size(), False);
        trackCursor(False);
        unlock();
        if (!all)
            break;
        }

    noteEditIfChanged();
    return matches;
}

void JsEditor::noteEditIfChanged()
{
    bool nowModified = modified == True;
    if (nowModified == lastModified && curPos.y == lastLine &&
        curPos.x == lastColumn)
        return;
    lastModified = nowModified;
    lastLine = curPos.y;
    lastColumn = curPos.x;
    if (!viewId.empty())
        noteEdited(viewId, nowModified, curPos.y, curPos.x);
}

// The same sandwich as every other widget that reports: there is no one method
// every edit goes through -- typing, Backspace, a click, Ctrl-Y, a paste and
// an undo all land in handleEvent -- and the state afterwards is the only
// thing they have in common.
void JsEditor::handleEvent(TEvent &event)
{
    TEditor::handleEvent(event);
    noteEditIfChanged();
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
// The text a field starts with. selectAll(True) is Turbo Vision's own
// convention for a value handed to a field the user has not touched yet: the
// whole thing is selected, so typing replaces it.
static void setInputText(TInputLine *input, const std::string &text)
{
    strncpy(input->data, text.c_str(), input->maxLen);
    input->data[input->maxLen] = EOS;
    input->selectAll(True);
}

// The text the *model* set, which is a different thing and must not select.
//
// A model that keeps what a Changed event told it renders it straight back,
// and if the render is a little behind the typing -- two keystrokes read in
// one pump, one render still in flight -- the value that arrives is one
// keystroke stale. Writing it costs a repaint and nothing else. Selecting it
// costs the user their next keystroke, which replaces the whole field.
//
// So: text in, caret at the end, nothing selected. That is also the right
// answer for the deliberate case, a model that transforms what was typed.
static void setInputTextKeepingCaret(TInputLine *input, const std::string &text)
{
    strncpy(input->data, text.c_str(), input->maxLen);
    input->data[input->maxLen] = EOS;
    int end = (int) strlen(input->data);
    input->curPos = input->selStart = input->selEnd = end;
    input->firstPos = std::max(0, end - input->size.x + 2);
    input->drawView();
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

static std::vector<int> getIntArray(const Napi::Value &v)
{
    std::vector<int> out;
    if (!v.IsArray())
        return out;
    Napi::Array array = v.As<Napi::Array>();
    for (uint32_t i = 0; i < array.Length(); ++i)
        out.push_back(array.Get(i).ToNumber().Int32Value());
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

Napi::Array checkedArray(const Napi::Env &env, uint32_t bits, uint32_t count)
{
    Napi::Array out = Napi::Array::New(env, count);
    for (uint32_t i = 0; i < count; ++i)
        out.Set(i, Napi::Boolean::New(env, (bits & ((uint32_t) 1 << i)) != 0));
    return out;
}

Napi::Array markArray(const Napi::Env &env, const std::vector<int> &states)
{
    Napi::Array out = Napi::Array::New(env, states.size());
    for (size_t i = 0; i < states.size(); ++i)
        out.Set((uint32_t) i, Napi::Number::New(env, states[i]));
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

// The optional `grow` field a Grows wrapper puts on a view, as TView::growMode.
//
// Absent means zero, which is what every view built before protocol 7 had and
// is "keep my rectangle exactly". gfGrowRel is deliberately not offered: it
// rescales an edge to the same *fraction* of the owner, which is what a window
// on the desktop wants -- beWindow() sets it already -- and which inside a
// window turns a two-line static text into a proportion of the window height.
static uchar growModeOf(const Napi::Object &it)
{
    if (!it.Has("grow"))
        return 0;
    Napi::Value value = it.Get("grow");
    if (!value.IsObject())
        return 0;

    Napi::Object grow = value.As<Napi::Object>();
    uchar mode = 0;
    if (getBool(grow, "left"))
        mode |= gfGrowLoX;
    if (getBool(grow, "top"))
        mode |= gfGrowLoY;
    if (getBool(grow, "right"))
        mode |= gfGrowHiX;
    if (getBool(grow, "bottom"))
        mode |= gfGrowHiY;
    return mode;
}

TView *buildItems(const Napi::Env &env, TGroup *win, const Napi::Value &value,
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
                new JsInputLine(getRect(env, it, "inputLine"), maxLen, id);
            // Structural, like maxLen: a field's filter is part of its shape,
            // so changing one rebuilds the window rather than being patched.
            std::string allowed = getString(it, "allowed");
            if (!allowed.empty())
                input->setValidator(new JsFilterValidator(allowed));
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
        else if (type == "history")
            {
            if (id.empty())
                throw Napi::Error::New(env, "tvision: a history needs an id");
            // Like a label, it points at a view that must already exist -- and
            // unlike a label it has no rectangle of its own. A history icon
            // sits in the three columns immediately right of its field in
            // every Turbo Vision dialog there is (tfildlg.cpp:75,
            // tchdrdlg.cpp:51), which makes the rectangle a consequence of the
            // field rather than a decision, and one fewer thing to get wrong.
            std::string forId = getString(it, "for");
            ViewRef *target = g_views.find(forId);
            if (target == nullptr || target->kind != "inputLine")
                throw Napi::Error::New(env,
                                       "tvision: history for '" + forId +
                                           "', which is not an inputLine listed "
                                           "before it");
            TRect field = target->view->getBounds();
            JsHistory *history =
                new JsHistory(TRect(field.b.x, field.a.y, field.b.x + 3,
                                    field.a.y + 1),
                              (TInputLine *) target->view, id, forId);
            if (it.Has("items"))
                history->setItems(getStringArray(it.Get("items")));
            made = history;
            }
        else if (type == "listBox")
            {
            if (id.empty())
                throw Napi::Error::New(env, "tvision: a listBox needs an id");
            // Beside the list, not on the window's frame.
            //
            // TWindow::standardScrollBar() puts it on the frame, which is
            // right for a Turbo Vision window that is a list and nothing else
            // and wrong for anything with two panes in it -- a directory tree
            // beside a file pane ends up with its scroll bar over on the far
            // side of the files. Here the bar occupies the single column
            // immediately to the right of the list's own rectangle, which is
            // a rule an author can lay out against.
            TRect listRect = getRect(env, it, "listBox");
            TScrollBar *sb = new TScrollBar(
                TRect(listRect.b.x, listRect.a.y, listRect.b.x + 1, listRect.b.y));
            // What standardScrollBar(sbHandleKeyboard) actually sets: the bar
            // sees keystrokes the focused list did not want, which is how
            // PgUp and PgDn reach it.
            sb->options |= ofPostProcess;
            win->insert(sb);
            JsListBox *list = new JsListBox(listRect, sb, id);
            if (it.Has("items"))
                list->setItems(getStringArray(it.Get("items")));
            if (it.Has("focused"))
                list->focusItemNum((short) getInt(it, "focused", 0));
            made = list;
            }
        else if (type == "editor")
            {
            if (id.empty())
                throw Napi::Error::New(env, "tvision: an editor needs an id");
            // Its own scroll bars, in the column to the right and the row
            // below -- the rule a list box already follows, one direction
            // more. TEditor drives both itself; nothing here has to.
            TRect box = getRect(env, it, "editor");
            TScrollBar *down = new TScrollBar(
                TRect(box.b.x, box.a.y, box.b.x + 1, box.b.y));
            TScrollBar *across = new TScrollBar(
                TRect(box.a.x, box.b.y, box.b.x, box.b.y + 1));
            down->options |= ofPostProcess;
            across->options |= ofPostProcess;
            win->insert(down);
            win->insert(across);
            made = new JsEditor(box, across, down, id);
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
                new JsCheckBoxes(getRect(env, it, "checkBoxes"), chain, count, id);
            if (it.Has("value"))
                boxes->setBits(checkedBits(it.Get("value")));
            made = boxes;
            }
        else if (type == "multiCheckBoxes")
            {
            uint32_t count = 0;
            TSItem *chain =
                makeItemChain(env, it.Get("items"), "multiCheckBoxes", count);
            std::string marks = getString(it, "marks");
            if (marks.size() < 2)
                throw Napi::Error::New(env, "tvision: a multiCheckBoxes needs at "
                                            "least two marks (one character per "
                                            "state)");
            int bits = JsMultiCheckBoxes::bitsFor(marks.size());
            if ((uint32_t) bits * count > 32)
                throw Napi::Error::New(
                    env, "tvision: " + std::to_string(count) + " boxes of " +
                             std::to_string(marks.size()) +
                             " states need more than the 32 bits a cluster's "
                             "value has -- use fewer boxes or fewer states");
            TRect where = getRect(env, it, "multiCheckBoxes");
            JsMultiCheckBoxes *boxes =
                new JsMultiCheckBoxes(where, chain, count, marks, id);
            if (it.Has("value"))
                boxes->setStates(getIntArray(it.Get("value")));
            made = boxes;
            }
        else if (type == "radioButtons")
            {
            uint32_t count = 0;
            TSItem *chain = makeItemChain(env, it.Get("items"), "radioButtons", count);
            JsRadioButtons *radio =
                new JsRadioButtons(getRect(env, it, "radioButtons"), chain, id);
            (void) count;
            radio->setSelected((uint32_t) getInt(it, "value", 0));
            made = radio;
            }
        else
            {
            throw Napi::Error::New(env, "tvision: unknown item type '" + type + "'");
            }

        // Before insert, and after the constructor: JsCanvas and friends set
        // growMode themselves, and this is the model overriding them.
        made->growMode = growModeOf(it);

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
        else if (ref->kind == "multiCheckBoxes")
            out.Set(id, markArray(env, ((JsMultiCheckBoxes *) ref->view)->states()));
        else if (ref->kind == "radioButtons")
            out.Set(id, Napi::Number::New(env,
                                          ((JsRadioButtons *) ref->view)->selected()));
        else if (ref->kind == "scrollBar")
            out.Set(id, Napi::Number::New(env, ((JsScrollBar *) ref->view)->value));
        // An "editor" is deliberately absent: a dialog's answer is a small
        // record of what the user chose, and putting a document in one would
        // make every DialogClosed carry it. tv.readEditor() is how a document
        // leaves, and it is asked for by name.
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
    win->beWindow();
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

// tv.setItems(id, [...]) -- replace a list box's contents, or a
// history drop-down's.
static Napi::Value SetItems(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ViewRef *ref = g_views.find(info[0].ToString().Utf8Value());
    if (ref == nullptr)
        return Napi::Boolean::New(env, false);

    if (ref->kind == "listBox")
        ((JsListBox *) ref->view)->setItems(getStringArray(info[1]));
    else if (ref->kind == "history")
        // Nothing is redrawn: the list is read when the drop-down opens, and
        // the icon beside the field looks the same either way.
        ((JsHistory *) ref->view)->setItems(getStringArray(info[1]));
    else
        return Napi::Boolean::New(env, false);
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
    if (ref->kind == "multiCheckBoxes")
        return markArray(env, ((JsMultiCheckBoxes *) ref->view)->states());
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
        setInputTextKeepingCaret((TInputLine *) ref->view,
                                 info[1].ToString().Utf8Value());
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
    if (ref->kind == "multiCheckBoxes")
        {
        ((JsMultiCheckBoxes *) ref->view)->setStates(getIntArray(info[1]));
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

// tv.setEditorText(id, text) -- replace an editor's document.
//
// A command rather than a field on the view: see the note on JsEditor. This is
// the way in, and readEditor is the way out.
static Napi::Value SetEditorText(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ViewRef *ref = g_views.find(info[0].ToString().Utf8Value());
    if (ref == nullptr || ref->kind != "editor")
        return Napi::Boolean::New(env, false);

    bool ok = ((JsEditor *) ref->view)->setText(info[1].ToString().Utf8Value());
    return Napi::Boolean::New(env, ok);
}

// tv.readEditor(id) -- the document, as a string, or null if there is no such
// editor. The one call in this binding that hands back something big, which is
// why it is asked for rather than volunteered.
static Napi::Value ReadEditor(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ViewRef *ref = g_views.find(info[0].ToString().Utf8Value());
    if (ref == nullptr || ref->kind != "editor")
        return env.Null();

    return Napi::String::New(env, ((JsEditor *) ref->view)->getWholeText());
}

// tv.searchEditor(id, {what, replace, replacement, matchCase, wholeWords, all})
// -- find or replace, returning how many matches were acted on.
//
// A number rather than a notification, because the caller is the runtime and
// it turns the number into an event. Nothing here is asked and answered inside
// the model's update: the Cmd goes out and a `Searched` event comes back.
static Napi::Value SearchEditor(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ViewRef *ref = g_views.find(info[0].ToString().Utf8Value());
    if (ref == nullptr || ref->kind != "editor" || !info[1].IsObject())
        return env.Null();

    Napi::Object spec = info[1].As<Napi::Object>();
    int matches = ((JsEditor *) ref->view)
                      ->searchAndReplace(getString(spec, "what"),
                                         getBool(spec, "replace"),
                                         getString(spec, "replacement"),
                                         getBool(spec, "matchCase"),
                                         getBool(spec, "wholeWords"),
                                         getBool(spec, "all"));
    return Napi::Number::New(env, matches);
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
        // Raising the window first is not belt and braces, it is the whole
        // thing. TView::focus() returns at once for a view that is already
        // sfSelected, and sfSelected means "current within my group" -- which
        // a window's first control almost always is, whether or not that
        // window is the active one. So focusing a control in a background
        // window did exactly nothing, and reported success.
        if (JsWindow *owner = g_views.findWindow(ref->windowId))
            {
            owner->select();
            owner->focus();
            }
        ref->view->focus();
        return Napi::Boolean::New(env, true);
        }
    return Napi::Boolean::New(env, false);
}

// tv.setBounds(id, rect) -- move and resize a window where it stands.
//
// The alternative, and what the differ used to do, is to close the window and
// build it again at the new rectangle. That works and throws away everything
// the window was holding: which view had the caret, where the list was
// scrolled, which row was highlighted. It also skips the one thing that makes
// growMode mean anything, because TGroup::changeBounds -- which is where every
// child's edges are recomputed -- only runs on a window that already exists.
//
// TView::locate is the call the frame's own resize handle makes: it clamps to
// sizeLimits, calls changeBounds, and repaints whatever the window uncovered.
static Napi::Value SetBounds(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    JsWindow *win = g_views.findWindow(info[0].ToString().Utf8Value());
    if (win == nullptr)
        return Napi::Boolean::New(env, false);

    if (!info[1].IsArray())
        throw Napi::Error::New(env, "tvision: setBounds needs a rect: "
                                    "[x1, y1, x2, y2]");
    Napi::Array a = info[1].As<Napi::Array>();
    if (a.Length() != 4)
        throw Napi::Error::New(env, "tvision: setBounds rect must have exactly "
                                    "4 numbers");

    // Desktop coordinates, the same as the rect tv.window() was given: locate
    // works in the owner's coordinates and the owner is the desktop.
    TRect bounds(a.Get(0u).ToNumber().Int32Value(),
                 a.Get(1u).ToNumber().Int32Value(),
                 a.Get(2u).ToNumber().Int32Value(),
                 a.Get(3u).ToNumber().Int32Value());
    win->locate(bounds);
    return Napi::Boolean::New(env, true);
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
    exports.Set("setEditorText", Napi::Function::New(env, SetEditorText));
    exports.Set("readEditor", Napi::Function::New(env, ReadEditor));
    exports.Set("searchEditor", Napi::Function::New(env, SearchEditor));
    exports.Set("getValue", Napi::Function::New(env, GetValue));
    exports.Set("setBounds", Napi::Function::New(env, SetBounds));
    exports.Set("setValue", Napi::Function::New(env, SetValue));
    exports.Set("exists", Napi::Function::New(env, Exists));
    exports.Set("focus", Napi::Function::New(env, Focus));
    exports.Set("close", Napi::Function::New(env, Close));
}

} // namespace tvnode
