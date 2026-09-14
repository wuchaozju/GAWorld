(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.GAWorldCooperationPage = api;
  }
  if (root && root.document) {
    api.boot();
  }
}(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  /* The page is required headlessly by tests/test_collaboration_frontend.py,
     where i18n.js is not loaded. Delegate to the globals when they exist and
     fall back to the key so the module stays importable either way; in the
     browser collaboration.html loads i18n.js first, so the globals are there. */
  const t = (key) => (typeof __ === "function" ? __(key) : key);
  const tf = (key, params) => (typeof __f === "function" ? __f(key, params) : key);

  function safeArtifactUrl(rawUrl, sessionId, baseHref, rawScope) {
    const cleanSessionId = String(sessionId || "");
    if (
      typeof rawUrl !== "string"
      || !rawUrl.trim()
      || typeof rawScope !== "string"
      || !rawScope.startsWith("/")
      || rawScope.startsWith("//")
      || !rawUrl.startsWith(rawScope)
      || !/^cs_[A-Za-z0-9_-]+$/.test(cleanSessionId)
      || rawScope.includes("\\")
      || /%2e|%2f|%5c/i.test(rawScope)
      || rawScope.split("/").some(function (segment) {
        return segment === "." || segment === "..";
      })
    ) {
      return null;
    }
    try {
      const base = new URL(baseHref);
      const scope = new URL(rawScope, base);
      const parsed = new URL(rawUrl, base);
      if (
        parsed.origin !== base.origin
        || parsed.username
        || parsed.password
        || parsed.search
        || parsed.hash
        || scope.origin !== base.origin
        || scope.username
        || scope.password
        || scope.search
        || scope.hash
      ) {
        return null;
      }
      const expectedSuffix = "/"
        + encodeURIComponent(cleanSessionId)
        + "/artifacts/";
      if (
        !scope.pathname.endsWith(expectedSuffix)
        || /%2e|%2f|%5c/i.test(scope.pathname)
        || !parsed.pathname.startsWith(scope.pathname)
      ) {
        return null;
      }
      const decodedScope = decodeURIComponent(scope.pathname);
      if (
        decodedScope.includes("\\")
        || decodedScope.split("/").some(function (segment) {
          return segment === "." || segment === "..";
        })
        || /[\u0000-\u001f\u007f]/.test(decodedScope)
      ) {
        return null;
      }
      const encodedFilename = parsed.pathname.slice(scope.pathname.length);
      if (
        !encodedFilename
        || encodedFilename.includes("/")
        || /%2f|%5c/i.test(encodedFilename)
      ) {
        return null;
      }
      const filename = decodeURIComponent(encodedFilename);
      if (
        !filename
        || filename === "."
        || filename === ".."
        || filename.includes("/")
        || filename.includes("\\")
        || /%2e|%2f|%5c/i.test(filename)
        || /[\u0000-\u001f\u007f]/.test(filename)
      ) {
        return null;
      }
      return parsed.pathname;
    } catch (_) {
      return null;
    }
  }

  function isLatestRequest(currentGeneration, requestGeneration) {
    return currentGeneration === requestGeneration;
  }

  function activityEntry(event, context) {
    const scope = context || {};
    const names = scope.names || {};
    const roles = scope.roles || {};
    const plan = Array.isArray(scope.plan) ? scope.plan : [];
    const type = String(event && event.type || "event");
    const metadata = (event && event.metadata) || {};
    const content = String(event && event.content || "");
    const rawAgentId = event ? event.agent_id : null;
    const hasAgent = rawAgentId !== null && rawAgentId !== undefined;
    const agentId = hasAgent ? Number(rawAgentId) : null;

    function nameOf(candidate) {
      const id = Number(candidate);
      return String(names[id] || tf("cl.resident_n", { id: id }));
    }

    const badges = [];
    if (hasAgent) {
      const role = String(roles[String(agentId)] || "").trim();
      if (role) {
        badges.push(role);
      }
      if (Number(scope.leaderId) === agentId) {
        badges.push(t("cl.leader"));
      }
    }

    const stepIndex = Number(metadata.step_index);
    const hasStep = Number.isInteger(stepIndex);
    const step = hasStep ? plan[stepIndex] : null;
    const stepLabel = step
      ? tf("cl.step_n", { n: stepIndex + 1 }) + " · " + String(step.title || "")
      : "";
    const phase = String(metadata.phase || "");
    let round = hasStep ? tf("cl.round_n", { n: stepIndex + 1 }) : "";
    if (metadata.final === true || phase === "synthesis") {
      round = t("cl.round_synthesis");
    }
    const excerpt = String(metadata.excerpt || "");

    let action = content || type.toUpperCase();
    let detail = "";
    let speech = "";

    if (type === "turn_started") {
      action = t({
        execute: "cl.turn_execute",
        review: "cl.turn_review",
        revision: "cl.turn_revision",
        synthesis: "cl.turn_synthesis",
      }[phase] || "cl.turn_default");
      detail = [stepLabel, content].filter(Boolean).join(" · ");
    } else if (type === "artifact") {
      action = t(metadata.final === true ? "cl.artifact_final" : "cl.artifact_sub");
      detail = [stepLabel, content].filter(Boolean).join(" · ");
      speech = excerpt;
    } else if (type === "revision") {
      action = t("cl.revision_done");
      detail = [stepLabel, content].filter(Boolean).join(" · ");
      speech = excerpt;
    } else if (type === "review") {
      action = t(metadata.approved === true ? "cl.review_approved" : "cl.review_changes");
      detail = [stepLabel, String(metadata.artifact || "")]
        .filter(Boolean)
        .join(" · ");
      speech = content;
    } else if (type === "plan_created") {
      const steps = Array.isArray(metadata.plan) ? metadata.plan : [];
      detail = steps.length ? tf("cl.plan_steps", { count: steps.length }) : "";
    } else if (type === "role_assigned") {
      detail = metadata.leader_id === null || metadata.leader_id === undefined
        ? ""
        : tf("cl.leader_is", { name: nameOf(metadata.leader_id) });
    } else if (type === "created") {
      action = t("cl.created");
      detail = content;
    } else if (type === "error") {
      action = t("cl.errored");
      speech = content;
    }

    return {
      type,
      speaker: hasAgent ? nameOf(agentId) : t("cl.system"),
      role: badges.join(" · "),
      round,
      action,
      detail,
      speech,
    };
  }

  function boot() {
    const core = window.GAWorldCollaborationCore;
    if (!core) {
      return;
    }

    const state = {
      agents: [],
      agentDetails: new Map(),
      detailLoading: new Set(),
      selected: new Set(),
      roles: new Map(),
      sessions: [],
      session: null,
      generation: 0,
      lastSeq: 0,
      pollTimer: null,
      polling: null,
      actionGeneration: 0,
      actionPending: null,
      creating: false,
      listGeneration: 0,
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
      els.formStatus.textContent = String(message || "");
      els.formStatus.classList.toggle("is-error", Boolean(error));
    }

    function clearPollTimer() {
      if (state.pollTimer !== null) {
        window.clearTimeout(state.pollTimer);
        state.pollTimer = null;
      }
    }

    function identity(generation, sessionId) {
      return {generation, sessionId};
    }

    function currentIdentity() {
      return identity(
        state.generation,
        state.session ? state.session.id : null,
      );
    }

    function isCurrent(candidate) {
      return core.isCurrentPoll(currentIdentity(), candidate);
    }

    function invalidateSession() {
      clearPollTimer();
      state.generation += 1;
      state.polling = null;
      state.actionPending = null;
      return state.generation;
    }

    function agentFor(agentId) {
      return state.agents.find(function (agent) {
        return Number(agent.id) === Number(agentId);
      });
    }

    function agentName(agentId) {
      const agent = agentFor(agentId);
      return agent
        ? String(agent.name || tf("cl.resident_n", { id: agentId }))
        : tf("cl.resident_n", { id: agentId });
    }

    function capabilityHint(agentId) {
      const detail = state.agentDetails.get(Number(agentId));
      if (!detail) {
        return state.detailLoading.has(Number(agentId))
          ? t("cl.caps_loading")
          : t("cl.caps_hint");
      }
      const capabilities = detail.capabilities || {};
      const values = []
        .concat(capabilities.skills || [])
        .concat(capabilities.deliverables || [])
        .filter(Boolean)
        .slice(0, 3);
      return values.length ? values.join(" · ") : t("cl.caps_none");
    }

    function selectedIds() {
      return core.normalizeAgentIds(Array.from(state.selected));
    }

    function selectedRoles() {
      const roles = {};
      selectedIds().forEach(function (agentId) {
        const value = String(state.roles.get(agentId) || "").trim();
        if (value) {
          roles[String(agentId)] = value;
        }
      });
      return roles;
    }

    function renderMemberPicker() {
      els.memberPicker.replaceChildren();
      if (!state.agents.length) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = t("cl.no_agents");
        els.memberPicker.appendChild(empty);
        return;
      }
      const controlsLocked = state.creating || Boolean(state.actionPending);
      state.agents.forEach(function (agent) {
        const agentId = Number(agent.id);
        const selected = state.selected.has(agentId);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "member-card";
        button.classList.toggle("is-selected", selected);
        button.setAttribute("aria-pressed", String(selected));
        button.disabled = controlsLocked;

        const id = document.createElement("span");
        id.className = "member-id";
        id.textContent = "AGENT / " + String(agentId);
        const name = document.createElement("strong");
        name.className = "member-name";
        name.textContent = String(agent.name || "");
        const capability = document.createElement("span");
        capability.className = "member-capability";
        capability.textContent = capabilityHint(agentId);
        button.append(id, name, capability);
        button.addEventListener("click", function () {
          toggleMember(agentId);
        });
        els.memberPicker.appendChild(button);
      });
    }

    function renderLeaderSelect() {
      const previous = els.leaderSelect.value;
      els.leaderSelect.replaceChildren();
      const automatic = document.createElement("option");
      automatic.value = "";
      automatic.textContent = t("cl.leader_auto");
      els.leaderSelect.appendChild(automatic);
      selectedIds().forEach(function (agentId) {
        const option = document.createElement("option");
        option.value = String(agentId);
        option.textContent = "#" + String(agentId) + " · " + agentName(agentId);
        els.leaderSelect.appendChild(option);
      });
      els.leaderSelect.value = state.selected.has(Number(previous))
        ? previous
        : "";
      els.leaderSelect.disabled = state.creating
        || Boolean(state.actionPending);
    }

    function renderRoleOverrides() {
      els.roleOverrides.replaceChildren();
      const legend = document.createElement("legend");
      legend.textContent = t("cl.roles_legend");
      const note = document.createElement("p");
      note.className = "field-note";
      note.textContent = t("cl.roles_note");
      els.roleOverrides.append(legend, note);

      selectedIds().forEach(function (agentId) {
        const row = document.createElement("div");
        row.className = "role-row";
        const label = document.createElement("label");
        const inputId = "role-agent-" + String(agentId);
        label.setAttribute("for", inputId);
        label.textContent = agentName(agentId);
        const input = document.createElement("input");
        input.id = inputId;
        input.className = "role-input";
        input.type = "text";
        input.placeholder = t("cl.role_auto");
        input.value = String(state.roles.get(agentId) || "");
        input.disabled = state.creating || Boolean(state.actionPending);
        input.addEventListener("input", function () {
          state.roles.set(agentId, input.value);
        });
        row.append(label, input);
        els.roleOverrides.appendChild(row);
      });
    }

    function renderComposerControls() {
      const invalid = selectedIds().length < 2
        || !els.taskInput.value.trim();
      const locked = state.creating || Boolean(state.actionPending);
      els.taskInput.disabled = locked;
      els.startTaskBtn.disabled = invalid || locked;
      els.startTaskBtn.classList.toggle("busy", state.creating);
      renderMemberPicker();
      renderLeaderSelect();
      renderRoleOverrides();
    }

    function loadAgentDetail(agentId) {
      if (
        state.agentDetails.has(agentId)
        || state.detailLoading.has(agentId)
      ) {
        return;
      }
      state.detailLoading.add(agentId);
      renderMemberPicker();
      request("/api/agents/" + encodeURIComponent(String(agentId)) + "/detail")
        .then(function (detail) {
          state.agentDetails.set(agentId, detail);
        })
        .catch(function () {
          state.agentDetails.set(agentId, {capabilities: {}});
        })
        .finally(function () {
          state.detailLoading.delete(agentId);
          renderMemberPicker();
        });
    }

    function toggleMember(agentId) {
      if (state.creating || state.actionPending) {
        return;
      }
      if (state.selected.has(agentId)) {
        state.selected.delete(agentId);
        state.roles.delete(agentId);
      } else {
        state.selected.add(agentId);
        loadAgentDetail(agentId);
      }
      renderComposerControls();
    }

    function renderSessionList() {
      els.sessionList.replaceChildren();
      if (!state.sessions.length) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = t("cl.no_sessions");
        els.sessionList.appendChild(empty);
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
        meta.textContent = String(session.status || "unknown")
          + " · "
          + String(session.id || "");
        button.append(title, meta);
        button.addEventListener("click", function () {
          openSession(session);
        });
        els.sessionList.appendChild(button);
      });
    }

    function renderEmptyActivity() {
      if (els.activityFeed.childElementCount) {
        return;
      }
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.dataset.activityEmpty = "true";
      empty.textContent = t("cl.activity_empty");
      els.activityFeed.appendChild(empty);
    }

    function activityContext() {
      const session = state.session;
      const names = {};
      state.agents.forEach(function (agent) {
        names[Number(agent.id)] = String(agent.name || "");
      });
      return {
        names,
        roles: Object.assign(
          {},
          session && session.role_overrides || {},
          session && session.roles || {},
        ),
        leaderId: session ? session.leader_id : null,
        plan: session && Array.isArray(session.plan) ? session.plan : [],
      };
    }

    function appendEvents(events) {
      const context = activityContext();
      const feed = els.activityFeed;
      // Keep the feed pinned to the newest turn only while the observer is
      // already at the bottom; otherwise reading an earlier round would be
      // interrupted every poll.
      const pinned = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 40;
      (Array.isArray(events) ? events : []).forEach(function (event) {
        const sequence = Number(event.seq || 0);
        if (sequence <= state.lastSeq) {
          return;
        }
        state.lastSeq = sequence;
        const empty = els.activityFeed.querySelector(
          "[data-activity-empty]",
        );
        if (empty) {
          empty.remove();
        }
        const entry = activityEntry(event, context);
        const item = document.createElement("article");
        item.className = "activity-event";
        item.classList.toggle("is-speech", Boolean(entry.speech));
        item.dataset.eventType = entry.type;
        const time = document.createElement("time");
        time.textContent = "#" + String(sequence).padStart(4, "0");
        const body = document.createElement("div");
        const head = document.createElement("div");
        head.className = "activity-speaker";
        const speaker = document.createElement("strong");
        speaker.textContent = entry.speaker;
        head.appendChild(speaker);
        if (entry.role) {
          const role = document.createElement("span");
          role.className = "activity-role";
          role.textContent = entry.role;
          head.appendChild(role);
        }
        if (entry.round) {
          const round = document.createElement("span");
          round.className = "activity-round";
          round.textContent = entry.round;
          head.appendChild(round);
        }
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
        if (entry.speech) {
          const speech = document.createElement("p");
          speech.className = "activity-speech";
          speech.textContent = entry.speech;
          body.appendChild(speech);
        }
        item.append(time, body);
        feed.appendChild(item);
      });
      els.eventCursor.textContent = "SEQ "
        + String(state.lastSeq).padStart(4, "0");
      renderEmptyActivity();
      if (pinned) {
        feed.scrollTop = feed.scrollHeight;
      }
    }

    function renderActiveTeam() {
      els.activeTeam.replaceChildren();
      const session = state.session;
      if (!session || !(session.member_ids || []).length) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = t("cl.team_empty");
        els.activeTeam.appendChild(empty);
        els.leaderBadge.textContent = t("cl.leader_unset");
        return;
      }
      const roles = Object.assign(
        {},
        session.role_overrides || {},
        session.roles || {},
      );
      (session.member_ids || []).forEach(function (agentId) {
        const card = document.createElement("article");
        card.className = "active-member";
        const id = document.createElement("b");
        id.textContent = "#" + String(agentId);
        const name = document.createElement("strong");
        name.textContent = agentName(agentId);
        const role = document.createElement("span");
        role.textContent = String(roles[String(agentId)] || t("cl.role_pending"));
        card.append(id, name, role);
        els.activeTeam.appendChild(card);
      });
      els.leaderBadge.textContent = session.leader_id
        ? tf("cl.leader_is", { name: agentName(session.leader_id) })
        : t("cl.leader_auto_note");
    }

    function renderPlan() {
      els.taskPlan.replaceChildren();
      const session = state.session;
      const plan = session && Array.isArray(session.plan)
        ? session.plan
        : [];
      if (!plan.length) {
        const empty = document.createElement("li");
        empty.className = "empty-state";
        empty.textContent = t("cl.plan_empty");
        els.taskPlan.appendChild(empty);
        els.currentStepText.textContent = t("cl.plan_waiting");
        els.progressText.textContent = "0 / 0";
        els.taskProgress.setAttribute("aria-valuenow", "0");
        els.taskProgressBar.style.width = "0%";
        return;
      }
      const currentStep = Number(session.current_step || 0);
      const completed = plan.filter(function (step, index) {
        return step.status === "completed" || index < currentStep;
      }).length;
      const progress = Math.round((completed / plan.length) * 100);
      els.progressText.textContent = String(completed)
        + " / "
        + String(plan.length);
      els.taskProgress.setAttribute("aria-valuenow", String(progress));
      els.taskProgressBar.style.width = String(progress) + "%";
      els.currentStepText.textContent = currentStep < plan.length
        ? tf("cl.current_step", {
            n: currentStep + 1,
            name: agentName(plan[currentStep].agent_id),
          })
        : t("cl.plan_done");

      plan.forEach(function (step, index) {
        const item = document.createElement("li");
        item.className = "plan-step";
        item.classList.toggle("is-current", index === currentStep);
        item.classList.toggle(
          "is-completed",
          step.status === "completed" || index < currentStep,
        );
        const body = document.createElement("div");
        const title = document.createElement("strong");
        title.textContent = String(step.title || t("cl.step_untitled"));
        const owner = document.createElement("span");
        owner.textContent = agentName(step.agent_id)
          + (step.artifact ? " · " + String(step.artifact) : "");
        body.append(title, owner);
        const status = document.createElement("span");
        status.className = "step-status";
        status.textContent = String(step.status || "pending");
        item.append(body, status);
        els.taskPlan.appendChild(item);
      });
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
      els.artifactList.replaceChildren();
      const artifacts = state.session && Array.isArray(state.session.artifacts)
        ? state.session.artifacts
        : [];
      els.artifactCount.textContent = String(artifacts.length) + " files";
      if (!artifacts.length) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = t("cl.artifacts_empty");
        els.artifactList.appendChild(empty);
        return;
      }
      artifacts.forEach(function (artifact) {
        const item = document.createElement("div");
        item.className = "artifact-item";
        const safeUrl = safeArtifactUrl(
          artifact && artifact.url,
          state.session.id,
          window.location.href,
          state.session.artifact_base_url,
        );
        let label;
        if (safeUrl) {
          label = document.createElement("a");
          label.href = safeUrl;
          label.target = "_blank";
          label.rel = "noopener";
        } else {
          label = document.createElement("span");
        }
        label.textContent = artifactName(artifact);
        item.appendChild(label);
        els.artifactList.appendChild(item);
      });
    }

    function renderSessionActions() {
      const session = state.session;
      const status = String(session && session.status || "");
      const locked = state.creating || Boolean(state.actionPending);
      els.pauseTaskBtn.hidden = status !== "running";
      els.resumeTaskBtn.hidden = ![
        "paused",
        "failed",
        "interrupted",
      ].includes(status);
      els.cancelTaskBtn.hidden = !session
        || ["completed", "cancelled"].includes(status);
      [
        els.pauseTaskBtn,
        els.resumeTaskBtn,
        els.cancelTaskBtn,
      ].forEach(function (button) {
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

    function renderWorkspace() {
      const session = state.session;
      els.taskStatus.textContent = state.creating
        ? t("cl.creating_task")
        : String(session && session.status || t("cl.awaiting_task"));
      els.sessionCode.textContent = session
        ? String(session.id)
        : "NO ACTIVE SESSION";
      els.activeTaskTitle.textContent = session
        ? String(session.task || session.title || session.id)
        : t("cl.pick_or_start");
      renderSessionActions();
      renderActiveTeam();
      renderPlan();
      renderArtifacts();
      renderSessionList();
      renderComposerControls();
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
      state.pollTimer = window.setTimeout(function () {
        refreshSession();
      }, 1000);
    }

    function terminal(session) {
      return Boolean(
        session
        && ["completed", "cancelled"].includes(session.status)
      );
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
      const candidate = identity(state.generation, String(state.session.id));
      if (core.isCurrentPoll(state.polling, candidate)) {
        return;
      }
      state.polling = candidate;
      clearPollTimer();
      const sessionId = encodeURIComponent(String(candidate.sessionId));
      try {
        const results = await Promise.all([
          request("/api/collaboration/sessions/" + sessionId),
          request(
            "/api/collaboration/sessions/"
            + sessionId
            + "/events?after="
            + String(state.lastSeq),
          ),
        ]);
        if (!isCurrent(candidate)) {
          return;
        }
        const wasTerminal = terminal(state.session);
        state.session = results[0];
        appendEvents(results[1].events);
        renderWorkspace();
        if (!wasTerminal && terminal(state.session)) {
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
        state.polling = core.releaseCurrentPoll(
          state.polling,
          candidate,
        );
        schedulePoll();
      }
    }

    async function loadAgents() {
      try {
        const payload = await request("/api/agents");
        state.agents = Array.isArray(payload.agents)
          ? payload.agents.slice()
          : [];
        setFormStatus(
          state.agents.length
            ? t("cl.form_hint")
            : t("cl.roster_empty"),
          false,
        );
      } catch (error) {
        state.agents = [];
        setFormStatus(error.message, true);
      }
      renderComposerControls();
    }

    async function loadSessions() {
      state.listGeneration += 1;
      const requestGeneration = state.listGeneration;
      els.refreshSessionsBtn.disabled = true;
      try {
        const payload = await request(
          "/api/collaboration/sessions?kind=cooperation",
        );
        if (!isLatestRequest(state.listGeneration, requestGeneration)) {
          return;
        }
        state.sessions = Array.isArray(payload.sessions)
          ? payload.sessions.slice()
          : [];
        renderSessionList();
      } catch (error) {
        if (!isLatestRequest(state.listGeneration, requestGeneration)) {
          return;
        }
        setFormStatus(error.message, true);
      } finally {
        if (!isLatestRequest(state.listGeneration, requestGeneration)) {
          return;
        }
        els.refreshSessionsBtn.disabled = false;
      }
    }

    function resetActivity() {
      state.lastSeq = 0;
      els.activityFeed.replaceChildren();
      els.eventCursor.textContent = "SEQ 0000";
      renderEmptyActivity();
    }

    function openSession(session) {
      if (state.creating || state.actionPending) {
        return;
      }
      invalidateSession();
      state.session = session;
      resetActivity();
      renderWorkspace();
      refreshSession();
    }

    async function startTask() {
      if (state.creating || state.actionPending) {
        return;
      }
      const agentIds = selectedIds();
      const task = els.taskInput.value.trim();
      if (agentIds.length < 2 || !task) {
        setFormStatus(t("cl.form_incomplete"), true);
        return;
      }
      const previousSession = state.session;
      const generation = invalidateSession();
      state.creating = true;
      state.session = null;
      resetActivity();
      renderWorkspace();
      setFormStatus(t("cl.creating"), false);
      const payload = core.cooperationPayload(
        agentIds,
        task,
        els.leaderSelect.value,
        selectedRoles(),
      );
      try {
        const session = await request(
          "/api/collaboration/sessions",
          {
            method: "POST",
            body: JSON.stringify(payload),
          },
        );
        if (generation !== state.generation) {
          return;
        }
        state.creating = false;
        state.session = session;
        resetActivity();
        renderWorkspace();
        setFormStatus(t("cl.created_ok"), false);
        loadSessions();
        refreshSession();
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

    function isCurrentAction(candidate) {
      return core.isCurrentAction(state.actionPending, candidate)
        && isCurrent(candidate);
    }

    async function changeSession(action) {
      if (!state.session || state.creating || state.actionPending) {
        return;
      }
      const sessionId = String(state.session.id);
      const generation = invalidateSession();
      state.actionGeneration += 1;
      const candidate = actionIdentity(
        generation,
        sessionId,
        state.actionGeneration,
        action,
      );
      state.actionPending = candidate;
      renderWorkspace();
      try {
        const session = await request(
          "/api/collaboration/sessions/"
          + encodeURIComponent(sessionId)
          + "/"
          + action,
          {
            method: "POST",
            body: "{}",
          },
        );
        if (!isCurrentAction(candidate)) {
          return;
        }
        state.session = session;
        state.actionPending = core.releaseCurrentAction(
          state.actionPending,
          candidate,
        );
        renderWorkspace();
        setFormStatus(t("cl.status_updated"), false);
        loadSessions();
        schedulePoll();
      } catch (error) {
        if (!isCurrentAction(candidate)) {
          return;
        }
        state.actionPending = core.releaseCurrentAction(
          state.actionPending,
          candidate,
        );
        renderWorkspace();
        setFormStatus(error.message, true);
        schedulePoll();
      }
    }

    function bindEvents() {
      els.taskInput.addEventListener("input", renderComposerControls);
      els.startTaskBtn.addEventListener("click", startTask);
      els.refreshSessionsBtn.addEventListener("click", loadSessions);
      els.pauseTaskBtn.addEventListener("click", function () {
        changeSession("pause");
      });
      els.resumeTaskBtn.addEventListener("click", function () {
        changeSession("resume");
      });
      els.cancelTaskBtn.addEventListener("click", function () {
        changeSession("cancel");
      });
      document.addEventListener("visibilitychange", function () {
        if (document.hidden) {
          clearPollTimer();
        } else if (
          !state.creating
          && !state.actionPending
          && core.shouldPoll(state.session)
        ) {
          refreshSession();
        }
      });
    }

    function collectElements() {
      els.taskInput = document.getElementById("taskInput");
      els.memberPicker = document.getElementById("memberPicker");
      els.leaderSelect = document.getElementById("leaderSelect");
      els.roleOverrides = document.getElementById("roleOverrides");
      els.startTaskBtn = document.getElementById("startTaskBtn");
      els.formStatus = document.getElementById("formStatus");
      els.refreshSessionsBtn = document.getElementById("refreshSessionsBtn");
      els.sessionList = document.getElementById("sessionList");
      els.taskStatus = document.getElementById("taskStatus");
      els.sessionCode = document.getElementById("sessionCode");
      els.activeTaskTitle = document.getElementById("activeTaskTitle");
      els.pauseTaskBtn = document.getElementById("pauseTaskBtn");
      els.resumeTaskBtn = document.getElementById("resumeTaskBtn");
      els.cancelTaskBtn = document.getElementById("cancelTaskBtn");
      els.taskProgress = document.getElementById("taskProgress");
      els.taskProgressBar = document.getElementById("taskProgressBar");
      els.progressText = document.getElementById("progressText");
      els.activeTeam = document.getElementById("activeTeam");
      els.leaderBadge = document.getElementById("leaderBadge");
      els.currentStepText = document.getElementById("currentStepText");
      els.taskPlan = document.getElementById("taskPlan");
      els.activityFeed = document.getElementById("activityFeed");
      els.eventCursor = document.getElementById("eventCursor");
      els.artifactList = document.getElementById("artifactList");
      els.artifactCount = document.getElementById("artifactCount");
      els.pauseTaskBtn.dataset.action = "pause";
      els.resumeTaskBtn.dataset.action = "resume";
      els.cancelTaskBtn.dataset.action = "cancel";
    }

    function init() {
      collectElements();
      bindEvents();
      renderWorkspace();
      renderEmptyActivity();
      Promise.all([loadAgents(), loadSessions()]);
    }

    /* The whole page is drawn from JS, so the language switch has to redraw it.
       The activity feed is not re-rendered from here: its entries are a log of
       what was said at the time, and rebuilding them would need the raw events
       kept around purely to re-translate history. Whatever arrives next is in
       the new language; what already happened stays as it was written. */
    document.addEventListener("locale-changed", function () {
      renderMemberPicker();
      renderLeaderSelect();
      renderRoleOverrides();
      renderSessionList();
      renderWorkspace();
      // The activity placeholder is painted at init, before the locale file
      // lands, so it is the one node that can be left showing a raw key. Drop
      // it and let renderEmptyActivity() put it back in the new language; real
      // entries are left alone (see the note above).
      const placeholder = els.activityFeed.querySelector("[data-activity-empty]");
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
    boot,
    activityEntry,
    isLatestRequest,
    safeArtifactUrl,
  };
}));
