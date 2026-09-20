"use strict";

// 渲染器的风险不在「能不能出 HTML」，而在几个会悄悄毁掉文档的地方：
// 锚点算错（文档间的 #小节 链接全部失效）、代码块里的尖括号没转义（吞掉后面
// 的正文）、下划线标识符被当成斜体（`sim_days` 变成 simdays）。这里盯的就是这些。

const test = require("node:test");
const assert = require("node:assert/strict");
const md = require("./docs-markdown.js");


test("标题按 GitHub 规则生成锚点，中文和数字都保留", () => {
  const out = md.render("### 3.1 长时段快进（Fast-forward）：跑 10 / 60 / 600 天");
  assert.deepEqual(out.headings, [{
    level: 3,
    text: "3.1 长时段快进（Fast-forward）：跑 10 / 60 / 600 天",
    slug: "31-长时段快进fast-forward跑-10--60--600-天",
  }]);
  assert.match(out.html, /^<h3 id="31-长时段快进fast-forward跑-10--60--600-天">/);
});


test("同名标题的锚点不重复", () => {
  const out = md.render("## 用法\n\n## 用法");
  assert.deepEqual(out.headings.map((h) => h.slug), ["用法", "用法-1"]);
});


test("代码块原样转义，不解析里面的 Markdown", () => {
  const out = md.render("```bash\npython sim.py --flag <value> & echo *x*\n```");
  assert.equal(
    out.html,
    '<pre class="md-code"><code class="lang-bash">'
    + "python sim.py --flag &lt;value&gt; &amp; echo *x*</code></pre>",
  );
});


test("行内代码里的星号和下划线不参与行内解析", () => {
  const out = md.render("把 `routing.default` 指向 `**not_bold**` 即可");
  assert.equal(
    out.html,
    "<p>把 <code>routing.default</code> 指向 <code>**not_bold**</code> 即可</p>",
  );
});


test("下划线标识符不会被当成斜体", () => {
  assert.equal(md.render("sim_days 和 agent_id 都是配置项").html,
    "<p>sim_days 和 agent_id 都是配置项</p>");
});


test("粗体、斜体和链接一起出现时各归各位", () => {
  const out = md.render("**重点**：见 [教程](./TUTORIAL.md) 与 *备注*");
  assert.equal(
    out.html,
    '<p><strong>重点</strong>：见 <a href="./TUTORIAL.md">教程</a> 与 <em>备注</em></p>',
  );
});


test("resolveLink 可以改写相对链接，外链自动新窗口打开", () => {
  const out = md.render("[A](./TUTORIAL.md) [B](https://example.com)", {
    resolveLink: (href) => (href === "./TUTORIAL.md" ? "#tutorial" : href),
  });
  assert.equal(
    out.html,
    '<p><a href="#tutorial">A</a> '
    + '<a href="https://example.com" target="_blank" rel="noopener">B</a></p>',
  );
});


test("HTML 会被转义，文档里的尖括号吃不掉后面的正文", () => {
  assert.equal(
    md.render('<img src=x onerror="alert(1)"> 后面还有正文').html,
    "<p>&lt;img src=x onerror=&quot;alert(1)&quot;&gt; 后面还有正文</p>",
  );
});


test("嵌套列表按缩进分层", () => {
  const out = md.render("- 一级\n  - 二级\n    - 三级\n- 另一个一级");
  assert.equal(
    out.html,
    "<ul><li>一级\n<ul><li>二级\n<ul><li>三级</li></ul></li></ul></li><li>另一个一级</li></ul>",
  );
});


test("有序列表条目里的代码块留在条目内", () => {
  const out = md.render("1. 先装依赖\n\n   ```bash\n   pip install -r requirements.txt\n   ```\n\n2. 再运行");
  assert.equal(
    out.html,
    "<ol><li>先装依赖\n"
    + '<pre class="md-code"><code class="lang-bash">pip install -r requirements.txt</code></pre></li>'
    + "<li>再运行</li></ol>",
  );
});


test("表格带对齐信息", () => {
  const out = md.render("| 配置 | 说明 |\n| --- | ---: |\n| `sim_days` | 天数 |");
  assert.equal(
    out.html,
    '<div class="md-tablewrap"><table><thead><tr><th>配置</th><th style="text-align:right">说明</th></tr></thead>'
    + '<tbody><tr><td><code>sim_days</code></td><td style="text-align:right">天数</td></tr></tbody></table></div>',
  );
});


test("引用块内部继续按 Markdown 解析", () => {
  assert.equal(
    md.render("> **注意**：先配好 LLM").html,
    "<blockquote><p><strong>注意</strong>：先配好 LLM</p></blockquote>",
  );
});


test("段落内的换行保留为 <br>，遇到块级元素结束段落", () => {
  const out = md.render("第一行\n第二行\n## 标题");
  assert.equal(out.html, "<p>第一行<br />第二行</p>\n" + '<h2 id="标题">标题</h2>');
});
