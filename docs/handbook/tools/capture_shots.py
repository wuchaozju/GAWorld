"""Capture real dashboard screenshots for the GAWorld teaching handbook.

Run with the dashboard already serving on http://127.0.0.1:8766.
Every shot lands in docs/handbook/images/ with a stable, content-based name.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8766"
OUT = Path(__file__).resolve().parents[1] / "images"
OUT.mkdir(parents=True, exist_ok=True)

# name -> (url, extra wait selector or None, full page?)
SHOTS: list[tuple[str, str, str | None, bool]] = [
    ("01-dashboard-home", "/", None, False),
    ("02-dashboard-config", "/#config", "#config", False),
    ("03-dashboard-run", "/#run", "#run", False),
    ("04-dashboard-observe", "/#observe", "#observe", False),
    ("05-agent-studio", "/site/dashboard/studio.html", None, False),
    ("06-city-lab", "/site/dashboard/city.html", None, False),
    ("07-city-map", "/site/citymap/index.html", None, False),
    ("08-games-hub", "/site/dashboard/games.html", None, False),
    ("09-game-persuade", "/site/dashboard/persuade.html", None, False),
    ("10-game-warzone", "/site/dashboard/warzone.html", None, False),
    ("11-game-rumor", "/site/dashboard/rumor.html", None, False),
    ("12-game-disaster", "/site/dashboard/disaster.html", None, False),
    ("13-game-referendum", "/site/dashboard/referendum.html", None, False),
    ("14-game-timeslip", "/site/dashboard/timeslip.html", None, False),
    ("15-game-roommate", "/site/dashboard/roommate.html", None, False),
    ("16-survey", "/site/dashboard/survey.html", None, False),
    ("17-research", "/site/dashboard/research.html", None, False),
    ("18-research-plan", "/site/dashboard/research.html?tab=plan", None, False),
    ("19-research-policy", "/site/dashboard/research.html?tab=policy", None, False),
    ("20-research-replication", "/site/dashboard/research.html?tab=replication", None, False),
    ("21-research-serious", "/site/dashboard/research.html?tab=games", None, False),
    ("22-parallel-worlds", "/site/dashboard/worlds.html", None, False),
    ("23-play", "/site/dashboard/play.html", None, False),
    ("24-collaboration", "/site/dashboard/collaboration.html", None, False),
    ("25-analytics", "/site/dashboard/analytics.html", None, False),
    ("26-organizations", "/site/dashboard/organizations.html", None, False),
    ("27-population", "/site/dashboard/population.html", None, False),
    ("28-external", "/site/dashboard/external.html", None, False),
    ("29-settings", "/site/dashboard/settings.html", None, False),
    ("30-docs-panel", "/site/dashboard/docs.html", None, False),
    ("31-console", "/site/console/index.html", None, False),
    ("32-simviz", "/site/simviz/index.html", None, False),
    ("33-home", "/site/index.html", None, False),
]


def main() -> int:
    failures: list[tuple[str, str]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb"])
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1.5,
            locale="zh-CN",
        )
        page = context.new_page()
        page.on("pageerror", lambda e: None)

        for name, url, wait_for, full in SHOTS:
            target = BASE + url
            try:
                page.goto(target, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(1800)
                if wait_for:
                    try:
                        page.wait_for_selector(wait_for, timeout=4000)
                    except Exception:
                        pass
                page.wait_for_timeout(600)
                path = OUT / f"{name}.png"
                page.screenshot(path=str(path), full_page=full)
                print(f"OK   {name}  {path.stat().st_size // 1024} KB")
            except Exception as error:  # noqa: BLE001 - report and continue
                failures.append((name, str(error)[:160]))
                print(f"FAIL {name}: {str(error)[:160]}")
            time.sleep(0.4)

        browser.close()

    print(f"\ndone: {len(SHOTS) - len(failures)}/{len(SHOTS)} captured")
    if failures:
        print("failures:", failures)
    return 0


if __name__ == "__main__":
    sys.exit(main())
