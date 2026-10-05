# City Lab appearance implementation plan

**Goal:** Apply the approved City Lab design to GAWorld's website, with persistent light and dark modes.

**Architecture:** Keep the existing HTML, navigation, API calls and rendering. A small shared script sets the appearance before paint, mounts two accessible controls on standalone pages, and synchronizes the console's same-origin frames. Shared tokens and a final stylesheet supply the warm paper, ink, orange accents and editorial hierarchy in both modes.

**Tech stack:** Existing vanilla HTML/CSS/JavaScript, Node test runner, pytest, native browser verification. Execute inline in this chat; preserve the current uncommitted work.

- [x] Add failing behavioral tests for saved mode, invalid preferences, unavailable storage, frame synchronization, and rejection of foreign-origin messages in `site/theme.test.js`. Add asset loading/order coverage in `tests/test_theme_frontend.py`; retain the existing public-resource tests.
- [x] Implement `site/theme.js`. Use `gaworld-theme` for storage; accept only `light` and `dark`; default to light. Expose `GAWorldTheme.set/get`. Apply `data-theme` in the head, mount a two-button appearance group after DOM readiness, translate labels on locale changes, and synchronize frames without message loops.
- [x] Update `site/tokens.css` and add `site/city-lab.css`. Keep complete light/dark palettes, readable forms and results, orange brand emphasis, dark ink navigation, strong typography, small corners, reduced motion, and responsive navigation. Use mode-specific tokens instead of filtering the page.
- [x] Load the script before styles and the City Lab sheet after page styles on the landing page, console, dashboard pages, and replay. Preserve all existing page scripts and control IDs.
- [x] Refine the real landing page's hero and add a City Lab schematic SVG, console shell, dashboard and research headers to match the selected preview. Use real content; add no fabricated run statistics.
- [x] Run `node --test site/theme.test.js`, relevant frontend/API resource tests, and `pytest --suite core`. Inspect the real landing page, embedded research/dashboard, and representative secondary pages in both modes; verify persistence, frame synchronization, keyboard controls and 390px layout. Record any unrelated baseline failure separately.

The user's selection of City Lab with two modes approves this scope. No further design approval is needed. Simulation configuration and comparability epochs are unaffected.

## Validation

- Shared controller: 11 Node tests passed, including saved mode, blocked storage, late iframe requests, origin checks, loop prevention, header mounting, accessible selected state and translated labels.
- Theme / public resources / i18n / analytics: 59 passed, 1 existing cosmetic skip, 88 subtests passed.
- Core: 462 passed, 1 skip (optional openapi-spec-validator unavailable), 667 subtests passed.
- New Python test passes Ruff; all dashboard CSS and shared CSS parse without errors; atlas SVG parses as XML.
- Native browser: actual home, dashboard, research, analytics and replay checked; both modes, persistence after reload, iframe and cross-tab sync, Enter activation and English labels verified. Home and embedded research have no horizontal overflow at 390px. Chart labels inherit the dark palette without fetching/redrawing data.
- Screenshots: `.superpowers/city-lab-delivery/`. Existing map/indoor renderer assets keep their own cartographic/illustration palettes.
