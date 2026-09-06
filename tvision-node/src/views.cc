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
    // Put back rather than dispatched, exactly as TFileDialog does with the
    // cmOK it makes out of a double click: the command then reaches the
    // dialog through the ordinary queue, so JsWindow::handleEvent ends the
    // modal with it and the model is answered by the same `dialogClosed` a
    // press on the button would have sent. Nothing here knows or cares
    // whether the list is in a dialog at all.
    if (chooses != 0)
        {
        TEvent event = {};
        event.what = evCommand;
        event.message.command = chooses;
        event.message.infoPtr = nullptr;
        putEvent(event);
        }
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

void JsListBox::setFocused(short item)
{
    quiet = true;
    focusItemNum(item);
    quiet = false;
    if (focused != item && !items.empty() && focused >= 0 &&
        (size_t) focused < items.size())
        noteFocused(viewId, focused, items[focused]);
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
// Cut, copy and paste, answered here rather than by TInputLine.
//
// The base class routes all three through `TClipboard`, whose fallback store
// this binding cannot read -- so a program that bound the three commands got a
// *second* clipboard invisible from Gren, and a copy made by the model and a
// paste made in a field filled and read different places. app.cc has the whole
// argument. What matters here is that the commands never reach the base class.
//
// `updateCommands` disables cmCut and cmCopy while nothing is selected, so the
// empty case should not arrive; it is answered anyway, by doing nothing rather
// than by putting an empty string on the clipboard, which is what the base
// class would do with it.
void JsInputLine::handleEvent(TEvent &event)
{
    if (event.what == evCommand)
        {
        ushort cmd = event.message.command;
        if (cmd == cmPaste)
            {
            clipboardRequestForView();
            clearEvent(event);
            return;
            }
        if (cmd == cmCut || cmd == cmCopy)
            {
            std::string before(data);
            if (selStart < selEnd)
                {
                clipboardSetFromView(
                    TStringView(data + selStart, selEnd - selStart));
                if (cmd == cmCut)
                    {
                    // The delete, asked for in the only vocabulary TInputLine
                    // exposes: `deleteSelect`, `saveState` and `checkValid` are
                    // all private, and `Del` with a selection out is exactly
                    // those three in that order (tinputli.cpp:399). It is also
                    // a shade better than the base class's own cmCut, which
                    // does not pull `firstPos` back after the text shrinks.
                    TEvent del = {};
                    del.what = evKeyDown;
                    del.keyDown.keyCode = kbDel;
                    TInputLine::handleEvent(del);
                    }
                }
            clearEvent(event);
            if (!viewId.empty() && before != data)
                noteChangedText(viewId, data);
            return;
            }
        }

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

// The mouse capture, which is the one thing a drag needs that Turbo Vision
// has no other way to give.
//
// `TGroup::handleEvent` routes a positional event to `firstThat(hasMouse)` --
// the view the pointer is *currently* over. Every stock view that drags gets
// round that by calling `TView::mouseEvent` in a loop, which pulls events out
// of the queue itself and is therefore a nested event loop: exactly the shape
// this package refuses. So the capture is written out longhand instead. The
// press records the canvas here, the pump hands it every motion and the
// release until the button comes up, and dragging off the edge of the canvas
// -- or off the window, or onto the menu bar -- keeps reporting to the view
// the gesture started in, which is what a selection being dragged means.
//
// One pointer and not a stack: there is one mouse.
static JsCanvas *g_dragCanvas = nullptr;
// The last cell reported, in the canvas's own coordinates. A terminal in mode
// 1002 reports motion per cell, but a press and the first motion are often the
// same cell, and a model told "you are still where you already were" would
// redraw for nothing.
static TPoint g_dragAt = {0, 0};
// Whether this gesture has reported any motion at all. A plain click must stay
// exactly what it is today -- one `Clicked` and nothing else -- so the release
// is reported only when there was a drag to end.
static bool g_dragMoved = false;

TView *mouseCaptureView()
{
    return g_dragCanvas;
}

void clearMouseCapture()
{
    g_dragCanvas = nullptr;
    g_dragMoved = false;
}

JsCanvas::JsCanvas(const TRect &bounds, std::string id, int aColorIndex,
                   bool selectable, bool blockCursorShape) noexcept
    : TView(bounds), viewId(std::move(id)), colorIndex(aColorIndex)
{
    growMode = 0;
    // TView asks for evMouseDown and nothing else of the mouse. A drag is
    // motion and a release, so both have to be asked for -- unconditionally,
    // because dragging is not a thing only a focusable view can be the subject
    // of. See the capture below for what a canvas does with them.
    eventMask |= evMouseMove | evMouseUp;
    if (selectable)
        {
        options |= ofSelectable;
        eventMask |= evKeyboard;   // TView masks keyboard events off by default
        if (blockCursorShape)
            blockCursor();
        }
}

JsCanvas::~JsCanvas()
{
    // A window closed mid-drag would otherwise leave the capture pointing at
    // freed memory, and the pump dereferences it on the very next motion.
    if (g_dragCanvas == this)
        clearMouseCapture();
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
        g_dragCanvas = this;
        g_dragAt = spot;
        g_dragMoved = false;
        dispatchClick(viewId, spot.x, spot.y,
                      (event.mouse.eventFlags & meDoubleClick) != 0,
                      (event.mouse.buttons & mbRightButton) != 0);
        clearEvent(event);
        }
    // The two halves of a drag. Both are guarded on this canvas being the one
    // that was pressed, and the guard is not paranoia: a terminal in mode 1002
    // reports motion whenever a button is down anywhere, so a drag begun on the
    // desktop and pulled across a canvas arrives here as well, and is not this
    // canvas's gesture to hear.
    //
    // The coordinates are `makeLocal` and are deliberately not clamped, so a
    // drag pulled above a canvas reports a negative row. That is the number a
    // model wanting to scroll needs, and a model that only wants the cells it
    // owns can clamp in one line -- whereas a clamped coordinate cannot be
    // un-clamped back into "past the top" by anybody.
    else if (event.what == evMouseMove && g_dragCanvas == this)
        {
        TPoint spot = makeLocal(event.mouse.where);
        if (spot.x != g_dragAt.x || spot.y != g_dragAt.y)
            {
            g_dragAt = spot;
            g_dragMoved = true;
            noteDragged(viewId, spot.x, spot.y, false);
            }
        clearEvent(event);
        }
    else if (event.what == evMouseUp && g_dragCanvas == this)
        {
        TPoint spot = makeLocal(event.mouse.where);
        if (g_dragMoved)
            noteDragged(viewId, spot.x, spot.y, true);
        clearMouseCapture();
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
    // `hasSelection` is not const in TEditor, so it is called rather than
    // read; the other two are members. All three are compared as well as the
    // caret, because a model that greys Undo on this has to hear the update
    // where *only* undoability changed -- the first Ctrl-Z of a session moves
    // nothing else.
    bool nowUndo = canUndo == True;
    bool nowSelected = hasSelection() == True;
    bool nowOverwrite = overwrite == True;
    if (nowModified == lastModified && curPos.y == lastLine &&
        curPos.x == lastColumn && nowUndo == lastCanUndo &&
        nowSelected == lastHasSelection && nowOverwrite == lastOverwrite)
        return;
    lastModified = nowModified;
    lastLine = curPos.y;
    lastColumn = curPos.x;
    lastCanUndo = nowUndo;
    lastHasSelection = nowSelected;
    lastOverwrite = nowOverwrite;
    if (!viewId.empty())
        noteEdited(viewId, nowModified, curPos.y, curPos.x, nowUndo,
                   nowSelected, nowOverwrite);
}

// The same sandwich as every other widget that reports: there is no one method
// every edit goes through -- typing, Backspace, a click, Ctrl-Y, a paste and
// an undo all land in handleEvent -- and the state afterwards is the only
// thing they have in common.
// The same three commands, taken for the same reason as JsInputLine's -- and
// answered with TEditor's own public verbs rather than by rewriting them, since
// here `deleteSelect`, `buffer` and `bufPtr` are all reachable. What is
// replaced is only the two lines inside `clipCopy` and `clipPaste` that name
// `TClipboard` (teditor1.cpp:306 and :329).
void JsEditor::handleEvent(TEvent &event)
{
    if (event.what == evCommand)
        {
        ushort cmd = event.message.command;
        if (cmd == cmPaste)
            {
            clipboardRequestForView();
            clearEvent(event);
            return;
            }
        if (cmd == cmCut || cmd == cmCopy)
            {
            if (selStart < selEnd)
                {
                clipboardSetFromView(TStringView(buffer + bufPtr(selStart),
                                                 selEnd - selStart));
                selecting = False;
                if (cmd == cmCut)
                    deleteSelect();
                else
                    update(ufUpdate);
                }
            clearEvent(event);
            noteEditIfChanged();
            return;
            }
        }

    TEditor::handleEvent(event);
    noteEditIfChanged();
}

void PaneScrollBar::handleEvent(TEvent &event)
{
    // `mouseInView` takes screen coordinates and converts them itself, which
    // is the only reason the bar can ask the question of two views at once.
    // The bar's own column counts as well as the pane's: a wheel turn with
    // the pointer on the bar is the least surprising thing there is.
    if (event.what == evMouseWheel && pane != nullptr &&
        !mouseInView(event.mouse.where) && !pane->mouseInView(event.mouse.where))
        return;
    TScrollBar::handleEvent(event);
}

void JsScrollBar::scrollDraw()
{
    TScrollBar::scrollDraw();
    if (!quiet)
        noteScrolled(viewId, value);
}

void JsScrollBar::tellModelIfItCouldNot(int wanted)
{
    if (value != wanted)
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

// The window in the middle of a move or a resize -- see JsWindow::dragView
// below, which is where all of this is explained. Declared up here because the
// destructor clears it. One window at a time, because there is one mouse and
// one keyboard: the same shape as g_dragCanvas above, and for the same reason.
static JsWindow *g_dragWindow = nullptr;

JsWindow *draggingWindow()
{
    return g_dragWindow;
}

JsWindow::~JsWindow()
{
    // The user can close a window from its frame, and TVision destroys the
    // children with it. This is the only place that reliably runs in every
    // one of those paths.
    // Unregister before notifying, so nothing can look this window up again.
    //
    // The drag pointer goes with it. A window can be closed by the model while
    // the user is dragging it -- the pump keeps running now, which is the whole
    // point, so the model really can act mid-gesture -- and the pump would
    // otherwise route the next mouse move into freed memory. setState is not
    // called here: the window is going away and sfDragging with it.
    if (g_dragWindow == this)
        g_dragWindow = nullptr;
    g_views.forgetWindow(windowId);
    if (reportClose)
        noteWindowClosed(windowId);
}

// The invented rectangle. See the note in tvnode.h for why a window needs one
// at all; what is decided here is only the number.
//
// A fraction and not a fixed size, because the only thing it has to be is
// *visibly not maximized* -- a border of desktop on all four sides is what
// tells the user the click did something, and it is also the frame they need
// in order to drag the window somewhere else. Three quarters leaves that
// border at every terminal size instead of at one.
//
// The floor is free: `TWindow::sizeLimits` reports `minWinSize`, sixteen by
// six (twindow.cpp:30), so a small terminal shrinks to that and stops.
//
// A dimension the model pinned is left at its maximum rather than shrunk,
// which is the rule the zoom itself already follows -- a hex window that is
// seventy-six columns and always will be un-zooms to seventy-six columns and
// fewer rows.
TRect JsWindow::threeQuarters(TPoint minSize, TPoint maxSize) const
{
    TPoint want = maxSize;
    if (canResizeWidth)
        want.x = std::max(minSize.x, maxSize.x * 3 / 4);
    if (canResizeHeight)
        want.y = std::max(minSize.y, maxSize.y * 3 / 4);

    TRect desk = owner == nullptr ? getBounds() : owner->getExtent();
    TRect r(0, 0, want.x, want.y);
    r.move(desk.a.x + (desk.b.x - desk.a.x - want.x) / 2,
           desk.a.y + (desk.b.y - desk.a.y - want.y) / 2);
    return r;
}

TRect JsWindow::fittedToDesktop(TRect r, TPoint minSize, TPoint maxSize) const
{
    TPoint want = {r.b.x - r.a.x, r.b.y - r.a.y};
    want.x = std::min(std::max(want.x, minSize.x), maxSize.x);
    want.y = std::min(std::max(want.y, minSize.y), maxSize.y);

    // The origin is kept where it still fits and pushed in where it does not,
    // rather than re-centred: a window the user put somewhere should come back
    // there, and only the part that cannot be honoured is changed.
    TRect desk = owner == nullptr ? getBounds() : owner->getExtent();
    TRect out(0, 0, want.x, want.y);
    out.move(std::min(std::max(r.a.x, desk.a.x), desk.b.x - want.x),
             std::min(std::max(r.a.y, desk.a.y), desk.b.y - want.y));
    return out;
}

void JsWindow::calcBounds(TRect &bounds, TPoint delta)
{
    TDialog::calcBounds(bounds, delta);

    // The owner has already been given its new size by the time a child's
    // bounds are recalculated (`TGroup::changeBounds` sets its own bounds
    // before it walks its subviews), so this is the desktop the window is
    // about to live on rather than the one it is leaving.
    TPoint minSize, maxSize;
    sizeLimits(minSize, maxSize);
    bounds = fittedToDesktop(bounds, minSize, maxSize);
}

void JsWindow::zoom()
{
    TPoint minSize, maxSize;
    sizeLimits(minSize, maxSize);

    // Only the restoring branch needs anything. Maximizing stores the
    // rectangle the window actually has, which is always a rectangle it
    // actually had.
    if (size == maxSize)
        {
        TRect back = fittedToDesktop(zoomRect, minSize, maxSize);
        zoomRect = back == getBounds() ? threeQuarters(minSize, maxSize) : back;
        }

    TWindow::zoom();
}

/* ------------------------------------------------------------------ */
/*  Dragging a window                                                 */
/* ------------------------------------------------------------------ */

// `TView::moveGrow` is private (views.h:476), so here it is again: the same
// clamps in the same order, ending at the same `locate`. Reproduced rather
// than approximated, because these are the rules that keep a window from being
// dragged entirely off the desktop and they are not obvious.
static void moveGrowInto(TView *view, TPoint p, TPoint s, const TRect &limits,
                         TPoint minSize, TPoint maxSize, uchar mode)
{
    s.x = std::min(std::max(s.x, minSize.x), maxSize.x);
    s.y = std::min(std::max(s.y, minSize.y), maxSize.y);
    p.x = std::min(std::max(p.x, limits.a.x - s.x + 1), limits.b.x - 1);
    p.y = std::min(std::max(p.y, limits.a.y - s.y + 1), limits.b.y - 1);

    if ((mode & dmLimitLoX) != 0)
        p.x = std::max(p.x, limits.a.x);
    if ((mode & dmLimitLoY) != 0)
        p.y = std::max(p.y, limits.a.y);
    if ((mode & dmLimitHiX) != 0)
        p.x = std::min(p.x, limits.b.x - s.x);
    if ((mode & dmLimitHiY) != 0)
        p.y = std::min(p.y, limits.b.y - s.y);

    TRect r(p.x, p.y, p.x + s.x, p.y + s.y);
    view->locate(r);
}

// `TView::change`, which is private for the same reason. Shift is what turns an
// arrow key from a move into a grow, and only when the mode allows both.
static void changeBy(uchar mode, TPoint delta, TPoint &p, TPoint &s,
                     ushort ctrlState)
{
    if ((mode & dmDragMove) != 0 && (ctrlState & kbShift) == 0)
        p += delta;
    else if ((mode & dmDragGrow) != 0 && (ctrlState & kbShift) != 0)
        s += delta;
}

void JsWindow::dragView(TEvent &event, uchar mode, TRect &limits,
                        TPoint minSize, TPoint maxSize)
{
    // A second one cannot start while one is running -- the pump sends every
    // event to the first -- but a window torn down mid-drag can leave the
    // pointer behind, so this is the belt to the destructor's braces.
    if (g_dragWindow != nullptr && g_dragWindow != this)
        g_dragWindow->endDrag();

    drag = Drag();
    drag.mode = mode;
    drag.limits = limits;
    drag.minSize = minSize;
    drag.maxSize = maxSize;
    drag.saved = getBounds();
    drag.bounds = getBounds();
    drag.byMouse = event.what == evMouseDown;

    // dragView's `p`, computed once from the press. Which corner it is about
    // is which of the three mouse branches the mode selects.
    if (drag.byMouse)
        {
        if ((mode & dmDragMove) != 0)
            drag.grip = origin - event.mouse.where;
        else if ((mode & dmDragGrow) != 0)
            drag.grip = size - event.mouse.where;
        else
            {
            TPoint corner = origin;
            corner.y += size.y;
            drag.grip = corner - event.mouse.where;
            }
        }

    drag.active = true;
    g_dragWindow = this;
    setState(sfDragging, True);
}

void JsWindow::endDrag()
{
    if (!drag.active)
        return;
    drag.active = false;
    if (g_dragWindow == this)
        g_dragWindow = nullptr;
    setState(sfDragging, False);
}

void JsWindow::dragEvent(TEvent &event)
{
    if (drag.byMouse)
        {
        if (event.what == evMouseMove)
            {
            TPoint where = event.mouse.where + drag.grip;
            if ((drag.mode & dmDragMove) != 0)
                moveGrowInto(this, where, size, drag.limits, drag.minSize,
                             drag.maxSize, drag.mode);
            else if ((drag.mode & dmDragGrow) != 0)
                moveGrowInto(this, origin, where, drag.limits, drag.minSize,
                             drag.maxSize, drag.mode);
            else
                {
                // dmDragGrowLeft: the left edge follows the pointer and the
                // right one stays where it was, which is why `bounds` is kept.
                drag.bounds.a.x =
                    std::min(std::max(where.x, drag.bounds.b.x - drag.maxSize.x),
                             drag.bounds.b.x - drag.minSize.x);
                drag.bounds.b.y = where.y;
                moveGrowInto(this, drag.bounds.a,
                             drag.bounds.b - drag.bounds.a, drag.limits,
                             drag.minSize, drag.maxSize, drag.mode);
                }
            }
        else if (event.what == evMouseUp)
            endDrag();

        // Everything, and not only the two above. The loop this replaces threw
        // away every event that was not the one it was waiting for, keystrokes
        // included, and a gesture that let some of them through would be a
        // different gesture.
        clearEvent(event);
        return;
        }

    if (event.what == evKeyDown)
        {
        static const TPoint goLeft = {-1, 0}, goRight = {1, 0},
                            goUp = {0, -1}, goDown = {0, 1},
                            goCtrlLeft = {-8, 0}, goCtrlRight = {8, 0},
                            goCtrlUp = {0, -4}, goCtrlDown = {0, 4};

        TPoint p = origin;
        TPoint s = size;
        ushort ctrl = event.keyDown.controlKeyState;
        switch (event.keyDown.keyCode & 0xFF00)
            {
            case kbLeft:      changeBy(drag.mode, goLeft, p, s, ctrl); break;
            case kbRight:     changeBy(drag.mode, goRight, p, s, ctrl); break;
            case kbUp:        changeBy(drag.mode, goUp, p, s, ctrl); break;
            case kbDown:      changeBy(drag.mode, goDown, p, s, ctrl); break;
            case kbCtrlLeft:  changeBy(drag.mode, goCtrlLeft, p, s, ctrl); break;
            case kbCtrlRight: changeBy(drag.mode, goCtrlRight, p, s, ctrl); break;
            case kbCtrlUp:    changeBy(drag.mode, goCtrlUp, p, s, ctrl); break;
            case kbCtrlDown:  changeBy(drag.mode, goCtrlDown, p, s, ctrl); break;
            case kbHome:      p.x = drag.limits.a.x; break;
            case kbEnd:       p.x = drag.limits.b.x - s.x; break;
            case kbPgUp:      p.y = drag.limits.a.y; break;
            case kbPgDn:      p.y = drag.limits.b.y - s.y; break;
            }
        moveGrowInto(this, p, s, drag.limits, drag.minSize, drag.maxSize,
                     drag.mode);

        // After the move and not instead of it, which is the order the loop
        // had: Enter and Esc match none of the cases above, so the moveGrow
        // they fall through to is a no-op on the bounds the last arrow left.
        if (event.keyDown.keyCode == kbEsc)
            {
            locate(drag.saved);
            endDrag();
            }
        else if (event.keyDown.keyCode == kbEnter)
            endDrag();
        }

    clearEvent(event);
}

void JsWindow::handleEvent(TEvent &event)
{
    // A drag owns every event until it ends. Ahead of TDialog::handleEvent
    // because that is what reaches TWindow's cmResize, and a second cmResize
    // arriving mid-drag must not start a drag inside a drag.
    if (drag.active)
        {
        dragEvent(event);
        return;
        }

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

// A cluster's `enabled` field: one boolean per box, so that a form can grey out
// the choices that do not apply without taking the whole cluster away.
//
// `setButtonState` and not `sfDisabled`: disabling the *view* greys every box
// in it, and a cluster is one view however many boxes it has. TCluster keeps a
// bit per item in `enableMask` and skips a disabled one when the arrows walk
// past, which is the behaviour that makes this worth having rather than
// drawing a grey label.
//
// An absent array leaves every box alone, and an array shorter than the
// cluster says nothing about the boxes past its end -- both so that a model
// that does not care says nothing at all.
static void applyItemsEnabled(const Napi::Object &it, TCluster *cluster,
                              uint32_t count)
{
    Napi::Value v = it.Get("enabledItems");
    if (!v.IsArray())
        return;
    Napi::Array flags = v.As<Napi::Array>();
    uint32_t n = flags.Length() < count ? flags.Length() : count;

    // A *mask* and not an index -- `setButtonState(uint32_t aMask, Boolean)`
    // ors or clears every bit it is given at once (tcluster.cpp:299), so the
    // two calls below are the whole cluster rather than one box each. Calling
    // it per box would work and would recompute `ofSelectable` n times.
    uint32_t on = 0, off = 0;
    for (uint32_t i = 0; i < n; ++i)
        {
        if (flags.Get(i).ToBoolean().Value())
            on |= 1u << i;
        else
            off |= 1u << i;
        }
    if (on != 0)
        cluster->setButtonState(on, True);
    if (off != 0)
        cluster->setButtonState(off, False);
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
            // `maxLen + 1`, and the plus one is not a fudge. TInputLine's
            // constructor takes a *limit* and stores `maxLen = limit - 1`
            // (tinputli.cpp), so a field declared four characters wide held
            // three: predc's time converter asked for a four-digit year and
            // got `202`. The name on the Gren side says how many characters
            // the user may type, so this is where the two are reconciled.
            // `setInputText` below writes at `[maxLen]` into a buffer of
            // `maxLen + 1` bytes, which is still the last valid byte.
            int maxLen = getInt(it, "maxLen", 128);
            TInputLine *input =
                new JsInputLine(getRect(env, it, "inputLine"), maxLen + 1, id);
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
            // TListViewer has had columns since 1990 and nothing here said so.
            // They divide the list's own rectangle and fill downwards, so a
            // two-column list of nine items puts five on the left and four on
            // the right -- which is what a list too long for its window often
            // wants instead of a scroll bar.
            int columns = getInt(it, "columns", 1);
            if (columns < 1)
                columns = 1;
            PaneScrollBar *sb = new PaneScrollBar(
                TRect(listRect.b.x, listRect.a.y, listRect.b.x + 1, listRect.b.y));
            // What standardScrollBar(sbHandleKeyboard) actually sets: the bar
            // sees keystrokes the focused list did not want, which is how
            // PgUp and PgDn reach it.
            sb->options |= ofPostProcess;
            win->insert(sb);
            JsListBox *list = new JsListBox(listRect, sb, id, (short) columns);
            // Which pane the wheel belongs to, now that there is one.
            sb->pane = list;
            std::string chooses = getString(it, "chooses");
            if (!chooses.empty())
                list->chooses = g_commands.intern(chooses);
            // TListViewer has had columns since 1990 and nothing here said
            // so. `numCols` divides the list's own rectangle, and the viewer
            // fills the columns downwards -- so a two-column list of nine
            // items puts five on the left and four on the right, which is what
            // a list too long for its window wants rather than a scroll bar.
            //
            if (it.Has("items"))
                list->setItems(getStringArray(it.Get("items")));
            if (it.Has("focused"))
                list->setFocused((short) getInt(it, "focused", 0));
            // After `setFocused`, which scrolls the list to keep the
            // highlight visible and would otherwise undo this. Saying where
            // the window starts *and* where the highlight is are two different
            // sentences, and a model gets to say both -- including the pair
            // that puts the highlight off screen, because the alternative is
            // deciding on the model's behalf which of its two sentences it
            // meant.
            if (it.Has("top"))
                list->setTop((short) getInt(it, "top", 0));
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
            PaneScrollBar *down = new PaneScrollBar(
                TRect(box.b.x, box.a.y, box.b.x + 1, box.b.y));
            PaneScrollBar *across = new PaneScrollBar(
                TRect(box.a.x, box.b.y, box.b.x, box.b.y + 1));
            down->options |= ofPostProcess;
            across->options |= ofPostProcess;
            win->insert(down);
            win->insert(across);
            JsEditor *editor = new JsEditor(box, across, down, id);
            down->pane = editor;
            across->pane = editor;
            // A mode the model sets and the user cannot: TEditor reads it when
            // Enter is pressed and copies the leading whitespace of the line
            // above. `overwrite` is not here beside it on purpose -- the user
            // owns that one, with the Insert key, so it is reported on
            // `Edited` rather than being written.
            editor->autoIndent = getBool(it, "autoIndent", false) ? True : False;
            made = editor;
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
            // `for` names the view this bar scrolls, and is what makes the
            // mouse wheel belong to that view rather than to the whole
            // window. Empty is not an omission: a window whose only
            // scrollable thing is this bar's wants the wheel from everywhere,
            // and that is the majority. Like a label's and a history's, the
            // view has to have been listed already -- and unlike theirs it may
            // be any kind of view at all, because what a model-owned bar
            // scrolls is usually a canvas the model paints.
            std::string scrolls = getString(it, "for");
            if (!scrolls.empty())
                {
                ViewRef *target = g_views.find(scrolls);
                if (target == nullptr)
                    throw Napi::Error::New(env,
                                           "tvision: scrollBar for unknown id '" +
                                               scrolls + "' (list it before the "
                                                         "bar)");
                bar->pane = target->view;
                }
            // setParams in one go: TScrollBar clamps the value against the
            // range, so setting them separately can leave the thumb somewhere
            // neither side asked for.
            bar->setParamsFromModel(getInt(it, "value", 0), getInt(it, "min", 0),
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
            applyItemsEnabled(it, boxes, count);
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
            applyItemsEnabled(it, radio, count);
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

        // After insert and not before. `setState` walks up to the owner to
        // redraw and to hand the caret on, and a view with no owner has
        // nowhere to hand it: disabling before the insert leaves the view grey
        // and still first in the tab order.
        //
        // A disabled view is skipped for focus by `TGroup`, so it must not be
        // what the window opens on either -- hence the check below rather than
        // the `ofSelectable` test alone.
        if (!getBool(it, "enabled", true))
            made->setState(sfDisabled, True);
        if (!getBool(it, "visible", true))
            made->setState(sfVisible, False);

        if (firstSelectable == nullptr && (made->options & ofSelectable) != 0 &&
            (made->state & sfDisabled) == 0)
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

// A window's `resize` field: {width, height}, each saying whether the user may
// change that dimension. Absent means both, which is what every window did
// before the field existed.
static void applyResize(const Napi::Object &spec, JsWindow *win)
{
    Napi::Value v = spec.Get("resize");
    if (!v.IsObject())
        return;
    Napi::Object r = v.As<Napi::Object>();
    win->setResize(getBool(r, "width", true), getBool(r, "height", true));
}

// A window's `canClose` and `canMove`. `beWindow()` turns on all four of
// TWindow's flags together -- move, grow, close and zoom -- and `resize`
// already speaks for the second and fourth, so these are the other two.
//
// A window with no close box is the one somebody wants first: a program whose
// main window *is* the program has nothing sensible to do when the user closes
// it, and telling them so afterwards is worse than not drawing the box.
// `TFrame::draw` reads the flags on every paint, so both are patchable rather
// than structural.
static void applyWindowFlags(const Napi::Object &spec, JsWindow *win)
{
    if (spec.Has("canClose"))
        win->setFlag(wfClose, getBool(spec, "canClose", true));
    if (spec.Has("canMove"))
        win->setFlag(wfMove, getBool(spec, "canMove", true));
}

// A window's `palette` field: "blue", "cyan" or "gray". Absent means blue,
// which is what beWindow() has already set and what a window on the desktop
// has been since Turbo Vision.
//
// The dp* names rather than the wp* ones, for the reason beWindow() gives:
// getPalette() here is TDialog's. The two sets have the same three values, and
// the dialog ones are the thirty-two-entry palettes a window with a button in
// it actually needs.
static void applyWindowPalette(const Napi::Object &spec, JsWindow *win)
{
    std::string which = getString(spec, "palette");
    if (which.empty())
        return;
    if (which == "blue")
        win->setWindowPalette(dpBlueDialog);
    else if (which == "cyan")
        win->setWindowPalette(dpCyanDialog);
    else if (which == "gray")
        win->setWindowPalette(dpGrayDialog);
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
    applyResize(spec, win);
    applyWindowFlags(spec, win);
    applyWindowPalette(spec, win);
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

// tv.setViewEnabled(id, on) -- grey a view out, or bring it back.
//
// Not the same thing as `tv.setEnabled(command, on)` beside it, and the
// difference is the reason this exists: that one greys a *command* wherever it
// appears, and a view without a command -- an input line, a list box, a canvas,
// a scroll bar -- had no way to be unavailable at all.
//
// `sfDisabled` is Turbo Vision's own: a disabled view draws in the palette's
// grey, is skipped by Tab, and is handed no positional or keyboard event
// (`TGroup::doHandleEvent` checks it before anything else). So nothing here has
// to remember that a view is off; the state is the view's.
static Napi::Value SetViewEnabled(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ViewRef *ref = g_views.find(info[0].ToString().Utf8Value());
    if (ref == nullptr)
        return Napi::Boolean::New(env, false);

    bool on = info[1].ToBoolean().Value();
    // Disabling the view the caret is in would leave the caret in a view that
    // cannot be typed into, so hand it on first -- to the next view that will
    // have it, which is what Tab does.
    if (!on && (ref->view->state & sfFocused) != 0 && ref->view->owner != nullptr)
        ref->view->owner->selectNext(False);
    ref->view->setState(sfDisabled, on ? False : True);
    return Napi::Boolean::New(env, true);
}

// tv.setListTop(id, item) -- which entry a list box draws on its first row.
static Napi::Value SetListTop(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ViewRef *ref = g_views.find(info[0].ToString().Utf8Value());
    if (ref == nullptr || ref->kind != "listBox")
        return Napi::Boolean::New(env, false);

    ((JsListBox *) ref->view)->setTop((short) info[1].ToNumber().Int32Value());
    return Napi::Boolean::New(env, true);
}

// tv.setItemsEnabled(id, [bool]) -- one boolean per box of a cluster.
static Napi::Value SetItemsEnabled(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ViewRef *ref = g_views.find(info[0].ToString().Utf8Value());
    if (ref == nullptr || !info[1].IsArray())
        return Napi::Boolean::New(env, false);
    if (ref->kind != "checkBoxes" && ref->kind != "radioButtons" &&
        ref->kind != "multiCheckBoxes")
        return Napi::Boolean::New(env, false);

    Napi::Array flags = info[1].As<Napi::Array>();
    uint32_t on = 0, off = 0;
    for (uint32_t i = 0; i < flags.Length() && i < 32; ++i)
        {
        if (flags.Get(i).ToBoolean().Value())
            on |= 1u << i;
        else
            off |= 1u << i;
        }
    TCluster *cluster = (TCluster *) ref->view;
    if (on != 0)
        cluster->setButtonState(on, True);
    if (off != 0)
        cluster->setButtonState(off, False);
    cluster->drawView();
    return Napi::Boolean::New(env, true);
}

// tv.insertIntoEditor(id, text) -- put text in at the caret, replacing the
// selection if there is one.
//
// Not `setEditorText`, which replaces the document: this is the call a "paste"
// or an "insert template" is made of, and the difference matters because the
// document only crosses the port twice per file by design.
//
// `insertText` and not `insertBuffer`: the first is the same call with the
// buffer arithmetic done for us (`editors.h:219`), and going through it means
// the undo record, the modified flag and the scroll bars are all updated the
// way typing would have updated them.
static Napi::Value InsertIntoEditor(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ViewRef *ref = g_views.find(info[0].ToString().Utf8Value());
    if (ref == nullptr || ref->kind != "editor")
        return Napi::Boolean::New(env, false);

    std::string text = info[1].ToString().Utf8Value();
    return Napi::Boolean::New(
        env, ((JsEditor *) ref->view)->insertAtCaret(text));
}

// tv.bringToFront(id) -- put a window in front of the others and make it the
// active one.
//
// `select()` and not `makeFirst()`, though the gap this closes was named after
// the second: `TWindow` carries `ofTopSelect`, and `TView::select` calls
// `makeFirst()` for a view that has it (tview.cpp:732) *and* hands it the
// caret. Raising a window without focusing it is a state no Turbo Vision
// program has, and nothing has asked for one.
//
// Until now the only way to raise a window was to change something structural
// about it so that the differ tore it down and built it again -- which worked,
// which FINDINGS records as a surprise rather than a feature, and which threw
// away the caret and every list highlight in it on the way.
static Napi::Value BringToFront(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    JsWindow *win = g_views.findWindow(info[0].ToString().Utf8Value());
    if (win == nullptr)
        return Napi::Boolean::New(env, false);
    win->select();
    return Napi::Boolean::New(env, true);
}

// tv.setViewVisible(id, on) -- draw a view, or stop drawing it.
//
// Different from `setViewEnabled` beside it and worth both: a disabled view is
// drawn grey and refuses, a hidden one is not drawn at all and the space it had
// is the window's ground. What makes hiding worth having rather than leaving
// the view out of the render is that the view survives -- an Editor keeps its
// document, a list keeps its highlight, an input line keeps what was typed --
// where leaving it out is a rebuild and throws all of that away.
static Napi::Value SetViewVisible(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    ViewRef *ref = g_views.find(info[0].ToString().Utf8Value());
    if (ref == nullptr)
        return Napi::Boolean::New(env, false);

    bool on = info[1].ToBoolean().Value();
    // Hiding the view with the caret would leave the caret nowhere, so pass it
    // on first -- the same rule, and the same call, as disabling one.
    if (!on && (ref->view->state & sfFocused) != 0 && ref->view->owner != nullptr)
        ref->view->owner->selectNext(False);
    ref->view->setState(sfVisible, on ? True : False);
    return Napi::Boolean::New(env, true);
}

// tv.setWindowFlags(id, {canClose, canMove}) -- whether the user may close or
// move a window, in place. Both are read by TFrame on every paint, so this is a
// redraw rather than a rebuild.
static Napi::Value SetWindowFlags(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    JsWindow *win = g_views.findWindow(info[0].ToString().Utf8Value());
    if (win == nullptr || !info[1].IsObject())
        return Napi::Boolean::New(env, false);

    Napi::Object o = info[1].As<Napi::Object>();
    if (o.Has("canClose"))
        win->setFlag(wfClose, getBool(o, "canClose", true));
    if (o.Has("canMove"))
        win->setFlag(wfMove, getBool(o, "canMove", true));
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
        //
        // `setFocused` and not `focusItemNum`, so that the move is not
        // reported back to the model that asked for it -- see its comment in
        // tvnode.h, and `drive_time.py`'s wheel checks for what happens when
        // it is.
        ((JsListBox *) ref->view)->setFocused((short) info[1].ToNumber().Int32Value());
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
        ((JsScrollBar *) ref->view)
            ->setValueFromModel(info[1].ToNumber().Int32Value());
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
    // The model asked for this, so the resize poll must not report it back as
    // news -- the same rule the Changed event follows for a value the model
    // set itself.
    win->lastReported = win->getBounds();
    return Napi::Boolean::New(env, true);
}

// tv.setWindowPalette(id, name) -- which of the three window colour sets a
// window is drawn in, in place.
//
// Patched rather than structural for the same reason as the title: rebuilding
// a window to recolour it would lose the caret, the z-order and every scroll
// position in it, and TWindow::getPalette reads the member on every draw, so
// there is nothing to rebuild for.
static Napi::Value SetWindowPalette(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    JsWindow *win = g_views.findWindow(info[0].ToString().Utf8Value());
    if (win == nullptr)
        return Napi::Boolean::New(env, false);

    Napi::Object spec = Napi::Object::New(env);
    spec.Set("palette", info[1]);
    applyWindowPalette(spec, win);
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
    exports.Set("setWindowPalette", Napi::Function::New(env, SetWindowPalette));
    exports.Set("setCursor", Napi::Function::New(env, SetCursor));
    exports.Set("setScroll", Napi::Function::New(env, SetScroll));
    exports.Set("setEnabled", Napi::Function::New(env, SetEnabled));
    exports.Set("window", Napi::Function::New(env, Window));
    exports.Set("setText", Napi::Function::New(env, SetText));
    exports.Set("setViewEnabled", Napi::Function::New(env, SetViewEnabled));
    exports.Set("setWindowFlags", Napi::Function::New(env, SetWindowFlags));
    exports.Set("bringToFront", Napi::Function::New(env, BringToFront));
    exports.Set("insertIntoEditor", Napi::Function::New(env, InsertIntoEditor));
    exports.Set("setViewVisible", Napi::Function::New(env, SetViewVisible));
    exports.Set("setListTop", Napi::Function::New(env, SetListTop));
    exports.Set("setItemsEnabled", Napi::Function::New(env, SetItemsEnabled));
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
