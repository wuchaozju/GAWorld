from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "site" / "dashboard"
LOCALE_PATH = DASHBOARD / "locales" / "zh-CN.json"
EN_LOCALE_PATH = DASHBOARD / "locales" / "en.json"


def _locale() -> dict:
    return json.loads(LOCALE_PATH.read_text(encoding="utf-8"))


def test_crowdsourcing_core_node_suite():
    result = subprocess.run(
        [
            "node",
            "--test",
            str(DASHBOARD / "crowdsourcing-core.test.js"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_the_page_hosts_both_collaboration_panes():
    html = (DASHBOARD / "collaboration.html").read_text(encoding="utf-8")

    assert 'id="paneSimple"' in html
    assert 'id="paneCrowd"' in html
    assert 'data-pane="simple"' in html
    assert 'data-pane="crowd"' in html
    assert 'role="tablist"' in html
    # The old observatory is kept, only renamed.
    assert 'data-i18n="collab.headline">简单协作任务' in html


def test_the_crowd_pane_carries_every_control_the_controller_needs():
    html = (DASHBOARD / "collaboration.html").read_text(encoding="utf-8")
    source = (DASHBOARD / "crowdsourcing.js").read_text(encoding="utf-8")

    for element_id in (
        "crowdTaskInput",
        "crowdCriteriaInput",
        "crowdStrategyGrid",
        "crowdPoolGrid",
        "crowdPoolSearch",
        "crowdPoolAll",
        "crowdPoolRandom",
        "crowdPoolClear",
        "crowdPoolCount",
        "crowdRounds",
        "crowdParticipants",
        "crowdKeep",
        "crowdPruneEnabled",
        "crowdStartBtn",
        "crowdFormStatus",
        "crowdSessionList",
        "crowdRefreshSessionsBtn",
        "crowdSessionCode",
        "crowdActiveTitle",
        "crowdPauseBtn",
        "crowdResumeBtn",
        "crowdCancelBtn",
        "crowdProgressText",
        "crowdProgressBar",
        "crowdRoundStrip",
        "crowdBidTable",
        "crowdClearingPrice",
        "crowdAttemptList",
        "crowdAgreement",
        "crowdLeaderboard",
        "crowdSurvivorCount",
        "crowdActivityFeed",
        "crowdEventCursor",
        "crowdFinalAnswer",
        "crowdArtifactList",
        "crowdCallCount",
        "crowdStatus",
        "crowdCostEstimate",
        "crowdPoolNote",
    ):
        assert f'id="{element_id}"' in html, element_id
        assert element_id in source, element_id


def test_the_pane_switcher_is_docked_in_the_masthead():
    """The switcher belongs to the header band.

    It used to sit above the masthead with no stylesheet at all, which left
    the browser's own button chrome floating over the top of the page.
    """
    html = (DASHBOARD / "collaboration.html").read_text(encoding="utf-8")

    masthead = html.index('<header class="masthead">')
    switcher = html.index('id="viewTabs"')
    assert masthead < switcher < html.index("</header>"), (
        "the pane switcher has to live inside the masthead band"
    )

    css = (DASHBOARD / "collaboration.css").read_text(encoding="utf-8")
    assert ".view-tabs {" in css, "the switcher needs its own rules"
    assert ".view-tab {" in css, "the switcher buttons need their own rules"


def test_the_shared_masthead_follows_the_active_pane():
    """Both panes bring a headline; the masthead shows the active one."""
    html = (DASHBOARD / "collaboration.html").read_text(encoding="utf-8")

    assert 'data-pane-set="simple"' in html
    assert 'data-pane-set="crowd"' in html

    source = (DASHBOARD / "collaboration.js").read_text(encoding="utf-8")
    assert "[data-pane-set]" in source, (
        "the pane switch has to hide the headline that belongs to the other pane"
    )


def test_the_crowd_scripts_load_after_the_shared_helpers():
    html = (DASHBOARD / "collaboration.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)

    i18n_index = scripts.index("/site/dashboard/i18n.js")
    core_index = scripts.index("/site/dashboard/crowdsourcing-core.js")
    page_index = scripts.index("/site/dashboard/crowdsourcing.js")

    assert i18n_index < core_index < page_index


def test_the_crowd_controller_never_writes_html():
    source = (DASHBOARD / "crowdsourcing.js").read_text(encoding="utf-8")

    assert "innerHTML" not in source
    assert "outerHTML" not in source
    assert "insertAdjacentHTML" not in source


def test_the_crowd_core_stays_free_of_the_browser():
    source = (DASHBOARD / "crowdsourcing-core.js").read_text(encoding="utf-8")

    assert "innerHTML" not in source
    # The module has to load in Node for the unit tests, so it may not reach
    # for a browser global at module scope.
    assert not re.search(r"\b(document|window)\.", source)


def test_the_crowd_controller_calls_the_documented_endpoints():
    source = (DASHBOARD / "crowdsourcing.js").read_text(encoding="utf-8")

    assert "/api/crowdsourcing/strategies" in source
    assert '"/api/crowdsourcing/sessions"' in source
    assert '"/api/crowdsourcing/sessions/" + sessionId' in source
    assert "/rounds" in source
    assert "/events?after=" in source


def test_every_crowd_i18n_key_the_controller_uses_is_translated():
    source = (DASHBOARD / "crowdsourcing.js").read_text(encoding="utf-8")
    locale = _locale()
    english = json.loads(EN_LOCALE_PATH.read_text(encoding="utf-8"))

    keys = set(re.findall(r'"(crowd\.[A-Za-z0-9_]+)"', source))
    assert keys, "the controller should reference crowd.* keys"

    for key in sorted(keys):
        assert key in locale, f"{key} is missing from zh-CN.json"
        assert key in english, f"{key} is missing from en.json"
        assert locale[key], f"{key} is empty in zh-CN.json"


def test_the_collaboration_tabs_are_translated():
    locale = _locale()
    english = json.loads(EN_LOCALE_PATH.read_text(encoding="utf-8"))

    assert locale["collab.tab_simple"] == "简单协作任务"
    assert locale["collab.tab_crowd"] == "群体智能众包"
    assert locale["collab.headline"] == "简单协作任务"
    assert english["collab.tab_crowd"] == "Swarm crowdsourcing"


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", text))


def test_every_placeholder_is_actually_filled_in():
    """A locale string carrying a ``{placeholder}`` has to be rendered
    through ``__f`` with that name, otherwise the page shows the literal
    ``{n}`` to the reader."""
    locale = _locale()
    english = json.loads(EN_LOCALE_PATH.read_text(encoding="utf-8"))

    for name in ("crowdsourcing.js", "collaboration.js"):
        source = (DASHBOARD / name).read_text(encoding="utf-8")

        # t("key") -- rendered without parameters, so any placeholder in the
        # locale string would survive onto the page.
        for key in re.findall(r'(?<![A-Za-z_$])t\(\s*"([^"]+)"\s*\)', source):
            assert key in locale, f"{key} is missing from zh-CN.json"
            assert not _placeholders(locale[key]), (
                f'{name}: t("{key}") renders a placeholder the locale still holds: {locale[key]!r}'
            )

        # tf("key", {param: ...}) -- the parameter names have to line up with
        # the placeholders the locale string asks for.
        for key, params in re.findall(r'tf\(\s*"([^"]+)"\s*,\s*\{([^}]*)\}', source):
            assert key in locale, f"{key} is missing from zh-CN.json"
            assert key in english, f"{key} is missing from en.json"
            wanted = _placeholders(locale[key])
            given = set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*:", params))
            assert wanted == given, (
                f'{name}: tf("{key}") fills {sorted(given)} but the locale wants {sorted(wanted)}'
            )

    # The two locales must ask for the same placeholders.
    for key, value in locale.items():
        if not key.startswith(("crowd.", "collab.")):
            continue
        assert _placeholders(value) == _placeholders(english.get(key, "")), (
            f"{key} asks for different placeholders in zh-CN and en"
        )


def test_opening_a_finished_session_loads_its_rounds_and_events():
    """A completed run never polls, so the archive path has to fetch the
    rounds and the activity log itself -- otherwise opening a finished
    session from the archive shows an empty workspace."""
    source = (DASHBOARD / "crowdsourcing.js").read_text(encoding="utf-8")

    loader = re.search(
        r"async function loadSessionDetail\(candidate\) \{(.*?)\n    \}",
        source,
        re.S,
    )
    assert loader, "the controller should expose a session-detail loader"
    assert "document.hidden" not in loader.group(1), (
        "loading a session must not be gated on the tab being visible"
    )

    opener = re.search(r"function openSession\(session\) \{(.*?)\n    \}", source, re.S)
    assert opener, "the controller should expose an archive entry point"
    assert "loadSessionDetail(" in opener.group(1), (
        "opening a session from the archive must load its rounds and events"
    )
