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
  listBox: ['items'],
  canvas: ['lines'],
};

function skeleton(view) {
  const copy = { ...view };
  for (const field of MUTABLE[view.type] || []) delete copy[field];
  return JSON.stringify(copy);
}

function sameShape(before, after) {
  if (!before) return false;
  if (JSON.stringify(before.rect) !== JSON.stringify(after.rect)) return false;
  if (before.items.length !== after.items.length) return false;
  return before.items.every((view, i) => skeleton(view) === skeleton(after.items[i]));
}

/**
 * @param tv        the binding, or anything with the same shape
 * @param onClosed  called with a window id the *user* closed, never one we did
 */
function createDiffer(tv, onClosed = () => {}) {
  let current = new Map(); // window id -> the spec we last applied

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
      case 'listBox':
        if (JSON.stringify(before.items) !== JSON.stringify(after.items)) {
          tv.setItems(after.id, after.items);
        }
        break;
      case 'canvas':
        if (JSON.stringify(before.lines) !== JSON.stringify(after.lines)) {
          tv.setLines(after.id, after.lines);
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

    /** Route a close notification: ours is swallowed, the user's is reported. */
    windowClosed(id) {
      if (selfClosed.delete(id)) return;
      onClosed(id);
    },
  };
}

module.exports = { createDiffer, skeleton, sameShape, MUTABLE };
