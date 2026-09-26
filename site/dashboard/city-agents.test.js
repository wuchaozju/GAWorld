/* Unit tests for the shared "residents of a city" renderers.
 *
 *   node site/dashboard/city-agents.test.js
 *
 * Plain node, no framework, no browser — the survey-charts.test.js
 * convention. Worth having because both the 城市 page and Agent Studio render
 * from this one module: a row that lost its city, or an unescaped job title,
 * would be wrong in two places at once and green in every Python test.
 */
"use strict";

const assert = require("assert");
const view = require("./city-agents.js");

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

const PAYLOAD = {
  city: { slug: "wuzhen", name: "乌镇", selected: false },
  matched: 3,
  offset: 0,
  limit: 200,
  agents: [
    { id: 1, name: "阿甲", gender: "女", age: 31, hukou: "本地", residence: "西栅", job: "社区医生" },
    { id: 2, name: "阿乙", gender: "男", age: 46, hukou: "外地", residence: "东栅", job: "货车司机" },
    { id: 3, name: "阿丙", gender: "女", age: 27, hukou: "本地", residence: "南栅", job: "" },
  ],
};

/* ------------------------------------------------------------------ escaping */

test("escapes every field that reaches the table", () => {
  const html = view.agentTable({
    agents: [{ id: 1, name: "<script>alert(1)</script>", job: 'a "quoted" & <b>x</b>' }],
  });
  assert.ok(!html.includes("<script>"), "raw script tag reached the DOM");
  assert.ok(html.includes("&lt;script&gt;"));
  assert.ok(html.includes("&amp;"));
});

test("escapes city slugs and names in the picker", () => {
  const html = view.cityOptions([{ slug: '"x', name: "<b>城</b>", count: 1 }], "");
  assert.ok(!html.includes("<b>城</b>"));
  assert.ok(html.includes("&quot;x"));
});

/* -------------------------------------------------------------------- table */

test("renders one row per resident with the id beside the name", () => {
  const html = view.agentTable(PAYLOAD);
  assert.strictEqual((html.match(/data-agent-id=/g) || []).length, 3);
  assert.ok(html.includes("阿甲"));
  assert.ok(html.includes("社区医生"));
  assert.ok(html.includes("女 · 31岁"));
});

test("a resident with no job renders a dash, not an empty cell", () => {
  const html = view.agentTable({ agents: [PAYLOAD.agents[2]] });
  assert.ok(html.includes(">—<"));
});

test("an empty city says so instead of rendering an empty table", () => {
  const html = view.agentTable({ agents: [] });
  assert.ok(html.includes("还没有居民"));
  assert.ok(!html.includes("<table"));
});

test("rows link out only when a href builder is given", () => {
  assert.ok(!view.agentTable(PAYLOAD).includes("ca-open"));
  const linked = view.agentTable(PAYLOAD, (p) => "/studio?city=wuzhen&agent=" + p.id);
  assert.ok(linked.includes('href="/studio?city=wuzhen&amp;agent=1"'));
});

/* ------------------------------------------------------------------- counts */

test("the count reports the whole population, and the page when it is smaller", () => {
  assert.ok(view.countLabel(PAYLOAD).includes("3"));
  assert.ok(!view.countLabel(PAYLOAD).includes("显示"));
  const paged = view.countLabel({ matched: 500, agents: PAYLOAD.agents });
  assert.ok(paged.includes("500") && paged.includes("3"), paged);
});

test("no residents reads as no residents, not as zero of zero", () => {
  assert.ok(view.countLabel({ matched: 0, agents: [] }).includes("没有"));
});

/* ------------------------------------------------------------------ pickers */

test("the city picker marks the selected slug, default world included", () => {
  const cities = [{ slug: "", name: "默认世界", count: 60 }, { slug: "wuzhen", name: "乌镇", count: 3 }];
  assert.ok(view.cityOptions(cities, "").includes('value="" selected'));
  const onWuzhen = view.cityOptions(cities, "wuzhen");
  assert.ok(onWuzhen.includes('value="wuzhen" selected'));
  assert.ok(onWuzhen.includes("乌镇（3）"));
});

test("the agent picker keeps the id visible", () => {
  const html = view.agentOptions(PAYLOAD.agents, 2);
  assert.ok(html.includes('value="2" selected'));
  assert.ok(html.includes("1 · 阿甲"));
});

/* ------------------------------------------------------------------- detail */

test("identity rows lead with the city, because ids repeat across cities", () => {
  const rows = view.identityRows(PAYLOAD.agents[0], PAYLOAD.city);
  assert.strictEqual(rows[0][1], "乌镇");
  assert.strictEqual(rows[1][1], "#1");
});

test("identity rows drop the fields a resident does not have", () => {
  const rows = view.identityRows({ id: 3, name: "阿丙" }, { name: "乌镇" });
  const labels = rows.map((r) => r[0]).join("|");
  assert.ok(!labels.includes("职业"), "an empty job should not render a blank row");
});

/* ------------------------------------------------------------------- notice */

test("the read-only notice names the city and says why it is read-only", () => {
  const html = view.browseNotice({ name: "乌镇" });
  assert.ok(html.includes("乌镇"));
  assert.ok(html.includes("编号"), "the id-collision reason is the point of the notice");
  assert.ok(html.includes("caUseCityBtn"));
});

console.log("city-agents.test.js: " + passed + " passed");
