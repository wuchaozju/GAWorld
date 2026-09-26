/* Unit tests for the 真人蒸馏 renderers.
 *
 *   node site/dashboard/persona-view.test.js
 *
 * Mirrors the survey-charts.test.js convention: plain node, no framework, no
 * browser. Worth having because the Python tests cover the endpoints and
 * cannot see the panel at all — a persona rendered without its sources, or a
 * "证据不足" portrait rendered as if it were solid, would leave every backend
 * test green while misleading the person deciding whether to deploy it.
 */
"use strict";

const assert = require("assert");
const view = require("./persona-view.js");

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

const PERSONA = {
  name: "李某",
  slug: "li-mou",
  summary: "一位做纺织外贸的经营者",
  gender: "男",
  age: 47,
  hukou: "绍兴",
  residence: "柯桥",
  job: "经营一家面料出口公司",
  education_income: "",
  daily_life: "早七点到厂",
  social_network: "同业商会",
  values: "务实",
  mental_models: [
    { name: "订单即信号", gist: "从订单结构反推行业周期", evidence: ["2023年提前减产"], limits: "只在自有渠道成立" },
  ],
  heuristics: [{ rule: "如果账期超过90天，则不接单", example: "2022年拒绝一家大客户" }],
  voice: { sentences: "短句", vocabulary: "行业术语多", phrases: ["先看单子"] },
  anti_patterns: ["赊账扩张"],
  boundaries: ["仅基于 6 条公开材料蒸馏"],
  state: { emotion: 0.6, stress: 0.7 },
  big5: { o: 0.3 },
  sources: [{ title: "某篇报道", url: "https://example.com/a", kind: "page" }],
  unknown_fields: ["education_income"],
  confidence: "medium",
  evidence_items: 6,
  evidence_pages: 2,
};

/* ------------------------------------------------------------------ escaping */

test("escapes HTML in every persona field", () => {
  const nasty = Object.assign({}, PERSONA, {
    name: "<script>alert(1)</script>",
    summary: 'a "quoted" & <b>bold</b>',
  });
  const html = view.personaView(nasty);
  assert.ok(!html.includes("<script>"), "raw script tag reached the DOM");
  assert.ok(html.includes("&lt;script&gt;"));
  assert.ok(html.includes("&amp;"));
});

test("escapes source titles and URLs", () => {
  const html = view.sourcesCard({ sources: [{ title: '<img onerror=x>', url: 'https://e.com/"x' }] });
  assert.ok(!html.includes("<img onerror"));
  assert.ok(html.includes("&quot;x"));
});

/* ---------------------------------------------------------------- provenance */

test("confidence chip carries the evidence counts", () => {
  const html = view.confidenceChip(PERSONA);
  assert.ok(html.includes("6"), "item count missing");
  assert.ok(html.includes("2"), "page count missing");
  assert.ok(html.includes("warn"), "medium confidence should read as a warning");
});

test("a persona with no confidence field reads as poorly sourced", () => {
  assert.ok(view.confidenceChip({}).includes("bad"));
  assert.ok(view.confidenceChip(null).includes("bad"));
});

test("sources are rendered as links that cannot hijack the opener", () => {
  const html = view.sourcesCard(PERSONA);
  assert.ok(html.includes('href="https://example.com/a"'));
  assert.ok(html.includes('rel="noopener noreferrer"'));
  assert.ok(html.includes('target="_blank"'));
});

test("a persona with no sources says so instead of rendering an empty list", () => {
  const html = view.sourcesCard({ sources: [] });
  assert.ok(html.includes("没有记录到来源"));
});

/* ------------------------------------------------------------------ the gaps */

test("unsourced identity fields are marked, not blanked", () => {
  const html = view.identityCard(PERSONA);
  assert.ok(html.includes("资料不足"), "an empty field rendered as a silent blank");
  assert.ok(html.includes("education_income"), "the gap list is not shown");
});

test("a framework with nothing in it says why", () => {
  const html = view.frameworkCard({ mental_models: [], heuristics: [], voice: {} });
  assert.ok(html.includes("材料不足以支撑"));
  assert.ok(html.includes("未提炼出可复用的决策规则"));
});

test("a framework the model failed to produce is not blamed on the evidence", () => {
  // Thin sources and a broken model answer call for opposite actions — go find
  // better sources, versus press the button again.
  const html = view.frameworkCard({
    mental_models: [], heuristics: [], voice: {},
    framework_error: "模型两次都没有返回可解析的思维框架，可以重试一次。",
  });
  assert.ok(html.includes("可以重试一次"));
  assert.ok(!html.includes("材料不足以支撑"), "that would send the operator the wrong way");
});

test("a mental model with no evidence is called out", () => {
  const html = view.frameworkCard({ mental_models: [{ name: "空模型", gist: "没有依据" }] });
  assert.ok(html.includes("未给出依据"));
});

/* --------------------------------------------------------------- the content */

test("the framework card renders models, heuristics and voice", () => {
  const html = view.frameworkCard(PERSONA);
  assert.ok(html.includes("订单即信号"));
  assert.ok(html.includes("从订单结构反推行业周期"));
  assert.ok(html.includes("2023年提前减产"));
  assert.ok(html.includes("只在自有渠道成立"));
  assert.ok(html.includes("如果账期超过90天，则不接单"));
  assert.ok(html.includes("短句"));
  assert.ok(html.includes("先看单子"));
  assert.ok(html.includes("赊账扩张"));
  assert.ok(html.includes("仅基于 6 条公开材料蒸馏"));
});

test("the full view puts provenance above the claims", () => {
  const html = view.personaView(PERSONA);
  assert.ok(html.indexOf("pd-chip") < html.indexOf("订单即信号"));
});

test("an absent persona renders nothing at all", () => {
  assert.strictEqual("", view.personaView(null));
});

/* ---------------------------------------------------------------- the archive */

test("the archive lists each portrait with its model count", () => {
  const html = view.archiveList([
    { slug: "li-mou", name: "李某", confidence: "medium", mental_models: 3, agent_id: 81 },
    { slug: "wang", name: "王某", confidence: "low", mental_models: 0 },
  ]);
  assert.ok(html.includes('data-slug="li-mou"'));
  assert.ok(html.includes("已落地 #81"));
  assert.ok(html.includes("王某"));
  assert.ok(!html.includes("已落地 #undefined"), "an undeployed portrait claimed an agent id");
});

test("an empty archive says so", () => {
  assert.ok(view.archiveList([]).includes("还没有蒸馏过任何人"));
});

/* ------------------------------------------------------------------- the form */

test("draftFromPersona maps onto the studio's identity fields", () => {
  const draft = view.draftFromPersona(PERSONA);
  assert.strictEqual(draft.identity.name, "李某");
  assert.strictEqual(draft.identity.age, 47);
  assert.strictEqual(draft.identity.residence, "柯桥");
  assert.strictEqual(draft.narrative.job, "经营一家面料出口公司");
  assert.strictEqual(draft.slug, "li-mou");
  assert.strictEqual(draft.state.emotion, 0.6);
});

test("draftFromPersona falls back rather than writing blanks into the seed", () => {
  const draft = view.draftFromPersona({ name: "无名" });
  assert.strictEqual(draft.identity.gender, "未知");
  assert.strictEqual(draft.identity.hukou, "未知");
  assert.strictEqual(draft.identity.residence, "杭州");
  assert.strictEqual(draft.identity.age, 40);
});

console.log("persona-view.test.js: " + passed + " passed");
