"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("./organization-picker-core.js");


function builtin(id, name) {
  return {
    id,
    name,
    version: 1,
    builtin: true,
    slots: null,
    description: "全员互联",
    method: { roles: [], topology: { kind: "full" } },
    evidence: { verdict: "builtin" },
  };
}


function saved(id, name, roles, verdict) {
  return {
    id,
    name,
    version: 2,
    builtin: false,
    slots: roles.length,
    method: { roles },
    evidence: { verdict },
  };
}


test("entries keep the role count and the source of every method", () => {
  const entries = core.entries([
    builtin("builtin:full", "全员互联"),
    saved("M1", "试点小组", ["研究", "撰写"], "better"),
  ]);
  assert.equal(entries[0].builtin, true);
  assert.equal(entries[0].roles, 0);
  assert.equal(entries[1].builtin, false);
  assert.equal(entries[1].roles, 2);
  assert.equal(entries[1].verdict, "better");
  assert.equal(entries[1].rolesText, "研究 → 撰写");
});


test("a built-in label names the structure, a saved one names its version", () => {
  const entries = core.entries([
    builtin("builtin:full", "全员互联"),
    saved("M1", "试点小组", ["研究", "撰写"], "better"),
  ]);
  assert.equal(core.label(entries[0], false), "全员互联 · 内置基本组织方式");
  assert.equal(core.label(entries[0], true), "全员互联 · built-in structure");
  assert.equal(core.label(entries[1], false), "试点小组 · v2 · 2 位");
  assert.equal(core.label(entries[1], true), "试点小组 · v2 · 2 members");
});


test("the note without a method explains both kinds of choice", () => {
  const note = core.describe(null, 3, false);
  assert.match(note, /研究工作台/);
  assert.match(note, /内置的基本组织方式/);
});


test("a built-in note says how many roles the team will run", () => {
  const entries = core.entries([builtin("builtin:hierarchy", "层级组织")]);
  const note = core.describe(entries[0], 4, false);
  assert.match(note, /当前团队 4 位成员，将生成 4 个角色/);
  assert.match(note, /未在本任务上验证/);
});


test("a saved method warns when its roles do not match the team", () => {
  const entries = core.entries([saved("M1", "试点小组", ["研究", "撰写"], "uncertain")]);
  assert.match(core.describe(entries[0], 3, false), /与当前 3 位成员不符/);
  assert.doesNotMatch(core.describe(entries[0], 2, false), /不符/);
  assert.match(core.describe(entries[0], 2, false), /验证状态：尚无优势证据/);
  assert.match(core.describe(entries[0], 2, true), /Evidence: No established advantage/);
});


test("an unknown verdict reads as not validated", () => {
  assert.equal(core.evidence("whatever", false), "尚未验证");
  assert.equal(core.evidence("whatever", true), "Not validated");
  assert.equal(core.evidence("builtin", false), "内置基本组织方式");
});
