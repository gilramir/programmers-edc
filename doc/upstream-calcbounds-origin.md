# Upstream bug report (draft): a window can be left outside the desktop after a resize

**For:** [magiblot/tvision](https://github.com/magiblot/tvision) — not filed yet.
Searched the issue tracker for `calcBounds`, `gfGrowRel`, "outside the desktop",
"off the screen", and for issues about window position after a resize: nothing.
The nearest thing is **[#63](https://github.com/magiblot/tvision/issues/63)**,
"Layout/resizing console window in Windows - will become broken", which is open,
has no diagnosis, and may well be this. Worth linking from the new issue either
way.

---

## Title

`TView::calcBounds` limits a view's size against the desktop but never its
position, so shrinking and re-growing the terminal leaves a window outside it

## What happens

Start any Turbo Vision program on a small terminal, then make the terminal
large again. A `gfGrowAll | gfGrowRel` window — which is what `TWindow`'s
constructor sets, so this is every ordinary window — can end up with its origin
so far to the right that the window extends past the desktop's right or bottom
edge. What you see is a window with **no right border and no bottom border**:
the top border runs to the last column and simply stops.

It is stable, not a repaint artefact: the window really is at those
coordinates, and it stays broken until something else moves it.

## Reproducing it

`tvdemo` in a terminal emulator that can be resized, or in tmux:

1. Start it in a pane about **24 columns by 8 rows**.
2. Open a window (any of them).
3. Make the pane **100x30**.

The window's frame is now incomplete. In our port the same three steps break
seven of sixteen example programs; the two failure shapes are

```
░░░░░░░░░░░░░░░░░░░░░╔═[■]═══════════════════════════════════════ Calculator ═══════════════════════
░░░░░░░░░░░░░░░░░░░░░║
░░░░░░░░░░░░░░░░░░░░░║                  0
```

— the top border with no `╗` on the end of it, the window running off the right
of a 100-column screen — and the same thing vertically, a window whose bottom
border is below the last row and therefore absent.

## Why

`TView::calcBounds` (`source/tvision/tview.cpp:134`):

```cpp
void TView::calcBounds( TRect& bounds, TPoint delta )
{
    bounds = getBounds();

    short s = owner->size.x;
    short d = delta.x;

    if( (growMode & gfGrowLoX) != 0 )
        grow(this, s, d, bounds.a.x);
    if( (growMode & gfGrowHiX) != 0 )
        grow(this, s, d, bounds.b.x);
    ...
    TPoint minLim, maxLim;
    sizeLimits( minLim, maxLim );
    fitToLimits( bounds.a.x, bounds.b.x, minLim.x, maxLim.x, resizeBalance.x );
    fitToLimits( bounds.a.y, bounds.b.y, minLim.y, maxLim.y, resizeBalance.y );
}
```

With `gfGrowRel`, `grow()` scales each coordinate by `s / (s - d)` — the
*coordinates*, both of them, origin included. Then `fitToLimits` is

```cpp
static inline void fitToLimits( int a, int &b, int min, int max, int &balance)
{
    b = a + balancedRange( b - a, min, max, balance );
}
```

which takes `a` as given and clamps only `b - a`: the **width and height** are
limited to `sizeLimits`' maximum, which for a non-`gfFixed` view is
`owner->size` (`tview.cpp:829`). The **origin is never clamped against the
owner at all**.

So a window whose origin scales to column 21 of a 100-column desktop, and whose
width is then clamped to the full 100, occupies columns 21..121 of a desktop
that ends at 100.

The scaling is also lossy in one direction — a window narrower than the
terminal, shrunk to a 24-column desktop, has had its coordinates divided down
and rounded — which is why the round trip is what exposes it rather than a
single resize. That part is inherent to `gfGrowRel` and is not what this report
is about; a window that comes back a different size is defensible, a window
that comes back outside its owner is not.

Same in Borland's original, as far as we can tell, so this is inherited rather
than introduced.

## Suggested fix

Clamp the origin to the owner after the size has been settled — the last two
lines of `calcBounds`, plus something like:

```cpp
    // A view may not be moved outside its owner by a resize. fitToLimits
    // clamps the size and leaves the origin where the scaling put it.
    if( owner != 0 && !(growMode & gfFixed) )
        {
        bounds.move( range(bounds.a.x, 0, max(0, owner->size.x - (bounds.b.x - bounds.a.x))) - bounds.a.x,
                     range(bounds.a.y, 0, max(0, owner->size.y - (bounds.b.y - bounds.a.y))) - bounds.a.y );
        }
```

The same reasoning applies to `TView::locate` (`tview.cpp:585`), which also
clamps the size against `sizeLimits` and leaves the origin alone — that one
bites when a window is un-zoomed onto a desktop narrower than the one it was
zoomed on, and we work around it separately.

## What we did meanwhile

Our port (a Node binding around this library) overrides `calcBounds` on its own
window class and fits the result to the desktop, origin included. It is a
workaround in our subclass, not a patch to the library, because we would rather
the library decided what the right behaviour is:

```cpp
void JsWindow::calcBounds(TRect &bounds, TPoint delta)
{
    TDialog::calcBounds(bounds, delta);
    TPoint minSize, maxSize;
    sizeLimits(minSize, maxSize);
    bounds = fittedToDesktop(bounds, minSize, maxSize);   // clamps the origin too
}
```

`TGroup::changeBounds` sets its own bounds before walking its subviews, so
`owner->size` inside `calcBounds` is already the *new* desktop, which is what
makes this a one-line fix at that point.

## How we found it

A test that starts every program in the repo on a 24x8 terminal, resizes to
100x30, back to 24x8 and up again, and asserts that the active window's frame is
whole — a `╔` with a matching `╗` on the same row, and a bottom border under it
with a corner on each end. Sixteen checks fail without the override and none
with it.
