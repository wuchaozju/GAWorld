/* Shared terrain-map renderer for GAWorld front-ends.
 *
 * One renderer, used by the Dashboard (控制台) map panel, the City tab
 * preview, and the Simulation replay (仿真回放) tab. Layers a real
 * vector basemap (Mapbox when a token is provided, MapLibre + the public
 * OpenFreeMap demo otherwise) with an HTML overlay for the trace-time
 * dynamic layer (agent avatars, movement trails, home ring, name pills).
 *
 *   const view = new CityMapView(canvas, { getSelectedAgentId: () => id });
 *   view.setTrace(trace);
 *   view.render(framesUpTo);   // framesUpTo = frames[0..current]; [] = base only
 *
 * Same external API as the legacy Canvas renderer so callers stay
 * untouched. Exposes window.CityMapView (no build step / modules).
 */
(function (global) {
  "use strict";

  const t = (key) => (typeof global.__ === "function" ? global.__(key) : key);

  const MAPBOX_DEFAULT_STYLE = "mapbox://styles/mapbox/dark-v11";
  const MAPBOX_LIGHT_STYLE = "mapbox://styles/mapbox/light-v11";
  const MAPLIBRE_DARK_STYLE = "https://tiles.openfreemap.org/styles/positron";
  const MAPLIBRE_LIGHT_STYLE = "https://tiles.openfreemap.org/styles/liberty";

  const CDN = {
    mapbox: "https://api.mapbox.com/mapbox-gl-js/v3.7.0/mapbox-gl.js",
    mapboxCss: "https://api.mapbox.com/mapbox-gl-js/v3.7.0/mapbox-gl.css",
    maplibre: "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js",
    maplibreCss: "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css",
  };

  const ROAD_TYPE_COLOR = {
    arterial: "#ffd166", collector: "#9bd1ff", road: "#9bd1ff",
    local: "#7a8aa0", bridge: "#ff9b6a",
  };
  const ROAD_TYPE_WIDTH = {
    arterial: 3.4, collector: 2.4, road: 2.0, local: 1.2, bridge: 2.6,
  };
  const agentColors = ["#13795b", "#b73e3e", "#385866", "#d6a81e", "#6e5f97", "#1f8a9b", "#8a5b30"];

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      if (document.querySelector(`script[src="${src}"]`)) return resolve();
      const s = document.createElement("script");
      s.src = src; s.async = true;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("failed to load " + src));
      document.head.appendChild(s);
    });
  }
  function loadCss(href) {
    return new Promise((resolve) => {
      if (document.querySelector(`link[href="${href}"]`)) return resolve();
      const link = document.createElement("link");
      link.rel = "stylesheet"; link.href = href; link.onload = () => resolve();
      document.head.appendChild(link);
    });
  }
  async function ensureMapLibre() {
    if (global.maplibregl) return global.maplibregl;
    await loadCss(CDN.maplibreCss);
    await loadScript(CDN.maplibre);
    return global.maplibregl;
  }
  async function ensureMapbox() {
    if (global.mapboxgl) return global.mapboxgl;
    await loadCss(CDN.mapboxCss);
    await loadScript(CDN.mapbox);
    return global.mapboxgl;
  }

  /* ============================================================
   * Helpers
   * ============================================================ */
  function num(v, fallback) {
    return (typeof v === "number" && Number.isFinite(v)) ? v : fallback;
  }
  function nodeLngLat(node) {
    if (!node) return null;
    if (typeof node.lng === "number" && typeof node.lat === "number") {
      return [node.lng, node.lat];
    }
    return null;
  }
  // Project (lng, lat) → screen (x, y) inside a container at the current
  // zoom. Returns null when the basemap is not yet ready.
  function projectToScreen(map, lng, lat) {
    if (!map) return null;
    try {
      const p = map.project([lng, lat]);
      return [p.x, p.y];
    } catch (e) { return null; }
  }
  function getNodeByName(nodesByName, name) {
    if (!name) return null;
    return nodesByName.get(String(name)) || nodesByName.get(String(name).trim()) || null;
  }

  /* ============================================================
   * Main class
   * ============================================================ */
  class CityMapView {
    constructor(canvas, opts) {
      opts = opts || {};
      this.canvas = canvas;
      // Backwards-compatible: callers do `new CityMapView(canvas, ...)`
      // expecting canvas to be the host. We replace it in-place with a
      // div container that holds the basemap + overlay.
      this._buildHost();
      // Public, mutable knobs (legacy callers may set avatarBase after).
      this.avatarBase = opts.avatarBase || "/output/visualization/";
      this.getSelectedAgentId = opts.getSelectedAgentId || (() => null);
      this.getSelectedAgentHome = opts.getSelectedAgentHome || (() => null);
      this.emptyText = opts.emptyText || (() => t("map.waiting_data"));
      this.trailFrames = opts.trailFrames || 96;
      this.token = this._resolveToken();
      this.theme = "dark";
      this.engine = null;
      this.map = null;
      this.trace = null;
      this.framesUpTo = [];
      this.layersInstalled = false;
      this.nodesByName = new Map();
      this.avatarCache = new Map();
      this._empty = true;
      this._setupInteractions();
      this._initMap();
    }

    _resolveToken() {
      // Look for ?token=pk.xxx in URL (added when users paste a token into
      // the dashboard's settings) or in localStorage (set by the mapbox
      // compare page). Either source works.
      const params = new URLSearchParams(location.search);
      const fromUrl = params.get("token");
      if (fromUrl) return fromUrl;
      try { return localStorage.getItem("gaworld.mapboxToken") || ""; }
      catch (e) { return ""; }
    }

    _buildHost() {
      const canvas = this.canvas;
      const host = document.createElement("div");
      host.className = "cmv-host";
      // The legacy renderer relied on the caller's #mapCanvas CSS
      // (width:100%; aspect-ratio:16/10) to size the slot. Carry those
      // visual properties over to host so the panel still grows to the
      // same rectangle as before — otherwise the flex parent collapses the
      // slot to header-only height.
      const ccs = getComputedStyle(canvas);
      const propsToCopy = ["display", "width", "height", "aspectRatio", "border",
                            "borderRadius", "boxSizing"];
      const baseStyle = propsToCopy
        .filter((p) => ccs[p] && ccs[p] !== "none" && ccs[p] !== "auto" && ccs[p] !== "")
        .map((p) => p + ":" + ccs[p])
        .join(";");
      host.style.cssText = [
        baseStyle,
        "position:relative",        // host itself is a normal block
        "overflow:hidden",          // clip the absolute Mapbox + overlay
        "background:#0c1118",
        // Default to a 16:10 box when the caller didn't pin a height: some
        // pages (e.g. the city tab) wrap canvas in a `.city-map-wrap` that
        // relies on the canvas's intrinsic aspect-ratio to size itself;
        // without this host collapses to zero height. The dashboard tab
        // already pins aspect-ratio via #mapCanvas so this is additive.
        "aspect-ratio:16/10",
      ].join(";").replace(/^;/, "");

      // Make the immediate parent a positioned, clipped container so any
      // absolute children of host stay inside its box. Callers frequently
      // leave the canvas wrapper as position:static — that let the old
      // absolute host escape its slot and cover the whole page.
      const parent = canvas.parentNode;
      if (parent) {
        const pcs = getComputedStyle(parent);
        if (pcs.position === "static") parent.style.position = "relative";
        if (pcs.overflow === "visible") parent.style.overflow = "hidden";
      }

      // Mapbox container
      const mapEl = document.createElement("div");
      mapEl.className = "cmv-map";
      mapEl.style.cssText = "position:absolute;inset:0;";
      host.appendChild(mapEl);
      // Overlay layer (HTML agents / trails / pills / home ring)
      const overlay = document.createElement("div");
      overlay.className = "cmv-overlay";
      overlay.style.cssText = [
        "position:absolute", "inset:0", "pointer-events:none",
        "z-index:5",
      ].join(";");
      host.appendChild(overlay);
      // Empty-state placeholder (shown until a trace arrives)
      const emptyEl = document.createElement("div");
      emptyEl.className = "cmv-empty";
      emptyEl.style.cssText = [
        "position:absolute", "left:24px", "top:24px", "color:#cfd8cf",
        "font:600 14px -apple-system,PingFang SC,sans-serif",
        "background:rgba(20,25,33,.78)", "padding:6px 12px", "border-radius:8px",
        "border:1px solid rgba(255,255,255,.08)",
      ].join(";");
      host.appendChild(emptyEl);
      // Insert host where canvas used to be.
      if (parent) {
        parent.replaceChild(host, canvas);
        this.host = host;
        this.overlay = overlay;
        this.mapEl = mapEl;
        this.emptyEl = emptyEl;
        this.canvas = mapEl;
      }
    }

    /* ---- public API (legacy-compatible) ------------------------------ */
    setTrace(trace) { this.trace = trace; this._refreshLayers(); }
    get selectedAgentId() { return this.getSelectedAgentId(); }
    render(framesUpTo) {
      this.framesUpTo = framesUpTo || [];
      this._empty = false;
      this.emptyEl.style.display = "none";
      this._drawOverlay();
    }
    rerender() { this._drawOverlay(); }
    renderEmpty(text) {
      this._empty = true;
      const fallback = typeof this.emptyText === "function" ? this.emptyText() : this.emptyText;
      this.emptyEl.textContent = text || fallback || "";
      this.emptyEl.style.display = "block";
      this.overlay.innerHTML = "";
    }
    hasMap() {
      const m = this.trace && this.trace.map;
      return !!(m && Array.isArray(m.nodes) && m.nodes.length);
    }
    zoomAt(cx, cy, factor) {
      // Mapbox's scroll-zoom handles wheel; this is for the + / - buttons.
      if (!this.map) return;
      try { this.map.zoomTo(this.map.getZoom() * (factor > 1 ? 1.25 : 1 / 1.25), { around: [cx, cy] }); }
      catch (e) { /* ignore — map not ready */ }
    }
    resetView() {
      if (!this.map || !this.hasMap()) return;
      const nodes = this.trace.map.nodes.filter(nodeLngLat);
      if (!nodes.length) return;
      let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity;
      for (const n of nodes) {
        if (n.lng < minLng) minLng = n.lng;
        if (n.lat < minLat) minLat = n.lat;
        if (n.lng > maxLng) maxLng = n.lng;
        if (n.lat > maxLat) maxLat = n.lat;
      }
      this.map.fitBounds([[minLng - 0.01, minLat - 0.01], [maxLng + 0.01, maxLat + 0.01]],
                         { padding: 60, duration: 600 });
    }

    /* ---- interactions ------------------------------------------------ */
    _setupInteractions() {
      // Mapbox has wheel-zoom + drag-pan + dblclick-zoom-in built in. We
      // add a small + / − / reset cluster to match the legacy renderer's
      // controls. The legacy renderer's resetView dblclick is replaced by
      // Mapbox's own dblclick-zoom-in; we wire resetView to a button.
      this._buildControls();
    }
    _buildControls() {
      const parent = this.host ? this.host.parentElement : null;
      if (!parent) return;
      if (parent.querySelector(".cmv-zoom")) return;
      const wrap = document.createElement("div");
      wrap.className = "cmv-zoom";
      wrap.style.cssText = "position:absolute;right:16px;bottom:18px;display:flex;flex-direction:column;gap:6px;z-index:6;";
      const mk = (label, title, fn) => {
        const b = document.createElement("button");
        b.type = "button"; b.textContent = label; b.title = title;
        b.style.cssText = "width:36px;height:36px;border-radius:9px;border:1px solid rgba(0,0,0,0.14);" +
          "background:rgba(255,255,255,0.94);color:#20321f;font-size:19px;line-height:1;cursor:pointer;" +
          "box-shadow:0 1px 5px rgba(0,0,0,0.18);";
        b.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); fn(); });
        return b;
      };
      wrap.appendChild(mk("+", t("map.zoom_in"), () => {
        if (!this.map) return;
        this.map.zoomTo(this.map.getZoom() * 1.25, { duration: 200 });
      }));
      wrap.appendChild(mk("−", t("map.zoom_out"), () => {
        if (!this.map) return;
        this.map.zoomTo(this.map.getZoom() / 1.25, { duration: 200 });
      }));
      wrap.appendChild(mk("↻", t("map.reset_view"), () => this.resetView()));
      parent.appendChild(wrap);
    }

    /* ---- map engine bootstrap --------------------------------------- */
    async _initMap() {
      try {
        let map, kind;
        // No fixed center here: we don't yet know where the trace is from,
        // and a hardcoded Hangzhou center meant Chicago / London / Wuzhen
        // traces would all open with the basemap framed on the wrong city.
        // ``_refreshLayers`` calls ``fitBounds`` once the trace arrives,
        // so we let the basemap pick its own default until then.
        if (this.token) {
          const mapboxgl = await ensureMapbox();
          mapboxgl.accessToken = this.token;
          const styleUrl = this.theme === "light" ? MAPBOX_LIGHT_STYLE : MAPBOX_DEFAULT_STYLE;
          map = new mapboxgl.Map({
            container: this.mapEl, style: styleUrl,
            center: [0, 20], zoom: 1.6,
            attributionControl: true,
          });
          kind = "mapbox";
        } else {
          const maplibregl = await ensureMapLibre();
          const styleUrl = this.theme === "light" ? MAPLIBRE_LIGHT_STYLE : MAPLIBRE_DARK_STYLE;
          map = new maplibregl.Map({
            container: this.mapEl, style: styleUrl,
            center: [0, 20], zoom: 1.6,
            attributionControl: true,
          });
          kind = "maplibre";
        }
        this.map = map; this.engine = kind;
        map.on("load", () => this._refreshLayers());
        map.on("move", () => this._drawOverlay());
      } catch (err) {
        // If Mapbox/MapLibre fails to load (offline, CSP, etc.), show a
        // friendly message instead of leaving the container empty.
        this.emptyEl.style.display = "block";
        this.emptyEl.textContent = "底图加载失败：" + (err.message || err);
      }
    }

    /* ---- basemap layers --------------------------------------------- */
    _refreshLayers() {
      if (!this.map || !this.map.isStyleLoaded()) {
        // try again after style is
        if (this.map) this.map.once("load", () => this._refreshLayers());
        return;
      }
      // Remove any prior gaworld-* sources we own, then reinstall.
      const style = this.map.getStyle();
      const existing = (style.layers || []).filter((l) => l.id.startsWith("cmv-"));
      existing.forEach((l) => { try { this.map.removeLayer(l.id); } catch (e) {} });
      for (const id of ["cmv-edges", "cmv-metro", "cmv-river", "cmv-nodes"]) {
        try { if (this.map.getLayer(id)) this.map.removeLayer(id); } catch (e) {}
        try { if (this.map.getSource(id)) this.map.removeSource(id); } catch (e) {}
      }
      const m = (this.trace || {}).map || {};
      const nodesArr = Array.isArray(m.nodes) ? m.nodes.filter(nodeLngLat) : [];
      this.nodesByName = new Map();
      for (const n of m.nodes || []) {
        const key = n.label || n.id || "";
        if (key) this.nodesByName.set(String(key), n);
      }
      // Sources
      this.map.addSource("cmv-edges", {
        type: "geojson",
        data: this._buildEdgesFC(m),
      });
      this.map.addSource("cmv-metro", {
        type: "geojson",
        data: this._buildMetroFC(m),
      });
      this.map.addSource("cmv-river", {
        type: "geojson",
        data: this._buildRiverFC(m),
      });
      this.map.addSource("cmv-nodes", {
        type: "geojson",
        data: this._buildNodesFC(m),
      });
      // River
      this.map.addLayer({
        id: "cmv-river", type: "line", source: "cmv-river",
        paint: {
          "line-color": "#5fb1e8", "line-width": 4, "line-opacity": 0.85, "line-blur": 0.6,
        },
      });
      // Edges
      this.map.addLayer({
        id: "cmv-edges", type: "line", source: "cmv-edges",
        paint: {
          "line-color": ["get", "color"],
          "line-width": ["interpolate", ["linear"], ["zoom"], 11, ["*", ["get", "width"], 0.5],
                         14, ["get", "width"], 17, ["*", ["get", "width"], 1.6]],
          "line-opacity": ["case", ["==", ["get", "roadType"], "local"], 0.55, 0.85],
        },
      });
      // Metro (glow + line)
      this.map.addLayer({
        id: "cmv-metro-glow", type: "line", source: "cmv-metro",
        paint: { "line-color": ["get", "color"], "line-width": 10, "line-opacity": 0.18, "line-blur": 5 },
      });
      this.map.addLayer({
        id: "cmv-metro", type: "line", source: "cmv-metro",
        paint: {
          "line-color": ["get", "color"], "line-width": 3, "line-opacity": 0.95,
          "line-dasharray": [0.5, 1.4],
        },
      });
      // Nodes
      this.map.addLayer({
        id: "cmv-nodes", type: "circle", source: "cmv-nodes",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 3, 16, 6],
          "circle-color": ["coalesce", ["get", "color"], "#9aa3b2"],
          "circle-stroke-color": "#0c1118", "circle-stroke-width": 1, "circle-opacity": 0.85,
        },
      });
      this.layersInstalled = true;
      // Frame the map on the current trace's bounds every time, not just
      // on first install: a user switching between cities in the console
      // city panel expects the basemap to follow. The ``isStyleLoaded``
      // guard above means we only run this after the basemap is ready,
      // which is the only timing constraint here. ``duration: 0`` makes
      // the snap feel instant when the user picks a city.
      if (nodesArr.length) {
        let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity;
        for (const n of nodesArr) {
          if (n.lng < minLng) minLng = n.lng; if (n.lat < minLat) minLat = n.lat;
          if (n.lng > maxLng) maxLng = n.lng; if (n.lat > maxLat) maxLat = n.lat;
        }
        this.map.fitBounds([[minLng - 0.01, minLat - 0.01], [maxLng + 0.01, maxLat + 0.01]],
                           { padding: 50, duration: 0 });
      }
      this._drawOverlay();
    }
    _buildEdgesFC(m) {
      const features = [];
      const nodesById = {};
      for (const n of (m.nodes || [])) nodesById[n.id] = n;
      for (const e of (m.edges || [])) {
        const a = nodesById[e.source || e.from || e.a];
        const b = nodesById[e.target || e.to || e.b];
        if (!a || !b) continue;
        if (!nodeLngLat(a) || !nodeLngLat(b)) continue;
        const t = e.road_type || e.type || "local";
        features.push({
          type: "Feature",
          geometry: { type: "LineString", coordinates: [[a.lng, a.lat], [b.lng, b.lat]] },
          properties: { roadType: t, color: ROAD_TYPE_COLOR[t] || ROAD_TYPE_COLOR.local,
                        width: ROAD_TYPE_WIDTH[t] || 1.2 },
        });
      }
      return { type: "FeatureCollection", features };
    }
    _buildMetroFC(m) {
      const features = [];
      const nodesByName = {};
      for (const n of (m.nodes || [])) if (n.label || n.id) nodesByName[n.label || n.id] = n;
      for (const line of (m.metro_lines || [])) {
        const coords = (line.stops || [])
          .map((name) => nodesByName[name]).filter(Boolean).filter(nodeLngLat)
          .map((n) => [n.lng, n.lat]);
        if (coords.length < 2) continue;
        features.push({
          type: "Feature",
          geometry: { type: "LineString", coordinates: coords },
          properties: { color: line.color || "#8f5bd8" },
        });
      }
      return { type: "FeatureCollection", features };
    }
    _buildRiverFC(m) {
      const r = m.river;
      if (!r || !r.path || r.path.length < 2) return { type: "FeatureCollection", features: [] };
      return {
        type: "FeatureCollection",
        features: [{
          type: "Feature",
          geometry: { type: "LineString", coordinates: r.path.map(([lng, lat]) => [lng, lat]) },
          properties: { name: r.name || "" },
        }],
      };
    }
    _buildNodesFC(m) {
      const features = [];
      const styleByCat = (m.category_style) || {};
      for (const n of (m.nodes || [])) {
        if (!nodeLngLat(n)) continue;
        const cat = n.category || "mixed";
        const style = styleByCat[cat] || {};
        features.push({
          type: "Feature",
          geometry: { type: "Point", coordinates: [n.lng, n.lat] },
          properties: { color: style.color || "#9aa3b2" },
        });
      }
      return { type: "FeatureCollection", features };
    }

    /* ---- overlay: agent avatars / trails / home ring ----------------- */
    _drawOverlay() {
      if (!this.map || this._empty) return;
      const frame = this.framesUpTo[this.framesUpTo.length - 1];
      if (!frame) {
        this.overlay.innerHTML = "";
        return;
      }
      const agents = (frame.agents || []);
      // Home ring for the selected agent's home node
      const homeId = this.getSelectedAgentHome ? this.getSelectedAgentHome() : null;
      // Trail: up to N frames
      const trailByAgent = new Map();
      const slice = this.framesUpTo.slice(-this.trailFrames);
      for (const fr of slice) {
        for (const a of (fr.agents || [])) {
          const k = Number(a.agent_id);
          if (!trailByAgent.has(k)) trailByAgent.set(k, []);
          const arr = trailByAgent.get(k);
          const last = arr[arr.length - 1];
          const p = this._agentLngLat(a);
          if (!p) continue;
          if (!last || last[0] !== p[0] || last[1] !== p[1]) arr.push(p);
        }
      }
      const html = [];
      // Home ring (drawn first so avatars sit on top)
      if (homeId) {
        const node = this._nodeById(homeId);
        if (node && nodeLngLat(node)) {
          const pt = projectToScreen(this.map, node.lng, node.lat);
          if (pt) {
            html.push(`<div style="position:absolute;left:${pt[0] - 14}px;top:${pt[1] - 14}px;width:28px;height:28px;
              border:2px dashed rgba(214,124,56,.85);border-radius:50%;
              box-shadow:0 0 0 6px rgba(214,124,56,.18);"></div>`);
          }
        }
      }
      // Trails (SVG polyline per agent)
      const selectedId = Number(this.selectedAgentId);
      for (const [agentId, pts] of trailByAgent.entries()) {
        if (pts.length < 2) continue;
        const isSelected = agentId === selectedId;
        const color = agentColors[Math.abs(agentId) % agentColors.length];
        const svgPts = pts.map((lnglat) => projectToScreen(this.map, lnglat[0], lnglat[1]))
          .filter(Boolean).map((p) => `${p[0]},${p[1]}`).join(" ");
        if (!svgPts) continue;
        html.push(`<svg style="position:absolute;left:0;top:0;width:100%;height:100%;overflow:visible;pointer-events:none;">
          <polyline points="${svgPts}" fill="none" stroke="${color}"
            stroke-width="${isSelected ? 4 : 2.4}"
            stroke-opacity="${isSelected ? 0.9 : 0.55}"
            stroke-dasharray="${isSelected ? "" : "6,5"}"
            stroke-linecap="round" stroke-linejoin="round"/>
        </svg>`);
      }
      // Avatars + name pills
      for (const a of agents) {
        const p = this._agentLngLat(a);
        if (!p) continue;
        const pt = projectToScreen(this.map, p[0], p[1]);
        if (!pt) continue;
        const isSelected = Number(a.agent_id) === selectedId;
        const r = isSelected ? 22 : 16;
        const color = agentColors[Math.abs(Number(a.agent_id || 0)) % agentColors.length];
        const avatarPath = this._avatarPath(a.agent_id);
        const name = (a.name || String(a.agent_id)).replace(/[<>&]/g, "");
        const homeBadge = this._isAgentAtHome(a)
          ? `<span style="position:absolute;right:-4px;bottom:-4px;width:18px;height:18px;border-radius:50%;
              background:#fffef9;border:1.5px solid #13795b;display:flex;align-items:center;justify-content:center;
              font-size:11px;line-height:1;">🏠</span>` : "";
        html.push(`<div style="position:absolute;left:${pt[0] - r - 3}px;top:${pt[1] - r - 3}px;
          width:${(r + 3) * 2}px;height:${(r + 3) * 2}px;border-radius:50%;
          background:#fffef9;box-shadow:0 4px 12px rgba(0,0,0,.35);">
          <div style="position:relative;width:${r * 2}px;height:${r * 2}px;margin:3px auto;
            border-radius:50%;overflow:hidden;border:${isSelected ? 3 : 2}px solid ${isSelected ? color : "#fffef9"};
            background:${color};">
            <img src="${avatarPath}" crossorigin="anonymous"
              style="width:100%;height:100%;object-fit:cover;display:block;"
              onerror="this.style.display='none'"/>
            ${homeBadge}
          </div>
        </div>
        <div style="position:absolute;left:${pt[0]}px;top:${pt[1] + r + 6}px;transform:translateX(-50%);
          background:rgba(23,33,29,.85);color:#fffef9;font:600 11px -apple-system,PingFang SC,sans-serif;
          padding:2px 7px;border-radius:5px;white-space:nowrap;max-width:160px;overflow:hidden;
          text-overflow:ellipsis;">${name}</div>`);
      }
      this.overlay.innerHTML = html.join("");
    }
    _agentLngLat(agent) {
      // Try to find a node by resolved/target name; if both exist and
      // travel_progress is in (0,1), interpolate the lng/lat so the agent
      // slides between two nodes mid-travel (matches the legacy renderer's
      // behaviour).
      const cur = getNodeByName(this.nodesByName, agent.resolved_location || agent.location);
      const tgt = getNodeByName(this.nodesByName, agent.target_location);
      const p = Number(agent.travel_progress);
      if (cur && tgt && cur !== tgt && Number.isFinite(p) && p >= 0 && p <= 1) {
        const ca = nodeLngLat(cur), ta = nodeLngLat(tgt);
        if (ca && ta) {
          return [ca[0] + (ta[0] - ca[0]) * p, ca[1] + (ta[1] - ca[1]) * p];
        }
      }
      const node = tgt || cur;
      const ll = nodeLngLat(node);
      return ll ? [ll[0], ll[1]] : null;
    }
    _nodeById(idOrLabel) {
      // Match either node.id or node.label — the trace stores names.
      for (const n of ((this.trace && this.trace.map && this.trace.map.nodes) || [])) {
        if (n.id === idOrLabel || n.label === idOrLabel) return n;
      }
      return null;
    }
    _avatarPath(agentId) {
      const agents = (this.trace && Array.isArray(this.trace.agents)) ? this.trace.agents : [];
      const meta = agents.find((a) => Number(a.id) === Number(agentId));
      const raw = (meta && meta.avatar_path) || `avatars/agent_${Number(agentId || 0)}.svg`;
      if (/^(https?:)?\/\//.test(raw) || raw.startsWith("data:")) return raw;
      if (!raw.startsWith("/")) return this.avatarBase + raw;
      return raw;
    }
    _isAgentAtHome(agent) {
      const home = String(agent.home || "").trim();
      const current = String(agent.resolved_location || agent.location || "").trim();
      if (!home || !current) return false;
      return home === current;
    }
  }

  global.CityMapView = CityMapView;
})(window);