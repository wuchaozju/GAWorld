# Website navigation implementation plan

**Goal:** Implement the approved homepage and console layout design in this checkout.

**Architecture:** Keep the existing static pages, theme tokens, translation systems and iframe routes. Home uses a single responsive navigation panel and a desktop disclosure for auxiliary actions. Console uses a tool disclosure, compact world context and a keyboard-accessible mobile drawer.

**Tech stack:** HTML, CSS, vanilla JavaScript, pytest and the existing Python Playwright browser fixture.

## 1. Establish interaction regressions

- [x] Extend `tests/test_landing_browser.py` with mobile entry visibility, homepage menu focus/Escape/resize, console drawer focus isolation, tool disclosure and route persistence tests. Stub console API responses and child documents to avoid changing application data.
- [x] Run `python -m pytest tests/test_landing_browser.py -q`; confirm the new assertions fail on the old interface.
- [x] Save desktop and mobile screenshots under `output/playwright/navigation-2026-11-13/` before editing.

## 2. Homepage layout

- [x] Update the matching headers in `site/index.html` and `site/home/index.html`: main navigation, visible lab entry, desktop login and a native details disclosure containing theme, language, GitHub and registration.
- [x] Adapt menu handling in `site/home/app.js`: open focus, Escape, outside click, link activation, keyboard containment on mobile and breakpoint cleanup. Preserve existing animation and translation logic.
- [x] Replace obsolete header rules in `site/home/style.css`; align section gutters, make navigation targets comfortable to tap and preserve the feature grid's responsive columns.

## 3. Console layout

- [x] Move theme, language, account and standalone-window actions into a native details disclosure in `site/console/index.html`; keep world controls separate.
- [x] Refine `site/console/console.css`: current-page breadcrumb, compact single-language sidebar, selected marker, mobile context row and bounded tool panel. Remove obsolete console overrides from `site/city-lab.css`.
- [x] Update `site/console/console.js`: mobile sidebar inert when closed, focus visible active tab when opened, isolate background, cycle keyboard focus, restore trigger on close and clear state across breakpoints.
- [x] Add matching translation keys in `site/dashboard/locales/zh-CN.json` and `en.json`. Preserve permissions, world switching, legacy hash aliases and loaded frames.

## 4. Verify and review

- [x] Run focused homepage/browser/navigation/locale regressions and the core suite; check JavaScript syntax and `git diff --check`.
- [x] Verify 1440/1024/768/390/320px in both themes and languages, including long account/world names and account/admin visibility.
- [x] Inspect before/after screenshots, resolve navigation and layout findings, and request an independent code review using the requesting-code-review skill.
- [x] Record actual checks and limitations in `docs/reports/2026-11-13-site-navigation.md`. Leave changes uncommitted for user review.

## Completion

Implemented and reviewed on 2026-11-13. See `docs/reports/2026-11-13-site-navigation.md` for actual test results, screenshots and pre-existing suite failures. No commit or deployment was made.
