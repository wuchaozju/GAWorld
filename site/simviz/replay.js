(function (global) {
  "use strict";

  function normalizeRuns(payload) {
    const runs = payload && Array.isArray(payload.runs) ? payload.runs : [];
    return runs.filter((run) => run && run.id && run.trace_url);
  }

  function selectRun(runs, requestedId) {
    if (!Array.isArray(runs) || !runs.length) return null;
    const target = String(requestedId || "").trim();
    return runs.find((run) => String(run.id) === target) || runs[0];
  }

  function framesUntil(trace, index) {
    const frames = trace && Array.isArray(trace.frames) ? trace.frames : [];
    if (!frames.length) return [];
    const safeIndex = Math.max(0, Math.min(frames.length - 1, Number(index) || 0));
    return frames.slice(0, safeIndex + 1);
  }

  function frameLabel(frame, index) {
    if (!frame) return "-";
    const day = frame.day == null ? "" : `Day ${frame.day}`;
    const time = frame.time || frame.time_str || "";
    const prefix = [day, time].filter(Boolean).join(" ");
    return prefix || `Frame ${index + 1}`;
  }

  function optionLabel(run) {
    const kind = run.kind ? `[${run.kind}] ` : "";
    const meta = [];
    if (run.sim_days != null) meta.push(`${run.sim_days}天`);
    if (run.agent_count != null) meta.push(`${run.agent_count}人`);
    if (run.frame_count != null) meta.push(`${run.frame_count}帧`);
    return `${kind}${run.label || run.id}${meta.length ? " · " + meta.join(" · ") : ""}`;
  }

  async function fetchJson(url) {
    const response = await fetch(`${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${url}`);
    return response.json();
  }

  function queryRunId() {
    if (!global.location) return "";
    return new URLSearchParams(global.location.search || "").get("run") || "";
  }

  function renderAgents(container, frame) {
    if (!container) return;
    const agents = frame && Array.isArray(frame.agents) ? frame.agents : [];
    if (!agents.length) {
      container.innerHTML = '<div class="agent-card"><p>当前帧没有 agent 记录。</p></div>';
      return;
    }
    container.innerHTML = agents.map((agent) => {
      const name = agent.name || `Agent ${agent.agent_id || ""}`;
      const activity = agent.activity || agent.final_activity || agent.scheduled_activity || "无活动记录";
      const location = agent.resolved_location || agent.location || agent.target_location || "未知位置";
      const thought = agent.plan || agent.action || agent.reflection || "";
      return (
        '<article class="agent-card">' +
        `<strong>${escapeHtml(name)}</strong>` +
        `<p>${escapeHtml(location)} · ${escapeHtml(activity)}</p>` +
        (thought ? `<p>${escapeHtml(thought)}</p>` : "") +
        "</article>"
      );
    }).join("");
  }

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function attachUi(document) {
    const els = {
      runSelect: document.getElementById("runSelect"),
      canvas: document.getElementById("mapCanvas"),
      timeline: document.getElementById("timeline"),
      playBtn: document.getElementById("playBtn"),
      latestBtn: document.getElementById("latestBtn"),
      refreshBtn: document.getElementById("refreshBtn"),
      speedSelect: document.getElementById("speedSelect"),
      statusText: document.getElementById("statusText"),
      frameStamp: document.getElementById("frameStamp"),
      frameTitle: document.getElementById("frameTitle"),
      agentList: document.getElementById("agentList"),
    };
    if (!els.runSelect || !els.canvas || !global.CityMapView) return null;

    const state = {
      runs: [],
      run: null,
      trace: null,
      index: 0,
      timer: null,
      view: new global.CityMapView(els.canvas, {
        emptyText: "等待轨迹数据...",
      }),
    };

    function setStatus(text) {
      els.statusText.textContent = text;
    }

    function resizeCanvas() {
      const rect = els.canvas.getBoundingClientRect();
      const width = Math.max(320, Math.floor(rect.width));
      const height = Math.max(240, Math.floor(rect.height));
      if (els.canvas.width !== width || els.canvas.height !== height) {
        els.canvas.width = width;
        els.canvas.height = height;
      }
      render();
    }

    function render() {
      const frames = state.trace && Array.isArray(state.trace.frames) ? state.trace.frames : [];
      const frame = frames[state.index];
      els.timeline.max = String(Math.max(0, frames.length - 1));
      els.timeline.value = String(state.index);
      els.frameStamp.textContent = frameLabel(frame, state.index);
      els.frameTitle.textContent = state.run ? (state.run.label || state.run.id) : "-";
      if (state.trace) state.view.setTrace(state.trace);
      state.view.avatarBase = (state.run && state.run.avatar_base) || "/output/visualization/";
      state.view.render(framesUntil(state.trace, state.index));
      renderAgents(els.agentList, frame);
    }

    async function loadRun(run) {
      if (!run) {
        setStatus("没有可回放的运行");
        state.view.renderEmpty("没有可回放的运行");
        return;
      }
      state.run = run;
      setStatus("读取轨迹...");
      const trace = await fetchJson(run.trace_url);
      state.trace = trace;
      const frames = Array.isArray(trace.frames) ? trace.frames : [];
      state.index = Math.max(0, frames.length - 1);
      setStatus(`${frames.length} 帧`);
      render();
    }

    async function refreshRuns() {
      setStatus("读取运行列表...");
      const payload = await fetchJson("/api/replay/runs");
      state.runs = normalizeRuns(payload);
      els.runSelect.innerHTML = state.runs.map((run) => {
        return `<option value="${escapeHtml(run.id)}">${escapeHtml(optionLabel(run))}</option>`;
      }).join("");
      const run = selectRun(state.runs, queryRunId());
      if (run) els.runSelect.value = run.id;
      await loadRun(run);
    }

    function play() {
      if (state.timer) {
        global.clearInterval(state.timer);
        state.timer = null;
        els.playBtn.textContent = "播放";
        return;
      }
      els.playBtn.textContent = "暂停";
      state.timer = global.setInterval(() => {
        const frames = state.trace && Array.isArray(state.trace.frames) ? state.trace.frames : [];
        state.index = frames.length ? (state.index + 1) % frames.length : 0;
        render();
      }, Number(els.speedSelect.value) || 500);
    }

    els.runSelect.addEventListener("change", () => {
      const run = selectRun(state.runs, els.runSelect.value);
      loadRun(run).catch((error) => setStatus(error.message));
    });
    els.timeline.addEventListener("input", () => {
      state.index = Number(els.timeline.value) || 0;
      render();
    });
    els.playBtn.addEventListener("click", play);
    els.latestBtn.addEventListener("click", () => {
      const frames = state.trace && Array.isArray(state.trace.frames) ? state.trace.frames : [];
      state.index = Math.max(0, frames.length - 1);
      render();
    });
    els.refreshBtn.addEventListener("click", () => refreshRuns().catch((error) => setStatus(error.message)));
    global.addEventListener("resize", resizeCanvas);
    refreshRuns().then(resizeCanvas).catch((error) => setStatus(error.message));
    return state;
  }

  const api = { normalizeRuns, selectRun, framesUntil, frameLabel, optionLabel, attachUi };
  global.GAWorldReplay = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (global.document) {
    global.document.addEventListener("DOMContentLoaded", () => attachUi(global.document));
  }
})(typeof window !== "undefined" ? window : globalThis);
