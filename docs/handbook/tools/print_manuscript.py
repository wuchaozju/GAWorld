"""Render the handbook manuscript to PDF with Chromium, using the same page
setup as the .docx (A4, 2.5 cm margins, 10.5 pt body, 1.2 line height).

Word's own PDF export became unresponsive on this machine, so this gives an
independent page count and a visual proof of the printed layout.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent.parent
HTML = ROOT / "build" / "handbook.html"
PDF = ROOT / "build" / "handbook-print.pdf"

CSS = """
@page { size: A4; margin: 2.5cm; }
html { font-family: "PingFang SC", "Microsoft YaHei", sans-serif; }
body {
  font-size: 10.5pt; line-height: 1.2; color: #22301f;
  max-width: 16cm; margin: 0 auto; text-align: justify;
}
p { margin: 0 0 3.5pt 0; }
h1 { font-size: 18pt; color: #1D3324; margin: 10pt 0 6pt; page-break-before: always; }
h2 { font-size: 14pt; color: #1D3324; margin: 7.5pt 0 5pt; }
h3 { font-size: 12pt; color: #1D3324; margin: 6.5pt 0 4.5pt; }
h4 { font-size: 11pt; color: #1D3324; margin: 5.5pt 0 4pt; }
img { width: 16cm; display: block; margin: 6pt auto 2pt; }
pre {
  background: #F6F3EC; border: 1px solid #E1DACA; border-radius: 4px;
  font-family: Menlo, Consolas, monospace; font-size: 9pt; line-height: 1.0;
  padding: 4pt 7pt; margin: 3pt 0 4.5pt; white-space: pre-wrap; word-break: break-all;
}
code { background: #EFEAE0; padding: 0 2pt; border-radius: 3px; font-size: 9.5pt; }
pre code { background: none; padding: 0; font-size: 9pt; }
table { border-collapse: collapse; width: 100%; font-size: 10.5pt; margin: 4pt 0 6pt; }
th, td { border: 1px solid #E1DACA; padding: 3.5pt 5pt; vertical-align: top; }
th { background: #F2EEE4; }
ul, ol { margin: 0 0 3.5pt 0; padding-left: 18pt; }
li { margin: 0 0 1.5pt 0; }
blockquote { border-left: 3px solid #D9C9AC; margin: 4pt 0; padding-left: 8pt; color: #55635A; }
#TOC ul { list-style: none; padding-left: 0; }
a { color: #1D3324; text-decoration: none; }
"""


def main() -> int:
    manuscript = ROOT / "handbook.md"
    if not manuscript.is_file():
        print("run build_handbook.py --md-only first")
        return 1
    subprocess.run(
        [
            "pandoc",
            str(manuscript),
            "-o",
            str(HTML),
            "--toc",
            "--toc-depth=2",
            "--standalone",
            "--metadata",
            "toc-title=目录",
            "--from",
            "markdown-implicit_figures+pipe_tables+tex_math_dollars+link_attributes",
        ],
        check=True,
        capture_output=True,
        cwd=str(ROOT),
    )
    html = HTML.read_text(encoding="utf-8")
    html = html.replace("</head>", f"<style>{CSS}</style></head>")
    # the manuscript references images/ relative to the handbook root, so the
    # html has to live there for the browser to resolve them
    html = html.replace('src="images/', 'src="../images/')
    HTML.write_text(html, encoding="utf-8")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(HTML.as_uri(), wait_until="load")
        page.wait_for_timeout(2500)
        page.pdf(path=str(PDF), format="A4", print_background=True, prefer_css_page_size=True)
        browser.close()

    size = PDF.stat().st_size // 1024
    print(f"wrote {PDF} ({size} KB)")
    try:
        import pypdf

        print("PAGES:", len(pypdf.PdfReader(str(PDF)).pages))
    except Exception as error:
        print("page count unavailable:", error)
    return 0


if __name__ == "__main__":
    sys.exit(main())
