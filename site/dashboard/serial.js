
var gwHTML = globalThis.GAWorldURL ? globalThis.GAWorldURL.html : function (value) { return value; };
var gwURL = globalThis.GAWorldURL ? globalThis.GAWorldURL.url : function (value) { return value; };
// Serial Drama — pick residents, pick a theme, get a multi-episode shot-card script.
//
//   GET  /api/games/serial/catalogue     -> theme presets, style presets, limits
//   GET  /api/games/serial/agents?city=… -> the roster to pick from
//   POST /api/games/serial/run           -> {job_id}; poll /jobs/<id> for progress,
//                                            then result.episodes[i].shots[k] for the script.
//   GET  /api/games/serial/runs          -> finished seasons still in memory
//   GET  /api/games/serial/jobs/<job_id> -> progress + result

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  city: null,
  catalogue: null,
  agents: [],
  picked: new Set(),
  jobId: null,
  pollHandle: null,
  result: null,
};

function apiPath(p) {
  return p;
}

async function api(path, options = {}) {
  const resp = await fetch(path, options);
  let body = null;
  try { body = await resp.json(); } catch (_) { body = null; }
  return { ok: resp.ok, status: resp.status, body };
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function boot() {
  const cat = await api("/api/games/serial/catalogue");
  if (!cat.ok) {
    $("#sStatus").textContent = "加载目录失败：" + (cat.body && cat.body.error || cat.status);
    return;
  }
  state.catalogue = cat.body;

  // Theme options
  const themeSel = $("#sTheme");
  themeSel.innerHTML = gwHTML("");
  for (const t of cat.body.themes) {
    const opt = document.createElement("option");
    opt.value = t.id;
    opt.textContent = `${t.emoji || "🎭"} ${t.title}`;
    themeSel.appendChild(opt);
  }
  themeSel.addEventListener("change", () => {
    syncThemeHint();
    $("#sCustomThemeBlock").hidden = themeSel.value !== "open";
  });
  syncThemeHint();

  // Style options
  const styleSel = $("#sStyle");
  styleSel.innerHTML = gwHTML("");
  for (const s of cat.body.styles) {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = `${s.emoji || "🎨"} ${s.title}`;
    styleSel.appendChild(opt);
  }
  styleSel.addEventListener("change", () => {
    syncStyleHint();
    $("#sCustomStyleBlock").hidden = styleSel.value !== "custom";
  });
  syncStyleHint();

  // City picker
  await loadCities();

  // Pickers
  $("#sPickNone").addEventListener("click", () => {
    state.picked.clear();
    renderAgents();
  });
  $("#sRunBtn").addEventListener("click", startRun);

  // Tabs
  $("#sTabScript").addEventListener("click", () => switchTab("script"));
  $("#sTabShots").addEventListener("click", () => switchTab("shots"));
  $("#sTabPrompts").addEventListener("click", () => switchTab("prompts"));

  $("#sCopyShots").addEventListener("click", copyShotsJson);
  $("#sDownloadShots").addEventListener("click", downloadShotsJson);

  $("#serialExportBtn").addEventListener("click", exportMarkdown);

  await loadHistory();
}

function syncThemeHint() {
  const t = (state.catalogue.themes || []).find((x) => x.id === $("#sTheme").value);
  $("#sThemeText").textContent = t ? `${t.tone || ""}${t.prompt_seed ? " · " + t.prompt_seed : ""}` : "";
}

function syncStyleHint() {
  const s = (state.catalogue.styles || []).find((x) => x.id === $("#sStyle").value);
  $("#sStyleText").textContent = s ? `${s.shot_style || s.text || ""}` : "";
}

async function loadCities() {
  const citySel = $("#sCity");
  citySel.innerHTML = gwHTML("");
  try {
    const resp = await fetch("/api/city/catalogue");
    if (resp.ok) {
      const data = await resp.json();
      const cities = data.cities || [];
      for (const c of cities) {
        const opt = document.createElement("option");
        opt.value = c.slug || c.id || "";
        opt.textContent = c.display_name || c.name || c.title || c.slug || "默认世界";
        citySel.appendChild(opt);
      }
      const preferred = data.selected != null ? data.selected : (cities[0] && (cities[0].slug || cities[0].id));
      citySel.value = preferred || "";
    }
  } catch (_) {}
  if (!citySel.options.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "默认世界";
    citySel.appendChild(opt);
  }
  state.city = citySel.value;
  citySel.addEventListener("change", async () => {
    state.city = citySel.value;
    await loadAgents();
  });
  await loadAgents();
}

async function loadAgents() {
  const resp = await api(`/api/games/serial/agents?city=${encodeURIComponent(state.city || "")}`);
  if (!resp.ok) {
    $("#sStatus").textContent = "读取居民失败：" + (resp.body && resp.body.error || resp.status);
    return;
  }
  state.agents = resp.body.agents || [];
  state.picked.clear();
  renderAgents();
}

function renderAgents() {
  const list = $("#sAgents");
  list.innerHTML = gwHTML("");
  if (!state.agents.length) {
    const empty = document.createElement("li");
    empty.className = "disaster-empty";
    empty.textContent = "这个城市还没有居民 — 切到一个有居民的城市，或先去「城市」面板建一个。";
    list.appendChild(empty);
    $("#sPicked").textContent = "0";
    return;
  }
  for (const agent of state.agents) {
    const li = document.createElement("li");
    li.className = "disaster-row-item" + (state.picked.has(agent.id) ? " is-picked" : "");
    const head = document.createElement("label");
    head.className = "disaster-row-label";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = state.picked.has(agent.id);
    cb.addEventListener("change", () => {
      if (cb.checked) state.picked.add(agent.id);
      else state.picked.delete(agent.id);
      $("#sPicked").textContent = String(state.picked.size);
      li.classList.toggle("is-picked", cb.checked);
    });
    const text = document.createElement("span");
    text.innerHTML = gwHTML(`<b>#${agent.id} ${escapeHtml(agent.name || "")}</b> · ${escapeHtml(agent.age || "")} · ${escapeHtml(agent.job || "")}`);
    head.appendChild(cb);
    head.appendChild(text);
    li.appendChild(head);
    list.appendChild(li);
  }
  $("#sPicked").textContent = String(state.picked.size);
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

// ---------------------------------------------------------------------------
// Run / poll
// ---------------------------------------------------------------------------

async function startRun() {
  const agentIds = Array.from(state.picked);
  if (agentIds.length < state.catalogue.min_agents || agentIds.length > state.catalogue.max_agents) {
    $("#sStatus").textContent = `主演数要在 ${state.catalogue.min_agents}–${state.catalogue.max_agents} 之间`;
    return;
  }
  const payload = {
    city: state.city || "",
    agent_ids: agentIds,
    theme_id: $("#sTheme").value,
    style_id: $("#sStyle").value,
    episodes: clampInt($("#sEpisodes").value, state.catalogue.min_episodes, state.catalogue.max_episodes, state.catalogue.default_episodes),
    shots_per_episode: clampInt($("#sShotsPerEpisode").value, state.catalogue.min_shots_per_episode, state.catalogue.max_shots_per_episode, state.catalogue.default_shots_per_episode),
    seconds_per_episode: clampInt($("#sSeconds").value, state.catalogue.min_episode_seconds, state.catalogue.max_episode_seconds, state.catalogue.default_episode_seconds),
    title_hint: $("#sTitleHint").value,
    user_brief: $("#sBrief").value,
  };
  if (payload.theme_id === "open") {
    const tone = $("#sCustomThemeTone").value.trim();
    if (!tone) {
      $("#sStatus").textContent = "自定义题材要写一句话核心情境";
      return;
    }
    payload.theme_custom = { tone, prompt_seed: $("#sCustomThemeSeed").value.trim() || tone };
  }
  if (payload.style_id === "custom") {
    const text = $("#sCustomStyleText").value.trim();
    if (!text) {
      $("#sStatus").textContent = "自定义视觉风格要写点内容";
      return;
    }
    payload.style_custom = { text, shot_style: $("#sCustomStyleShot").value.trim() || "中近景为主,自然光" };
  }

  $("#sRunBtn").disabled = true;
    state.runRelease = setButtonBusy($("#sRunBtn"), "novel.running", "正在写…");
  $("#sStatus").textContent = "启动中…";
  $("#sBar").style.width = "0%";
  $("#sPct").textContent = "0%";
  $("#sResult").hidden = true;
  $("#sIdle").hidden = false;

  const resp = await api("/api/games/serial/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok || !resp.body || !resp.body.job_id) {
    if (state.runRelease) { state.runRelease(); state.runRelease = null; }
    $("#sStatus").textContent = "启动失败：" + (resp.body && resp.body.error || resp.status);
    return;
  }
  state.jobId = resp.body.job_id;
  state.pollHandle = setInterval(pollJob, 1200);
  await pollJob();
}

function clampInt(raw, lo, hi, fallback) {
  const v = parseInt(raw, 10);
  if (Number.isNaN(v)) return fallback;
  return Math.max(lo, Math.min(hi, v));
}

async function pollJob() {
  if (!state.jobId) return;
  const resp = await api(`/api/games/serial/jobs/${encodeURIComponent(state.jobId)}`);
  if (!resp.ok) return;
  const job = resp.body;
  const pct = Math.round((job.progress || 0) * 100);
  $("#sBar").style.width = pct + "%";
  $("#sPct").textContent = pct + "%";
  $("#sStatus").textContent = job.message || job.status || "";
  if (job.status === "failed") {
    clearInterval(state.pollHandle);
    state.pollHandle = null;
    if (state.runRelease) { state.runRelease(); state.runRelease = null; }
    $("#sStatus").textContent = "失败：" + (job.error || "未知错误");
    return;
  }
  if (job.status === "done" && job.result) {
    clearInterval(state.pollHandle);
    state.pollHandle = null;
    state.result = job.result;
    if (state.runRelease) { state.runRelease(); state.runRelease = null; }
    renderResult(job.result);
    await loadHistory();
  }
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function renderResult(result) {
  $("#sResult").hidden = false;
  $("#sIdle").hidden = true;
  $("#serialExportBtn").hidden = false;

  $("#sShowTitle").textContent = result.title || "未命名";
  $("#sPremise").textContent = result.premise || "";
  $("#sLogline").textContent = result.logline || "";
  $("#sMeta").innerHTML = gwHTML(`
    <span class="novel-pill">${escapeHtml(result.theme_title || "")}</span>
    <span class="novel-pill">${escapeHtml(result.style_title || "")}</span>
    <span class="novel-pill">${(result.episodes || []).length} 集</span>
    <span class="novel-pill">约 ${Math.round((result.stats || {}).total_seconds || 0)} 秒</span>
  `);

  const castEl = $("#sCast");
  castEl.innerHTML = gwHTML("");
  for (const c of result.cast || []) {
    const tag = document.createElement("span");
    tag.className = "novel-cast-item";
    tag.innerHTML = gwHTML(`<b>${escapeHtml(c.name || "")}</b> · ${escapeHtml(c.role || "")}`);
    castEl.appendChild(tag);
  }

  const stats = result.stats || {};
  $("#sStats").innerHTML = gwHTML(`
    <span><b>${stats.episodes || 0}</b> 集</span>
    <span><b>${stats.shots || 0}</b> 镜头</span>
    <span><b>${stats.total_seconds || 0}</b> 秒总时长</span>
    <span>平均镜头 <b>${stats.avg_shot_seconds || 0}</b> 秒</span>
  `);

  renderEpisodeToc(result.episodes || []);
  renderEpisodes(result.episodes || []);
  renderShotsJson(result);
  renderPromptsList(result);
}

function renderEpisodeToc(episodes) {
  const ol = $("#sEpToc");
  ol.innerHTML = gwHTML("");
  for (const ep of episodes) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = gwURL(`#sEp-${ep.episode}`);
    a.innerHTML = gwHTML(`第${ep.episode}集 《${escapeHtml(ep.title || "")}》 <span class="muted">(${ep.total_seconds || 0}s)</span>`);
    li.appendChild(a);
    ol.appendChild(li);
  }
}

function renderEpisodes(episodes) {
  const host = $("#sEpisodes");
  host.innerHTML = gwHTML("");
  for (const ep of episodes) {
    const block = document.createElement("section");
    block.className = "novel-chapter";
    block.id = `sEp-${ep.episode}`;

    const head = document.createElement("header");
    head.innerHTML = gwHTML(`
      <h3>第${ep.episode}集 《${escapeHtml(ep.title || "")}》</h3>
      <p class="novel-summary">${escapeHtml(ep.logline || "")}</p>
      <p class="muted">${ep.total_seconds || 0} 秒 · ${(ep.shots || []).length} 个镜头 · 下一集:${escapeHtml(ep.hook_to_next || "—")}</p>
    `);
    block.appendChild(head);

    for (const shot of ep.shots || []) {
      block.appendChild(renderShot(shot));
    }

    host.appendChild(block);
  }
}

function renderShot(shot) {
  const card = document.createElement("article");
  card.className = "serial-shot";

  const head = document.createElement("header");
  head.innerHTML = gwHTML(`
    <span class="serial-shot-no">#${shot.shot}</span>
    <span class="serial-shot-loc">${escapeHtml(shot.location || "")}</span>
    <span class="serial-shot-time">${escapeHtml(shot.time || "")}</span>
    <span class="serial-shot-type">${escapeHtml(shot.shot_type || "")}</span>
    <span class="serial-shot-dur">${shot.duration || 0}s</span>
    <span class="serial-shot-tr">${escapeHtml(shot.transition || "cut")}</span>
  `);
  card.appendChild(head);

  const promptRow = document.createElement("div");
  promptRow.className = "serial-shot-prompt";
  promptRow.innerHTML = gwHTML(`
    <span class="serial-shot-label">画面提示</span>
    <p>${escapeHtml(shot.visual_prompt || "（模型未给出画面描述）")}</p>
    <button class="button small" type="button" data-copy="${encodeURIComponent(shot.visual_prompt || "")}">复制</button>
  `);
  card.appendChild(promptRow);

  if (shot.dialogue) {
    const lines = Array.isArray(shot.dialogue) ? shot.dialogue : [{ text: String(shot.dialogue) }];
    if (lines.length) {
      const dlg = document.createElement("div");
      dlg.className = "serial-shot-dialogue";
      dlg.innerHTML = gwHTML(`<span class="serial-shot-label">台词</span>`);
      for (const line of lines) {
        const row = document.createElement("div");
        row.className = "serial-shot-line";
        const who = line.character != null ? `#${line.character}` : (line.character || "角色");
        row.innerHTML = gwHTML(`<b>${escapeHtml(who)}:</b> ${escapeHtml(line.line || line.text || "")}`);
        dlg.appendChild(row);
      }
      card.appendChild(dlg);
    }
  }

  if (shot.sound) {
    const snd = document.createElement("div");
    snd.className = "serial-shot-sound";
    snd.innerHTML = gwHTML(`<span class="serial-shot-label">声音</span><span>${escapeHtml(shot.sound)}</span>`);
    card.appendChild(snd);
  }

  // Wire up copy buttons lazily after insertion.
  const copyBtn = promptRow.querySelector("button[data-copy]");
  if (copyBtn) {
    copyBtn.addEventListener("click", () => {
      const text = decodeURIComponent(copyBtn.getAttribute("data-copy") || "");
      copyToClipboard(text, copyBtn);
    });
  }
  return card;
}

function renderShotsJson(result) {
  const payload = (result.episodes || []).map((ep) => ({
    episode: ep.episode,
    title: ep.title,
    logline: ep.logline,
    characters: ep.characters,
    shots: ep.shots || [],
  }));
  $("#sShotsJson").value = JSON.stringify(payload, null, 2);
}

function renderPromptsList(result) {
  const ol = $("#sPromptsList");
  ol.innerHTML = gwHTML("");
  let n = 0;
  for (const ep of result.episodes || []) {
    const head = document.createElement("li");
    head.className = "serial-prompts-ep";
    head.innerHTML = gwHTML(`第${ep.episode}集 《${escapeHtml(ep.title || "")}》`);
    ol.appendChild(head);
    for (const shot of ep.shots || []) {
      n += 1;
      const li = document.createElement("li");
      li.className = "serial-prompts-item";
      li.innerHTML = gwHTML(`
        <span class="serial-prompts-no">${n}</span>
        <code>${escapeHtml(shot.visual_prompt || "")}</code>
        <button class="button small" type="button" data-copy="${encodeURIComponent(shot.visual_prompt || "")}">复制</button>
      `);
      ol.appendChild(li);
    }
  }
  // Wire copy buttons.
  for (const btn of ol.querySelectorAll("button[data-copy]")) {
    btn.addEventListener("click", () => {
      const text = decodeURIComponent(btn.getAttribute("data-copy") || "");
      copyToClipboard(text, btn);
    });
  }
}

function copyToClipboard(text, btn) {
  if (!text) return;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => flash(btn, "已复制"));
  } else {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); flash(btn, "已复制"); } catch (_) { flash(btn, "失败"); }
    document.body.removeChild(ta);
  }
}

function flash(btn, msg) {
  if (!btn) return;
  const old = btn.textContent;
  btn.textContent = msg;
  setTimeout(() => { btn.textContent = old; }, 1200);
}

function switchTab(name) {
  const map = { script: "sScriptPane", shots: "sShotsPane", prompts: "sPromptsPane" };
  const tabs = { script: "sTabScript", shots: "sTabShots", prompts: "sTabPrompts" };
  for (const [k, id] of Object.entries(map)) {
    $("#" + id).hidden = k !== name;
    $("#" + tabs[k]).classList.toggle("is-active", k === name);
    $("#" + tabs[k]).setAttribute("aria-selected", k === name ? "true" : "false");
  }
}

async function copyShotsJson() {
  const txt = $("#sShotsJson").value;
  copyToClipboard(txt, $("#sCopyShots"));
}

function downloadShotsJson() {
  const txt = $("#sShotsJson").value;
  const blob = new Blob([txt], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = gwURL(url);
  a.download = (state.result && state.result.title ? state.result.title.replace(/[\\/:*?"<>|]/g, "_") : "serial") + ".shots.json";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// History + Markdown export
// ---------------------------------------------------------------------------

async function loadHistory() {
  const resp = await api("/api/games/serial/runs");
  const list = $("#sHistory");
  list.innerHTML = gwHTML("");
  if (!resp.ok || !resp.body) return;
  for (const row of (resp.body.runs || []).slice(0, 8)) {
    const li = document.createElement("li");
    li.innerHTML = gwHTML(`<a href="#" data-jid="${row.job_id}">${escapeHtml(row.title || "未命名")} <span class="muted">${row.episodes || 0} 集 · ${row.total_seconds || 0}s</span></a>`);
    list.appendChild(li);
  }
  for (const a of list.querySelectorAll("a[data-jid]")) {
    a.addEventListener("click", async (ev) => {
      ev.preventDefault();
      const jid = a.getAttribute("data-jid");
      const resp = await api(`/api/games/serial/jobs/${encodeURIComponent(jid)}`);
      if (resp.ok && resp.body && resp.body.result) {
        state.result = resp.body.result;
        renderResult(resp.body.result);
      }
    });
  }
}

function exportMarkdown() {
  if (!state.result) return;
  const r = state.result;
  let md = `# ${r.title || "未命名"}\n\n`;
  if (r.logline) md += `> ${r.logline}\n\n`;
  md += `**主题** ${r.theme_title} · **视觉** ${r.style_title}\n\n`;
  md += `**核心情境** ${r.premise}\n\n`;
  if (r.cast && r.cast.length) {
    md += `## 主演\n`;
    for (const c of r.cast) md += `- **${c.name}** (#${c.agent_id}) · ${c.role} — ${c.arc}\n`;
    md += "\n";
  }
  for (const ep of r.episodes || []) {
    md += `## 第${ep.episode}集 《${ep.title}》\n`;
    if (ep.logline) md += `${ep.logline}\n\n`;
    for (const shot of ep.shots || []) {
      md += `### Shot ${shot.shot} · ${shot.location || ""} · ${shot.time || ""} · ${shot.shot_type || ""} · ${shot.duration || 0}s\n`;
      if (shot.visual_prompt) md += `${shot.visual_prompt}\n\n`;
      if (shot.dialogue) {
        const lines = Array.isArray(shot.dialogue) ? shot.dialogue : [{ text: String(shot.dialogue) }];
        for (const line of lines) {
          const who = line.character != null ? `#${line.character}` : "角色";
          md += `> **${who}**: ${line.line || line.text || ""}\n`;
        }
        md += "\n";
      }
      if (shot.sound) md += `_声音_: ${shot.sound}\n\n`;
      md += `_转场_: ${shot.transition || "cut"}\n\n`;
    }
  }
  const blob = new Blob([md], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = gwURL(url);
  a.download = (r.title || "serial").replace(/[\\/:*?"<>|]/g, "_") + ".md";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

document.addEventListener("DOMContentLoaded", boot);