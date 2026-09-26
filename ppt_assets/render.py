#!/usr/bin/env python3
"""Render the GAWorld intro Markdown into a single self-contained HTML deck
in 克制的中文期刊风 style. Real screenshots are inlined as <img src="data:...">
so the file is portable.

Output: /Users/cw/dev/GAWorld/ppt_assets/GAWorld_项目介绍.html
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

import markdown

ROOT = Path("/Users/cw/dev/GAWorld")
ASSETS = ROOT / "ppt_assets"
SHOTS = ASSETS / "screenshots"
OUT = ASSETS / "GAWorld_项目介绍.html"


def b64(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def embed_media(md_text: str) -> str:
    """Inline every <media src="../ppt_assets/screenshots/X.png" /> as a real <img>."""
    pattern = re.compile(r'<media\s+src="\.\./ppt_assets/screenshots/([^"]+)"\s*/>')

    def sub(m: re.Match[str]) -> str:
        fname = m.group(1)
        path = SHOTS / fname
        if not path.exists():
            return f'<p class="missing">[missing screenshot: {fname}]</p>'
        return (
            f'<figure class="shot">'
            f'<img src="{b64(path)}" alt="{fname}" loading="lazy"/>'
            f'<figcaption>{fname}</figcaption>'
            f'</figure>'
        )

    return pattern.sub(sub, md_text)


def md_to_html(md: str) -> str:
    """Markdown → HTML, with page-number badge on '第 N 页' h2 headings."""
    md = embed_media(md)
    html = markdown.markdown(
        md,
        extensions=["fenced_code", "tables", "sane_lists"],
        output_format="html",
    )
    # rewrite <h2>第 N 页 · Title</h2> to include a span badge
    def repl(m: re.Match[str]) -> str:
        text = m.group(1)
        badge_match = re.match(r"^(第\s+\d+\s+页)\s*[·\.]\s*(.+)$", text)
        if badge_match:
            badge, rest = badge_match.group(1), badge_match.group(2)
            return f'<h2 id="{badge}"><span class="pgnum">{badge}</span><span>{rest}</span></h2>'
        return f'<h2>{text}</h2>'

    html = re.sub(r"<h2>([^<]+)</h2>", repl, html)
    return html


def page_split(html: str) -> list[str]:
    """Split by 第 N 页 h2 markers → list of section HTML strings."""
    # Match h2 whose id starts with '第 N 页' OR h2 whose first text is '第 N 页'
    parts = re.split(r'(?=<h2\b[^>]*>\s*(?:<span class="pgnum">)?第\s+\d+\s+页)', html)
    return [p.strip() for p in parts if p.strip()]


def make_cover() -> str:
    hero = SHOTS / "01_hero.png"
    return f"""
<div class="cover">
  <div class="eyebrow">GENERATIVE AGENT SIMULATION · v2026.09</div>
  <h1>GAWorld 项目介绍</h1>
  <div class="sub">生成式城市社会仿真 · Generative Agent Simulation for Urban Social Behavior</div>
  <div class="lede">
    GAWorld 把人物画像、长期记忆、社会影响、环境扰动、政策冲击、闭环经济和 LLM 决策整合到一条
    可回放、可对照的流水线。同批居民、同一颗种子，只换一件事——一场暴雨、一笔补贴、一条新地铁线——
    把"如果当初"做成可量化的对照实验。本机即可复现，不依赖外部 SaaS。
  </div>

  <div class="four">
    <div class="item">
      <div class="num">01 — 仿真引擎</div>
      <div class="ttl">society-centric 微内核</div>
      <div class="desc">12 阶段认知管线 + 9 个内置插件，全部可热替换。</div>
    </div>
    <div class="item">
      <div class="num">02 — 真实人群</div>
      <div class="ttl">OCEAN + 家庭 + Dunbar</div>
      <div class="desc">每位居民带人格、家庭节点、三层记忆、社交圈；OCEAN 决定风格，通道独立可关。</div>
    </div>
    <div class="item">
      <div class="num">03 — 真实城市</div>
      <div class="ttl">OSM 地图 + 闭环经济</div>
      <div class="desc">地名创建城市；钱守恒、部门池、个税代扣、市场因子投资、跨城市本地新闻。</div>
    </div>
    <div class="item">
      <div class="num">04 — 可对照实验</div>
      <div class="ttl">平行世界 + 群体采访</div>
      <div class="desc">同种子分叉到 N 个世界；每步测距，找出政策真正落到哪些个人头上。</div>
    </div>
  </div>

  <div class="shotwrap">
    <img src="{b64(hero)}" alt="项目首页"/>
  </div>
  <div class="shotcap">FIG. 1 · 项目首页（截图自本机 dashboard 服务）</div>

  <div class="meta">
    <div><b>CODE</b>Python 3.11+ · 纯本地</div>
    <div><b>BACKEND</b>Ollama / OpenAI / Anthropic 多路由</div>
    <div><b>FRONTEND</b>13 个控制台视图 · 中英双语</div>
  </div>
  <div class="repo">git: /Users/cw/dev/GAWorld &nbsp;·&nbsp; docs: docs/ &nbsp;·&nbsp; entry: python dashboard_server.py</div>
</div>
"""


CSS = """
:root{
  --ink:#1a1a1a;
  --ink-soft:#444;
  --rule:#1a1a1a;
  --paper:#faf7f1;
  --paper-deep:#f3eee2;
  --accent:#5b3a29;
  --accent-soft:#8b6f59;
  --link:#3a2b1f;
  --code-bg:#efe9da;
}
*{box-sizing:border-box;}
html,body{margin:0;padding:0;background:var(--paper);color:var(--ink);font-family:"Source Han Serif SC","Noto Serif CJK SC","Songti SC","STSong","SimSun",serif;font-size:14.5px;line-height:1.65;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;}
.page{
  width:210mm;min-height:297mm;margin:0 auto 18px auto;padding:18mm 16mm 16mm 16mm;
  background:var(--paper);border:1px solid #d8cfb8;position:relative;
  box-shadow:0 6px 24px rgba(0,0,0,.06);page-break-after:always;
}
.page:last-child{page-break-after:auto;}
.page::before{
  content:"GAWorld · 项目介绍 · v2026.09";
  position:absolute;left:16mm;top:7mm;
  font-family:"Inter","Helvetica Neue",Arial,sans-serif;
  font-size:9px;letter-spacing:.2em;color:var(--accent-soft);
}
.page::after{
  content:counter(page) " / " counter(pages);
  position:absolute;right:16mm;bottom:7mm;
  font-family:"Inter","Helvetica Neue",Arial,sans-serif;
  font-size:9px;letter-spacing:.2em;color:var(--accent-soft);
}
@page{size:A4;margin:0;}
body{counter-reset:page;}
.page{counter-increment:page;}
body{counter-reset:pages 10;}

/* cover */
.cover{display:flex;flex-direction:column;min-height:265mm;}
.cover .eyebrow{font-family:"Inter","Helvetica Neue",Arial,sans-serif;letter-spacing:.32em;font-size:10.5px;color:var(--accent);margin-top:6mm;}
.cover h1{font-size:48px;line-height:1.1;margin:10px 0 6px 0;letter-spacing:.01em;font-weight:600;border:none;padding:0;}
.cover .sub{font-size:17px;color:var(--ink-soft);margin:0 0 18px 0;letter-spacing:.01em;}
.cover .lede{font-size:14.5px;line-height:1.75;color:var(--ink);max-width:158mm;text-align:justify;text-justify:inter-ideograph;}
.cover .four{display:grid;grid-template-columns:1fr 1fr;gap:6mm 8mm;margin:10mm 0;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);padding:7mm 0;}
.cover .four .item{padding-right:6mm;}
.cover .four .item .num{font-family:"Inter","Helvetica Neue",Arial,sans-serif;color:var(--accent);font-size:11px;letter-spacing:.3em;margin-bottom:4px;}
.cover .four .item .ttl{font-size:15px;font-weight:600;color:var(--ink);margin-bottom:4px;}
.cover .four .item .desc{font-size:13px;color:var(--ink-soft);line-height:1.6;}
.cover .shotwrap{margin-top:6mm;border:1px solid #c9bfa6;max-height:80mm;overflow:hidden;}
.cover .shotwrap img{width:100%;display:block;}
.cover .shotcap{font-family:"Inter","Helvetica Neue",Arial,sans-serif;font-size:10px;color:var(--accent-soft);letter-spacing:.15em;margin-top:4px;text-align:right;}
.cover .meta{display:grid;grid-template-columns:repeat(3,1fr);gap:5mm 8mm;margin-top:6mm;font-family:"Inter","Helvetica Neue",Arial,sans-serif;}
.cover .meta div{font-size:11.5px;color:var(--ink-soft);}
.cover .meta b{display:block;color:var(--accent);font-size:10px;letter-spacing:.25em;margin-bottom:3px;font-weight:500;text-transform:uppercase;}
.cover .repo{font-family:"JetBrains Mono","Menlo",monospace;font-size:11.5px;color:var(--link);margin-top:5mm;border-top:1px dashed #c9bfa6;padding-top:5mm;}

/* body */
h1{font-size:22px;font-weight:600;border-bottom:1px solid var(--rule);padding-bottom:5px;margin:0 0 10px 0;}
h2{font-size:18px;font-weight:600;margin:0 0 8px 0;padding-bottom:4px;border-bottom:1px solid #c9bfa6;display:flex;align-items:baseline;gap:8px;}
h2 .pgnum{font-family:"Inter","Helvetica Neue",Arial,sans-serif;color:var(--accent-soft);font-size:11px;letter-spacing:.2em;font-weight:500;}
h3{font-size:14.5px;font-weight:600;margin:10px 0 4px 0;color:var(--accent);}
h4{font-size:13px;font-weight:600;margin:8px 0 3px 0;color:var(--accent-soft);letter-spacing:.04em;}
p{margin:0 0 8px 0;text-align:justify;text-justify:inter-ideograph;}
strong{color:var(--accent);font-weight:600;}
code{font-family:"JetBrains Mono","Menlo",monospace;font-size:11.5px;background:var(--code-bg);padding:1px 5px;border-radius:3px;color:#3a2b1f;}
pre{background:var(--code-bg);padding:10px 12px;border-left:3px solid var(--accent);font-size:11.5px;line-height:1.5;border-radius:0 4px 4px 0;overflow-x:auto;margin:8px 0 10px 0;}
pre code{background:transparent;padding:0;}
ol,ul{padding-left:22px;margin:0 0 8px 0;}
ol li,ul li{margin-bottom:3px;}
hr{border:none;border-top:1px solid #c9bfa6;margin:10px 0;}

table{width:100%;border-collapse:collapse;margin:6px 0 10px 0;font-size:12.5px;}
table th,table td{border-bottom:1px solid #d8cfb8;padding:5px 8px;text-align:left;vertical-align:top;}
table th{background:var(--paper-deep);font-weight:600;color:var(--accent);}
table td:first-child{font-family:"JetBrains Mono","Menlo",monospace;color:var(--link);width:38%;}

/* figure */
figure.shot{margin:8px 0 10px 0;text-align:center;}
figure.shot img{width:100%;height:auto;max-height:130mm;object-fit:contain;object-position:top center;display:block;border:1px solid #c9bfa6;box-shadow:0 2px 8px rgba(0,0,0,.04);}
figure.shot figcaption{font-family:"Inter","Helvetica Neue",Arial,sans-serif;font-size:9.5px;color:var(--accent-soft);letter-spacing:.1em;text-align:right;padding-top:3px;}

/* section eyebrow */
.eyebrow{font-family:"Inter","Helvetica Neue",Arial,sans-serif;letter-spacing:.28em;font-size:10px;color:var(--accent);margin-bottom:4px;text-transform:uppercase;}

@media print{.page{margin:0;box-shadow:none;border:none;}}

/* TOC */
.toc ol{list-style:none;padding:0;border-top:1px solid var(--rule);}
.toc li{border-bottom:1px solid #d8cfb8;padding:6px 0;display:flex;justify-content:space-between;align-items:baseline;font-size:13.5px;}
.toc li span:first-child{flex:1;color:var(--ink);}
.toc li span:last-child{font-family:"JetBrains Mono",monospace;color:var(--accent-soft);font-size:11px;}

.missing{color:#a05a5a;font-style:italic;}
"""


def main() -> None:
    md = (ASSETS / "intro.md").read_text(encoding="utf-8")
    html_body = md_to_html(md)

    pages_html = page_split(html_body)
    page_chunks = pages_html[1:]  # drop front-matter (h1 title + 摘要)

    toc_items: list[tuple[str, str]] = []
    for chunk in page_chunks:
        m = re.search(r"<h2[^>]*>(?:<span class=\"pgnum\">)?(第\s+\d+\s+页)[^<]*?(?:</span>)?<span>([^<]+)</span>", chunk)
        if not m:
            m2 = re.search(r"<h2[^>]*>([^<]+)</h2>", chunk)
            if m2:
                toc_items.append((m2.group(1), ""))
            continue
        full = f"{m.group(1)} · {m.group(2)}"
        short = m.group(2)
        toc_items.append((full, short))

    toc_rows = "".join(
        f"<li><span>{full}</span><span>p.{i+2:02d}</span></li>"
        for i, (full, _short) in enumerate(toc_items)
    )

    toc_html = (
        '<section class="page toc-page">'
        '<div class="eyebrow">目  录 · CONTENTS</div>'
        '<h2 style="border:none;margin-top:6px">CONTENTS</h2>'
        f'<div class="toc"><ol>{toc_rows}</ol></div>'
        '<div class="meta" style="margin-top:14mm">'
        '<div><b>FORMAT</b>A4 单页装订 · 13 张</div>'
        '<div><b>STYLE</b>克制中文期刊</div>'
        '<div><b>SCOPE</b>项目能力 / 实证 / 上手</div>'
        '</div>'
        "</section>"
    )

    body_pages = "\n".join(
        f'<section class="page">{chunk}</section>' for chunk in page_chunks
    )
    cover_html = make_cover()

    full = (
        "<!doctype html><html lang='zh-CN'><head>"
        "<meta charset='utf-8'/>"
        "<title>GAWorld 项目介绍 · v2026.09</title>"
        f"<style>{CSS}</style>"
        "</head><body>"
        f'<section class="page">{cover_html}</section>'
        + toc_html
        + body_pages
        + "</body></html>"
    )

    OUT.write_text(full, encoding="utf-8")
    size_kb = OUT.stat().st_size // 1024
    print(f"OK  wrote {OUT}  ({size_kb} KB)")


if __name__ == "__main__":
    main()