"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("./crowdsourcing-core.js");


test("agent ids normalize to unique positive integers", () => {
  assert.deepEqual(
    core.normalizeAgentIds(["2", 1, "2", 0, -3, "not-an-id", 4.5]),
    [2, 1],
  );
});


test("a crowd payload carries the task, the pool and the pruning switch", () => {
  const payload = core.buildPayload({
    task: "  为商业街设计夜间照明  ",
    criteria: "  可行性  ",
    strategy: "market",
    agentIds: [3, "1", 3],
    rounds: "2",
    participantsPerRound: "5",
    pruneEnabled: true,
    keep: "8",
    exploreRatio: 0.25,
  });

  assert.equal(payload.task, "为商业街设计夜间照明");
  assert.equal(payload.criteria, "可行性");
  assert.equal(payload.strategy, "market");
  assert.deepEqual(payload.agent_ids, [3, 1]);
  assert.equal(payload.rounds, 2);
  assert.equal(payload.participants_per_round, 5);
  assert.deepEqual(payload.prune, {
    enabled: true,
    keep: 8,
    explore_ratio: 0.25,
  });
});


test("the payload defaults to the market mechanism and trims the explore ratio", () => {
  const payload = core.buildPayload({
    task: "t",
    agentIds: [1, 2],
    rounds: 0,
    participantsPerRound: 0,
    pruneEnabled: false,
    keep: 0,
    exploreRatio: 4,
  });

  assert.equal(payload.strategy, "market");
  assert.equal(payload.rounds, 1);
  assert.equal(payload.participants_per_round, 1);
  assert.equal(payload.prune.enabled, false);
  assert.equal(payload.prune.explore_ratio, 1);
});


test("the call estimate counts attempts, one judge and the market's bids", () => {
  // 3 rounds x (3 attempts + 1 judge) for a plain mechanism.
  assert.equal(
    core.estimateCalls({
      strategy: "vote",
      poolSize: 9,
      rounds: 3,
      participantsPerRound: 3,
    }),
    12,
  );
  // The market quotes with the whole pool, not only the ones who work.
  assert.equal(
    core.estimateCalls({
      strategy: "market",
      poolSize: 9,
      rounds: 3,
      participantsPerRound: 3,
    }),
    39,
  );
});


test("the call estimate never exceeds the pool and needs a round to count", () => {
  assert.equal(
    core.estimateCalls({
      strategy: "vote",
      poolSize: 2,
      rounds: 1,
      participantsPerRound: 9,
    }),
    3,
  );
  assert.equal(
    core.estimateCalls({
      strategy: "vote",
      poolSize: 9,
      rounds: 0,
      participantsPerRound: 3,
    }),
    0,
  );
});


test("a random sample draws distinct agents and never more than the pool", () => {
  const values = [1, 2, 3, 4, 5];
  const picked = core.randomSample(values, 3, () => 0);

  assert.deepEqual(picked, [1, 2, 3]);
  assert.deepEqual(core.randomSample(values, 99, () => 0).length, 5);
  assert.deepEqual(core.randomSample([], 3, () => 0), []);
  // The source list is not consumed.
  assert.deepEqual(values, [1, 2, 3, 4, 5]);
});


test("a status maps to its label key", () => {
  assert.equal(core.formatStatus("running"), "crowd.status_running");
  assert.equal(core.formatStatus("completed"), "crowd.status_completed");
  // An unrecognised status is echoed rather than guessed at.
  assert.equal(core.formatStatus("nonsense"), "nonsense");
});


test("a mechanism maps to its label key", () => {
  assert.equal(core.formatMethod("vote"), "crowd.method_vote");
  assert.equal(core.formatMethod("market"), "crowd.method_market");
  assert.equal(core.formatMethod("nonsense"), "nonsense");
});


test("clamp keeps a number inside its bounds", () => {
  assert.equal(core.clamp(5, 0, 1), 1);
  assert.equal(core.clamp(-5, 0, 1), 0);
  assert.equal(core.clamp(0.4, 0, 1), 0.4);
  assert.equal(core.clamp("nonsense", 0, 1), 0);
});


test("a finished crowd stops being polled", () => {
  assert.equal(core.shouldPoll({ status: "running" }), true);
  assert.equal(core.shouldPoll({ status: "queued" }), true);
  assert.equal(core.shouldPoll({ status: "paused" }), true);
  assert.equal(core.shouldPoll({ status: "completed" }), false);
  assert.equal(core.shouldPoll({ status: "cancelled" }), false);
  assert.equal(core.shouldPoll(null), false);
});
