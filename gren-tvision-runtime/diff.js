'use strict';

// Turning one UI description into calls on the binding.
//
// Everything stateful about rendering lives here, and it takes the binding as
// an argument so it can be tested against a fake one. That matters more than it
// sounds: every bug this layer has had -- a window rebuilt because its title
// changed, a self-inflicted close reported as the user's, an input line
// overwritten while someone was typing in it -- is a pure-logic bug that a fake
// binding catches in milliseconds and a terminal catches by accident.

// Fields a view can change without being rebuilt. Everything else -- the id,
// the rectangle, a button's command -- is structural: change one and the
// window is torn down and made again. A window's *title* is not structural
// either; it is patched with setTitle.
const MUTABLE = {
  staticText: ['text'],
  inputLine: ['value'],
  history: ['items'],
  listBox: ['items', 'focused'],
  canvas: ['lines', 'cursorAt'],
  checkBoxes: ['value'],
  multiCheckBoxes: ['value'],
  radioButtons: ['value'],
  scrollBar: ['value', 'min', 'max', 'pageStep', 'arrowStep'],
};

function skeleton(view) {
  const copy = { ...view };
  for (const field of MUTABLE[view.type] || []) delete copy[field];
  return JSON.stringify(copy);
}

// A window's *rectangle* is not structural, for the same reason its title is
// not: there is a call that changes it in place. It used to be, and rebuilding
// a window to move it threw away the caret, the scroll position and the list
// highlight -- and skipped TGroup::changeBounds, which is the only thing that
// resolves a child view's growMode. A view's own rect is still structural:
// nothing can move one of those but a rebuild.
function sameShape(before, after) {
  if (!before) return false;
  if (before.items.length !== after.items.length) return false;
  return before.items.every((view, i) => skeleton(view) === skeleton(after.items[i]));
}

/**
 * @param tv        the binding, or anything with the same shape
 * @param onClosed  called with a window id the *user* closed, never one we did
 */
function createDiffer(tv, onClosed = () => {}) {
  let current = new Map(); // window id -> the spec we last applied
  let chrome = null;       // the menu bar and status line we last applied
  let overlays = null;     // the views on the application we last applied

  // tv.close() destroys the window, which notifies onClose -- but not until the
  // pump reaches a safe point, so the notification arrives *after* the call
  // that caused it. A synchronous flag would already have been cleared; the ids
  // we closed ourselves have to be remembered until they come back.
  const selfClosed = new Set();

  // A render can arrive while we are in the middle of applying one: patching a
  // view can close a window, which notifies the program, which updates, which
  // renders. Take the newest and apply it after, rather than recursing.
  let applying = false;
  let pending = null;

  function patchView(before, after) {
    switch (after.type) {
      case 'staticText':
        // Compared against the *previous description*, never against what is
        // on screen. An input line the user has typed into disagrees with the
        // model by design; writing the model back on every render would eat
        // their keystrokes.
        if (before.text !== after.text) tv.setText(after.id, after.text);
        break;
      case 'inputLine':
        if (before.value !== after.value) tv.setValue(after.id, after.value);
        break;
      case 'history':
        // Nothing on screen changes: the drop-down reads the list when it
        // opens, and the arrow beside the field looks the same whatever is
        // behind it. Patching it rather than treating it as structural is
        // still what keeps a model that appends to its history from rebuilding
        // the window -- and so from closing the dialog the field is in.
        if (JSON.stringify(before.items) !== JSON.stringify(after.items)) {
          tv.setItems(after.id, after.items);
        }
        break;
      case 'listBox': {
        const rebuilt = JSON.stringify(before.items) !== JSON.stringify(after.items);
        if (rebuilt) tv.setItems(after.id, after.items);
        // After setItems, and *whenever* it ran -- not only when the model
        // moved the highlight. Rebuilding a list puts the highlight back on
        // row zero no matter where it was, so a `focused` that did not change
        // is still a `focused` the list no longer agrees with. Leaving it out
        // is how a tree collapses itself the moment you expand a branch: the
        // model says 1, the list says 0, and the list is the one that reports.
        if (rebuilt || before.focused !== after.focused) {
          tv.setValue(after.id, after.focused);
        }
        break;
      }
      case 'canvas':
        if (JSON.stringify(before.lines) !== JSON.stringify(after.lines)) {
          tv.setLines(after.id, after.lines);
        }
        if (JSON.stringify(before.cursorAt) !== JSON.stringify(after.cursorAt)) {
          // null means no cursor. TVision has no "hide" that keeps a position,
          // so hiding takes one anyway and the position is discarded.
          if (after.cursorAt) tv.setCursor(after.id, after.cursorAt[0], after.cursorAt[1], true);
          else tv.setCursor(after.id, 0, 0, false);
        }
        break;
      case 'checkBoxes':
        // A cluster holds state the model cannot see -- a box the user ticks
        // is reported only when a dialog is answered -- so the same rule as an
        // input line applies, and for the same reason: write it back only when
        // the *model* changed it, never merely because it disagrees with the
        // screen.
        if (JSON.stringify(before.value) !== JSON.stringify(after.value)) {
          tv.setValue(after.id, after.value);
        }
        break;
      case 'multiCheckBoxes':
        // Same rule as a cluster of two-state boxes: written back only when
        // the *model* changed it, never merely because it disagrees with the
        // screen.
        if (JSON.stringify(before.value) !== JSON.stringify(after.value)) {
          tv.setValue(after.id, after.value);
        }
        break;
      case 'radioButtons':
        if (before.value !== after.value) tv.setValue(after.id, after.value);
        break;
      case 'scrollBar':
        // The range and the value go together or not at all: TScrollBar clamps
        // one against the other, so setting them one at a time can land the
        // thumb somewhere neither side asked for.
        if (
          before.min !== after.min ||
          before.max !== after.max ||
          before.pageStep !== after.pageStep ||
          before.arrowStep !== after.arrowStep
        ) {
          tv.setScroll(after.id, after.value, after.min, after.max, after.pageStep, after.arrowStep);
        } else if (before.value !== after.value) {
          tv.setValue(after.id, after.value);
        }
        break;
      default:
        break;
    }
  }

  function closeWindow(id) {
    selfClosed.add(id);
    tv.close(id);
  }

  return {
    /** Apply a render message's windows. */
    apply(windows) {
      if (applying) {
        pending = windows;
        return;
      }
      applying = true;

      try {
        do {
          const next = new Map(windows.map((w) => [w.id, w]));

          for (const id of current.keys()) {
            if (!next.has(id) && tv.exists(id)) closeWindow(id);
          }

          for (const window of windows) {
            // tv.exists() rather than our own bookkeeping: the user may have
            // closed this window from its frame since the last render.
            if (!tv.exists(window.id)) {
              tv.window(window);
            } else if (!sameShape(current.get(window.id), window)) {
              closeWindow(window.id);
              tv.window(window);
            } else {
              const before = current.get(window.id);
              if (before.title !== window.title) tv.setTitle(window.id, window.title);
              // Before the contents, so that a view which grew with the window
              // is written at the size it has now.
              if (JSON.stringify(before.rect) !== JSON.stringify(window.rect)) {
                tv.setBounds(window.id, window.rect);
              }
              window.items.forEach((view, i) => patchView(before.items[i], view));
            }
          }

          current = next;
          windows = pending;
          pending = null;
        } while (windows);
      } finally {
        applying = false;
      }
    },

    /**
     * The user changed a view's value, so the description we are diffing
     * against is out of date -- record what the view says now.
     *
     * Without this, a model that keeps the value it was told (which is the
     * point of being told) renders it straight back, the differ compares it
     * against the value it last *applied*, sees a difference, and writes it
     * into the view. For an input line that is not merely wasteful: setValue
     * ends in selectAll(), so the field the user is typing in becomes a
     * selected block and their next keystroke replaces the lot.
     *
     * This is the controlled-input problem every virtual DOM has, and the same
     * answer: the last thing the *view* reported is what the next render is
     * compared against.
     */
    valueChanged(id, value) {
      for (const window of current.values()) {
        for (const view of window.items) {
          if (view.id === id) {
            view.value = value;
            return;
          }
        }
      }
    },

    /**
     * Apply the menu bar and status line, which are part of the view like
     * anything else -- Turbo Vision lets both be swapped after startup. Sent
     * whole rather than diffed entry by entry: they are small, and rebuilding
     * one has no state to lose.
     *
     * Returns false the first time, when the caller still has to build the
     * application out of them.
     */
    chrome(menuBar, statusLine) {
      const next = JSON.stringify([menuBar, statusLine]);
      if (chrome === null) {
        chrome = next;
        return false;
      }
      if (chrome === next) return true;

      const [beforeMenu, beforeStatus] = JSON.parse(chrome);
      if (JSON.stringify(beforeMenu) !== JSON.stringify(menuBar)) tv.setMenuBar(menuBar);
      if (JSON.stringify(beforeStatus) !== JSON.stringify(statusLine)) {
        tv.setStatusLine(statusLine);
      }
      chrome = next;
      return true;
    },

    /**
     * Apply the views that sit on the *application* rather than on the
     * desktop -- a clock in the corner, tvdemo's heap gauge.
     *
     * Rebuilt whole when the shape changes and patched by id when it does
     * not, which is the same rule a window follows and matters for the same
     * reason: a clock renders once a second, and rebuilding the set every
     * second would repaint the corner of the screen forever.
     */
    overlay(items) {
      items = items || [];
      if (overlays !== null && sameShape({ items: overlays }, { items })) {
        items.forEach((view, i) => patchView(overlays[i], view));
        overlays = items;
        return;
      }
      tv.overlays(items);
      overlays = items;
    },

    /** Route a close notification: ours is swallowed, the user's is reported. */
    windowClosed(id) {
      if (selfClosed.delete(id)) return;
      onClosed(id);
    },
  };
}

module.exports = { createDiffer, skeleton, sameShape, MUTABLE };
