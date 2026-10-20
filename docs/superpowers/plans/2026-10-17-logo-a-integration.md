# Logo A Integration Plan

**Goal:** Apply the selected logo across the website without changing feature behavior.

**Architecture:** Place the exact selected images under the existing public auth asset prefix and extend the existing shared `site/brand.css` stylesheet. Insert images into native brand slots; use CSS to adapt contrast and keep existing iframe behavior.

**Tech Stack:** HTML/CSS, PNG assets, pytest, Playwright.

- [x] Add failing regression tests for public selected-brand resources and their use on homepage, console, login and feature headers.
- [x] Copy the selected PNGs unchanged into `site/auth/brand/` and implement the shared sizing/contrast styles.
- [x] Update native brand slots and favicons, preserving page-specific titles and markup; keep login self-contained except for already-public brand resources.
- [x] Run brand, auth, theme and homepage tests. Verify real loaded images in desktop and mobile browser views, and run the core suite.
- [x] Record the result and leave source changes available for review.
