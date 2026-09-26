/* 真人蒸馏 — 从一个姓名或一个网址造出对应的智能体。
 *
 * 面板做三件事：起任务、看进度、复核结果。三步之间刻意隔开：
 *
 * - 蒸馏只写 output/personas/，不碰仿真用的种子文件。写进世界的动作叫「部署」，
 *   由人按下去。这是一个关于真人的断言，不该有任何一部分未经复核就进到运行中的世界。
 * - 进度条是真的：检索四个方向、抓正文、两次模型调用，后端按阶段回报。
 *   一个假的转圈会让人以为卡住了，然后重复点击，把同一批请求再打一遍。
 * - 结果页把「证据强度」和「来源链接」放在结论旁边，不折叠。看起来笃定的画像可能
 *   只来自两条搜索摘要，这件事必须一眼可见。
 *
 * 渲染函数在 persona-view.js 里，纯函数、无 DOM，可以用 node 单独测。
 * 与工作台之间只有两个接口：`persona:fill` 事件（把结果灌进七步表单），
 * 以及 studio.js 保存时改走 /api/persona/deploy。
 */
(function () {
  "use strict";

  var view = window.GAWorldPersonaView;

  var POLL_MS = 1500;

  var state = {
    open: false,
    job: null,
    poll: null,
    persona: null,
    archive: [],
    busy: false,
    message: "",
    tone: "",
  };

  /** i18n with an inline Chinese fallback, same contract as survey.js. */
  function t(key, fallback) {
    if (typeof window.__ !== "function") return fallback;
    var value = window.__("pd." + key);
    return value && value !== "pd." + key ? value : fallback;
  }

  function esc(text) { return view.esc(text); }

  async function api(path, options) {
    var res = await fetch(path, Object.assign(
      { cache: "no-store", headers: { "Content-Type": "application/json" } },
      options || {}
    ));
    var payload = await res.json().catch(function () { return {}; });
    /* Only the HTTP status decides, never `payload.error`: a job record
     * legitimately *carries* an `error` field (the traceback of the job that
     * failed) and arrives with 200. Treating that as a failed request threw
     * `new Error({type, detail})`, and the panel showed the job's real reason
     * as "[object Object]". Same rule as worlds.js, the other job poller. */
    if (!res.ok) throw new Error(errorText(payload) || ("HTTP " + res.status));
    return payload;
  }

  /** A server error can be a string or a {type, detail} record; say something. */
  function errorText(payload) {
    var raw = (payload || {}).error;
    if (!raw) return "";
    if (typeof raw === "string") return raw;
    return String(raw.detail || raw.type || JSON.stringify(raw));
  }

  function say(message, tone) {
    state.message = message || "";
    state.tone = tone || "";
    render();
  }

  // ------------------------------------------------------------------ modal

  function open() {
    if (state.open) return;
    state.open = true;
    var box = document.createElement("div");
    box.className = "pd-modal";
    box.id = "pdModal";
    document.body.appendChild(box);
    document.addEventListener("keydown", onKey);
    render();
    loadArchive();
  }

  function close() {
    stopPolling();
    state.open = false;
    state.job = null;
    document.removeEventListener("keydown", onKey);
    var box = document.getElementById("pdModal");
    if (box) box.remove();
  }

  function onKey(ev) { if (ev.key === "Escape") close(); }

  function render() {
    var box = document.getElementById("pdModal");
    if (!box) return;
    var running = !!(state.job && state.job.status === "running");
    box.innerHTML =
      '<div class="pd-box" role="dialog" aria-modal="true" aria-label="' + esc(t("title", "从真人蒸馏")) + '">' +
        '<div class="pd-head-bar">' +
          "<h3>" + esc(t("title", "从真人蒸馏")) + "</h3>" +
          '<button type="button" class="mini-btn" id="pdClose" aria-label="' + esc(t("close", "关闭")) + '">✕</button>' +
        "</div>" +
        '<p class="pd-note">' + esc(t("note",
          "输入一个姓名或一个网址。系统会检索公开资料、读取正文，再蒸馏成一份带证据的画像：" +
          "身份档案 + 心智模型 / 决策启发式 / 表达方式 / 画像边界。只用检索到的材料，不足之处会明确留空。")) + "</p>" +
        '<div class="pd-form">' +
          '<input id="pdSubject" type="text" placeholder="' +
            esc(t("placeholder", "如：张三，或 https://example.com/about")) + '"' +
            (running ? " disabled" : "") + ' value="' + esc(currentSubject()) + '">' +
          '<button type="button" class="button primary" id="pdStart"' + (running ? " disabled" : "") + ">" +
            esc(running ? t("running", "蒸馏中…") : t("start", "开始蒸馏")) + "</button>" +
        "</div>" +
        progressBar() +
        (state.message ? '<p class="pd-msg ' + esc(state.tone) + '">' + esc(state.message) + "</p>" : "") +
        '<div class="pd-body">' +
          '<div class="pd-result">' + (state.persona ? view.personaView(state.persona) : placeholder()) + "</div>" +
          '<aside class="pd-side">' +
            "<h4>" + esc(t("archive", "已蒸馏")) + "</h4>" +
            view.archiveList(state.archive) +
          "</aside>" +
        "</div>" +
        actionBar() +
      "</div>";
    bind();
  }

  function currentSubject() {
    var input = document.getElementById("pdSubject");
    return input ? input.value : "";
  }

  function placeholder() {
    return '<p class="pd-empty">' + esc(t("empty", "结果会显示在这里。")) + "</p>";
  }

  function progressBar() {
    if (!state.job) return "";
    var pct = Math.round(Math.max(0, Math.min(1, state.job.progress || 0)) * 100);
    var failed = state.job.status === "error";
    return '<div class="pd-progress ' + (failed ? "bad" : "") + '">' +
      '<div class="pd-bar"><span style="width:' + pct + '%"></span></div>' +
      "<span>" + esc(state.job.message || "") + "</span></div>";
  }

  function actionBar() {
    if (!state.persona) return "";
    var deployed = state.persona.agent_id != null;
    return '<div class="pd-actions">' +
      '<button type="button" class="button primary" id="pdFill">' + esc(t("fill", "填入表单")) + "</button>" +
      '<button type="button" class="button steel" id="pdDeploy"' + (state.busy ? " disabled" : "") + ">" +
        esc(deployed ? t("deploy_again", "再部署一个") : t("deploy", "直接部署为居民")) + "</button>" +
      '<button type="button" class="button" id="pdSkill"' + (state.busy ? " disabled" : "") + ">" +
        esc(t("install", "导出为 Skill")) + "</button>" +
      '<button type="button" class="button" id="pdDelete">' + esc(t("discard", "删除画像")) + "</button>" +
      "</div>";
  }

  function bind() {
    var byId = function (id, fn) {
      var el = document.getElementById(id);
      if (el) el.addEventListener("click", fn);
    };
    byId("pdClose", close);
    byId("pdStart", start);
    byId("pdFill", fill);
    byId("pdDeploy", deploy);
    byId("pdSkill", installSkill);
    byId("pdDelete", discard);
    var input = document.getElementById("pdSubject");
    if (input) {
      input.addEventListener("keydown", function (ev) { if (ev.key === "Enter") start(); });
    }
    var box = document.getElementById("pdModal");
    if (box) {
      box.addEventListener("click", function (ev) { if (ev.target === box) close(); });
      box.querySelectorAll(".pd-open").forEach(function (btn) {
        btn.addEventListener("click", function () { openPersona(btn.dataset.slug); });
      });
    }
  }

  // ------------------------------------------------------------------ actions

  async function loadArchive() {
    try {
      var payload = await api("/api/persona/list");
      state.archive = payload.personas || [];
      render();
    } catch (err) {
      say(t("archive_failed", "读取画像列表失败：") + err.message, "err");
    }
  }

  async function start() {
    var subject = (currentSubject() || "").trim();
    if (!subject) { say(t("need_subject", "请填写姓名或网址。"), "err"); return; }
    try {
      state.persona = null;
      var res = await api("/api/persona/distill", { method: "POST", body: JSON.stringify({ subject: subject }) });
      state.job = { id: res.job_id, status: "running", progress: 0, message: t("queued", "启动中…") };
      say("", "");
      startPolling(res.job_id);
    } catch (err) {
      say(t("start_failed", "启动失败：") + err.message, "err");
    }
  }

  function startPolling(jobId) {
    stopPolling();
    state.poll = setInterval(async function () {
      try {
        var job = await api("/api/persona/jobs/" + encodeURIComponent(jobId));
        state.job = job;
        if (job.status === "running") { render(); return; }
        stopPolling();
        if (job.status === "error") {
          say(t("failed", "蒸馏失败：") + (job.message || ""), "err");
          return;
        }
        state.persona = (job.result || {}).persona || null;
        say(t("done", "蒸馏完成，请复核证据与边界后再落地。"), "ok");
        loadArchive();
      } catch (err) {
        stopPolling();
        say(t("poll_failed", "读取进度失败：") + err.message, "err");
      }
    }, POLL_MS);
  }

  function stopPolling() {
    if (state.poll) { clearInterval(state.poll); state.poll = null; }
  }

  async function openPersona(slug) {
    try {
      var payload = await api("/api/persona/detail/" + encodeURIComponent(slug));
      state.persona = payload.persona;
      state.job = null;
      say("", "");
    } catch (err) {
      say(t("open_failed", "打开画像失败：") + err.message, "err");
    }
  }

  /** Hand the persona to Agent Studio's seven-step form and step aside. */
  function fill() {
    if (!state.persona) return;
    document.dispatchEvent(new CustomEvent("persona:fill", { detail: state.persona }));
    close();
  }

  async function deploy() {
    if (!state.persona || state.busy) return;
    state.busy = true;
    say(t("deploying", "正在落地为居民…"), "");
    try {
      var res = await api("/api/persona/deploy", {
        method: "POST", body: JSON.stringify({ slug: state.persona.slug }),
      });
      state.persona.agent_id = res.agent_id;
      var note = res.big5_written ? "" : t("no_big5", "（未写入大五人格：种子文件缺失）");
      say(t("deployed_ok", "已落地为居民 #") + res.agent_id + note, "ok");
      document.dispatchEvent(new CustomEvent("persona:deployed", { detail: res }));
      loadArchive();
    } catch (err) {
      say(t("deploy_failed", "部署失败：") + err.message, "err");
    } finally {
      state.busy = false;
    }
  }

  async function installSkill() {
    if (!state.persona || state.busy) return;
    state.busy = true;
    try {
      var res = await api("/api/persona/install-skill", {
        method: "POST", body: JSON.stringify({ slug: state.persona.slug }),
      });
      if (res.installed) {
        say(t("installed", "已导出 Skill：") + res.path, "ok");
      } else if (res.reason === "exists") {
        if (window.confirm(t("overwrite_ask", "该 Skill 已存在，覆盖吗？\n") + res.path)) {
          var again = await api("/api/persona/install-skill", {
            method: "POST", body: JSON.stringify({ slug: state.persona.slug, overwrite: true }),
          });
          say(t("installed", "已导出 Skill：") + again.path, "ok");
        } else {
          say(t("install_skipped", "已取消导出。"), "");
        }
      }
    } catch (err) {
      say(t("install_failed", "导出失败：") + err.message, "err");
    } finally {
      state.busy = false;
    }
  }

  async function discard() {
    if (!state.persona) return;
    if (!window.confirm(t("discard_ask", "删除这份画像及其调研素材？（已落地的居民不受影响）"))) return;
    try {
      await api("/api/persona/delete", { method: "POST", body: JSON.stringify({ slug: state.persona.slug }) });
      state.persona = null;
      say(t("discarded", "画像已删除。"), "ok");
      loadArchive();
    } catch (err) {
      say(t("discard_failed", "删除失败：") + err.message, "err");
    }
  }

  // ------------------------------------------------------------------ wire up

  function init() {
    var btn = document.getElementById("distillBtn");
    if (btn) btn.addEventListener("click", open);
  }

  document.addEventListener("DOMContentLoaded", init);

  window.PersonaPanel = { open: open, close: close };
}());
