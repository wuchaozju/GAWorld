// 小说局 (Novel Writer) — front-end controller.
//
// Three server calls drive the page:
//
//   GET  /api/games/novel/catalogue     -> style presets, limits
//   GET  /api/games/novel/agents?city=… -> the roster to pick from
//   POST /api/games/novel/run           -> {job_id}; poll /jobs/<id> for progress,
//                                          then read .result for the finished novel
//
// The right column switches between three states:
//   1. idle hint (no run yet)
//   2. progress bar (run in flight; polls every second)
//   3. finished novel (cover, cast, table of contents, chapter reader)
//
// Each chapter is rendered as a card with a heading and a single flowing
// paragraph block — Markdown would be over-formatting for a novel page, and
// the prompt already strips markdown artefacts from the model output.

(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&", "<": "<", ">": ">", '"': "&quot;", "'": "&#39;",
  }[c]));
  const nl2br = (s) => esc(s).replace(/\n\n+/g, "<br/><br/>").replace(/\n/g, "<br/>");
  const t = (key, fallback) => {
    const value = typeof __ === "function" ? __(key) : "";
    return !value || value === key ? fallback : value;
  };

  const CUSTOM_STYLE = "__custom__";

  const state = {
    city: null,
    agents: [],
    picked: new Set(),
    styles: [],
    style: null,             // resolved style dict (or null until catalogue loaded)
    jobId: null,
    jobTimer: null,
    novel: null,             // finished novel result
    maxAgents: 6,
  };

  const exporter = GAWorldGameExport.attach(() => state.novel && {
    game: "novel",
    label: state.novel.title || "novel",
    markdown: GAWorldGameExport.novel(state.novel),
  });

  async function init() {
    $("#nRunBtn").addEventListener("click", startRun);
    $("#nPickNone").addEventListener("click", () => { state.picked.clear(); renderAgents(); });
    $("#nCity").addEventListener("change", () => {
      state.city = $("#nCity").value;
      state.picked.clear();
      loadAgents();
    });
    $("#nStyle").addEventListener("change", renderStyleText);
    $("#nTabReader").addEventListener("click", () => showPane("reader"));
    $("#nTabViz").addEventListener("click", () => showPane("viz"));
    $("#nCustomStyleText").addEventListener("input", () => {/* just enable/disable Run */});
    await Promise.all([loadCities().then(loadAgents), loadCatalogue()]);
    loadHistory();
  }

  // -- catalogue ----------------------------------------------------------
  async function loadCatalogue() {
    const resp = await fetch("/api/games/novel/catalogue");
    const data = await resp.json();
    state.styles = data.styles || [];
    state.maxAgents = data.max_agents || 6;

    const sel = $("#nStyle");
    sel.innerHTML = state.styles
      .map((s) => `<option value="${esc(s.id)}">${esc(s.title)}</option>`)
      .concat([`<option value="${CUSTOM_STYLE}">${esc(t("novel.custom_option", "自己写一段…"))}</option>`])
      .join("");
    sel.value = state.styles[0] ? state.styles[0].id : CUSTOM_STYLE;
    state.style = state.styles[0] || null;
    renderStyleText();
  }

  function renderStyleText() {
    const sel = $("#nStyle");
    const customBlock = $("#nCustomStyleBlock");
    if (sel.value === CUSTOM_STYLE) {
      customBlock.hidden = false;
      state.style = null;
      $("#nStyleText").textContent = "";
    } else {
      customBlock.hidden = true;
      state.style = state.styles.find((s) => s.id === sel.value) || null;
      $("#nStyleText").textContent = state.style ? state.style.text : "";
    }
  }

  // -- cities / agents ----------------------------------------------------
  async function loadCities() {
    const sel = $("#nCity");
    try {
      const resp = await fetch("/api/city/catalogue");
      const data = await resp.json();
      const cities = data.cities || [];
      sel.innerHTML = cities
        .map((c) => `<option value="${esc(c.slug)}">${esc(c.display_name || c.name || c.slug)}</option>`)
        .join("");
      const preferred = data.selected != null ? data.selected : (cities[0] && cities[0].slug);
      sel.value = preferred || "";
      state.city = sel.value;
    } catch (e) {
      sel.innerHTML = `<option value="">默认世界</option>`;
      state.city = "";
    }
  }

  async function loadAgents() {
    const list = $("#nAgents");
    list.innerHTML = `<li class="disaster-empty">加载中…</li>`;
    try {
      const resp = await fetch(`/api/games/novel/agents?city=${encodeURIComponent(state.city || "")}`);
      const data = await resp.json();
      state.agents = data.agents || [];
    } catch (e) {
      state.agents = [];
    }
    renderAgents();
  }

  function renderAgents() {
    const list = $("#nAgents");
    if (!state.agents.length) {
      list.innerHTML = `<li class="disaster-empty">${esc(t("novel.agents_empty", "没有可挑选的居民"))}</li>`;
    } else {
      list.innerHTML = state.agents
        .map((a) => {
          const picked = state.picked.has(a.id);
          const disabled = !picked && state.picked.size >= state.maxAgents;
          return `
            <li>
              <label style="opacity:${disabled ? 0.5 : 1}">
                <input type="checkbox" data-id="${a.id}" ${picked ? "checked" : ""} ${disabled ? "disabled" : ""} />
                <span class="who">#${a.id} ${esc(a.name)}</span>
                <span class="meta">${esc(a.age || "")} · ${esc(a.gender || "")} · ${esc(a.job || "")}</span>
              </label>
            </li>`;
        })
        .join("");
      list.querySelectorAll("input[type=checkbox]").forEach((cb) => {
        cb.addEventListener("change", () => {
          const id = parseInt(cb.getAttribute("data-id"), 10);
          if (cb.checked) state.picked.add(id); else state.picked.delete(id);
          renderAgents();
        });
      });
    }
    $("#nPicked").textContent = String(state.picked.size);
  }

  // -- run ----------------------------------------------------------------
  async function startRun() {
    const outline = $("#nOutline").value.trim();
    if (!outline) {
      alert(t("novel.outline_required", "先填一段故事大纲"));
      $("#nOutline").focus();
      return;
    }
    if (state.picked.size < 2) {
      alert(t("novel.agents_required", "至少挑 2 个居民当主角"));
      return;
    }
    if (state.picked.size > state.maxAgents) {
      alert(`最多 ${state.maxAgents} 人`);
      return;
    }

    let styleId = $("#nStyle").value;
    let styleCustom = null;
    if (styleId === CUSTOM_STYLE) {
      const text = $("#nCustomStyleText").value.trim();
      if (!text) {
        alert(t("novel.custom_style_required", "填一段自定义风格"));
        return;
      }
      styleCustom = {
        title: t("novel.custom_option", "自定义风格"),
        text,
        point_of_view: $("#nCustomStylePov").value,
      };
      styleId = "";
    }

    const targetWords = Math.max(1000, Math.min(80000, parseInt($("#nTargetWords").value, 10) || 10000));

    const payload = {
      city: state.city || "",
      agent_ids: [...state.picked].sort((a, b) => a - b),
      outline,
      target_words: targetWords,
      style_id: styleId,
      style_custom: styleCustom,
      title_hint: $("#nTitleHint").value.trim(),
    };

    state.novel = null;
    exporter.sync();
    $("#nResult").hidden = true;
    $("#nIdle").hidden = false;
    $("#nStatus").textContent = t("novel.starting", "提交任务…");

    try {
      const resp = await fetch("/api/games/novel/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await resp.json();
      if (!resp.ok || !body.job_id) {
        alert(body.error || t("novel.failed", "提交失败"));
        $("#nStatus").textContent = t("novel.idle", "还没开始");
        return;
      }
      state.jobId = body.job_id;
      poll();
    } catch (e) {
      $("#nStatus").textContent = t("novel.failed", "提交失败");
    }
  }

  function poll() {
    if (state.jobTimer) clearInterval(state.jobTimer);
    let tries = 0;
    const maxTries = 600; // ~10 minutes
    state.jobTimer = setInterval(async () => {
      tries += 1;
      try {
        const resp = await fetch(`/api/games/novel/jobs/${encodeURIComponent(state.jobId)}`);
        const data = await resp.json();
        const pct = Math.round((data.progress || 0) * 100);
        $("#nBar").style.width = pct + "%";
        $("#nPct").textContent = pct + "%";
        if (data.message) $("#nStatus").textContent = data.message;
        if (data.status === "done") {
          clearInterval(state.jobTimer);
          state.jobTimer = null;
          state.novel = data.result;
          renderNovel();
          loadHistory();
        } else if (data.status === "failed" || tries > maxTries) {
          clearInterval(state.jobTimer);
          state.jobTimer = null;
          $("#nStatus").textContent = t("novel.failed", "生成失败") + "：" + (data.error || "");
        }
      } catch (e) {
        // network blip — keep polling
      }
    }, 1000);
  }

  // -- render finished novel ---------------------------------------------
  function renderNovel() {
    if (!state.novel) return;
    const novel = state.novel;
    $("#nIdle").hidden = true;
    $("#nResult").hidden = false;
    $("#nTitle").textContent = t("novel.section_board", "小说");
    $("#nStatus").textContent = t("novel.complete", "已完成");

    $("#nBookTitle").textContent = novel.title || "未命名";
    $("#nPremise").textContent = novel.premise || "";
    $("#nBackCover").textContent = novel.back_cover || "";
    $("#nCast").innerHTML = (novel.cast || [])
      .map((c) => `<span class="novel-cast-tag"><b>${esc(c.name)}</b><i>${esc(c.role || "")}</i></span>`)
      .join("");
    const stats = novel.stats || {};
    $("#nStats").innerHTML = `
      <span>${esc(t("novel.stat_chapters", "章数"))}：${stats.chapters || (novel.chapters || []).length}</span>
      <span>${esc(t("novel.stat_total_words", "总字数"))}：${stats.total_words || 0}</span>
      <span>${esc(t("novel.stat_target_words", "目标"))}：${stats.target_words || novel.target_words || 0}</span>
      <span>${esc(t("novel.stat_actual_words", "实写/目标"))}：${stats.on_target ? "✓" : "≈"}</span>
    `;

    const toc = $("#nToc");
    toc.innerHTML = (novel.chapters || []).map((c) => {
      return `<li><a href="#chapter-${c.chapter}">第${c.chapter}章《${esc(c.title)}》<span class="muted">${esc(c.word_count || 0)}字</span></a></li>`;
    }).join("");

    const reader = $("#nChapters");
    reader.innerHTML = (novel.chapters || []).map((c) => `
      <article class="novel-chapter" id="chapter-${c.chapter}">
        <h2>第${c.chapter}章　${esc(c.title)}</h2>
        <p class="muted novel-chapter-meta">${esc(c.word_count || 0)}字 · ${esc((c.characters || []).map((id) => "#" + id).join(" "))}</p>
        <div class="novel-chapter-body">${nl2br(c.text || "")}</div>
      </article>
    `).join("");
    reader.scrollTop = 0;

    // Default to the reader pane after a fresh render.
    showPane("reader");

    renderFlowChart(novel);
    renderArcChart(novel);
    renderNetChart(novel);
  }

  // -- tabs ---------------------------------------------------------------
  function showPane(name) {
    const reader = $("#nReaderPane");
    const viz = $("#nVizPane");
    const tabReader = $("#nTabReader");
    const tabViz = $("#nTabViz");
    if (name === "viz") {
      reader.hidden = true;
      viz.hidden = false;
      tabReader.classList.remove("is-active");
      tabViz.classList.add("is-active");
      tabReader.setAttribute("aria-selected", "false");
      tabViz.setAttribute("aria-selected", "true");
    } else {
      reader.hidden = false;
      viz.hidden = true;
      tabReader.classList.add("is-active");
      tabViz.classList.remove("is-active");
      tabReader.setAttribute("aria-selected", "true");
      tabViz.setAttribute("aria-selected", "false");
    }
  }

  // -- viz: chapter flow --------------------------------------------------
  // A left-to-right chain of nodes; width scales with chapter word count,
  // fill colour scales with how many cast members appear in the chapter.
  function renderFlowChart(novel) {
    const host = $("#nFlowChart");
    const chapters = novel.chapters || [];
    if (!chapters.length) { host.innerHTML = ""; return; }
    const castCount = Math.max(1, (novel.cast || []).length);
    const maxWords = Math.max(1, ...chapters.map((c) => c.word_count || 0));
    const nodeW = 90;
    const gap = 26;
    const height = 96;
    const width = chapters.length * (nodeW + gap) + gap;
    const y = 36;

    const nodes = chapters.map((c, i) => {
      const x = gap + i * (nodeW + gap);
      const ratio = (c.word_count || 0) / maxWords;
      const castInChapter = (c.characters || []).length;
      const intensity = Math.min(1, castInChapter / castCount);
      const fill = `color-mix(in srgb, var(--green, #0e7a58) ${20 + Math.round(intensity * 60)}%, var(--card, #fff))`;
      const href = `#chapter-${c.chapter}`;
      return `
        <g class="novel-flow-node" tabindex="0" role="link" data-href="${href}">
          <a href="${href}"><rect x="${x}" y="${y}" width="${nodeW}" height="${height}"
            rx="10" ry="10" fill="${fill}" stroke="var(--line, #dde6de)" stroke-width="1"></rect></a>
          <a href="${href}"><text x="${x + nodeW / 2}" y="${y + 22}" text-anchor="middle"
            class="novel-flow-label">第${c.chapter}章</text></a>
          <a href="${href}"><text x="${x + nodeW / 2}" y="${y + 42}" text-anchor="middle"
            class="novel-flow-title">${esc((c.title || "").slice(0, 7))}</text></a>
          <a href="${href}"><text x="${x + nodeW / 2}" y="${y + 64}" text-anchor="middle"
            class="novel-flow-meta">${(c.word_count || 0)}字</text></a>
          <a href="${href}"><text x="${x + nodeW / 2}" y="${y + 80}" text-anchor="middle"
            class="novel-flow-meta">${castInChapter}人</text></a>
          <title>第${c.chapter}章《${esc(c.title)}》(${c.word_count || 0}字,${castInChapter}个角色)</title>
        </g>`;
    }).join("");

    // Arrows between consecutive chapters.
    const arrows = [];
    for (let i = 0; i < chapters.length - 1; i += 1) {
      const x1 = gap + i * (nodeW + gap) + nodeW;
      const x2 = gap + (i + 1) * (nodeW + gap);
      const midY = y + height / 2;
      arrows.push(`<line x1="${x1}" y1="${midY}" x2="${x2 - 6}" y2="${midY}"
        stroke="var(--line, #dde6de)" stroke-width="2" marker-end="url(#nFlowArrow)"></line>`);
    }

    host.innerHTML = `<svg viewBox="0 0 ${width} ${height + 60}" class="novel-flow-svg" role="img">
      <defs><marker id="nFlowArrow" viewBox="0 0 8 8" refX="7" refY="4"
        markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="var(--line, #dde6de)"></path></marker></defs>
      <g class="novel-flow-arrows">${arrows.join("")}</g>
      <g class="novel-flow-nodes">${nodes}</g>
    </svg>`;
  }

  // -- viz: character arcs ------------------------------------------------
  // One polyline per cast member; X = chapter index, Y = presence score.
  // Drawn as a classic chart with grid lines so a glance tells you
  // "who's present, who drops out, who rises".
  function renderArcChart(novel) {
    const host = $("#nArcChart");
    const chapters = novel.chapters || [];
    const cast = novel.cast || [];
    if (!chapters.length || !cast.length) { host.innerHTML = ""; renderArcLegend([]); return; }

    const W = 720;
    const H = 220;
    const padL = 36, padR = 12, padT = 14, padB = 28;
    const innerW = W - padL - padR;
    const innerH = H - padT - padB;

    const xFor = (i) => chapters.length === 1
      ? padL + innerW / 2
      : padL + (i / (chapters.length - 1)) * innerW;
    const yFor = (score) => padT + (1 - Math.min(100, Math.max(0, score)) / 100) * innerH;

    const colorPalette = ["#0e7a58", "#c04545", "#c9871a", "#5e60ce", "#0b6e8a", "#7a4caf", "#9c6b1e", "#a04e6f"];

    // X-axis ticks: chapter labels every other chapter to avoid clutter.
    const ticks = chapters.map((c, i) => {
      const x = xFor(i);
      return `<g>
        <line x1="${x}" y1="${padT}" x2="${x}" y2="${padT + innerH}" stroke="var(--line, #dde6de)" stroke-width="0.5"></line>
        <text x="${x}" y="${padT + innerH + 16}" text-anchor="middle" class="novel-arc-tick">${c.chapter}</text>
      </g>`;
    }).join("");

    // Y-axis: 0 / 50 / 100 with light guides.
    const yGuides = [0, 50, 100].map((v) => {
      const y = yFor(v);
      return `<g>
        <line x1="${padL}" y1="${y}" x2="${padL + innerW}" y2="${y}" stroke="var(--line, #dde6de)" stroke-width="0.5" stroke-dasharray="2 3"></line>
        <text x="${padL - 6}" y="${y + 4}" text-anchor="end" class="novel-arc-tick">${v}</text>
      </g>`;
    }).join("");

    // One polyline per cast member; pad missing scores with 0 so a cast
    // member absent from a chapter simply sits on the floor.
    const lines = cast.map((member, idx) => {
      const color = colorPalette[idx % colorPalette.length];
      const pts = chapters.map((c, i) => {
        const score = (c.presence && c.presence[String(member.agent_id)] != null) ? c.presence[String(member.agent_id)] : 0;
        return [xFor(i), yFor(score)];
      });
      const d = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
      const dots = pts.map((p, i) => `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3" fill="${color}"><title>${esc(member.name)} · 第${chapters[i].chapter}章 ${(c.presence[String(member.agent_id)] || 0)}</title></circle>`).join("");
      return `<g class="novel-arc-line">
        <path d="${d}" fill="none" stroke="${color}" stroke-width="1.8"></path>
        ${dots}
      </g>`;
    }).join("");

    host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="novel-arc-svg" role="img">
      <g class="novel-arc-guides">${yGuides}${ticks}</g>
      <g class="novel-arc-lines">${lines}</g>
    </svg>`;
    renderArcLegend(cast.map((m, i) => ({ name: m.name, role: m.role, color: colorPalette[i % colorPalette.length] })));
  }

  function renderArcLegend(items) {
    const host = $("#nArcLegend");
    if (!items.length) { host.innerHTML = ""; return; }
    host.innerHTML = items.map((it) => `
      <li>
        <i class="novel-arc-dot" style="background:${it.color}"></i>
        <b>${esc(it.name)}</b>
        <span class="muted">${esc(it.role || "")}</span>
      </li>
    `).join("");
  }

  // -- viz: co-presence network ------------------------------------------
  function renderNetChart(novel) {
    const host = $("#nNetChart");
    const cast = novel.cast || [];
    const co = novel.co_occurrences || [];
    if (!cast.length) { host.innerHTML = ""; return; }

    const SIZE = 360;
    const R = 120;
    const NODE_R = 18;
    const cx = SIZE / 2;
    const cy = SIZE / 2;
    const byId = {};
    cast.forEach((c, i) => {
      const angle = (i / cast.length) * Math.PI * 2 - Math.PI / 2;
      byId[c.agent_id] = { x: cx + R * Math.cos(angle), y: cy + R * Math.sin(angle), name: c.name, role: c.role };
    });

    const maxCount = Math.max(1, ...co.map((row) => row.count));
    const ties = co.map((row) => {
      const a = byId[row.a], b = byId[row.b];
      if (!a || !b) return "";
      const width = 1 + (row.count / maxCount) * 5;
      return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"
        class="novel-net-tie" stroke="var(--game-accent, #0e7a58)" stroke-width="${width.toFixed(1)}" opacity="0.65">
        <title>${esc(a.name)} × ${esc(b.name)}：同框 ${row.count} 章</title>
      </line>`;
    }).join("");

    const isolated = [];
    const nodes = cast.map((c) => {
      const p = byId[c.agent_id];
      const partner = co.filter((row) => row.a === c.agent_id || row.b === c.agent_id);
      if (!partner.length) isolated.push(c.name);
      return `<g class="novel-net-node">
        <circle cx="${p.x}" cy="${p.y}" r="${NODE_R}" fill="var(--card, #fff)" stroke="var(--game-accent, #0e7a58)" stroke-width="2"></circle>
        <text x="${p.x}" y="${p.y + 4}" text-anchor="middle" class="novel-net-label">${esc((c.name || "").slice(0, 3))}</text>
        <title>${esc(c.name)}${c.role ? " · " + esc(c.role) : ""}</title>
      </g>`;
    }).join("");

    host.innerHTML = `<svg viewBox="0 0 ${SIZE} ${SIZE}" class="novel-net-svg" role="img">
      <g class="novel-net-ties">${ties}</g>
      <g class="novel-net-nodes">${nodes}</g>
    </svg>`;
    if (isolated.length) {
      host.insertAdjacentHTML("afterend", `<p class="muted novel-net-note">${esc(t("novel.viz_net_isolated", "孤立角色（未与其他人同章）："))}${esc(isolated.join("、"))}</p>`);
    } else {
      const note = host.parentNode.querySelector(".novel-net-note");
      if (note) note.remove();
    }
  }

  // -- history ------------------------------------------------------------
  async function loadHistory() {
    try {
      const resp = await fetch("/api/games/novel/runs");
      const data = await resp.json();
      const runs = data.runs || [];
      const list = $("#nHistory");
      if (!runs.length) {
        list.innerHTML = `<li class="muted">${esc(t("novel.no_history", "暂无"))}</li>`;
        return;
      }
      list.innerHTML = runs.map((r) => `
        <li>
          <button data-job="${esc(r.job_id)}">
            <span class="who">${esc(r.title || "未命名")}</span>
            <span class="meta">${r.actual_words || 0}字 · ${r.chapters || 0}章 · ${esc(r.city || "默认世界")}</span>
          </button>
        </li>
      `).join("");
      list.querySelectorAll("button[data-job]").forEach((btn) => {
        btn.addEventListener("click", () => loadJobResult(btn.getAttribute("data-job")));
      });
    } catch (e) {
      // best-effort
    }
  }

  async function loadJobResult(jobId) {
    try {
      const resp = await fetch(`/api/games/novel/jobs/${encodeURIComponent(jobId)}`);
      const data = await resp.json();
      if (data.status === "done" && data.result) {
        state.novel = data.result;
        renderNovel();
      } else {
        alert(t("novel.not_done", "这本还没完成"));
      }
    } catch (e) {
      // ignore
    }
  }

  // -- boot ---------------------------------------------------------------
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();