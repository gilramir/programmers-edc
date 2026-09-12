# Upstream report: un-zooming after a terminal resize puts the window outside the desktop

*To file at <https://github.com/magiblot/tvision/issues>. Delete this file once
it has an issue number. The `calcBounds` report that used to sit beside it went
that way when it became
[#235](https://github.com/magiblot/tvision/issues/235) — the issue is the
report, and a copy of it here only rots. The reasoning behind it lives in
FINDINGS, under "The rectangle a window remembers is about a desktop that is
gone".*

---

**Title:** `TWindow::zoom` restores `zoomRect` without checking it against the desktop it is restoring onto

---

Un-zooming a window after the terminal has shrunk puts it outside the desktop — often entirely off the screen.

`TWindow::zoom` records the window's bounds in `zoomRect` when it maximizes and restores them verbatim when it un-maximizes. If the terminal changed size in between, that rectangle describes a desktop that no longer exists, and nothing reconciles the two.

### Reproducing it in tvdemo

`tvdemo` opens a `TFileWindow` for any file named on its command line, and that window is one of the few in the demo that keeps `TWindow`'s default `growMode`:

```
$ cd examples/tvdemo && <builddir>/tvdemo fileview.cpp   # from its own source dir, for demohelp.h32
```

on a 100x30 terminal, then:

1. `Ctrl-F5`, shrink the window to about 40x18 with `Shift-Left`/`Shift-Up`, move it right until it is flush against the right-hand edge, `Enter`. It is now at columns 60..100 — an ordinary place to put a window.
2. `F5` to zoom it. `zoomRect` is now `(60, 4, 100, 22)`.
3. Resize the terminal to 60 columns. The window is maximized, so it follows the desktop down to columns 0..60. Everything is still correct here.
4. `F5` to un-zoom.

The window is gone. Not clipped — gone:

```
  ≡  File  Windows  Options                        08:14:01
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
 F1 Help  Alt-X Exit                                 390576
```

It is restored to columns 60..100 of a desktop that is 60 wide, so there is no overlap at all. The window is still alive and still the active one — the Windows menu is fully populated, and `Ctrl-F5` followed by holding `Left` walks it back into view — but there is nothing on the screen and nothing a mouse can reach.

Same run at four terminal widths:

| terminal | while zoomed | restored to | desktop is |
|---|---|---|---|
| 80x20 | 0..80 | 60..100 | 0..80 |
| 60x20 | 0..60 | 60..100 | 0..60 |
| 50x20 | 0..50 | 60..100 | 0..50 |
| 40x20 | 0..40 | 60..100 | 0..40 |

At 80 columns half the window is off the right-hand side; at 60 and below it is entirely outside.

### Why

`TWindow::zoom` (`twindow.cpp:229`, on `master`):

```cpp
    else
        locate( zoomRect );
```

and `TView::locate` (`tview.cpp:585`):

```cpp
    bounds.b.x = bounds.a.x + range(bounds.b.x - bounds.a.x, min.x, max.x);
    bounds.b.y = bounds.a.y + range(bounds.b.y - bounds.a.y, min.y, max.y);
```

`locate` clamps the *size* against `sizeLimits` and takes the origin as given. In the run above the stored width is 40 and the maximum is 60, so nothing is clamped at all and the origin passes straight through.

### `locate` is not the place to fix it

Its other callers depend on that behaviour:

- `TView::moveGrow` has already clamped the origin itself — against `dragMode`'s limit bits rather than against the owner. The default `dragMode` is `dmLimitLoY` alone, so a window may deliberately be dragged off the left, the right and the bottom, and `moveGrow` only stops the origin at `limits.b - 1`.
- `TView::dragView`'s Esc path calls `locate(saveBounds)` to put the window back, and `saveBounds` may be one of those deliberately-overhanging rectangles.

A clamp inside `locate` would make both impossible. The stale rectangle belongs to `TWindow`, so the reconciliation does too.

### Suggested fix

Clamp the size the way `locate` will, then slide the origin back inside the owner; pin a window too large to fit at the owner's origin rather than dragging it negative.

```cpp
static inline int range( int val, int min, int max )
{
    return val < min ? min : val > max ? max : val;
}

static TRect fittedToOwner( const TRect& r, TPoint minSize, TPoint maxSize,
                            TPoint ownerSize )
{
    int w = range( r.b.x - r.a.x, minSize.x, maxSize.x );
    int h = range( r.b.y - r.a.y, minSize.y, maxSize.y );
    int x = range( r.a.x, 0, ownerSize.x - w < 0 ? 0 : ownerSize.x - w );
    int y = range( r.a.y, 0, ownerSize.y - h < 0 ? 0 : ownerSize.y - h );
    return TRect( x, y, x + w, y + h );
}

void TWindow::zoom()
{
    TPoint minSize, maxSize;
    sizeLimits( minSize, maxSize );
    if( size != maxSize )
        {
        zoomRect = getBounds();
        TRect r( 0, 0, maxSize.x, maxSize.y );
        locate(r);
        }
    else
        {
        TRect r = owner == 0 ? zoomRect
                             : fittedToOwner( zoomRect, minSize, maxSize,
                                              owner->size );
        locate( r );
        }
}
```

With that, the four runs above restore to 40..80, 20..60, 10..50 and 0..40: the same size the window was, still flush against the right-hand edge, on the screen.

### Relationship to #235

Same shape, different route. #235 is the terminal resize itself — `TView::calcBounds` scaling or shifting an origin it never checks. This one is a rectangle *remembered* across a resize. Fixing #235 does not fix this, and vice versa; I have them as separate commits.

(The closing note on my #235 patch guessed that `TView::locate` wanted the same treatment as `calcBounds`. Having looked at its callers, I no longer think so, for the reason above.)
