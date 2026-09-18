/* Unit tests for the 群体采访 renderers.
 *
 *   node site/dashboard/survey-charts.test.js
 *
 * Mirrors the collaboration-core.test.js / analytics-export.test.js
 * convention: plain node, no framework, no browser. Worth having because the
 * Python tests cover the endpoints and cannot see a chart at all — a
 * swapped-colour legend or a share rendered without its denominator would
 * leave every backend test green.
 */
"use strict";

const assert = require("assert");
const charts = require("./survey-charts.js");

let passed = 0;

function test(name, fn) {
  try {
    fn();
    passed += 1;
  } catch (err) {
    console.error("FAIL: " + name);
    console.error(err && err.message ? err.message : err);
    process.exit(1);
  }
}

/* ------------------------------------------------------------------ escaping */

test("esc neutralises html", function () {
  assert.strictEqual(charts.esc('<b>"x"&y</b>'), "&lt;b&gt;&quot;x&quot;&amp;y&lt;/b&gt;");
});

test("option labels containing markup are escaped in the bars", function () {
  const svg = charts.optionBars([{ label: "<script>", people: 3, share: 1, respondents: 3 }]);
  assert.ok(svg.indexOf("<script>") === -1, "raw markup must not reach the SVG");
  assert.ok(svg.indexOf("&lt;script&gt;") >= 0);
});

/* -------------------------------------------------------------------- colour */

test("a bucket keeps the same colour across the overall and per-group charts", function () {
  // The whole point of a fixed, index-ordered palette: "支持" must be the
  // same colour in every chart on the page or the comparison misleads.
  const buckets = ["支持", "不支持"];
  const overall = charts.optionBars([
    { label: "支持", people: 5, share: 0.5, respondents: 5 },
    { label: "不支持", people: 5, share: 0.5, respondents: 5 },
  ]);
  const grouped = charts.breakdownBars(buckets, [
    { value: "甲", counts: { 支持: 3, 不支持: 1 }, people: { 支持: 3, 不支持: 1 }, answered: 4, answered_people: 4 },
  ]);
  const first = charts.colorOf(0);
  assert.ok(overall.indexOf(first) >= 0);
  assert.ok(grouped.indexOf(first) >= 0);
});

test("palette wraps rather than running out of colours", function () {
  assert.strictEqual(charts.colorOf(0), charts.colorOf(charts.PALETTE.length));
});

/* ------------------------------------------------------------------ bar chart */

test("bars are sized by people represented, not by respondent count", function () {
  // A cohort of 40 and an individual are one respondent each; the bar must
  // reflect the 40.
  const svg = charts.optionBars([
    { label: "多", people: 40, share: 0.98, respondents: 1 },
    { label: "少", people: 1, share: 0.02, respondents: 1 },
  ]);
  const widths = [];
  svg.replace(/width="([\d.]+)"/g, function (_, value) {
    widths.push(Number(value));
    return "";
  });
  assert.ok(widths[0] > widths[1] * 5, "the 40-person bar must dominate");
});

test("bars report both the count and the share", function () {
  const svg = charts.optionBars([{ label: "支持", people: 11, share: 11 / 12, respondents: 2 }]);
  assert.ok(svg.indexOf("11 人") >= 0);
  assert.ok(svg.indexOf("92%") >= 0);
});

test("a zero bucket renders no bar but keeps its label", function () {
  const svg = charts.optionBars([
    { label: "有人选", people: 4, share: 1, respondents: 4 },
    { label: "没人选", people: 0, share: 0, respondents: 0 },
  ]);
  assert.ok(svg.indexOf("没人选") >= 0);
  assert.ok(svg.indexOf('width="0.0"') >= 0 || svg.indexOf('width="0"') >= 0);
});

test("no rows means no chart rather than an empty axis", function () {
  assert.strictEqual(charts.optionBars([]), "");
  assert.strictEqual(charts.optionBars(null), "");
});

/* ------------------------------------------------------------- breakdown bars */

test("each group is normalised to its own answered total", function () {
  // A small group that disagrees must be as visible as a large one that
  // agrees — raw counts would hide it.
  const svg = charts.breakdownBars(["支持", "不支持"], [
    { value: "大组", counts: {}, people: { 支持: 90, 不支持: 10 }, answered: 100, answered_people: 100 },
    { value: "小组", counts: {}, people: { 支持: 1, 不支持: 9 }, answered: 10, answered_people: 10 },
  ]);
  const widths = [];
  svg.replace(/<rect[^>]*width="([\d.]+)"/g, function (_, value) {
    widths.push(Number(value));
    return "";
  });
  // Segment 1 of 大组 (90%) and segment 2 of 小组 (90%) must be equal width.
  assert.ok(Math.abs(widths[0] - widths[3]) < 0.5, "both 90% segments must be the same width");
});

test("groups with no answers are dropped, not drawn as empty bars", function () {
  const svg = charts.breakdownBars(["支持"], [
    { value: "有回答", counts: {}, people: { 支持: 3 }, answered: 3, answered_people: 3 },
    { value: "没回答", counts: {}, people: {}, answered: 0, answered_people: 0 },
  ]);
  assert.ok(svg.indexOf("有回答") >= 0);
  assert.strictEqual(svg.indexOf("没回答"), -1);
});

test("every segment carries a hoverable title with its real count", function () {
  const svg = charts.breakdownBars(["支持"], [
    { value: "甲", counts: {}, people: { 支持: 7 }, answered: 7, answered_people: 7 },
  ]);
  assert.ok(svg.indexOf("<title>甲 · 支持：7 人</title>") >= 0);
});

test("the default world is labelled, not shown as its internal slug", function () {
  // The empty slug becomes "default" in the demographics because a breakdown
  // axis cannot have an empty key; the reader should never see that.
  assert.strictEqual(charts.groupLabel("city", "default"), charts.DEFAULT_CITY_LABEL);
  assert.strictEqual(charts.groupLabel("city", ""), charts.DEFAULT_CITY_LABEL);
  assert.strictEqual(charts.groupLabel("city", "绍兴柯桥"), "绍兴柯桥");
  // Only the city axis: a hukou or district literally named "default" stays.
  assert.strictEqual(charts.groupLabel("hukou", "default"), "default");
});

test("the city chart renders the default world's label in bars and tooltips", function () {
  const svg = charts.breakdownBars(
    ["支持"],
    [{ value: "default", counts: {}, people: { 支持: 4 }, answered: 4, answered_people: 4 }],
    "city"
  );
  assert.ok(svg.indexOf(charts.DEFAULT_CITY_LABEL) >= 0);
  assert.strictEqual(svg.indexOf(">default<"), -1);
});

/* ---------------------------------------------------------------- coverage */

test("coverage always states the denominator", function () {
  const html = charts.coverageNote({ answered: 12, answered_people: 40 });
  assert.ok(html.indexOf("有效回答 12 份") >= 0);
  assert.ok(html.indexOf("代表 40 人") >= 0);
});

test("unparsed answers are called out, not hidden", function () {
  const html = charts.coverageNote({ answered: 8, answered_people: 8, unparsed: 4 });
  assert.ok(html.indexOf("4 份未按题型作答") >= 0);
  assert.ok(html.indexOf("sv-warn") >= 0, "the shortfall must be visually flagged");
});

test("missing and unparsed are reported as different things", function () {
  const html = charts.coverageNote({ answered: 1, unparsed: 2, missing: 3 });
  assert.ok(html.indexOf("2 份未按题型作答") >= 0);
  assert.ok(html.indexOf("3 份缺失或出错") >= 0);
});

/* ----------------------------------------------------------- question block */

function entry(overrides) {
  return Object.assign(
    {
      question: { id: "q1", text: "你支持吗", kind: "choice", options: ["支持", "不支持"], round: 1 },
      stats: {
        rows: [
          { label: "支持", people: 6, share: 0.6, respondents: 3 },
          { label: "不支持", people: 4, share: 0.4, respondents: 2 },
        ],
        answered: 5,
        answered_people: 10,
      },
      breakdown: {},
      summary: "多数人支持，但外省户籍的受访者更犹豫。",
    },
    overrides || {}
  );
}

test("a question block carries the summary, the legend and the tally", function () {
  const html = charts.questionBlock(entry(), 1);
  assert.ok(html.indexOf("Q1. 你支持吗") >= 0);
  assert.ok(html.indexOf("选择题") >= 0);
  assert.ok(html.indexOf("多数人支持") >= 0);
  assert.ok(html.indexOf("sv-legend") >= 0);
  assert.ok(html.indexOf("有效回答 5 份") >= 0);
});

test("a missing summary is marked rather than silently blank", function () {
  const html = charts.questionBlock(entry({ summary: "" }), 1);
  assert.ok(html.indexOf("未生成摘要") >= 0);
});

test("breakdown sections appear per axis with a readable heading", function () {
  const html = charts.questionBlock(
    entry({
      breakdown: {
        city: [
          { value: "甲", counts: {}, people: { 支持: 3 }, answered: 3, answered_people: 3 },
          { value: "乙", counts: {}, people: { 不支持: 2 }, answered: 2, answered_people: 2 },
        ],
      },
    }),
    2
  );
  assert.ok(html.indexOf("按城市拆分") >= 0);
});

test("an open question shows its summary and no chart", function () {
  const html = charts.questionBlock(
    entry({
      question: { id: "q2", text: "还有什么想说的", kind: "open", options: [], round: 2 },
      stats: { rows: [], answered: 4, answered_people: 4 },
      breakdown: {},
    }),
    3
  );
  assert.ok(html.indexOf("开放题") >= 0);
  assert.ok(html.indexOf("第 2 轮") >= 0);
  assert.strictEqual(html.indexOf("sv-legend"), -1);
});

test("a malformed entry renders nothing instead of throwing", function () {
  assert.strictEqual(charts.questionBlock(null, 1), "");
  assert.strictEqual(charts.questionBlock({}, 1), "");
});

/* --------------------------------------------------------------- cost note */

test("cost counts calls as respondents times questions", function () {
  const summary = charts.costSummary(
    [{ kind: "agent", size: 1 }, { kind: "cohort", size: 40 }],
    [{ text: "a" }, { text: "b" }, { text: "c" }]
  );
  assert.strictEqual(summary.respondents, 2);
  assert.strictEqual(summary.individuals, 1);
  assert.strictEqual(summary.cohorts, 1);
  assert.strictEqual(summary.people, 41);
  assert.strictEqual(summary.calls, 6);
});

test("cost of nothing is zero, not NaN", function () {
  const summary = charts.costSummary(null, null);
  assert.strictEqual(summary.calls, 0);
  assert.strictEqual(summary.people, 0);
});

/* ------------------------------------------------------------------- labels */

test("the host can localize every display string the renderer emits", function () {
  // The panel is bilingual; a renderer with hardcoded Chinese would print it
  // into an English UI.
  charts.setLabels({
    defaultCity: "Default world",
    kinds: { choice: "Multiple choice" },
    axes: { city: "City" },
    round: "round {n}",
    noSummary: "(no summary generated)",
    breakdownBy: "By {axis}",
    people: "people",
    coverage: {
      answered: "{n} usable answers",
      people: "standing for {n} people",
      unparsed: "{n} excluded",
      missing: "{n} missing",
    },
  });
  try {
    const html = charts.questionBlock(
      entry({
        breakdown: {
          city: [
            { value: "default", counts: {}, people: { 支持: 3 }, answered: 3, answered_people: 3 },
            { value: "绍兴柯桥", counts: {}, people: { 不支持: 2 }, answered: 2, answered_people: 2 },
          ],
        },
        stats: {
          rows: [{ label: "支持", people: 3, share: 0.6, respondents: 3 }],
          answered: 5,
          answered_people: 5,
          unparsed: 1,
        },
      }),
      1
    );
    assert.ok(html.indexOf("Multiple choice") >= 0);
    assert.ok(html.indexOf("round 1") >= 0);
    assert.ok(html.indexOf("By City") >= 0);
    assert.ok(html.indexOf("Default world") >= 0);
    assert.ok(html.indexOf("5 usable answers") >= 0);
    assert.ok(html.indexOf("1 excluded") >= 0);
    assert.ok(html.indexOf("people") >= 0);
    // No Chinese chrome left over (the option label 支持 is data, not chrome).
    assert.strictEqual(html.indexOf("拆分"), -1);
    assert.strictEqual(html.indexOf("有效回答"), -1);
    assert.strictEqual(html.indexOf("选择题"), -1);
  } finally {
    // Restore the Chinese defaults so test order cannot matter.
    charts.setLabels({
      defaultCity: "默认世界",
      kinds: { open: "开放题", choice: "选择题", boolean: "是非题" },
      axes: charts.AXIS_LABELS,
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
    });
  }
});

test("setLabels leaves untouched strings at their defaults", function () {
  charts.setLabels({ people: "persons" });
  try {
    assert.ok(charts.coverageNote({ answered: 2, answered_people: 2 }).indexOf("有效回答") >= 0);
  } finally {
    charts.setLabels({ people: "人" });
  }
});

console.log("survey-charts.test.js: " + passed + " assertions passed");
