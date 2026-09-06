# Upstream bug report: a window can be left outside the desktop after a resize

**Filed as [magiblot/tvision#235](https://github.com/magiblot/tvision/issues/235).**

Before filing, the issue tracker was searched for `calcBounds`, `gfGrowRel`,
"outside the desktop", "off the screen", and for issues about window position
after a resize: nothing. The nearest thing is
**[#63](https://github.com/magiblot/tvision/issues/63)**, "Layout/resizing
console window in Windows - will become broken", which is open, has no
diagnosis, and may well be this.

The fix below lives in our fork as `fix/calcbounds-origin`, one commit off
upstream `master`, and is carried on `patches`. No pull request has been opened
yet — the issue came first, deliberately, because the per-axis guard is a
judgement call the maintainer may want to make differently.

---

## Title

`TView::calcBounds` limits a view's size against the desktop but never its
position, so shrinking and re-growing the terminal leaves a window outside it

## What happens

Start any Turbo Vision program on a small terminal, then make the terminal
large again. A `gfGrowAll | gfGrowRel` window — which is what `TWindow`'s
constructor sets, so this is every window that does not opt out — can end up
with its origin so far to the right that the window extends past the desktop's
right or bottom edge. What you see is a window with **no right border and no bottom border**:
the top border runs to the last column and simply stops.

It is stable, not a repaint artefact: the window really is at those
coordinates, and it stays broken until something else moves it.

## Reproducing it

The bug needs a window that both grows relatively **and** has a non-zero
origin, because `grow()` scales the origin and zero scales to zero. `TWindow`'s
constructor gives every window the first (`twindow.cpp:51`), but `TDialog`'s
sets `growMode = 0` (`tdialog.cpp:29`), and `tvdemo`'s own windows opt out one
way or another:

| window | class | `growMode` |
| --- | --- | --- |
| Calculator, Mouse, Colors, Background | `TDialog` | `0`, from the constructor |
| Calendar, Ascii Table, Puzzle | `TWindow` | set to `0` explicitly |
| File viewer | `TWindow` | `gfGrowHiX \| gfGrowHiY` — the origin never scales |
| **Event Viewer** | `TWindow` | **the default `gfGrowAll \| gfGrowRel`** |

So the Event Viewer is the only candidate in the demo, and it opens full-screen
at origin `(0, 0)` — which is why it has to be moved by hand before any of this
shows. That is plausibly why the bug has gone unnoticed for so long: the
shipped demo cannot demonstrate it untouched.

In `tvdemo`, in a terminal that can be resized (tmux, or dragging the corner):

1. Start it in a pane about **100x30**.
2. `Alt-0` for the Event Viewer.
3. Make it narrow and park it against the **right** edge — drag its
   bottom-right corner leftwards, then drag its title bar to the right.
   (`Ctrl-F5`, then `Shift-←` and `→` and `Enter`, does the same from the
   keyboard.) It should end up somewhere around columns 60..100.
4. Resize the pane to something much smaller — **24x8**, say, or narrower
   still, such as **4 columns by 30 rows**. The window is already wrong here:
   it has been scaled down below `minWinSize.x`, which is 16, and `fitToLimits`
   puts those 16 columns back by moving the *right* edge outwards from an
   origin it never checks.
5. Resize the pane back to **100x30**. The window comes back outside the
   desktop — and how far outside depends on how narrow the intermediate was,
   because the scaling multiplies the origin by the ratio between the two
   widths. A narrower intermediate throws it further, and past a point a
   different limit starts to matter:

   | intermediate | comes back at | width | what gets clamped |
   | --- | --- | --- | --- |
   | 24x8 | columns 58..118 | 60 | nothing — 60 is under the maximum |
   | 4x30 | columns 50..150 | 100 | the width, to exactly the desktop's |

   From 24x8 no limit is reached at all, so the misplacement is purely the
   unchecked scaled origin. From 4 columns the raw width scales to about 400 and
   `fitToLimits` *does* clamp it — to `sizeLimits`' maximum, which for a
   non-`gfFixed` view is `owner->size.x`, exactly 100 — and then leaves the
   origin at 50, giving a window precisely as wide as the whole desktop that
   begins halfway across it.

Either way the frame is incomplete: the top border runs to the last column with
no `╗` on the end of it, no row below it has a right `║`, and there is no
bottom-right corner. In the narrower case the centred title is cut in half by
the edge of the screen as well, which is the clearest thing to look at.

<!-- screenshot goes here: the 4-column case, back at 100x30 -->

In our port no hand-positioning is needed, because its windows are placed at
non-zero origins by the applications themselves — so there the plain recipe of
starting at 24x8, opening a window and going to 100x30 breaks seven of sixteen
example programs. The two failure shapes are

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
that ends at 100. That is the 4-column run above, in `tvdemo` and unmodified:
columns 50..150 of a desktop 100 wide.

The scaling is also lossy in one direction — a window narrower than the
terminal, shrunk to a 24-column desktop, has had its coordinates divided down
and rounded — which is why the round trip is what exposes it rather than a
single resize. That part is inherent to `gfGrowRel` and is not what this report
is about; a window that comes back a different size is defensible, a window
that comes back outside its owner is not.

Same in Borland's original, as far as we can tell, so this is inherited rather
than introduced.

## Suggested fix

Clamp the origin to the owner once the size has been settled. Written out, and
tested — see below:

```cpp
// A resize may change a view's size, but it must not leave the view outside
// its owner. fitToLimits clamps the size and takes the origin as given, so a
// relatively-grown origin -- or one left behind by a shrink -- can put the
// whole view past the owner's edge. Slide it back; a view too big to fit is
// pinned to the origin rather than dragged negative.
static inline void fitToOwner( int &a, int &b, int ownerSize )
{
    int last = ownerSize - (b - a);
    if( last < 0 )
        last = 0;
    int d = range( a, 0, last ) - a;
    a += d;
    b += d;
}
```

called from the end of `calcBounds`, after the two `fitToLimits` lines:

```cpp
    // Only on an axis the view actually grows on: a view that does not grow
    // keeps the bounds it came in with, and moving it here would shove fixed
    // controls around inside a shrinking window instead of clipping them.
    if( owner != 0 && (growMode & gfFixed) == 0 )
        {
        if( (growMode & (gfGrowLoX | gfGrowHiX)) != 0 )
            fitToOwner( bounds.a.x, bounds.b.x, owner->size.x );
        if( (growMode & (gfGrowLoY | gfGrowHiY)) != 0 )
            fitToOwner( bounds.a.y, bounds.b.y, owner->size.y );
        }
```

The per-axis guard is the one judgement call in it. A view with no grow bits
on an axis comes out of `calcBounds` with the bounds it went in with, so
clamping it there would be a new behaviour rather than a fix: fixed controls
inside a shrinking window would slide together instead of being clipped, which
is not what any of them was laid out for. Clamping only where the view already
moves leaves every currently-working case byte-identical.

A shrink reaches the same broken state without `gfGrowRel` at all, which is why
the guard is `gfGrowLoX | gfGrowHiX` and not `gfGrowRel`: a `gfGrowHiX` view at
columns 50..100 of a 100-column owner keeps its origin at 50 when the owner
becomes 24 wide, and `fitToLimits` then grows it rightwards from there.

### Tested

Applied to `tview.cpp` and rebuilt, this fixes both runs above:

```
                          before                after
  24x8    round trip      58..118, no corner    33..93,  whole
  4x30    round trip      50..150, no corner     0..100, whole
```

The one case that still draws an incomplete frame is the 4-column desktop
itself, where a window cannot be whole: `minWinSize.x` is 16 and the desktop is
4, so the window is pinned to column 0 and clipped, which is the best available.

We also ran it against our port's own suite — 51 pty-driven test programs,
sixteen of which are full Turbo Vision applications started on a 24x8 terminal,
resized to 100x30, back down and up again, asserting the active window's frame
is whole each time:

```
  library fix   our workaround   result
      no             no          FAILS -- 6 checks, in calc, calendar and dir
      no             yes         passes   (what we ship today)
      yes            no          passes -- all 51 suites
      yes            yes         passes -- all 51 suites
```

The first row is the control: with our own override removed the suite really
does detect this, so the third row is the fix carrying it alone rather than a
test that stopped looking.

### `TView::locate`

`TView::locate` (`tview.cpp:585`) clamps the size against `sizeLimits` in the
same shape and leaves the origin alone:

```cpp
    bounds.b.x = bounds.a.x + range(bounds.b.x - bounds.a.x, min.x, max.x);
    bounds.b.y = bounds.a.y + range(bounds.b.y - bounds.a.y, min.y, max.y);
```

We work around that one separately, in `zoom()`, because un-zooming restores a
rectangle recorded on a desktop that may since have got smaller. We have *not*
reduced it to a `tvdemo` reproduction the way we did the above, so treat it as
an observation about the code rather than a second reported bug — but it is the
same omission in the same place, and whatever `calcBounds` should do here
`locate` probably should too.

## What we did meanwhile

Our port (a Node binding around this library) overrides `calcBounds` on its own
window class and fits the result to the desktop, origin included. We wrote it as
a workaround in our subclass rather than a patch to the library because we would
rather the library decided what the right behaviour is — and with the patch
above in place we can drop it, which is the third row of the table:

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
