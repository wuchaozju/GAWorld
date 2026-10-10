#!/usr/bin/env python3
"""
Build terminal variants of every dashboard page.

For each page in /site/dashboard/<name>.html, produce /site/terminal/<name>.html
that:
  1. Replaces /site/tokens.css            → /terminal/tokens-terminal.css
  2. Replaces /site/dashboard/styles.css  → /terminal/terminal-styles.css
  3. Replaces /site/dashboard/page-shell.css → /terminal/terminal-shell.css
  4. Leaves page-specific CSS alone (e.g. studio.css) — those still load.
  5. Rewrites /site/dashboard/<x>.{js,css} → /site/dashboard/<x>.{js,css}  (untouched)
  6. Inserts CRT overlays + a topbar (unless the page already is-embedded).
  7. Sets lang="zh-CN" if not already.

This is the same shape as site/citymap/build.py: a build-time tool that
produces standalone, double-clickable HTML in /site/terminal/.

Usage:
  python3 /site/terminal/_build.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC  = ROOT / "site" / "dashboard"
DST  = ROOT / "site" / "terminal"

# Pages to skip (those already exist as terminal-native, or out of scope).
SKIP = {
    "index.html",      # uses /console nav, terminal/console.html already covers
    "docs.html",       # terminal/docs.html already covers
    "settings.html",   # cream settings is fine; skipping to keep this batch tight
}

# Map: source css → replacement css (relative paths only — absolute URLs handled by str.replace).
TOKEN_MAP = {
    "/site/tokens.css":                "/terminal/tokens-terminal.css",
    "/site/dashboard/styles.css":      "/terminal/terminal-styles.css",
    "/site/dashboard/page-shell.css":  "/terminal/terminal-shell.css",
}

# Loaded last in every terminal HTML so page-specific CSS that re-declares
# tokens (games.css, studio.css, …) is overridden back to the terminal
# palette. CSS custom properties are inherited, so re-declaring at :root
# in a later-loaded stylesheet always wins.
TERMINAL_OVERRIDE = "/terminal/terminal-override.css"

CRT_BAR_HTML = """
  <div class="crt crt-scanlines" aria-hidden="true"></div>
  <div class="crt crt-sweep"     aria-hidden="true"></div>
  <div class="crt crt-vignette"  aria-hidden="true"></div>
  <div class="bg-grid"           aria-hidden="true"></div>
"""


def transform(html: str, page_name: str) -> str:
    # 1. Swap css references.
    for old, new in TOKEN_MAP.items():
        html = html.replace(old, new)

    # 1b. Some pages (analytics, collaboration) skip styles.css /
    #     page-shell.css and ship their own complete stylesheet. Detect
    #     that and inject the terminal equivalents so the .button /
    #     .panel / .studio-* atoms still apply.
    needs_styles = '<link rel="stylesheet"' in html and (
        "/site/dashboard/styles.css" not in html
        and "/terminal/terminal-styles.css" not in html
    )
    needs_shell = (
        "/site/dashboard/page-shell.css" not in html
        and "/terminal/terminal-shell.css" not in html
    )
    inject_before = "</head>"
    if needs_styles:
        html = html.replace(
            inject_before,
            f'  <link rel="stylesheet" href="/terminal/terminal-styles.css" />\n{inject_before}',
            1,
        )
    if needs_shell:
        html = html.replace(
            inject_before,
            f'  <link rel="stylesheet" href="/terminal/terminal-shell.css" />\n{inject_before}',
            1,
        )

    # 2. Append terminal-override.css as the LAST stylesheet so any
    #    page-specific CSS (games.css, studio.css, …) gets re-skinned.
    if TERMINAL_OVERRIDE not in html:
        html = html.replace(
            "</head>",
            f'  <link rel="stylesheet" href="{TERMINAL_OVERRIDE}" />\n</head>',
            1,
        )

    # 3. Add favicon if missing.
    if 'rel="icon"' not in html and '<link rel="icon"' not in html:
        html = html.replace(
            '<meta charset="utf-8" />',
            '<meta charset="utf-8" />\n  <link rel="icon" type="image/svg+xml" href="/site/assets/favicon.svg" />',
            1,
        )

    # 3. Insert CRT overlay block right after <body> if not already there.
    if 'class="crt crt-scanlines"' not in html:
        html = re.sub(r"<body([^>]*)>", r"<body\1>" + CRT_BAR_HTML, html, count=1, flags=re.IGNORECASE)

    # 4. Add a tiny back-to-console link in <head> via a meta is just for linking,
    #    but the cream pages don't have a topbar we can re-skin — the studio shell
    #    is the page shell. We add a link to /terminal/console.html from the
    #    studio-top header when the page is one of the step-rail pages; if not,
    #    we add a small floating "go back" pill.
    if 'class="studio-top"' in html and 'class="topbar-status"' not in html:
        html = _inject_terminal_status(html)

    # 5. Title tweak: prefix with // .
    html = re.sub(
        r"<title>([^<]+)</title>",
        lambda m: f"<title>GAWorld // {m.group(1).split('·', 1)[-1].strip() if '·' in m.group(1) else m.group(1)}</title>",
        html,
        count=1,
    )

    return html


def _inject_terminal_status(html: str) -> str:
    """Add a small `// terminal_variant` chip in the studio-top header
    so the reader knows this is the dark variant of the page."""
    return html.replace(
        "</header>",
        """<span class="topbar-status">
        <span class="pulse-dot" aria-hidden="true"></span>
        TERMINAL_VARIANT · <a href="/terminal/console.html" style="color: var(--green); text-decoration: none;">back_to_console</a>
      </span>
    </header>""",
        1,
    )


def main() -> int:
    if not SRC.is_dir():
        print(f"missing {SRC}", file=sys.stderr)
        return 1
    DST.mkdir(parents=True, exist_ok=True)

    generated = []
    skipped = []
    for src_html in sorted(SRC.glob("*.html")):
        name = src_html.name
        if name in SKIP:
            skipped.append(name)
            continue
        out_html = DST / name
        text = src_html.read_text(encoding="utf-8")
        text = transform(text, name)
        out_html.write_text(text, encoding="utf-8")
        kb = out_html.stat().st_size / 1024
        generated.append((name, kb))

    print(f"[build-terminal] generated {len(generated)} pages:")
    for n, kb in generated:
        print(f"  - /site/terminal/{n}  ({kb:.0f} KB)")
    if skipped:
        print(f"[build-terminal] skipped: {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())