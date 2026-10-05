// 搜索高亮：把文本里的命中关键词包成 <mark class="doc-mark">，可以放在
// 浏览器（作为 <script> 直接挂到 globalThis）和 Node 测试（require）两侧用。
//
// 没有构建步骤，所以这里的导出方式是兼容两边的 UMD-ish：
//   - 浏览器：`globalThis.GAWorldHighlight = { highlight, tokensOf, escapeHtml, snippetOf }`
//   - Node：`module.exports = { ... }`
//
// 所有函数都是纯函数（输入文本 → 输出字符串 / 字符串数组），无副作用，便于单测。
(function (root) {
  "use strict";

  // ------------------------------------------------------------ escape

  // HTML 特殊字符转义。escape 是 highlight() 的前置：needle 和正文都先过这里，
  // 再用正则替换插入 <mark>，保证即便 needle 含 `<` `&` 也不会被当成标签吞掉。
  function escapeHtml(text) {
    return String(text)
.replace(/&/g, "&amp;")
.replace(/</g, "&lt;")
.replace(/>/g, "&gt;")
.replace(/"/g, "&quot;")
.replace(/'/g, '&#39;')
  }

  // ------------------------------------------------------------ tokens

  // 把 query 拆成多个 needle token（按空白分）。空 token 丢掉。返回小写数组，
  // 调用方拿到数组后可再按 minLen 过滤。
  //
  // 多 token 是 OR 关系：任何一个命中都标记 —— 现在的 docs UI 也只展示「命中
  // 多少篇」，不分匹配强度。
  function tokensOf(queryString) {
    if (!queryString) return [];
    return String(queryString)
      .toLowerCase()
      .split(/\s+/)
      .filter(function (t) { return t.length > 0; });
  }

  // ------------------------------------------------------------ mark

  // 给定一段文本和一个 needle，返回一段 HTML：所有出现的 token 被
  // `<wrapTag class="wrapClass">` 包起来；正文先 escapeHtml()，所以调用方
  // 直接把返回值赋给 innerHTML 即可，不用担心 XSS。
  //
  // 选项：
  //   wrapTag        - 包裹标签（默认 "mark"，便于屏幕阅读器和浏览器查找）
  //   wrapClass      - 包裹标签的 class（默认 "doc-mark"，与 CSS 对齐）
  //   minLen         - token 至少多长才算命中（默认 1；侧栏想放宽到 2 时用）
  //
  // token 中的正则元字符会被原样 escape，所以搜索 `(a|b)` 不会变成一个
  // 正则组 —— 我们只做字面子串匹配。
  function highlight(text, needle, opts) {
    opts = opts || {};
    var wrapTag = opts.wrapTag || "mark";
    var wrapClass = opts.wrapClass || "doc-mark";
    var minLen = opts.minLen != null ? opts.minLen : 1;
    var tokens = tokensOf(needle).filter(function (t) { return t.length >= minLen; });
    if (!tokens.length) return escapeHtml(text);

    var escaped = escapeHtml(text);
    var pattern = tokens
      .map(function (t) { return t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); })
      .join("|");
    var re = new RegExp("(" + pattern + ")", "gi");
    var replacement = "<" + wrapTag + ' class="' + wrapClass + '">$1</' + wrapTag + ">";
    return escaped.replace(re, replacement);
  }

  // ------------------------------------------------------------ snippet

  // 给一段长文本（通常是文档正文）和 needle，找出第一个包含任一 token 的行，
  // 修剪空白、截断到 ~90 字符，返回**纯文本**（不带 mark 包裹）。
  //
  // 这个函数只负责选行；外面会再调 highlight() 给命中片段加 mark。
  // 拆成两步是因为高亮函数必须先 escapeHtml，纯文本摘要直接复用更简单。
  function snippetOf(text, needle) {
    var tokens = tokensOf(needle);
    if (!tokens.length) return "";
    var lines = String(text).split("\n");
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (tokens.some(function (t) { return line.toLowerCase().indexOf(t) >= 0; })) {
        var trimmed = line.trim();
        return trimmed.length > 90 ? trimmed.slice(0, 90) + "…" : trimmed;
      }
    }
    return "";
  }

  var api = { escapeHtml: escapeHtml, tokensOf: tokensOf, highlight: highlight, snippetOf: snippetOf };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    root.GAWorldHighlight = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
