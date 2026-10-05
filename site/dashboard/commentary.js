// 新闻评论 (News Commentary) — front-end controller.
//
// One run is one background job on the server (`/api/games/commentary/*`):
//
//   POST run          → {job_id}; cost is residents + 1 model calls, so the
//                       request is too long for an inline answer and it polls.
//   GET  jobs/<id>    → progress while running, the whole run once done.
//   GET  runs         → finished runs still in memory (sidebar history).
//   GET  catalogue    → the stance vocabulary the server recognises (used to
//                       tag cards with the right colour).
//
// The board is rendered from the finished run only: a resident's comment is
// the whole point, and a half-written card would read as a result rather than
// as work in progress. The progress bar is what moves during the run.
//
// Multi-news shape: the first block is the *main* news everyone is scored
// against. The remaining blocks ("相关新闻") ride along inside the prompt as
// background only — they never produce their own stance or comment.

(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&", "<": "<", ">": ">", "\"": "&#34;", "'": "&#39;",
  }[c]));
  // Same contract as rumor.js / disaster.js: an unresolved key means i18n has
  // not loaded yet (the catalogue fetch can win that race), so fall back to
  // the inline text rather than rendering "commentary.x" at the user.
  const t = (key, fallback) => {
    const value = typeof __ === "function" ? __(key) : "";
    return !value || value === key ? fallback : value;
  };

  // `city` is null until the picker loads: "" is a real city (the default
  // world), so it cannot double as "nothing selected".
  const state = {
    city: null,
    agents: [],
    picked: new Set(),
    run: null,
    jobId: null,
    jobTimer: null,
    stances: ["支持", "反对", "中立", "质疑", "其他"],
    // Per-block mode: 0 = paste, 1 = url. The first block (index 0) is the
    // main news and is always present; the rest are related.
    modes: [0],
  };

  // Stance → CSS tag colour. Order matters: the first four are the official
  // vocabulary (server validates against them) and the last is the catch-all
  // for an off-vocabulary reply that nobody should punish the resident for.
  const STANCE_TAG = {
    支持: "is-pro",
    反对: "is-against",
    中立: "is-neutral",
    质疑: "is-skeptic",
    其他: "is-other",
  };

  const exporter = GAWorldGameExport.attach(() => state.run && {
    game: "commentary",
    label: ((state.run.news || {}).title || "新闻评论") + ((state.run.related || []).length ? "（+" + state.run.related.length + "）" : ""),
    markdown: GAWorldGameExport.commentary(state.run),
  });

  async function init() {
    $("#cRunBtn").addEventListener("click", startRun);
    $("#cPickRandom").addEventListener("click", pickRandom);
    $("#cPickNone").addEventListener("click", () => { state.picked.clear(); renderAgents(); });
    $("#cCity").addEventListener("change", () => {
      state.city = $("#cCity").value;
      state.picked.clear();
      loadAgents();
    });
    bindModeToggle("#newsTitle");
    $("#cAddRelated").addEventListener("click", addRelatedBlock);
    updateRelatedCount();
    await Promise.all([loadCities().then(loadAgents), loadCatalogue()]);
    loadHistory();
  }

  // -- news blocks (main + related) ----------------------------------------
  function bindModeToggle(scope) {
    // Each news block has its own pair of paste/url buttons.
    $$(scope + " .news-mode-toggle .button", $(scope)).forEach((btn) => {
      btn.addEventListener("click", () => {
        const block = btn.closest(".news-block");
        if (!block) return;
        const idx = blockIndex(block);
        const mode = btn.getAttribute("data-mode") === "url" ? 1 : 0;
        state.modes[idx] = mode;
        applyBlockMode(block, mode);
      });
    });
  }

  function applyBlockMode(block, mode) {
    const toggle = block.querySelectorAll(".news-mode-toggle .button");
    toggle.forEach((b) => {
      const on = (b.getAttribute("data-mode") === "url" ? 1 : 0) === mode;
      b.classList.toggle("is-on", on);
    });
    block.querySelector(".paste-title-block").hidden = mode === 1;
    block.querySelector(".paste-body-block").hidden = mode === 1;
    block.querySelector(".url-block").hidden = mode === 0;
  }

  function $$(sel, root) {
    return Array.from((root || document).querySelectorAll(sel));
  }

  function blockIndex(block) {
    // The data-news-index attribute is the source of truth; falling back to
    // DOM position keeps the index sane when blocks are removed.
    const raw = block && block.getAttribute("data-news-index");
    return raw == null ? 0 : parseInt(raw, 10);
  }

  function addRelatedBlock() {
    const list = $("#relatedList");
    if (!list) return;
    if (list.children.length >= commentaryMaxRelated()) {
      setStatus(t("commentary.too_many_related", "相关新闻最多 5 条"), true);
      return;
    }
    const idx = list.children.length + 1; // 0 is reserved for the main block
    state.modes.push(0);
    const el = document.createElement("div");
    el.className = "news-block is-related";
    el.setAttribute("data-news-index", String(idx));
    el.innerHTML = `
      <header class="news-block-head">
        <span class="news-block-tag">${esc(t("commentary.news_related", "相关新闻"))}</span>
        <div class="news-mode-toggle">
          <button class="button is-on" type="button" data-mode="paste">${esc(t("commentary.mode_paste", "📝 贴文本"))}</button>
          <button class="button" type="button" data-mode="url">${esc(t("commentary.mode_url", "🔗 给网址"))}</button>
        </div>
        <button class="button" type="button" data-role="remove">${esc(t("commentary.remove", "删除"))}</button>
      </header>
      <label class="field paste-title-block">
        <span>${esc(t("commentary.paste_title_label", "新闻标题（可选）"))}</span>
        <input type="text" data-role="paste_title" placeholder="${esc(t("commentary.paste_title_placeholder", "例如：地铁涨价方案公示"))}" />
      </label>
      <label class="field paste-body-block">
        <span>${esc(t("commentary.paste_body_label", "新闻正文"))}</span>
        <textarea data-role="paste_body" placeholder="${esc(t("commentary.paste_body_placeholder", "把新闻正文贴进来…"))}"></textarea>
      </label>
      <label class="field url-block" hidden>
        <span>${esc(t("commentary.url_label", "新闻网址"))}</span>
        <input type="url" data-role="url" placeholder="${esc(t("commentary.url_placeholder", "https://…"))}" />
      </label>
    `;
    list.appendChild(el);
    bindModeToggleOn(el);
    el.querySelector('[data-role="remove"]').addEventListener("click", () => removeRelatedBlock(el));
    updateRelatedCount();
  }

  function removeRelatedBlock(el) {
    const list = $("#relatedList");
    if (!list || !el || !list.contains(el)) return;
    const idx = blockIndex(el);
    list.removeChild(el);
    // Drop the matching mode entry so state.modes stays aligned with the
    // remaining blocks. The main block's mode (index 0) is never touched.
    if (idx > 0 && idx < state.modes.length) {
      state.modes.splice(idx, 1);
    }
    // Re-number the remaining related blocks so indices stay contiguous and
    // match their position in state.modes.
    Array.from(list.children).forEach((child, i) => {
      child.setAttribute("data-news-index", String(i + 1));
    });
    updateRelatedCount();
  }

  function bindModeToggleOn(block) {
    block.querySelectorAll(".news-mode-toggle .button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = blockIndex(block);
        const mode = btn.getAttribute("data-mode") === "url" ? 1 : 0;
        state.modes[idx] = mode;
        applyBlockMode(block, mode);
      });
    });
  }

  function commentaryMaxRelated() {
    // Hard-coded mirror of the server-side cap so the button can grey out.
    // Backend is the source of truth; if it changes, this lags one release.
    return 5;
  }

  function updateRelatedCount() {
    const list = $("#relatedList");
    const n = list ? list.children.length : 0;
    const cap = commentaryMaxRelated();
    const hint = $("#cRelatedCount");
    if (!hint) return;
    hint.textContent = n ? `（${n}/${cap}）` : `（0/${cap}）`;
    const addBtn = $("#cAddRelated");
    if (addBtn) addBtn.disabled = n >= cap;
  }

  function readOneBlock(block, idx) {
    const mode = state.modes[idx] || 0;
    if (mode === 1) {
      const url = (block.querySelector('[data-role="url"]').value || "").trim();
      if (!url) throw new Error(t("commentary.need_url", "先贴一个网址"));
      return { url };
    }
    const body = (block.querySelector('[data-role="paste_body"]').value || "").trim();
    if (!body) throw new Error(t("commentary.need_body", "先贴一段新闻正文"));
    return {
      title: (block.querySelector('[data-role="paste_title"]').value || "").trim(),
      body,
    };
  }

  function readAllNews() {
    // The main block is the first .news-block on the page; related blocks
    // live inside #relatedList and were added by addRelatedBlock().
    const blocks = $$(".news-block", $("#newsTitle"));
    const mainBlock = blocks.find((b) => b.classList.contains("is-main"));
    if (!mainBlock) throw new Error(t("commentary.no_input", "请填写一条新闻"));
    const mainIdx = blockIndex(mainBlock);
    const main = readOneBlock(mainBlock, mainIdx);
    const relatedBlocks = $$("#relatedList .news-block");
    const related = relatedBlocks.map((b, i) => readOneBlock(b, i + 1));
    // The server's array form takes everything in order: main first, related
    // after. Wrap the single news in an array when there are no related
    // entries too — keeps the wire shape consistent.
    return { news: [main].concat(related) };
  }

  // -- pickers ------------------------------------------------------------
  async function loadCities() {
    const sel = $("#cCity");
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
      const resp = await fetch("/api/games/commentary/catalogue");
      const data = await resp.json();
      state.stances = (data.stances || state.stances).concat(["其他"]);
      state.maxAgents = data.max_agents || 12;
    } catch (_) {
      // Catalogue failure should not block the page; defaults stay.
    }
  }

  async function loadAgents() {
    const list = $("#cAgents");
    if (state.city === null) return;
    list.innerHTML = `<li class="disaster-empty">${esc(t("commentary.loading", "加载中…"))}</li>`;
    try {
      const resp = await fetch("/api/games/agents?city=" + encodeURIComponent(state.city));
      const data = await resp.json();
      state.agents = data.agents || [];
      renderAgents();
    } catch (err) {
      list.innerHTML = `<li class="disaster-empty is-error">${esc(String(err))}</li>`;
    }
  }

  function renderAgents() {
    const list = $("#cAgents");
    if (!state.agents.length) {
      list.innerHTML = `<li class="disaster-empty">${esc(t("commentary.no_agents", "这座城市暂无居民"))}</li>`;
      $("#cPicked").textContent = "0";
      return;
    }
    list.innerHTML = state.agents
      .map((a) => {
        const meta = [a.age ? a.age + "岁" : "", a.job || ""].filter(Boolean).join(" · ");
        const on = state.picked.has(a.id) ? " checked" : "";
        return `<li><label>
          <input type="checkbox" value="${a.id}"${on} />
          <span class="who">#${a.id} ${esc(a.name)}</span>
          <span class="meta">${esc(meta)}</span>
        </label></li>`;
      })
      .join("");
    Array.from(list.querySelectorAll("input[type=checkbox]")).forEach((box) => {
      box.addEventListener("change", () => {
        const id = parseInt(box.value, 10);
        if (box.checked) state.picked.add(id);
        else state.picked.delete(id);
        if (state.picked.size > (state.maxAgents || 12)) {
          state.picked.delete(id);
          box.checked = false;
          setStatus(t("commentary.too_many", "最多 12 人"), true);
        }
        $("#cPicked").textContent = String(state.picked.size);
      });
    });
    $("#cPicked").textContent = String(state.picked.size);
  }

  function pickRandom() {
    const pool = state.agents.slice();
    for (let i = pool.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [pool[i], pool[j]] = [pool[j], pool[i]];
    }
    state.picked = new Set(pool.slice(0, 6).map((a) => a.id));
    renderAgents();
  }

  // -- the run ------------------------------------------------------------
  async function startRun() {
    if (!state.picked.size) return setStatus(t("commentary.need_agents", "先选几个居民"), true);
    let newsPayload;
    try {
      newsPayload = readAllNews();
    } catch (err) {
      return setStatus(String(err.message || err), true);
    }
    const body = Object.assign({ city: state.city, agent_ids: Array.from(state.picked) }, newsPayload);

    $("#cRunBtn").disabled = true;
    setProgress(0);
    setStatus(t("commentary.running", "评论中…"));
    try {
      const resp = await fetch("/api/games/commentary/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.error || "HTTP " + resp.status);
      state.jobId = data.job_id;
      pollJob();
    } catch (err) {
      setStatus(String(err.message || err), true);
      $("#cRunBtn").disabled = false;
    }
  }

  function pollJob() {
    if (!state.jobId) return;
    clearInterval(state.jobTimer);
    state.jobTimer = setInterval(async () => {
      try {
        const resp = await fetch("/api/games/commentary/jobs/" + encodeURIComponent(state.jobId));
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const rec = await resp.json();
        setProgress(Math.round((rec.progress || 0) * 100));
        if (rec.status === "running") {
          setStatus(rec.message || t("commentary.running", "评论中…"));
          return;
        }
        stopPolling();
        if (rec.status === "done") {
          state.run = rec.result;
          render();
          setStatus(t("commentary.done", "评论完成"));
          loadHistory();
        } else {
          setStatus(rec.error || "failed", true);
        }
      } catch (err) {
        stopPolling();
        setStatus(String(err.message || err), true);
      }
    }, 900);
  }

  function stopPolling() {
    clearInterval(state.jobTimer);
    state.jobTimer = null;
    $("#cRunBtn").disabled = false;
  }

  // -- rendering ----------------------------------------------------------
  function render() {
    const run = state.run;
    $("#cIdle").hidden = !!run;
    $("#cResult").hidden = !run;
    exporter.sync();
    if (!run) return;

    const news = run.news || {};
    const related = run.related || [];
    $("#cTitle").textContent = `${news.title || "(无题)"} · ${(run.nodes || []).length} ${t("commentary.people", "人")}`;

    // Main news box: title + body + where it came from. Hide when there is
    // nothing to show so the panel does not render an empty placeholder.
    const hasNewsBody = !!(news.body && news.body.trim());
    $("#cNewsBox").hidden = !hasNewsBody;
    if (hasNewsBody) {
      $("#cNewsTitle").textContent = news.title || "";
      $("#cNewsBody").textContent = news.body;
      const meta = [];
      if (news.source === "url") {
        meta.push(news.url);
        if (news.fetch_error) meta.push("⚠ " + news.fetch_error);
      } else {
        meta.push("粘贴文本");
      }
      $("#cNewsMeta").textContent = meta.join(" · ");
    }

    // Related-news box: short summary list. Only shown when the run actually
    // carried related items; otherwise the box is hidden so the page does not
    // grow an empty section.
    $("#cRelatedBox").hidden = !related.length;
    if (related.length) {
      $("#cRelatedList").innerHTML = related
        .map((item) => `<li>
          <span class="related-title">《${esc(item.title || "(无题)")}》</span>
          ${item.source === "url" ? `<span class="related-source"> · <a href="${esc(item.url)}" target="_blank" rel="noopener">${esc(item.url)}</a></span>` : `<span class="related-source"> · 粘贴文本</span>`}
          ${item.fetch_error ? `<span class="warn"> · ⚠ ${esc(item.fetch_error)}</span>` : ""}
        </li>`)
        .join("");
    }

    $("#cSummaryBox").hidden = !run.summary;
    $("#cSummary").textContent = run.summary || "";

    const stats = run.stats || {};
    $("#cOverall").innerHTML = [
      metric(t("commentary.m_total", "参与人数"), stats.total, ""),
      metric(t("commentary.m_spoke", "出声人数"), stats.spoke, ""),
      metric(
        t("commentary.m_strength", "平均强度"),
        stats.avg_strength != null ? stats.avg_strength : "—",
        "/ 100"
      ),
      metric(
        t("commentary.m_strongest", "最坚定"),
        stats.strongest ? `${stats.strongest.name}（${stats.strongest.stance}）` : "—",
        stats.strongest ? `× ${stats.strongest.strength}` : ""
      ),
    ].join("");

    renderStanceBars(stats.stance_counts || {}, stats.total || 1);
    renderCards(run.nodes || []);
  }

  function metric(label, value, suffix) {
    return `<div class="disaster-metric">
      <span class="label">${esc(label)}</span>
      <b>${esc(value == null ? "—" : value)}</b><span class="suffix">${esc(suffix)}</span>
    </div>`;
  }

  function renderStanceBars(counts, total) {
    // Server-defined order first (the four stances the prompt offers), then
    // "其他" if any reply landed off-vocabulary. Anything past those is the
    // same bucket.
    const order = ["支持", "反对", "中立", "质疑", "其他"];
    const rows = order
      .filter((stance) => counts[stance])
      .map((stance) => [stance, counts[stance]]);
    if (!rows.length) {
      $("#cStanceBars").innerHTML = `<p class="disaster-empty">${esc(t("commentary.no_stance", "这次没人发言"))}</p>`;
      return;
    }
    $("#cStanceBars").innerHTML = rows.map(([stance, n]) => `<div class="disaster-bar">
      <span class="bar-label">${esc(stance)}</span>
      <span class="bar-track"><i style="width:${Math.round((n / total) * 100)}%"></i></span>
      <span class="bar-n">${n}</span>
    </div>`).join("");
  }

  function renderCards(nodes) {
    if (!nodes.length) {
      $("#cCards").innerHTML = `<p class="disaster-empty">${esc(t("commentary.no_comments", "没有人评论"))}</p>`;
      return;
    }
    // Strongest first: a comment you can scroll past fast is better than one
    // you have to read past slow. The "其他" bucket always sinks.
    const ranked = nodes.slice().sort((a, b) => (b.strength || 0) - (a.strength || 0));
    $("#cCards").innerHTML = ranked.map(cardHtml).join("");
  }

  function cardHtml(node) {
    const tag = STANCE_TAG[node.stance] || "is-other";
    const strength = Math.max(0, Math.min(100, Number(node.strength) || 0));
    // 5 dots is what disaster.js uses for panic, so the strength bar reads at
    // a glance to anyone who has played the other game.
    const dots = "●".repeat(Math.round(strength / 20)) + "○".repeat(5 - Math.round(strength / 20));
    const meta = [node.age ? node.age + "岁" : "", node.job || ""].filter(Boolean).join(" · ");
    return `<article class="disaster-card">
      <header>
        <span class="name">#${node.agent_id} ${esc(node.name)}</span>
        <span class="tag ${esc(tag)}">${esc(node.stance || "其他")}</span>
      </header>
      <p class="detail">${esc(node.comment || "(没说话)")}</p>
      ${meta ? `<p class="meta-line">${esc(meta)}</p>` : ""}
      <footer>
        <span class="panic" title="${esc(t("commentary.strength", "表态强度"))}">${dots}</span>
        ${node.error ? `<span class="help is-error">${esc(node.error)}</span>` : ""}
      </footer>
    </article>`;
  }

  function setStatus(message, isError) {
    const el = $("#cStatus");
    el.className = "disaster-status" + (isError ? " is-error" : "");
    el.textContent = message;
  }

  function setProgress(pct) {
    $("#cBar").style.width = pct + "%";
    $("#cPct").textContent = pct + "%";
  }

  // -- history ------------------------------------------------------------
  async function loadHistory() {
    const ul = $("#cHistory");
    try {
      const resp = await fetch("/api/games/commentary/runs");
      const data = await resp.json();
      const runs = data.runs || [];
      if (!runs.length) {
        ul.innerHTML = `<li class="disaster-empty">${esc(t("commentary.no_history", "还没有评论"))}</li>`;
        return;
      }
      ul.innerHTML = runs.map((r) => `<li>
        <button type="button" data-job="${esc(r.job_id)}">
          <span class="who">${esc(r.title || "(无题)")}${r.related_count ? ` <small>· +${r.related_count} 相关</small>` : ""}</span>
          <span class="meta">${r.total || 0} ${esc(t("commentary.people", "人"))} · ${esc(r.source || "")}${r.url ? ` · ${esc(r.url.slice(0, 28))}…` : ""}</span>
        </button>
      </li>`).join("");
      Array.from(ul.querySelectorAll("button[data-job]")).forEach((btn) => {
        btn.addEventListener("click", () => openRun(btn.getAttribute("data-job")));
      });
    } catch (err) {
      ul.innerHTML = `<li class="disaster-empty is-error">${esc(String(err))}</li>`;
    }
  }

  async function openRun(jobId) {
    try {
      const resp = await fetch("/api/games/commentary/jobs/" + encodeURIComponent(jobId));
      const rec = await resp.json();
      if (!resp.ok) throw new Error(rec.error || "HTTP " + resp.status);
      state.run = rec.result;
      render();
      setStatus(t("commentary.viewing", "回看已完成的评论"));
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