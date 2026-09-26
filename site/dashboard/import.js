// Bulk import modal for Agent Studio.
//
// Flow:
//   1) user drops / picks a CSV / xlsx / JSONL file;
//   2) client parses it (CSV by hand, JSONL by JSON.parse per line, xlsx via
//      SheetJS CDN if the file extension is .xlsx);
//   3) client POSTs a preview to /api/import/preview to get suggested
//      column mappings + inferred demographics;
//   4) user reviews / edits the mapping, picks anonymise + expand-to;
//   5) client POSTs the same payload to /api/import/run which returns a
//      job id; the UI then polls /api/import/jobs/<id> until done;
//   6) on success, refreshes the agent list and offers a "go to last agent"
//      link.
//
// All i18n strings are prefixed `studio.bulk.*` so the locale bundle in
// `locales/zh-CN.json` is the single source of truth.
//
// This module is loaded after `studio.js`. It does not modify `store` —
// it only reads `store.cityRef` so it always imports to the city currently
// shown in the Studio's left rail.

(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const I18N_KEYS = {
    title: "studio.bulk_import_title",
    pickFile: "studio.bulk_pick_file",
    dropHint: "studio.bulk_drop_hint",
    mapTitle: "studio.bulk_map_title",
    mapHint: "studio.bulk_map_hint",
    cfgTitle: "studio.bulk_cfg_title",
    cfgAnonymise: "studio.bulk_cfg_anonymise",
    cfgAnonymiseHint: "studio.bulk_cfg_anonymise_hint",
    cfgExpand: "studio.bulk_cfg_expand",
    cfgExpandHint: "studio.bulk_cfg_expand_hint",
    cfgCity: "studio.bulk_cfg_city",
    summaryTitle: "studio.bulk_summary_title",
    back: "studio.bulk_back",
    next: "studio.bulk_next",
    run: "studio.bulk_run",
    close: "studio.bulk_close",
    cancel: "studio.bulk_cancel",
    running: "studio.bulk_running",
    done: "studio.bulk_done",
    failed: "studio.bulk_failed",
    reimport: "studio.bulk_reimport",
    viewAgents: "studio.bulk_view_agents",
    noMap: "studio.bulk_no_map",
    inferred: "studio.bulk_inferred",
    rows: "studio.bulk_rows",
    cols: "studio.bulk_cols",
    unmapped: "studio.bulk_unmapped",
    ignore: "studio.bulk_ignore",
    errFormat: "Unknown file format",
  };

  const i18n = (key, fallback) => {
    if (typeof __ === "function") {
      const val = __(key);
      if (val && val !== key) return val;
    }
    return fallback ?? key;
  };

  // ----- module state -----
  let _ctx = null;
  /**
   * Shape:
   *   {
   *     file: File | null,
   *     format: "csv" | "xlsx" | "jsonl",
   *     headers: string[],
   *     rows: Array<Record<string, string>>,
   *     preview: object | null,   // last server response from /preview
   *     mapping: Record<string, string>,  // raw header → canonical field
   *     city: string,
   *     anonymise: boolean,
   *     expandTo: number,
   *     jobId: string | null,
   *     jobTimer: number | null,
   *   }
   */

  function open() {
    const modal = $("#importModal");
    if (!modal) return;
    if (!_ctx) _ctx = freshContext();
    _ctx.city = currentCityRef();
    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");
    renderStepUpload();
  }

  function close() {
    const modal = $("#importModal");
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute("aria-hidden", "true");
    $("#importBody").innerHTML = "";
    if (_ctx && _ctx.jobTimer) {
      clearInterval(_ctx.jobTimer);
      _ctx.jobTimer = null;
    }
    _ctx = freshContext();
  }

  function freshContext() {
    return {
      file: null,
      format: "csv",
      headers: [],
      rows: [],
      preview: null,
      mapping: {},
      city: currentCityRef(),
      anonymise: true,
      expandTo: 0,
      jobId: null,
      jobTimer: null,
    };
  }

  function currentCityRef() {
    // The Studio keeps the active city on its #citySelect element.
    const sel = document.querySelector("#citySelect");
    if (sel && sel.value) return String(sel.value);
    // Fallback: window globals set by studio.js
    if (window.store && window.store.cityRef) return String(window.store.cityRef);
    return "";
  }

  // ----- step 1: upload + parse -----
  function renderStepUpload() {
    const body = $("#importBody");
    body.innerHTML = `
      <section class="imp-step is-active">
        <h4>${esc(i18n(I18N_KEYS.pickFile, "上传文件"))}</h4>
        <p class="hint">${esc(i18n(I18N_KEYS.dropHint, "支持 CSV、Excel (.xlsx) 与 JSONL。最大 5 MB，第一行视为表头。"))}</p>
        <div class="imp-drop" id="impDrop">
          <p><strong>${esc(i18n("studio.bulk_drop_label", "拖入文件 或 点击选择"))}</strong></p>
          <p>CSV · XLSX · JSONL</p>
          <input type="file" id="impFile" accept=".csv,.xlsx,.jsonl,.json,.ndjson" hidden />
        </div>
        <p id="impFileMeta" class="imp-status"></p>
        <div class="imp-actions">
          <button class="button" id="impCancel">${esc(i18n(I18N_KEYS.cancel, "取消"))}</button>
          <button class="button primary" id="impNext" disabled>${esc(i18n(I18N_KEYS.next, "下一步 →"))}</button>
        </div>
      </section>
    `;
    const drop = $("#impDrop");
    const input = $("#impFile");
    drop.addEventListener("click", () => input.click());
    drop.addEventListener("dragover", (ev) => {
      ev.preventDefault();
      drop.classList.add("is-drag");
    });
    drop.addEventListener("dragleave", () => drop.classList.remove("is-drag"));
    drop.addEventListener("drop", (ev) => {
      ev.preventDefault();
      drop.classList.remove("is-drag");
      const file = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];
      if (file) handleFile(file);
    });
    input.addEventListener("change", () => {
      const file = input.files && input.files[0];
      if (file) handleFile(file);
    });
    $("#impCancel").addEventListener("click", close);
    $("#impNext").addEventListener("click", () => previewAndShowMapping());
  }

  async function handleFile(file) {
    _ctx.file = file;
    _ctx.format = sniffFormat(file.name);
    $("#impFileMeta").className = "imp-status";
    $("#impFileMeta").textContent = `${file.name} · ${(file.size / 1024).toFixed(1)} KB · ${_ctx.format}`;
    try {
      if (_ctx.format === "xlsx") {
        await parseXlsx(file);
      } else if (_ctx.format === "jsonl") {
        await parseJsonl(file);
      } else {
        await parseCsv(file);
      }
      if (!_ctx.headers.length) throw new Error("文件没有表头");
      if (!_ctx.rows.length) throw new Error("文件没有任何记录");
      $("#impNext").disabled = false;
    } catch (err) {
      $("#impFileMeta").className = "imp-status is-error";
      $("#impFileMeta").textContent = `${i18n("studio.bulk_err_parse", "解析失败")}: ${err.message || err}`;
      $("#impNext").disabled = true;
    }
  }

  function sniffFormat(name) {
    const lower = (name || "").toLowerCase();
    if (lower.endsWith(".csv")) return "csv";
    if (lower.endsWith(".xlsx")) return "xlsx";
    if (lower.endsWith(".jsonl") || lower.endsWith(".ndjson") || lower.endsWith(".json")) return "jsonl";
    return "csv";
  }

  async function parseCsv(file) {
    const text = await file.text();
    const lines = text.split(/\r?\n/).filter((line) => line.trim() !== "");
    if (!lines.length) throw new Error("空文件");
    const headers = splitCsvLine(lines[0]);
    _ctx.headers = headers;
    _ctx.rows = lines.slice(1).map((line) => {
      const cells = splitCsvLine(line);
      const obj = {};
      headers.forEach((h, i) => {
        obj[h] = cells[i] !== undefined ? cells[i] : "";
      });
      return obj;
    });
  }

  // Minimal CSV split that handles quoted fields with embedded commas.
  function splitCsvLine(line) {
    const cells = [];
    let buf = "";
    let inQuote = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (inQuote) {
        if (ch === '"' && line[i + 1] === '"') {
          buf += '"';
          i++;
        } else if (ch === '"') {
          inQuote = false;
        } else {
          buf += ch;
        }
      } else if (ch === '"') {
        inQuote = true;
      } else if (ch === ",") {
        cells.push(buf);
        buf = "";
      } else {
        buf += ch;
      }
    }
    cells.push(buf);
    return cells.map((c) => c.trim());
  }

  async function parseJsonl(file) {
    const text = await file.text();
    const lines = text.split(/\r?\n/).filter((line) => line.trim() !== "");
    const records = [];
    const headerSet = new Set();
    for (const line of lines) {
      try {
        const obj = JSON.parse(line);
        if (Array.isArray(obj)) {
          // {"batch": [...]} shapes arrive as a single line — expand here.
          obj.forEach((item) => {
            if (item && typeof item === "object") {
              records.push(item);
              Object.keys(item).forEach((k) => headerSet.add(k));
            }
          });
        } else if (obj && typeof obj === "object") {
          records.push(obj);
          Object.keys(obj).forEach((k) => headerSet.add(k));
        }
      } catch (err) {
        throw new Error(`JSONL 解析失败：${err.message}`);
      }
    }
    _ctx.headers = Array.from(headerSet);
    _ctx.rows = records.map((r) => {
      const obj = {};
      _ctx.headers.forEach((h) => {
        obj[h] = r[h] === undefined || r[h] === null ? "" : String(r[h]);
      });
      return obj;
    });
  }

  async function parseXlsx(file) {
    if (typeof XLSX === "undefined") {
      await loadSheetJs();
    }
    const buf = await file.arrayBuffer();
    const workbook = XLSX.read(buf, { type: "array" });
    const sheet = workbook.Sheets[workbook.SheetNames[0]];
    const matrix = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: "" });
    if (!matrix.length) throw new Error("空工作表");
    const headers = matrix[0].map((c) => String(c).trim());
    _ctx.headers = headers;
    _ctx.rows = matrix.slice(1)
      .filter((row) => row.some((cell) => String(cell).trim() !== ""))
      .map((row) => {
        const obj = {};
        headers.forEach((h, i) => {
          obj[h] = row[i] === undefined || row[i] === null ? "" : String(row[i]);
        });
        return obj;
      });
  }

  let _sheetJsPromise = null;
  function loadSheetJs() {
    if (_sheetJsPromise) return _sheetJsPromise;
    _sheetJsPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js";
      script.onload = () => resolve();
      script.onerror = () => reject(new Error("无法加载 SheetJS CDN"));
      document.head.appendChild(script);
    });
    return _sheetJsPromise;
  }

  // ----- step 2: server preview + mapping -----
  async function previewAndShowMapping() {
    const meta = $("#impFileMeta");
    meta.className = "imp-status";
    meta.textContent = i18n("studio.bulk_loading", "正在分析…");
    try {
      const payload = {
        format: _ctx.format,
        filename: _ctx.file ? _ctx.file.name : "",
        file_text: _ctx.format === "xlsx" ? await readFileBase64(_ctx.file) : await _ctx.file.text(),
        file_encoding: _ctx.format === "xlsx" ? "base64" : "utf-8",
        rows: _ctx.rows,
        headers: _ctx.headers,
        anonymise: _ctx.anonymise,
        expand_to: _ctx.expandTo,
      };
      const resp = await fetch("/api/import/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.error || `HTTP ${resp.status}`);
      }
      _ctx.preview = await resp.json();
      _ctx.mapping = { ..._ctx.preview.mapping_suggested };
      meta.textContent = "";
      renderStepMapping();
    } catch (err) {
      meta.className = "imp-status is-error";
      meta.textContent = `${i18n("studio.bulk_err_preview", "预览失败")}: ${err.message || err}`;
    }
  }

  function readFileBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = String(reader.result || "");
        const idx = result.indexOf(",");
        resolve(idx >= 0 ? result.slice(idx + 1) : result);
      };
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });
  }

  function renderStepMapping() {
    const body = $("#importBody");
    const canonical = (_ctx.preview && _ctx.preview.canonical_fields) || [];
    const rowsHtml = _ctx.headers.map((h) => `
      <tr>
        <th>${esc(h)}</th>
        <td>
          <select data-raw="${esc(h)}">
            <option value="">${esc(i18n(I18N_KEYS.ignore, "忽略"))}</option>
            ${canonical.map((c) => `<option value="${esc(c)}" ${_ctx.mapping[h] === c ? "selected" : ""}>${esc(c)}</option>`).join("")}
          </select>
        </td>
      </tr>
    `).join("");
    body.innerHTML = `
      <section class="imp-step is-active">
        <h4>${esc(i18n(I18N_KEYS.mapTitle, "列映射"))}</h4>
        <p class="hint">${esc(i18n(I18N_KEYS.mapHint, "系统已按表头含义给出推荐映射；调整后会自动重新计算分布概览。"))}</p>
        <table class="imp-table">
          <thead><tr><th>${esc(i18n(I18N_KEYS.cols, "表头"))}</th><th>${esc(i18n(I18N_KEYS.noMap, "对应字段"))}</th></tr></thead>
          <tbody>${rowsHtml}</tbody>
        </table>
        <div id="impInferred" class="imp-status"></div>
        <div class="imp-actions">
          <button class="button" id="impBack">${esc(i18n(I18N_KEYS.back, "← 上一步"))}</button>
          <button class="button primary" id="impNext">${esc(i18n(I18N_KEYS.next, "下一步 →"))}</button>
        </div>
      </section>
    `;
    $$("select[data-raw]", body).forEach((sel) => {
      sel.addEventListener("change", () => {
        const raw = sel.getAttribute("data-raw");
        _ctx.mapping[raw] = sel.value;
        refreshInferred();
      });
    });
    $("#impBack").addEventListener("click", renderStepUpload);
    $("#impNext").addEventListener("click", renderStepConfig);
    refreshInferred();
  }

  async function refreshInferred() {
    const target = $("#impInferred");
    if (!target) return;
    target.textContent = i18n("studio.bulk_recalculating", "重新计算中…");
    try {
      const resp = await fetch("/api/import/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          format: _ctx.format,
          filename: _ctx.file ? _ctx.file.name : "",
          file_text: _ctx.format === "xlsx" ? await readFileBase64(_ctx.file) : await _ctx.file.text(),
          file_encoding: _ctx.format === "xlsx" ? "base64" : "utf-8",
          rows: _ctx.rows,
          headers: _ctx.headers,
          mapping: _ctx.mapping,
          anonymise: _ctx.anonymise,
          expand_to: _ctx.expandTo,
        }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      _ctx.preview = await resp.json();
      renderInferredBox(target, _ctx.preview.inferred);
    } catch (err) {
      target.textContent = `${i18n("studio.bulk_err_inferred", "推断失败")}: ${err.message || err}`;
    }
  }

  function renderInferredBox(el, inferred) {
    if (!inferred) {
      el.textContent = "";
      return;
    }
    const counts = inferred.counts || {};
    const demo = inferred.demography || {};
    const income = inferred.income || {};
    el.innerHTML = `
      <strong>${esc(i18n(I18N_KEYS.inferred, "推断出的分布"))}</strong>：
      ${esc(i18n(I18N_KEYS.rows, "记录"))} ${counts.total || 0} ·
      median_age ${(demo.median_age || 0).toFixed(1)} ·
      <18 ${((demo.share_under_18 || 0) * 100).toFixed(1)}% ·
      65+ ${((demo.share_over_65 || 0) * 100).toFixed(1)}% ·
      月薪中位数 ¥${(income.median || 0).toFixed(0)}
    `;
  }

  // ----- step 3: config (anonymise + expand + city) -----
  function renderStepConfig() {
    const body = $("#importBody");
    const inferred = (_ctx.preview && _ctx.preview.inferred) || {};
    const recommended = Math.max((inferred.counts && inferred.counts.total) || _ctx.rows.length, _ctx.rows.length);
    body.innerHTML = `
      <section class="imp-step is-active">
        <h4>${esc(i18n(I18N_KEYS.cfgTitle, "导入选项"))}</h4>
        <p class="hint">${esc(i18n(I18N_KEYS.cfgAnonymiseHint, "开启后姓名替换为假名、联系方式丢弃、自由文本里的人名/地名会被替换。"))}</p>

        <div class="imp-toggle">
          <input type="checkbox" id="impAnon" ${_ctx.anonymise ? "checked" : ""} />
          <label for="impAnon">${esc(i18n(I18N_KEYS.cfgAnonymise, "匿名化（推荐）"))}</label>
        </div>

        <div class="imp-toggle">
          <label for="impExpand">${esc(i18n(I18N_KEYS.cfgExpand, "扩容到"))}</label>
          <input type="number" id="impExpand" min="${_ctx.rows.length}" step="50" value="${recommended}" style="width:100px" />
          <span class="imp-status">${esc(i18n(I18N_KEYS.cfgExpandHint, "人（保持与上传库相同的分布；超过上传库的人数由仿真器抽样生成）"))}</span>
        </div>

        <div class="imp-toggle">
          <label for="impCity">${esc(i18n(I18N_KEYS.cfgCity, "目标城市"))}</label>
          <input type="text" id="impCity" value="${esc(_ctx.city)}" style="width:180px" />
        </div>

        <div class="imp-actions">
          <button class="button" id="impBack">${esc(i18n(I18N_KEYS.back, "← 上一步"))}</button>
          <button class="button primary" id="impRun">${esc(i18n(I18N_KEYS.run, "开始导入"))}</button>
        </div>
      </section>
    `;
    $("#impAnon").addEventListener("change", (ev) => { _ctx.anonymise = !!ev.target.checked; });
    $("#impExpand").addEventListener("input", (ev) => { _ctx.expandTo = Math.max(_ctx.rows.length, parseInt(ev.target.value, 10) || 0); });
    $("#impCity").addEventListener("input", (ev) => { _ctx.city = ev.target.value.trim(); });
    $("#impBack").addEventListener("click", renderStepMapping);
    $("#impRun").addEventListener("click", runImport);
  }

  // ----- step 4: run + progress -----
  async function runImport() {
    if (!_ctx.city) {
      alert(i18n("studio.bulk_err_city", "请填写目标城市"));
      return;
    }
    const body = $("#importBody");
    body.innerHTML = `
      <section class="imp-step is-active">
        <h4>${esc(i18n(I18N_KEYS.running, "正在导入…"))}</h4>
        <div class="imp-progress">
          <div class="bar"><span id="impBar" style="width:5%"></span></div>
          <span id="impPct" class="imp-status">5%</span>
        </div>
        <p id="impMsg" class="imp-status">${esc(i18n("studio.bulk_starting", "启动中…"))}</p>
      </section>
    `;
    try {
      const payload = {
        city: _ctx.city,
        format: _ctx.format,
        filename: _ctx.file ? _ctx.file.name : "",
        file_text: _ctx.format === "xlsx" ? await readFileBase64(_ctx.file) : await _ctx.file.text(),
        file_encoding: _ctx.format === "xlsx" ? "base64" : "utf-8",
        rows: _ctx.rows,
        headers: _ctx.headers,
        mapping: _ctx.mapping,
        anonymise: _ctx.anonymise,
        expand_to: _ctx.expandTo,
        seed: Math.floor(Math.random() * 1e9),
        salt: `web-${Date.now()}`,
      };
      const resp = await fetch("/api/import/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        const body2 = await resp.json().catch(() => ({}));
        throw new Error(body2.error || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      _ctx.jobId = data.job_id;
      pollJob();
    } catch (err) {
      $("#impMsg").className = "imp-status is-error";
      $("#impMsg").textContent = `${err.message || err}`;
      $("#impBar").style.width = "100%";
    }
  }

  function pollJob() {
    if (!_ctx.jobId) return;
    _ctx.jobTimer = setInterval(async () => {
      try {
        const resp = await fetch("/api/import/jobs/" + encodeURIComponent(_ctx.jobId));
        if (!resp.ok) throw new Error("job status HTTP " + resp.status);
        const rec = await resp.json();
        const pct = Math.round((rec.progress || 0) * 100);
        const bar = $("#impBar");
        const pctEl = $("#impPct");
        const msg = $("#impMsg");
        if (bar) bar.style.width = pct + "%";
        if (pctEl) pctEl.textContent = pct + "%";
        if (msg) {
          msg.textContent = rec.message || (rec.status === "running" ? "…" : "");
          msg.className = "imp-status";
        }
        if (rec.status === "done") {
          clearInterval(_ctx.jobTimer);
          _ctx.jobTimer = null;
          renderStepResult(rec.result || {});
        } else if (rec.status === "failed") {
          clearInterval(_ctx.jobTimer);
          _ctx.jobTimer = null;
          if (msg) {
            msg.className = "imp-status is-error";
            msg.textContent = (rec.error || "failed") + "";
          }
          renderStepFailure(rec.error || "unknown");
        }
      } catch (err) {
        const msg = $("#impMsg");
        if (msg) {
          msg.className = "imp-status is-error";
          msg.textContent = String(err);
        }
      }
    }, 800);
  }

  function renderStepResult(result) {
    const body = $("#importBody");
    body.innerHTML = `
      <section class="imp-step is-active">
        <h4>${esc(i18n(I18N_KEYS.done, "导入完成"))}</h4>
        <div class="imp-summary">
          <div class="stat"><div class="n">${result.inserted_direct || 0}</div><div class="l">${esc(i18n("studio.bulk_direct", "直接导入"))}</div></div>
          <div class="stat"><div class="n">${result.expanded_extra || 0}</div><div class="l">${esc(i18n("studio.bulk_synthetic", "抽样新增"))}</div></div>
          <div class="stat"><div class="n">${result.total || 0}</div><div class="l">${esc(i18n("studio.bulk_total", "城市人口"))}</div></div>
        </div>
        <p class="imp-status is-success">${esc(i18n("studio.bulk_added_to", "已加入"))} <code>${esc(result.city || "")}</code></p>
        <div class="imp-actions">
          <button class="button" id="impReimport">${esc(i18n(I18N_KEYS.reimport, "再导一批"))}</button>
          <button class="button primary" id="impClose">${esc(i18n(I18N_KEYS.close, "完成"))}</button>
        </div>
      </section>
    `;
    $("#impReimport").addEventListener("click", () => {
      _ctx = freshContext();
      open();
    });
    $("#impClose").addEventListener("click", close);
  }

  function renderStepFailure(error) {
    const body = $("#importBody");
    body.innerHTML = `
      <section class="imp-step is-active">
        <h4>${esc(i18n(I18N_KEYS.failed, "导入失败"))}</h4>
        <p class="imp-status is-error">${esc(error)}</p>
        <div class="imp-actions">
          <button class="button" id="impReimport">${esc(i18n(I18N_KEYS.reimport, "重试"))}</button>
          <button class="button" id="impClose">${esc(i18n(I18N_KEYS.cancel, "取消"))}</button>
        </div>
      </section>
    `;
    $("#impReimport").addEventListener("click", () => {
      _ctx = freshContext();
      open();
    });
    $("#impClose").addEventListener("click", close);
  }

  // ----- helpers -----
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function ready(fn) {
    if (document.readyState !== "loading") fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }

  ready(() => {
    const btn = $("#bulkImportBtn");
    const closeBtn = $("#importClose");
    const modal = $("#importModal");
    if (btn) btn.addEventListener("click", open);
    if (closeBtn) closeBtn.addEventListener("click", close);
    if (modal) {
      modal.addEventListener("click", (ev) => {
        if (ev.target === modal) close();
      });
    }
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && modal && !modal.hidden) close();
    });
  });

  // Expose for tests / Studio JS that wants to open it programmatically.
  window.GAWorldBulkImport = { open, close };
})();