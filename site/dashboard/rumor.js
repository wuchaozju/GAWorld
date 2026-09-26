// 谣言扩散局 (Rumor Spread) — front-end controller.
//
// Two server calls carry the page:
//
//   GET  /api/games/rumor/graph  → the derived network for the current
//        selection. Free (no model call), so it runs on every change of the
//        picker: you see the network you are about to infect, and an empty
//        one is visible *before* you pay for a run.
//   POST /api/games/rumor/run    → {job_id}; poll /jobs/<id> for progress,
//        then draw the finished diffusion tree.
//
// The graph is drawn on a circle rather than force-directed: a run is at
// most 14 residents, the layout has to be stable between the preview and the
// result (the same node must not jump), and a circle makes "who reached whom"
// legible without a physics loop.

(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
  const t = (key, fallback) => (typeof __ === "function" ? __(key) : fallback);

  const CUSTOM = "__custom__";
  const SIZE = 460;        // SVG viewBox, square
  const R = 170;           // node ring radius
  const NODE_R = 13;

  const state = {
    city: null,
    agents: [],
    picked: new Set(),
    rumors: [],
    graph: null,    // preview: {nodes, edges, isolated}
    run: null,      // finished run
    roundFilter: null,
    jobId: null,
    jobTimer: null,
    maxAgents: 14,
  };

  async function init() {
    $("#rRunBtn").addEventListener("click", startRun);
    $("#rPickBlock").addEventListener("click", pickBlocks);
    $("#rPickNone").addEventListener("click", () => { state.picked.clear(); afterPick(); });
    $("#rCity").addEventListener("change", () => {
      state.city = $("#rCity").value;
      state.picked.clear();
      loadAgents();
    });
    $("#rRumor").addEventListener("change", renderRumorText);
    await Promise.all([loadCities().then(loadAgents), loadCatalogue()]);
    loadHistory();
  }

  // -- pickers ------------------------------------------------------------
  async function loadCities() {
    const sel = $("#rCity");
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
    const sel = $("#rRumor");
    try {
      const resp = await fetch("/api/games/rumor/catalogue");
      const data = await resp.json();
      state.rumors = data.rumors || [];
      state.maxAgents = data.max_agents || 14;
      sel.innerHTML = state.rumors
        .map((r) => `<option value="${esc(r.id)}">${esc(r.emoji + " " + r.title)}</option>`)
        .join("") + `<option value="${CUSTOM}">✍️ ${esc(t("rumor.custom_option", "自己写一条…"))}</option>`;
      $("#rRounds").max = data.max_rounds || 5;
      $("#rRounds").value = data.default_rounds || 3;
      renderRumorText();
    } catch (err) {
      sel.innerHTML = `<option value="">${esc(String(err))}</option>`;
    }
  }

  function renderRumorText() {
    const id = $("#rRumor").value;
    const custom = id === CUSTOM;
    $("#rCustomBlock").hidden = !custom;
    const found = state.rumors.find((r) => r.id === id);
    $("#rRumorText").textContent = custom
      ? t("rumor.custom_hint", "像在群里传的那样写：听说…")
      : (found ? "「" + found.text + "」" : "");
  }

  async function loadAgents() {
    const list = $("#rAgents");
    if (state.city === null) return;
    list.innerHTML = `<li class="disaster-empty">${esc(t("rumor.loading", "加载中…"))}</li>`;
    try {
      const resp = await fetch("/api/games/agents?city=" + encodeURIComponent(state.city));
      const data = await resp.json();
      state.agents = data.agents || [];
      renderAgents();
      afterPick();
    } catch (err) {
      list.innerHTML = `<li class="disaster-empty is-error">${esc(String(err))}</li>`;
    }
  }

  function renderAgents() {
    const list = $("#rAgents");
    if (!state.agents.length) {
      list.innerHTML = `<li class="disaster-empty">${esc(t("rumor.no_agents", "这座城市暂无居民"))}</li>`;
      return;
    }
    // Group by 小区: ties travel through addresses, so the picker is ordered
    // the way the network is.
    const blocks = new Map();
    state.agents.forEach((a) => {
      const key = a.residence || t("rumor.no_block", "（无住址）");
      if (!blocks.has(key)) blocks.set(key, []);
      blocks.get(key).push(a);
    });
    list.innerHTML = Array.from(blocks.entries())
      .map(([block, people]) => {
        const rows = people
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
        return `<li class="rumor-block"><button type="button" data-block="${esc(block)}">${esc(block)} · ${people.length}</button></li>` + rows;
      })
      .join("");

    Array.from(list.querySelectorAll("input[type=checkbox]")).forEach((box) => {
      box.addEventListener("change", () => {
        const id = parseInt(box.value, 10);
        if (box.checked) state.picked.add(id);
        else state.picked.delete(id);
        if (state.picked.size > state.maxAgents) {
          state.picked.delete(id);
          box.checked = false;
          setStatus(t("rumor.too_many", "最多 14 人"), true);
          return;
        }
        afterPick();
      });
    });
    Array.from(list.querySelectorAll("button[data-block]")).forEach((btn) => {
      btn.addEventListener("click", () => selectBlock(btn.getAttribute("data-block")));
    });
  }

  /** Select everyone living in *blocks* (one name or a list of them). */
  function selectBlock(blocks) {
    const wanted = new Set([].concat(blocks));
    const people = state.agents.filter(
      (a) => wanted.has(a.residence || t("rumor.no_block", "（无住址）"))
    );
    state.picked = new Set(people.slice(0, state.maxAgents).map((a) => a.id));
    renderAgents();
    afterPick();
  }

  /** Two crowded blocks, not one.
   *
   *  Everyone in a single 小区 is a neighbour of everyone else, so one block
   *  is a complete graph and the rumor is everywhere after one hop. Two
   *  blocks give two clusters joined only by the weak ties (same trade, same
   *  age) — and "does it cross?" is the question worth watching. */
  function pickBlocks() {
    const sizes = new Map();
    state.agents.forEach((a) => {
      if (a.residence) sizes.set(a.residence, (sizes.get(a.residence) || 0) + 1);
    });
    if (!sizes.size) return;
    const biggest = Math.max(...sizes.values());
    const floor = Math.max(3, Math.ceil(biggest / 2));
    let pool = Array.from(sizes.keys()).filter((block) => sizes.get(block) >= floor);
    if (pool.length < 2) pool = Array.from(sizes.keys());
    pool = pool.slice();
    const chosen = [];
    while (pool.length && chosen.length < 2) {
      chosen.push(pool.splice(Math.floor(Math.random() * pool.length), 1)[0]);
    }
    selectBlock(chosen);
  }

  /** Refresh the count, the seed picker and the free graph preview. */
  function afterPick() {
    $("#rPicked").textContent = String(state.picked.size);
    const seeds = $("#rSeeds");
    const chosen = new Set(Array.from(seeds.selectedOptions || []).map((o) => parseInt(o.value, 10)));
    seeds.innerHTML = state.agents
      .filter((a) => state.picked.has(a.id))
      .map((a) => `<option value="${a.id}"${chosen.has(a.id) ? " selected" : ""}>#${a.id} ${esc(a.name)}</option>`)
      .join("");
    loadGraph();
  }

  async function loadGraph() {
    if (state.picked.size < 2) {
      state.graph = null;
      $("#rGraphHint").textContent = t("rumor.need_two", "至少选两个人，一个人传不开。");
      drawGraph();
      return;
    }
    try {
      const url = "/api/games/rumor/graph?city=" + encodeURIComponent(state.city) +
        "&agent_ids=" + Array.from(state.picked).join(",");
      const resp = await fetch(url);
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "HTTP " + resp.status);
      state.graph = data;
      const lonely = (data.isolated || []).length;
      $("#rGraphHint").textContent =
        `${data.edges.length} ${t("rumor.ties", "条关系")}` +
        (lonely ? ` · ${lonely} ${t("rumor.isolated", "人没有任何关系，传不到他们")}` : "");
      if (!state.run) drawGraph();
    } catch (err) {
      $("#rGraphHint").textContent = String(err.message || err);
    }
  }

  // -- the run ------------------------------------------------------------
  async function startRun() {
    if (state.picked.size < 2) return setStatus(t("rumor.need_two", "至少选两个人，一个人传不开。"), true);
    const id = $("#rRumor").value;
    const body = {
      city: state.city,
      agent_ids: Array.from(state.picked),
      rumor_id: id === CUSTOM ? "" : id,
      rounds: Math.max(1, parseInt($("#rRounds").value, 10) || 3),
      seeds: Array.from($("#rSeeds").selectedOptions || []).map((o) => parseInt(o.value, 10)),
    };
    if (id === CUSTOM) {
      body.custom = { title: $("#rCustomTitle").value.trim(), text: $("#rCustomText").value };
    }

    $("#rRunBtn").disabled = true;
    setProgress(0);
    setStatus(t("rumor.running", "传开中…"));
    try {
      const resp = await fetch("/api/games/rumor/run", {
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
      $("#rRunBtn").disabled = false;
    }
  }

  function pollJob() {
    if (!state.jobId) return;
    clearInterval(state.jobTimer);
    state.jobTimer = setInterval(async () => {
      try {
        const resp = await fetch("/api/games/rumor/jobs/" + encodeURIComponent(state.jobId));
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const rec = await resp.json();
        setProgress(Math.round((rec.progress || 0) * 100));
        if (rec.status === "running") {
          setStatus(rec.message || t("rumor.running", "传开中…"));
          return;
        }
        stopPolling();
        if (rec.status === "done") {
          state.run = rec.result;
          state.roundFilter = null;
          render();
          setStatus(t("rumor.done", "传完了"));
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
    $("#rRunBtn").disabled = false;
  }

  // -- rendering ----------------------------------------------------------
  function render() {
    const run = state.run;
    $("#rIdle").hidden = !!run;
    $("#rResult").hidden = !run;
    if (!run) return drawGraph();

    const r = run.rumor || {};
    const stats = run.stats || {};
    $("#rTitle").textContent = `${r.emoji || ""} ${r.title || ""} · ${stats.reached}/${stats.total} ${t("rumor.heard", "人听说")}`;

    $("#rSummaryBox").hidden = !run.summary;
    $("#rSummary").textContent = run.summary || "";

    const spread = stats.total ? Math.round((stats.reached / stats.total) * 100) : 0;
    $("#rOverall").innerHTML = [
      metric(t("rumor.m_reach", "触达"), stats.reached + "/" + stats.total, "· " + spread + "%"),
      metric(t("rumor.m_believers", "相信"), stats.believers, ""),
      metric(t("rumor.m_belief", "平均信任度"), stats.avg_belief, "%"),
      metric(
        t("rumor.m_super", "最大传播者"),
        stats.superspreader ? stats.superspreader.name : "—",
        stats.superspreader ? "×" + stats.superspreader.n : ""
      ),
    ].join("");

    renderRoundTabs();
    drawGraph();
    renderRounds();
    renderCards();
  }

  function metric(label, value, suffix) {
    return `<div class="disaster-metric">
      <span class="label">${esc(label)}</span>
      <b>${esc(value == null ? "—" : value)}</b><span class="suffix">${esc(suffix)}</span>
    </div>`;
  }

  function renderRoundTabs() {
    const rounds = (state.run && state.run.rounds) || [];
    const tabs = $("#rRoundTabs");
    if (!rounds.length) return (tabs.innerHTML = "");
    const make = (value, label) => {
      const on = String(state.roundFilter) === String(value) ? " is-on" : "";
      return `<button type="button" class="rumor-tab${on}" data-round="${value}">${esc(label)}</button>`;
    };
    tabs.innerHTML = [make("null", t("rumor.all_rounds", "全部"))]
      .concat(rounds.map((r) => make(r.round, t("rumor.round", "第") + (r.round + 1) + t("rumor.round_suffix", "轮"))))
      .join("");
    Array.from(tabs.querySelectorAll("button[data-round]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        const raw = btn.getAttribute("data-round");
        state.roundFilter = raw === "null" ? null : parseInt(raw, 10);
        renderRoundTabs();
        drawGraph();
      });
    });
  }

  /** Circle layout. Works for a preview (no run yet) and for a result. */
  function drawGraph() {
    const box = $("#rGraph");
    const run = state.run;
    const source = run || state.graph;
    if (!source || !(source.nodes || []).length) {
      box.innerHTML = `<p class="disaster-empty">${esc(t("rumor.no_graph", "选两个以上的居民，这里会画出他们的关系网。"))}</p>`;
      return;
    }
    const nodes = source.nodes;
    const at = {};
    const cx = SIZE / 2;
    const cy = SIZE / 2;
    nodes.forEach((node, index) => {
      const angle = (index / nodes.length) * Math.PI * 2 - Math.PI / 2;
      at[node.agent_id] = { x: cx + R * Math.cos(angle), y: cy + R * Math.sin(angle) };
    });

    const ties = (source.edges || [])
      .map((edge) => {
        const a = at[edge.a];
        const b = at[edge.b];
        if (!a || !b) return "";
        return `<line class="tie" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"
          stroke-width="${(edge.closeness * 3).toFixed(1)}"><title>${esc(edge.label)}</title></line>`;
      })
      .join("");

    const shown = (run ? run.transmissions || [] : []).filter(
      (item) => state.roundFilter == null || item.round === state.roundFilter
    );
    const arrows = shown
      .map((item) => {
        const a = at[item.from];
        const b = at[item.to];
        if (!a || !b) return "";
        // Stop short of the target so the head is visible outside the circle.
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const len = Math.max(1, Math.hypot(dx, dy));
        const ex = b.x - (dx / len) * (NODE_R + 4);
        const ey = b.y - (dy / len) * (NODE_R + 4);
        return `<line class="hop is-${esc(item.kind)}" x1="${a.x}" y1="${a.y}" x2="${ex}" y2="${ey}"
          marker-end="url(#rumor-arrow-${esc(item.kind)})"><title>${esc(item.label || "")} · ${t("rumor.round", "第")}${item.round + 1}${t("rumor.round_suffix", "轮")}</title></line>`;
      })
      .join("");

    const dots = nodes
      .map((node) => {
        const p = at[node.agent_id];
        const heard = node.heard_round != null;
        const cls = !run || !heard ? "is-quiet" : node.believes ? "is-believer" : "is-doubter";
        const seed = run && (run.seeds || []).includes(node.agent_id) ? " is-seed" : "";
        const label = String(node.name || "").slice(0, 3);
        return `<g class="node ${cls}${seed}">
          <circle cx="${p.x}" cy="${p.y}" r="${NODE_R}"></circle>
          <text x="${p.x}" y="${p.y + 3.5}" text-anchor="middle">${esc(label)}</text>
          <title>#${node.agent_id} ${esc(node.name)}${node.job ? " · " + esc(node.job) : ""}${
            run && heard ? ` · ${t("rumor.belief", "信")} ${node.belief}% · ${esc(node.action || "")}` : ""
          }</title>
        </g>`;
      })
      .join("");

    box.innerHTML = `<svg viewBox="0 0 ${SIZE} ${SIZE}" class="rumor-svg" role="img">
      <defs>
        ${arrowMarker("rumor", "rumor-arrow-rumor")}
        ${arrowMarker("question", "rumor-arrow-question")}
        ${arrowMarker("debunk", "rumor-arrow-debunk")}
      </defs>
      <g class="ties">${ties}</g>
      <g class="hops">${arrows}</g>
      <g class="nodes">${dots}</g>
    </svg>`;
  }

  function arrowMarker(kind, id) {
    return `<marker id="${id}" class="arrow is-${kind}" viewBox="0 0 8 8" refX="6" refY="4"
      markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L8,4 L0,8 z"></path></marker>`;
  }

  function renderRounds() {
    const rounds = (state.run && state.run.rounds) || [];
    const total = (state.run.stats || {}).total || 1;
    $("#rRoundBars").innerHTML = rounds
      .map((r) => `<div class="rumor-round">
        <span class="label">${esc(t("rumor.round", "第"))}${r.round + 1}${esc(t("rumor.round_suffix", "轮"))}</span>
        <span class="bar-track">
          <i class="is-reach" style="width:${Math.round((r.reached / total) * 100)}%"></i>
          <i class="is-believe" style="width:${Math.round((r.believers / total) * 100)}%"></i>
        </span>
        <span class="n">${r.reached} ${esc(t("rumor.heard", "人听说"))} · ${r.believers} ${esc(t("rumor.believing", "人信"))}</span>
      </div>`)
      .join("");
  }

  function renderCards() {
    const run = state.run;
    const names = {};
    (run.nodes || []).forEach((n) => { names[n.agent_id] = n.name; });
    $("#rCards").innerHTML = (run.nodes || [])
      .slice()
      .sort((a, b) => (a.heard_round == null ? 99 : a.heard_round) - (b.heard_round == null ? 99 : b.heard_round))
      .map((node) => {
        if (node.heard_round == null) {
          return `<article class="disaster-card is-quiet">
            <header><span class="name">#${node.agent_id} ${esc(node.name)}</span>
            <span class="tag">${esc(t("rumor.never_heard", "没听说"))}</span></header>
            <p class="detail">${esc(t("rumor.out_of_reach", "关系网没有把消息送到这里。"))}</p>
          </article>`;
        }
        const from = node.heard_from != null ? names[node.heard_from] : t("rumor.self_found", "自己刷到的");
        return `<article class="disaster-card">
          <header>
            <span class="name">#${node.agent_id} ${esc(node.name)}</span>
            <span class="tag">${esc(node.action)}</span>
          </header>
          <p class="detail">${esc(t("rumor.round", "第"))}${node.heard_round + 1}${esc(t("rumor.round_suffix", "轮"))}${esc(t("rumor.heard_from", "听说，来自"))}${esc(from)}</p>
          ${node.say ? `<p class="say">「${esc(node.say)}」</p>` : ""}
          <footer>
            <span class="belief ${node.believes ? "is-believer" : "is-doubter"}">${esc(t("rumor.belief", "信"))} ${node.belief}%</span>
            ${node.spoke_rounds.length > 1 ? `<span class="help">${esc(t("rumor.changed", "被辟谣后改口"))}</span>` : ""}
          </footer>
        </article>`;
      })
      .join("");
  }

  function setStatus(message, isError) {
    const el = $("#rStatus");
    el.className = "disaster-status" + (isError ? " is-error" : "");
    el.textContent = message;
  }

  function setProgress(pct) {
    $("#rBar").style.width = pct + "%";
    $("#rPct").textContent = pct + "%";
  }

  async function loadHistory() {
    const ul = $("#rHistory");
    try {
      const resp = await fetch("/api/games/rumor/runs");
      const data = await resp.json();
      const runs = data.runs || [];
      if (!runs.length) {
        ul.innerHTML = `<li class="disaster-empty">${esc(t("rumor.no_history", "还没有记录"))}</li>`;
        return;
      }
      ul.innerHTML = runs
        .map((r) => `<li>
          <button type="button" data-job="${esc(r.job_id)}">
            <span class="who">${esc((r.emoji || "") + " " + (r.rumor || ""))}</span>
            <span class="meta">${r.reached}/${r.total} ${esc(t("rumor.heard", "人听说"))} · ${r.believers} ${esc(t("rumor.believing", "人信"))}</span>
          </button>
        </li>`)
        .join("");
      Array.from(ul.querySelectorAll("button[data-job]")).forEach((btn) => {
        btn.addEventListener("click", () => openRun(btn.getAttribute("data-job")));
      });
    } catch (err) {
      ul.innerHTML = `<li class="disaster-empty is-error">${esc(String(err))}</li>`;
    }
  }

  async function openRun(jobId) {
    try {
      const resp = await fetch("/api/games/rumor/jobs/" + encodeURIComponent(jobId));
      const rec = await resp.json();
      if (!resp.ok) throw new Error(rec.error || "HTTP " + resp.status);
      state.run = rec.result;
      state.roundFilter = null;
      render();
      setStatus(t("rumor.viewing", "回看已完成的一场"));
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
