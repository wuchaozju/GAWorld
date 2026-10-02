// 猜人局 (Read the Room) — front-end controller.
//
//   POST /api/games/guess/deal   → a resident, a dilemma and their file.
//        Free: no model is touched until a guess is committed.
//   POST /api/games/guess/answer → {round_id, guess} → what they actually
//        picked, why, and whether you had them right.
//   POST /api/games/guess/again  → one more sample from the same resident,
//        same dilemma — the consistency check.
//   GET  /api/games/guess/scoreboard → accuracy, streak, stability.
//
// Unlike the other games there is no polling: one round is one call and the
// wait is a couple of seconds, so every action is a plain request/response.

(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
  // Same contract as city-agents.js: an unresolved key means i18n has not
  // loaded yet (the catalogue fetch can win that race), so fall back to the
  // inline text rather than rendering "vote.custom_option" at the user.
  const t = (key, fallback) => {
    const value = typeof __ === "function" ? __(key) : "";
    return !value || value === key ? fallback : value;
  };

  const state = { city: null, round: null, board: null, busy: false, maxSamples: 3 };

  const exporter = GAWorldGameExport.attach(() => state.round && state.round.settled && {
    game: "guess",
    label: (state.round.agent || {}).name,
    markdown: GAWorldGameExport.guess(state.round, state.board),
  });

  async function init() {
    $("#gDealBtn").addEventListener("click", () => deal());
    $("#gNextBtn").addEventListener("click", () => deal());
    $("#gAgainBtn").addEventListener("click", askAgain);
    $("#gCity").addEventListener("change", () => {
      state.city = $("#gCity").value;
      deal();
    });
    await Promise.all([loadCities(), loadCatalogue()]);
    await deal();
    loadScore();
  }

  async function loadCities() {
    const sel = $("#gCity");
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

  async function loadCatalogue() {
    try {
      const resp = await fetch("/api/games/guess/catalogue");
      const data = await resp.json();
      state.maxSamples = data.max_samples || 3;
    } catch (err) {
      /* the cap is a nicety; the server enforces it either way */
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

  // -- the game -----------------------------------------------------------
  async function deal() {
    if (state.city === null) return;
    setBusy(true, t("guess.dealing", "正在发牌…"));
    try {
      state.round = await post("/api/games/guess/deal", { city: state.city });
      render();
      setStatus(t("guess.your_move", "读档案，猜他会怎么选"));
    } catch (err) {
      setStatus(String(err.message || err), true);
    } finally {
      setBusy(false);
    }
  }

  async function guess(key) {
    if (!state.round || state.round.settled || state.busy) return;
    setBusy(true, t("guess.asking", "正在问他…"));
    try {
      state.round = await post("/api/games/guess/answer", {
        round_id: state.round.id,
        guess: key,
      });
      render();
      setStatus(state.round.correct ? t("guess.hit", "猜中了") : t("guess.miss", "没猜中"));
      loadScore();
    } catch (err) {
      setStatus(String(err.message || err), true);
    } finally {
      setBusy(false);
    }
  }

  async function askAgain() {
    if (!state.round || !state.round.settled || state.busy) return;
    setBusy(true, t("guess.asking_again", "再问一次…"));
    try {
      state.round = await post("/api/games/guess/again", { round_id: state.round.id });
      render();
      setStatus(t("guess.sampled", "又问了一次"));
      loadScore();
    } catch (err) {
      setStatus(String(err.message || err), true);
    } finally {
      setBusy(false);
    }
  }

  // -- rendering ----------------------------------------------------------
  function render() {
    const round = state.round;
    exporter.sync();
    if (!round) return;
    const agent = round.agent || {};
    const meta = [agent.age ? agent.age + "岁" : "", agent.gender || "", agent.job || "", agent.residence || ""]
      .filter(Boolean)
      .join(" · ");

    $("#gFile").innerHTML = `
      <h4>#${agent.agent_id} ${esc(agent.name)}</h4>
      <p class="meta">${esc(meta)}</p>
      <div class="file-body">${esc(agent.file || t("guess.no_file", "（这个人没有档案，只有一行身份信息——猜起来全靠运气）"))}</div>
    `;

    $("#gDilemma").textContent = round.dilemma.text;

    const settled = round.settled;
    $("#gOptions").innerHTML = (round.dilemma.options || [])
      .map((o) => {
        const classes = ["guess-option"];
        if (settled && o.key === round.choice) classes.push("is-theirs");
        if (settled && o.key === round.guess) classes.push("is-yours");
        return `<button type="button" class="${classes.join(" ")}" data-key="${esc(o.key)}" ${settled ? "disabled" : ""}>
          <b>${esc(o.key)}</b> ${esc(o.text)}
          ${settled && o.key === round.guess ? `<span class="pill">${esc(t("guess.you_said", "你猜"))}</span>` : ""}
          ${settled && o.key === round.choice ? `<span class="pill is-theirs">${esc(t("guess.they_said", "他选"))}</span>` : ""}
        </button>`;
      })
      .join("");
    Array.from($("#gOptions").querySelectorAll("button[data-key]")).forEach((btn) => {
      btn.addEventListener("click", () => guess(btn.getAttribute("data-key")));
    });

    const reveal = $("#gReveal");
    reveal.hidden = !settled;
    $("#gAfter").hidden = !settled;
    if (settled) {
      const samples = round.samples || [];
      const spread = new Set(samples.map((s) => s.choice));
      reveal.className = "guess-reveal " + (round.correct ? "is-hit" : "is-miss");
      reveal.innerHTML = `
        <h4>${round.correct ? esc(t("guess.win", "🎯 猜中了")) : esc(t("guess.lose", "🙈 没猜中"))}</h4>
        <p>${esc(round.why || t("guess.no_reason", "（他没说理由）"))}</p>
        ${samples.length > 1
          ? `<p class="samples"><b>${esc(t("guess.asked_n", "问了"))} ${samples.length} ${esc(t("guess.times", "次"))}：</b>
             ${samples.map((s) => esc(s.choice || "?")).join(" / ")} —
             ${spread.size === 1
               ? esc(t("guess.stable", "每次都一样，这份档案很稳"))
               : esc(t("guess.unstable", "答案不一致，这份档案撑不住这道题"))}</p>`
          : ""}
      `;
      $("#gAgainBtn").disabled = exhausted();
    }
  }

  /** Out of re-asks. Checked in both render() and setBusy(), because
   *  setBusy runs last and would otherwise re-enable the button. */
  function exhausted() {
    const samples = (state.round && state.round.samples) || [];
    return samples.length >= state.maxSamples;
  }

  function setStatus(message, isError) {
    const el = $("#gStatus");
    el.className = "disaster-status" + (isError ? " is-error" : "");
    el.textContent = message;
  }

  function setBusy(busy, message) {
    state.busy = busy;
    $("#gDealBtn").disabled = busy;
    $("#gNextBtn").disabled = busy;
    $("#gAgainBtn").disabled = busy || !(state.round && state.round.settled) || exhausted();
    Array.from($("#gOptions").querySelectorAll("button")).forEach((btn) => {
      btn.disabled = busy || (state.round && state.round.settled);
    });
    if (busy && message) setStatus(message);
  }

  async function loadScore() {
    try {
      const resp = await fetch("/api/games/guess/scoreboard");
      const board = await resp.json();
      state.board = board;
      $("#gScore").innerHTML = [
        metric(t("guess.m_accuracy", "命中率"), board.played ? Math.round(board.accuracy * 100) + "%" : "—",
          board.played ? `${board.correct}/${board.played}` : ""),
        metric(t("guess.m_streak", "连胜"), board.streak, `${t("guess.m_best", "最佳")} ${board.best_streak}`),
        metric(t("guess.m_stable", "档案稳定"), board.resampled ? `${board.stable}/${board.resampled}` : "—",
          t("guess.m_stable_suffix", "复问一致")),
      ].join("");

      const ul = $("#gHistory");
      if (!board.history.length) {
        ul.innerHTML = `<li class="disaster-empty">${esc(t("guess.no_history", "还没玩过"))}</li>`;
        return;
      }
      ul.innerHTML = board.history
        .map((h) => `<li class="${h.correct ? "is-hit" : "is-miss"}">
          <span class="mark">${h.correct ? "✅" : "❌"}</span>
          <span class="who">${esc(h.name)}</span>
          <span class="meta">${esc(h.dilemma)} · ${esc(t("guess.you_said", "你猜"))} ${esc(h.guess)} · ${esc(t("guess.they_said", "他选"))} ${esc(h.choice || "?")}</span>
        </li>`)
        .join("");
    } catch (err) {
      $("#gScore").innerHTML = `<p class="disaster-empty is-error">${esc(String(err))}</p>`;
    }
  }

  function metric(label, value, suffix) {
    return `<div class="disaster-metric">
      <span class="label">${esc(label)}</span>
      <b>${esc(value == null ? "—" : value)}</b><span class="suffix">${esc(suffix || "")}</span>
    </div>`;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
