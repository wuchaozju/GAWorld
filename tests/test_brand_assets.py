"""Text branding works without the missing, uncommitted brand image."""

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def test_unneeded_brand_assets_are_not_public():
    from gaworld.accounts.policy import required

    for method in ("GET", "HEAD", "POST"):
        assert required(method, "/site/assets/private.png") != "public"


def test_pages_do_not_reference_the_missing_brand_image():
    pages = list((ROOT / "site").rglob("*.html"))
    assert pages
    for page in pages:
        assert "logo-emergent.png" not in page.read_text(encoding="utf-8"), page


def test_login_keeps_text_brand_without_protected_image_dependencies():
    html = (ROOT / "site/auth/index.html").read_text(encoding="utf-8")
    assert "GAWorld" in html
    assert not re.findall(r'<img[^>]+src="([^"]+)"', html)
    assert 'id="nickname"' in html and 'id="password"' in html


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
