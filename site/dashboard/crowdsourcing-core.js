/* Pure helpers for the swarm-crowdsourcing pane.
 *
 * No DOM, no fetch, no globals: the page controller imports this module and
 * the Node unit tests require() it directly, so every export stays a plain
 * function over plain data. `globalThis` keeps the file loadable in Node
 * without a browser around it.
 */
(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.GAWorldCrowdsourcingCore = api;
  }
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const POLL_STATUSES = ["queued", "running", "paused", "failed", "interrupted"];

  /* Status / method -> i18n key. The keys live in the locale files; this
   * module stays free of the translation runtime, so it hands the key back
   * and the page turns it into a sentence. */
  const STATUS_LABEL_KEYS = {
    queued: "crowd.status_queued",
    running: "crowd.status_running",
    paused: "crowd.status_paused",
    completed: "crowd.status_completed",
    cancelled: "crowd.status_cancelled",
    failed: "crowd.status_failed",
    interrupted: "crowd.status_interrupted",
  };

  const METHOD_LABEL_KEYS = {
    best_score: "crowd.method_best_score",
    vote: "crowd.method_vote",
    market: "crowd.method_market",
    debate: "crowd.method_debate",
    elite: "crowd.method_elite",
  };

  function clamp(value, min, max) {
    let number = Number(value);
    if (!Number.isFinite(number)) {
      number = Number(min);
      if (!Number.isFinite(number)) {
        number = 0;
      }
    }
    if (min !== undefined && min !== null && Number.isFinite(Number(min))) {
      if (number < Number(min)) {
        return Number(min);
      }
    }
    if (max !== undefined && max !== null && Number.isFinite(Number(max))) {
      if (number > Number(max)) {
        return Number(max);
      }
    }
    return number;
  }

  function toFiniteNumber(value) {
    if (value === null || value === undefined || value === "") {
      return null;
    }
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function toPositiveInt(value) {
    const number = Number(value);
    return Number.isInteger(number) && number > 0 ? number : null;
  }

  function firstDefined(source, keys) {
    if (!source || typeof source !== "object") {
      return null;
    }
    for (let index = 0; index < keys.length; index += 1) {
      const value = source[keys[index]];
      if (value !== undefined && value !== null && value !== "") {
        return value;
      }
    }
    return null;
  }

  function normalizeAgentIds(values) {
    const result = [];
    (Array.isArray(values) ? values : []).forEach(function (raw) {
      const value = Number(raw);
      if (
        Number.isInteger(value)
        && value > 0
        && !result.includes(value)
      ) {
        result.push(value);
      }
    });
    return result;
  }

  function buildPayload(options) {
    const opts = options || {};
    const rounds = Math.max(1, Math.round(Number(opts.rounds) || 1));
    const participantsPerRound = Math.max(
      1,
      Math.round(Number(opts.participantsPerRound) || 1),
    );
    const keep = Math.max(1, Math.round(Number(opts.keep) || 1));
    return {
      task: String(opts.task || "").trim(),
      criteria: String(opts.criteria || "").trim(),
      strategy: String(opts.strategy || "market").trim() || "market",
      agent_ids: normalizeAgentIds(opts.agentIds),
      rounds: rounds,
      participants_per_round: participantsPerRound,
      prune: {
        enabled: Boolean(opts.pruneEnabled),
        keep: keep,
        explore_ratio: clamp(opts.exploreRatio, 0, 1),
      },
    };
  }

  /* A round costs one attempt per participating agent plus one judge call;
   * the market mechanism adds a bid call for every resident still in the
   * pool — the whole crowd gets to quote, not only the ones who end up
   * working. A round can never involve more agents than the pool holds. */
  function estimateCalls(options) {
    const opts = options || {};
    const strategy = String(opts.strategy || "").trim();
    const poolSize = Math.max(0, Math.round(Number(opts.poolSize) || 0));
    const rounds = Math.max(0, Math.round(Number(opts.rounds) || 0));
    const requested = Math.max(
      0,
      Math.round(Number(opts.participantsPerRound) || 0),
    );
    const participants = Math.min(requested, poolSize);
    if (!rounds || !participants) {
      return 0;
    }
    const attempts = participants;
    const judge = 1;
    const bids = strategy === "market" ? poolSize : 0;
    return rounds * (attempts + judge + bids);
  }

  function randomSample(values, count, rng) {
    const pool = Array.isArray(values) ? values.slice() : [];
    const wanted = Math.max(0, Math.round(Number(count) || 0));
    const random = typeof rng === "function" ? rng : Math.random;
    const picked = [];
    const total = Math.min(wanted, pool.length);
    for (let index = 0; index < total; index += 1) {
      const remaining = pool.length - index;
      const roll = Number(random());
      let position = Number.isFinite(roll) ? Math.floor(roll * remaining) : 0;
      if (!Number.isFinite(position) || position < 0) {
        position = 0;
      }
      if (position > remaining - 1) {
        position = remaining - 1;
      }
      picked.push(pool.splice(position, 1)[0]);
    }
    return picked;
  }

  function normalizeBid(raw) {
    if (!raw || typeof raw !== "object") {
      return null;
    }
    const agentId = toPositiveInt(
      firstDefined(raw, ["agent_id", "agent", "id"]),
    );
    if (agentId === null) {
      return null;
    }
    return {
      agent_id: agentId,
      value: toFiniteNumber(
        firstDefined(raw, ["value", "bid", "amount", "price", "score"]),
      ),
      confidence: toFiniteNumber(
        firstDefined(raw, ["confidence", "certainty", "confidence_score"]),
      ),
      reason: String(
        firstDefined(raw, ["reason", "rationale", "text", "note", "comment"]) || "",
      ),
    };
  }

  function normalizeAttempt(raw) {
    if (!raw || typeof raw !== "object") {
      return null;
    }
    const agentId = toPositiveInt(
      firstDefined(raw, ["agent_id", "agent", "id"]),
    );
    if (agentId === null) {
      return null;
    }
    return {
      agent_id: agentId,
      answer: String(
        firstDefined(raw, ["answer", "text", "content", "response", "output"]) || "",
      ),
      rationale: String(
        firstDefined(raw, ["rationale", "reason", "explanation", "why"]) || "",
      ),
      score: toFiniteNumber(
        firstDefined(raw, ["score", "rating", "value", "quality"]),
      ),
    };
  }

  function normalizeScores(raw) {
    const result = [];
    if (Array.isArray(raw)) {
      raw.forEach(function (item) {
        if (!item || typeof item !== "object") {
          return;
        }
        const agentId = toPositiveInt(
          firstDefined(item, ["agent_id", "agent", "id"]),
        );
        const score = toFiniteNumber(
          firstDefined(item, ["score", "value", "rating"]),
        );
        if (agentId === null || score === null) {
          return;
        }
        result.push({agent_id: agentId, score: score});
      });
      return result;
    }
    if (raw && typeof raw === "object") {
      Object.keys(raw).forEach(function (key) {
        const agentId = toPositiveInt(key);
        const score = toFiniteNumber(raw[key]);
        if (agentId === null || score === null) {
          return;
        }
        result.push({agent_id: agentId, score: score});
      });
    }
    return result;
  }

  /* Vote counts per agent, for the vote mechanism: either a list of
   {agent_id, votes} or a map from agent id to votes. */
  function normalizeVotes(raw) {
    const result = [];
    if (Array.isArray(raw)) {
      raw.forEach(function (item) {
        if (!item || typeof item !== "object") {
          return;
        }
        const agentId = toPositiveInt(
          firstDefined(item, ["agent_id", "agent", "id"]),
        );
        const votes = toFiniteNumber(
          firstDefined(item, ["votes", "count", "value"]),
        );
        if (agentId === null || votes === null) {
          return;
        }
        result.push({agent_id: agentId, votes: votes});
      });
      return result;
    }
    if (raw && typeof raw === "object") {
      Object.keys(raw).forEach(function (key) {
        const agentId = toPositiveInt(key);
        const votes = toFiniteNumber(raw[key]);
        if (agentId === null || votes === null) {
          return;
        }
        result.push({agent_id: agentId, votes: votes});
      });
    }
    return result;
  }

  function normalizeIdList(raw) {
    const result = [];
    (Array.isArray(raw) ? raw : []).forEach(function (item) {
      if (item && typeof item === "object") {
        const nested = toPositiveInt(
          firstDefined(item, ["agent_id", "agent", "id"]),
        );
        if (nested !== null && !result.includes(nested)) {
          result.push(nested);
        }
        return;
      }
      const id = toPositiveInt(item);
      if (id !== null && !result.includes(id)) {
        result.push(id);
      }
    });
    return result;
  }

  /* The market clears at the cheapest winning bid: the lowest bid among the
   * agents the round actually selected. */
  function lowestWinningBid(bids, selected) {
    if (!Array.isArray(bids) || !bids.length) {
      return null;
    }
    if (!Array.isArray(selected) || !selected.length) {
      return null;
    }
    let lowest = null;
    bids.forEach(function (bid) {
      if (!bid || !selected.includes(bid.agent_id)) {
        return;
      }
      if (bid.value === null || bid.value === undefined) {
        return;
      }
      if (lowest === null || bid.value < lowest) {
        lowest = bid.value;
      }
    });
    return lowest;
  }

  function summarizeRound(round) {
    const source = round && typeof round === "object" ? round : {};
    const aggregate = source.aggregate && typeof source.aggregate === "object"
      ? source.aggregate
      : {};
    const bids = (Array.isArray(source.bids) ? source.bids : [])
      .map(normalizeBid)
      .filter(Boolean);
    const scores = normalizeScores(source.scores);
    const attempts = (Array.isArray(source.attempts) ? source.attempts : [])
      .map(normalizeAttempt)
      .filter(Boolean)
      .map(function (attempt) {
        if (attempt.score !== null) {
          return attempt;
        }
        const match = scores.find(function (item) {
          return item.agent_id === attempt.agent_id;
        });
        return Object.assign({}, attempt, {
          score: match ? match.score : null,
        });
      });
    const selected = normalizeIdList(source.selected);
    const survivors = normalizeIdList(source.survivors);
    let agreement = toFiniteNumber(
      firstDefined(aggregate, ["agreement", "consensus", "agreement_ratio"]),
    );
    if (agreement === null) {
      agreement = toFiniteNumber(source.agreement);
    }
    let clearingPrice = toFiniteNumber(
      firstDefined(aggregate, ["clearing_price", "clearingPrice", "price"]),
    );
    if (clearingPrice === null) {
      clearingPrice = lowestWinningBid(bids, selected);
    }
    const index = Number(source.index);
    const winner = toPositiveInt(firstDefined(aggregate, [
      "aggregated_agent_id",
      "winner_agent_id",
      "winner",
      "agent_id",
    ])) || toPositiveInt(source.aggregated_agent_id);
    return {
      index: Number.isInteger(index) ? index : 0,
      method: String(
        firstDefined(aggregate, ["method", "mode"]) || source.method || "",
      ).trim(),
      winner_agent_id: winner,
      agreement: agreement,
      clearingPrice: clearingPrice,
      calls: Math.max(0, Math.round(Number(source.calls) || 0)),
      selected: selected,
      survivors: survivors,
      bids: bids,
      attempts: attempts,
      scores: scores,
      votes: normalizeVotes(firstDefined(aggregate, ["votes", "vote_counts"])),
    };
  }

  function shouldPoll(session) {
    return Boolean(
      session
      && POLL_STATUSES.includes(String(session.status || ""))
    );
  }

  function formatStatus(status) {
    const key = String(status || "").trim().toLowerCase();
    return STATUS_LABEL_KEYS[key] || key;
  }

  function formatMethod(method) {
    const key = String(method || "").trim().toLowerCase();
    return METHOD_LABEL_KEYS[key] || key;
  }

  return {
    clamp: clamp,
    normalizeAgentIds: normalizeAgentIds,
    buildPayload: buildPayload,
    estimateCalls: estimateCalls,
    randomSample: randomSample,
    summarizeRound: summarizeRound,
    shouldPoll: shouldPoll,
    formatStatus: formatStatus,
    formatMethod: formatMethod,
  };
}));
