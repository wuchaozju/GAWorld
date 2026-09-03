// 文档面板：把仓库里的 Markdown 文档直接读出来渲染。
//
// 文档就是 docs/ 下那些 .md 文件本身 —— dashboard_server 已经把仓库根目录当静态
// 目录服务了，所以这里直接 fetch 原文，不需要新的 API，也不会出现「网页上的教程
// 和仓库里的教程各说各话」。
//
// 清单是手写的：docs/ 里混着重构计划、审计记录这类只对维护者有意义的文件，
// 全列出来只会淹没真正要看的教程。新增文档时在 DOCS 里加一行即可。
(function () {
  "use strict";

  var DOCS = [
    {
      id: "tutorial",
      path: "/docs/TUTORIAL.md",
      title: "用户教程",
      en: "Tutorial",
      group: "快速上手",
      summary: "10 分钟跑通第一次仿真：装依赖、配 LLM、run、看输出在哪。",
      tags: ["quickstart", "run", "ollama", "openai", "第一次"],
    },
    {
      id: "tutorial-v2",
      path: "/docs/TUTORIAL.v2.md",
      title: "教程 v2（完整手册）",
      en: "Tutorial v2",
      group: "快速上手",
      summary: "最全的一本：长时段快进与月/年尺度长跑、对照实验、群体模拟、外部系统、分析导出全都在里面。",
      tags: ["手册", "快进", "fast-forward", "月", "年", "长跑", "对照", "analytics"],
    },
    {
      id: "readme",
      path: "/README.zh-CN.md",
      title: "项目简介",
      en: "README",
      group: "快速上手",
      summary: "GAWorld 是什么、能做什么实验、目录怎么组织。",
      tags: ["readme", "overview", "简介"],
    },
    {
      id: "features",
      path: "/docs/FEATURES.md",
      title: "功能特性总览",
      en: "Features",
      group: "功能与玩法",
      summary: "记忆、社交、经济、干预、地图……每个子系统一条，先扫这份再决定看哪篇。",
      tags: ["features", "功能", "总览"],
    },
    {
      id: "map-modes",
      path: "/docs/MAP_MODES.md",
      title: "地图模式",
      en: "Map Modes",
      group: "功能与玩法",
      summary: "虚拟地图和真实城市地图的区别、各自需要什么数据。",
      tags: ["map", "citymap", "地图", "虚拟", "真实"],
    },
    {
      id: "skill-system",
      path: "/docs/SKILL_SYSTEM.md",
      title: "Skill 系统",
      en: "Skill System",
      group: "功能与玩法",
      summary: "智能体的技能怎么定义、怎么练、怎么影响行为。",
      tags: ["skill", "技能", "成长"],
    },
    {
      id: "real-work",
      path: "/docs/REAL_WORK_USAGE.md",
      title: "真实工作执行",
      en: "Real Work",
      group: "功能与玩法",
      summary: "让智能体真的去执行工作任务（而不只是描述），怎么开、怎么看结果。",
      tags: ["real work", "工作", "执行"],
    },
    {
      id: "group-simulation",
      path: "/docs/GROUP_SIMULATION_TUTORIAL.md",
      title: "群体模拟教程",
      en: "Group Simulation",
      group: "专题教程",
      summary: "从个体扩到人群：人口构成、群体智能体、规模化跑法。",
      tags: ["group", "population", "人口", "群体"],
    },
    {
      id: "social-network",
      path: "/docs/SOCIAL_NETWORK_TUTORIAL.md",
      title: "社交网络教程",
      en: "Social Network",
      group: "专题教程",
      summary: "关系怎么建立和演化、社交网络图怎么导出和解读。",
      tags: ["social", "network", "关系", "社交"],
    },
    {
      id: "external-systems",
      path: "/docs/EXTERNAL_SYSTEMS_TUTORIAL.md",
      title: "外部系统教程",
      en: "External Systems",
      group: "专题教程",
      summary: "接入外部平台/服务，让仿真和外面的系统互相影响。",
      tags: ["external", "外部系统", "接入"],
    },
    {
      id: "parallel-worlds",
      path: "/docs/PARALLEL_WORLDS_TUTORIAL.md",
      title: "平行世界教程",
      en: "Parallel Worlds",
      group: "专题教程",
      summary: "同一批人换一件事：多分支反事实实验怎么设计、怎么读分叉图、为什么先跑安慰剂。",
      tags: ["parallel", "counterfactual", "平行世界", "对照", "反事实"],
    },
    {
      id: "openclaw",
      path: "/docs/OPENCLAW_INTEGRATION.md",
      title: "OpenClaw 接入",
      en: "OpenClaw",
      group: "专题教程",
      summary: "把 OpenClaw Agent 接进 GAWorld 社会模拟的使用说明。",
      tags: ["openclaw", "integration", "接入"],
    },
    {
      id: "fos",
      path: "/docs/FOS_Integration.md",
      title: "FOS 集成指南",
      en: "FOS Integration",
      group: "专题教程",
      summary: "GAWorld 与 FOS 的数据交换与导出流程（英文）。",
      tags: ["fos", "export", "integration"],
    },
    {
      id: "plugin-authoring",
      path: "/docs/PLUGIN_AUTHORING.md",
      title: "插件作者指南",
      en: "Plugin Authoring",
      group: "开发与扩展",
      summary: "写一个插件挂进微内核：钩子、注册、生命周期和最小示例。",
      tags: ["plugin", "插件", "kernel", "扩展"],
    },
    {
      id: "project-structure",
      path: "/docs/PROJECT_STRUCTURE.md",
      title: "项目结构",
      en: "Project Structure",
      group: "开发与扩展",
      summary: "各个包各管什么、代码该往哪放。",
      tags: ["structure", "目录", "架构"],
    },
    {
      id: "contributing",
      path: "/AGENTS.md",
      title: "仓库约定",
      en: "Repository Guidelines",
      group: "开发与扩展",
      summary: "目录组织、命名、测试和提交约定 —— 动手改代码前先看这份。",
      tags: ["contributing", "约定", "测试", "commit"],
    },
    {
      id: "changelog",
      path: "/CHANGELOG.md",
      title: "更新日志",
      en: "Changelog",
      group: "开发与扩展",
      summary: "版本之间改了什么。",
      tags: ["changelog", "版本", "更新"],
    },
    {
      id: "group-agent-design",
      path: "/docs/GROUP_AGENT_DESIGN.md",
      title: "Group Agent 设计",
      en: "Group Agent Design",
      group: "设计文档",
      summary: "群体智能体的建模思路与分阶段实施计划。",
      tags: ["design", "group", "设计"],
    },
    {
      id: "family-design",
      path: "/docs/FAMILY_DESIGN.md",
      title: "家庭系统设计",
      en: "Family / Household Design",
      group: "设计文档",
      summary: "婚姻状态怎么抽样、家庭怎么影响日程与账目、以及为什么这样接钩子。",
      tags: ["design", "family", "household", "家庭", "设计"],
    },
    {
      id: "social-network-design",
      path: "/docs/SOCIAL_NETWORK_DESIGN.md",
      title: "社交网络设计",
      en: "Social Network Design",
      group: "设计文档",
      summary: "关系模型、影响传播和存储结构的实施设计。",
      tags: ["design", "social", "设计"],
    },
    {
      id: "real-work-design",
      path: "/docs/REAL_WORK_DESIGN.md",
      title: "真实工作执行设计",
      en: "Real Work Design",
      group: "设计文档",
      summary: "工作任务如何被分解、执行和评估的实施设计。",
      tags: ["design", "real work", "设计"],
    },
    {
      id: "big-five-design",
      path: "/docs/proposals/2026-08-20-big-five-personality.md",
      title: "大五人格设计",
      en: "Big Five Personality Design",
      group: "设计文档",
      summary: "五维人格怎么从性格段落离线标定并冻结、规则/提示词/日记三条通道各改变什么、以及为什么运行期不漂移。",
      tags: ["design", "personality", "big five", "ocean", "人格", "设计"],
    },
  ];

  var GROUPS = ["快速上手", "功能与玩法", "专题教程", "开发与扩展", "设计文档"];

  var byId = {};
  var byPath = {};
  DOCS.forEach(function (doc) {
    byId[doc.id] = doc;
    byPath[doc.path] = doc;
  });

  var sideEl = document.getElementById("docSide");
  var articleEl = document.getElementById("docArticle");
  var tocEl = document.getElementById("docToc");
  var metaEl = document.getElementById("docTopMeta");
  var searchEl = document.getElementById("docSearch");
  var hintEl = document.getElementById("docSearchHint");

  var cache = {};        // id -> Markdown 原文
  var current = null;    // 当前文档
  var headings = [];     // 当前文档的大纲
  var query = "";
  var fullTextReady = false;
  var fullTextLoading = false;

  // ------------------------------------------------------------ 链接改写

  function joinPath(basePath, href) {
    if (href.charAt(0) === "/") return href;
    var parts = basePath.split("/");
    parts.pop();
    href.split("/").forEach(function (segment) {
      if (!segment || segment === ".") return;
      if (segment === "..") parts.pop();
      else parts.push(segment);
    });
    return parts.join("/");
  }

  // 文档之间互相引用得留在面板里；指向仓库其它文件的相对链接则交给静态服务，
  // 这样 `gaworld/kernel/bus.py` 这种引用点开就能看到源码。
  function makeResolver(doc) {
    return function (href) {
      if (!href) return href;
      if (/^(https?:|mailto:)/i.test(href)) return href;
      if (href.charAt(0) === "#") return "#" + doc.id + "/" + href.slice(1);

      var hash = "";
      var hashAt = href.indexOf("#");
      if (hashAt >= 0) {
        hash = href.slice(hashAt + 1);
        href = href.slice(0, hashAt);
      }
      var abs = joinPath(doc.path, href);
      var target = byPath[abs];
      if (target) return "#" + target.id + (hash ? "/" + hash : "");
      return abs + (hash ? "#" + hash : "");
    };
  }

  // ------------------------------------------------------------ 搜索

  function snippetOf(text, needle) {
    var lines = text.split("\n");
    for (var i = 0; i < lines.length; i++) {
      if (lines[i].toLowerCase().indexOf(needle) >= 0) {
        var line = lines[i].trim();
        return line.length > 90 ? line.slice(0, 90) + "…" : line;
      }
    }
    return "";
  }

  function matchDoc(doc, needle) {
    var haystack = [doc.title, doc.en, doc.summary, doc.group, doc.tags.join(" ")]
      .join(" ")
      .toLowerCase();
    if (haystack.indexOf(needle) >= 0) return { doc: doc, snippet: "" };
    var text = cache[doc.id];
    if (text && text.toLowerCase().indexOf(needle) >= 0) {
      return { doc: doc, snippet: snippetOf(text, needle) };
    }
    return null;
  }

  function visibleDocs() {
    if (!query) return DOCS.map(function (doc) { return { doc: doc, snippet: "" }; });
    var needle = query.toLowerCase();
    var hits = [];
    DOCS.forEach(function (doc) {
      var hit = matchDoc(doc, needle);
      if (hit) hits.push(hit);
    });
    return hits;
  }

  // 正文搜索需要全部原文，但开面板时没必要都拉下来 —— 第一次真正搜索时再补齐。
  function ensureFullText() {
    if (fullTextReady || fullTextLoading) return;
    fullTextLoading = true;
    Promise.all(DOCS.map(function (doc) {
      return fetchDoc(doc).catch(function () { return ""; });
    })).then(function () {
      fullTextReady = true;
      fullTextLoading = false;
      renderSide();
    });
  }

  // ------------------------------------------------------------ 读取

  function fetchDoc(doc) {
    if (cache[doc.id] != null) return Promise.resolve(cache[doc.id]);
    return fetch(doc.path).then(function (response) {
      if (!response.ok) throw new Error(doc.path + " → HTTP " + response.status);
      return response.text();
    }).then(function (text) {
      cache[doc.id] = text;
      return text;
    });
  }

  // ------------------------------------------------------------ 渲染

  function renderMeta() {
    metaEl.innerHTML = "";
    var chip = document.createElement("span");
    chip.className = "doc-chip";
    chip.innerHTML = "共 <b>" + DOCS.length + "</b> 篇文档";
    metaEl.appendChild(chip);
    var source = document.createElement("span");
    source.className = "doc-chip";
    source.textContent = "直读仓库 docs/";
    metaEl.appendChild(source);
  }

  function renderSide() {
    var hits = visibleDocs();
    var shown = {};
    hits.forEach(function (hit) { shown[hit.doc.id] = hit.snippet; });

    sideEl.innerHTML = "";
    GROUPS.forEach(function (group) {
      var docs = DOCS.filter(function (doc) {
        return doc.group === group && Object.prototype.hasOwnProperty.call(shown, doc.id);
      });
      if (!docs.length) return;

      var section = document.createElement("div");
      section.className = "doc-group";
      var title = document.createElement("h2");
      title.textContent = group;
      section.appendChild(title);

      docs.forEach(function (doc) {
        var item = document.createElement("a");
        item.className = "doc-item" + (current && current.id === doc.id ? " is-active" : "");
        item.href = "#" + doc.id;
        item.innerHTML = "<strong>" + doc.title + "</strong><em>" + doc.en + "</em>";
        var note = document.createElement("span");
        note.className = "doc-item-note";
        note.textContent = shown[doc.id] || doc.summary;
        item.appendChild(note);
        section.appendChild(item);
      });
      sideEl.appendChild(section);
    });

    if (!hits.length) {
      var empty = document.createElement("p");
      empty.className = "doc-empty";
      empty.textContent = fullTextReady ? "没有匹配的文档。" : "正在搜索正文…";
      sideEl.appendChild(empty);
    }

    if (!query) {
      hintEl.textContent = "";
    } else if (!fullTextReady) {
      hintEl.textContent = "正在载入正文…";
    } else {
      hintEl.textContent = hits.length + " 篇匹配（含正文）";
    }
  }

  function renderToc() {
    tocEl.innerHTML = "";
    var items = headings.filter(function (item) {
      return item.level >= 2 && item.level <= 3;
    });
    if (!items.length) return;

    var title = document.createElement("h2");
    title.textContent = "本页大纲";
    tocEl.appendChild(title);
    items.forEach(function (item) {
      var link = document.createElement("a");
      link.className = "doc-tocitem level-" + item.level;
      link.href = "#" + current.id + "/" + item.slug;
      link.textContent = item.text;
      link.dataset.slug = item.slug;
      tocEl.appendChild(link);
    });
  }

  function markTocActive() {
    var links = tocEl.querySelectorAll(".doc-tocitem");
    if (!links.length) return;
    var activeSlug = "";
    for (var i = 0; i < headings.length; i++) {
      var node = document.getElementById(headings[i].slug);
      if (node && node.getBoundingClientRect().top <= 90) activeSlug = headings[i].slug;
    }
    Array.prototype.forEach.call(links, function (link) {
      link.classList.toggle("is-active", link.dataset.slug === activeSlug);
    });
  }

  function scrollToSlug(slug) {
    if (!slug) {
      window.scrollTo(0, 0);
      return;
    }
    var node = document.getElementById(slug);
    if (node) node.scrollIntoView({ block: "start" });
    markTocActive();
  }

  function renderDoc(doc, slug) {
    current = doc;
    document.title = "GAWorld 文档 · " + doc.title;
    articleEl.innerHTML = '<p class="doc-loading">正在载入 ' + doc.path + " …</p>";
    renderSide();

    fetchDoc(doc).then(function (text) {
      if (current !== doc) return; // 用户已经切走了
      var result = window.GAWorldMarkdown.render(text, { resolveLink: makeResolver(doc) });
      headings = result.headings;
      articleEl.innerHTML =
        '<header class="doc-head">'
        + '<p class="doc-kicker">' + doc.group + " · " + doc.en + "</p>"
        + "<h1>" + doc.title + "</h1>"
        + '<p class="doc-source">源文件 <a href="' + doc.path + '" target="_blank" rel="noopener">'
        + doc.path + "</a></p>"
        + "</header>"
        + '<div class="doc-body">' + result.html + "</div>";
      renderToc();
      scrollToSlug(slug);
    }).catch(function (error) {
      if (current !== doc) return;
      headings = [];
      renderToc();
      articleEl.innerHTML =
        '<p class="doc-error">读不到 <code>' + doc.path + "</code>：" + error.message
        + "<br />文档是直接从仓库读的，确认这个文件还在。</p>";
    });
  }

  // ------------------------------------------------------------ 路由

  function route() {
    var raw = (location.hash || "").replace(/^#/, "");
    // 中文锚点在 location.hash 里是百分号编码的，不解码就对不上标题的 id。
    try {
      raw = decodeURIComponent(raw);
    } catch (error) {
      /* 非法转义序列：按原样用 */
    }
    var slash = raw.indexOf("/");
    var id = slash >= 0 ? raw.slice(0, slash) : raw;
    var slug = slash >= 0 ? raw.slice(slash + 1) : "";
    var doc = byId[id] || DOCS[0];

    if (current && current.id === doc.id) {
      scrollToSlug(slug); // 同一篇里跳锚点，不重新渲染
      return;
    }
    renderDoc(doc, slug);
  }

  searchEl.addEventListener("input", function () {
    query = searchEl.value.trim();
    if (query.length >= 2) ensureFullText();
    renderSide();
  });

  window.addEventListener("hashchange", route);
  window.addEventListener("scroll", markTocActive, { passive: true });

  renderMeta();
  route();
}());
