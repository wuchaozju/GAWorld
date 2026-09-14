/**
 * GAWorld help tooltips — self-contained "?" explanations.
 *
 * Drop-in: include this script on any page. Mark up a trigger with
 *   <span class="help-tip" data-help="说明文本"></span>
 * (the "?" glyph is filled in automatically), or add data-help to any
 * existing element to turn it into a trigger. Injects its own styles so
 * no extra stylesheet is required. Reusable across dashboard / studio /
 * simulation pages.
 *
 * Accessibility notes, because this is the console's primary in-context
 * documentation and it has to actually reach people:
 *
 *  - Tap opens it. Hover alone stranded every touch user, since a tap on a
 *    tabindex'd <span> does not reliably focus on iOS. Hover is now mouse-only
 *    (pointerType filter) so a tap cannot show-then-immediately-toggle-shut.
 *  - The accessible name is a short "Help", and the explanation is exposed via
 *    aria-describedby to a visually-hidden copy next to the trigger. A whole
 *    paragraph as an accessible name is unusable, and tying the text to the
 *    hover state would hide it from anyone not hovering.
 *  - aria-expanded is real: Enter/Space toggle, so the button role is honest.
 *  - Escape, outside click and scroll dismiss.
 *  - The focus ring is a ring, not a colour swap on a 1px border.
 *  - The visual dot stays 16px; an inset ::after pseudo-element takes the hit
 *    area to 24x24 without disturbing any layout it sits in.
 */
(function () {
  "use strict";
  if (window.__helpTipInit) return;
  window.__helpTipInit = true;

  var CSS = [
    ".help-tip{position:relative;display:inline-flex;align-items:center;justify-content:center;",
    "width:16px;height:16px;margin-left:5px;border-radius:50%;",
    "border:1px solid #9aa8a0;color:#7c8a82;background:#fff;",
    "font-size:11px;font-weight:800;line-height:1;cursor:help;opacity:.85;",
    "vertical-align:middle;user-select:none;flex:0 0 auto;",
    "transition:border-color .15s ease,color .15s ease,opacity .15s ease;}",
    /* 16px dot, 24x24 target: the pseudo-element is out of flow, so nothing moves. */
    ".help-tip::after{content:'';position:absolute;inset:-4px;border-radius:50%;}",
    ".help-tip:hover{opacity:1;border-color:#0e7a58;color:#0e7a58;}",
    ".help-tip[aria-expanded='true']{opacity:1;border-color:#0e7a58;color:#0e7a58;}",
    ".help-tip:focus-visible{outline:2px solid #0e7a58;outline-offset:2px;opacity:1;}",
    ".help-sr{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;",
    "clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap;border:0;}",
    ".help-pop{position:fixed;z-index:2000;max-width:288px;padding:9px 12px;",
    "border-radius:10px;background:#17251f;color:#eaf7f0;font-size:12.5px;",
    "line-height:1.6;font-weight:500;box-shadow:0 12px 34px rgba(10,30,22,.32);",
    "opacity:0;transform:translateY(4px);transition:opacity .14s ease,transform .14s ease;",
    "pointer-events:none;white-space:normal;}",
    ".help-pop.show{opacity:1;transform:translateY(0);}",
    "@media (prefers-reduced-motion: reduce){",
    ".help-tip,.help-pop{transition:none;}",
    ".help-pop{transform:none;}}"
  ].join("");

  var style = document.createElement("style");
  style.textContent = CSS;
  (document.head || document.documentElement).appendChild(style);

  var pop = null;
  var openTrigger = null;
  var seq = 0;

  function label() {
    // window.__ returns the key itself when a locale has no entry for it, and
    // this script also loads on pages that predate i18n.js. Both locales do
    // define help.label, so the fallback is only ever a last resort.
    var t = typeof window.__ === "function" ? window.__("help.label") : "";
    return !t || t === "help.label" ? "Help" : t;
  }

  function ensurePop() {
    if (!pop) {
      pop = document.createElement("div");
      pop.className = "help-pop";
      // Purely visual: the text reaches assistive tech through the
      // aria-describedby target instead, so this must not be announced twice.
      pop.setAttribute("aria-hidden", "true");
      document.body.appendChild(pop);
    }
    return pop;
  }

  function position(el, p) {
    var r = el.getBoundingClientRect();
    p.style.left = "0px";
    p.style.top = "0px";
    var pr = p.getBoundingClientRect();
    var left = r.left + r.width / 2 - pr.width / 2;
    var top = r.bottom + 8;
    if (top + pr.height > window.innerHeight - 8) top = r.top - pr.height - 8;
    left = Math.max(8, Math.min(left, window.innerWidth - pr.width - 8));
    p.style.left = Math.round(left) + "px";
    p.style.top = Math.round(top) + "px";
  }

  function show(el) {
    var text = el.getAttribute("data-help");
    if (!text) return;
    if (openTrigger && openTrigger !== el) openTrigger.setAttribute("aria-expanded", "false");
    var p = ensurePop();
    p.textContent = text;
    p.classList.add("show");
    position(el, p);
    el.setAttribute("aria-expanded", "true");
    openTrigger = el;
  }

  function hide() {
    if (pop) pop.classList.remove("show");
    if (openTrigger) openTrigger.setAttribute("aria-expanded", "false");
    openTrigger = null;
  }

  function toggle(el) {
    if (openTrigger === el) hide();
    else show(el);
  }

  /** Keep the hidden description (and the short label) in step with the locale. */
  function syncText(el) {
    var describer = el.__helpSr;
    if (describer) describer.textContent = el.getAttribute("data-help") || "";
    el.setAttribute("aria-label", label());
  }

  function wire(el) {
    if (el.__helpWired) return;
    el.__helpWired = true;

    if (el.classList.contains("help-tip") && !el.textContent.trim()) el.textContent = "?";
    if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
    if (!el.hasAttribute("role")) el.setAttribute("role", "button");
    el.setAttribute("aria-expanded", "false");

    // The explanation lives in a hidden sibling rather than in aria-label, so
    // the button keeps a short name and the text is available whether or not
    // the tooltip happens to be open.
    var sr = document.createElement("span");
    sr.className = "help-sr";
    sr.id = "help-sr-" + (++seq);
    sr.textContent = el.getAttribute("data-help") || "";
    if (el.parentNode) el.parentNode.insertBefore(sr, el.nextSibling);
    el.__helpSr = sr;
    el.setAttribute("aria-describedby", sr.id);
    el.setAttribute("aria-label", label());

    // Hover is a mouse affordance only. On touch, the tap fires click below;
    // letting a synthesised pointerenter also run would open then close it.
    el.addEventListener("pointerenter", function (e) {
      if (e.pointerType === "mouse") show(el);
    });
    el.addEventListener("pointerleave", function (e) {
      if (e.pointerType === "mouse" && openTrigger === el) hide();
    });

    // Tap / click / Enter / Space — the button role now does something.
    el.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      toggle(el);
    });
    el.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
        e.preventDefault();
        toggle(el);
      } else if (e.key === "Escape" && openTrigger === el) {
        hide();
      }
    });

    el.addEventListener("focus", function () { show(el); });
    el.addEventListener("blur", function () { if (openTrigger === el) hide(); });
  }

  function scan(root) {
    (root || document).querySelectorAll("[data-help]").forEach(wire);
  }

  window.addEventListener("scroll", hide, true);
  window.addEventListener("resize", hide);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") hide();
  });
  document.addEventListener("click", function (e) {
    if (openTrigger && !(e.target.closest && e.target.closest("[data-help]"))) hide();
  });
  // data-help is rewritten by i18n.applyTranslations(); mirror it across.
  document.addEventListener("locale-changed", function () {
    document.querySelectorAll("[data-help]").forEach(function (el) {
      if (el.__helpWired) syncText(el);
    });
  });

  window.HelpTips = { scan: scan };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { scan(); });
  } else {
    scan();
  }
})();
