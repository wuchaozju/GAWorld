/* What a resident is thinking right now, as one short line for a speech bubble.
 *
 * A trace frame carries the resident's cognition for the tick: `plan` is the
 * labelled intention the model wrote ("目标：…；顾虑：…；打算：…"), `perception` is
 * a first-person read of the moment, `reflection` looks back at the last action.
 * The bubble wants the main thought, so the goal of the plan wins, then the
 * first sentence of the perception, then whatever else the frame has.
 *
 * Shared by CityMapView (bubbles on the map) and IndoorView (bubbles in the
 * floor plan). Exposes window.AgentThought; require()-able under Node for tests.
 */
(function (global) {
  "use strict";

  const PLAN_KEYS = ["目标", "打算", "goal", "plan", "intention"];
  const LABEL_RE = /^\s*([^：:；;]{1,12})[：:]\s*/;

  // "目标：A；顾虑：B" → { 目标: "A", 顾虑: "B" }. Unlabelled text → {}.
  function planSegments(text) {
    const out = {};
    String(text || "").split(/[；;\n]/).forEach((part) => {
      const m = part.match(LABEL_RE);
      if (!m) return;
      const value = part.slice(m[0].length).trim();
      if (value) out[m[1].trim().toLowerCase()] = value;
    });
    return out;
  }

  function firstSentence(text) {
    const s = String(text || "").trim();
    if (!s) return "";
    const m = s.match(/^[\s\S]*?(?:[。！？；;]|[.!?](?=\s|$))/);
    return (m ? m[0] : s).replace(/[。；;]$/, "").trim();
  }

  function clip(text, max) {
    const chars = Array.from(String(text || ""));
    return chars.length > max ? chars.slice(0, max - 1).join("") + "…" : chars.join("");
  }

  // The resident's main thought for this frame, clipped to `max` characters.
  function thoughtOf(agent, max) {
    if (!agent) return "";
    const limit = max || 60;
    const segs = planSegments(agent.plan);
    for (const key of PLAN_KEYS) if (segs[key]) return clip(segs[key], limit);
    const plain = String(agent.plan || "").trim();
    if (plain && !Object.keys(segs).length) return clip(firstSentence(plain), limit);
    for (const field of ["perception", "thought", "reflection", "action", "activity"]) {
      const s = firstSentence(agent[field]);
      if (s) return clip(s, limit);
    }
    return "";
  }

  const api = { planSegments, firstSentence, clip, thoughtOf };
  global.AgentThought = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
