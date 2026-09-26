/* 研究工作台 — 把一个研究想法或一篇论文交给模型，对照 GAWorld 的功能目录产出实施方案。
 *
 * 一次分析 = 一次后台任务（POST /api/research/analyze → 轮询 /api/research/jobs/<id>）。
 * 论文分两步：先解读（POST /api/research/digest），研究者改完解读再带着它去分析；
 * 想法仍是一步。一份方案里有几种可选的实验设计，「转成研究」编译当前选中的那个。
 * 提示词带着整份功能目录和最多一篇论文的文本，本地模型要跑几分钟，浏览器请求不该等它。
 *
 * 所有界面文案走 `t(key, 中文兜底)`：中文兜底让页面在 locale 文件缺键时依然可读，
 * 而键的存在让英文界面不至于突然冒出中文。
 */
(function () {
  "use strict";

  var POLL_MS = 1500;

  function t(key, fallback) {
    if (typeof window.__ !== "function") return fallback;
    var value = window.__("research." + key);
    return value && value !== "research." + key ? value : fallback;
  }

  function tf(key, fallback, params) {
    var text = t(key, fallback);
    Object.keys(params || {}).forEach(function (name) {
      text = text.split("{" + name + "}").join(String(params[name]));
    });
    return text;
  }

  function $(id) {
    return document.getElementById(id);
  }

  function esc(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  var state = {
    context: null,
    plans: [],
    plan: null,
    designIndex: 0,
    digest: null,
    studies: [],
    study: null,
    busy: false,
    pollTimer: null,
    studyPollTimer: null,
  };

  /* ------------------------------------------------------------------- api */

  function api(method, path, body) {
    return fetch(path, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    })
      .then(function (res) {
        return res
          .json()
          .catch(function () {
            throw new Error(tf("not_json", "HTTP {status}（返回的不是 JSON）", { status: res.status }));
          })
          .then(function (data) {
            if (!res.ok) throw new Error((data && data.error) || "HTTP " + res.status);
            return data;
          });
      })
      .catch(function (err) {
        if (err instanceof TypeError) {
          throw new Error(tf("no_backend", "连不上后端：{error}", { error: err.message }));
        }
        throw err;
      });
  }

  /* ------------------------------------------------------------------ form */

  function currentKind() {
    var checked = document.querySelector("input[name=rwKind]:checked");
    return checked ? checked.value : "idea";
  }

  function syncKindPlaceholder() {
    var area = $("rwText");
    if (currentKind() === "paper") {
      area.placeholder = t(
        "text_ph_paper",
        "把论文的摘要或全文贴在这里（标题、理论、方法、数据、主要发现）。也可以从文件读入。"
      );
    } else {
      area.placeholder = t(
        "text_ph_idea",
        "例如：我想研究在一座 500 人的县城里，给低收入家庭发放租金补贴之后，他们的社交圈会不会扩大、压力会不会下降；和不发补贴的世界比较。"
      );
    }
  }

  function syncRunLabel() {
    var paper = currentKind() === "paper";
    $("rwSkipDigest").hidden = !paper;
    if (state.busy) return;
    $("rwRun").textContent = paper ? t("run_digest", "① 解读论文") : t("run", "生成实施方案");
  }

  /* A digest answers the material it was read from; once the material or
   * its kind changes it no longer does. */
  function dropDigest() {
    if (!state.digest) return;
    state.digest = null;
    renderDigest();
  }

  function syncCount() {
    var limit = (state.context && state.context.limits && state.context.limits.material_chars) || 80000;
    var n = $("rwText").value.length;
    var el = $("rwCount");
    el.textContent = n ? tf("chars", "{n} 字", { n: n }) : "";
    el.classList.toggle("is-over", n > limit);
    if (n > limit) el.textContent += " " + tf("chars_over", "（超出 {limit} 字的部分会被截断）", { limit: limit });
  }

  function fillProviders() {
    var select = $("rwProvider");
    var previous = select.value;
    select.innerHTML = "";
    var routed = document.createElement("option");
    routed.value = "";
    routed.textContent = t("route_by_config", "按配置路由（默认模型）");
    select.appendChild(routed);
    ((state.context && state.context.providers) || []).forEach(function (provider) {
      var option = document.createElement("option");
      option.value = provider.name;
      option.textContent = provider.name + (provider.model ? " · " + provider.model : "") + (provider.is_default ? " ★" : "");
      select.appendChild(option);
    });
    if (previous) select.value = previous;
  }

  /* The same provider list as the top picker, as markup — the study card is
   * built as a string. Blank = whatever the config routes `sim` to. */
  function providerOptions(selected) {
    var chosen = String(selected || "");
    var options = [{ name: "", label: t("route_by_config", "按配置路由（默认模型）") }];
    ((state.context && state.context.providers) || []).forEach(function (provider) {
      options.push({
        name: provider.name,
        label: provider.name + (provider.model ? " · " + provider.model : "") + (provider.is_default ? " ★" : ""),
      });
    });
    return options.map(function (option) {
      return "<option value=\"" + esc(option.name) + "\"" + (option.name === chosen ? " selected" : "") + ">" +
        esc(option.label) + "</option>";
    }).join("");
  }

  function providerLabel(name) {
    if (!name) return t("route_by_config_short", "按配置路由");
    var found = ((state.context && state.context.providers) || []).filter(function (provider) {
      return provider.name === name;
    })[0];
    return found && found.model ? found.name + " · " + found.model : name;
  }

  function renderCatalogueNote() {
    var el = $("rwCatalogue");
    var cat = state.context && state.context.catalogue;
    if (!cat) {
      el.textContent = "";
      return;
    }
    if (cat.available) {
      el.textContent = tf("catalogue_ok", "功能目录：{path}（{n} 字）", { path: cat.path, n: cat.chars });
      el.classList.remove("rw-warn");
    } else {
      el.textContent = tf("catalogue_missing", "找不到功能目录 {path}，方案会只依据平台概况。", { path: cat.path });
      el.classList.add("rw-warn");
    }
  }

  function setProgress(text, mode) {
    var el = $("rwProgress");
    el.textContent = text || "";
    el.classList.toggle("is-live", mode === "live");
    el.classList.toggle("is-error", mode === "error");
  }

  function setBusy(busy) {
    state.busy = busy;
    $("rwRun").disabled = busy;
    $("rwSkipDigest").disabled = busy;
    if ($("rwDesignFromDigest")) $("rwDesignFromDigest").disabled = busy;
    if ($("rwRedigest")) $("rwRedigest").disabled = busy;
    if (busy) $("rwRun").textContent = t("running", "分析中…");
    else syncRunLabel();
  }

  /* ---------------------------------------------------------------- upload */

  function readFile(file) {
    var name = (file.name || "").toLowerCase();
    var hint = $("rwFileHint");
    hint.textContent = tf("reading_file", "正在读取 {name}…", { name: file.name });
    if (name.endsWith(".pdf")) {
      var reader = new FileReader();
      reader.onload = function () {
        api("POST", "/api/research/extract", { name: file.name, data: reader.result })
          .then(function (data) {
            $("rwText").value = data.text || "";
            syncCount();
            hint.textContent = tf("extracted", "已读取 {name}：{pages} 页，{n} 字", {
              name: file.name,
              pages: data.pages,
              n: (data.text || "").length,
            });
            if (!$("rwTitle").value) $("rwTitle").value = file.name.replace(/\.pdf$/i, "");
            var paper = document.querySelector("input[name=rwKind][value=paper]");
            if (paper) {
              paper.checked = true;
              syncKindPlaceholder();
              syncRunLabel();
            }
            dropDigest();
          })
          .catch(function (err) {
            hint.textContent = t("extract_failed", "读取失败：") + err.message;
          });
      };
      reader.onerror = function () {
        hint.textContent = t("read_failed", "读不了这个文件。");
      };
      reader.readAsDataURL(file);
      return;
    }
    var textReader = new FileReader();
    textReader.onload = function () {
      $("rwText").value = String(textReader.result || "");
      syncCount();
      dropDigest();
      hint.textContent = tf("extracted", "已读取 {name}：{pages} 页，{n} 字", {
        name: file.name,
        pages: 1,
        n: $("rwText").value.length,
      });
    };
    textReader.onerror = function () {
      hint.textContent = t("read_failed", "读不了这个文件。");
    };
    textReader.readAsText(file);
  }

  /* --------------------------------------------------------------- analyse */

  function materialPayload() {
    return {
      kind: currentKind(),
      title: $("rwTitle").value.trim(),
      text: $("rwText").value.trim(),
      provider: $("rwProvider").value,
      language: (typeof window.getLocale === "function" && window.getLocale()) || "zh-CN",
    };
  }

  function needText() {
    if ($("rwText").value.trim()) return false;
    setProgress(t("need_text", "先写下研究想法，或粘贴论文内容。"), "error");
    $("rwText").focus();
    return true;
  }

  /* The form's button: a paper is read first, an idea goes straight to a plan. */
  function runPrimary() {
    if (currentKind() === "paper") runDigest();
    else runAnalysis(null);
  }

  function runDigest() {
    if (state.busy || needText()) return;
    setBusy(true);
    setProgress(t("digesting", "正在解读论文…"), "live");
    api("POST", "/api/research/digest", materialPayload())
      .then(function (data) {
        pollJob(data.job_id, t("digesting", "正在解读论文…"), function (result) {
          state.digest = result;
          if (result.title && !$("rwTitle").value.trim()) $("rwTitle").value = result.title;
          setProgress(t("digest_done", "论文解读好了：请核对、修改，再据此设计实验。"), "");
          renderDigest();
          $("rwDigest").scrollIntoView({ behavior: "smooth", block: "start" });
        });
      })
      .catch(function (err) {
        setBusy(false);
        setProgress(t("failed", "分析失败：") + err.message, "error");
      });
  }

  function runAnalysis(digest) {
    if (state.busy || needText()) return;
    var payload = materialPayload();
    if (digest) payload.digest = digest;
    setBusy(true);
    setProgress(t("starting", "正在提交…"), "live");
    api("POST", "/api/research/analyze", payload)
      .then(function (data) {
        poll(data.job_id);
      })
      .catch(function (err) {
        setBusy(false);
        setProgress(t("failed", "分析失败：") + err.message, "error");
      });
  }

  /* A job whose result is handed to onDone as-is (the digest). */
  function pollJob(jobId, liveText, onDone) {
    clearTimeout(state.pollTimer);
    api("GET", "/api/research/jobs/" + encodeURIComponent(jobId))
      .then(function (job) {
        if (job.status === "running") {
          setProgress(job.message || liveText, "live");
          state.pollTimer = setTimeout(function () {
            pollJob(jobId, liveText, onDone);
          }, POLL_MS);
          return;
        }
        setBusy(false);
        if (job.status !== "done") {
          setProgress(t("failed", "分析失败：") + (job.message || ""), "error");
          return;
        }
        onDone(job.result || {});
      })
      .catch(function (err) {
        setBusy(false);
        setProgress(t("task_lost", "任务丢失了：") + err.message, "error");
      });
  }

  /* ---------------------------------------------------------------- digest */

  function lines(text) {
    return String(text || "").split("\n").map(function (line) {
      return line.trim();
    }).filter(Boolean);
  }

  function digestField(id, label, value, rows) {
    return "<label class=\"rw-field\"><span>" + esc(label) + "</span><textarea id=\"" + id + "\" rows=\"" + rows + "\">" +
      esc(value) + "</textarea></label>";
  }

  function renderDigest() {
    var host = $("rwDigest");
    var digest = state.digest;
    if (!digest) {
      host.hidden = true;
      host.innerHTML = "";
      return;
    }
    var paper = digest.paper_digest || {};
    var html = "<h3>" + esc(t("digest_title", "2 · 论文解读（可修改）")) + "</h3>" +
      "<p class=\"rw-hint\">" + esc(t("digest_hint", "模型读出的理论、方法、变量和发现。改掉读错的地方、删掉编造的内容，实验设计会以这里为准。列表类字段每行一条。")) + "</p>";
    if (digest.truncated) html += "<p class=\"rw-hint rw-warn\">" + esc(t("truncated", "（已截断）")) + "</p>";
    html += digestField("rwDgTheory", t("theory", "理论框架"), paper.theory, 3);
    html += digestField("rwDgMethod", t("method", "方法与数据"), paper.method, 3);
    html += digestField("rwDgVariables", t("variables", "关键变量"), (paper.key_variables || []).join("\n"), 3);
    html += digestField("rwDgFindings", t("findings", "主要发现"), paper.findings, 3);
    html += digestField("rwDgQuestions", t("questions", "研究问题"), (digest.research_questions || []).join("\n"), 3);
    html += digestField("rwDgHypotheses", t("hypotheses", "假设"), (digest.hypotheses || []).join("\n"), 4);
    html += "<div class=\"rw-row\"><button class=\"btn ghost\" id=\"rwRedigest\">" + esc(t("redigest", "重新解读")) + "</button>" +
      "<button class=\"btn\" id=\"rwDesignFromDigest\">" + esc(t("design_from_digest", "③ 据此设计实验")) + "</button></div>";
    host.innerHTML = html;
    host.hidden = false;
    $("rwRedigest").addEventListener("click", runDigest);
    $("rwDesignFromDigest").addEventListener("click", function () {
      runAnalysis(readDigest());
    });
    setBusy(state.busy);
  }

  function readDigest() {
    return {
      paper_digest: {
        theory: $("rwDgTheory").value.trim(),
        method: $("rwDgMethod").value.trim(),
        key_variables: lines($("rwDgVariables").value),
        findings: $("rwDgFindings").value.trim(),
      },
      research_questions: lines($("rwDgQuestions").value),
      hypotheses: lines($("rwDgHypotheses").value),
    };
  }

  function poll(jobId) {
    clearTimeout(state.pollTimer);
    api("GET", "/api/research/jobs/" + encodeURIComponent(jobId))
      .then(function (job) {
        if (job.status === "running") {
          setProgress(job.message || t("analyzing", "模型正在分析…"), "live");
          state.pollTimer = setTimeout(function () {
            poll(jobId);
          }, POLL_MS);
          return;
        }
        setBusy(false);
        if (job.status !== "done") {
          setProgress(t("failed", "分析失败：") + (job.message || ""), "error");
          return;
        }
        setProgress(t("done", "方案已生成。"), "");
        var planId = job.result && job.result.plan_id;
        return Promise.all([openPlan(planId), refreshHistory()]);
      })
      .catch(function (err) {
        setBusy(false);
        setProgress(t("task_lost", "任务丢失了：") + err.message, "error");
      });
  }

  /* ----------------------------------------------------------------- plans */

  function refreshHistory() {
    return api("GET", "/api/research/plans").then(function (data) {
      state.plans = data.plans || [];
      renderHistory();
    });
  }

  function openPlan(planId) {
    if (!planId) return Promise.resolve();
    return api("GET", "/api/research/plans/" + encodeURIComponent(planId))
      .then(function (plan) {
        state.plan = plan;
        state.designIndex = plan.recommended_design || 0;
        renderPlan();
        renderHistory();
        $("rwResult").scrollIntoView({ behavior: "smooth", block: "start" });
      })
      .catch(function (err) {
        setProgress(t("open_failed", "打开方案失败：") + err.message, "error");
      });
  }

  function saveMarkdown(data) {
    var blob = new Blob([data.markdown], { type: "text/markdown;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = data.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
    return tf("downloaded", "已下载 {filename}（{kb}KB）", {
      filename: data.filename,
      kb: Math.max(1, Math.round(data.bytes / 1024)),
    });
  }

  function downloadPlan() {
    if (!state.plan) return;
    api("GET", "/api/research/plans/" + encodeURIComponent(state.plan.id) + "/export")
      .then(function (data) {
        setProgress(saveMarkdown(data), "");
      })
      .catch(function (err) {
        setProgress(t("failed", "分析失败：") + err.message, "error");
      });
  }

  /* --------------------------------------------------------------- studies */
  /* A study is a plan carried through protocol → approval → run → verdicts →
   * report. Compiling and running are jobs; the card re-reads the study
   * between stages, so what it shows is always what is on disk. */

  function stageLabel(stage) {
    return {
      protocol: t("stage_protocol", "待批准"),
      approved: t("stage_approved", "已批准"),
      running: t("stage_running", "运行中"),
      evaluated: t("stage_evaluated", "已判定"),
      reported: t("stage_reported", "已出报告"),
      error: t("stage_error", "出错"),
    }[stage] || stage || "";
  }

  function verdictBadge(verdict) {
    var label = {
      supported: t("verdict_supported", "支持"),
      contradicted: t("verdict_contradicted", "反向"),
      inconclusive: t("verdict_inconclusive", "不确定"),
      unmeasured: t("verdict_unmeasured", "未测到"),
    }[verdict] || verdict || "";
    return "<span class=\"rw-verdict rw-verdict-" + esc(verdict) + "\">" + esc(label) + "</span>";
  }

  function roleLabel(role) {
    return {
      baseline: t("role_baseline", "基准"),
      treatment: t("role_treatment", "处理"),
      placebo: t("role_placebo", "安慰剂"),
    }[role] || role || "";
  }

  function directionLabel(direction) {
    return {
      increase: t("direction_increase", "上升"),
      decrease: t("direction_decrease", "下降"),
    }[direction] || direction || "";
  }

  function num(value, signed) {
    if (value === null || value === undefined || isNaN(Number(value))) return "—";
    var n = Number(value);
    return (signed && n > 0 ? "+" : "") + n.toFixed(4);
  }

  function setStudyProgress(text, mode) {
    var el = $("rwStudyProgress");
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("is-live", mode === "live");
    el.classList.toggle("is-error", mode === "error");
  }

  function createStudy() {
    if (!state.plan) return;
    var autopilot = !!($("rwAutopilot") && $("rwAutopilot").checked);
    setProgress(t("compiling", "正在编译预注册协议…"), "live");
    api("POST", "/api/research/studies", {
      plan_id: state.plan.id,
      design_index: (state.plan.designs || []).length > 1 ? state.designIndex : undefined,
      provider: $("rwProvider").value,
      autopilot: autopilot,
    })
      .then(function (data) {
        pollStudyJob(data.job_id);
      })
      .catch(function (err) {
        setProgress(t("study_failed", "研究失败：") + err.message, "error");
      });
  }

  function pollStudyJob(jobId) {
    clearTimeout(state.studyPollTimer);
    api("GET", "/api/research/jobs/" + encodeURIComponent(jobId))
      .then(function (job) {
        if (job.status === "running") {
          setProgress(job.message || t("compiling", "正在编译预注册协议…"), "live");
          state.studyPollTimer = setTimeout(function () {
            pollStudyJob(jobId);
          }, POLL_MS);
          return;
        }
        if (job.status !== "done") {
          setProgress(t("study_failed", "研究失败：") + (job.message || ""), "error");
          return;
        }
        setProgress(t("study_created", "协议已生成。"), "");
        var result = job.result || {};
        return openStudy(result.study_id).then(function () {
          if (result.run_job_id) pollStudyRun(result.run_job_id);
          return refreshStudies();
        });
      })
      .catch(function (err) {
        setProgress(t("task_lost", "任务丢失了：") + err.message, "error");
      });
  }

  function pollStudyRun(jobId) {
    clearTimeout(state.studyPollTimer);
    api("GET", "/api/research/jobs/" + encodeURIComponent(jobId))
      .then(function (job) {
        if (job.status === "running") {
          var paused = !!(state.study && state.study.paused);
          setStudyProgress(
            (paused ? t("paused_progress", "已暂停：") : t("run_progress", "运行中：")) +
              (job.message || "") + " " + Math.round((job.progress || 0) * 100) + "%",
            paused ? "" : "live"
          );
          state.studyPollTimer = setTimeout(function () {
            pollStudyRun(jobId);
          }, POLL_MS);
          return;
        }
        var id = state.study && state.study.id;
        return Promise.all([id ? openStudy(id) : null, refreshStudies()]).then(function () {
          if (job.status !== "done") setStudyProgress(t("study_failed", "研究失败：") + (job.message || ""), "error");
        });
      })
      .catch(function (err) {
        // A job that cannot be read any more (restart, evicted record) is not
        // a study stuck at 运行中: re-read the study, which the server has by
        // then marked interrupted, so its buttons come back.
        var message = t("task_lost", "任务丢失了：") + err.message;
        var id = state.study && state.study.id;
        if (!id) {
          setStudyProgress(message, "error");
          return;
        }
        openStudy(id).then(function () {
          setStudyProgress(message, "error");
          return refreshStudies();
        });
      });
  }

  function refreshStudies() {
    return api("GET", "/api/research/studies").then(function (data) {
      state.studies = data.studies || [];
      renderStudies();
    });
  }

  function openStudy(studyId) {
    if (!studyId) return Promise.resolve();
    return api("GET", "/api/research/studies/" + encodeURIComponent(studyId))
      .then(function (study) {
        state.study = study;
        renderStudy();
        renderStudies();
        if (study.active_job_id) pollStudyRun(study.active_job_id);
        $("rwStudy").scrollIntoView({ behavior: "smooth", block: "start" });
      })
      .catch(function (err) {
        setProgress(t("open_failed", "打开方案失败：") + err.message, "error");
      });
  }

  function studyAction(action, body) {
    if (!state.study) return;
    var id = state.study.id;
    setStudyProgress("…", "live");
    api("POST", "/api/research/studies/" + encodeURIComponent(id) + "/" + action, body || {})
      .then(function (data) {
        var jobId = data.job_id || data.run_job_id;
        // The card is rebuilt by openStudy, so anything the server wants said
        // has to be written into the fresh one.
        return openStudy(id).then(function () {
          setStudyProgress(data.note || "", data.note ? "error" : "");
          if (jobId) pollStudyRun(jobId);
          return refreshStudies();
        });
      })
      .catch(function (err) {
        setStudyProgress(err.message, "error");
      });
  }

  function resetStudy() {
    if (!state.study) return;
    if (!window.confirm(t("reset_ask", "清空这次运行的结果并重新运行？已有的平行世界产物会保留，重跑会另起一份。"))) return;
    studyAction("reset", { run: true });
  }

  function recheckStudy() {
    studyAction("update", {
      seeds: $("rwKnobSeeds").value,
      sim_days: $("rwKnobDays").value,
      fast: $("rwKnobFast").checked,
      agent_ids: $("rwKnobAgents").value,
      sim_provider: $("rwKnobSimProvider").value,
    });
  }

  function downloadStudyReport() {
    if (!state.study) return;
    api("GET", "/api/research/studies/" + encodeURIComponent(state.study.id) + "/report")
      .then(function (data) {
        setStudyProgress(saveMarkdown(data), "");
      })
      .catch(function (err) {
        setStudyProgress(err.message, "error");
      });
  }

  function deleteStudy() {
    if (!state.study) return;
    if (!window.confirm(t("delete_study_ask", "删除这项研究？平行世界的运行产物不会删除。"))) return;
    api("POST", "/api/research/studies/" + encodeURIComponent(state.study.id) + "/delete", {})
      .then(function () {
        state.study = null;
        renderStudy();
        return refreshStudies();
      })
      .catch(function (err) {
        setStudyProgress(err.message, "error");
      });
  }

  function renderStudy() {
    var host = $("rwStudy");
    var study = state.study;
    if (!study) {
      host.hidden = true;
      host.innerHTML = "";
      return;
    }
    var protocol = study.protocol || {};
    var preflight = study.preflight || {};
    var stage = study.stage || "";
    var editable = stage === "protocol" || stage === "error";
    var sample = protocol.sample || {};
    var validity = protocol.validity || {};

    var badges = [
      "<span class=\"rw-badge rw-stage-" + esc(stage) + "\">" + esc(stageLabel(stage)) + "</span>",
      "<span class=\"rw-badge\">" + esc(t("plan_of_study", "来源方案") + "：" + (study.plan_id || "")) + "</span>",
      "<span class=\"rw-badge\">" + esc(fmtTime(study.created_at)) + "</span>",
    ];
    if (study.autopilot) badges.push("<span class=\"rw-badge\">" + esc(t("autopilot_short", "自动执行")) + "</span>");
    if (study.paused) badges.push("<span class=\"rw-badge rw-stage-paused\">" + esc(t("stage_paused", "已暂停")) + "</span>");
    var actions = [];
    if (editable) {
      var can = preflight.ok ? "" : " disabled";
      actions.push("<button class=\"btn tiny\" id=\"rwApprove\"" + can + ">" + esc(t("approve", "批准")) + "</button>");
      actions.push("<button class=\"btn tiny\" id=\"rwApproveRun\"" + can + ">" + esc(t("approve_run", "批准并运行")) + "</button>");
    }
    if (stage === "approved") actions.push("<button class=\"btn tiny\" id=\"rwRunStudy\">" + esc(t("run_study", "运行")) + "</button>");
    if (stage === "running" && study.live) {
      actions.push(study.paused
        ? "<button class=\"btn tiny\" id=\"rwResumeStudy\">" + esc(t("resume", "继续")) + "</button>"
        : "<button class=\"btn tiny ghost\" id=\"rwPauseStudy\">" + esc(t("pause", "暂停")) + "</button>");
      actions.push("<button class=\"btn tiny ghost danger\" id=\"rwStopStudy\">" + esc(t("stop", "停止")) + "</button>");
    }
    // Anything that has already run — including a run cut short — can be put
    // back to the starting line. The old worlds stay on disk.
    if (!study.live && (stage === "evaluated" || stage === "reported" || stage === "error" || (study.runs || []).length)) {
      actions.push("<button class=\"btn tiny ghost\" id=\"rwResetStudy\">" + esc(t("reset_run", "重置运行")) + "</button>");
    }
    actions.push("<button class=\"btn tiny ghost\" id=\"rwDownloadStudy\">" + esc(t("download_report", "下载报告")) + "</button>");
    if (!study.live) actions.push("<button class=\"btn tiny ghost danger\" id=\"rwDeleteStudy\">" + esc(t("delete_study", "删除研究")) + "</button>");

    var html = "<div class=\"rw-result-head\"><div><h3>" + esc(study.title) + "</h3><div class=\"rw-badges\">" + badges.join("") + "</div></div>" +
      "<div class=\"rw-actions\">" + actions.join("") + "</div></div>" +
      "<p class=\"rw-progress\" id=\"rwStudyProgress\" aria-live=\"polite\"></p>";
    if (study.error) html += "<p class=\"rw-rationale rw-warn\">" + esc(study.error) + "</p>";

    var pf = "";
    var budget = preflight.budget || {};
    if (budget.estimated_calls !== undefined) {
      pf += "<p class=\"rw-rationale\"><b>" + esc(t("budget", "估算调用量")) + "：</b>" +
        esc(Number(budget.estimated_calls).toLocaleString() + " / " + Number(budget.limit).toLocaleString() +
          "（" + budget.agents + " × " + budget.sim_days + "d × " + budget.calls_per_agent_day + " × " + budget.worlds + " × " + budget.seeds + "）") + "</p>";
    }
    (preflight.errors || []).forEach(function (item) {
      pf += "<div class=\"rw-gap\"><b>" + esc(item) + "</b></div>";
    });
    (preflight.warnings || []).forEach(function (item) {
      pf += "<div class=\"rw-gap rw-gap-warn\">" + esc(item) + "</div>";
    });
    html += section(t("preflight", "跑前检查"), pf);

    if (editable) {
      html += "<h4>" + esc(t("prereg", "预注册")) + "</h4><div class=\"rw-knobs\">" +
        "<label class=\"rw-field\"><span>" + esc(t("knobs_seeds", "种子（逗号分隔）")) + "</span><input id=\"rwKnobSeeds\" value=\"" + esc((validity.seeds || []).join(", ")) + "\" /></label>" +
        "<label class=\"rw-field\"><span>" + esc(t("knobs_days", "仿真天数")) + "</span><input id=\"rwKnobDays\" type=\"number\" min=\"1\" value=\"" + esc(protocol.sim_days) + "\" /></label>" +
        "<label class=\"rw-field\"><span>" + esc(t("knobs_agents", "参与居民 id（留空 = 全部）")) + "</span><input id=\"rwKnobAgents\" value=\"" + esc((sample.agent_ids || []).join(", ")) + "\" /></label>" +
        "<label class=\"rw-field\"><span>" + esc(t("knobs_sim_provider", "仿真模型（居民跑在哪个模型上）")) + "</span>" +
        "<select id=\"rwKnobSimProvider\">" + providerOptions(protocol.sim_provider) + "</select></label>" +
        "<label class=\"rw-check\"><input type=\"checkbox\" id=\"rwKnobFast\"" + (protocol.fast ? " checked" : "") + " /> " + esc(t("knobs_fast", "快速模式")) + "</label>" +
        "<button class=\"btn tiny ghost\" id=\"rwRecheck\">" + esc(t("recheck", "重新检查")) + "</button></div>";
    } else {
      html += section(t("prereg", "预注册"), dl([
        [t("knobs_seeds", "种子（逗号分隔）"), (validity.seeds || []).join(", ")],
        [t("knobs_days", "仿真天数"), String(protocol.sim_days) + (protocol.fast ? " · " + t("knobs_fast", "快速模式") : "")],
        [t("knobs_agents", "参与居民 id（留空 = 全部）"), (sample.agent_ids || []).join(", ") || "—"],
        [t("sim_model", "仿真模型"), providerLabel(protocol.sim_provider)],
      ]));
    }
    if (sample.note) html += "<p class=\"rw-rationale\">" + esc(sample.note) + "</p>";

    html += "<h4>" + esc(t("conditions", "实验条件")) + "</h4>" +
      "<table class=\"rw-table\"><thead><tr><th>id</th><th>" + esc(t("label", "名称")) + "</th><th>" + esc(t("role", "角色")) +
      "</th><th>" + esc(t("events", "事件")) + "</th></tr></thead><tbody>" +
      (protocol.conditions || []).map(function (cond) {
        var events = (cond.events || []).map(function (e) {
          return "Day " + e.day + " " + e.time + " " + e.name;
        }).join("；") || "—";
        return "<tr><td class=\"rw-feature\">" + esc(cond.id) + "</td><td>" + esc(cond.label) + "</td><td>" + esc(roleLabel(cond.role)) + "</td><td>" + esc(events) + "</td></tr>";
      }).join("") + "</tbody></table>";

    html += "<h4>" + esc(t("hypotheses", "假设")) + "</h4>" +
      "<table class=\"rw-table\"><thead><tr><th>id</th><th>" + esc(t("hypotheses", "假设")) + "</th><th>" + esc(t("measure", "指标")) + "</th><th>" +
      esc(t("contrast", "对比")) + "</th><th>" + esc(t("direction", "预测方向")) + "</th><th>" + esc(t("min_effect", "最小效应")) + "</th></tr></thead><tbody>" +
      (protocol.hypotheses || []).map(function (h) {
        return "<tr><td class=\"rw-feature\">" + esc(h.id) + "</td><td>" + esc(h.statement) + "</td><td><code>" + esc(h.measure) + "</code></td><td>" +
          esc(h.treatment + " vs " + h.control) + "</td><td>" + esc(directionLabel(h.direction)) + "</td><td class=\"rw-num\">" + esc(num(h.min_effect, false)) + " · " + esc(h.aggregation) + "</td></tr>";
      }).join("") + "</tbody></table>";
    if ((protocol.dropped || []).length) {
      html += section(t("dropped", "编译时丢弃"), protocol.dropped.map(function (item) {
        return "<div class=\"rw-gap rw-gap-warn\">" + esc((item.what || "") + " · " + (item.where || "") + "：" + (item.reason || "")) + "</div>";
      }).join(""));
    }

    if ((study.runs || []).length) {
      html += section(t("runs", "执行记录"), "<table class=\"rw-table\"><thead><tr><th>" + esc(t("seed", "种子")) + "</th><th>" + esc(t("status", "状态")) +
        "</th><th>output</th></tr></thead><tbody>" + study.runs.map(function (run) {
          var worlds = Object.keys(run.world_status || {}).map(function (k) { return k + ": " + run.world_status[k]; }).join("，");
          return "<tr><td>" + esc(run.seed) + "</td><td>" + esc(run.status) + (worlds ? "<div class=\"rw-reasons\">" + esc(worlds) + "</div>" : "") + "</td><td><code>" + esc(run.root) + "</code></td></tr>";
        }).join("") + "</tbody></table>");
    }

    var evaluation = study.evaluation || {};
    if ((evaluation.hypotheses || []).length) {
      var summary = evaluation.summary || {};
      var body = "<div class=\"rw-badges\">" + Object.keys(summary).map(function (k) {
        return verdictBadge(k) + " " + esc(summary[k]);
      }).join(" ") + "</div>";
      body += "<table class=\"rw-table\"><thead><tr><th>id</th><th>" + esc(t("verdict", "判定")) + "</th><th>" + esc(t("measure", "指标")) + "</th><th>" +
        esc(t("per_seed", "各种子效应")) + "</th><th>" + esc(t("mean_effect", "均值效应")) + "</th><th>" + esc(t("noise", "噪声底线")) + "</th></tr></thead><tbody>" +
        evaluation.hypotheses.map(function (h) {
          var per = (h.effects || []).map(function (row) { return "s" + row.seed + " " + num(row.effect, true); }).join("，");
          return "<tr><td class=\"rw-feature\">" + esc(h.id) + "</td><td>" + verdictBadge(h.verdict) + "</td><td>" + esc(h.measure_label || h.measure) +
            "</td><td class=\"rw-num\">" + esc(per) + "</td><td class=\"rw-num\">" + esc(num(h.mean_effect, true)) + "</td><td class=\"rw-num\">" + esc(num(h.noise, false)) + "</td></tr>" +
            "<tr><td></td><td colspan=\"5\"><div class=\"rw-reasons\">" + esc((h.statement ? h.statement + " — " : "") + (h.reasons || []).join("；")) + "</div></td></tr>";
        }).join("") + "</tbody></table>";
      var quality = evaluation.quality || {};
      body += "<h4>" + esc(t("quality", "数据质量")) + "</h4>";
      if ((quality.issues || []).length) {
        body += quality.issues.map(function (issue) {
          var where = [issue.seed, issue.condition].filter(function (v) { return v !== null && v !== undefined; }).join(" · ");
          return "<div class=\"rw-gap\"><b>" + esc(issue.issue) + "</b>" + (where ? " " + esc("（" + where + "）") : "") + (issue.detail ? "<div class=\"rw-workaround\">" + esc(issue.detail) + "</div>" : "") + "</div>";
        }).join("");
      } else {
        body += "<p class=\"rw-hint\">" + esc(t("quality_ok", "所有世界都有数据，所有指标都有变化。")) + "</p>";
      }
      html += section(t("results", "结果"), body);

      var interp = study.interpretation || {};
      var ibody = "";
      if (interp.error || !(interp.findings || interp.limitations || interp.next_studies)) {
        ibody = "<p class=\"rw-hint\">" + esc(t("interpretation_missing", "解读不可用") + (interp.error ? "：" + interp.error : "")) + "</p>";
      } else {
        if ((interp.findings || []).length) {
          ibody += "<ul class=\"rw-list\">" + interp.findings.map(function (f) {
            return "<li><b>" + esc(f.hypothesis || "?") + "</b>" + (f.grounded ? "" : " <span class=\"rw-warn\">" + esc("（" + t("ungrounded", "未挂到任何假设，不作数") + "）") + "</span>") +
              " " + esc(f.claim) + (f.evidence ? " <span class=\"rw-reasons\">" + esc(f.evidence) + "</span>" : "") + "</li>";
          }).join("") + "</ul>";
        }
        if ((interp.limitations || []).length) ibody += "<h4>" + esc(t("limitations", "局限")) + "</h4>" + list(interp.limitations);
        if ((interp.next_studies || []).length) {
          ibody += "<h4>" + esc(t("next_studies", "后续研究")) + "</h4>" + interp.next_studies.map(function (n) {
            return "<div class=\"rw-gap\"><b class=\"rw-feature\">" + esc(n.title) + "</b> " + esc(n.rationale || "") + (n.change ? "<div class=\"rw-workaround\">" + esc(n.change) + "</div>" : "") + "</div>";
          }).join("");
        }
      }
      html += section(t("interpretation", "解读"), ibody);
    }
    if (protocol.notes) html += section(t("notes", "备注"), "<p class=\"rw-rationale\">" + esc(protocol.notes) + "</p>");

    host.innerHTML = html;
    host.hidden = false;
    var bind = function (id, fn) {
      var el = $(id);
      if (el) el.addEventListener("click", fn);
    };
    bind("rwApprove", function () { studyAction("approve", {}); });
    bind("rwApproveRun", function () { studyAction("approve", { run: true }); });
    bind("rwRunStudy", function () { studyAction("run", {}); });
    bind("rwStopStudy", function () { studyAction("stop", {}); });
    bind("rwPauseStudy", function () { studyAction("pause", {}); });
    bind("rwResumeStudy", function () { studyAction("resume", {}); });
    bind("rwResetStudy", resetStudy);
    bind("rwRecheck", recheckStudy);
    // Picking a model is one discrete act, so save it right away rather than
    // leaving it to be lost when 批准 skips the knobs.
    var simProvider = $("rwKnobSimProvider");
    if (simProvider) simProvider.addEventListener("change", recheckStudy);
    bind("rwDownloadStudy", downloadStudyReport);
    bind("rwDeleteStudy", deleteStudy);
  }

  function renderStudies() {
    var host = $("rwStudies");
    if (!host) return;
    if (!state.studies.length) {
      host.innerHTML = "<p class=\"rw-hint\">" + esc(t("no_studies", "还没有研究。")) + "</p>";
      return;
    }
    host.innerHTML = state.studies.map(function (item) {
      var active = state.study && state.study.id === item.id;
      var summary = item.summary || {};
      var meta = [stageLabel(item.stage), fmtTime(item.created_at)];
      if (item.stage === "reported" || item.stage === "evaluated") {
        meta.push(t("verdict_supported", "支持") + " " + (summary.supported || 0) + "/" + item.hypotheses);
      }
      return "<button type=\"button\" class=\"rw-history-item" + (active ? " is-active" : "") + "\" data-id=\"" + esc(item.id) + "\">" +
        "<span class=\"rw-hist-title\">" + esc(item.title || item.id) + "</span>" +
        "<span class=\"rw-hist-meta\">" + esc(meta.filter(Boolean).join(" · ")) + "</span></button>";
    }).join("");
    Array.prototype.forEach.call(host.querySelectorAll(".rw-history-item"), function (button) {
      button.addEventListener("click", function () {
        openStudy(button.dataset.id);
      });
    });
  }

  function copyPlan() {
    if (!state.plan || !navigator.clipboard) return;
    navigator.clipboard.writeText(state.plan.markdown || "").then(function () {
      setProgress(t("copied", "已复制 Markdown 到剪贴板。"), "");
    });
  }

  function deletePlan() {
    if (!state.plan) return;
    if (!window.confirm(t("delete_ask", "删除这份方案？"))) return;
    api("POST", "/api/research/delete", { plan_id: state.plan.id })
      .then(function () {
        state.plan = null;
        $("rwResult").hidden = true;
        $("rwResult").innerHTML = "";
        setProgress(t("deleted", "方案已删除。"), "");
        return refreshHistory();
      })
      .catch(function (err) {
        setProgress(t("failed", "分析失败：") + err.message, "error");
      });
  }

  /* ---------------------------------------------------------------- render */

  function kindLabel(kind) {
    return kind === "paper" ? t("kind_paper", "一篇论文") : t("kind_idea", "研究想法");
  }

  function verdictLabel(verdict) {
    return {
      high: t("feas_high", "可行性高"),
      medium: t("feas_medium", "可行性中等"),
      low: t("feas_low", "可行性低"),
    }[verdict] || "";
  }

  function fmtTime(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  }

  function list(items) {
    if (!items || !items.length) return "";
    return "<ul class=\"rw-list\">" + items.map(function (item) {
      return "<li>" + esc(item) + "</li>";
    }).join("") + "</ul>";
  }

  function section(title, body) {
    return body ? "<h4>" + esc(title) + "</h4>" + body : "";
  }

  function renderPlan() {
    var plan = state.plan;
    var host = $("rwResult");
    if (!plan) {
      host.hidden = true;
      host.innerHTML = "";
      return;
    }
    var feas = plan.feasibility || {};
    var badges = [
      "<span class=\"rw-badge\">" + esc(kindLabel(plan.kind)) + "</span>",
      "<span class=\"rw-badge\">" + esc(t("model", "模型") + "：" + (plan.provider || t("route_by_config_short", "按配置路由"))) + "</span>",
      "<span class=\"rw-badge\">" + esc(fmtTime(plan.created_at)) + "</span>",
    ];
    if (feas.verdict) {
      var score = typeof feas.score === "number" && feas.score >= 0 ? " " + feas.score + "/100" : "";
      badges.push("<span class=\"rw-badge feas-" + esc(feas.verdict) + "\">" + esc(verdictLabel(feas.verdict) + score) + "</span>");
    }

    var html = "";
    html += "<div class=\"rw-result-head\"><div><h3>" + esc(plan.title) + "</h3><div class=\"rw-badges\">" + badges.join("") + "</div></div>";
    html += "<div class=\"rw-actions\">" +
      "<button class=\"btn tiny\" id=\"rwToStudy\">" + esc(t("to_study", "转成研究")) + "</button>" +
      "<label class=\"rw-check\" title=\"" + esc(t("autopilot", "自动执行（跑前检查通过即运行）")) + "\"><input type=\"checkbox\" id=\"rwAutopilot\" /> " + esc(t("autopilot_short", "自动执行")) + "</label>" +
      "<button class=\"btn tiny ghost\" id=\"rwDownload\">" + esc(t("download", "下载 Markdown")) + "</button>" +
      "<button class=\"btn tiny ghost\" id=\"rwCopy\">" + esc(t("copy", "复制")) + "</button>" +
      "<button class=\"btn tiny ghost danger\" id=\"rwDelete\">" + esc(t("delete", "删除")) + "</button>" +
      "</div></div>";
    if (plan.summary) html += "<p class=\"rw-summary\">" + esc(plan.summary) + "</p>";
    if (feas.rationale) html += "<p class=\"rw-rationale\"><b>" + esc(t("feasibility", "可行性")) + "：</b>" + esc(feas.rationale) + "</p>";

    var digest = plan.paper_digest || {};
    if (digest.theory || digest.method || digest.findings || (digest.key_variables || []).length) {
      var rows = [];
      if (digest.theory) rows.push([t("theory", "理论框架"), digest.theory]);
      if (digest.method) rows.push([t("method", "方法与数据"), digest.method]);
      if ((digest.key_variables || []).length) rows.push([t("variables", "关键变量"), digest.key_variables.join("；")]);
      if (digest.findings) rows.push([t("findings", "主要发现"), digest.findings]);
      html += section(t("digest", "论文摘要"), dl(rows));
    }
    html += section(t("questions", "研究问题"), list(plan.research_questions));
    html += section(t("hypotheses", "假设"), list(plan.hypotheses));

    if ((plan.capability_map || []).length) {
      html += section(t("map", "功能映射"),
        "<table class=\"rw-table\"><thead><tr><th>" + esc(t("need", "研究需要")) + "</th><th>" + esc(t("feature", "GAWorld 功能")) +
        "</th><th>" + esc(t("how", "用法")) + "</th><th>" + esc(t("entry", "入口")) + "</th></tr></thead><tbody>" +
        plan.capability_map.map(function (row) {
          return "<tr><td>" + esc(row.need) + "</td><td class=\"rw-feature\">" + esc(row.feature) + "</td><td>" + esc(row.how) +
            "</td><td><code>" + esc(row.entry) + "</code></td></tr>";
        }).join("") + "</tbody></table>");
    }

    var designs = planDesigns(plan);
    if (designs.length) {
      var index = Math.min(state.designIndex, designs.length - 1);
      var designHtml = "";
      if (designs.length > 1) {
        designHtml += "<p class=\"rw-hint\">" + esc(t("designs_hint", "几种思路不同的设计，「转成研究」会用当前选中的那个。")) + "</p>" +
          "<div class=\"rw-design-tabs\" role=\"tablist\">" + designs.map(function (d, i) {
            var label = tf("design_n", "设计 {n}", { n: i + 1 }) + (d.name ? "：" + d.name : "");
            var star = i === (plan.recommended_design || 0) ? " <span class=\"rw-rec\">" + esc(t("recommended", "推荐")) + "</span>" : "";
            return "<button type=\"button\" role=\"tab\" class=\"rw-design-tab" + (i === index ? " is-active" : "") +
              "\" aria-selected=\"" + (i === index) + "\" data-index=\"" + i + "\">" + esc(label) + star + "</button>";
          }).join("") + "</div>";
      }
      designHtml += renderDesign(designs[index]);
      html += section(t("design", "实验设计"), designHtml);
    }

    if ((plan.steps || []).length) {
      html += section(t("steps", "实施步骤"), "<ol class=\"rw-steps\">" + plan.steps.map(function (step) {
        var inner = "<span class=\"rw-step-title\">" + esc(step.title) + "</span>";
        if (step.panel) inner += "<span class=\"rw-step-panel\">" + esc(step.panel) + "</span>";
        if (step.detail) inner += "<p class=\"rw-step-detail\">" + esc(step.detail) + "</p>";
        if ((step.commands || []).length) inner += "<pre>" + esc(step.commands.join("\n")) + "</pre>";
        return "<li class=\"rw-step\">" + inner + "</li>";
      }).join("") + "</ol>");
    }

    html += section(t("validation", "可信度检验"), list(plan.validation));
    if ((plan.gaps || []).length) {
      html += section(t("gaps", "局限与替代"), plan.gaps.map(function (gap) {
        return "<div class=\"rw-gap\"><b>" + esc(gap.limitation) + "</b>" +
          (gap.workaround ? "<div class=\"rw-workaround\">" + esc(t("workaround", "替代做法")) + "：" + esc(gap.workaround) + "</div>" : "") + "</div>";
      }).join(""));
    }
    var cost = plan.estimated_cost || {};
    if (cost.llm_calls || cost.note) {
      var costRows = [];
      if (cost.llm_calls) costRows.push([t("calls", "模型调用"), cost.llm_calls]);
      if (cost.note) costRows.push([t("note", "建议"), cost.note]);
      html += section(t("cost", "成本估算"), dl(costRows));
    }
    if (plan.material) {
      html += "<details class=\"rw-material\"><summary>" + esc(t("material", "原始材料")) +
        (plan.material_truncated ? " " + esc(t("truncated", "（已截断）")) : "") + "</summary><pre>" + esc(plan.material) + "</pre></details>";
    }

    host.innerHTML = html;
    host.hidden = false;
    $("rwToStudy").addEventListener("click", createStudy);
    $("rwDownload").addEventListener("click", downloadPlan);
    $("rwCopy").addEventListener("click", copyPlan);
    $("rwDelete").addEventListener("click", deletePlan);
    Array.prototype.forEach.call(host.querySelectorAll(".rw-design-tab"), function (tab) {
      tab.addEventListener("click", function () {
        state.designIndex = Number(tab.dataset.index) || 0;
        renderPlan();
      });
    });
  }

  /* Plans saved before alternatives existed carry only `design`. */
  function planDesigns(plan) {
    if ((plan.designs || []).length) return plan.designs;
    var design = plan.design || {};
    return Object.keys(design).some(function (key) {
      var value = design[key];
      return Array.isArray(value) ? value.length : value;
    }) ? [design] : [];
  }

  function renderDesign(design) {
    var rows = [];
    if (design.approach) rows.push([t("approach", "思路"), design.approach]);
    if (design.strengths) rows.push([t("strengths", "优势"), design.strengths]);
    if (design.weaknesses) rows.push([t("weaknesses", "短板"), design.weaknesses]);
    if (design.city) rows.push([t("city", "城市"), design.city]);
    if (design.population) rows.push([t("population", "人口"), design.population]);
    if (design.agents) rows.push([t("agents", "Agent 设定"), design.agents]);
    if (design.timeline) rows.push([t("timeline", "时间跨度"), design.timeline]);
    var html = dl(rows);
    if ((design.conditions || []).length) {
      html += "<h4>" + esc(t("conditions", "实验条件")) + "</h4>" + list(design.conditions.map(function (c) {
        return (c.name || "") + (c.manipulation ? "：" + c.manipulation : "");
      }));
    }
    if ((design.events || []).length) html += "<h4>" + esc(t("events", "事件")) + "</h4>" + list(design.events);
    if ((design.measures || []).length) {
      html += "<h4>" + esc(t("measures", "测量指标")) + "</h4>" +
        "<table class=\"rw-table\"><thead><tr><th>" + esc(t("measure", "指标")) + "</th><th>" + esc(t("operationalization", "操作化")) +
        "</th><th>" + esc(t("source", "来源")) + "</th></tr></thead><tbody>" +
        design.measures.map(function (m) {
          return "<tr><td>" + esc(m.name) + "</td><td>" + esc(m.operationalization) + "</td><td><code>" + esc(m.source) + "</code></td></tr>";
        }).join("") + "</tbody></table>";
    }
    return html;
  }

  function dl(rows) {
    if (!rows.length) return "";
    return "<dl class=\"rw-dl\">" + rows.map(function (row) {
      return "<dt>" + esc(row[0]) + "</dt><dd>" + esc(row[1]) + "</dd>";
    }).join("") + "</dl>";
  }

  function renderHistory() {
    var host = $("rwHistory");
    if (!state.plans.length) {
      host.innerHTML = "<p class=\"rw-hint\">" + esc(t("no_history", "还没有生成过方案。")) + "</p>";
      return;
    }
    host.innerHTML = state.plans.map(function (item) {
      var active = state.plan && state.plan.id === item.id;
      var meta = [kindLabel(item.kind), verdictLabel(item.verdict), fmtTime(item.created_at)].filter(Boolean).join(" · ");
      return "<button type=\"button\" class=\"rw-history-item" + (active ? " is-active" : "") + "\" data-id=\"" + esc(item.id) + "\">" +
        "<span class=\"rw-hist-title\">" + esc(item.title || item.id) + "</span>" +
        "<span class=\"rw-hist-meta\">" + esc(meta) + "</span></button>";
    }).join("");
    Array.prototype.forEach.call(host.querySelectorAll(".rw-history-item"), function (button) {
      button.addEventListener("click", function () {
        openPlan(button.dataset.id);
      });
    });
  }

  function renderTopMeta() {
    var el = $("rwTopMeta");
    var n = (state.context && state.context.providers || []).length;
    el.textContent = tf("topmeta", "{n} 个可用模型 · {m} 份历史方案", { n: n, m: state.plans.length });
  }

  /* ------------------------------------------------------------------ init */

  function init() {
    document.querySelectorAll("input[name=rwKind]").forEach(function (radio) {
      radio.addEventListener("change", function () {
        syncKindPlaceholder();
        syncRunLabel();
        dropDigest();
      });
    });
    $("rwText").addEventListener("input", function () {
      syncCount();
      dropDigest();
    });
    $("rwFile").addEventListener("change", function (event) {
      var file = event.target.files && event.target.files[0];
      if (file) readFile(file);
      event.target.value = "";
    });
    $("rwRun").addEventListener("click", runPrimary);
    $("rwSkipDigest").addEventListener("click", function () {
      runAnalysis(null);
    });

    document.addEventListener("locale-changed", function () {
      fillProviders();
      syncKindPlaceholder();
      syncCount();
      renderCatalogueNote();
      renderDigest();
      renderPlan();
      renderHistory();
      renderStudy();
      renderStudies();
      renderTopMeta();
      syncRunLabel();
    });

    api("GET", "/api/research/context")
      .then(function (context) {
        state.context = context;
        state.plans = context.plans || [];
        state.studies = context.studies || [];
        fillProviders();
        renderCatalogueNote();
        renderHistory();
        renderStudies();
        renderTopMeta();
        syncKindPlaceholder();
        syncRunLabel();
        syncCount();
      })
      .catch(function (err) {
        setProgress(err.message, "error");
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
