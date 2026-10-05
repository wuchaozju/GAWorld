"use strict";

// 搜索高亮的纯函数测试。docs.js 里的高亮调用全部走这里，所以这里的失败
// 一定会反映到浏览器侧。docs.js 的 DOM 遍历（clearMarks / highlightArticle）
// 是浏览器侧的：要走 jsdom 才能测，但这次范围仅限单测纯函数，先盯 highlight
// 的核心合同。

const test = require("node:test");
const assert = require("node:assert/strict");
const hl = require("./highlight.js");


test("escapeHtml 转义全部 5 个特殊字符", () => {
  // 输入: <a href="x">'&'</a>
  // 期望 (5 个全转义): <a href="x">&#39;&&#39;</a>
  const input = "<a href=\u0022x\u0022>\u0027&\u0027</a>";
  const expected = "&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;";
  assert.equal(hl.escapeHtml(input), expected);
});


test("escapeHtml 非字符串原样处理后转义", () => {
  assert.equal(hl.escapeHtml(42), "42");
  assert.equal(hl.escapeHtml(null), "null");
});


test("tokensOf 把 query 按空白拆成小写数组", () => {
  assert.deepEqual(hl.tokensOf("  Fast  Forward "), ["fast", "forward"]);
  assert.deepEqual(hl.tokensOf(""), []);
  assert.deepEqual(hl.tokensOf(null), []);
  // 中文不分大小写，但 ASCII 走 lowerCase
  assert.deepEqual(hl.tokensOf("插件 PLUGIN"), ["插件", "plugin"]);
});


test("highlight 在 needle 命中处插入 <mark>", () => {
  const out = hl.highlight("Fast-forward 模式", "fast");
  assert.equal(out, "<mark class=\"doc-mark\">Fast</mark>-forward 模式");
});


test("highlight 多 token 任意一个命中就标黄", () => {
  const out = hl.highlight("插件和 ollama 都能跑", "ollama 插件");
  // 两个 token 各命中一次
  assert.match(out, /<mark class="doc-mark">插件<\/mark>/);
  assert.match(out, /<mark class="doc-mark">ollama<\/mark>/);
});


test("highlight 大小写不敏感", () => {
  assert.equal(hl.highlight("OpenAI 也能用", "openai"),
    "<mark class=\"doc-mark\">OpenAI</mark> 也能用");
});


test("highlight needle 含正则元字符时按字面量匹配", () => {
  // "(a|b)" 不应该被解读为捕获组
  const text = "搜索 (a|b) 这个示例";
  const out = hl.highlight(text, "(a|b)");
  assert.match(out, /<mark class="doc-mark">\(a\|b\)<\/mark>/);
});


test("highlight 空 needle / 过短 needle 返回原文本", () => {
  assert.equal(hl.highlight("hello", ""), "hello");
  assert.equal(hl.highlight("hello", "   "), "hello");
  assert.equal(hl.highlight("hello", "h", { minLen: 2 }), "hello");
});


test("highlight 转义 needle 与正文里的特殊字符", () => {
  // 正文里的 < 和 & 应该先被转义，否则会和 <mark> 一起被浏览器当成标签
  assert.equal(
    hl.highlight("脚本 <script>alert(1)</script>", "脚本"),
    "<mark class=\"doc-mark\">脚本</mark> &lt;script&gt;alert(1)&lt;/script&gt;",
  );
});


test("highlight 支持自定义 wrapTag / wrapClass", () => {
  const out = hl.highlight("abc 123", "abc", { wrapTag: "span", wrapClass: "hit" });
  assert.equal(out, "<span class=\"hit\">abc</span> 123");
});


test("snippetOf 找出第一个含任一 token 的非空行，截断到 90 字符", () => {
  const text = "第一行无\n第二行包含 fast forward\n第三行无";
  assert.equal(hl.snippetOf(text, "fast"), "第二行包含 fast forward");
});


test("snippetOf 长行末尾加省略号", () => {
  const line = "x".repeat(120);
  const out = hl.snippetOf("无\n" + line, "x");
  assert.equal(out.length, 91); // 90 chars + "…"
  assert.ok(out.endsWith("…"));
});


test("snippetOf 无命中返回空串", () => {
  assert.equal(hl.snippetOf("无任何关键词", "ollama"), "");
  assert.equal(hl.snippetOf("有 fast", ""), "");
});
