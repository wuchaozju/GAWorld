# GAWorld B Logo Web Integration

**Goal:** Apply the user-selected green emergent-society logo to the existing Web interfaces.

**Architecture:** Keep the approved emblem as a transparent PNG in `site/assets/logo-emergent.png`. Replace existing GA tiles with an image and real text, share styles through `site/brand.css`, and retain each page's existing layout. Every standalone GAWorld HTML page uses the same favicon. Dark backgrounds use a white silhouette.

**Tech stack:** Static HTML/CSS, existing Python dashboard, pytest, Playwright CLI.

- [x] Inspect current page shells and existing uncommitted changes.
- [x] Generate an isolated transparent emblem from the approved B preview using built-in imagegen.
- [x] Add asset-resolution, transparency and page-integration tests; verify failure before integration.
- [x] Save the PNG, replace old brand marks and favicon links, and apply shared sizing and dark-background styles.
- [x] Ensure the login page can load the public logo without authentication.
- [x] Run targeted tests and the required core suite; inspect desktop/mobile pages in light/dark modes.

The user authorized integration in this chat. Work is performed inline, preserving unrelated changes; no simulation or model experiment is started.

## Verification

- Core suite: 471 passed, 1 skipped (optional OpenAPI validator missing), 669 subtests passed. Existing CJK font warnings remain.
- Targeted brand/theme/resources/accounts checks pass. The shared resource test now resolves URL paths before checking local files, allowing existing CSS version query parameters.
- Live homepage, console and standalone research page load the emblem. The homepage and console were checked at 390px with no horizontal overflow. Dark mode uses a white silhouette.
- Browser evidence is saved under `output/playwright/logo-*.png`.
