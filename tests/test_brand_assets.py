"""The approved brand is available on standalone pages and public deployments."""

import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGO = "/site/assets/logo-emergent.png"


def test_logo_is_public_without_exposing_other_assets():
    from gaworld.accounts.policy import required

    assert required("GET", LOGO) == "public"
    assert required("HEAD", LOGO) == "public"
    assert required("GET", "/site/assets/private.png") != "public"
    assert required("POST", LOGO) != "public"


def test_brand_icon_has_alpha_and_enough_resolution():
    data = (ROOT / LOGO.lstrip("/")).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height, _, color_type = struct.unpack(">IIBB", data[16:26])
    assert width == height and width >= 256
    assert color_type == 6, "Navbar logo needs RGBA for light and dark backgrounds"


def test_standalone_pages_use_a_resolvable_brand_favicon():
    for page in (ROOT / "site").rglob("*.html"):
        html = page.read_text(encoding="utf-8")
        head = html.split("</head>")[0]
        if "GAWorld" not in head or '<meta http-equiv="refresh"' in head:
            continue
        icons = re.findall(r'<link[^>]+rel="icon"[^>]+href="([^"]+)"', head)
        assert icons == [LOGO], page.relative_to(ROOT)
        assert (ROOT / icons[0].lstrip("/")).is_file()


def test_navigation_and_panel_marks_reference_the_brand_asset():
    count = 0
    for page in (ROOT / "site").rglob("*.html"):
        html = page.read_text(encoding="utf-8")
        marks = re.findall(r'<(?:span|div) class="brand-mark[^\"]*"[^>]*>(.*?)</(?:span|div)>', html)
        for mark in marks:
            count += 1
            assert f'src="{LOGO}"' in mark, page.relative_to(ROOT)
            assert 'class="brand-symbol"' in mark
            assert 'width="' in mark and 'height="' in mark
    assert count >= 2, "Both the homepage and console must carry the brand"
