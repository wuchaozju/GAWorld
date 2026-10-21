"""Console sidebar navigation placement of the FOS tab.

RED phase (task 2773): the ``data-tab="fos"`` button currently lives in the
Analyze/分析 nav group (site/console/index.html ~L118). It belongs in the
Experiment/实验 group alongside collaboration/games/play/survey/external.
Parses the real HTML with html.parser — no raw string offsets.
"""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONSOLE_HTML = REPO_ROOT / "site" / "console" / "index.html"

EXPERIMENT_GROUP_TABS = {"collaboration", "games", "play", "survey", "external"}
ANALYZE_GROUP_TABS = {"analytics", "research"}


class _NavParser(HTMLParser):
    """Collects nav groups as lists of button data-tab values."""

    def __init__(self) -> None:
        super().__init__()
        self.groups: list[dict] = []  # {"label": str|None, "tabs": [str, ...]}
        self._group: dict | None = None
        self._in_button = False
        self._button_tab: str | None = None
        self._in_label = False
        self._label_buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section" and "nav-group" in (a.get("class") or ""):
            self._group = {"label": None, "tabs": []}
        elif tag == "h2" and "nav-group-label" in (a.get("class") or ""):
            self._in_label = True
            self._label_buf = []
        elif tag == "span" and self._in_label:
            if "en" not in (a.get("class") or ""):
                self._collect_span = True
        elif tag == "button" and self._group is not None and "tab" in (a.get("class") or ""):
            self._in_button = True
            self._button_tab = a.get("data-tab")
        elif tag == "span" and self._in_button:
            pass  # button inner content irrelevant

    def handle_data(self, data):
        if getattr(self, "_collect_span", False) and self._in_label:
            self._label_buf.append(data.strip())

    def handle_endtag(self, tag):
        if tag == "span" and getattr(self, "_collect_span", False):
            self._collect_span = False
        elif tag == "h2" and self._in_label:
            self._in_label = False
            if self._group is not None:
                self._group["label"] = "".join(self._label_buf).strip()
        elif tag == "button" and self._in_button:
            if self._button_tab is not None and self._group is not None:
                self._group["tabs"].append(self._button_tab)
            self._in_button = False
            self._button_tab = None
        elif tag == "section" and self._group is not None:
            self.groups.append(self._group)
            self._group = None


@pytest.fixture(scope="module")
def nav_groups():
    parser = _NavParser()
    parser.feed(CONSOLE_HTML.read_text(encoding="utf-8"))
    return parser.groups


def _group_containing(groups, tab):
    return [g for g in groups if tab in g["tabs"]]


class TestFosNavPlacement:
    def test_exactly_one_fos_button(self, nav_groups):
        hits = _group_containing(nav_groups, "fos")
        count = sum(g["tabs"].count("fos") for g in hits)
        assert count == 1, f"RED: expected exactly one data-tab='fos' button, found {count}"

    def test_fos_button_in_experiment_group(self, nav_groups):
        groups = _group_containing(nav_groups, "fos")
        assert groups, "RED: no data-tab='fos' button found at all"
        experiment_groups = [g for g in groups if EXPERIMENT_GROUP_TABS & set(g["tabs"])]
        assert experiment_groups, (
            "RED: data-tab='fos' is not inside the Experiment/实验 nav group "
            f"(groups containing fos: {[g['tabs'] for g in groups]})"
        )

    def test_fos_button_not_in_analyze_group(self, nav_groups):
        analyze_groups = [
            g for g in nav_groups if set(g["tabs"]) & ANALYZE_GROUP_TABS
        ]
        offenders = [g for g in analyze_groups if "fos" in g["tabs"]]
        assert not offenders, (
            "RED: data-tab='fos' still sits in the Analyze/分析 nav group "
            f"(analyze group tabs: {offenders[0]['tabs']})"
        )

    def test_experiment_group_labels(self, nav_groups):
        """Sanity: the group we require fos into is really the Experiment group."""
        exp = [g for g in nav_groups if EXPERIMENT_GROUP_TABS <= set(g["tabs"])]
        assert exp, "test bug: Experiment group (collaboration/games/play/survey/external) not found"


class TestFosNavLocaleKeys:
    @pytest.mark.parametrize("locale", ["en", "zh-CN"])
    def test_exactly_one_nav_fos_key(self, locale):
        path = REPO_ROOT / "site" / "dashboard" / "locales" / f"{locale}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        keys = [k for k in data if k == "nav.fos"]
        assert len(keys) == 1, f"RED: {locale}.json must have exactly one 'nav.fos' key"
