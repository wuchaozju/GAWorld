/* Home Mode panel renderer.
 *
 * Pulls `GET /api/home/<id>` and turns the response into:
 *
 *  - A four-cell summary strip (rooms / m² / ambiance quality / observation rows)
 *  - One card per room, with the current room highlighted (if any)
 *  - The vibe line
 *  - The latest ambiance snapshot (lighting / sound / smell / temperature / tidiness)
 *  - A scrollable observation tail: one row per tick the agent was at home
 *
 * Used by `app.js` via `renderHomePanel(payload, helpers)` so the host page
 * can stay in charge of i18n, error display, and panel-collapsing.
 *
 *   const payload = await api(`/api/home/${agentId}`);
 *   renderHomePanel(payload, { t, fmt });
 *
 * The module is plain UMD-style: it adds `window.renderHomePanel` and the
 * helpers it needs are passed in (so it never imports another file in the
 * bundle).
 */
(function (global) {
  "use strict";

  // i18n fallbacks. Hosts normally pass `t`, but a missing translator should
  // never crash the panel — we just print the key.
  const fallback = (key) => key;
  const t = (maybeT, key, params) => {
    const fn = typeof maybeT === "function" ? maybeT : fallback;
    const out = fn(key, params);
    if (out && out !== key) return out;
    return FALLBACKS[key] || key;
  };

  const FALLBACKS = {
    "home.title": "Home Mode",
    "home.subtitle": "居家模式",
    "home.empty": "尚无居家模式数据。运行一次仿真后，这里会显示每位居民的居家环境。",
    "home.not_in_run": "这位居民没有参与上一轮运行，因此没有居家记录。",
    "home.summary.rooms": "房间",
    "home.summary.size": "总面积",
    "home.summary.quality": "档次",
    "home.summary.observations": "在家的帧数",
    "home.rooms_label": "房间布局",
    "home.vibe_label": "家的整体气质",
    "home.ambiance_label": "此刻氛围",
    "home.ambiance.lighting": "光线",
    "home.ambiance.sound": "声音",
    "home.ambiance.smell": "气味",
    "home.ambiance.temperature": "体感",
    "home.ambiance.tidiness": "整洁度",
    "home.observations_title": "居家活动记录",
    "home.obs.out": "外出",
    "home.obs.unknown_room": "未知房间",
  };

  const QUALITY_LABEL = {
    minimal: "极简",
    basic: "基础",
    comfortable: "舒适",
    premium: "精装",
  };

  const SIZE_FMT = (sqm) => (sqm ? `${sqm} 平米` : "—");

  function el(tag, opts, ...kids) {
    const node = document.createElement(tag);
    if (opts) {
      if (opts.cls) node.className = opts.cls;
      if (opts.text != null) node.textContent = String(opts.text);
      if (opts.attrs) {
        for (const [k, v] of Object.entries(opts.attrs)) {
          if (v != null) node.setAttribute(k, String(v));
        }
      }
    }
    for (const kid of kids) {
      if (kid == null) continue;
      node.appendChild(typeof kid === "string" ? document.createTextNode(kid) : kid);
    }
    return node;
  }

  function renderHomePanel(payload, helpers = {}) {
    const root = helpers.root || document.getElementById("homeDetail");
    if (!root) return;
    root.innerHTML = "";

    if (!payload || payload.error) {
      root.appendChild(
        el("div", { cls: "home-empty", text: payload?.error || t(helpers.t, "home.empty") }),
      );
      return;
    }
    if (!payload.has_home) {
      root.appendChild(
        el("div", { cls: "home-empty", text: t(helpers.t, "home.not_in_run") }),
      );
      return;
    }

    root.appendChild(renderSummary(payload, helpers));
    root.appendChild(renderVibe(payload, helpers));
    root.appendChild(renderRooms(payload, helpers));
    root.appendChild(renderAmbiance(payload, helpers));
    root.appendChild(renderObservations(payload, helpers));
  }

  function renderSummary(payload, helpers) {
    const design = payload.design || {};
    const rooms = design.rooms || {};
    const observations = payload.recent_observations || payload.observations || [];
    const totalSize = Object.values(rooms).reduce((acc, r) => acc + (Number(r.size_sqm) || 0), 0);
    const cells = [
      {
        label: t(helpers.t, "home.summary.rooms"),
        value: String(Object.keys(rooms).length),
      },
      {
        label: t(helpers.t, "home.summary.size"),
        value: SIZE_FMT(totalSize),
      },
      {
        label: t(helpers.t, "home.summary.quality"),
        value: QUALITY_LABEL[design.ambiance_quality] || design.ambiance_quality || "—",
      },
      {
        label: t(helpers.t, "home.summary.observations"),
        value: String(observations.length),
      },
    ];
    const grid = el("div", { cls: "home-summary-grid" });
    cells.forEach((c) => {
      grid.appendChild(
        el("div", { cls: "home-summary-item" },
          el("div", { cls: "home-summary-label", text: c.label }),
          el("div", { cls: "home-summary-value", text: c.value }),
        ),
      );
    });
    return grid;
  }

  function renderVibe(payload, helpers) {
    const design = payload.design || {};
    if (!design.vibe) return document.createDocumentFragment();
    const box = el("div", { cls: "home-vibe" });
    box.appendChild(el("span", { cls: "home-vibe-label", text: t(helpers.t, "home.vibe_label") }));
    box.appendChild(document.createTextNode(design.vibe));
    return box;
  }

  function renderRooms(payload, helpers) {
    const design = payload.design || {};
    const rooms = design.rooms || {};
    const activities = design.at_home_activities || {};
    if (!Object.keys(rooms).length) return document.createDocumentFragment();
    const wrap = el("div", { cls: "home-rooms" });
    for (const [key, room] of Object.entries(rooms)) {
      const roomNode = el("div", { cls: "home-room", attrs: { "data-room": key } });
      const head = el("div", { cls: "home-room-head" });
      head.appendChild(el("span", { cls: "home-room-name", text: room.name || key }));
      if (room.size_sqm) {
        head.appendChild(el("span", { cls: "home-room-size", text: SIZE_FMT(room.size_sqm) }));
      }
      roomNode.appendChild(head);
      if (Array.isArray(room.furniture) && room.furniture.length) {
        roomNode.appendChild(
          el("div", {
            cls: "home-room-furniture",
            text: "家具：" + room.furniture.join("、"),
          }),
        );
      }
      const acts = activities[key] || [];
      if (acts.length) {
        const tagWrap = el("div", { cls: "home-room-activities" });
        acts.forEach((a) => tagWrap.appendChild(el("span", { cls: "home-room-tag", text: a })));
        roomNode.appendChild(tagWrap);
      }
      wrap.appendChild(roomNode);
    }
    return wrap;
  }

  function renderAmbiance(payload, helpers) {
    const observations = payload.recent_observations || payload.observations || [];
    // Pick the latest at-home observation that carries an ambiance snapshot.
    let ambiance = null;
    for (let i = observations.length - 1; i >= 0; i -= 1) {
      const o = observations[i];
      if (o && o.ambiance && Object.keys(o.ambiance).length) {
        ambiance = o.ambiance;
        break;
      }
    }
    if (!ambiance) return document.createDocumentFragment();
    const grid = el("div", { cls: "home-ambiance" });
    const dims = [
      ["lighting", "home.ambiance.lighting"],
      ["sound", "home.ambiance.sound"],
      ["smell", "home.ambiance.smell"],
      ["temperature", "home.ambiance.temperature"],
      ["tidiness", "home.ambiance.tidiness"],
    ];
    dims.forEach(([key, label]) => {
      const value = ambiance[key];
      if (!value) return;
      grid.appendChild(
        el("div", { cls: "home-ambiance-item" },
          el("div", { cls: "home-ambiance-label", text: t(helpers.t, label) }),
          el("div", { cls: "home-ambiance-value", text: value }),
        ),
      );
    });
    return grid;
  }

  function renderObservations(payload, helpers) {
    const observations = payload.recent_observations || payload.observations || [];
    if (!observations.length) return document.createDocumentFragment();
    const wrap = el("div", { cls: "home-observations" });
    wrap.appendChild(
      el("div", { cls: "home-observations-head" },
        el("div", { cls: "home-observations-title", text: t(helpers.t, "home.observations_title") }),
        el("div", {
          cls: "home-observations-count",
          text: `${observations.length} 行`,
        }),
      ),
    );
    const list = el("ul", { cls: "home-observations-list" });
    // Newest first — observers are more interested in recent than old.
    [...observations].reverse().forEach((obs) => {
      const isHome = obs && obs.current_room && obs.current_room.key;
      const row = el("li", { cls: "home-observation-row" + (isHome ? "" : " is-out") });
      row.appendChild(el("span", { cls: "home-obs-day", text: obs.day != null ? `D${obs.day}` : "—" }));
      row.appendChild(el("span", { cls: "home-obs-time", text: obs.time || "—" }));
      const roomLabel = isHome
        ? (obs.current_room.name || obs.current_room.key)
        : t(helpers.t, "home.obs.out");
      row.appendChild(el("span", { cls: "home-obs-room", text: roomLabel }));
      list.appendChild(row);
    });
    wrap.appendChild(list);
    return wrap;
  }

  /**
   * Highlight the room a data arg designates as "current" on the rendered
   * panel. Call this from the host page after re-rendering to flash the
   * room that matches the latest observation.
   */
  function highlightCurrentRoom(root, currentRoomKey) {
    if (!root || !currentRoomKey) return;
    const target = root.querySelector(`.home-room[data-room="${currentRoomKey}"]`);
    if (!target) return;
    target.classList.add("is-current");
  }

  global.HomePanel = {
    render: renderHomePanel,
    highlightCurrentRoom,
  };
})(typeof window !== "undefined" ? window : globalThis);