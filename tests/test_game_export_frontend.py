from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "site" / "dashboard"
GAMES = ["persuade", "disaster", "rumor", "duel", "referendum", "guess", "arena", "novel"]


def test_game_export_node_suite():
    result = subprocess.run(
        ["node", "--test", str(DASHBOARD / "game-export.test.js")],
        cwd=ROOT, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_game_page_mounts_the_export_button_and_script():
    for game in GAMES:
        html = (DASHBOARD / f"{game}.html").read_text(encoding="utf-8")
        assert 'id="gameExportBtn"' in html, game
        assert html.index("game-export.js") < html.index(f"/site/dashboard/{game}.js"), game
