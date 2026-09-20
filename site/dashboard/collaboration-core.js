(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.GAWorldCollaborationCore = api;
  }
}(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  function normalizeAgentIds(values) {
    const result = [];
    (values || []).forEach(function (raw) {
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

  function discussionPayload(values, topic, maxRounds) {
    return {
      kind: "discussion",
      agent_ids: normalizeAgentIds(values),
      topic: String(topic || "").trim(),
      max_rounds: Number(maxRounds),
    };
  }

  function cooperationPayload(values, task, leaderId, roles) {
    const payload = {
      kind: "cooperation",
      agent_ids: normalizeAgentIds(values),
      task: String(task || "").trim(),
      role_overrides: Object.assign({}, roles || {}),
    };
    const leader = Number(leaderId);
    if (Number.isInteger(leader) && leader > 0) {
      payload.leader_id = leader;
    }
    return payload;
  }

  function shouldPoll(session) {
    return Boolean(
      session
      && [
        "queued",
        "running",
        "paused",
        "failed",
        "interrupted",
      ].includes(session.status)
    );
  }

  function queueFullHistoryRequest(generation) {
    return Number(generation);
  }

  function consumeFullHistoryRequest(pendingGeneration, generation) {
    if (pendingGeneration === generation) {
      return {
        fullHistory: true,
        pendingGeneration: null,
      };
    }
    return {
      fullHistory: false,
      pendingGeneration,
    };
  }

  function isCurrentPoll(current, request) {
    return Boolean(
      current
      && request
      && current.sessionId !== null
      && current.sessionId !== undefined
      && request.sessionId !== null
      && request.sessionId !== undefined
      && current.generation === request.generation
      && String(current.sessionId) === String(request.sessionId)
    );
  }

  function releaseCurrentPoll(current, request) {
    return isCurrentPoll(current, request) ? null : current;
  }

  function isCurrentAction(current, request) {
    return Boolean(
      isCurrentPoll(current, request)
      && current.actionGeneration === request.actionGeneration
    );
  }

  function releaseCurrentAction(current, request) {
    return isCurrentAction(current, request) ? null : current;
  }

  return {
    normalizeAgentIds,
    discussionPayload,
    cooperationPayload,
    shouldPoll,
    queueFullHistoryRequest,
    consumeFullHistoryRequest,
    isCurrentPoll,
    releaseCurrentPoll,
    isCurrentAction,
    releaseCurrentAction,
  };
}));
