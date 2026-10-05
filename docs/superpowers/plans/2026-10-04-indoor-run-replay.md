# Indoor Run and Replay Implementation Plan

**Goal:** Add the approved pixel indoor mode to live simulation and results replay.

**Architecture:** Reuse IndoorScene with an instance-owned trace/frame state and an embedded renderer API. IndoorView owns building selection, city/indoor switching and zoom controls. Both pages supply their existing frame; no polling, simulation or iframe is started by the renderer.

**Tech Stack:** JavaScript, local Phaser 3, Node VM tests, pytest.

- [x] Add failing tests to tests/indoor-pixel.test.js for embedded initialization, independent frame state, building/run changes and empty frames; add an IndoorView UI harness for mode and building controls.
- [x] Modify site/simviz/phaser-app.js: isolate IndoorScene state and expose createIndoorRenderer(host). Load with data-indoor-only on consuming pages so the village app never boots there.
- [x] Replace IndoorView canvas drawing with the shared renderer. Keep automatic resident following and pinned building selection; add zoom and a clear empty state.
- [x] Add city/indoor buttons in site/dashboard/index.html and site/simviz/index.html; show one scene at a time in their existing panels. Preserve live latest-frame and replay timeline behavior. Clear stale replay state when runs disappear.
- [x] Run Node frontend checks, related pytest and core suite; inspect both pages with demonstration frames on desktop and phone and save actual screenshots.

Execute in this chat without automatic commits. Preserve unrelated working-tree changes. The user explicitly requested this integration of the already approved indoor design.

## Verification

- Node scene, embedded state, mode selection, replay synchronization and existing indoor/replay helpers: 33 checks passed. Building id/label aliases count the same residents; travellers remain excluded.
- Related pytest: 45 passed, 1 cosmetic i18n-order skip, 82 subtests passed.
- Core suite: 471 passed, 1 optional-validator skip, 669 subtests passed (existing font warnings). Later clearing/alias fixes were verified with focused Node and pytest checks.
- Spatial tree: no failures. Scoped whitespace and Python Ruff checks passed.
- Reviewer found one P2: city trace retained old data when clearing a run. Both renderers now receive null and the regression check passes. No other actionable findings.
- Browser checked actual existing London trace (37 frames), without launching a simulation: both pages show shared pixel rooms, building pinning and zoom. Replay frame scrubbing and resident following checked; viewport 390px has no horizontal overflow, and its playback controls stay visible. Browser console contains no warnings/errors.
- Screenshots: output/visualization/indoor-pixel-review/integration/run-desktop.jpg, run-mobile.jpg, replay-desktop.jpg, replay-mobile.jpg. Desktop captures include the city/indoor mode controls; phone replay includes playback controls.
