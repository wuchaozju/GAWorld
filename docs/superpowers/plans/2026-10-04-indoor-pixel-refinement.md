# Indoor Pixel Refinement Implementation Plan

**Goal:** Restore and refine the approved indoor pixel view with readable room layouts, detailed furniture and full-body residents.

**Architecture:** Keep the existing Phaser scene and spatial-tree data source. Fit world geometry within the canvas, paint sorted objects on a shared graphics layer, and draw deterministic pixel characters from activity and resident id.

**Tech Stack:** Plain JavaScript, Phaser 3, Node test runner, pytest.

- [x] Add a Node VM regression harness in `tests/indoor-pixel.test.js`, using the real scene and spatial tree with a recording Graphics adapter. Verify indoor room labels and finite geometry; run `node --test tests/indoor-pixel.test.js` and observe the blank-scene regression.
- [x] Repair the scene bounds and fit in `site/simviz/phaser-app.js`; replace the name reduction with room-coordinate reduction, use a shared depth-sorted graphics layer, generate shared partitions once and keep low front walls. Re-run scene tests.
- [x] Refine existing room furniture kits and residential room proportions in `site/simviz/spatial-tree.js`; preserve normalized geometry and activity slots. Run `node site/simviz/spatial-tree.test.js`.
- [x] Replace uniform furniture boxes with components: beds, sofas, tables and chairs, desks, shelves, appliances and plants. Add plank seams, rugs, windows and tile details. Replace floating character shapes with connected pixel silhouettes and activity poses.
- [x] Run the Node scene tests, existing indoor/spatial/replay tests and pytest core suite. Check actual residential and public interiors, a populated deterministic fixture, desktop and narrow canvas dimensions in the browser; save a final screenshot.

Execution stays in this chat. Existing unrelated working-tree edits are preserved; no automatic commit or simulation run.

## Verification

- `node --test tests/indoor-pixel.test.js`: 12 passed, including blank-scene regression, six building categories, fitted bounds, depth layer, activity positioning, grounded pixel body, paused stability, zoom reset, visible study chair, rear-wall order and seated pelvis alignment.
- `node --test site/dashboard/indoor-view.test.js site/simviz/replay.test.js`: 13 passed.
- `node site/simviz/spatial-tree.test.js`: no failures.
- `python -m pytest tests/test_indoor_pixel_frontend.py tests/test_replay_runs.py -q`: 9 passed.
- `python -m pytest --suite core -q`: 462 passed, 1 skipped (optional openapi-spec-validator absent), 667 subtests passed; existing chart font warnings.
- Python Ruff and scoped Git whitespace checks passed.
- Browser verification at 1440x1000 and 390x844: actual furniture and four resident poses render; zoom/drag/reset work; console has no warnings/errors; narrow page scrollWidth is 390. Phone interior height is 360 CSS pixels and labels appear after zooming to avoid overview overlap.
- Preview uses explicitly labelled artwork demonstration data in `output/visualization/indoor-pixel-demo.json`, not simulation output. Real screenshot and phone screenshots are in `output/visualization/indoor-pixel-review/`.
