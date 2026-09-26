// 说服游戏 (Persuasion) — front-end controller.
//
// One game is one session on the server (`/api/games/persuasion/*`):
//
//   start  → the opponent answers the question once; that answer is the
//            baseline the whole game is scored against.
//   say    → one chat turn. The server replies in character and, when the
//            last allowed turn is used, settles the game on its own.
//   settle → re-ask the original question, then a judge LLM decides whether
//            the position actually moved.
//
// Every call is a plain request/response — no polling — because each one is
// a single LLM round trip, short enough to await inside a chat UI. Sessions
// live in the server's memory only, so "最近对局" empties when the dashboard
// restarts; that matches the arena's sandbox semantics.

(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
  const t = (key, fallback) => (typeof __ === "function" ? __(key) : fallback);

  // `city` is null until the picker loads: "" is a real city (the default
  // world), so it cannot double as "nothing selected".
  const state = {
    city: null,
    agents: [],
    session: null,
    busy: false,
  };

  async function init() {
    $("#pStartBtn").addEventListener("click", startGame);
    $("#pSendBtn").addEventListener("click", sendMessage);
    $("#pSettleBtn").addEventListener("click", () => settle());
    $("#pCity").addEventListener("change", () => {
      state.city = $("#pCity").value;
      loadAgents();
    });
    $("#pMessage").addEventListener("keydown", (ev) => {
      if ((ev.metaKey || ev.ctrlKey) && ev.key === "Enter") sendMessage();
    });
    await loadCities();
    await Promise.all([loadAgents(), loadHistory()]);
  }

  // -- pickers ------------------------------------------------------------
  async function loadCities() {
    const sel = $("#pCity");
    try {
      const resp = await fetch("/api/city/catalogue");
      const data = await resp.json();
      const cities = data.cities || [];
      sel.innerHTML = cities
        .map((c) => `<option value="${esc(c.slug)}">${esc(c.display_name || c.name || c.slug)}</option>`)
        .join("");
      const preferred = data.selected != null ? data.selected : (cities[0] && cities[0].slug);
      if (preferred != null) sel.value = preferred;
      state.city = sel.value;
    } catch (err) {
      sel.innerHTML = `<option value="">${esc(String(err))}</option>`;
      state.city = "";
    }
  }

  async function loadAgents() {
    const sel = $("#pAgent");
    if (state.city === null) return;
    sel.innerHTML = `<option>${esc(t("persuade.loading", "加载中…"))}</option>`;
    try {
      const resp = await fetch("/api/games/agents?city=" + encodeURIComponent(state.city));
      const data = await resp.json();
      state.agents = data.agents || [];
      if (!state.agents.length) {
        sel.innerHTML = `<option value="">${esc(t("persuade.no_agents", "这座城市暂无居民"))}</option>`;
        return;
      }
      sel.innerHTML = state.agents
        .map((a) => {
          const meta = [a.age ? a.age + "岁" : "", a.gender || "", a.job || ""].filter(Boolean).join(" · ");
          return `<option value="${a.id}">#${a.id} ${esc(a.name)}${meta ? " — " + esc(meta) : ""}</option>`;
        })
        .join("");
    } catch (err) {
      sel.innerHTML = `<option value="">${esc(String(err))}</option>`;
    }
  }

  // -- the game -----------------------------------------------------------
  async function startGame() {
    const question = $("#pQuestion").value.trim();
    const agentId = parseInt($("#pAgent").value, 10);
    if (!question) return setStatus(t("persuade.need_question", "先写一个问题"), true);
    if (!agentId) return setStatus(t("persuade.need_agent", "先选一个对手"), true);

    setBusy(true, t("persuade.asking", "正在问他…"));
    try {
      const session = await post("/api/games/persuasion/start", {
        city: state.city,
        agent_id: agentId,
        question,
        max_turns: Math.max(1, parseInt($("#pMaxTurns").value, 10) || 5),
      });
      state.session = session;
      render();
      setStatus(t("persuade.your_move", "他答完了 — 该你了"));
      loadHistory();
    } catch (err) {
      setStatus(String(err.message || err), true);
    } finally {
      setBusy(false);
    }
  }

  async function sendMessage() {
    if (!state.session || state.busy) return;
    const box = $("#pMessage");
    const message = box.value.trim();
    if (!message) return;
    setBusy(true, t("persuade.thinking", "他在想…"));
    try {
      const session = await post("/api/games/persuasion/say", {
        session_id: state.session.id,
        message,
      });
      state.session = session;
      box.value = "";
      render();
      setStatus(
        session.status === "settled"
          ? t("persuade.settled", "轮数用完，已复问结算")
          : t("persuade.your_move", "该你了")
      );
      loadHistory();
    } catch (err) {
      setStatus(String(err.message || err), true);
    } finally {
      setBusy(false);
    }
  }

  async function settle() {
    if (!state.session || state.busy) return;
    setBusy(true, t("persuade.resettling", "正在复问…"));
    try {
      const session = await post("/api/games/persuasion/settle", { session_id: state.session.id });
      state.session = session;
      render();
      setStatus(t("persuade.settled_manual", "已复问结算"));
      loadHistory();
    } catch (err) {
      setStatus(String(err.message || err), true);
    } finally {
      setBusy(false);
    }
  }

  async function post(url, body) {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "HTTP " + resp.status);
    return data;
  }

  // -- rendering ----------------------------------------------------------
  function render() {
    const session = state.session;
    $("#pIdle").hidden = !!session;
    $("#pBoard").hidden = !session;
    if (!session) return;

    $("#pQuestionEcho").textContent = session.question;
    $("#pTurnsLeft").textContent = session.turns_left + " / " + session.max_turns;

    const who = "#" + session.agent_id + " " + session.agent_name;
    const lines = [bubble("agent", who, session.initial_answer, "is-opening")];
    (session.messages || []).forEach((m) => {
      lines.push(bubble(m.role, m.role === "player" ? t("persuade.you", "你") : who, m.text, ""));
    });
    if (session.final_answer) {
      lines.push(bubble("agent", who + t("persuade.final_suffix", "（复问）"), session.final_answer, "is-final"));
    }
    const chat = $("#pChat");
    chat.innerHTML = lines.join("");
    chat.scrollTop = chat.scrollHeight;

    const settled = session.status === "settled";
    $("#pMessage").disabled = settled;
    $("#pSendBtn").disabled = settled;
    $("#pSettleBtn").disabled = settled;

    const verdict = $("#pVerdict");
    verdict.hidden = !settled;
    if (settled) {
      const win = session.outcome === "success";
      verdict.className = "persuade-verdict " + (win ? "is-success" : "is-failed");
      verdict.innerHTML = `
        <h4>${win ? esc(t("persuade.win", "🎉 说服成功")) : esc(t("persuade.lose", "🪨 没说动他"))}</h4>
        <p><b>${esc(t("persuade.before", "最初"))}：</b>${esc(session.initial_answer)}</p>
        <p><b>${esc(t("persuade.after", "复问"))}：</b>${esc(session.final_answer)}</p>
        ${session.reason ? `<p><b>${esc(t("persuade.judge", "裁判"))}：</b>${esc(session.reason)}</p>` : ""}
      `;
    }
  }

  function bubble(role, speaker, text, extra) {
    return `<div class="chat-line is-${role === "player" ? "player" : "agent"}">
      <div class="chat-bubble ${extra}">
        <span class="speaker">${esc(speaker)}</span>${esc(text)}
      </div>
    </div>`;
  }

  function setStatus(message, isError) {
    const el = $("#pStatus");
    el.className = "persuade-status" + (isError ? " is-error" : "");
    el.textContent = message;
  }

  function setBusy(busy, message) {
    state.busy = busy;
    $("#pStartBtn").disabled = busy;
    const settled = state.session && state.session.status === "settled";
    $("#pSendBtn").disabled = busy || settled;
    $("#pSettleBtn").disabled = busy || settled;
    if (busy && message) setStatus(message);
  }

  async function loadHistory() {
    const ul = $("#pHistory");
    try {
      const resp = await fetch("/api/games/persuasion/sessions");
      const data = await resp.json();
      const sessions = data.sessions || [];
      if (!sessions.length) {
        ul.innerHTML = `<li class="persuade-empty">${esc(t("persuade.no_history", "还没有对局"))}</li>`;
        return;
      }
      ul.innerHTML = sessions
        .map((s) => {
          const mark = s.status !== "settled"
            ? t("persuade.tag_open", "进行中")
            : s.outcome === "success"
              ? t("persuade.tag_win", "✅ 说服成功")
              : t("persuade.tag_lose", "❌ 未说服");
          return `<li>
            <button type="button" data-session="${esc(s.id)}">
              <span class="who">#${s.agent_id} ${esc(s.agent_name)}</span>
              <span class="meta">${esc(mark)} · ${s.turns_used}/${s.max_turns} · ${esc(s.question.slice(0, 22))}</span>
            </button>
          </li>`;
        })
        .join("");
      Array.from(ul.querySelectorAll("button[data-session]")).forEach((btn) => {
        btn.addEventListener("click", () => openSession(btn.getAttribute("data-session")));
      });
    } catch (err) {
      ul.innerHTML = `<li class="persuade-empty is-error">${esc(String(err))}</li>`;
    }
  }

  async function openSession(sessionId) {
    try {
      const resp = await fetch("/api/games/persuasion/sessions/" + encodeURIComponent(sessionId));
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "HTTP " + resp.status);
      state.session = data;
      render();
      setStatus(data.status === "settled" ? t("persuade.viewing", "回看已结束的对局") : t("persuade.your_move", "该你了"));
    } catch (err) {
      setStatus(String(err.message || err), true);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
