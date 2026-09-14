// 文档面板用的 Markdown 渲染器。
//
// 仓库里的文档是给人看的 Markdown，不是给构建工具用的：这里不引第三方库，
// 也不加构建步骤（和 collaboration-core.js 一样，浏览器和 node:test 都能用）。
// 覆盖 docs/ 下实际用到的语法：标题、围栏代码块、有序/无序嵌套列表、表格、
// 引用、分隔线、行内代码/粗体/斜体/链接/图片。
//
// 两个刻意的取舍：
// * 斜体只认 `*x*`，不认 `_x_` —— 文档里满是 `sim_days`、`agent_id` 这种下划线
//   标识符，认了 `_` 会把它们吃成斜体。
// * 段落内的换行渲染成 <br>：中文文档常按语义手动断行，按 CommonMark 折成空格
//   会把断行的意图丢掉（而且中文之间会多出一个可见的空格）。
(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.GAWorldMarkdown = api;
  }
}(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  const LIST_RE = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
  const FENCE_RE = /^\s*(`{3,}|~{3,})\s*([^\s`]*)/;
  const HEADING_RE = /^(#{1,6})\s+(.*?)\s*#*\s*$/;
  const HR_RE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;
  const QUOTE_RE = /^\s*>/;

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // 行内标记去掉后的纯文本 —— 标题的锚点和大纲都用它。
  function plainText(text) {
    return String(text)
      .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/[`*~]/g, "")
      .trim();
  }

  // GitHub 的锚点规则：小写、去标点、空格换连字符。文档之间的
  // `./TUTORIAL.v2.md#31-长时段快进fast-forward跑-10--60--600-天`
  // 这种链接就是按这个规则生成的，跟着它才点得动。
  function slugify(text) {
    return plainText(text)
      .toLowerCase()
      /* i18n-exempt-start: a character class, not a string */
      .replace(/[^\w一-鿿\- ]+/g, "")
      /* i18n-exempt-end */
      // 一个空格换一个连字符，不合并：GitHub 去掉标点后留下的空位也会各算一个，
      // `跑 10 / 60 天` 的锚点里就是连着两个连字符。
      .replace(/\s/g, "-");
  }

  function renderInline(text, options) {
    const codes = [];
    let out = String(text).replace(/`([^`]+)`/g, function (_match, code) {
      codes.push("<code>" + escapeHtml(code) + "</code>");
      return "\u0000" + (codes.length - 1) + "\u0000";
    });
    out = escapeHtml(out);

    const resolve = (options && options.resolveLink) || function (href) { return href; };

    out = out.replace(/!\[([^\]]*)\]\(([^)\s]+)[^)]*\)/g, function (_match, alt, href) {
      return '<img src="' + resolve(href) + '" alt="' + alt + '" loading="lazy" />';
    });
    out = out.replace(/\[([^\]]*)\]\(([^)\s]+)[^)]*\)/g, function (_match, label, href) {
      const target = resolve(href);
      const external = /^https?:/i.test(target);
      return '<a href="' + target + '"'
        + (external ? ' target="_blank" rel="noopener"' : "")
        + ">" + label + "</a>";
    });
    out = out.replace(
      /&lt;(https?:\/\/[^\s&]+)&gt;/g,
      '<a href="$1" target="_blank" rel="noopener">$1</a>',
    );

    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    out = out.replace(/~~([^~]+)~~/g, "<del>$1</del>");

    return out.replace(/\u0000(\d+)\u0000/g, function (_match, index) {
      return codes[Number(index)];
    });
  }

  function leadingSpaces(line) {
    return line.length - line.replace(/^\s*/, "").length;
  }

  function dedent(line, width) {
    const strip = Math.min(width, leadingSpaces(line));
    return line.slice(strip);
  }

  function isTableSeparator(line) {
    return line.indexOf("|") >= 0 && line.indexOf("-") >= 0 && /^[\s|:-]+$/.test(line);
  }

  function splitRow(line) {
    return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(function (cell) {
      return cell.trim();
    });
  }

  function alignOf(spec) {
    const left = spec.charAt(0) === ":";
    const right = spec.charAt(spec.length - 1) === ":";
    if (left && right) return "center";
    if (right) return "right";
    if (left) return "left";
    return "";
  }

  function isBlockStart(line) {
    return FENCE_RE.test(line)
      || HEADING_RE.test(line)
      || HR_RE.test(line)
      || QUOTE_RE.test(line)
      || LIST_RE.test(line);
  }

  function renderList(lines, start, out, ctx) {
    const first = LIST_RE.exec(lines[start]);
    const indent = first[1].length;
    const ordered = /\d/.test(first[2]);
    const items = [];
    let childIndent = indent + 2;
    let i = start;

    while (i < lines.length) {
      const line = lines[i];
      const marker = LIST_RE.exec(line);

      if (marker && marker[1].length === indent) {
        childIndent = marker[0].length - marker[3].length;
        items.push([marker[3]]);
        i += 1;
        continue;
      }
      if (!line.trim()) {
        // 空行只有在后面还接着本列表的内容时才留在列表里。
        let next = i;
        while (next < lines.length && !lines[next].trim()) next += 1;
        if (next >= lines.length) break;
        const nextMarker = LIST_RE.exec(lines[next]);
        const continues = (nextMarker && nextMarker[1].length >= indent)
          || leadingSpaces(lines[next]) >= childIndent;
        if (!continues) break;
        if (items.length) items[items.length - 1].push("");
        i = next;
        continue;
      }
      if (items.length && leadingSpaces(line) > indent) {
        items[items.length - 1].push(dedent(line, childIndent));
        i += 1;
        continue;
      }
      break;
    }

    const body = items.map(function (itemLines) {
      const inner = renderBlocks(itemLines, ctx);
      // 条目开头那段文字去掉 <p>，免得列表被段落间距撑开；条目里真的写了
      // 第二段时保持原样，那种情况本来就该按松散列表排。
      const onlyOne = inner.indexOf("<p>") === 0 && inner.indexOf("<p>", 3) === -1;
      const close = inner.indexOf("</p>");
      const text = onlyOne ? inner.slice(3, close) + inner.slice(close + 4) : inner;
      return "<li>" + text + "</li>";
    }).join("");

    out.push(ordered ? "<ol>" + body + "</ol>" : "<ul>" + body + "</ul>");
    return i;
  }

  function renderBlocks(lines, ctx) {
    const out = [];
    let i = 0;

    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) {
        i += 1;
        continue;
      }

      const fence = FENCE_RE.exec(line);
      if (fence) {
        const closing = new RegExp("^\\s*" + fence[1].charAt(0) + "{3,}\\s*$");
        const body = [];
        i += 1;
        while (i < lines.length && !closing.test(lines[i])) {
          body.push(lines[i]);
          i += 1;
        }
        i += 1; // 收尾的围栏
        const lang = fence[2] ? ' class="lang-' + escapeHtml(fence[2]) + '"' : "";
        out.push('<pre class="md-code"><code' + lang + ">" + escapeHtml(body.join("\n")) + "</code></pre>");
        continue;
      }

      const heading = HEADING_RE.exec(line);
      if (heading) {
        const level = heading[1].length;
        const slug = ctx.uniqueSlug(slugify(heading[2]));
        ctx.headings.push({ level: level, text: plainText(heading[2]), slug: slug });
        out.push(
          "<h" + level + ' id="' + slug + '">'
          + renderInline(heading[2], ctx.options)
          + "</h" + level + ">",
        );
        i += 1;
        continue;
      }

      if (HR_RE.test(line)) {
        out.push("<hr />");
        i += 1;
        continue;
      }

      if (QUOTE_RE.test(line)) {
        const body = [];
        while (i < lines.length && QUOTE_RE.test(lines[i])) {
          body.push(lines[i].replace(/^\s*>\s?/, ""));
          i += 1;
        }
        out.push("<blockquote>" + renderBlocks(body, ctx) + "</blockquote>");
        continue;
      }

      if (line.indexOf("|") >= 0 && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
        const header = splitRow(line);
        const aligns = splitRow(lines[i + 1]).map(alignOf);
        i += 2;
        const cell = function (tag, value, index) {
          const align = aligns[index] ? ' style="text-align:' + aligns[index] + '"' : "";
          return "<" + tag + align + ">" + renderInline(value, ctx.options) + "</" + tag + ">";
        };
        const rows = [];
        while (i < lines.length && lines[i].trim() && lines[i].indexOf("|") >= 0) {
          rows.push("<tr>" + splitRow(lines[i]).map(function (value, index) {
            return cell("td", value, index);
          }).join("") + "</tr>");
          i += 1;
        }
        out.push(
          '<div class="md-tablewrap"><table><thead><tr>'
          + header.map(function (value, index) { return cell("th", value, index); }).join("")
          + "</tr></thead><tbody>" + rows.join("") + "</tbody></table></div>",
        );
        continue;
      }

      if (LIST_RE.test(line)) {
        i = renderList(lines, i, out, ctx);
        continue;
      }

      const para = [];
      while (i < lines.length && lines[i].trim() && !(para.length && isBlockStart(lines[i]))) {
        para.push(lines[i].trim());
        i += 1;
      }
      out.push("<p>" + para.map(function (text) {
        return renderInline(text, ctx.options);
      }).join("<br />") + "</p>");
    }

    return out.join("\n");
  }

  // render(text, {resolveLink}) -> {html, headings}
  // headings 是大纲用的 [{level, text, slug}]，顺序即文档顺序。
  function render(text, options) {
    const slugs = Object.create(null);
    const ctx = {
      headings: [],
      options: options || {},
      uniqueSlug: function (base) {
        const key = base || "section";
        const seen = slugs[key] || 0;
        slugs[key] = seen + 1;
        return seen ? key + "-" + seen : key;
      },
    };
    const lines = String(text).replace(/\r\n?/g, "\n").split("\n");
    return { html: renderBlocks(lines, ctx), headings: ctx.headings };
  }

  return { render: render, slugify: slugify, escapeHtml: escapeHtml, plainText: plainText };
}));
