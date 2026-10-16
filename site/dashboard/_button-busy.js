/**
 * GAWorld button busy-state utility.
 *
 * One flip-signal that:
 *   - sets `disabled` so the same click cannot fire twice
 *   - swaps the visible label to a "busy" copy (e.g. "运行" → "运行中…")
 *   - restores both when the caller signals done (even if it errors)
 *   - survives locale switches: stores the original data-i18n key, not the
 *     translated text, so applyTranslations() can re-render it later
 *   - survives re-entrancy: a second busy() call while the button is already
 *     busy is a no-op, so a long-running flow can nest setButtonBusy(btn, true)
 *     inside itself without losing the original label
 *
 * Usage:
 *   const release = setButtonBusy(btn, "btn.busy_key", "运行中…");
 *   try { ... await ... } finally { release(); }
 *
 * Or, fire-and-forget with an async thunk:
 *   await withButtonBusy(btn, "btn.busy_key", "运行中…", async () => { ... });
 */
(function () {
  "use strict";

  const ORIGINAL_KEY = "_busyOrigI18n";
  const ORIGINAL_TEXT = "_busyOrigText";
  const COUNTER = "_busyDepth";

  function t(key, fallback) {
    if (typeof window.__ === "function") {
      const v = window.__(key, undefined);
      if (v !== undefined && v !== key) return v;
      if (fallback !== undefined) return fallback;
      return key;
    }
    return fallback !== undefined ? fallback : key;
  }

  function currentLabel(btn) {
    // Prefer the saved text snapshot so a second busy() can re-apply the
    // same label even after a locale switch happened in between.
    if (btn.dataset[ORIGINAL_TEXT] !== undefined) return btn.dataset[ORIGINAL_TEXT];
    if (btn.dataset && btn.dataset.i18n) return t(btn.dataset.i18n, btn.textContent);
    return btn.textContent;
  }

  /**
   * Mark a button as busy. Returns a `release` function that must be called
   * once the work is done (or has failed) to restore the button.
   */
  function setButtonBusy(btn, busyKey, busyFallback) {
    if (!btn) return function noopRelease() {};
    // First busy() call snapshots the resting label so we can restore it
    // after the *last* release, even if the locale changed mid-flight.
    if (btn.dataset[COUNTER] === undefined) {
      btn.dataset[COUNTER] = "0";
      // Prefer the i18n key over the rendered text so locale switches
      // rerender the resting label correctly.
      const i18nKey = btn.getAttribute("data-i18n") || "";
      if (i18nKey) {
        btn.dataset[ORIGINAL_KEY] = i18nKey;
      } else {
        btn.dataset[ORIGINAL_TEXT] = btn.textContent;
      }
      // Also snapshot the resting disabled state so release restores it
      // verbatim (some buttons start disabled by design, e.g. ride-along
      // buttons gated by an agent being chosen).
      btn.dataset._busyOrigDisabled = btn.disabled ? "1" : "0";
    }
    const depth = parseInt(btn.dataset[COUNTER], 10) || 0;
    btn.dataset[COUNTER] = String(depth + 1);
    btn.disabled = true;
    btn.classList.add("is-busy");
    btn.setAttribute("aria-busy", "true");
    if (busyKey || busyFallback) {
      btn.textContent = t(busyKey || "", busyFallback);
    }
    let released = false;
    return function release() {
      if (released) return;
      released = true;
      const d = parseInt(btn.dataset[COUNTER], 10) || 1;
      const next = d - 1;
      if (next > 0) {
        // Still busy in an outer caller; just decrement and leave label alone.
        btn.dataset[COUNTER] = String(next);
        return;
      }
      btn.dataset[COUNTER] = "0";
      btn.classList.remove("is-busy");
      btn.removeAttribute("aria-busy");
      // Restore resting label.
      const origKey = btn.dataset[ORIGINAL_KEY];
      if (origKey) {
        btn.textContent = t(origKey, btn.dataset[ORIGINAL_TEXT] || "");
      } else if (btn.dataset[ORIGINAL_TEXT] !== undefined) {
        btn.textContent = btn.dataset[ORIGINAL_TEXT];
      }
      // Restore resting disabled (default: enabled).
      btn.disabled = btn.dataset._busyOrigDisabled === "1";
      delete btn.dataset._busyOrigDisabled;
      delete btn.dataset[ORIGINAL_TEXT];
      delete btn.dataset[ORIGINAL_KEY];
    };
  }

  /**
   * Run an async thunk with the button in busy state. The button is restored
   * even when the thunk throws. Returns whatever the thunk returns.
   */
  async function withButtonBusy(btn, busyKey, busyFallback, thunk) {
    const release = setButtonBusy(btn, busyKey, busyFallback);
    try {
      return await thunk();
    } finally {
      release();
    }
  }

  window.setButtonBusy = setButtonBusy;
  window.withButtonBusy = withButtonBusy;
})();