"""Build docs/FEATURE_MAP.html from the feature registry (docs/features.toml).

The page's ``<head>`` (styles) is kept as it is in the file; everything from
``<body>`` on is generated: the role jump bar, one Mermaid mind map per axis
and the collapsible three-level index. ``tests/test_feature_registry.py``
fails when the file is out of date.

Usage::

    python scripts/build_feature_map.py           # rewrite docs/FEATURE_MAP.html
    python scripts/build_feature_map.py --check   # exit 1 if it is out of date
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, "docs", "features.toml")
PAGE = os.path.join(ROOT, "docs", "FEATURE_MAP.html")
NUMERALS = {3: "三", 4: "四", 5: "五", 6: "六", 7: "七"}


def load_registry(path: str = REGISTRY) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def features(registry: dict):
    """(axis, group, feature) for every feature, in registry order."""
    for axis in registry["axis"]:
        for group in axis["group"]:
            for feature in group["feature"]:
                yield axis, group, feature


def mind_label(text: str) -> str:
    """A Mermaid mind-map node: brackets and separators would be read as shapes."""
    return re.sub(r"[\s（）()\[\]{}/：:，,·「」\"'`]+", "_", str(text)).strip("_")


def entry_html(entry: str) -> str:
    parts = str(entry or "").split("`")
    return "".join(f"<code>{html.escape(p)}</code>" if i % 2 else html.escape(p) for i, p in enumerate(parts))


def render_body(registry: dict) -> str:
    axes = registry["axis"]
    n_groups = sum(len(a["group"]) for a in axes)
    n_features = sum(1 for _ in features(registry))
    numeral = NUMERALS.get(len(axes), str(len(axes)))
    out = [
        "<body>",
        "",
        "<h1>GAWorld 功能地图</h1>",
        '<p class="meta">',
        f'  按"使用者 × 使用场景"组织的三级功能全景：{len(axes)} 个主轴（角色） → {n_groups} 个能力子轴'
        f" → 共 {n_features} 个具体功能点。",
        '  每个功能点都在 <a href="./FEATURES.md"><code>docs/FEATURES.md</code></a> 中有详细的作用与访问方法。',
        "  本页由 <code>docs/features.toml</code> 生成（<code>python scripts/build_feature_map.py</code>），不要手改。",
        "</p>",
        "",
        '<div class="lead">',
        "  <strong>读图路径</strong>：先选你要扮演的角色（蓝/绿/红/紫/橙），沿子轴找到需要的能力，再点叶子查 FEATURES.md。",
        '  跨主轴共享的能力（如"本地 Dashboard"同时服务多类使用者）按其主要服务对象归位，并在 FEATURES.md 中可定位。',
        "</div>",
        "",
        "<h2>角色跳板</h2>",
        '<div class="axis-jump">',
        *[
            f'  <a class="j-{a["id"]}" href="#axis-{a["id"]}">{a["emoji"]} {html.escape(a["name"])}</a>'
            for a in axes
        ],
        "</div>",
        "",
        '<div class="nav">',
        '  <a href="#mindmap">↓ 思维导图</a>',
        '  <a href="#index">↓ 三层分类索引</a>',
        '  <a href="./FEATURES.md">↗ FEATURES.md（详细）</a>',
        '  <a href="./README.md">↗ 项目结构</a>',
        "</div>",
        "",
        "<!-- ============== 思维导图 ============== -->",
        f'<h2 id="mindmap">一、{numeral}主轴思维导图</h2>',
    ]
    for axis in axes:
        out += [
            "",
            f'<h3 id="axis-{axis["id"]}">{axis["emoji"]} {html.escape(axis["name"])} — {html.escape(axis["tagline"])}</h3>',
            f'<div class="mermaid-wrap {axis["id"]}">',
            '<pre class="mermaid">',
            "mindmap",
            f"  root(({mind_label(axis['name'])}))",
        ]
        for group in axis["group"]:
            out.append(f"    {mind_label(group['name'])}")
            out += [f"      {mind_label(f.get('mind') or f['name'])}" for f in group["feature"]]
        out += ["</pre>", "</div>"]
    out += [
        "",
        "<!-- ============== 三层分类索引 ============== -->",
        '<h2 id="index">二、三层分类索引（可折叠）</h2>',
        "",
        '<div class="controls">',
        "  <button onclick=\"document.querySelectorAll('details.group').forEach(d=>d.open=true)\">展开全部</button>",
        "  <button onclick=\"document.querySelectorAll('details.group').forEach(d=>d.open=false)\">折叠全部</button>",
        "</div>",
    ]
    for axis in axes:
        count = sum(len(g["feature"]) for g in axis["group"])
        out += [
            "",
            f"<!-- {axis['name']} -->",
            f'<div class="axis {axis["id"]}"><span>{html.escape(axis["name"])}</span>'
            f'<span class="cnt">{len(axis["group"])} 子轴 · {count} 功能</span></div>',
        ]
        for group in axis["group"]:
            note = f" · {html.escape(group['note'])}" if group.get("note") else ""
            out += [
                "",
                f'<details class="group"><summary><span>{html.escape(group["name"])}</span>'
                f'<span class="count">{len(group["feature"])} 项{note}</span></summary>',
                "<ul>",
            ]
            for f in group["feature"]:
                entry = f" {entry_html(f['entry'])}" if f.get("entry") else ""
                out.append(
                    f"  <li><strong>{html.escape(f['name'])}</strong> — {html.escape(f['desc'])}{entry}</li>"
                )
            out += ["</ul>", "</details>"]
    out += [
        "",
        "<footer>",
        f'  <p>数据源：<a href="./features.toml"><code>docs/features.toml</code></a>（{n_features} 个功能点，'
        '每个都指向 <a href="./FEATURES.md"><code>docs/FEATURES.md</code></a> 里的一行详细说明）。</p>',
        "  <p>跨主轴共用的能力（如<em>本地 Dashboard</em>同时服务世界构建者与研究者）按其主要服务对象归位，详细仍见 FEATURES.md。</p>",
        "  <p>维护约定：新增 / 移除 / 重组功能时改 <code>docs/features.toml</code>，再运行 "
        "<code>python scripts/build_feature_map.py</code>；<code>tests/test_feature_registry.py</code> 检查两边对得上。</p>",
        '  <p>图形：<a href="https://mermaid.js.org/">Mermaid</a> 思维导图（CDN 加载 <code>mermaid@10</code>）。</p>',
        "</footer>",
        "",
        '<script type="module">',
        '  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs";',
        "  mermaid.initialize({",
        "    startOnLoad: true,",
        '    theme: "default",',
        '    securityLevel: "loose",',
        "    mindmap: { useMaxWidth: true, padding: 12 },",
        "    themeVariables: {",
        '      fontFamily: \'"Songti SC","STSong","Source Han Serif",Georgia,serif\',',
        '      fontSize: "14px"',
        "    }",
        "  });",
        '  document.querySelectorAll("pre.mermaid").forEach((el, i) => {',
        '    el.id = "mm-" + i;',
        "  });",
        "</script>",
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(out)


def render(registry: dict, current: str) -> str:
    """The page: the current ``<head>`` part, then the generated body."""
    head = current[: current.index("<body>")] if "<body>" in current else current
    return head + render_body(registry)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build docs/FEATURE_MAP.html from docs/features.toml")
    parser.add_argument("--check", action="store_true", help="exit 1 if the page is out of date")
    args = parser.parse_args(argv)
    with open(PAGE, encoding="utf-8") as fh:
        current = fh.read()
    page = render(load_registry(), current)
    if args.check:
        if page != current:
            print("docs/FEATURE_MAP.html is out of date: python scripts/build_feature_map.py")
            return 1
        return 0
    if page != current:
        with open(PAGE, "w", encoding="utf-8") as fh:
            fh.write(page)
        print("rewrote docs/FEATURE_MAP.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
