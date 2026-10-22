"""Generate the handbook's diagram set as PNGs.

Each diagram is authored as a small HTML document (styled with the GAWorld
brand palette) and rendered with headless Chromium, so CJK typography stays
crisp. Layout kinds:

    stack  - vertical layers, each holding a row of boxes
    flow   - horizontal chain of steps
    grid   - card grid with optional grouping headers
    cycle  - closed loop of stages
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "images"
OUT.mkdir(parents=True, exist_ok=True)

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  background: #ffffff; color: #22301f; padding: 28px 30px 24px;
  width: 1320px;
}
.d-title { font-size: 30px; font-weight: 700; color: #1d3324; letter-spacing: .5px; }
.d-sub   { font-size: 17px; color: #6c7a66; margin-top: 6px; margin-bottom: 22px; }
.layer { margin-bottom: 9px; }
.layer-label {
  font-size: 15px; font-weight: 700; color: #8a9a83; letter-spacing: 1.4px;
  text-transform: uppercase; margin-bottom: 6px;
}
.row { display: flex; gap: 9px; align-items: stretch; }
.box {
  flex: 1; background: #FBF9F4; border: 1.5px solid #E1DACA; border-radius: 9px;
  padding: 12px 14px; font-size: 16.5px; line-height: 1.5;
}
.box b { display: block; color: #1d3324; font-size: 17px; margin-bottom: 3px; }
.box span { color: #5d6b58; font-size: 14.5px; }
.box.accent { background: #FDF3E7; border-color: #E0A469; }
.box.accent b { color: #A85A1C; }
.box.green  { background: #EFF5EC; border-color: #9BB894; }
.box.green b { color: #2E5B34; }
.box.dark   { background: #1d3324; border-color: #1d3324; color: #EDF3EA; }
.box.dark b { color: #B6E0A8; }
.box.dark span { color: #BFD0BC; }
.arrow-down {
  text-align: center; color: #B08A62; font-size: 17px; line-height: 1;
  margin: 3px 0 6px;
}
.flow { display: flex; align-items: stretch; gap: 0; }
.flow .box { flex: 0 0 auto; min-width: 168px; }
.flow .sep {
  display: flex; align-items: center; padding: 0 7px;
  color: #B08A62; font-size: 19px;
}
.grid { display: grid; gap: 10px; }
.gcard {
  background: #FBF9F4; border: 1.5px solid #E1DACA; border-radius: 9px; padding: 12px 14px;
}
.gcard h4 { font-size: 17.5px; color: #1d3324; margin-bottom: 5px; }
.gcard p { font-size: 14.5px; color: #5d6b58; line-height: 1.55; }
.gcard code { background: #EFEAE0; padding: 1px 5px; border-radius: 4px; font-size: 11.5px; }
.ghead {
  font-size: 12.5px; font-weight: 700; color: #8a9a83; letter-spacing: 1.3px;
  margin: 4px 0 7px; text-transform: uppercase;
}
.note {
  margin-top: 16px; font-size: 14.5px; color: #6c7a66; line-height: 1.6;
  border-left: 3px solid #D9C9AC; padding-left: 11px;
}
.cyclewrap { display: flex; flex-wrap: wrap; gap: 8px; width: 1300px; }
.stage {
  width: 272px; background: #FBF9F4; border: 1.5px solid #E1DACA; border-radius: 9px;
  padding: 10px 12px;
}
.stage .n {
  display: inline-block; font-size: 11px; font-weight: 700; color: #fff;
  background: #2E5B34; border-radius: 20px; padding: 1px 8px; margin-bottom: 5px;
}
.stage h5 { font-size: 16.5px; color: #1d3324; margin-bottom: 3px; }
.stage p { font-size: 14px; color: #5d6b58; line-height: 1.5; }
.pill {
  display: inline-block; font-size: 13.5px; background: #FDF3E7; color: #A85A1C;
  border: 1px solid #E0A469; border-radius: 20px; padding: 2px 9px; margin: 2px 4px 2px 0;
}
.pill.g { background: #EFF5EC; color: #2E5B34; border-color: #9BB894; }
.pill.d { background: #F6EAEA; color: #A03A32; border-color: #D9A19C; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border: 1px solid #E1DACA; padding: 7px 10px; text-align: left; vertical-align: top; }
th { background: #F2EEE4; color: #1d3324; font-weight: 700; }
td code { background: #EFEAE0; padding: 1px 5px; border-radius: 4px; font-size: 12px; }
"""


def esc(text: str) -> str:
    return html.escape(str(text))


def render_stack(spec: dict) -> str:
    out = []
    for layer in spec["layers"]:
        out.append(
            f'<div class="layer"><div class="layer-label">{esc(layer["label"])}</div><div class="row">'
        )
        for item in layer["items"]:
            cls = item.get("c", "")
            body = f"<b>{esc(item['t'])}</b><span>{esc(item.get('d', ''))}</span>"
            out.append(f'<div class="box {cls}">{body}</div>')
        out.append("</div></div>")
        if layer is not spec["layers"][-1]:
            out.append('<div class="arrow-down">▼</div>')
    return "\n".join(out)


def render_flow(spec: dict) -> str:
    out = ['<div class="flow">']
    for index, item in enumerate(spec["steps"]):
        if index:
            out.append('<div class="sep">→</div>')
        cls = item.get("c", "")
        body = f"<b>{esc(item['t'])}</b><span>{esc(item.get('d', ''))}</span>"
        out.append(f'<div class="box {cls}" style="min-width:{item.get("w", 190)}px">{body}</div>')
    out.append("</div>")
    return "\n".join(out)


def render_grid(spec: dict) -> str:
    out = []
    for group in spec["groups"]:
        out.append(f'<div class="ghead">{esc(group["label"])}</div>')
        out.append(f'<div class="grid" style="grid-template-columns:repeat({group.get("cols", 3)},1fr)">')
        for card in group["cards"]:
            pills = "".join(
                f'<span class="pill {p.get("c", "")}">{esc(p["t"])}</span>' for p in card.get("pills", [])
            )
            out.append(
                f'<div class="gcard"><h4>{esc(card["t"])}</h4><p>{esc(card.get("d", ""))}</p>{pills}</div>'
            )
        out.append("</div>")
    return "\n".join(out)


def render_cycle(spec: dict) -> str:
    out = ['<div class="cyclewrap">']
    for index, stage in enumerate(spec["stages"]):
        out.append(
            f'<div class="stage"><span class="n">{index + 1:02d}</span>'
            f"<h5>{esc(stage['t'])}</h5><p>{esc(stage.get('d', ''))}</p></div>"
        )
    return "\n".join(out)


def render_table(spec: dict) -> str:
    out = ["<table><thead><tr>"]
    out += [f"<th>{esc(h)}</th>" for h in spec["head"]]
    out.append("</tr></thead><tbody>")
    for row in spec["rows"]:
        out.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


RENDERERS = {
    "stack": render_stack,
    "flow": render_flow,
    "grid": render_grid,
    "cycle": render_cycle,
    "table": render_table,
}


def page(spec: dict) -> str:
    body = RENDERERS[spec["layout"]](spec)
    note = f'<div class="note">{spec["note"]}</div>' if spec.get("note") else ""
    return (
        f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f"<style>{CSS}</style></head><body>"
        f'<div class="d-title">{esc(spec["title"])}</div>'
        f'<div class="d-sub">{esc(spec.get("sub", ""))}</div>'
        f"{body}{note}</body></html>"
    )


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from diagram_specs import DIAGRAMS  # type: ignore

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page_obj = browser.new_page(viewport={"width": 1480, "height": 900}, device_scale_factor=1.35)
        for name, spec in DIAGRAMS.items():
            html_text = page(spec)
            tmp = Path("/tmp") / f"gaworld-diagram-{name}.html"
            tmp.write_text(html_text, encoding="utf-8")
            page_obj.goto(tmp.as_uri(), wait_until="load")
            page_obj.wait_for_timeout(280)
            path = OUT / f"d-{name}.png"
            page_obj.screenshot(path=str(path), full_page=True)
            print(f"OK   d-{name}  {path.stat().st_size // 1024} KB")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
