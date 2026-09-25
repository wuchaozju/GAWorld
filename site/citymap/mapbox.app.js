/* Mapbox / MapLibre renderer for GAWorld city maps.
 *
 * Pure-browser single-page app — no build step.
 *   - Consumes `/api/city/map?city=<slug>` and `/api/city/agents?city=<slug>`.
 *   - Renders the same nodes/edges/metro/river data as the existing Canvas
 *     visualizer (site/dashboard/citymap-view.js), but layered on a real
 *     vector basemap (Mapbox when a token is provided, MapLibre + the public
 *     OpenFreeMap demo otherwise). The simulation itself is untouched.
 *
 *   const view = new GAWorldMapView(mapDiv, sideDiv);
 *   await view.load('wuzhen');
 *
 * Exposed as window.GAWorldMapView.
 */
(function (global) {
  "use strict";

  /* ============================================================
   * Constants & helpers
   * ============================================================ */
  // Public Mapbox style URL we fall back to; safe even without a token if the
  // account has any free tier left. If the user has not configured a token,
  // loadMapLibre() runs instead and never touches mapbox.com.
  const MAPBOX_DEFAULT_STYLE = "mapbox://styles/mapbox/dark-v11";
  const MAPBOX_LIGHT_STYLE = "mapbox://styles/mapbox/light-v11";
  const MAPBOX_STREETS_STYLE = "mapbox://styles/mapbox/streets-v12";

  // MapLibre free public style — no token, no account. Roads, water, parks
  // already styled for a clean dark/light look.
  const MAPLIBRE_DARK_STYLE = "https://tiles.openfreemap.org/styles/positron";
  const MAPLIBRE_LIGHT_STYLE = "https://tiles.openfreemap.org/styles/liberty";

  const CDN = {
    mapbox: "https://api.mapbox.com/mapbox-gl-js/v3.7.0/mapbox-gl.js",
    mapboxCss: "https://api.mapbox.com/mapbox-gl-js/v3.7.0/mapbox-gl.css",
    maplibre: "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js",
    maplibreCss: "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css",
  };

  const CATEGORY_LABEL_ZH = {
    residential: "居住区", commerce: "商业区", education: "教育区",
    medical: "医疗区", industry: "产业区", government: "行政区",
    leisure: "休闲区", transit: "交通枢纽", mixed: "综合区",
  };

  const ROAD_TYPE_COLOR = {
    arterial: "#ffd166",  // warm yellow — main arteries
    collector: "#9bd1ff", // sky blue — secondary collectors
    road: "#9bd1ff",
    local: "#7a8aa0",     // muted slate — local streets
    bridge: "#ff9b6a",
  };
  const ROAD_TYPE_WIDTH = {
    arterial: 3.4, collector: 2.4, road: 2.0, local: 1.2, bridge: 2.6,
  };

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function debounce(fn, ms) {
    let t = 0;
    return function () {
      const args = arguments, ctx = this;
      clearTimeout(t);
      t = setTimeout(() => fn.apply(ctx, args), ms);
    };
  }

  /* ============================================================
   * Script loader — pull Mapbox or MapLibre from CDN on demand.
   * ============================================================ */
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src; s.async = true;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("failed to load " + src));
      document.head.appendChild(s);
    });
  }
  function loadCss(href) {
    return new Promise((resolve) => {
      const link = document.createElement("link");
      link.rel = "stylesheet"; link.href = href;
      link.onload = () => resolve();
      link.onerror = () => resolve(); // not fatal; map still works visually
      document.head.appendChild(link);
    });
  }
  async function ensureMapLibre() {
    if (global.maplibregl) return global.maplibregl;
    await loadCss(CDN.maplibreCss);
    await loadScript(CDN.maplibre);
    if (!global.maplibregl) throw new Error("maplibre-gl failed to initialize");
    return global.maplibregl;
  }
  async function ensureMapbox() {
    if (global.mapboxgl) return global.mapboxgl;
    await loadCss(CDN.mapboxCss);
    await loadScript(CDN.mapbox);
    if (!global.mapboxgl) throw new Error("mapbox-gl failed to initialize");
    return global.mapboxgl;
  }

  /* ============================================================
   * Data fetching
   * ============================================================ */
  async function fetchJSON(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status + " on " + url);
    return r.json();
  }
  async function fetchCityData(slug) {
    const [mapPayload, agentsPayload] = await Promise.all([
      fetchJSON("/api/city/map?city=" + encodeURIComponent(slug)),
      fetchJSON("/api/city/agents?city=" + encodeURIComponent(slug) + "&limit=200"),
    ]);
    return { map: mapPayload, agents: agentsPayload };
  }

  /* ============================================================
   * GeoJSON builders
   * ============================================================ */
  function nodePointFeature(node, style) {
    // Normalise null/None to a number so MapLibre/Mapbox style expressions
    // don't warn "Expected value to be of type number, but found null
    // instead". Fallbacks match the median of typical categories so the
    // visual gradient still feels right.
    const num = (v, fallback) => (typeof v === "number" && Number.isFinite(v) ? v : fallback);
    return {
      type: "Feature",
      geometry: { type: "Point", coordinates: [node.lng, node.lat] },
      properties: {
        id: node.id, name: node.name, kind: node.kind, category: node.category,
        district: node.district,
        popularity: num(node.popularity, 0.4),
        density: num(node.density, 0.5),
        style: style || {},
      },
    };
  }
  function buildNodeCollection(mapPayload) {
    const features = [];
    const nodes = (mapPayload && mapPayload.map && mapPayload.map.nodes) || [];
    const styleByCat = (mapPayload && mapPayload.map && mapPayload.map.category_style) || {};
    for (const n of nodes) {
      if (typeof n.lng !== "number" || typeof n.lat !== "number") continue;
      const cat = n.category || "mixed";
      features.push(nodePointFeature(n, styleByCat[cat] || {}));
    }
    return { type: "FeatureCollection", features };
  }
  function buildEdgesCollection(mapPayload) {
    const features = [];
    const nodesById = {};
    const nodes = (mapPayload && mapPayload.map && mapPayload.map.nodes) || [];
    for (const n of nodes) nodesById[n.id] = n;
    const edges = (mapPayload && mapPayload.map && mapPayload.map.edges) || [];
    for (const e of edges) {
      const a = nodesById[e.source || e.from || e.a];
      const b = nodesById[e.target || e.to || e.b];
      if (!a || !b) continue;
      if (typeof a.lng !== "number" || typeof b.lng !== "number") continue;
      const t = e.road_type || e.type || "local";
      features.push({
        type: "Feature",
        geometry: { type: "LineString", coordinates: [[a.lng, a.lat], [b.lng, b.lat]] },
        properties: { roadType: t, color: ROAD_TYPE_COLOR[t] || ROAD_TYPE_COLOR.local,
                      width: ROAD_TYPE_WIDTH[t] || 1.2, bridge: !!e.bridge },
      });
    }
    return { type: "FeatureCollection", features };
  }
  function buildMetroCollection(mapPayload) {
    const features = [];
    const nodesByName = {};
    const nodes = (mapPayload && mapPayload.map && mapPayload.map.nodes) || [];
    for (const n of nodes) {
      if (n.name) nodesByName[n.name] = n;
    }
    const lines = (mapPayload && mapPayload.map && mapPayload.map.metro_lines) || [];
    for (const line of lines) {
      const stops = (line.stops || []).map((name) => nodesByName[name]).filter(Boolean);
      if (stops.length < 2) continue;
      features.push({
        type: "Feature",
        geometry: { type: "LineString",
          coordinates: stops.map((s) => [s.lng, s.lat]) },
        properties: {
          name: line.name || "M?", color: line.color || "#8f5bd8",
          stopCount: stops.length,
          stops: stops.map((s) => s.name),
        },
      });
      // Add the stations as a separate feature collection below — here we
      // also annotate the nodes with their metro lines for the popup.
      for (const s of stops) {
        s.__metroLines = (s.__metroLines || []);
        if (!s.__metroLines.includes(line.name)) s.__metroLines.push(line.name);
      }
    }
    return { type: "FeatureCollection", features };
  }
  function buildRiverCollection(mapPayload) {
    const r = mapPayload && mapPayload.map && mapPayload.map.river;
    if (!r || !r.path || r.path.length < 2) {
      return { type: "FeatureCollection", features: [] };
    }
    return {
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        geometry: { type: "LineString", coordinates: r.path.map(([lng, lat]) => [lng, lat]) },
        properties: { name: r.name || "河流", width: r.width || 0.05 },
      }],
    };
  }
  function buildAgentsCollection(agentsPayload) {
    const features = [];
    const agents = (agentsPayload && agentsPayload.agents) || [];
    for (const a of agents) {
      // agents don't always carry lat/lng; resolve via home node if needed.
      let lng = a.lng, lat = a.lat;
      if ((typeof lng !== "number" || typeof lat !== "number") && a.home_node) {
        // Map agent home_node → simulated grid → approximate lat/lng.
        // We approximate by looking up node by id from the loaded map.
        // The view wires this lookup after the map payload loads.
      }
      if (typeof lng !== "number" || typeof lat !== "number") continue;
      features.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: [lng, lat] },
        properties: {
          id: a.id, name: a.name || ("居民 #" + a.id),
          age: a.age, occupation: a.occupation, mood: a.mood,
        },
      });
    }
    return { type: "FeatureCollection", features };
  }

  /* ============================================================
   * Map factory — picks Mapbox or MapLibre based on token.
   * ============================================================ */
  async function createMap({ container, token, theme }) {
    if (token) {
      const mapboxgl = await ensureMapbox();
      mapboxgl.accessToken = token;
      const styleUrl = theme === "light" ? MAPBOX_LIGHT_STYLE
                     : theme === "streets" ? MAPBOX_STREETS_STYLE
                     : MAPBOX_DEFAULT_STYLE;
      const map = new mapboxgl.Map({
        container, style: styleUrl, center: [120.4819, 30.7465], zoom: 13.5,
        attributionControl: true, pitch: 0, bearing: 0,
      });
      return { map, kind: "mapbox" };
    }
    const maplibregl = await ensureMapLibre();
    const styleUrl = theme === "light" ? MAPLIBRE_LIGHT_STYLE : MAPLIBRE_DARK_STYLE;
    const map = new maplibregl.Map({
      container, style: styleUrl, center: [120.4819, 30.7465], zoom: 13.5,
      attributionControl: true,
    });
    return { map, kind: "maplibre" };
  }

  /* ============================================================
   * Main view class
   * ============================================================ */
  class GAWorldMapView {
    constructor(mapEl, sideEl, opts) {
      this.mapEl = mapEl;
      this.sideEl = sideEl;
      this.opts = opts || {};
      this.engine = null;
      this.map = null;
      this.mapPayload = null;
      this.agentsPayload = null;
      this.layers = { edges: true, metro: true, river: true, agents: true, labels: true };
      this.selectedAgentId = null;
      this.token = (opts && opts.mapboxToken) || "";
    }

    /* ---- public ---- */
    async load(slug) {
      this.slug = slug;
      const data = await fetchCityData(slug);
      this.mapPayload = data.map;
      this.agentsPayload = data.agents;
      // Patch agents that lack explicit lat/lng with their home node coords.
      const nodesById = {};
      for (const n of (this.mapPayload.map.nodes || [])) nodesById[n.id] = n;
      for (const a of (this.agentsPayload.agents || [])) {
        if ((typeof a.lng !== "number" || typeof a.lat !== "number") && a.home_node && nodesById[a.home_node]) {
          const h = nodesById[a.home_node];
          // Tiny deterministic jitter so 60 agents aren't all stacked on the
          // same pixel — same scheme the existing Canvas view uses.
          const seed = String(a.id || "").split("").reduce((s, c) => s + c.charCodeAt(0), 0);
          const dx = ((seed * 9301 + 49297) % 233 - 116) / 116 * 0.0006;
          const dy = ((seed * 7919 + 23333) % 277 - 138) / 138 * 0.0006;
          a.lng = h.lng + dx; a.lat = h.lat + dy;
        }
      }
      const { map, kind } = await createMap({
        container: this.mapEl, token: this.token, theme: this.opts.theme || "dark",
      });
      this.map = map; this.engine = kind;
      map.on("load", () => this._installLayers());
      this._renderSide();
    }
    setLayerVisible(key, on) {
      this.layers[key] = !!on;
      if (!this.map.isStyleLoaded()) return;
      const id = this._layerId(key);
      if (this.map.getLayer(id)) {
        this.map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
      }
      this._renderSide();
    }
    flyTo(lng, lat, zoom) {
      if (this.engine === "mapbox") {
        this.map.flyTo({ center: [lng, lat], zoom: zoom || 14 });
      } else {
        this.map.flyTo({ center: [lng, lat], zoom: zoom || 14 });
      }
    }

    /* ---- internal: layers ---- */
    _layerId(key) {
      return "gaworld-" + key;
    }
    _installLayers() {
      // Compute a comfortable bounds box so the map opens framed on the city.
      const nodes = (this.mapPayload.map.nodes || []).filter((n) => n.lng && n.lat);
      if (nodes.length) {
        let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity;
        for (const n of nodes) {
          if (n.lng < minLng) minLng = n.lng;
          if (n.lat < minLat) minLat = n.lat;
          if (n.lng > maxLng) maxLng = n.lng;
          if (n.lat > maxLat) maxLat = n.lat;
        }
        this.map.fitBounds([[minLng - 0.01, minLat - 0.01], [maxLng + 0.01, maxLat + 0.01]],
                            { padding: 50, duration: 0 });
      }
      // Sources
      this.map.addSource("gaworld-edges",  { type: "geojson", data: buildEdgesCollection(this.mapPayload) });
      this.map.addSource("gaworld-metro",  { type: "geojson", data: buildMetroCollection(this.mapPayload) });
      this.map.addSource("gaworld-river",  { type: "geojson", data: buildRiverCollection(this.mapPayload) });
      this.map.addSource("gaworld-nodes",  { type: "geojson", data: buildNodeCollection(this.mapPayload) });
      this.map.addSource("gaworld-agents", { type: "geojson", data: buildAgentsCollection(this.agentsPayload) });

      const beforeId = this._firstSymbolLayerId();

      // River — water blue, slightly transparent, sits under everything else
      this.map.addLayer({
        id: this._layerId("river"),
        type: "line", source: "gaworld-river",
        layout: { visibility: this.layers.river ? "visible" : "none" },
        paint: {
          "line-color": "#5fb1e8",
          "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1.2, 14, 4, 17, 9],
          "line-opacity": 0.85,
          "line-blur": 0.6,
        },
      });

      // Roads — colored by class. Local streets desaturate so arterials pop.
      this.map.addLayer({
        id: this._layerId("edges"),
        type: "line", source: "gaworld-edges",
        layout: { visibility: this.layers.edges ? "visible" : "none" },
        paint: {
          "line-color": ["get", "color"],
          "line-width": ["interpolate", ["linear"], ["zoom"], 10, ["*", ["get", "width"], 0.4],
                         14, ["get", "width"], 17, ["*", ["get", "width"], 1.6]],
          "line-opacity": ["case", ["==", ["get", "roadType"], "local"], 0.55, 0.85],
        },
      });

      // Metro — color from data, with a soft glow underneath for that "modern
      // subway map" feel.
      this.map.addLayer({
        id: this._layerId("metro-glow"),
        type: "line", source: "gaworld-metro",
        layout: { visibility: this.layers.metro ? "visible" : "none" },
        paint: {
          "line-color": ["get", "color"], "line-width": 10, "line-opacity": 0.18, "line-blur": 5,
        },
      });
      this.map.addLayer({
        id: this._layerId("metro"),
        type: "line", source: "gaworld-metro",
        layout: { visibility: this.layers.metro ? "visible" : "none" },
        paint: {
          "line-color": ["get", "color"], "line-width": 3.2, "line-opacity": 0.95,
          "line-dasharray": [0.5, 1.4],
        },
      });

      // POI nodes — colored circles sized by density.
      this.map.addLayer({
        id: this._layerId("nodes"),
        type: "circle", source: "gaworld-nodes",
        layout: { visibility: this.layers.agents ? "visible" : "none" },
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 2.5, 14, 5.5, 17, 9],
          "circle-color": ["coalesce", ["get", "color"], "#9aa3b2"],
          "circle-stroke-color": "#0c1118",
          "circle-stroke-width": 1.4,
          "circle-opacity": 0.92,
        },
      });

      // Agents — small dots, hidden by default once you zoom in past nodes.
      this.map.addLayer({
        id: this._layerId("agents"),
        type: "circle", source: "gaworld-agents",
        layout: { visibility: this.layers.agents ? "visible" : "none" },
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 1.6, 16, 3.4],
          "circle-color": "#22d3a0", "circle-stroke-color": "#0c1118", "circle-stroke-width": 0.8,
          "circle-opacity": 0.85,
        },
      });

      // Labels (only when toggled on)
      this.map.addLayer({
        id: this._layerId("labels"),
        type: "symbol", source: "gaworld-nodes",
        layout: {
          visibility: this.layers.labels ? "visible" : "none",
          "text-field": ["get", "name"],
          "text-font": ["Open Sans Semibold", "Arial Unicode MS Bold"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 12, 10, 16, 13],
          "text-offset": [0, 1.1], "text-anchor": "top",
          "text-allow-overlap": false,
        },
        paint: {
          "text-color": "#f5f7fa",
          "text-halo-color": "#0c1118", "text-halo-width": 1.4,
        },
      });

      // Click popups
      this.map.on("click", this._layerId("nodes"), (e) => this._showNodePopup(e));
      this.map.on("click", this._layerId("agents"), (e) => this._showAgentPopup(e));
      this.map.on("mouseenter", this._layerId("nodes"), () => (this.map.getCanvas().style.cursor = "pointer"));
      this.map.on("mouseleave", this._layerId("nodes"), () => (this.map.getCanvas().style.cursor = ""));
    }
    _firstSymbolLayerId() {
      const layers = this.map.getStyle().layers || [];
      for (const l of layers) {
        if (l.type === "symbol") return l.id;
      }
      return undefined;
    }
    _showNodePopup(e) {
      const f = e.features && e.features[0];
      if (!f) return;
      const p = f.properties;
      const html = `<div class="popup">
        <div class="popup-title">${escapeHtml(p.name)}</div>
        <div class="popup-row"><span>分类</span><b>${escapeHtml(CATEGORY_LABEL_ZH[p.category] || p.category || "")}</b></div>
        <div class="popup-row"><span>区域</span><b>${escapeHtml(p.district || "—")}</b></div>
        <div class="popup-row"><span>类型</span><b>${escapeHtml(p.kind || "—")}</b></div>
        ${p.popularity ? `<div class="popup-row"><span>人气</span><b>${(p.popularity * 100).toFixed(0)}%</b></div>` : ""}
      </div>`;
      new (this.engine === "mapbox" ? global.mapboxgl : global.maplibregl).Popup({ closeButton: true })
        .setLngLat(f.geometry.coordinates).setHTML(html).addTo(this.map);
    }
    _showAgentPopup(e) {
      const f = e.features && e.features[0];
      if (!f) return;
      const p = f.properties;
      const html = `<div class="popup">
        <div class="popup-title">${escapeHtml(p.name)}</div>
        <div class="popup-row"><span>年龄</span><b>${escapeHtml(p.age || "—")}</b></div>
        <div class="popup-row"><span>职业</span><b>${escapeHtml(p.occupation || "—")}</b></div>
        ${p.mood ? `<div class="popup-row"><span>情绪</span><b>${escapeHtml(p.mood)}</b></div>` : ""}
      </div>`;
      new (this.engine === "mapbox" ? global.mapboxgl : global.maplibregl).Popup({ closeButton: true })
        .setLngLat(f.geometry.coordinates).setHTML(html).addTo(this.map);
    }

    /* ---- internal: side panel ---- */
    _renderSide() {
      const map = this.mapPayload || {};
      const city = (map.city || {}).display_name || this.slug;
      const nodes = (map.map && map.map.nodes) || [];
      const edges = (map.map && map.map.edges) || [];
      const metro = (map.map && map.map.metro_lines) || [];
      const meta = map.meta || {};
      const agents = (this.agentsPayload && this.agentsPayload.agents) || [];
      const byCat = {};
      for (const n of nodes) {
        const c = n.category || "mixed";
        byCat[c] = (byCat[c] || 0) + 1;
      }
      const catRows = Object.keys(byCat).sort((a, b) => byCat[b] - byCat[a]).map((c) => {
        const style = (map.map && map.map.category_style && map.map.category_style[c]) || {};
        const label = CATEGORY_LABEL_ZH[c] || c;
        return `<div class="cat-row">
          <span class="swatch" style="background:${style.color || "#888"}"></span>
          <span class="cat-name">${escapeHtml(label)}</span>
          <span class="cat-count">${byCat[c]}</span>
        </div>`;
      }).join("");
      const metroRows = metro.map((line) => {
        const stops = (line.stops || []).slice(0, 6).join(" → ");
        const more = (line.stops || []).length > 6 ? " …" : "";
        return `<div class="metro-row">
          <span class="swatch" style="background:${line.color || "#8f5bd8"}"></span>
          <span class="metro-name">${escapeHtml(line.name)}</span>
          <span class="metro-stops">${escapeHtml(stops + more)}</span>
        </div>`;
      }).join("");
      const tokenNote = this.token
        ? `<span class="engine-badge mapbox">Mapbox</span>`
        : `<span class="engine-badge maplibre">MapLibre · 无 token</span>`;
      this.sideEl.innerHTML = `
        <div class="side-head">
          <h1>${escapeHtml(city)}</h1>
          <div class="sub">${tokenNote} · 底图 ${meta.mode === "real" ? "OSM 派生" : "程序生成"}</div>
        </div>
        <div class="side-body">
          <div class="group">
            <div class="label">图层</div>
            <label class="toggle"><input type="checkbox" data-layer="edges" ${this.layers.edges ? "checked" : ""}> 道路</label>
            <label class="toggle"><input type="checkbox" data-layer="metro" ${this.layers.metro ? "checked" : ""}> 地铁</label>
            <label class="toggle"><input type="checkbox" data-layer="river" ${this.layers.river ? "checked" : ""}> 河流</label>
            <label class="toggle"><input type="checkbox" data-layer="agents" ${this.layers.agents ? "checked" : ""}> 居民</label>
            <label class="toggle"><input type="checkbox" data-layer="labels" ${this.layers.labels ? "checked" : ""}> 标签</label>
          </div>
          <div class="group">
            <div class="label">统计</div>
            <div class="stat-row"><span>节点</span><b>${nodes.length}</b></div>
            <div class="stat-row"><span>道路</span><b>${edges.length}</b></div>
            <div class="stat-row"><span>地铁线</span><b>${metro.length}</b></div>
            <div class="stat-row"><span>居民</span><b>${agents.length}</b></div>
          </div>
          <div class="group">
            <div class="label">分类分布</div>
            ${catRows || '<div class="empty">无</div>'}
          </div>
          <div class="group">
            <div class="label">地铁线路</div>
            ${metroRows || '<div class="empty">无</div>'}
          </div>
          <div class="group">
            <div class="label">操作</div>
            <button class="primary" data-act="fit">回到全城</button>
            <button data-act="theme">切换主题</button>
          </div>
          <div class="group">
            <div class="label">说明</div>
            <div class="footnote">
              真实坐标由 ${meta.source || "city spec"} 提供。
              ${this.token ? "已配置 Mapbox token。" : "未配置 Mapbox token，当前使用开源 MapLibre 底图；填入 <code>?token=pk.xxx</code> 升级。"}
            </div>
          </div>
        </div>
      `;
      this.sideEl.querySelectorAll("input[data-layer]").forEach((el) => {
        el.addEventListener("change", () => this.setLayerVisible(el.dataset.layer, el.checked));
      });
      this.sideEl.querySelector("[data-act='fit']").addEventListener("click", () => this._fitToCity());
      this.sideEl.querySelector("[data-act='theme']").addEventListener("click", () => this._toggleTheme());
    }
    _fitToCity() {
      const nodes = (this.mapPayload.map.nodes || []).filter((n) => n.lng && n.lat);
      if (!nodes.length) return;
      let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity;
      for (const n of nodes) {
        if (n.lng < minLng) minLng = n.lng; if (n.lat < minLat) minLat = n.lat;
        if (n.lng > maxLng) maxLng = n.lng; if (n.lat > maxLat) maxLat = n.lat;
      }
      this.map.fitBounds([[minLng - 0.01, minLat - 0.01], [maxLng + 0.01, maxLat + 0.01]],
                         { padding: 60, duration: 600 });
    }
    _toggleTheme() {
      const cur = this.opts.theme || "dark";
      this.opts.theme = cur === "dark" ? "light" : "dark";
      // Reload the page to swap styles cleanly. Mapbox/MapLibre don't gracefully
      // hot-swap style URLs across vector tile providers.
      const url = new URL(window.location.href);
      url.searchParams.set("theme", this.opts.theme);
      window.location.href = url.toString();
    }
  }

  global.GAWorldMapView = GAWorldMapView;
})(window);