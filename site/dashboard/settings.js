/* 配置中心 —— 项目里所有配置项的唯一入口。
 *
 * 四个刻意的设计：
 *
 * - **表单是从配置本身长出来的**，和 external.js 同因：这棵树有 500+ 个叶子，手写
 *   表单写不完，也会在加旋钮的当天过期。这里按 JSON 形状渲染控件，后端再按现有配置
 *   的类型把补丁强制成形。
 * - **每一项都必有 hover 说明**。有人写过的说明就用人写的，没有的就退回「路径 · 类型 ·
 *   默认值 · 这个值从哪来」。后者听起来简陋，但它回答的恰恰是最常卡住人的那个问题。
 * - **来源比数值更重要**。改了一项、保存成功、却什么都没变，是这里最贵的一种困惑：
 *   data/environment_config.json 在覆盖链的最后一环，它写了的键，你在别处改都白改。
 *   所以来自它的项会被标红并明说「在这里改不生效」。
 * - **搜索是跨分区的**。一个人想调「通胀」时，他不知道通胀属于哪个分区，也不该知道。
 */
(function () {
  "use strict";

  /* These tables hold locale *keys*, not text. They are module-level, so any
     literal in them would freeze whatever language was current when this file
     was evaluated — and the locale JSON has not even arrived by then. */
  var META_TABS = [
    { id: "__env", titleKey: "set.tab_env", helpKey: "set.tab_env_help" },
    { id: "__files", titleKey: "set.tab_files", helpKey: "set.tab_files_help" },
  ];

  var SOURCE_LABEL_KEYS = {
    "default": "set.src_default",
    dashboard: "set.src_dashboard",
    env: "set.src_env",
  };

  var SOURCE_SHORT_KEYS = {
    dashboard: "set.src_short_dashboard",
    env: "set.src_short_env",
    env_file: "set.src_short_env_file",
  };

  /* data/environment_config.json is a path, not prose, so it has no key. */
  function sourceLabel(source) {
    var key = SOURCE_LABEL_KEYS[source];
    if (key) return __(key);
    return source === "env_file" ? "data/environment_config.json" : source;
  }

  function sourceShort(source) {
    var key = SOURCE_SHORT_KEYS[source];
    return key ? __(key) : source;
  }

  var PROVIDER_TYPES = {
    ollama: {
      labelKey: "set.pt_ollama",
      endpoint: "http://localhost:11434/api/generate",
      needsKey: false,
      noteKey: "set.pt_ollama_note",
    },
    openai: {
      labelKey: "set.pt_openai",
      endpoint: "https://api.openai.com/v1",
      needsKey: true,
      noteKey: "set.pt_openai_note",
    },
    anthropic: {
      labelKey: "set.pt_anthropic",
      endpoint: "https://api.anthropic.com",
      needsKey: true,
      noteKey: "set.pt_anthropic_note",
    },
  };

  var state = {
    data: null,
    tab: null,
    query: "",
    onlyOverridden: false,
    dirty: {},   // "economy.macro.initial_inflation_rate" -> value
    invalid: {}, // 同 key，JSON 文本框解析不了时为 true
    busy: false,
    probes: {},  // 后端名 -> {busy|ok|error}，测试结果就地更新，不重绘整页
    draft: { type: "ollama", name: "", endpoint: "", model: "", api_key_env: "", timeout: "" },
  };

  /* ----------------------------------------------------------------- utils */

  function $(id) {
    return document.getElementById(id);
  }

  function esc(text) {
    return String(text == null ? "" : text).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function has(obj, key) {
    return Object.prototype.hasOwnProperty.call(obj, key);
  }

  function pathKey(prefix, key) {
    return prefix ? prefix + "." + key : String(key);
  }

  /** 按点分路径取值。中途断链返回 undefined，而不是抛错。 */
  function at(root, path) {
    var node = root;
    var parts = String(path).split(".");
    for (var i = 0; i < parts.length; i++) {
      if (node == null || typeof node !== "object") return undefined;
      node = node[parts[i]];
    }
    return node;
  }

  function typeName(value) {
    if (value === null) return __("set.type_null");
    if (Array.isArray(value)) return __f("set.type_list", { count: value.length });
    if (typeof value === "object") return __("set.type_group");
    if (typeof value === "boolean") return __("set.type_bool");
    if (typeof value === "number") return __("set.type_number");
    return __("set.type_text");
  }

  function preview(value) {
    if (value === undefined) return __("set.no_default");
    if (value === null) return "null";
    if (typeof value === "string") return value.length > 60 ? value.slice(0, 59) + "…" : value;
    var text;
    try {
      text = JSON.stringify(value);
    } catch (err) {
      return String(value);
    }
    return text.length > 60 ? text.slice(0, 59) + "…" : text;
  }

  function docFor(path) {
    return (state.data && state.data.docs && state.data.docs[path]) || {};
  }

  /* The server sends both languages per field (label / label_en, help /
     help_en) and leaves the choice here, so switching language needs no
     refetch. A missing *_en means nobody has written the English — the ~600
     extracted source comments never will, since they are Python comments for
     whoever maintains the settings modules. Falling back to the Chinese shows
     the only text that exists, which beats a blank tooltip. */
  function english() {
    return typeof getLocale === "function" && getLocale() === "en";
  }

  function pickLang(zh, en) {
    return (english() && en) || zh || "";
  }

  function labelFor(path) {
    var doc = docFor(path);
    return pickLang(doc.label, doc.label_en) || path.split(".").pop();
  }

  function helpFor(path) {
    var doc = docFor(path);
    return pickLang(doc.help, doc.help_en);
  }

  function sectionTitle(section) {
    return pickLang(section.title, section.title_en);
  }

  function sectionHelp(section) {
    return pickLang(section.help, section.help_en);
  }

  function sourceFor(path) {
    return (state.data && state.data.sources && state.data.sources[path]) || "default";
  }

  function defaultFor(path) {
    return at(state.data ? state.data.defaults : null, path);
  }

  /** 闭集取值（目前只有模型路由）。没有就返回 null，走原来的自由文本框。 */
  function choicesFor(path) {
    var map = (state.data && state.data.choices) || {};
    return has(map, path) ? map[path] : null;
  }

  function isReadOnly(path) {
    var list = (state.data && state.data.read_only) || [];
    for (var i = 0; i < list.length; i++) {
      if (path === list[i] || path.indexOf(list[i] + ".") === 0) return true;
    }
    return false;
  }

  /** 每一项都有说明：人写的在前，「路径/类型/默认/来源」永远兜底。 */
  function helpText(path, value) {
    var lines = [];
    var curated = helpFor(path);
    if (curated) lines.push(curated);
    var source = sourceFor(path);
    lines.push(__("set.help_path") + path);
    lines.push(__("set.help_type") + typeName(value));
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      lines.push(__("set.help_default") + preview(defaultFor(path)));
    }
    lines.push(__("set.help_source") + sourceLabel(source));
    if (source === "env_file") {
      lines.push(__("set.warn_env_file"));
    } else if (source === "env") {
      lines.push(__("set.warn_env"));
    }
    if (isReadOnly(path)) {
      lines.push(__("set.warn_readonly"));
    }
    return lines.join("\n");
  }

  function tipFor(path, value) {
    return ' <span class="help-tip" data-help="' + esc(helpText(path, value)) + '"></span>';
  }

  /* -------------------------------------------------------------------- api */

  /** 失败一定看得见，busy 一定清掉：卡住的 busy 看起来就是「按钮没反应」。 */
  function api(method, path, body) {
    state.busy = true;
    syncFooter();
    return fetch(path, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    })
      .then(function (res) {
        return res
          .json()
          .catch(function () {
            throw new Error(__f("set.not_json", { status: res.status }));
          })
          .then(function (payload) {
            if (!res.ok) throw new Error(payload.error || "HTTP " + res.status);
            return payload;
          });
      })
      .catch(function (err) {
        status(String(err.message || err), "bad");
        throw err;
      })
      .then(
        function (payload) {
          state.busy = false;
          return payload;
        },
        function (err) {
          state.busy = false;
          syncFooter();
          throw err;
        }
      );
  }

  function status(text, kind) {
    var el = $("setStatus");
    el.className = "set-status" + (kind ? " is-" + kind : "");
    el.textContent = text || "";
  }

  /* ------------------------------------------------------------- 树的渲染 */

  function currentValue(path, fallback) {
    return has(state.dirty, path) ? state.dirty[path] : fallback;
  }

  function fieldClass(path) {
    var source = sourceFor(path);
    return "set-field" +
      (has(state.dirty, path) ? " is-dirty" : "") +
      (state.invalid[path] ? " is-bad" : "") +
      (source !== "default" ? " is-overridden" : "") +
      (source === "env_file" || source === "env" ? " is-shadowed" : "");
  }

  /** 「已改 / 环境文件」小标签 + 单项恢复默认。 */
  function badges(path) {
    var source = sourceFor(path);
    if (source === "default") return "";
    var out = '<span class="set-badge is-' + source + '">' + esc(sourceShort(source)) + "</span>";
    if (source === "dashboard") {
      out += '<button type="button" class="set-revert" data-revert="' + esc(path) +
        '" title="' + esc(__("set.revert_title")) + '">↺</button>';
    }
    return out;
  }

  function labelCell(path, value) {
    return '<span class="set-label">' + esc(labelFor(path)) + tipFor(path, value) +
      '<code class="set-path">' + esc(path.split(".").pop()) + "</code>" + badges(path) + "</span>";
  }

  /** 下拉选项。当前值不在清单里也要列出来并标明 ——
   *  悄悄显示成另一个后端，比显示一个坏值更危险。 */
  function optionsHtml(options, current) {
    var list = options.slice();
    var stale = current && list.indexOf(current) < 0;
    if (stale) list.unshift(current);
    return list.map(function (name) {
      return '<option value="' + esc(name) + '"' + (name === current ? " selected" : "") + ">" +
        esc(name) + (stale && name === current ? esc(__("set.provider_missing")) : "") + "</option>";
    }).join("");
  }

  /** 搜索命中判断：标签、路径、说明都算。 */
  function matches(path) {
    if (!state.query) return true;
    var doc = docFor(path);
    /* Search both languages regardless of the current one: someone reading
       the English panel may well remember the Chinese label, and vice versa. */
    var hay = [path, doc.label, doc.label_en, doc.help, doc.help_en]
      .filter(Boolean).join(" ").toLowerCase();
    return hay.indexOf(state.query) >= 0;
  }

  function overriddenOk(path) {
    return !state.onlyOverridden || sourceFor(path) !== "default";
  }

  /** 子树里有没有任何一个叶子通过了当前的搜索/筛选。 */
  function subtreeVisible(value, path) {
    if (value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length) {
      if (matches(path) && !state.onlyOverridden) return true;
      var keys = Object.keys(value);
      for (var i = 0; i < keys.length; i++) {
        if (subtreeVisible(value[keys[i]], pathKey(path, keys[i]))) return true;
      }
      return false;
    }
    return matches(path) && overriddenOk(path);
  }

  function renderNode(key, value, path, depth) {
    if (!subtreeVisible(value, path)) return "";

    if (value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length) {
      var body = Object.keys(value).map(function (childKey) {
        return renderNode(childKey, value[childKey], pathKey(path, childKey), depth + 1);
      }).join("");
      var open = depth === 0 || !!state.query || state.onlyOverridden;
      // Wrap the group name in a heading so the nineteen collapsible groups
      // show up in the document outline. The role goes on an inner span, not
      // on <summary> itself — that would override summary's own disclosure
      // role and cost the expand/collapse semantics. display:contents keeps
      // the extra element out of the layout.
      var level = Math.min(depth + 3, 6);
      return '<details class="set-group depth-' + depth + '"' + (open ? " open" : "") + ">" +
        "<summary>" +
        '<span class="set-group-heading" role="heading" aria-level="' + level + '">' +
        labelCell(path, value) + "</span>" +
        "</summary>" +
        '<div class="set-group-body">' + body + "</div></details>";
    }

    var locked = isReadOnly(path);
    var attrs = ' data-path="' + esc(path) + '"' + (locked ? " disabled" : "");

    if (typeof value === "boolean") {
      var on = currentValue(path, value);
      return '<label class="' + fieldClass(path) + ' is-inline">' +
        '<input type="checkbox" data-kind="bool"' + attrs + (on ? " checked" : "") + " />" +
        labelCell(path, value) + "</label>";
    }

    if (typeof value === "number") {
      return '<label class="' + fieldClass(path) + '">' + labelCell(path, value) +
        '<input type="number" step="any" data-kind="number"' + attrs +
        ' value="' + esc(currentValue(path, value)) + '" /></label>';
    }

    if (typeof value === "string") {
      var text = String(currentValue(path, value));
      var options = choicesFor(path);
      if (options) {
        return '<label class="' + fieldClass(path) + '">' + labelCell(path, value) +
          '<select data-kind="text"' + attrs + ">" + optionsHtml(options, text) + "</select></label>";
      }
      if (text.length > 80) {
        return '<label class="' + fieldClass(path) + '">' + labelCell(path, value) +
          '<textarea data-kind="text"' + attrs + ">" + esc(text) + "</textarea></label>";
      }
      return '<label class="' + fieldClass(path) + '">' + labelCell(path, value) +
        '<input type="text" data-kind="text"' + attrs + ' value="' + esc(text) + '" /></label>';
    }

    // 列表 / null / 空对象：JSON 文本框。给这些做结构化控件得不偿失，而 JSON 可校验。
    var raw = currentValue(path, value);
    var json = typeof raw === "string" && state.invalid[path] ? raw : JSON.stringify(raw);
    return '<label class="' + fieldClass(path) + '">' + labelCell(path, value) +
      (state.invalid[path] ? '<b class="set-warn">' + esc(__("set.json_invalid")) + "</b>" : "") +
      '<textarea data-kind="json"' + attrs + ">" + esc(json) + "</textarea></label>";
  }

  /* ---------------------------------------------------------- 语言模型卡片 */

  /* 这一段是整个面板里唯一一处手写表单，因为「模型」这一项的三件事都是通用树渲染
   * 不可能长出来的：选后端要的是闭集下拉而不是自由文本、加后端要的是一次写进一整
   * 个块、测连通性根本不是配置读写。其余 500 多项仍然走下面的通用渲染。 */

  function providerRows() {
    return (state.data && state.data.providers) || [];
  }

  function probeHtml(probe) {
    if (!probe) return "";
    if (probe.busy) return '<span class="llm-result is-busy">' + esc(__("set.probe_busy")) + "</span>";
    if (probe.ok) {
      return '<span class="llm-result is-ok">' + esc(probe.sample
        ? __f("set.probe_ok_sample", { ms: probe.latency_ms, sample: probe.sample })
        : __f("set.probe_ok", { ms: probe.latency_ms })) + "</span>";
    }
    return '<span class="llm-result is-bad">✗ ' + esc(probe.error || __("set.probe_failed")) + "</span>";
  }

  function renderPicker() {
    var path = "llm.routing.default";
    var value = String(currentValue(path, at(state.data.tree, path) || ""));
    var options = choicesFor(path) || [];
    var help = __("set.pick_help");
    return '<div class="llm-card llm-pick">' +
      "<h3>" + esc(__("set.pick_title")) +
        '<span class="help-tip" data-help="' + esc(help) + '"></span></h3>' +
      '<label class="' + fieldClass(path) + '">' +
      '<span class="set-label">' + esc(__("set.pick_default")) +
        '<code class="set-path">' + esc(path) + "</code>" + badges(path) + "</span>" +
      '<select data-kind="text" data-path="' + esc(path) + '">' + optionsHtml(options, value) + "</select></label>" +
      '<p class="set-hint">' + esc(__("set.pick_hint")) + "</p></div>";
  }

  function renderProviderList() {
    var rows = providerRows().map(function (item) {
      var meta = [
        item.type,
        item.model,
        item.endpoint,
        item.timeout ? __f("set.timeout_meta", { seconds: item.timeout }) : "",
      ].filter(Boolean).map(esc).join(" · ");
      var key = "";
      if (item.needs_key) {
        key = item.key_ready
          ? '<span class="llm-key is-ok">' + esc(__("set.key_ready")) + "</span>"
          : '<span class="llm-key is-bad">' + esc(__f("set.key_missing", {
              envs: item.api_key_envs.join("、") || __("set.key_env_unset"),
            })) + "</span>";
      }
      return '<div class="llm-row' + (item.is_default ? " is-default" : "") + '">' +
        '<div class="llm-row-head"><b>' + esc(item.name) + "</b>" +
        (item.is_default
          ? '<span class="set-badge is-dashboard">' + esc(__("set.badge_default")) + "</span>" : "") +
        (item.editable
          ? '<span class="set-badge is-dashboard">' + esc(__("set.badge_added_here")) + "</span>" : "") +
        key + "</div>" +
        '<div class="llm-row-meta">' + meta + "</div>" +
        '<div class="llm-row-actions">' +
        '<button type="button" class="button subtle" data-test-provider="' + esc(item.name) + '">' +
          esc(__("set.test_connection")) + "</button>" +
        (item.editable
          ? '<button type="button" class="button subtle" data-drop-provider="' + esc(item.name) +
            '" title="' + esc(__("set.drop_provider_title")) + '">' + esc(__("set.drop_provider")) + "</button>"
          : "") +
        '<span class="llm-slot" data-result="' + esc(item.name) + '">' +
        probeHtml(state.probes[item.name]) + "</span></div></div>";
    }).join("");
    var help = __("set.provider_list_help");
    return '<div class="llm-card">' +
      "<h3>" + esc(__("set.provider_list_title")) +
      ' <span class="set-count">' + providerRows().length + "</span>" +
      '<span class="help-tip" data-help="' + esc(help) + '"></span></h3>' +
      (rows || '<p class="set-hint">' + esc(__("set.no_providers")) + "</p>") + "</div>";
  }

  function renderAddForm() {
    var draft = state.draft;
    var spec = PROVIDER_TYPES[draft.type] || PROVIDER_TYPES.ollama;
    var types = Object.keys(PROVIDER_TYPES).map(function (id) {
      return '<option value="' + id + '"' + (id === draft.type ? " selected" : "") + ">" +
        esc(__(PROVIDER_TYPES[id].labelKey)) + "（" + id + "）</option>";
    }).join("");
    function field(key, label, placeholder, help) {
      return '<label class="llm-field"><span>' + esc(label) +
        '<span class="help-tip" data-help="' + esc(help) + '"></span></span>' +
        '<input type="text" data-draft="' + key + '" value="' + esc(draft[key]) +
        '" placeholder="' + esc(placeholder) + '" /></label>';
    }
    return '<div class="llm-form">' +
      '<label class="llm-field"><span>' + esc(__("set.field_type")) + '<span class="help-tip" data-help="' + esc(__(spec.noteKey)) +
      '"></span></span><select data-draft="type">' + types + "</select></label>" +
      field("name", __("set.field_name"), __("set.field_name_ph"), __("set.field_name_help")) +
      field("model", __("set.field_model"), draft.type === "ollama" ? "qwen3.5:9b" : "gpt-5.4",
        __("set.field_model_help")) +
      field("endpoint", __("set.field_endpoint"), spec.endpoint,
        __f("set.field_endpoint_help", { endpoint: spec.endpoint })) +
      (spec.needsKey
        ? field("api_key_env", __("set.field_key_env"), "MY_PROVIDER_API_KEY",
            __("set.field_key_env_help"))
        : "") +
      field("timeout", __("set.field_timeout"), spec.needsKey ? "120" : "600",
        __("set.field_timeout_help")) +
      '<div class="llm-form-actions">' +
      '<button type="button" class="button subtle" id="llmDraftTest">' + esc(__("set.draft_test")) + "</button>" +
      '<button type="button" class="button primary" id="llmDraftSave">' + esc(__("set.draft_save")) + "</button>" +
      '<span class="llm-slot" id="llmDraftResult">' + probeHtml(state.probes.__draft) + "</span></div></div>";
  }

  function renderAddCard() {
    var help = __("set.add_card_help");
    return '<div class="llm-card">' +
      "<h3>" + esc(__("set.add_card_title")) +
        '<span class="help-tip" data-help="' + esc(help) + '"></span></h3>' +
      '<div id="llmAddBox">' + renderAddForm() + "</div></div>";
  }

  function renderLlmPanel() {
    return renderPicker() + renderProviderList() + renderAddCard();
  }

  /* ------------------------------------------------------------ 各页签内容 */

  function renderSection(section) {
    var tree = state.data.tree;
    var head = section.id === "llm" ? renderLlmPanel() : "";
    var body = section.keys.map(function (key) {
      return renderNode(key, tree[key], key, 0);
    }).join("");
    if (!body) {
      if (head) return '<p class="set-section-help">' + esc(sectionHelp(section)) + "</p>" + head;
      return '<p class="set-hint">' +
        esc(state.query
          ? __f("set.section_no_match", { query: state.query })
          : __("set.section_empty")) +
        "</p>";
    }
    return '<p class="set-section-help">' + esc(sectionHelp(section)) + "</p>" + head + body;
  }

  /** 搜索时跨分区平铺，因为想调「通胀」的人不该先知道它属于哪个分区。 */
  function renderSearch() {
    var tree = state.data.tree;
    var blocks = state.data.sections.map(function (section) {
      var body = section.keys.map(function (key) {
        return renderNode(key, tree[key], key, 0);
      }).join("");
      if (!body) return "";
      return '<div class="set-search-group"><h3>' + esc(sectionTitle(section)) + "</h3>" + body + "</div>";
    }).join("");
    if (!blocks) {
      return '<p class="set-hint">' + esc(__f("set.search_no_match", { query: state.query })) + "</p>";
    }
    return blocks;
  }

  function renderEnv() {
    var env = state.data.env;
    var groups = {};
    var order = [];
    env.vars.forEach(function (item) {
      var name = item.group || __("set.env_group_other");
      if (!groups[name]) { groups[name] = []; order.push(name); }
      groups[name].push(item);
    });
    var rows = order.map(function (name) {
      var items = groups[name].map(function (item) {
        var help = [
          item.help || __("set.env_no_doc"),
          __f("set.env_var_name", { name: item.name }),
          __(item.set ? "set.env_state_set" : "set.env_state_unset"),
          __(item.secret ? "set.env_is_secret" : "set.env_not_secret"),
          __("set.env_edit_note"),
        ].join("\n");
        return '<div class="set-env-row' + (item.set ? " is-set" : "") + '">' +
          '<code class="set-env-name">' + esc(item.name) + "</code>" +
          '<span class="help-tip" data-help="' + esc(help) + '"></span>' +
          '<span class="set-env-state">' + esc(__(item.set ? "set.env_set" : "set.env_unset")) + "</span>" +
          '<span class="set-env-value">' + (item.value ? esc(item.value) : "—") + "</span>" +
          '<span class="set-env-help">' + esc(item.help || "") + "</span></div>";
      }).join("");
      return '<div class="set-env-group"><h3>' + esc(name) + "</h3>" + items + "</div>";
    }).join("");
    return '<p class="set-section-help">' + __("set.env_intro") + "</p>" +
      '<p class="set-envfile">' + esc(__("set.env_file_label")) +
      "<code>" + esc(env.env_file) + "</code> · " +
      (env.env_file_exists
        ? esc(__("set.exists"))
        : '<b class="set-warn">' + esc(__("set.not_exists")) + "</b>") + "</p>" + rows;
  }

  function renderFiles() {
    var files = state.data.files;
    function block(id, title, note, info) {
      return '<div class="set-file"><h3>' + esc(title) +
        '<span class="help-tip" data-help="' + esc(note) + '"></span></h3>' +
        '<p class="set-filepath"><code>' + esc(info.path) + "</code> · " +
        esc(__(info.exists ? "set.exists" : "set.not_exists")) + "</p>" +
        '<pre class="codebox">' + esc(info.text || __("set.file_empty")) + "</pre></div>";
    }
    return block(
      "dashboard",
      "dashboard_config.json",
      __("set.file_dashboard_note"),
      files.dashboard_config
    ) + block(
      "environment",
      "data/environment_config.json",
      __("set.file_env_note"),
      files.environment_config
    );
  }

  /* --------------------------------------------------------------- 侧边栏 */

  function dirtyPaths() {
    return Object.keys(state.dirty);
  }

  function renderSide() {
    var paths = dirtyPaths();
    var overridden = Object.keys(state.data.sources || {});
    var shadowed = overridden.filter(function (p) {
      return state.data.sources[p] === "env_file" || state.data.sources[p] === "env";
    });

    var pending = paths.length
      ? '<ul class="set-pending">' + paths.map(function (path) {
          return "<li" + (state.invalid[path] ? ' class="is-bad"' : "") + ">" +
            '<code>' + esc(path) + "</code>" +
            "<span>" + esc(preview(state.dirty[path])) + "</span>" +
            '<button type="button" class="set-undo" data-undo="' + esc(path) + '" title="' + esc(__("set.undo_title")) + '">×</button>' +
            "</li>";
        }).join("") + "</ul>"
      : '<p class="set-hint">' + esc(__("set.no_pending")) + "</p>";

    return '<div class="set-card">' +
      "<h3>" + esc(__("set.pending_title")) +
      ' <span class="set-count">' + paths.length + "</span>" +
      '<span class="help-tip" data-help="' + esc(__("set.pending_help")) + '"></span></h3>' +
      pending + "</div>" +
      '<div class="set-card">' +
      "<h3>" + esc(__("set.overrides_title")) +
      '<span class="help-tip" data-help="' + esc(__("set.overrides_help")) + '"></span></h3>' +
      '<p class="set-stat">' + __f("set.overrides_stat", {
        overridden: overridden.length, shadowed: shadowed.length,
      }) + "</p>" +
      '<button type="button" class="button subtle set-wide" id="setShowOverridden">' +
        esc(__("set.show_overridden")) + "</button>" +
      '<button type="button" class="button danger set-wide" id="setResetAll">' +
        esc(__("set.reset_all")) + "</button>" +
      '<p class="set-hint">' + esc(__("set.reset_all_hint")) + "</p>" +
      "</div>";
  }

  /* ---------------------------------------------------------------- 渲染 */

  /* The server's sections arrive with `title`/`help` already; the meta tabs
     carry keys, so resolve them here and every consumer keeps working. */
  function tabs() {
    return state.data.sections.concat(META_TABS.map(function (tab) {
      return { id: tab.id, title: __(tab.titleKey), help: __(tab.helpKey) };
    }));
  }

  /* A tab is either a server section (bilingual fields) or a meta tab (already
     resolved above), so go through the same picker either way. */
  function tabTitle(tab) {
    return sectionTitle(tab);
  }

  function tabHelp(tab) {
    return sectionHelp(tab);
  }

  /** Title of whatever the main column is currently showing. */
  function currentTabTitle() {
    if (state.query) return __f("set.search_results", { query: state.query });
    var found = null;
    tabs().forEach(function (tab) {
      if (tab.id === state.tab) found = tab;
    });
    return found ? tabTitle(found) : __("set.fallback_title");
  }

  function renderTabs() {
    var html = tabs().map(function (tab) {
      var count = tab.keys ? countOverridden(tab) : 0;
      var active = tab.id === state.tab;
      // `.is-active` was the only marker, so which of the twelve sections you
      // were in was visible but not programmatically exposed. aria-current
      // rather than role="tab": these buttons have no arrow-key roving, and a
      // half-built tablist misleads more than plain buttons do.
      return '<button class="step' + (active ? " is-active" : "") + '" data-tab="' + esc(tab.id) + '"' +
        (active ? ' aria-current="true"' : "") + ' aria-controls="setBody">' +
        esc(tabTitle(tab)) +
        (count ? '<em class="set-tabcount">' + count + "</em>" : "") +
        '<span class="help-tip" data-help="' + esc(tabHelp(tab)) + '"></span></button>';
    }).join("");
    $("setTabs").innerHTML = html;
  }

  function countOverridden(tab) {
    var sources = state.data.sources || {};
    var total = 0;
    Object.keys(sources).forEach(function (path) {
      var head = path.split(".")[0];
      if (tab.keys.indexOf(head) >= 0) total += 1;
    });
    return total;
  }

  function render() {
    if (!state.data) return;
    renderTabs();

    var body;
    if (state.query) {
      body = renderSearch();
    } else if (state.tab === "__env") {
      body = renderEnv();
    } else if (state.tab === "__files") {
      body = renderFiles();
    } else {
      var section = null;
      state.data.sections.forEach(function (item) {
        if (item.id === state.tab) section = item;
      });
      body = section ? renderSection(section) : '<p class="set-hint">' + esc(__("set.unknown_section")) + "</p>";
    }
    // Name the panel. Without this the main column — 600-odd controls — had no
    // heading of its own: the page went h1 straight to the sidebar's h3, so a
    // screen reader had nothing to jump to and no way to tell which section's
    // settings it was reading.
    $("setBody").innerHTML = '<h2 class="set-section-title">' + esc(currentTabTitle()) + "</h2>" + body;
    $("setSide").innerHTML = renderSide();

    var sources = state.data.sources || {};
    $("setTopMeta").innerHTML =
      '<span class="set-chip">' + esc(__("set.chip_items")) +
        " <b>" + countLeaves(state.data.tree) + "</b></span>" +
      '<span class="set-chip">' + esc(__("set.chip_overridden")) +
        " <b>" + Object.keys(sources).length + "</b></span>";

    syncFooter();
    if (window.HelpTips) window.HelpTips.scan($("setBody").parentNode);
  }

  function countLeaves(node) {
    if (node && typeof node === "object" && !Array.isArray(node)) {
      var keys = Object.keys(node);
      if (!keys.length) return 1;
      return keys.reduce(function (sum, key) { return sum + countLeaves(node[key]); }, 0);
    }
    return 1;
  }

  function syncFooter() {
    var count = dirtyPaths().length;
    var bad = Object.keys(state.invalid).length;
    $("setSave").disabled = state.busy || !count || !!bad;
    $("setDiscard").disabled = state.busy || !count;
    $("setSave").textContent = count ? __f("set.save_n", { count: count }) : __("set.save");
  }

  /* ------------------------------------------------------------- 事件绑定 */

  function readControl(el) {
    var kind = el.getAttribute("data-kind");
    if (kind === "bool") return el.checked;
    if (kind === "number") {
      var num = Number(el.value);
      return isFinite(num) ? num : el.value;
    }
    if (kind === "json") return JSON.parse(el.value);
    return el.value;
  }

  function onFieldChange(event) {
    var el = event.target;
    var path = el.getAttribute && el.getAttribute("data-path");
    if (!path) return;
    var original = at(state.data.tree, path);
    var value;
    try {
      value = readControl(el);
      delete state.invalid[path];
    } catch (err) {
      state.invalid[path] = true;
      state.dirty[path] = el.value;
      el.closest(".set-field").classList.add("is-bad");
      $("setSide").innerHTML = renderSide();
      syncFooter();
      return;
    }
    // 改回原值就不算改动，免得「待保存」里堆一堆什么都没改的项。
    if (JSON.stringify(value) === JSON.stringify(original)) {
      delete state.dirty[path];
    } else {
      state.dirty[path] = value;
    }
    // 默认后端在页面上有两个控件（顶部的选择器和下面的 routing 树），它们绑同一个
    // 路径。不同步的话，面板会同时显示两个互相矛盾的「当前值」。
    var twins = document.querySelectorAll('[data-path="' + path + '"]');
    for (var i = 0; i < twins.length; i++) {
      if (twins[i] === el) continue;
      if (twins[i].type === "checkbox") twins[i].checked = el.checked;
      else twins[i].value = el.value;
      var twinField = twins[i].closest(".set-field");
      if (twinField) twinField.classList.toggle("is-dirty", has(state.dirty, path));
    }
    var field = el.closest(".set-field");
    if (field) {
      field.classList.toggle("is-dirty", has(state.dirty, path));
      field.classList.remove("is-bad");
    }
    $("setSide").innerHTML = renderSide();
    if (window.HelpTips) window.HelpTips.scan($("setSide"));
    syncFooter();
  }

  /** 把扁平的 dirty 路径还原成嵌套补丁。 */
  function buildPatch() {
    var patch = {};
    dirtyPaths().forEach(function (path) {
      var parts = path.split(".");
      var node = patch;
      for (var i = 0; i < parts.length - 1; i++) {
        if (typeof node[parts[i]] !== "object" || node[parts[i]] === null) node[parts[i]] = {};
        node = node[parts[i]];
      }
      node[parts[parts.length - 1]] = state.dirty[path];
    });
    return patch;
  }

  function absorb(payload) {
    state.data = payload;
    state.dirty = {};
    state.invalid = {};
    render();
  }

  function save() {
    if (Object.keys(state.invalid).length) {
      status(__("set.fix_json_first"), "bad");
      return;
    }
    var count = dirtyPaths().length;
    api("POST", "/api/settings/save", { config: buildPatch() }).then(function (payload) {
      var notes = [];
      if (payload.saved) notes.push(__f("set.saved_n", { count: (payload.applied || []).length }));
      else notes.push(__("set.saved_none"));
      if (payload.dropped && payload.dropped.length) {
        notes.push(__f("set.dropped_n", { count: payload.dropped.length }));
      }
      if (payload.blocked && payload.blocked.length) {
        notes.push(__f("set.blocked_n", { names: payload.blocked.join("、") }));
      }
      // 写进去了、却仍然不是生效值的那些项：被后面的覆盖层盖住了。这正是本面板
      // 想消除的那种「保存成功但什么都没变」，所以要在保存后当场说出来，不能只
      // 指望用户去 hover。
      var shadowed = (payload.applied || []).filter(function (path) {
        var source = (payload.sources || {})[path];
        return source && source !== "dashboard";
      });
      absorb(payload);
      status(notes.join("；") + __("set.applies_next_run"), payload.saved ? "ok" : "warn");
      if (shadowed.length) {
        status(__f("set.saved_but_shadowed", {
          count: shadowed.length, paths: shadowed.join("、"),
        }), "warn");
      }
      if (!payload.saved && count) {
        status(__f("set.none_written", { count: count, paths: (payload.dropped || []).join("、") }), "bad");
      }
    }).catch(function () {});
  }

  function revert(path) {
    api("POST", "/api/settings/reset", { paths: [path] }).then(function (payload) {
      absorb(payload);
      status(payload.removed.length
        ? __f("set.restored_defaults", { paths: payload.removed.join("、") })
        : __("set.not_overridden"), "ok");
    }).catch(function () {});
  }

  function resetAll() {
    if (!window.confirm(__("set.confirm_reset_all"))) return;
    api("POST", "/api/settings/reset-all", {}).then(function (payload) {
      absorb(payload);
      status(__f("set.cleared_n", { count: payload.removed.length }), "ok");
    }).catch(function () {});
  }

  /* -------------------------------------------------------- 语言模型的动作 */

  /** 测试结果就地更新：整页重绘会把用户正在填的表单和滚动位置一起清掉。 */
  function paintProbe(key) {
    var slot = key === "__draft" ? $("llmDraftResult") : document.querySelector('[data-result="' + key + '"]');
    if (slot) slot.innerHTML = probeHtml(state.probes[key]);
  }

  function probe(key, payload) {
    var label = key === "__draft"
      ? __("set.probe_draft_label")
      : __f("set.probe_provider_label", { name: key });
    state.probes[key] = { busy: true };
    paintProbe(key);
    api("POST", "/api/settings/llm/test", payload).then(function (result) {
      state.probes[key] = result;
      paintProbe(key);
      status(result.ok
        ? __f("set.probe_reached", { label: label, ms: result.latency_ms })
        : __f("set.probe_unreachable", { label: label }),
        result.ok ? "ok" : "bad");
    }).catch(function (err) {
      state.probes[key] = { ok: false, error: String((err && err.message) || err) };
      paintProbe(key);
    });
  }

  /** 表单 -> provider 配置块。地址的键名随类型变，所以在这里而不是在后端拍板。 */
  function draftPayload() {
    var draft = state.draft;
    var spec = PROVIDER_TYPES[draft.type] || PROVIDER_TYPES.ollama;
    var config = { type: draft.type, model: draft.model.trim() };
    config[draft.type === "ollama" ? "url" : "base_url"] = draft.endpoint.trim() || spec.endpoint;
    if (spec.needsKey && draft.api_key_env.trim()) config.api_key_env = draft.api_key_env.trim();
    if (draft.timeout.trim()) config.timeout = draft.timeout.trim();
    return { name: draft.name.trim(), config: config };
  }

  function addProvider() {
    var payload = draftPayload();
    api("POST", "/api/settings/llm/provider", payload).then(function (result) {
      state.draft = { type: state.draft.type, name: "", endpoint: "", model: "", api_key_env: "", timeout: "" };
      delete state.probes.__draft;
      absorb(result);
      status(__f("set.provider_added", { name: result.name }), "ok");
    }).catch(function () {});
  }

  function dropProvider(name) {
    if (!window.confirm(__f("set.confirm_drop_provider", { name: name }))) return;
    // 复用通用的 reset：删一个覆盖项本来就是「把这个路径从覆盖文件里剪掉」。
    api("POST", "/api/settings/reset", { paths: ["llm.providers." + name] }).then(function (result) {
      delete state.probes[name];
      absorb(result);
      status(result.removed.length
        ? __f("set.provider_dropped", { name: name })
        : __("set.provider_not_overridden"),
        result.removed.length ? "ok" : "warn");
    }).catch(function () {});
  }

  function load() {
    status(__("set.loading"));
    api("GET", "/api/settings/overview").then(function (payload) {
      if (!state.tab) state.tab = (payload.sections[0] || {}).id || "__env";
      absorb(payload);
      status("");
    }).catch(function () {});
  }

  /* ------------------------------------------------------------------ wire */

  var body = $("setBody");
  body.addEventListener("change", onFieldChange);
  body.addEventListener("input", function (event) {
    // 文本/数字/JSON 边打边记；勾选框由 change 处理，避免重复。
    var kind = event.target.getAttribute && event.target.getAttribute("data-kind");
    if (kind && kind !== "bool") onFieldChange(event);
  });
  // 新增表单的输入只记进 state.draft，不触发重绘 —— 边打字边重绘会把光标弹走。
  body.addEventListener("input", function (event) {
    var key = event.target.getAttribute && event.target.getAttribute("data-draft");
    if (key && key !== "type") state.draft[key] = event.target.value;
  });
  body.addEventListener("change", function (event) {
    if (!event.target.getAttribute) return;
    if (event.target.getAttribute("data-draft") !== "type") return;
    // 换类型要换字段（本地后端没有密钥环境变量）和占位提示，只重画这一张表单。
    state.draft.type = event.target.value;
    var box = $("llmAddBox");
    if (box) {
      box.innerHTML = renderAddForm();
      if (window.HelpTips) window.HelpTips.scan(box);
    }
  });

  body.addEventListener("click", function (event) {
    var test = event.target.closest("[data-test-provider]");
    if (test) {
      probe(test.getAttribute("data-test-provider"), { name: test.getAttribute("data-test-provider") });
      return;
    }
    var drop = event.target.closest("[data-drop-provider]");
    if (drop) {
      dropProvider(drop.getAttribute("data-drop-provider"));
      return;
    }
    if (event.target.id === "llmDraftTest") {
      probe("__draft", draftPayload());
      return;
    }
    if (event.target.id === "llmDraftSave") {
      addProvider();
      return;
    }
    var target = event.target.closest("[data-revert]");
    if (!target) return;
    event.preventDefault();
    revert(target.getAttribute("data-revert"));
  });

  $("setSide").addEventListener("click", function (event) {
    var undo = event.target.closest("[data-undo]");
    if (undo) {
      var path = undo.getAttribute("data-undo");
      delete state.dirty[path];
      delete state.invalid[path];
      render();
      return;
    }
    if (event.target.id === "setResetAll") resetAll();
    if (event.target.id === "setShowOverridden") {
      state.onlyOverridden = true;
      $("setOnlyOverridden").checked = true;
      render();
    }
  });

  $("setTabs").addEventListener("click", function (event) {
    var btn = event.target.closest(".step");
    if (!btn) return;
    state.tab = btn.getAttribute("data-tab");
    render();
  });

  var searchTimer = null;
  $("setSearch").addEventListener("input", function (event) {
    var value = event.target.value.trim().toLowerCase();
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(function () {
      state.query = value;
      render();
    }, 140);
  });

  $("setOnlyOverridden").addEventListener("change", function (event) {
    state.onlyOverridden = event.target.checked;
    render();
  });

  $("setSave").addEventListener("click", save);
  $("setReload").addEventListener("click", load);
  $("setDiscard").addEventListener("click", function () {
    state.dirty = {};
    state.invalid = {};
    render();
    status(__("set.discarded"));
  });

  /* Redraw on a language switch. render() rebuilds the tab strip, the main
     column and the sidebar, and syncFooter() relabels the save button; the
     600-odd field labels and help texts come from the server with the section
     payload, so they are not this file's to translate. Pending edits live in
     state.dirty and survive the redraw. */
  document.addEventListener("locale-changed", function () {
    if (!state.data) return;
    render();
  });

  load();
})();
