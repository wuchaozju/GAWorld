(function () {
  "use strict";

  const core = window.GAWorldCollaborationCore;
  if (!core) {
    return;
  }

  const state = {
    agents: [],
    selected: new Set(),
    session: null,
    lastSeq: 0,
    lastSpeakerId: null,
    pollTimer: null,
    sessionGeneration: 0,
    pollingGeneration: null,
    pollingSessionId: null,
    pendingFullHistoryGeneration: null,
    actionGeneration: 0,
    actionPending: null,
    notice: null,
    friendship: null,
  };

  const els = {};

  function translate(key) {
    return typeof window.__ === "function" ? window.__(key) : key;
  }

  function format(key, params) {
    if (typeof window.__f === "function") {
      return window.__f(key, params);
    }
    let result = translate(key);
    Object.keys(params || {}).forEach(function (name) {
      result = result
        .split("{" + name + "}")
        .join(String(params[name]));
    });
    return result;
  }

  async function request(path, options) {
    const settings = Object.assign({}, options || {});
    settings.headers = Object.assign(
      {"Content-Type": "application/json"},
      settings.headers || {},
    );
    const response = await fetch(path, settings);
    let payload = {};
    try {
      payload = await response.json();
    } catch (_) {
      payload = {};
    }
    if (!response.ok) {
      throw new Error(
        String(payload.error || format(
          "collaboration.http_error",
          {status: response.status},
        )),
      );
    }
    return payload;
  }

  function setBusy(button, busy) {
    button.disabled = Boolean(busy);
    button.classList.toggle("busy", Boolean(busy));
  }

  function agentFor(agentId) {
    return state.agents.find(function (agent) {
      return Number(agent.id) === Number(agentId);
    });
  }

  function agentName(agentId) {
    const agent = agentFor(agentId);
    if (!agent) {
      return format("collaboration.agent_fallback", {id: agentId});
    }
    return String(agent.name || format(
      "collaboration.agent_fallback",
      {id: agentId},
    ));
  }

  function selectedIds() {
    return core.normalizeAgentIds(Array.from(state.selected));
  }

  function renderSelectionState() {
    const count = state.selected.size;
    els.selectionCount.textContent = format(
      "collaboration.selection_count",
      {count},
    );
    els.makeFriendsBtn.disabled = count < 2;
    els.startDiscussionBtn.disabled = count < 2
      || Boolean(state.actionPending);
  }

  function toggleAgent(agentId) {
    if (state.selected.has(agentId)) {
      state.selected.delete(agentId);
    } else {
      state.selected.add(agentId);
    }
    renderMembers();
  }

  function renderMembers() {
    els.members.replaceChildren();
    if (!state.agents.length) {
      const empty = document.createElement("p");
      empty.className = "collaboration-roster-empty";
      empty.textContent = translate("collaboration.no_agents");
      els.members.appendChild(empty);
      renderSelectionState();
      return;
    }

    state.agents.forEach(function (agent) {
      const agentId = Number(agent.id);
      const selected = state.selected.has(agentId);
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "collaboration-member-chip";
      chip.classList.toggle("is-selected", selected);
      chip.setAttribute("role", "checkbox");
      chip.setAttribute("aria-checked", String(selected));
      chip.setAttribute(
        "aria-label",
        format(
          selected
            ? "collaboration.member_remove"
            : "collaboration.member_add",
          {id: agentId, name: String(agent.name || "")},
        ),
      );

      const id = document.createElement("span");
      id.className = "collaboration-member-id";
      id.textContent = "#" + String(agentId);
      const name = document.createElement("span");
      name.className = "collaboration-member-name";
      name.textContent = String(agent.name || "");
      chip.append(id, name);
      chip.addEventListener("click", function () {
        toggleAgent(agentId);
      });
      els.members.appendChild(chip);
    });
    renderSelectionState();
  }

  function renderNotice() {
    els.notice.classList.toggle(
      "is-error",
      Boolean(state.notice && state.notice.error),
    );
    if (!state.notice) {
      els.notice.textContent = translate("collaboration.status_idle");
      return;
    }
    if (state.notice.text !== undefined) {
      els.notice.textContent = String(state.notice.text);
      return;
    }
    els.notice.textContent = format(
      state.notice.key,
      state.notice.params || {},
    );
  }

  function notify(key, params, error) {
    state.notice = {
      key,
      params: params || {},
      error: Boolean(error),
    };
    renderNotice();
  }

  function reportError(error) {
    state.notice = {
      text: String(error && error.message ? error.message : error),
      error: true,
    };
    renderNotice();
  }

  function pairText(pairs) {
    return (pairs || []).map(function (pair) {
      return pair.map(function (agentId) {
        return "#" + String(agentId);
      }).join(" ↔ ");
    }).join(" · ");
  }

  function renderFriendship() {
    if (!state.friendship) {
      els.friendship.textContent = translate(
        "collaboration.friendship_idle",
      );
      return;
    }
    const created = state.friendship.created_pairs || [];
    const updated = state.friendship.updated_pairs || [];
    const existing = state.friendship.existing_pairs || [];
    const summary = format("collaboration.friendship_summary", {
      created: created.length,
      updated: updated.length,
      existing: existing.length,
    });
    const pairs = pairText(created.concat(updated, existing));
    els.friendship.textContent = pairs ? summary + " · " + pairs : summary;
  }

  async function loadAgents() {
    els.members.replaceChildren();
    const loading = document.createElement("p");
    loading.className = "collaboration-roster-empty";
    loading.textContent = translate("collaboration.loading_agents");
    els.members.appendChild(loading);
    try {
      const payload = await request("/api/agents");
      state.agents = Array.isArray(payload.agents)
        ? payload.agents.slice()
        : [];
      const knownIds = new Set(state.agents.map(function (agent) {
        return Number(agent.id);
      }));
      state.selected.forEach(function (agentId) {
        if (!knownIds.has(agentId)) {
          state.selected.delete(agentId);
        }
      });
      renderMembers();
    } catch (error) {
      state.agents = [];
      renderMembers();
      reportError(error);
    }
  }

  async function makeFriends() {
    const agentIds = selectedIds();
    if (agentIds.length < 2) {
      notify("collaboration.validation_members", {}, true);
      return;
    }
    setBusy(els.makeFriendsBtn, true);
    try {
      state.friendship = await request(
        "/api/relationships/friends",
        {
          method: "POST",
          body: JSON.stringify({agent_ids: agentIds}),
        },
      );
      renderFriendship();
      notify("collaboration.friendship_saved");
    } catch (error) {
      reportError(error);
    } finally {
      setBusy(els.makeFriendsBtn, false);
      renderSelectionState();
    }
  }

  function clearPollTimer() {
    if (state.pollTimer !== null) {
      window.clearTimeout(state.pollTimer);
      state.pollTimer = null;
    }
  }

  function invalidatePolling() {
    clearPollTimer();
    state.sessionGeneration += 1;
    state.pollingGeneration = null;
    state.pollingSessionId = null;
    state.pendingFullHistoryGeneration = null;
    return state.sessionGeneration;
  }

  function pollIdentity(generation, sessionId) {
    return {
      generation,
      sessionId,
    };
  }

  function currentPollIdentity() {
    return pollIdentity(
      state.sessionGeneration,
      state.session ? state.session.id : null,
    );
  }

  function isCurrentPoll(identity) {
    return core.isCurrentPoll(currentPollIdentity(), identity);
  }

  function isPollInFlight(identity) {
    return core.isCurrentPoll(
      pollIdentity(
        state.pollingGeneration,
        state.pollingSessionId,
      ),
      identity,
    );
  }

  function releasePoll(identity) {
    const remaining = core.releaseCurrentPoll(
      pollIdentity(
        state.pollingGeneration,
        state.pollingSessionId,
      ),
      identity,
    );
    state.pollingGeneration = remaining
      ? remaining.generation
      : null;
    state.pollingSessionId = remaining
      ? remaining.sessionId
      : null;
  }

  function schedulePoll() {
    clearPollTimer();
    if (
      state.actionPending
      || document.hidden
      || !core.shouldPoll(state.session)
    ) {
      return;
    }
    state.pollTimer = window.setTimeout(function () {
      refreshSession(false);
    }, 1000);
  }

  function statusKey(status) {
    const known = [
      "queued",
      "running",
      "paused",
      "completed",
      "cancelled",
      "failed",
      "interrupted",
    ];
    return known.includes(status)
      ? "collaboration.status_" + status
      : "collaboration.status_unknown";
  }

  function renderSession() {
    const session = state.session;
    if (!session) {
      els.status.textContent = translate("collaboration.status_idle");
      els.status.className = "collaboration-status is-idle";
      els.round.textContent = translate("collaboration.round_idle");
      els.speaker.textContent = translate("collaboration.speaker_idle");
      els.pauseBtn.hidden = true;
      els.resumeBtn.hidden = true;
      els.cancelBtn.hidden = true;
      els.pauseBtn.disabled = true;
      els.resumeBtn.disabled = true;
      els.cancelBtn.disabled = true;
      els.pauseBtn.classList.remove("busy");
      els.resumeBtn.classList.remove("busy");
      els.cancelBtn.classList.remove("busy");
      els.historyBtn.disabled = true;
      return;
    }
    const status = String(session.status || "unknown");
    const controlsDisabled = Boolean(state.actionPending);
    const pendingAction = state.actionPending
      ? state.actionPending.action
      : null;
    els.status.textContent = translate(statusKey(status));
    els.status.className = "collaboration-status is-" + status;
    els.round.textContent = format("collaboration.round_progress", {
      current: Number(session.current_round || 0),
      total: Number(session.max_rounds || 0),
    });
    els.speaker.textContent = state.lastSpeakerId === null
      ? translate("collaboration.speaker_idle")
      : format("collaboration.speaker_active", {
        name: agentName(state.lastSpeakerId),
      });
    els.pauseBtn.hidden = status !== "running";
    els.resumeBtn.hidden = ![
      "paused",
      "failed",
      "interrupted",
    ].includes(status);
    els.cancelBtn.hidden = ["completed", "cancelled"].includes(status);
    els.pauseBtn.disabled = controlsDisabled;
    els.resumeBtn.disabled = controlsDisabled;
    els.cancelBtn.disabled = controlsDisabled;
    els.historyBtn.disabled = controlsDisabled;
    els.pauseBtn.classList.toggle("busy", pendingAction === "pause");
    els.resumeBtn.classList.toggle("busy", pendingAction === "resume");
    els.cancelBtn.classList.toggle("busy", pendingAction === "cancel");
    if (!core.shouldPoll(session)) {
      clearPollTimer();
    }
  }

  function renderEmptyTranscript() {
    if (els.transcript.childElementCount) {
      return;
    }
    const empty = document.createElement("p");
    empty.className = "collaboration-transcript-empty";
    empty.dataset.emptyTranscript = "true";
    empty.textContent = translate("collaboration.empty_transcript");
    els.transcript.appendChild(empty);
  }

  function appendEvents(events) {
    const incoming = Array.isArray(events) ? events : [];
    if (incoming.length) {
      const empty = els.transcript.querySelector(
        "[data-empty-transcript]",
      );
      if (empty) {
        empty.remove();
      }
    }
    incoming.forEach(function (event) {
      const sequence = Number(event.seq || 0);
      if (sequence <= state.lastSeq) {
        return;
      }
      state.lastSeq = sequence;
      if (event.agent_id !== null && event.agent_id !== undefined) {
        state.lastSpeakerId = Number(event.agent_id);
      }

      const item = document.createElement("article");
      item.className = "collaboration-event";
      item.dataset.eventType = String(event.type || "");

      const marker = document.createElement("span");
      marker.className = "collaboration-event-marker";
      marker.setAttribute("aria-hidden", "true");

      const body = document.createElement("div");
      body.className = "collaboration-event-body";
      const meta = document.createElement("div");
      meta.className = "collaboration-event-meta";
      const speaker = document.createElement("strong");
      speaker.className = "collaboration-event-speaker";
      speaker.textContent = event.agent_id === null
        || event.agent_id === undefined
        ? translate("collaboration.speaker_system")
        : agentName(event.agent_id);
      const sequenceLabel = document.createElement("span");
      sequenceLabel.textContent = format(
        "collaboration.event_sequence",
        {seq: sequence},
      );
      meta.append(speaker, sequenceLabel);

      const content = document.createElement("p");
      content.className = "collaboration-event-content";
      content.textContent = String(event.content ?? "");
      body.append(meta, content);
      item.append(marker, body);
      els.transcript.appendChild(item);
    });
    renderEmptyTranscript();
    renderSession();
    if (incoming.length) {
      els.transcript.scrollTop = els.transcript.scrollHeight;
    }
  }

  async function refreshSession(fullHistory) {
    if (state.actionPending) {
      return;
    }
    const generation = state.sessionGeneration;
    if (fullHistory) {
      state.pendingFullHistoryGeneration = (
        core.queueFullHistoryRequest(generation)
      );
    }
    if (!state.session) {
      return;
    }
    const sessionId = String(state.session.id);
    const identity = pollIdentity(generation, sessionId);
    if (isPollInFlight(identity) || document.hidden) {
      return;
    }
    const historyRequest = core.consumeFullHistoryRequest(
      state.pendingFullHistoryGeneration,
      generation,
    );
    state.pendingFullHistoryGeneration = (
      historyRequest.pendingGeneration
    );
    state.pollingGeneration = generation;
    state.pollingSessionId = sessionId;
    clearPollTimer();
    const encodedSessionId = encodeURIComponent(sessionId);
    const after = historyRequest.fullHistory ? 0 : state.lastSeq;
    try {
      const results = await Promise.all([
        request("/api/collaboration/sessions/" + encodedSessionId),
        request(
          "/api/collaboration/sessions/"
          + encodedSessionId
          + "/events?after="
          + String(after),
        ),
      ]);
      if (!isCurrentPoll(identity)) {
        return;
      }
      state.session = results[0];
      if (historyRequest.fullHistory) {
        state.lastSeq = 0;
        state.lastSpeakerId = null;
        els.transcript.replaceChildren();
      }
      appendEvents(results[1].events);
    } catch (error) {
      if (isCurrentPoll(identity)) {
        reportError(error);
      }
    } finally {
      if (!isCurrentPoll(identity)) {
        return;
      }
      releasePoll(identity);
      renderSession();
      if (
        !document.hidden
        && state.pendingFullHistoryGeneration === generation
      ) {
        refreshSession(false);
        return;
      }
      schedulePoll();
    }
  }

  async function startDiscussion() {
    if (state.actionPending) {
      return;
    }
    const agentIds = selectedIds();
    if (agentIds.length < 2) {
      notify("collaboration.validation_members", {}, true);
      return;
    }
    const payload = core.discussionPayload(
      agentIds,
      els.topic.value,
      els.rounds.value,
    );
    if (
      !Number.isInteger(payload.max_rounds)
      || payload.max_rounds < 3
      || payload.max_rounds > 20
    ) {
      notify("collaboration.validation_rounds", {}, true);
      return;
    }
    const previousSession = state.session;
    const generation = invalidatePolling();
    state.session = null;
    renderSession();
    setBusy(els.startDiscussionBtn, true);
    try {
      const session = await request(
        "/api/collaboration/sessions",
        {
          method: "POST",
          body: JSON.stringify(payload),
        },
      );
      if (generation !== state.sessionGeneration) {
        return;
      }
      state.session = session;
      state.lastSeq = 0;
      state.lastSpeakerId = null;
      els.transcript.replaceChildren();
      renderEmptyTranscript();
      renderSession();
      notify("collaboration.discussion_created", {
        id: state.session.id,
      });
      await refreshSession(false);
    } catch (error) {
      if (generation === state.sessionGeneration) {
        state.session = previousSession;
        renderSession();
        schedulePoll();
        reportError(error);
      }
    } finally {
      setBusy(els.startDiscussionBtn, false);
      renderSelectionState();
    }
  }

  function actionIdentity(
    generation,
    sessionId,
    actionGeneration,
    action,
  ) {
    return {
      generation,
      sessionId,
      actionGeneration,
      action,
    };
  }

  function isCurrentAction(identity) {
    return core.isCurrentAction(state.actionPending, identity)
      && isCurrentPoll(identity);
  }

  function releaseAction(identity) {
    state.actionPending = core.releaseCurrentAction(
      state.actionPending,
      identity,
    );
  }

  async function changeSession(action) {
    if (!state.session || state.actionPending) {
      return;
    }
    const sessionId = String(state.session.id);
    const generation = invalidatePolling();
    state.actionGeneration += 1;
    const identity = actionIdentity(
      generation,
      sessionId,
      state.actionGeneration,
      action,
    );
    state.actionPending = identity;
    renderSession();
    renderSelectionState();
    try {
      const encodedSessionId = encodeURIComponent(sessionId);
      const session = await request(
        "/api/collaboration/sessions/"
        + encodedSessionId
        + "/"
        + action,
        {
          method: "POST",
          body: "{}",
        },
      );
      if (!isCurrentAction(identity)) {
        return;
      }
      state.session = session;
      releaseAction(identity);
      renderSession();
      renderSelectionState();
      notify("collaboration.action_" + action);
      schedulePoll();
    } catch (error) {
      if (!isCurrentAction(identity)) {
        return;
      }
      releaseAction(identity);
      renderSession();
      renderSelectionState();
      reportError(error);
      schedulePoll();
    }
  }

  function refreshLocale() {
    renderMembers();
    renderFriendship();
    renderNotice();
    renderSession();
    const empty = els.transcript.querySelector(
      "[data-empty-transcript]",
    );
    if (empty) {
      empty.textContent = translate("collaboration.empty_transcript");
    }
  }

  function bindEvents() {
    els.makeFriendsBtn.addEventListener("click", makeFriends);
    els.startDiscussionBtn.addEventListener("click", startDiscussion);
    els.pauseBtn.addEventListener("click", function () {
      changeSession("pause");
    });
    els.resumeBtn.addEventListener("click", function () {
      changeSession("resume");
    });
    els.cancelBtn.addEventListener("click", function () {
      changeSession("cancel");
    });
    els.historyBtn.addEventListener("click", function () {
      refreshSession(true);
    });
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        clearPollTimer();
      } else if (
        !state.actionPending
        && (
          state.pendingFullHistoryGeneration === state.sessionGeneration
          || core.shouldPoll(state.session)
        )
      ) {
        refreshSession(false);
      }
    });
    document.addEventListener("locale-changed", refreshLocale);
  }

  function init() {
    const panel = document.getElementById("collaborationPanel");
    if (!panel) {
      return;
    }
    els.members = document.getElementById("collaborationMembers");
    els.selectionCount = document.getElementById(
      "collaborationSelectionCount",
    );
    els.makeFriendsBtn = document.getElementById("makeFriendsBtn");
    els.friendship = document.getElementById("collaborationFriendship");
    els.topic = document.getElementById("collaborationTopic");
    els.rounds = document.getElementById("collaborationRounds");
    els.startDiscussionBtn = document.getElementById(
      "startDiscussionBtn",
    );
    els.notice = document.getElementById("collaborationNotice");
    els.status = document.getElementById("collaborationStatus");
    els.round = document.getElementById("collaborationRound");
    els.speaker = document.getElementById("collaborationSpeaker");
    els.transcript = document.getElementById(
      "collaborationTranscript",
    );
    els.pauseBtn = document.getElementById("pauseDiscussionBtn");
    els.resumeBtn = document.getElementById("resumeDiscussionBtn");
    els.cancelBtn = document.getElementById("cancelDiscussionBtn");
    els.historyBtn = document.getElementById("fullHistoryBtn");

    bindEvents();
    renderFriendship();
    renderNotice();
    renderSession();
    renderEmptyTranscript();
    renderSelectionState();
    loadAgents();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
}());
