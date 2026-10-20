"""Selected branding loads on both signed-in and public entry pages."""

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SYMBOL = "/site/auth/brand/gaworld-symbol-a.png"
LOCKUP = "/site/auth/brand/gaworld-lockup-a.png"


def test_unneeded_brand_assets_are_not_public():
    from gaworld.accounts.policy import required

    for method in ("GET", "HEAD", "POST"):
        assert required(method, "/site/assets/private.png") != "public"


def test_pages_do_not_reference_the_missing_brand_image():
    pages = list((ROOT / "site").rglob("*.html"))
    assert pages
    for page in pages:
        assert "logo-emergent.png" not in page.read_text(encoding="utf-8"), page


def test_selected_brand_images_are_public_and_present():
    from gaworld.accounts.policy import required

    for url in (SYMBOL, LOCKUP):
        assert (ROOT / url.lstrip("/")).is_file(), url
        for method in ("GET", "HEAD"):
            assert required(method, url) == "public"


def test_login_uses_the_selected_public_lockup():
    html = (ROOT / "site/auth/index.html").read_text(encoding="utf-8")
    assert "GAWorld" in html
    sources = re.findall(r'<img[^>]+src="([^"]+)"', html)
    assert LOCKUP in sources
    assert all(source.startswith("/site/auth/brand/") for source in sources)
    assert 'id="nickname"' in html and 'id="password"' in html


def test_primary_brand_slots_use_the_selected_symbol():
    for name in (
        "site/index.html",
        "site/home/index.html",
        "site/console/index.html",
        "site/dashboard/research.html",
        "site/dashboard/studio.html",
        "site/dashboard/games.html",
        "site/simviz/index.html",
    ):
        html = (ROOT / name).read_text(encoding="utf-8")
        assert re.search(r'<img[^>]+src="' + re.escape(SYMBOL) + '"', html), name
        assert 'href="' + SYMBOL + '"' in html, name
        assert "/site/brand.css" in html, name


def test_local_page_scripts_styles_and_images_are_committed_assets():
    class Assets(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            url = attrs.get("src") if tag in {"script", "img"} else None
            if tag == "link" and attrs.get("rel") in {"stylesheet", "icon"}:
                url = attrs.get("href")
            path = urlsplit(url or "").path
            if path.startswith("/site/"):
                assert (ROOT / path.lstrip("/")).is_file(), path

    for page in (ROOT / "site").rglob("*.html"):
        Assets().feed(page.read_text(encoding="utf-8"))
