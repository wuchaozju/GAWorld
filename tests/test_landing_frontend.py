"""The landing page is a working entrance to the existing application."""

import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from gaworld.apps.community_pages import page_target
from gaworld.apps.dashboard_server import _static_path_allowed

ROOT = Path(__file__).resolve().parents[1]


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = set()
        self.assets = set()
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "a" and attrs.get("href"):
            self.links.add(attrs["href"])
        if tag == "script" and attrs.get("src"):
            self.assets.add(attrs["src"])
        if tag == "link" and attrs.get("rel") in {"stylesheet", "icon"}:
            self.assets.add(attrs["href"])


@pytest.mark.parametrize("name", ["site/index.html", "site/home/index.html"])
def test_homepage_links_directly_to_feature_views(name):
    page = PageLinks()
    page.feed((ROOT / name).read_text())
    for view in ("dashboard", "city", "studio", "survey", "games", "research", "worlds"):
        assert f"/console#{view}" in page.links, (name, view)
    console = (ROOT / "site/console/console.js").read_text()
    for link in page.links:
        if link.startswith("/console#"):
            view = urlsplit(link).fragment
            assert f'id: "{view}"' in console or f"{view}: {{" in console


@pytest.mark.parametrize("name", ["site/index.html", "site/home/index.html"])
def test_homepage_local_resources_and_section_links_resolve(name):
    path = ROOT / name
    page = PageLinks()
    page.feed(path.read_text())
    tracked = {"/site/theme.js", "/site/city-lab.css", "/site/home/style.css", "/site/home/app.js"}
    assert tracked <= page.assets
    for url in page.assets | page.links:
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or parsed.path == "/console":
            continue
        if not parsed.path:
            assert parsed.fragment in page.ids, url
        else:
            served_path = page_target(parsed.path) or (
                "/site/auth/index.html" if parsed.path in {"/login", "/join", "/reset"} else parsed.path
            )
            target = (
                ROOT / served_path.lstrip("/") if served_path.startswith("/") else path.parent / served_path
            )
            assert target.exists(), url


def test_homepage_manual_is_an_allowed_download():
    for name in ("site/index.html", "site/home/index.html"):
        page = PageLinks()
        page.feed((ROOT / name).read_text())
        assert "/read.doc" in page.links
    assert (ROOT / "read.doc").is_file()
    assert _static_path_allowed("/read.doc")
    assert not _static_path_allowed("/dashboard_config.json")


def test_legacy_feature_hashes_still_open_the_console():
    result = subprocess.run(
        [
            "node",
            "-e",
            r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync('site/home/app.js', 'utf8');
for (const hash of ['#studio', '#settings', '#dashboard', '#worlds', '#platform', '#research', '#unknown', '']) {
  let destination;
  const location = { hash, search: '?from=legacy', replace: value => { destination = value; } };
  const context = { window: { location }, localStorage: { getItem: () => null },
    document: { querySelectorAll() { throw new Error('continue landing'); } } };
  try { vm.runInNewContext(source, context); }
  catch (error) { assert.equal(error.message, 'continue landing'); }
  if (['#studio', '#settings', '#dashboard', '#worlds'].includes(hash)) {
    assert.equal(destination, '/console?from=legacy' + hash);
  } else { assert.equal(destination, undefined); }
}
""",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
