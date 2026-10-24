# Dashboard community integration

**Goal:** Integrate personal workspaces and community collaboration into the existing `/console` Dashboard, as requested by the user.

**Architecture:** Reuse the persistent iframe shell and sidebar. A shared pure navigation module maps old URLs to console hashes, preserves research/publication deep links, and restricts frame targets to known pages. Embedded community pages hide their standalone navigation and inherit the Dashboard visual conventions. Anonymous public pages remain shareable. World changes reload the shell and all panels, preserving ownership and request context.

**Tech stack:** Existing Python HTTP server, vanilla JS/CSS, Node test runner, pytest, agent-browser. No model runs.

- [x] Add failing navigation tests for old workspace URLs, research details, publication versions, safe targets and legacy world alias; run `node --test site/community/navigation.test.js`.
- [x] Implement `site/community/navigation.js`; integrate route resolution and account-aware sidebars in `site/console/index.html` and `console.js`.
- [x] Integrate community pages via `common.js`, embedded CSS, logical navigation, old-link redirects and full-shell world changes. Point research publishing and auth defaults to the console.
- [x] Run JS tests, HTTP community/auth/mode regressions, core suite and changed-file lint checks. Test logged-in workspace → research → publication → discussion and guest public/private behavior in a real browser; inspect mobile and dark mode.
- [x] Request independent review, fix findings, update `docs/COMMUNITY.md` and a verification report. Preserve unrelated organization-intelligence changes and user data. No commit or deployment requested.
