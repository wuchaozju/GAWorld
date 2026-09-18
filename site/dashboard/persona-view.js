(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.GAWorldPersonaView = api;
  }
}(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  /* Pure renderers for 真人蒸馏 — the "build a resident from a real person"
   * panel in Agent Studio.
   *
   * Split out of persona.js and kept free of the DOM so they can be tested
   * with plain `node site/dashboard/persona-view.test.js`, the same split
   * survey.js / survey-charts.js uses.
   *
   * Two rules run through everything here and are worth stating once:
   *
   * - **Provenance is not decoration.** A persona is a claim about a real
   *   person, so the confidence chip, the evidence count and the source links
   *   are rendered next to the claims rather than tucked into a details pane.
   *   An operator should not have to go looking to find out that a decisive-
   *   sounding profile came from two search snippets.
   * - **Nothing is invented at render time.** Missing fields print an explicit
   *   「资料不足」 instead of a plausible blank, because a blank reads as
   *   "nothing interesting here" and a gap in the sources is interesting.
   */

  const CONFIDENCE = {
    high: { cls: "ok", label: "证据充分" },
    medium: { cls: "warn", label: "证据一般" },
    low: { cls: "bad", label: "证据不足" },
  };

  const IDENTITY_ROWS = [
    ["job", "职业"],
    ["residence", "常住"],
    ["hukou", "户籍"],
    ["education_income", "教育与收入"],
    ["daily_life", "日常"],
    ["social_network", "社交"],
    ["values", "价值观"],
  ];

  function esc(text) {
    return String(text == null ? "" : text).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  /** i18n with an inline Chinese fallback, same contract as survey.js. */
  function t(key, fallback) {
    if (typeof globalThis.__ !== "function") return fallback;
    const value = globalThis.__("pd." + key);
    return value && value !== "pd." + key ? value : fallback;
  }

  function list(items, empty) {
    const rows = (items || []).filter(Boolean);
    if (!rows.length) return '<p class="pd-empty">' + esc(empty) + "</p>";
    return "<ul>" + rows.map(function (item) { return "<li>" + esc(item) + "</li>"; }).join("") + "</ul>";
  }

  function confidenceChip(persona) {
    const info = CONFIDENCE[(persona || {}).confidence] || CONFIDENCE.low;
    const label = t("conf_" + ((persona || {}).confidence || "low"), info.label);
    const items = (persona || {}).evidence_items || 0;
    const pages = (persona || {}).evidence_pages || 0;
    return (
      '<span class="pd-chip ' + info.cls + '">' + esc(label) + "</span>" +
      '<span class="pd-evidence">' +
      esc(t("evidence", "材料") + " " + items + " · " + t("full_text", "全文") + " " + pages) +
      "</span>"
    );
  }

  /** The distilled thinking framework — nuwa's Phase 2 output, as a card. */
  function frameworkCard(persona) {
    const p = persona || {};
    const models = (p.mental_models || []).map(function (m) {
      const limits = m.limits
        ? '<div class="pd-limit">' + esc(t("limits", "失效条件") + "：" + m.limits) + "</div>"
        : "";
      const evidence = (m.evidence || []).length
        ? '<div class="pd-evi">' + esc(t("basis", "依据") + "：" + m.evidence.join("；")) + "</div>"
        : '<div class="pd-evi pd-empty">' + esc(t("no_basis", "未给出依据")) + "</div>";
      return (
        '<li><b>' + esc(m.name) + "</b>" +
        (m.gist ? "：" + esc(m.gist) : "") + evidence + limits + "</li>"
      );
    }).join("");

    const heuristics = (p.heuristics || []).map(function (h) {
      const example = h.example ? '<span class="pd-eg">' + esc("例：" + h.example) + "</span>" : "";
      return "<li>" + esc(h.rule) + example + "</li>";
    }).join("");

    const voice = p.voice || {};
    const voiceBits = [
      voice.sentences && t("v_sentences", "句式") + "：" + voice.sentences,
      voice.vocabulary && t("v_vocabulary", "用词") + "：" + voice.vocabulary,
      voice.rhythm && t("v_rhythm", "节奏") + "：" + voice.rhythm,
      voice.humor && t("v_humor", "幽默") + "：" + voice.humor,
      voice.certainty && t("v_certainty", "确定性") + "：" + voice.certainty,
    ].filter(Boolean);

    return (
      '<div class="pd-card">' +
      "<h4>" + esc(t("models", "心智模型")) + "</h4>" +
      (models ? "<ul class='pd-models'>" + models + "</ul>"
              : '<p class="pd-empty">' + esc(t("no_models", "材料不足以支撑跨领域复现的心智模型。")) + "</p>") +
      "<h4>" + esc(t("heuristics", "决策启发式")) + "</h4>" +
      (heuristics ? "<ul>" + heuristics + "</ul>"
                  : '<p class="pd-empty">' + esc(t("no_heuristics", "未提炼出可复用的决策规则。")) + "</p>") +
      "<h4>" + esc(t("voice", "表达方式")) + "</h4>" +
      (voiceBits.length ? "<p>" + esc(voiceBits.join("；")) + "</p>"
                        : '<p class="pd-empty">' + esc(t("no_voice", "资料不足。")) + "</p>") +
      ((voice.phrases || []).length
        ? "<p>" + esc(t("phrases", "口头禅") + "：" + voice.phrases.join("、")) + "</p>" : "") +
      "<h4>" + esc(t("anti", "绝不会做")) + "</h4>" +
      list(p.anti_patterns, t("none", "（无）")) +
      "<h4>" + esc(t("boundaries", "画像边界")) + "</h4>" +
      list(p.boundaries, t("none", "（无）")) +
      "</div>"
    );
  }

  function identityCard(persona) {
    const p = persona || {};
    const rows = IDENTITY_ROWS.map(function (pair) {
      const value = p[pair[0]];
      const label = t("f_" + pair[0], pair[1]);
      const body = value
        ? esc(value)
        : '<span class="pd-empty">' + esc(t("unsourced", "资料不足")) + "</span>";
      return "<tr><th>" + esc(label) + "</th><td>" + body + "</td></tr>";
    }).join("");
    const basics = [p.gender, p.age ? p.age + t("years", "岁") : "", p.residence].filter(Boolean).join(" · ");
    return (
      '<div class="pd-card">' +
      "<h3>" + esc(p.name || t("unnamed", "（无名）")) + "</h3>" +
      '<p class="pd-basics">' + esc(basics) + "</p>" +
      (p.summary ? "<p>" + esc(p.summary) + "</p>" : "") +
      "<table class='pd-table'>" + rows + "</table>" +
      ((p.unknown_fields || []).length
        ? '<p class="pd-warn">' + esc(t("gaps", "以下字段资料不足，已留空") + "：" + p.unknown_fields.join("、")) + "</p>"
        : "") +
      "</div>"
    );
  }

  /** Source links. External, so they open in a new tab with rel=noopener. */
  function sourcesCard(persona) {
    const sources = ((persona || {}).sources || []).filter(function (s) { return s && s.url; });
    if (!sources.length) {
      return '<div class="pd-card"><h4>' + esc(t("sources", "资料来源")) + "</h4>" +
        '<p class="pd-empty">' + esc(t("no_sources", "没有记录到来源。")) + "</p></div>";
    }
    const rows = sources.map(function (s) {
      const label = s.title || s.url;
      const kind = s.kind === "page" ? t("full_text", "全文") : t("snippet", "摘要");
      return '<li><a href="' + esc(s.url) + '" target="_blank" rel="noopener noreferrer">' +
        esc(label) + '</a> <span class="pd-kind">' + esc(kind) + "</span></li>";
    }).join("");
    return '<div class="pd-card"><h4>' + esc(t("sources", "资料来源")) +
      "</h4><ul class='pd-sources'>" + rows + "</ul></div>";
  }

  function personaView(persona) {
    if (!persona) return "";
    return (
      '<div class="pd-head">' + confidenceChip(persona) + "</div>" +
      identityCard(persona) + frameworkCard(persona) + sourcesCard(persona)
    );
  }

  /** The archive list: personas distilled earlier, newest first. */
  function archiveList(rows) {
    if (!(rows || []).length) return '<p class="pd-empty">' + esc(t("no_archive", "还没有蒸馏过任何人。")) + "</p>";
    return "<ul class='pd-archive'>" + rows.map(function (row) {
      const info = CONFIDENCE[row.confidence] || CONFIDENCE.low;
      const deployed = row.agent_id != null
        ? '<span class="pd-kind">' + esc(t("deployed", "已落地") + " #" + row.agent_id) + "</span>"
        : "";
      return '<li><button type="button" class="pd-open" data-slug="' + esc(row.slug) + '">' +
        esc(row.name || row.slug) + "</button>" +
        '<span class="pd-chip ' + info.cls + '">' + esc(row.mental_models || 0) + " " +
        esc(t("models_short", "模型")) + "</span>" + deployed + "</li>";
    }).join("") + "</ul>";
  }

  /** Draft fields for Agent Studio's seven-step form. */
  function draftFromPersona(persona) {
    const p = persona || {};
    return {
      identity: {
        id: null,
        name: p.name || "",
        gender: p.gender || "未知",
        age: p.age || 40,
        hukou: p.hukou || "未知",
        residence: p.residence || "杭州",
      },
      state: Object.assign({}, p.state),
      narrative: { job: p.job || "", personality: p.personality || "" },
      slug: p.slug || "",
    };
  }

  return {
    CONFIDENCE,
    archiveList,
    confidenceChip,
    draftFromPersona,
    esc,
    frameworkCard,
    identityCard,
    personaView,
    sourcesCard,
  };
}));
