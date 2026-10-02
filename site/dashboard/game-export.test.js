/* node site/dashboard/game-export.test.js */
"use strict";

const assert = require("assert");
const gx = require("./game-export.js");

const NOW = new Date(2026, 8, 29, 10, 5);
let passed = 0;
function test(name, fn) {
  try { fn(); passed += 1; } catch (err) { console.error("FAIL " + name); throw err; }
}

test("persuasion: transcript, outcome, multi-line quote", () => {
  const md = gx.persuasion({
    agent_id: 3, agent_name: "王阿姨", question: "该不该拆?", max_turns: 5, turns_left: 3,
    status: "settled", outcome: "success", reason: "改口了",
    initial_answer: "不该\n绝对不该", final_answer: "可以拆",
    messages: [{ role: "player", text: "想想孩子" }, { role: "agent", text: "嗯" }],
  }, NOW);
  assert(md.startsWith("# 说服游戏"));
  assert(md.includes("> 不该\n> 绝对不该"));
  assert(md.includes("## 结果：说服成功"));
  assert(md.includes("轮数：2/5"));
  assert(md.includes("导出时间：2026-09-29 10:05"));
});

test("persuasion: unsettled game says so", () => {
  const md = gx.persuasion({ agent_id: 1, agent_name: "a", question: "q", max_turns: 2, turns_left: 2, initial_answer: "x", messages: [] }, NOW);
  assert(md.includes("尚未结算"));
});

test("disaster: table cells survive pipes and newlines", () => {
  const md = gx.disaster({
    disaster: { emoji: "🌊", name: "洪水" }, stages: ["水来了"],
    agents: [{ agent_id: 1, name: "甲", reactions: [{ action: "转移", detail: "a|b\nc", say: "跑", panic: 4, help: true }] }],
    stats: { overall: { avg_panic: 4, help_rate: 1, n: 1, actions: { 转移: 1 } }, per_stage: [{ text: "水来了", avg_panic: 4, help_rate: 1, actions: { 转移: 1 }, n: 1 }] },
  }, NOW);
  assert(md.includes("# 灾害模式：🌊 洪水"));
  assert(md.includes("a\\|b c"));
  assert(md.includes("互助率：100%"));
  assert(md.includes("## 第 1 幕"));
});

test("rumor: unreached residents and hop table", () => {
  const md = gx.rumor({
    rumor: { title: "菜场要拆", emoji: "📢" }, seeds: [1],
    stats: { reached: 1, total: 2, believers: 1, avg_belief: 80, superspreader: { name: "甲", n: 1 } },
    nodes: [
      { agent_id: 1, name: "甲", heard_round: 0, heard_from: null, action: "转发", belief: 80, believes: true, say: "真的" },
      { agent_id: 2, name: "乙", heard_round: null },
    ],
    rounds: [{ round: 0, reached: 1, believers: 1 }],
    transmissions: [{ round: 0, from: 1, to: 2, kind: "rumor", label: "转发" }],
  }, NOW);
  assert(md.includes("触达：1/2（50%）"));
  assert(md.includes("没听说"));
  assert(md.includes("| 第 1 轮 | #1 甲 | #2 乙 | 转发 |"));
});

test("duel: tie and winner labels, scoresheet total", () => {
  const run = {
    task: { title: "停车" },
    teams: [
      { key: "A", name: "红队", method: { title: "甲法" }, plans: [{ round: 0, headline: "h", steps: ["s1"] }], members: [] },
      { key: "B", name: "蓝队", method: { title: "乙法" }, plans: [], members: [] },
    ],
    verdict: { winner: "A", reason: "更稳", criteria: [{ key: "c1", label: "可行" }], scores: { A: { c1: 8, total: 8 }, B: { c1: 5, total: 5 } } },
  };
  const md = gx.duel(run, NOW);
  assert(md.includes("## 结果：红队 赢"));
  assert(md.includes("| 合计 | 8 | 5 |"));
  run.verdict.winner = "tie";
  assert(gx.duel(run, NOW).includes("## 结果：打平"));
});

test("referendum: tally and flips", () => {
  const md = gx.referendum({
    motion: { title: "停车场" }, campaign: "为了孩子",
    stats: { total: 2, result: "通过", swing: 1, flips: 1, private: { 支持: 1, 反对: 1, 弃权: 0, avg_strength: 3 }, public: { 支持: 2, 反对: 0, 弃权: 0, avg_strength: 4 } },
    flips: [{ name: "乙", from: "反对", to: "支持", say: "随大流" }],
    voters: [{ agent_id: 2, name: "乙", job: "教师", private: { stance: "反对" }, public: { stance: "支持", strength: 3, say: "好吧" } }],
  }, NOW);
  assert(md.includes("## 结果：通过"));
  assert(md.includes("较私下表态 +1"));
  assert(md.includes("| 乙 | 反对 → 支持 | 随大流 |"));
});

test("guess: marks both picks", () => {
  const md = gx.guess({
    settled: true, correct: false, guess: "A", choice: "B", why: "顾家",
    agent: { agent_id: 4, name: "丙" }, dilemma: { text: "选?", options: [{ key: "A", text: "走" }, { key: "B", text: "留" }] },
    samples: [{ choice: "B" }, { choice: "A" }],
  }, null, NOW);
  assert(md.includes("- **A** 走　（你猜）"));
  assert(md.includes("- **B** 留　（他选）"));
  assert(md.includes("答案不一致"));
});

test("arena: ranking rows", () => {
  const md = gx.arena({ city: "c", leaderboard: [{ agent_id: 1, name: "甲", accuracy: 0.5, correct: 1, attempted: 2, median_latency_s: 1.234 }] }, { eliminated: [9] }, NOW);
  assert(md.includes("| 1 | #1 甲 | 50%（1/2） | 1.23s |"));
  assert(md.includes("#9"));
});

test("fileName is filesystem safe", () => {
  assert.strictEqual(gx.fileName("arena", "a/b c", NOW), "arena-a-b-c-20260929-1005.md");
  assert(gx.fileName("x", "", NOW).includes("-result-"));
});

console.log(`${passed} passed`);
