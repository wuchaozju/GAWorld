(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.GAWorldSurveyCharts = api;
  }
}(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  /* Pure renderers for the 群体采访 result view.
   *
   * Split out of survey.js and kept free of the DOM so they can be tested
   * with plain `node site/dashboard/survey-charts.test.js`. Everything here
   * is a string of SVG or HTML built from the API payload — the same
   * no-build, no-chart-library approach as analytics.js, which is what keeps
   * site/dashboard usable with no network.
   *
   * The palette is fixed and ordered, so "支持" is the same colour in the
   * overall chart and in every per-city chart beside it. A distribution whose
   * colours shift between two adjacent charts is actively misleading.
   */

  const PALETTE = [
    "#4c7ef3", "#e8663d", "#3fa66a", "#b676d6", "#d9a33a",
    "#43a8c0", "#d4577f", "#7a8798", "#8a6d3b", "#5c6bc0",
    "#26a69a", "#9c6b4e",
  ];

  const AXIS_LABELS = {
    city: "城市",
    age_band: "年龄段",
    gender: "性别",
    hukou: "户籍",
    district: "片区",
  };

  /* The default world carries the empty slug, which the demographics record
   * as "default" (a breakdown axis cannot have an empty key). The chart
   * should not make the reader decode that.
   *
   * Display strings live in a table the host page sets once, rather than as
   * constants here: the panel is bilingual, and a renderer that hardcodes
   * Chinese would print it into an English UI. Defaults keep the module
   * usable (and testable) with no host. */
  const DEFAULT_CITY_LABEL = "默认世界";

  const labels = {
    defaultCity: DEFAULT_CITY_LABEL,
    kinds: { open: "开放题", choice: "选择题", boolean: "是非题" },
    axes: Object.assign({}, AXIS_LABELS),
    round: "第 {n} 轮",
    noSummary: "（未生成摘要）",
    breakdownBy: "按{axis}拆分",
    people: "人",
    coverage: {
      answered: "有效回答 {n} 份",
      people: "代表 {n} 人",
      unparsed: "{n} 份未按题型作答，未计入统计",
      missing: "{n} 份缺失或出错",
    },
  };

  /** Merge host-supplied display strings over the defaults. */
  function setLabels(overrides) {
    const next = overrides || {};
    Object.keys(next).forEach(function (key) {
      const value = next[key];
      if (value && typeof value === "object" && !Array.isArray(value)) {
        labels[key] = Object.assign({}, labels[key], value);
      } else if (value != null && value !== "") {
        labels[key] = value;
      }
    });
  }

  function fill(template, params) {
    let text = String(template == null ? "" : template);
    Object.keys(params || {}).forEach(function (name) {
      text = text.split("{" + name + "}").join(String(params[name]));
    });
    return text;
  }

  function esc(text) {
    return String(text == null ? "" : text).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function groupLabel(axis, value) {
    const text = String(value == null ? "" : value);
    if (axis === "city" && (text === "" || text === "default")) return labels.defaultCity;
    return text;
  }

  function colorOf(index) {
    return PALETTE[index % PALETTE.length];
  }

  function pct(value) {
    return Math.round(Number(value || 0) * 100) + "%";
  }

  /* --------------------------------------------------------------- legend */

  function legend(buckets) {
    const items = (buckets || []).map(function (label, index) {
      return (
        '<span class="sv-key"><i style="background:' + colorOf(index) + '"></i>'
        + esc(label) + "</span>"
      );
    });
    return '<div class="sv-legend">' + items.join("") + "</div>";
  }

  /* ----------------------------------------------------------- bar chart */

  /** Horizontal bars, one per option, labelled with people and share.
   *
   * Uses `people` (population represented) for the bar length rather than
   * `respondents`: with cohorts in the sample the two differ by an order of
   * magnitude, and the population number is the one the question is about.
   */
  function optionBars(rows) {
    const list = (rows || []).filter(function (row) { return row; });
    if (!list.length) return "";
    const W = 360;
    const rowH = 30;
    const labelW = 96;
    const H = list.length * rowH + 8;
    const max = list.reduce(function (acc, row) {
      return Math.max(acc, Number(row.people || 0));
    }, 1);
    const bars = list.map(function (row, index) {
      const y = index * rowH + 4;
      const people = Number(row.people || 0);
      const width = max > 0 ? Math.max(people > 0 ? 2 : 0, (people / max) * (W - labelW - 60)) : 0;
      return (
        '<text class="sv-bar-label" x="' + (labelW - 6) + '" y="' + (y + 15)
        + '" text-anchor="end">' + esc(row.label) + "</text>"
        + '<rect x="' + labelW + '" y="' + (y + 4) + '" width="' + width.toFixed(1)
        + '" height="14" rx="3" fill="' + colorOf(index) + '"></rect>'
        + '<text class="sv-bar-value" x="' + (labelW + width + 6) + '" y="' + (y + 15) + '">'
        + people + " " + esc(labels.people) + " · " + pct(row.share) + "</text>"
      );
    });
    return (
      '<svg class="sv-chart" viewBox="0 0 ' + W + " " + H + '" role="img">'
      + bars.join("") + "</svg>"
    );
  }

  /* ------------------------------------------------------- grouped chart */

  /** One stacked 100% bar per demographic group — the distribution view.
   *
   * Normalised to each group's own answered total on purpose: the question
   * "do older residents answer differently from younger ones?" is about
   * proportions, and raw counts would let a large group's shape hide a small
   * group's disagreement entirely.
   */
  function breakdownBars(buckets, groups, axis) {
    const names = buckets || [];
    const list = (groups || []).filter(function (group) {
      return group && Number(group.answered_people || 0) > 0;
    });
    if (!names.length || !list.length) return "";
    const W = 360;
    const rowH = 34;
    const labelW = 96;
    const barW = W - labelW - 46;
    const H = list.length * rowH + 8;
    const rows = list.map(function (group, rowIndex) {
      const y = rowIndex * rowH + 4;
      const total = Number(group.answered_people || 0);
      const label = groupLabel(axis, group.value);
      let x = labelW;
      const segments = names.map(function (name, index) {
        const people = Number((group.people || {})[name] || 0);
        const width = total > 0 ? (people / total) * barW : 0;
        if (width <= 0) return "";
        const rect = (
          '<rect x="' + x.toFixed(1) + '" y="' + (y + 5) + '" width="' + width.toFixed(1)
          + '" height="16" fill="' + colorOf(index) + '">'
          + "<title>" + esc(label) + " · " + esc(name) + "：" + people + " " + esc(labels.people)
          + "</title></rect>"
        );
        x += width;
        return rect;
      });
      return (
        '<text class="sv-bar-label" x="' + (labelW - 6) + '" y="' + (y + 18)
        + '" text-anchor="end">' + esc(label) + "</text>"
        + segments.join("")
        + '<text class="sv-bar-value" x="' + (labelW + barW + 6) + '" y="' + (y + 18) + '">'
        + total + " " + esc(labels.people) + "</text>"
      );
    });
    return (
      '<svg class="sv-chart" viewBox="0 0 ' + W + " " + H + '" role="img">'
      + rows.join("") + "</svg>"
    );
  }

  /* ------------------------------------------------------------ coverage */

  /** The denominator, stated. Never render a share without it. */
  function coverageNote(stats) {
    const s = stats || {};
    const parts = [esc(fill(labels.coverage.answered, { n: Number(s.answered || 0) }))];
    if (Number(s.answered_people || 0)) {
      parts.push(esc(fill(labels.coverage.people, { n: s.answered_people })));
    }
    if (Number(s.unparsed || 0)) {
      parts.push(
        '<b class="sv-warn">' + esc(fill(labels.coverage.unparsed, { n: s.unparsed })) + "</b>"
      );
    }
    if (Number(s.missing || 0)) {
      parts.push(esc(fill(labels.coverage.missing, { n: s.missing })));
    }
    return '<p class="sv-coverage">' + parts.join("；") + "。</p>";
  }

  /* -------------------------------------------------------- one question */

  function bucketsOf(entry) {
    return ((entry && entry.stats && entry.stats.rows) || []).map(function (row) {
      return row.label;
    });
  }

  /** Full analysis block for one question: summary, tally, cross-tabs. */
  function questionBlock(entry, index) {
    if (!entry || !entry.question) return "";
    const question = entry.question;
    const stats = entry.stats || {};
    const buckets = bucketsOf(entry);
    const kind = labels.kinds[question.kind] || question.kind;
    const round = fill(labels.round, { n: Number(question.round || 1) });
    const out = [
      '<article class="sv-result">',
      '<header class="sv-result-head">',
      '<h4>Q' + index + ". " + esc(question.text) + "</h4>",
      '<span class="sv-tag">' + esc(kind) + " · " + esc(round) + "</span>",
      "</header>",
    ];
    if (entry.summary) {
      out.push('<p class="sv-summary">' + esc(entry.summary) + "</p>");
    } else {
      out.push('<p class="sv-summary is-empty">' + esc(labels.noSummary) + "</p>");
    }
    if (buckets.length) {
      out.push(legend(buckets));
      out.push(optionBars(stats.rows));
    }
    out.push(coverageNote(stats));

    const breakdown = entry.breakdown || {};
    const axes = Object.keys(breakdown);
    if (buckets.length && axes.length) {
      out.push('<div class="sv-breakdowns">');
      axes.forEach(function (axis) {
        const chart = breakdownBars(buckets, breakdown[axis], axis);
        if (!chart) return;
        const heading = fill(labels.breakdownBy, { axis: labels.axes[axis] || axis });
        out.push(
          '<section class="sv-breakdown"><h5>' + esc(heading) + "</h5>" + chart + "</section>"
        );
      });
      out.push("</div>");
    }
    out.push("</article>");
    return out.join("");
  }

  /* ----------------------------------------------------------- cost note */

  /** What a round will cost, before it is spent. */
  function costSummary(respondents, questions) {
    const people = (respondents || []).reduce(function (acc, item) {
      return acc + Number(item.size || 1);
    }, 0);
    const cohorts = (respondents || []).filter(function (item) {
      return item.kind === "cohort";
    }).length;
    const calls = (respondents || []).length * (questions || []).length;
    return {
      respondents: (respondents || []).length,
      individuals: (respondents || []).length - cohorts,
      cohorts: cohorts,
      people: people,
      questions: (questions || []).length,
      calls: calls,
    };
  }

  return {
    AXIS_LABELS,
    DEFAULT_CITY_LABEL,
    PALETTE,
    breakdownBars,
    groupLabel,
    bucketsOf,
    colorOf,
    costSummary,
    coverageNote,
    esc,
    fill,
    legend,
    optionBars,
    pct,
    questionBlock,
    setLabels,
  };
}));
