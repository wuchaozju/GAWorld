"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("./collaboration-core.js");


test("agent ids normalize to unique positive integers", () => {
  assert.deepEqual(
    core.normalizeAgentIds(["2", 1, "2", 0, -3, "not-an-id", 4.5]),
    [2, 1],
  );
});


test("discussion payload normalizes members and trims topic", () => {
  assert.deepEqual(
    core.discussionPayload(["2", 1, "2"], "  公共空间  ", "6"),
    {
      kind: "discussion",
      agent_ids: [2, 1],
      topic: "公共空间",
      max_rounds: 6,
    },
  );
});


test("cooperation payload includes only a valid leader", () => {
  assert.deepEqual(
    core.cooperationPayload(
      [3, "1", 3],
      "  联合报告 ",
      "3",
      {"1": "研究", "3": "编辑"},
    ),
    {
      kind: "cooperation",
      agent_ids: [3, 1],
      task: "联合报告",
      leader_id: 3,
      role_overrides: {"1": "研究", "3": "编辑"},
    },
  );
  assert.equal(
    Object.hasOwn(
      core.cooperationPayload([1, 2], "报告", "none", {}),
      "leader_id",
    ),
    false,
  );
});


test("only active sessions continue polling", () => {
  ["queued", "running", "paused", "failed", "interrupted"].forEach((status) => {
    assert.equal(core.shouldPoll({status}), true);
  });
  ["completed", "cancelled", "unknown"].forEach((status) => {
    assert.equal(core.shouldPoll({status}), false);
  });
  assert.equal(core.shouldPoll(null), false);
});


test("full history requests wait for their polling generation", () => {
  const pendingGeneration = core.queueFullHistoryRequest(7);

  assert.equal(pendingGeneration, 7);
  assert.deepEqual(
    core.consumeFullHistoryRequest(pendingGeneration, 7),
    {fullHistory: true, pendingGeneration: null},
  );
  assert.deepEqual(
    core.consumeFullHistoryRequest(pendingGeneration, 8),
    {fullHistory: false, pendingGeneration: 7},
  );
});


test("poll responses are current only for the same generation and session", () => {
  const current = {generation: 4, sessionId: "new-session"};

  assert.equal(
    core.isCurrentPoll(current, {generation: 4, sessionId: "new-session"}),
    true,
  );
  assert.equal(
    core.isCurrentPoll(current, {generation: 3, sessionId: "new-session"}),
    false,
  );
  assert.equal(
    core.isCurrentPoll(current, {generation: 4, sessionId: "old-session"}),
    false,
  );
});


test("releasing a stale poll preserves the newer in-flight identity", () => {
  const current = {generation: 5, sessionId: "new-session"};
  const stale = {generation: 4, sessionId: "old-session"};

  assert.deepEqual(core.releaseCurrentPoll(current, stale), current);
  assert.equal(core.releaseCurrentPoll(current, current), null);
});


test("action identity serializes release by generation and session", () => {
  const current = {
    generation: 8,
    sessionId: "session-b",
    actionGeneration: 3,
    action: "cancel",
  };
  const stale = {
    generation: 8,
    sessionId: "session-b",
    actionGeneration: 2,
    action: "pause",
  };

  assert.equal(core.isCurrentAction(current, current), true);
  assert.equal(core.isCurrentAction(current, stale), false);
  assert.deepEqual(core.releaseCurrentAction(current, stale), current);
  assert.equal(core.releaseCurrentAction(current, current), null);
});
