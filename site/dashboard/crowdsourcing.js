/* Page controller for the swarm-crowdsourcing pane (#paneCrowd).
 *
 * Mirrors the sibling cooperation page: the same fetch/JSON helper, the same
 * generation-guarded polling, the same DOM-only rendering (every node is
 * built with createElement/textContent, never from a markup string). Every
 * element lookup is optional -- the pane may be embedded
 * where the crowdsourcing markup is absent, and a missing node must never
 * take the page down.
 */
(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.GAWorldCrowdsourcingPage = api;
  }
  if (root && root.document) {
    api.boot();
  }
}(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  /* The page is required headlessly by the front-end tests, where i18n.js is
   * not loaded. Delegate to the globals when they exist and fall back to the
   * key, exactly like the sibling cooperation page does. */
  const t = (key) => (typeof __ === "function" ? __(key) : key);
  const tf = (key, params) => (typeof __f === "function" ? __f(key, params) : key);

  const STRATEGY_LABEL_KEYS = {
    market: "crowd.strategy_market",
    vote: "crowd.strategy_vote",
    elite: "crowd.strategy_elite",
    debate: "crowd.strategy_debate",
  };

  const STRATEGY_DESC_KEYS = {
    market: "crowd.strategy_market_desc",
    vote: "crowd.strategy_vote_desc",
    elite: "crowd.strategy_elite_desc",
    debate: "crowd.strategy_debate_desc",
  };

  /* Used when /api/crowdsourcing/strategies is unreachable: the four
   * mechanisms are fixed, only their copy comes from the API. */
  const FALLBACK_STRATEGIES = [
    {id: "market", source: "https://arxiv.org/abs/2610.22322"},
    {id: "vote"},
    {id: "elite"},
    {id: "debate"},
  ];

  const DEFAULT_LIMITS = {
    max_pool_size: 200,
    max_rounds: 8,
    max_participants_per_round: 32,
    max_keep: 200,
  };

  const DEFAULT_PRUNE = {
    enabled: true,
    keep: 8,
    explore_ratio: 0.25,
  };

  const POLL_INTERVAL_MS = 1000;

  function setText(element, value) {
    if (!element) {
      return;
    }
    element.textContent = value === null || value === undefined
      ? ""
      : String(value);
  }

  function clearElement(element) {
    if (!element) {
      return;
    }
    element.replaceChildren();
  }

  function formatNumber(value, digits) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return "";
    }
    return number.toFixed(digits === undefined ? 2 : digits);
  }

  function formatPercent(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return "";
    }
    return String(Math.round(number <= 1 ? number * 100 : number)) + "%";
  }

  function isHttpUrl(value) {
    return /^https?:\/\//i.test(String(value || ""));
  }

  /* Artifact links are same-origin relative paths that must name the session
   * they belong to and must not walk out of it. */
  function safeArtifactUrl(rawUrl, sessionId) {
    const url = String(rawUrl || "").trim();
    const id = String(sessionId || "");
    if (!url || !id) {
      return null;
    }
    if (!url.startsWith("/") || url.startsWith("//")) {
      return null;
    }
    if (url.includes("\\") || url.includes("..")) {
      return null;
    }
    if (/%2e|%2f|%5c/i.test(url)) {
      return null;
    }
    if (/[\u0000-\u001f\u007f]/.test(url)) {
      return null;
    }
    if (url.indexOf(id) === -1) {
      return null;
    }
    return url;
  }

  function boot() {
    const scope = typeof window !== "undefined" ? window : globalThis;
    if (!scope.document) {
      return;
    }
    const core = scope.GAWorldCrowdsourcingCore;
    if (!core) {
      return;
    }
    /* Captured locally so the controller can also be driven by a stub DOM
     * in a head-less test. */
    const document = scope.document;

    const state = {
      strategies: [],
      defaults: {},
      limits: Object.assign({}, DEFAULT_LIMITS),
      strategy: "market",
      agents: [],
      agentDetails: new Map(),
      detailLoading: new Set(),
      selected: new Set(),
      sessions: [],
      session: null,
      rounds: [],
      expanded: new Set(),
      generation: 0,
      lastSeq: 0,
      pollTimer: null,
      polling: null,
      actionGeneration: 0,
      actionPending: null,
      creating: false,
      listGeneration: 0,
      poolNotice: "",
      formStatus: {message: "", error: false},
    };

    const els = {};

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
      if (!response.ok || payload.error) {
        throw new Error(String(payload.error || "HTTP " + response.status));
      }
      return payload;
    }

    function setFormStatus(message, error) {
      state.formStatus = {
        message: String(message || ""),
        error: Boolean(error),
      };
      if (!els.formStatus) {
        return;
      }
      els.formStatus.textContent = state.formStatus.message;
      els.formStatus.classList.toggle("is-error", state.formStatus.error);
    }

    function syncFormStatus() {
      if (state.formStatus.error) {
        return;
      }
      if (state.creating) {
        setFormStatus(t("crowd.form_status_running"), false);
        return;
      }
      const task = String(els.taskInput ? els.taskInput.value : "").trim();
      if (!task || state.selected.size < 2) {
        setFormStatus(t("crowd.form_status_select"), false);
        return;
      }
      setFormStatus(t("crowd.form_status_ready"), false);
    }

    function clearPollTimer() {
      if (state.pollTimer !== null) {
        scope.clearTimeout(state.pollTimer);
        state.pollTimer = null;
      }
    }

    function identity(generation, sessionId) {
      return {generation: generation, sessionId: sessionId};
    }

    function currentIdentity() {
      return identity(
        state.generation,
        state.session ? state.session.id : null,
      );
    }

    function isCurrent(candidate) {
      const current = currentIdentity();
      return Boolean(
        current
        && candidate
        && current.generation === candidate.generation
        && String(current.sessionId) === String(candidate.sessionId)
      );
    }

    function invalidateSession() {
      clearPollTimer();
      state.generation += 1;
      state.polling = null;
      state.actionPending = null;
      return state.generation;
    }

    function agentFor(agentId) {
      const wanted = Number(agentId);
      return state.agents.find(function (agent) {
        return Number(agent.id) === wanted;
      });
    }

    function agentName(agentId) {
      const agent = agentFor(agentId);
      const name = agent ? String(agent.name || "") : "";
      const id = Number(agentId);
      return name ? "#" + id + " " + name : "#" + id;
    }

    function jobLabel(agentId) {
      const detail = state.agentDetails.get(Number(agentId));
      if (!detail) {
        return "";
      }
      const capabilities = detail.capabilities || {};
      const card = detail.agent_card || {};
      return String(capabilities.job_label || card.job_label || "");
    }

    function loadAgentDetail(agentId) {
      const id = Number(agentId);
      if (!Number.isInteger(id) || id <= 0) {
        return;
      }
      if (state.agentDetails.has(id) || state.detailLoading.has(id)) {
        return;
      }
      state.detailLoading.add(id);
      request("/api/agents/" + encodeURIComponent(String(id)) + "/detail")
        .then(function (detail) {
          state.agentDetails.set(id, detail || {});
        })
        .catch(function () {
          state.agentDetails.set(id, {});
        })
        .finally(function () {
          state.detailLoading.delete(id);
          renderPool();
          renderAttempts();
        });
    }

    function limits() {
      return Object.assign({}, DEFAULT_LIMITS, state.limits || {});
    }

    function maxPoolSize() {
      return Math.max(1, Math.round(Number(limits().max_pool_size) || 1));
    }

    function numberFrom(input, fallback, min, max) {
      const value = Number(input && input.value);
      if (!Number.isFinite(value)) {
        return fallback;
      }
      return core.clamp(Math.round(value), min, max);
    }

    function roundsValue() {
      return numberFrom(els.rounds, 1, 1, limits().max_rounds);
    }

    function participantsValue() {
      return numberFrom(
        els.participants,
        1,
        1,
        limits().max_participants_per_round,
      );
    }

    function keepValue() {
      return numberFrom(els.keep, DEFAULT_PRUNE.keep, 1, limits().max_keep);
    }

    function selectedIds() {
      return core.normalizeAgentIds(Array.from(state.selected));
    }

    /* -- strategies ---------------------------------------------------- */

    function normalizeStrategy(raw) {
      if (!raw || typeof raw !== "object") {
        return null;
      }
      const id = String(raw.id || "").trim();
      if (!id) {
        return null;
      }
      return {
        id: id,
        name: String(raw.name || ""),
        name_en: String(raw.name_en || ""),
        summary: String(raw.summary || ""),
        source: String(raw.source || ""),
        mechanics: Array.isArray(raw.mechanics) ? raw.mechanics.slice() : [],
      };
    }

    function strategyLabel(strategyId, fallbackText) {
      const id = String(strategyId || "").trim();
      const key = STRATEGY_LABEL_KEYS[id];
      return key ? t(key) : String(fallbackText || id);
    }

    function strategyDesc(strategyId, fallbackText) {
      const id = String(strategyId || "").trim();
      const key = STRATEGY_DESC_KEYS[id];
      return key ? t(key) : String(fallbackText || "");
    }

    function renderStrategies() {
      const grid = els.strategyGrid;
      if (!grid) {
        return;
      }
      clearElement(grid);
      const list = state.strategies.length
        ? state.strategies
        : FALLBACK_STRATEGIES.map(normalizeStrategy);
      list.forEach(function (strategy) {
        const active = strategy.id === state.strategy;
        const card = document.createElement("div");
        card.className = "crowd-strategy-card";
        card.classList.toggle("is-active", active);
        card.setAttribute("role", "radio");
        card.setAttribute("aria-checked", String(active));
        card.setAttribute("tabindex", active ? "0" : "-1");
        card.dataset.strategy = strategy.id;

        const name = document.createElement("strong");
        name.className = "crowd-strategy-name";
        name.textContent = strategyLabel(strategy.id, strategy.name);
        card.appendChild(name);

        if (strategy.name_en) {
          const english = document.createElement("span");
          english.className = "crowd-strategy-en";
          english.textContent = strategy.name_en;
          card.appendChild(english);
        }

        const desc = document.createElement("span");
        desc.className = "crowd-strategy-desc";
        desc.textContent = strategyDesc(strategy.id, strategy.summary);
        card.appendChild(desc);

        if (strategy.id === "market" && isHttpUrl(strategy.source)) {
          const link = document.createElement("a");
          link.className = "crowd-strategy-source";
          link.href = strategy.source;
          link.target = "_blank";
          link.rel = "noopener";
          link.textContent = t("crowd.source_market");
          link.addEventListener("click", function (event) {
            event.stopPropagation();
          });
          card.appendChild(link);
        }

        function choose() {
          selectStrategy(strategy.id);
        }
        card.addEventListener("click", choose);
        card.addEventListener("keydown", function (event) {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            choose();
          }
        });
        grid.appendChild(card);
      });
    }

    function selectStrategy(strategyId) {
      if (state.creating || state.actionPending) {
        return;
      }
      state.strategy = String(strategyId || "market");
      renderStrategies();
      renderCost();
    }

    async function loadStrategies() {
      try {
        const payload = await request("/api/crowdsourcing/strategies");
        const list = Array.isArray(payload.strategies) ? payload.strategies : [];
        const normalized = list.map(normalizeStrategy).filter(Boolean);
        if (!normalized.length) {
          throw new Error("no strategies returned");
        }
        state.strategies = normalized;
        state.defaults = payload.defaults && typeof payload.defaults === "object"
          ? payload.defaults
          : {};
        state.limits = Object.assign({}, DEFAULT_LIMITS, payload.limits || {});
        applyDefaults();
        renderStrategies();
        syncFormStatus();
      } catch (error) {
        state.strategies = FALLBACK_STRATEGIES.map(normalizeStrategy);
        renderStrategies();
        setFormStatus(
          error && error.message ? error.message : t("crowd.form_status_error"),
          true,
        );
      }
    }

    function applyDefaults() {
      const defaults = state.defaults || {};
      if (els.rounds && defaults.rounds !== undefined) {
        els.rounds.value = String(core.clamp(
          Math.round(Number(defaults.rounds) || 1),
          1,
          limits().max_rounds,
        ));
      }
      if (els.participants && defaults.participants_per_round !== undefined) {
        els.participants.value = String(core.clamp(
          Math.round(Number(defaults.participants_per_round) || 1),
          1,
          limits().max_participants_per_round,
        ));
      }
      if (els.keep && defaults.keep !== undefined) {
        els.keep.value = String(core.clamp(
          Math.round(Number(defaults.keep) || DEFAULT_PRUNE.keep),
          1,
          limits().max_keep,
        ));
      }
      if (defaults.strategy && STRATEGY_LABEL_KEYS[defaults.strategy]) {
        state.strategy = String(defaults.strategy);
      }
    }

    /* -- pool ---------------------------------------------------------- */

    function filteredAgents() {
      const raw = String(els.poolSearch ? els.poolSearch.value : "").trim().toLowerCase();
      if (!raw) {
        return state.agents.slice();
      }
      return state.agents.filter(function (agent) {
        const id = String(agent.id);
        const name = String(agent.name || "").toLowerCase();
        return id === raw || id.indexOf(raw) !== -1 || name.indexOf(raw) !== -1;
      });
    }

    function renderPool() {
      const grid = els.poolGrid;
      if (!grid) {
        return;
      }
      clearElement(grid);
      const list = filteredAgents();
      if (!list.length) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = state.agents.length
          ? t("crowd.emptypool")
          : t("crowd.no_pool");
        grid.appendChild(empty);
        return;
      }
      const locked = state.creating || Boolean(state.actionPending);
      list.forEach(function (agent) {
        const agentId = Number(agent.id);
        const selected = state.selected.has(agentId);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "crowd-pool-chip";
        button.classList.toggle("is-selected", selected);
        button.setAttribute("aria-pressed", String(selected));
        button.disabled = locked;

        const id = document.createElement("span");
        id.className = "crowd-pool-id";
        id.textContent = "#" + String(agentId);
        const name = document.createElement("strong");
        name.className = "crowd-pool-name";
        name.textContent = String(agent.name || "");
        button.append(id, name);

        const job = jobLabel(agentId);
        if (job) {
          const label = document.createElement("span");
          label.className = "crowd-pool-job";
          label.textContent = job;
          button.appendChild(label);
        }

        button.addEventListener("click", function () {
          toggleAgent(agentId);
        });
        grid.appendChild(button);
      });
    }

    function toggleAgent(agentId) {
      if (state.creating || state.actionPending) {
        return;
      }
      if (state.selected.has(agentId)) {
        state.selected.delete(agentId);
      } else {
        const cap = maxPoolSize();
        if (state.selected.size >= cap) {
          state.poolNotice = tf("crowd.pool_cap", {n: cap});
          renderPoolNote();
          return;
        }
        state.selected.add(agentId);
      }
      state.poolNotice = "";
      renderPool();
      renderComposer();
      syncFormStatus();
    }

    function selectAllAgents() {
      if (state.creating || state.actionPending) {
        return;
      }
      const cap = maxPoolSize();
      const list = filteredAgents().map(function (agent) {
        return Number(agent.id);
      });
      const picked = list.slice(0, cap);
      state.selected = new Set(picked);
      state.poolNotice = list.length > cap ? tf("crowd.pool_cap", {n: cap}) : "";
      renderPool();
      renderComposer();
      syncFormStatus();
    }

    function randomAgents() {
      if (state.creating || state.actionPending) {
        return;
      }
      const cap = maxPoolSize();
      const wanted = numberFrom(els.poolCount, 1, 1, cap);
      const pool = filteredAgents().map(function (agent) {
        return Number(agent.id);
      });
      const picked = core.randomSample(pool, wanted, Math.random);
      state.selected = new Set(picked);
      state.poolNotice = wanted > cap ? tf("crowd.pool_cap", {n: cap}) : "";
      renderPool();
      renderComposer();
      syncFormStatus();
    }

    function clearAgents() {
      if (state.creating || state.actionPending) {
        return;
      }
      state.selected = new Set();
      state.poolNotice = "";
      renderPool();
      renderComposer();
      syncFormStatus();
    }

    function renderPoolNote() {
      if (!els.poolNote) {
        return;
      }
      const parts = [tf("crowd.pool_selected", {count: state.selected.size})];
      const requested = participantsValue();
      const poolSize = state.selected.size;
      if (poolSize > 0 && requested > poolSize) {
        parts.push(tf("crowd.participants_cap", {n: limits().max_participants_per_round}));
      }
      if (state.poolNotice) {
        parts.push(state.poolNotice);
      }
      setText(els.poolNote, parts.join(" · "));
    }

    /* -- cost ---------------------------------------------------------- */

    function renderCost() {
      if (!els.costEstimate) {
        return;
      }
      const calls = core.estimateCalls({
        strategy: state.strategy,
        poolSize: state.selected.size,
        rounds: roundsValue(),
        participantsPerRound: Math.min(
          participantsValue(),
          state.selected.size || participantsValue(),
        ),
      });
      setText(els.costEstimate, tf("crowd.cost_calls", {count: calls}));
    }

    function renderStartButton() {
      if (!els.startBtn) {
        return;
      }
      const task = String(els.taskInput ? els.taskInput.value : "").trim();
      const locked = state.creating || Boolean(state.actionPending);
      els.startBtn.disabled = locked || !task || state.selected.size < 2;
      els.startBtn.classList.toggle("busy", state.creating);
      const label = els.startBtn.querySelector("span");
      if (label) {
        label.textContent = state.creating
          ? t("crowd.starting")
          : t("crowd.start");
      }
    }

    function renderComposer() {
      renderStartButton();
      renderCost();
      renderPoolNote();
    }

    /* -- session list -------------------------------------------------- */

    function renderSessionList() {
      const list = els.sessionList;
      if (!list) {
        return;
      }
      clearElement(list);
      if (!state.sessions.length) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = t("crowd.no_sessions");
        list.appendChild(empty);
        return;
      }
      const locked = state.creating || Boolean(state.actionPending);
      state.sessions.forEach(function (session) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "session-entry";
        button.classList.toggle(
          "is-active",
          Boolean(state.session && state.session.id === session.id),
        );
        button.disabled = locked;
        const title = document.createElement("strong");
        title.textContent = String(session.task || session.title || session.id);
        const meta = document.createElement("span");
        meta.textContent = t(core.formatStatus(session.status))
          + " · "
          + String(session.id || "");
        button.append(title, meta);
        button.addEventListener("click", function () {
          openSession(session);
        });
        list.appendChild(button);
      });
    }

    /* -- activity feed ------------------------------------------------- */

    function renderEmptyActivity() {
      const feed = els.activityFeed;
      if (!feed || feed.childElementCount) {
        return;
      }
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.dataset.activityEmpty = "true";
      empty.textContent = t("crowd.awaiting");
      feed.appendChild(empty);
    }

    function roundIndexOf(metadata) {
      const candidates = [
        metadata.round,
        metadata.round_index,
        metadata.index,
        metadata.current_round,
      ];
      for (let index = 0; index < candidates.length; index += 1) {
        const number = Number(candidates[index]);
        if (Number.isFinite(number) && number > 0) {
          return Math.round(number);
        }
      }
      return null;
    }

    function activityEntry(event) {
      const type = String(event && event.type || "event");
      const metadata = (event && event.metadata) || {};
      const content = String(event && event.content || "");
      const rawAgentId = event ? event.agent_id : null;
      const hasAgent = rawAgentId !== null && rawAgentId !== undefined;
      const agentId = hasAgent ? Number(rawAgentId) : null;
      const speaker = hasAgent && Number.isFinite(agentId)
        ? agentName(agentId)
        : "GAWorld";
      const roundIndex = roundIndexOf(metadata);

      let action = content;
      let detail = "";

      if (!action) {
        if (type === "round_started" || type === "round_finished") {
          action = roundIndex
            ? tf("crowd.round_n", {n: roundIndex})
            : t("crowd.progress");
        } else if (type === "bid") {
          action = t("crowd.bid");
        } else if (type === "attempt") {
          action = t("crowd.agent");
        } else if (type === "scored") {
          action = t("crowd.score");
        } else if (type === "pruned") {
          action = t("crowd.prune_action");
        } else if (type === "final") {
          action = t("crowd.final_title");
        } else if (type === "paused") {
          action = t("crowd.pause");
        } else if (type === "resumed") {
          action = t("crowd.resume");
        } else if (type === "cancelled") {
          action = t("crowd.cancel");
        } else if (type === "error") {
          action = t("crowd.form_status_error");
        } else {
          action = type.toUpperCase();
        }
      }

      if (type === "bid") {
        const value = metadata.value !== undefined ? metadata.value : metadata.bid;
        const confidence = metadata.confidence;
        detail = [
          value === undefined ? "" : t("crowd.bid") + " " + formatNumber(value),
          confidence === undefined
            ? ""
            : t("crowd.confidence") + " " + formatPercent(confidence),
        ].filter(Boolean).join(" · ");
      } else if (type === "scored") {
        const score = metadata.score !== undefined ? metadata.score : metadata.value;
        detail = score === undefined ? "" : t("crowd.score") + " " + formatNumber(score);
      } else if (type === "pruned") {
        const survivors = Array.isArray(metadata.survivors)
          ? metadata.survivors.length
          : null;
        detail = survivors === null
          ? ""
          : tf("crowd.survivors", {count: survivors});
      } else if (type === "round_started" || type === "round_finished") {
        const method = metadata.method ? t(core.formatMethod(metadata.method)) : "";
        const agreement = metadata.agreement;
        detail = [
          roundIndex ? tf("crowd.round_n", {n: roundIndex}) : "",
          method,
          agreement === undefined
            ? ""
            : tf("crowd.agreement", {n: formatPercent(agreement)}),
        ].filter(Boolean).join(" · ");
      } else if (type === "created") {
        detail = strategyLabel(state.strategy);
      } else if (type === "final") {
        detail = metadata.agent_id
          ? tf("crowd.final_from", {name: agentName(metadata.agent_id)})
          : "";
      }

      return {
        type: type,
        speaker: speaker,
        action: action,
        detail: detail,
      };
    }

    function appendEvents(events) {
      const feed = els.activityFeed;
      if (!feed) {
        return;
      }
      const pinned = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 40;
      (Array.isArray(events) ? events : []).forEach(function (event) {
        const sequence = Number(event && event.seq || 0);
        if (sequence <= state.lastSeq) {
          return;
        }
        state.lastSeq = sequence;
        const placeholder = feed.querySelector("[data-activity-empty]");
        if (placeholder) {
          placeholder.remove();
        }
        const entry = activityEntry(event);
        const item = document.createElement("article");
        item.className = "activity-event";
        item.dataset.eventType = entry.type;
        const time = document.createElement("time");
        time.textContent = "#" + String(sequence).padStart(4, "0");
        const body = document.createElement("div");
        const head = document.createElement("div");
        head.className = "activity-speaker";
        const speaker = document.createElement("strong");
        speaker.textContent = entry.speaker;
        head.appendChild(speaker);
        const action = document.createElement("p");
        action.className = "activity-action";
        action.textContent = entry.action;
        body.append(head, action);
        if (entry.detail) {
          const detail = document.createElement("p");
          detail.className = "activity-detail";
          detail.textContent = entry.detail;
          body.appendChild(detail);
        }
        item.append(time, body);
        feed.appendChild(item);
      });
      setText(els.eventCursor, "SEQ " + String(state.lastSeq).padStart(4, "0"));
      renderEmptyActivity();
      if (pinned) {
        feed.scrollTop = feed.scrollHeight;
      }
    }

    function resetActivity() {
      state.lastSeq = 0;
      clearElement(els.activityFeed);
      setText(els.eventCursor, "SEQ 0000");
      renderEmptyActivity();
    }

    /* -- workspace ----------------------------------------------------- */

    function currentRound() {
      const session = state.session;
      const index = Number(session && session.current_round) || 0;
      const rounds = state.rounds.map(core.summarizeRound);
      if (!rounds.length) {
        return null;
      }
      if (index > 0) {
        const found = rounds.find(function (round) {
          return round.index === index;
        });
        if (found) {
          return found;
        }
      }
      return rounds[rounds.length - 1];
    }

    function lastSummary() {
      const session = state.session;
      const summaries = session && Array.isArray(session.round_summaries)
        ? session.round_summaries
        : [];
      return summaries.length ? summaries[summaries.length - 1] : null;
    }

    function winnerAgentId() {
      const round = currentRound();
      if (round && round.winner_agent_id) {
        return round.winner_agent_id;
      }
      const summary = lastSummary();
      const fromSummary = summary
        ? Number(summary.aggregated_agent_id || 0)
        : 0;
      if (fromSummary) {
        return fromSummary;
      }
      const session = state.session;
      return Number(session && session.final_agent_id) || 0;
    }

    function survivors() {
      const summary = lastSummary();
      if (!summary || !Array.isArray(summary.survivors)) {
        return null;
      }
      return new Set(summary.survivors.map(Number));
    }

    function renderHeader() {
      const session = state.session;
      setText(els.status, session
        ? t(core.formatStatus(session.status))
        : t("crowd.awaiting"));
      setText(els.sessionCode, session
        ? String(session.id)
        : "NO ACTIVE SESSION");
      setText(els.activeTitle, session
        ? String(session.task || session.title || session.id)
        : t("crowd.pick_or_start"));
    }

    function renderActions() {
      const session = state.session;
      const status = String(session && session.status || "");
      const locked = state.creating || Boolean(state.actionPending);
      if (els.pauseBtn) {
        els.pauseBtn.hidden = status !== "running";
      }
      if (els.resumeBtn) {
        els.resumeBtn.hidden = !["paused", "failed", "interrupted"].includes(status);
      }
      if (els.cancelBtn) {
        els.cancelBtn.hidden = !session || ["completed", "cancelled"].includes(status);
      }
      [els.pauseBtn, els.resumeBtn, els.cancelBtn].forEach(function (button) {
        if (!button) {
          return;
        }
        button.disabled = locked;
        button.classList.toggle(
          "busy",
          Boolean(
            state.actionPending
            && state.actionPending.action === button.dataset.action
          ),
        );
      });
    }

    function renderProgress() {
      const session = state.session;
      const total = Number(session && session.rounds) || 0;
      const current = Number(session && session.current_round) || 0;
      const percent = total > 0
        ? Math.round((Math.min(current, total) / total) * 100)
        : 0;
      setText(els.progressText, current + " / " + total);
      if (els.progress) {
        els.progress.setAttribute("aria-valuenow", String(percent));
      }
      if (els.progressBar) {
        els.progressBar.style.width = String(percent) + "%";
      }
    }

    function renderRoundStrip() {
      const strip = els.roundStrip;
      if (!strip) {
        return;
      }
      clearElement(strip);
      const session = state.session;
      const summaries = session && Array.isArray(session.round_summaries)
        ? session.round_summaries
        : [];
      const total = Number(session && session.rounds) || 0;
      if (!summaries.length && !total) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = t("crowd.no_rounds");
        strip.appendChild(empty);
        return;
      }
      const current = Number(session && session.current_round) || 0;
      const count = Math.max(summaries.length, total);
      for (let index = 1; index <= count; index += 1) {
        const summary = summaries.find(function (item) {
          return Number(item.index) === index;
        }) || null;
        const chip = document.createElement("div");
        chip.className = "crowd-round-chip";
        chip.classList.toggle("is-current", index === current);
        chip.classList.toggle("is-done", Boolean(summary));
        chip.title = tf("crowd.round_of", {n: index, total: count});

        const number = document.createElement("strong");
        number.textContent = tf("crowd.round_n", {n: index});
        chip.appendChild(number);

        const method = document.createElement("span");
        method.className = "crowd-round-method";
        method.textContent = summary && summary.method
          ? t(core.formatMethod(summary.method))
          : "";
        chip.appendChild(method);

        const winner = summary
          ? Number(summary.aggregated_agent_id || summary.winner_agent_id || 0)
          : 0;
        if (winner) {
          const owner = document.createElement("span");
          owner.className = "crowd-round-winner";
          owner.textContent = agentName(winner);
          chip.appendChild(owner);
        }
        strip.appendChild(chip);
      }
    }

    function renderBids() {
      const table = els.bidTable;
      if (!table) {
        return;
      }
      clearElement(table);
      setText(els.clearingPrice, "");
      const session = state.session;
      const strategy = String(session && session.strategy || state.strategy);
      if (strategy !== "market") {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = t("crowd.method") + ": "
          + strategyLabel(strategy)
          + " · "
          + strategyDesc(strategy);
        table.appendChild(empty);
        return;
      }
      const round = currentRound();
      const bids = round ? round.bids : [];
      if (!bids.length) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = t("crowd.awaiting");
        table.appendChild(empty);
        return;
      }
      const grid = document.createElement("table");
      grid.className = "crowd-bid-grid";
      const head = document.createElement("thead");
      const headRow = document.createElement("tr");
      ["crowd.agent", "crowd.bid", "crowd.confidence", "crowd.reason"].forEach(
        function (key) {
          const cell = document.createElement("th");
          cell.textContent = t(key);
          headRow.appendChild(cell);
        },
      );
      head.appendChild(headRow);
      const body = document.createElement("tbody");
      const selected = round && Array.isArray(round.selected) ? round.selected : [];
      bids.forEach(function (bid) {
        const row = document.createElement("tr");
        row.classList.toggle("is-winner", selected.includes(bid.agent_id));
        const agent = document.createElement("td");
        agent.textContent = agentName(bid.agent_id);
        const value = document.createElement("td");
        value.className = "crowd-num";
        value.textContent = formatNumber(bid.value);
        const confidence = document.createElement("td");
        confidence.className = "crowd-num";
        confidence.textContent = formatPercent(bid.confidence);
        const reason = document.createElement("td");
        reason.className = "crowd-reason";
        reason.textContent = bid.reason;
        row.append(agent, value, confidence, reason);
        body.appendChild(row);
      });
      grid.append(head, body);
      table.appendChild(grid);

      if (round && round.clearingPrice !== null && round.clearingPrice !== undefined) {
        setText(
          els.clearingPrice,
          tf("crowd.clearing_price", {n: formatNumber(round.clearingPrice)}),
        );
      }
    }

    function renderAttempts() {
      const list = els.attemptList;
      if (!list) {
        return;
      }
      clearElement(list);
      const round = currentRound();
      const attempts = round ? round.attempts : [];
      if (!attempts.length) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = t("crowd.awaiting");
        list.appendChild(empty);
        return;
      }
      const winner = winnerAgentId();
      attempts.forEach(function (attempt) {
        // The job label only shows up for residents the run actually put to
        // work, so their details are fetched here -- lazily and cached.
        loadAgentDetail(attempt.agent_id);
        const card = document.createElement("article");
        card.className = "crowd-attempt-card";
        const isWinner = winner === attempt.agent_id;
        card.classList.toggle("is-winner", isWinner);

        const head = document.createElement("header");
        head.className = "crowd-attempt-head";
        const who = document.createElement("strong");
        who.textContent = agentName(attempt.agent_id);
        head.appendChild(who);
        const job = jobLabel(attempt.agent_id);
        if (job) {
          const label = document.createElement("span");
          label.className = "crowd-attempt-job";
          label.textContent = job;
          head.appendChild(label);
        }
        const score = document.createElement("span");
        score.className = "crowd-attempt-score";
        score.textContent = t("crowd.score") + " "
          + formatNumber(attempt.score);
        head.appendChild(score);
        const votes = (round.votes || []).find(function (item) {
          return item.agent_id === attempt.agent_id;
        });
        if (votes) {
          const tally = document.createElement("span");
          tally.className = "crowd-attempt-votes";
          tally.textContent = tf("crowd.votes", {n: formatNumber(votes.votes, 0)});
          head.appendChild(tally);
        }
        if (isWinner) {
          const badge = document.createElement("span");
          badge.className = "crowd-winner-badge";
          badge.textContent = t("crowd.winner");
          head.appendChild(badge);
        }
        card.appendChild(head);

        const answer = document.createElement("p");
        answer.className = "crowd-attempt-answer";
        answer.textContent = attempt.answer;
        card.appendChild(answer);

        if (attempt.answer.length > 220) {
          const toggle = document.createElement("button");
          toggle.type = "button";
          toggle.className = "crowd-attempt-toggle";
          const expanded = state.expanded.has(attempt.agent_id);
          card.classList.toggle("is-expanded", expanded);
          toggle.textContent = expanded
            ? t("crowd.collapse")
            : t("crowd.expand");
          toggle.addEventListener("click", function () {
            if (state.expanded.has(attempt.agent_id)) {
              state.expanded.delete(attempt.agent_id);
            } else {
              state.expanded.add(attempt.agent_id);
            }
            renderAttempts();
          });
          card.appendChild(toggle);
        }

        if (attempt.rationale) {
          const rationale = document.createElement("p");
          rationale.className = "crowd-attempt-rationale";
          rationale.textContent = t("crowd.rationale") + ": " + attempt.rationale;
          card.appendChild(rationale);
        }
        list.appendChild(card);
      });
    }

    function renderAgreement() {
      if (!els.agreement) {
        return;
      }
      const round = currentRound();
      const summary = lastSummary();
      const method = String(
        (round && round.method) || (summary && summary.method) || "",
      );
      const agreement = round && round.agreement !== null
        ? round.agreement
        : summary
          ? Number(summary.agreement)
          : null;
      if (agreement === null || !Number.isFinite(Number(agreement))) {
        setText(els.agreement, "");
        return;
      }
      if (method && !["vote", "market"].includes(method)) {
        setText(els.agreement, "");
        return;
      }
      setText(
        els.agreement,
        tf("crowd.agreement", {n: formatPercent(agreement)}),
      );
    }

    function renderLeaderboard() {
      const board = els.leaderboard;
      if (!board) {
        return;
      }
      clearElement(board);
      const session = state.session;
      const rows = session && Array.isArray(session.leaderboard)
        ? session.leaderboard
        : [];
      const alive = survivors();
      if (els.survivorCount) {
        setText(
          els.survivorCount,
          alive ? tf("crowd.survivors", {count: alive.size}) : "",
        );
      }
      if (!rows.length) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = t("crowd.awaiting");
        board.appendChild(empty);
        return;
      }
      const strategy = String(session && session.strategy || state.strategy);
      const market = strategy === "market";
      const grid = document.createElement("table");
      grid.className = "crowd-leaderboard-grid";
      const head = document.createElement("thead");
      const headRow = document.createElement("tr");
      const keys = ["crowd.rank", "crowd.agent", "crowd.credit", "crowd.rounds_acted"];
      if (market) {
        keys.push("crowd.bid_adjust");
      }
      keys.forEach(function (key) {
        const cell = document.createElement("th");
        cell.textContent = t(key);
        headRow.appendChild(cell);
      });
      head.appendChild(headRow);
      const body = document.createElement("tbody");
      rows.forEach(function (row) {
        const agentId = Number(row.agent_id);
        const eliminated = Boolean(alive) && !alive.has(agentId);
        const tr = document.createElement("tr");
        tr.classList.toggle("is-eliminated", eliminated);
        const rank = document.createElement("td");
        rank.className = "crowd-num";
        rank.textContent = String(row.rank === undefined ? "" : row.rank);
        const agent = document.createElement("td");
        agent.textContent = agentName(agentId);
        const credit = document.createElement("td");
        credit.className = "crowd-num";
        credit.textContent = formatNumber(row.credit);
        const acted = document.createElement("td");
        acted.className = "crowd-num";
        acted.textContent = String(row.rounds === undefined ? "" : row.rounds);
        tr.append(rank, agent, credit, acted);
        if (market) {
          const adjust = document.createElement("td");
          adjust.className = "crowd-num";
          adjust.textContent = formatNumber(row.bid_adjust);
          tr.appendChild(adjust);
        }
        body.appendChild(tr);
      });
      grid.append(head, body);
      board.appendChild(grid);
    }

    function renderFinal() {
      const box = els.finalAnswer;
      if (!box) {
        return;
      }
      clearElement(box);
      const session = state.session;
      const answer = String(session && session.final_answer || "").trim();
      if (!answer) {
        const pending = document.createElement("p");
        pending.className = "empty-state";
        pending.textContent = t("crowd.final_pending");
        box.appendChild(pending);
        return;
      }
      const text = document.createElement("p");
      text.className = "crowd-final-text";
      text.textContent = answer;
      box.appendChild(text);
      const finalAgent = Number(session.final_agent_id) || 0;
      if (finalAgent) {
        const from = document.createElement("p");
        from.className = "crowd-final-from";
        from.textContent = tf("crowd.final_from", {name: agentName(finalAgent)});
        box.appendChild(from);
      }
    }

    function artifactName(artifact) {
      if (artifact && artifact.filename) {
        return String(artifact.filename);
      }
      if (artifact && artifact.path) {
        const parts = String(artifact.path).split("/");
        return parts[parts.length - 1] || "artifact";
      }
      return "artifact";
    }

    function renderArtifacts() {
      const list = els.artifactList;
      if (!list) {
        return;
      }
      clearElement(list);
      const session = state.session;
      const artifacts = session && Array.isArray(session.artifacts)
        ? session.artifacts
        : [];
      if (!artifacts.length) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = t("crowd.final_pending");
        list.appendChild(empty);
        return;
      }
      artifacts.forEach(function (artifact) {
        const item = document.createElement("div");
        item.className = "artifact-item";
        const name = artifactName(artifact);
        const url = safeArtifactUrl(
          artifact && artifact.url,
          session ? session.id : "",
        );
        if (url) {
          const link = document.createElement("a");
          link.href = url;
          link.target = "_blank";
          link.rel = "noopener";
          link.textContent = name;
          item.appendChild(link);
          const save = document.createElement("a");
          save.className = "artifact-download";
          save.href = url;
          save.download = name;
          save.rel = "noopener";
          save.textContent = t("crowd.artifact_download");
          item.appendChild(save);
        } else {
          const label = document.createElement("span");
          label.textContent = name;
          item.appendChild(label);
        }
        list.appendChild(item);
      });
    }

    function renderCallCount() {
      const session = state.session;
      const stats = session && session.stats ? session.stats : {};
      const calls = Math.max(0, Math.round(Number(stats.calls) || 0));
      setText(els.callCount, tf("crowd.calls", {n: calls}));
      if (els.callCount) {
        const elapsed = Number(stats.elapsed_seconds);
        els.callCount.title = Number.isFinite(elapsed)
          ? tf("crowd.elapsed", {seconds: formatNumber(elapsed, 1)})
          : "";
      }
    }

    function renderWorkspace() {
      renderHeader();
      renderActions();
      renderProgress();
      renderRoundStrip();
      renderBids();
      renderAttempts();
      renderAgreement();
      renderLeaderboard();
      renderFinal();
      renderArtifacts();
      renderCallCount();
      renderSessionList();
      renderComposer();
    }

    /* -- polling ------------------------------------------------------- */

    function isTerminal(session) {
      return Boolean(
        session
        && ["completed", "cancelled"].includes(String(session.status))
      );
    }

    function schedulePoll() {
      clearPollTimer();
      if (
        document.hidden
        || state.creating
        || state.actionPending
        || !core.shouldPoll(state.session)
      ) {
        return;
      }
      state.pollTimer = scope.setTimeout(function () {
        refreshSession();
      }, POLL_INTERVAL_MS);
    }

    /**
     * Fetch a session's full detail: the session, the activity log and the
     * per-round records. This is what fills the workspace, and it has to
     * run for a finished session too -- polling stops once a run reaches a
     * terminal status, so opening it from the archive would otherwise show
     * an empty workspace.
     */
    async function loadSessionDetail(candidate) {
      const pending = state.polling;
      if (
        pending
        && pending.generation === candidate.generation
        && String(pending.sessionId) === String(candidate.sessionId)
      ) {
        return;
      }
      state.polling = candidate;
      clearPollTimer();
      const sessionId = encodeURIComponent(String(candidate.sessionId));
      try {
        const results = await Promise.all([
          request("/api/crowdsourcing/sessions/" + sessionId),
          request(
            "/api/crowdsourcing/sessions/"
            + sessionId
            + "/events?after="
            + String(state.lastSeq),
          ),
          request("/api/crowdsourcing/sessions/" + sessionId + "/rounds")
            .catch(function () {
              return null;
            }),
        ]);
        if (!isCurrent(candidate)) {
          return;
        }
        const wasTerminal = isTerminal(state.session);
        state.session = results[0];
        if (results[2] && Array.isArray(results[2].rounds)) {
          state.rounds = results[2].rounds;
        }
        appendEvents(results[1].events);
        renderWorkspace();
        if (!wasTerminal && isTerminal(state.session)) {
          loadSessions();
        }
      } catch (error) {
        if (isCurrent(candidate)) {
          setFormStatus(error.message, true);
        }
      } finally {
        if (!isCurrent(candidate)) {
          return;
        }
        state.polling = null;
        schedulePoll();
      }
    }

    async function refreshSession() {
      if (
        !state.session
        || document.hidden
        || state.creating
        || state.actionPending
      ) {
        return;
      }
      await loadSessionDetail(
        identity(state.generation, String(state.session.id)),
      );
    }

    async function loadSessions() {
      state.listGeneration += 1;
      const requestGeneration = state.listGeneration;
      if (els.refreshSessionsBtn) {
        els.refreshSessionsBtn.disabled = true;
      }
      try {
        const payload = await request("/api/crowdsourcing/sessions");
        if (requestGeneration !== state.listGeneration) {
          return;
        }
        state.sessions = Array.isArray(payload.sessions)
          ? payload.sessions.slice()
          : [];
        renderSessionList();
      } catch (error) {
        if (requestGeneration !== state.listGeneration) {
          return;
        }
        setFormStatus(error.message, true);
      } finally {
        if (requestGeneration !== state.listGeneration) {
          return;
        }
        if (els.refreshSessionsBtn) {
          els.refreshSessionsBtn.disabled = false;
        }
      }
    }

    async function loadAgents() {
      try {
        const payload = await request("/api/agents");
        state.agents = Array.isArray(payload.agents)
          ? payload.agents.slice()
          : [];
        renderPool();
        syncFormStatus();
      } catch (error) {
        state.agents = [];
        renderPool();
        setFormStatus(error.message, true);
      }
    }

    function openSession(session) {
      if (state.creating || state.actionPending) {
        return;
      }
      invalidateSession();
      state.session = session;
      state.rounds = [];
      state.expanded = new Set();
      resetActivity();
      renderWorkspace();
      // A finished session never polls, so the rounds, the bids and the
      // activity log have to be fetched right here.
      loadSessionDetail(identity(state.generation, String(session.id)));
    }

    async function startSession() {
      if (state.creating || state.actionPending) {
        return;
      }
      const task = String(els.taskInput ? els.taskInput.value : "").trim();
      const agentIds = selectedIds();
      if (agentIds.length < 2) {
        setFormStatus(t("crowd.select_at_least"), true);
        return;
      }
      if (!task) {
        setFormStatus(t("crowd.form_status_select"), true);
        return;
      }
      const previousSession = state.session;
      const generation = invalidateSession();
      state.creating = true;
      state.session = null;
      state.rounds = [];
      state.expanded = new Set();
      resetActivity();
      renderWorkspace();
      setFormStatus(t("crowd.form_status_running"), false);
      const payload = core.buildPayload({
        task: task,
        criteria: String(els.criteriaInput ? els.criteriaInput.value : ""),
        strategy: state.strategy,
        agentIds: agentIds,
        rounds: roundsValue(),
        participantsPerRound: Math.min(
          participantsValue(),
          agentIds.length,
        ),
        pruneEnabled: Boolean(els.pruneEnabled && els.pruneEnabled.checked),
        keep: keepValue(),
        exploreRatio: DEFAULT_PRUNE.explore_ratio,
      });
      try {
        const session = await request("/api/crowdsourcing/sessions", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        if (generation !== state.generation) {
          return;
        }
        state.creating = false;
        state.session = session;
        resetActivity();
        renderWorkspace();
        setFormStatus(t("crowd.form_status_running"), false);
        loadSessions();
        loadSessionDetail(identity(state.generation, String(session.id)));
      } catch (error) {
        if (generation !== state.generation) {
          return;
        }
        state.creating = false;
        state.session = previousSession;
        renderWorkspace();
        setFormStatus(error.message, true);
        schedulePoll();
      }
    }

    /* -- controls ------------------------------------------------------ */

    async function changeSession(action) {
      if (!state.session || state.creating || state.actionPending) {
        return;
      }
      const sessionId = String(state.session.id);
      const generation = invalidateSession();
      state.actionGeneration += 1;
      const candidate = {
        generation: generation,
        sessionId: sessionId,
        actionGeneration: state.actionGeneration,
        action: action,
      };
      state.actionPending = candidate;
      const busyBtn = action === "pause"
        ? els.pauseBtn
        : action === "resume" ? els.resumeBtn : els.cancelBtn;
      let release = null;
      if (busyBtn && typeof scope.setButtonBusy === "function") {
        release = scope.setButtonBusy(busyBtn, "", "处理中…");
      }
      renderWorkspace();
      try {
        const session = await request(
          "/api/crowdsourcing/sessions/"
          + encodeURIComponent(sessionId)
          + "/"
          + action,
          {method: "POST", body: "{}"},
        );
        if (!isCurrentAction(candidate)) {
          return;
        }
        state.session = session;
        state.actionPending = null;
        if (release) {
          release();
        }
        renderWorkspace();
        setFormStatus(t("crowd.form_status_ready"), false);
        loadSessions();
        schedulePoll();
      } catch (error) {
        if (!isCurrentAction(candidate)) {
          return;
        }
        state.actionPending = null;
        if (release) {
          release();
        }
        renderWorkspace();
        setFormStatus(error.message, true);
        schedulePoll();
      }
    }

    function isCurrentAction(candidate) {
      return Boolean(
        state.actionPending
        && candidate
        && state.actionPending.actionGeneration === candidate.actionGeneration
        && state.actionPending.action === candidate.action
        && isCurrent(candidate)
      );
    }

    /* -- wiring -------------------------------------------------------- */

    function bindEvents() {
      if (els.taskInput) {
        els.taskInput.addEventListener("input", function () {
          state.formStatus = {message: "", error: false};
          renderComposer();
          syncFormStatus();
        });
      }
      if (els.criteriaInput) {
        els.criteriaInput.addEventListener("input", function () {
          state.formStatus = {message: "", error: false};
          syncFormStatus();
        });
      }
      if (els.poolSearch) {
        els.poolSearch.addEventListener("input", renderPool);
      }
      if (els.poolAll) {
        els.poolAll.addEventListener("click", selectAllAgents);
      }
      if (els.poolRandom) {
        els.poolRandom.addEventListener("click", randomAgents);
      }
      if (els.poolClear) {
        els.poolClear.addEventListener("click", clearAgents);
      }
      [els.rounds, els.participants, els.keep].forEach(function (input) {
        if (!input) {
          return;
        }
        input.addEventListener("input", function () {
          state.formStatus = {message: "", error: false};
          renderComposer();
          syncFormStatus();
        });
      });
      if (els.pruneEnabled) {
        els.pruneEnabled.addEventListener("change", function () {
          state.formStatus = {message: "", error: false};
          renderComposer();
          syncFormStatus();
        });
      }
      if (els.startBtn) {
        els.startBtn.addEventListener("click", startSession);
      }
      if (els.refreshSessionsBtn) {
        els.refreshSessionsBtn.addEventListener("click", loadSessions);
      }
      if (els.pauseBtn) {
        els.pauseBtn.addEventListener("click", function () {
          changeSession("pause");
        });
      }
      if (els.resumeBtn) {
        els.resumeBtn.addEventListener("click", function () {
          changeSession("resume");
        });
      }
      if (els.cancelBtn) {
        els.cancelBtn.addEventListener("click", function () {
          changeSession("cancel");
        });
      }
      document.addEventListener("visibilitychange", function () {
        if (document.hidden) {
          clearPollTimer();
        } else if (
          state.session
          && !state.creating
          && !state.actionPending
        ) {
          // A run that reached its end while the tab sat in the background
          // still owes the workspace its last round.
          refreshSession();
        }
      });
    }

    function collectElements() {
      els.status = document.getElementById("crowdStatus");
      els.taskInput = document.getElementById("crowdTaskInput");
      els.criteriaInput = document.getElementById("crowdCriteriaInput");
      els.strategyGrid = document.getElementById("crowdStrategyGrid");
      els.poolSearch = document.getElementById("crowdPoolSearch");
      els.poolCount = document.getElementById("crowdPoolCount");
      els.poolAll = document.getElementById("crowdPoolAll");
      els.poolRandom = document.getElementById("crowdPoolRandom");
      els.poolClear = document.getElementById("crowdPoolClear");
      els.poolNote = document.getElementById("crowdPoolNote");
      els.poolGrid = document.getElementById("crowdPoolGrid");
      els.rounds = document.getElementById("crowdRounds");
      els.participants = document.getElementById("crowdParticipants");
      els.keep = document.getElementById("crowdKeep");
      els.pruneEnabled = document.getElementById("crowdPruneEnabled");
      els.costEstimate = document.getElementById("crowdCostEstimate");
      els.startBtn = document.getElementById("crowdStartBtn");
      els.formStatus = document.getElementById("crowdFormStatus");
      els.refreshSessionsBtn = document.getElementById("crowdRefreshSessionsBtn");
      els.sessionList = document.getElementById("crowdSessionList");
      els.sessionCode = document.getElementById("crowdSessionCode");
      els.activeTitle = document.getElementById("crowdActiveTitle");
      els.pauseBtn = document.getElementById("crowdPauseBtn");
      els.resumeBtn = document.getElementById("crowdResumeBtn");
      els.cancelBtn = document.getElementById("crowdCancelBtn");
      els.progressText = document.getElementById("crowdProgressText");
      els.progress = document.getElementById("crowdProgress");
      els.progressBar = document.getElementById("crowdProgressBar");
      els.roundStrip = document.getElementById("crowdRoundStrip");
      els.clearingPrice = document.getElementById("crowdClearingPrice");
      els.bidTable = document.getElementById("crowdBidTable");
      els.agreement = document.getElementById("crowdAgreement");
      els.attemptList = document.getElementById("crowdAttemptList");
      els.survivorCount = document.getElementById("crowdSurvivorCount");
      els.leaderboard = document.getElementById("crowdLeaderboard");
      els.eventCursor = document.getElementById("crowdEventCursor");
      els.activityFeed = document.getElementById("crowdActivityFeed");
      els.callCount = document.getElementById("crowdCallCount");
      els.finalAnswer = document.getElementById("crowdFinalAnswer");
      els.artifactList = document.getElementById("crowdArtifactList");
      if (els.pauseBtn) {
        els.pauseBtn.dataset.action = "pause";
      }
      if (els.resumeBtn) {
        els.resumeBtn.dataset.action = "resume";
      }
      if (els.cancelBtn) {
        els.cancelBtn.dataset.action = "cancel";
      }
    }

    function init() {
      collectElements();
      if (!els.strategyGrid && !els.formStatus && !els.poolGrid) {
        return;
      }
      bindEvents();
      renderWorkspace();
      renderStrategies();
      renderPool();
      renderEmptyActivity();
      setFormStatus(t("crowd.loading_roster"), false);
      Promise.all([loadStrategies(), loadAgents(), loadSessions()]);
    }

    /* The pane is drawn from JS, so a language switch has to redraw it. The
     * activity feed is left alone: its entries are a log of what happened at
     * the time, and rebuilding them would mean keeping the raw events around
     * only to re-translate history. */
    document.addEventListener("locale-changed", function () {
      if (!els.strategyGrid && !els.formStatus) {
        return;
      }
      renderStrategies();
      renderPool();
      renderWorkspace();
      syncFormStatus();
      const placeholder = els.activityFeed
        ? els.activityFeed.querySelector("[data-activity-empty]")
        : null;
      if (placeholder) {
        placeholder.remove();
        renderEmptyActivity();
      }
    });

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }

  return {
    boot: boot,
    safeArtifactUrl: safeArtifactUrl,
    formatPercent: formatPercent,
  };
}));
