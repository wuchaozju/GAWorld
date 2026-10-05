"""Appearance works across independent pages and console frames."""

import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def test_theme_behavior_node_suite():
    result = subprocess.run(
        ["node", "--test", str(ROOT / "site/theme.test.js")],
        cwd=ROOT, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_main_pages_apply_theme_before_styles_and_load_city_lab_last():
    pages = [ROOT / "site/index.html", ROOT / "site/console/index.html", ROOT / "site/simviz/index.html"]
    pages += list((ROOT / "site/dashboard").glob("*.html"))
    for page in pages:
        html = page.read_text(encoding="utf-8")
        # Redirect-only documents have no interface to theme.
        if '<meta http-equiv="refresh"' in html:
            continue
        head = html.split("</head>")[0]
        assert head.count('<script src="/site/theme.js"></script>') == 1, page.name
        assert head.index("/site/theme.js") < head.index('rel="stylesheet"'), page.name
        sheets = re.findall(r'<link rel="stylesheet" href="([^"]+)"', head)
        assert sheets[-1] == "/site/city-lab.css", page.name
        for sheet in sheets:
            assert (ROOT / urlsplit(sheet).path.lstrip("/")).is_file(), sheet
