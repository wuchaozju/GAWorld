"""Second pass: capture the real simulation console (/dashboard) in several states.

The console is a single page with collapsible panels and an agent selector, so
these shots need interaction, not just a URL.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8766"
OUT = Path(__file__).resolve().parents[1] / "images"
OUT.mkdir(parents=True, exist_ok=True)


def shoot(page, name: str, full: bool = False) -> None:
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=full)
    print(f"OK   {name}  {path.stat().st_size // 1024} KB")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb"])
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1.5,
            locale="zh-CN",
        )
        page = context.new_page()

        # 1) console as it opens: toolbar + map + profile
        page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(3000)
        shoot(page, "34-console-overview")

        # 2) toolbar zoom: the run configuration every first-time user touches
        toolbar = page.locator("section.toolbar")
        if toolbar.count():
            toolbar.screenshot(path=str(OUT / "35-console-toolbar.png"))
            print("OK   35-console-toolbar")
        page.locator("section.toolbar").scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        shoot(page, "36-console-toolbar-context")

        # 3) pick a resident so the profile / family / home panels fill in
        try:
            select = page.locator("#agentSelect")
            options = select.locator("option")
            if options.count() > 1:
                value = options.nth(1).get_attribute("value")
                select.select_option(value)
                page.wait_for_timeout(3500)
                shoot(page, "37-console-agent-selected")
        except Exception as error:  # noqa: BLE001
            print(f"agent select failed: {str(error)[:120]}")

        # 4) expand every collapsed panel (memory, logs, family, collaboration…)
        try:
            page.evaluate(
                """() => {
                    document.querySelectorAll('.panel.collapsible.is-collapsed')
                        .forEach((p) => p.classList.remove('is-collapsed'));
                }"""
            )
            page.wait_for_timeout(1800)
            shoot(page, "38-console-panels-expanded")
        except Exception as error:  # noqa: BLE001
            print(f"expand failed: {str(error)[:120]}")

        # 5) the configuration centre (#settings hash on the console)
        page.goto(f"{BASE}/dashboard#settings", wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(2500)
        shoot(page, "39-console-settings")

        # 6) the run/history section of the console
        page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(2500)
        try:
            page.evaluate(
                """() => {
                    const el = document.querySelector('#agentLogView, #episodesView');
                    if (el) el.scrollIntoView({block: 'center'});
                }"""
            )
            page.wait_for_timeout(800)
            shoot(page, "40-console-memory")
        except Exception as error:  # noqa: BLE001
            print(f"memory shot failed: {str(error)[:120]}")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
