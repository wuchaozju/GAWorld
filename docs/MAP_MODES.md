# Map modes: virtual vs. real

GAWorld's city map supports two interchangeable modes. Both build the **same**
`city_map` structure, so routing, distance, transport, spatial queries, agent
location inference, and the visualizer all work identically — the only
difference is where the geography comes from.

> Looking to set up a **different city** rather than understand the two modes?
> Go to the [city tutorial](CITY_TUTORIAL.md) — `python -m gaworld.city create "<place name>"`
> builds a bundle in either mode for you and wires the config up. This page is the
> layer underneath that.

| | `virtual` (default) | `real` |
|---|---|---|
| Source | Procedural spec `data/citymap.md` | Real OSM bundle, e.g. `data/hangzhou_real.geojson` |
| Coordinates | Synthetic grid → projected to fake lat/lng around Hangzhou | True WGS-84 lat/lng from OpenStreetMap |
| Nodes | Hand-authored hubs + generated blocks | Real districts (街道), metro stations, hospitals, universities, malls, parks, government |
| Roads | Generated MST + loops | Hierarchical network synthesized over real node positions |
| Metro / river | Declared lines, or none | Real metro lines + real river polyline |
| Offline / reproducible | Yes | Yes (bundle is a committed file) |

> **Metro defaults changed.** A spec that uses `@` directives now declares its
> transit explicitly: no `@metro` line means the place genuinely has none. This
> stops a generated village from inheriting a subway and skewing
> `choose_transport_mode` and fares. Legacy specs with *no* `@` directives at all
> (e.g. `data/testcitymap.md`) still fall back to the sample lines.

## Switching modes

Set `map_mode` in your config (defaults live in
[`gaworld/settings/runtime.py`](../gaworld/settings/runtime.py)):

```jsonc
{
  "map_mode": "real",                          // "virtual" | "real"
  "real_map_path": "data/hangzhou_real.geojson"
}
```

Every map load in the simulation routes through `load_city_map` /
`load_city_map_text` in `generative_city_sim.py`, which dispatch on `map_mode`,
so switching is config-only — no code changes.

## Regenerating the real bundle

The bundle is derived from OpenStreetMap via the Overpass API and committed for
offline runs. To refresh it (requires network):

```bash
python3 scripts/dev/fetch_hangzhou_osm.py            # → data/hangzhou_real.geojson
# custom area: --bbox south,west,north,east
python3 scripts/dev/fetch_hangzhou_osm.py --bbox 30.14,119.98,30.40,120.35
```

The fetcher is deliberately **coarse** (a few hundred landmark nodes, not every
building) to match the simulation's abstraction level. It rotates across public
Overpass mirrors and backs off on rate limits; metro reconstruction is
best-effort and non-fatal.

For **any other place**, use the city layer instead of this Hangzhou-specific
script — it geocodes the name, derives the bbox, writes the projection anchor,
and falls back to a procedural map when OSM is unreachable:

```bash
python -m gaworld.city create "绍兴柯桥"    # → data/cities/绍兴柯桥/map.geojson
```

Its Overpass client (`gaworld/city/osm.py`) is the generalised version of this
script: it pins whichever mirror answered last and caps the whole fetch with a
wall-clock deadline, because `urlopen`'s timeout is per socket operation and a
trickling mirror otherwise runs far past it.

## Bundle format

A GeoJSON `FeatureCollection` (same schema as `city_map.export_geojson`, plus a
few properties). `load_real_city_map` parses:

- **Point** features → nodes. `properties`: `name`, `category`, `kind`
  (`hub`/`place`), optional `district`.
- **LineString** `properties.kind="metro"` → a metro line: `line`, `color`,
  ordered `stops` (names matching Point nodes).
- **LineString** `properties.kind="river"` → the river: `name`, `width_km`.
- **LineString** `properties.kind="road"` → an explicit road edge
  (`source`/`target` node names). Omitted edges are auto-generated.
- `meta.city` → the city's name, used in the LLM prompt header.
- `meta.origin` → **the projection anchor** (see below). Optional; omitting it
  keeps the historical Hangzhou projection.

Any bundle in this format works, so the real-map mode is not Hangzhou-specific —
point the fetcher (or a hand-authored GeoJSON) at another city and it loads the
same way. `python -m gaworld.city create "<place name>"` does exactly this and
writes the anchor for you.

## The projection anchor (`meta.origin`)

The module constants in `gaworld/world/city_map.py` are calibrated for Hangzhou
(~30°N), where one degree of longitude is ~96 km. Longitude degrees shrink as
`cos(latitude)`, so reusing those constants elsewhere distorts **east-west**
distances — at Paris (48.86°N) they come out **31% too large**, which feeds
straight into travel time and fares.

A bundle can therefore carry its own anchor:

```json
{
  "meta": {
    "city": "柯桥区",
    "origin": {
      "lat": 30.084796, "lng": 120.490807,
      "lat_per_km": 0.009009009, "lng_per_km": 0.010381686
    }
  }
}
```

`lng_per_km` is `1 / (111.32 · cos(lat))`. Both the forward and inverse
projections honour it, so a node's recomputed lat/lng still round-trips to its
true value. Bundles without `meta.origin` are unaffected.

## Rendering in the viewer

The Phaser viewer at [`site/citymap/`](../site/citymap) renders whichever map
you feed it. Regenerate its data from the real map:

```bash
python3 scripts/dev/real_citymap_viz.py    # → data/citymap_real_visualization.json (+ .geojson)
```

Then load `data/citymap_real_visualization.json` in `site/citymap/viewer.html`
(载入地图 JSON). The virtual map's committed exports are left untouched.
