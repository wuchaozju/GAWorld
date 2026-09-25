# CityMap Viewer

Phaser 3 viewer for the enhanced `city_map` — smooth camera, baked terrain /
overlay / road textures, agent replay, and a pixel indoor mode.

## Open it

Just open **`viewer.html`** in any browser (double-click). Phaser and a sample
map are inlined, so it is fully self-contained and renders immediately — no
server, no sibling files.

The editable sources are `index.html` (shell + DOM panels), `app.src.js`
(Phaser scenes + logic), and `../vendor/phaser.min.js` (Phaser 3.90, vendored).
`build.py` inlines all three into `viewer.html`.

## Load your own data

Two buttons in the side panel:

- **载入地图 JSON** — a `build_visualization_payload(city_map)` dump
  (e.g. `data/citymap_visualization.json`), a raw `city_map`, a
  `simulation_trace.json` (its `map` is used), or a GeoJSON export.
- **载入轨迹** — a `simulation_trace.json` with `frames[]` for agent replay.

## Layers

Terrain tiles · land-use zoning · density gradient · roads (by class) ·
metro lines · river/bridges · styled place nodes · labels. Each is a separate
Phaser layer (terrain/overlays are baked to GPU textures once for speed).
Toggle independently; overlay opacity adjustable. Category chips filter nodes.
Scroll to zoom, drag to pan. Hover any node for its attributes.

## Replay

When a trace with frames is loaded, the bottom transport bar appears:
play/pause (`Space`), scrub, speed, `←/→` to step. Agents interpolate along
their `travel.route` by `progress`; click an agent in the side list to follow it.

## Indoor mode (pixel rooms)

**Double-click any node** to drop into a Smallville-style top-down pixel room:
plank/tile floor, gray pixel walls with a door gap and glass windows, grass
surround, and pixel furniture laid out by category (bed/kitchen/sofa for homes,
desks + chalkboard for schools, shelves + checkout for shops, beds + consult
desk for clinics, counters for cafés, trees + fountain for parks). Agents
present at that location (from the current trace frame) appear inside with a
`NAME: emoji` speech bubble and wander between furniture; sleepers lie down.
Double-click empty space or press `Esc` to return to the map.

## Regenerate

```bash
python3 scripts/dev/citymap_smoke.py   # virtual map → data/citymap_visualization.json + .geojson
python3 scripts/dev/real_citymap_viz.py # real Hangzhou (OSM) map → same outputs
python3 site/citymap/build.py          # inlines phaser + index.html + app.src.js + sample → viewer.html
```

The viewer renders whichever map you load — the procedural virtual map or the
real Hangzhou map (`map_mode="real"`). See [docs/MAP_MODES.md](../../docs/MAP_MODES.md).

Edit `index.html` (markup/CSS) or `app.src.js` (Phaser scenes), then re-run
`build.py`. `viewer.html` is the generated artifact — don't hand-edit it.

## Mapbox / MapLibre vector-basemap view (2026-09)

Two new pages, **no simulation impact**, layered on real vector tiles:

| Page | URL | What it is |
| --- | --- | --- |
| `mapbox.html` | `/site/citymap/mapbox.html` | Full-screen Mapbox/MapLibre view. Same nodes / edges / metro / river data, but drawn on top of a real basemap. |
| `compare.html` | `/site/citymap/compare.html` | Side-by-side: old Canvas view (left) vs new Mapbox view (right). The fastest way to see the difference. |

### Which engine runs?

- If the URL has `?token=pk.xxx...`, **`mapbox-gl-js`** runs against Mapbox's vector tiles.
- Otherwise, **`maplibre-gl`** + the public OpenFreeMap style runs (no token, no account).

Token is per-URL, never stored. It exists in the page only — Mapbox public
tokens are meant to be visible to the browser.

### What gets drawn

Layers (toggle from the side panel):

- **River** — water-blue polyline with soft blur, sits under everything.
- **Edges** — roads colored by class (arterial = warm yellow, collector = sky,
  local = muted slate). Local streets desaturate so arterials pop.
- **Metro** — line color from data, with a translucent glow underneath.
- **Nodes** — colored circles (color from `category_style`, radius from
  `density`). Click for popup (name / category / district / popularity).
- **Agents** — small dots positioned on each resident's home node with a
  tiny deterministic jitter. Click for popup (name / age / occupation / mood).
- **Labels** — POI names, sized by zoom.

### How to upgrade an existing city

The new view reads from `/api/city/map?city=<slug>` — same endpoint the old
view uses. Nothing in the simulation moves. For richer basemap detail, refresh
the OSM-derived `map.geojson`:

```bash
python3 scripts/dev/refresh_city_osm.py wuzhen   # overwrites data/cities/wuzhen/map.geojson
python3 scripts/dev/refresh_city_osm.py wuzhen --dry-run   # fetch but don't write
```

Requires an Overpass mirror to be reachable; the script rotates across three
public mirrors with the same retry/deadline discipline as `city create`.

### Files

- `site/citymap/mapbox.html` — page shell (HTML/CSS + loader).
- `site/citymap/mapbox.app.js` — `GAWorldMapView` class: source/layer setup,
  popups, side panel, theme/layer toggles. No build step.
- `site/citymap/compare.html` — side-by-side page. The "old" pane is a tiny
  inlined canvas renderer that mirrors `citymap-view.js`'s color scheme; the
  "new" pane is an iframe pointing at `mapbox.html`.
- `scripts/dev/refresh_city_osm.py` — operator script to retry/expand the
  OSM bundle for one city without recreating the bundle.
