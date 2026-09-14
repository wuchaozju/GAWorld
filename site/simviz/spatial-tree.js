/* GAWorld simviz — indoor spatial tree.
 *
 * A generative-agents–style spatial memory for building interiors:
 *
 *     World ─▶ Sector (building) ─▶ Arena (room) ─▶ Game Object (furniture)
 *
 * mirrors Stanford generative_agents' `world:sector:arena:object` addressing,
 * but is self-contained in the visualization layer (no simulation changes).
 * Two jobs:
 *   1. STORE   — hold every interior object under a tree keyed by building/room.
 *   2. INDEX   — answer "where is the bed?", "which room serves `sleep`?",
 *                resolve a full address back to a node, list a room's objects.
 *
 * Geometry travels with the tree so the Phaser renderer can walk it directly:
 *   arena.geom  = {x,y,w,h} normalized within the building interior (0..1)
 *   object.geom = {x,y,w,h} normalized within its arena (0..1)
 *
 * Loaded as a plain <script> (exposes window.GAWorldSpatial) and also
 * require()-able under Node for tests (module.exports).
 */
(function () {
  "use strict";

  const WORLD = "GAWorld Village";

  // ---- tiny builders so blueprints stay terse + uniform ----
  const obj = (name, kind, x, y, w, h, slot) => ({ name, kind, x, y, w, h, slot: slot || null });
  const room = (name, type, x, y, w, h, door, objects) =>
    ({ name, type, x, y, w, h, door: door || "S", objects: objects || [] });

  // ===== room furniture kits (object x,y,w,h are 0..1 of the room) =====
  function bedroomKit() {
    return [
      obj("bed", "bed", 0.08, 0.10, 0.46, 0.34, "sleep"),
      obj("nightstand", "nightstand", 0.58, 0.12, 0.14, 0.14),
      obj("wardrobe", "wardrobe", 0.76, 0.10, 0.18, 0.30),
      obj("desk", "desk", 0.10, 0.64, 0.32, 0.18, "study"),
      obj("chair", "chair", 0.18, 0.83, 0.14, 0.12, "sit"),
      obj("plant", "plant", 0.80, 0.74, 0.12, 0.18),
    ];
  }
  function bathroomKit() {
    return [
      obj("sink", "sink", 0.12, 0.08, 0.30, 0.18, "wash"),
      obj("toilet", "toilet", 0.12, 0.60, 0.28, 0.30, "toilet"),
      obj("bathtub", "bathtub", 0.52, 0.18, 0.40, 0.64, "wash"),
    ];
  }
  function kitchenKit() {
    return [
      obj("counter", "counter", 0.06, 0.08, 0.60, 0.16, "cook"),
      obj("stove", "stove", 0.22, 0.10, 0.16, 0.12, "cook"),
      obj("fridge", "fridge", 0.74, 0.10, 0.16, 0.30),
      obj("sink", "sink", 0.06, 0.32, 0.20, 0.16, "wash"),
      obj("table", "table", 0.42, 0.56, 0.26, 0.26, "eat"),
      obj("chair", "chair", 0.40, 0.84, 0.10, 0.10, "sit"),
      obj("chair", "chair", 0.62, 0.84, 0.10, 0.10, "sit"),
    ];
  }
  function livingKit() {
    return [
      obj("plant", "plant", 0.05, 0.06, 0.12, 0.18),
      obj("tv", "tv", 0.06, 0.40, 0.30, 0.10),
      obj("sofa", "sofa", 0.06, 0.60, 0.34, 0.18, "watch"),
      obj("coffee_table", "coffee_table", 0.12, 0.82, 0.20, 0.10),
      obj("dining_table", "table", 0.46, 0.30, 0.24, 0.24, "eat"),
      obj("chair", "chair", 0.45, 0.17, 0.10, 0.10, "sit"),
      obj("chair", "chair", 0.62, 0.17, 0.10, 0.10, "sit"),
      obj("chair", "chair", 0.45, 0.56, 0.10, 0.10, "sit"),
      obj("chair", "chair", 0.62, 0.56, 0.10, 0.10, "sit"),
      obj("bookshelf", "bookshelf", 0.78, 0.06, 0.18, 0.16, "read"),
      obj("piano", "piano", 0.78, 0.30, 0.18, 0.36, "music"),
    ];
  }
  function studyKit() {
    return [
      obj("desk", "desk", 0.12, 0.20, 0.44, 0.22, "work"),
      obj("chair", "chair", 0.28, 0.46, 0.14, 0.14, "sit"),
      obj("bookshelf", "bookshelf", 0.10, 0.70, 0.80, 0.16, "read"),
      obj("plant", "plant", 0.80, 0.20, 0.12, 0.20),
    ];
  }
  function restroomKit() {
    return [
      obj("sink", "sink", 0.14, 0.10, 0.30, 0.20, "wash"),
      obj("toilet", "toilet", 0.16, 0.55, 0.28, 0.32, "toilet"),
      obj("sink", "sink", 0.58, 0.10, 0.30, 0.20, "wash"),
      obj("toilet", "toilet", 0.58, 0.55, 0.28, 0.32, "toilet"),
    ];
  }
  // beds stacked down the left, a shelf + plant on the right (hospital ward)
  function wardKit(n) {
    const out = [];
    const gap = 0.9 / n;
    for (let i = 0; i < n; i++) out.push(obj("bed", "bed", 0.06, 0.06 + i * gap, 0.46, gap * 0.78, "rest"));
    out.push(obj("shelf", "shelf", 0.80, 0.10, 0.14, 0.7));
    out.push(obj("plant", "plant", 0.62, 0.82, 0.12, 0.16));
    return out;
  }
  function consultKit() {
    return [
      obj("desk", "desk", 0.10, 0.18, 0.40, 0.20, "consult"),
      obj("chair", "chair", 0.24, 0.42, 0.14, 0.12, "sit"),
      obj("bed", "bed", 0.10, 0.62, 0.44, 0.26, "rest"),
      obj("shelf", "shelf", 0.78, 0.16, 0.16, 0.66),
    ];
  }
  // a row of shelves, used for shops + pharmacies (slot: shop)
  function shelfFloor(cols) {
    const out = [];
    const span = 0.92 / cols;
    for (let c = 0; c < cols; c++) out.push(obj("shelf", "shelf", 0.06 + c * span, 0.14, span * 0.6, 0.6, "shop"));
    out.push(obj("fridge", "fridge", 0.06, 0.82, 0.16, 0.14));
    return out;
  }
  // a grid of desks for classrooms (slot: study)
  function classroomKit() {
    const out = [obj("chalkboard", "chalkboard", 0.14, 0.04, 0.72, 0.08), obj("podium", "podium", 0.46, 0.16, 0.10, 0.10)];
    for (let r = 0; r < 2; r++) for (let c = 0; c < 3; c++) {
      out.push(obj("desk", "desk", 0.12 + c * 0.26, 0.34 + r * 0.28, 0.18, 0.12, "study"));
      out.push(obj("chair", "chair", 0.16 + c * 0.26, 0.48 + r * 0.28, 0.09, 0.09, "sit"));
    }
    return out;
  }
  function libraryKit() {
    const out = [];
    for (let c = 0; c < 4; c++) out.push(obj("bookshelf", "bookshelf", 0.06 + c * 0.16, 0.08, 0.12, 0.5, "read"));
    out.push(obj("desk", "desk", 0.30, 0.66, 0.40, 0.18, "read"));
    out.push(obj("chair", "chair", 0.36, 0.86, 0.10, 0.10, "sit"));
    out.push(obj("chair", "chair", 0.54, 0.86, 0.10, 0.10, "sit"));
    return out;
  }
  function cafeCounterKit() {
    return [
      obj("counter", "counter", 0.06, 0.16, 0.66, 0.14, "order"),
      obj("coffee_machine", "coffee_machine", 0.10, 0.04, 0.12, 0.12),
      obj("shelf", "shelf", 0.80, 0.12, 0.14, 0.7),
    ];
  }
  function seatingKit() {
    const out = [];
    for (let r = 0; r < 2; r++) for (let c = 0; c < 3; c++) {
      out.push(obj("table", "table", 0.10 + c * 0.28, 0.16 + r * 0.42, 0.14, 0.16, "eat"));
      out.push(obj("chair", "chair", 0.08 + c * 0.28, 0.34 + r * 0.42, 0.08, 0.08, "sit"));
      out.push(obj("chair", "chair", 0.20 + c * 0.28, 0.34 + r * 0.42, 0.08, 0.08, "sit"));
    }
    return out;
  }
  function receptionKit() {
    return [
      obj("desk", "desk", 0.16, 0.20, 0.52, 0.18, "work"),
      obj("chair", "chair", 0.36, 0.44, 0.14, 0.12, "sit"),
      obj("bench", "bench", 0.14, 0.74, 0.30, 0.10, "rest"),
      obj("plant", "plant", 0.80, 0.20, 0.12, 0.22),
    ];
  }
  function officeKit() {
    const out = [];
    for (let i = 0; i < 2; i++) {
      out.push(obj("desk", "desk", 0.12, 0.16 + i * 0.42, 0.42, 0.18, "work"));
      out.push(obj("chair", "chair", 0.28, 0.40 + i * 0.42, 0.14, 0.12, "sit"));
    }
    out.push(obj("plant", "plant", 0.80, 0.30, 0.12, 0.24));
    return out;
  }
  function meetingKit() {
    const out = [obj("table", "table", 0.22, 0.30, 0.56, 0.40, "meeting")];
    for (let c = 0; c < 3; c++) {
      out.push(obj("chair", "chair", 0.26 + c * 0.18, 0.16, 0.10, 0.10, "sit"));
      out.push(obj("chair", "chair", 0.26 + c * 0.18, 0.76, 0.10, 0.10, "sit"));
    }
    return out;
  }
  function pharmacyKit() {
    const out = [];
    for (let c = 0; c < 3; c++) out.push(obj("shelf", "shelf", 0.08 + c * 0.22, 0.12, 0.14, 0.6, "shop"));
    out.push(obj("counter", "counter", 0.08, 0.80, 0.6, 0.12, "shop"));
    return out;
  }
  function parkKit() {
    return [
      obj("tree", "tree", 0.08, 0.16, 0.16, 0.30),
      obj("tree", "tree", 0.78, 0.16, 0.16, 0.30),
      obj("tree", "tree", 0.10, 0.62, 0.16, 0.30),
      obj("fountain", "fountain", 0.42, 0.38, 0.18, 0.24, "rest"),
      obj("bench", "bench", 0.30, 0.74, 0.16, 0.06, "rest"),
      obj("bench", "bench", 0.58, 0.74, 0.16, 0.06, "rest"),
    ];
  }

  // ===== building blueprints (room x,y,w,h are 0..1 of the interior) =====
  // Rooms tile the unit square in horizontal bands; `spatial-tree.test` asserts
  // they stay in-bounds and never overlap, so edits are caught.
  const BLUEPRINTS = {
    residential: {
      category: "residential",
      rooms: [
        room("Bedroom 1", "bedroom", 0.00, 0.00, 0.30, 0.56, "S", bedroomKit()),
        room("Bathroom 1", "bathroom", 0.30, 0.00, 0.14, 0.56, "S", bathroomKit()),
        room("Bedroom 2", "bedroom", 0.44, 0.00, 0.30, 0.56, "S", bedroomKit()),
        room("Bathroom 2", "bathroom", 0.74, 0.00, 0.13, 0.56, "S", bathroomKit()),
        room("Study", "study", 0.87, 0.00, 0.13, 0.56, "S", studyKit()),
        room("Kitchen", "kitchen", 0.00, 0.56, 0.26, 0.44, "N", kitchenKit()),
        room("Living Room", "living", 0.26, 0.56, 0.46, 0.44, "N", livingKit()),
        room("Bedroom 3", "bedroom", 0.72, 0.56, 0.28, 0.44, "N", bedroomKit()),
      ],
    },
    medical: {
      category: "medical",
      rooms: [
        room("Reception", "reception", 0.00, 0.00, 0.34, 0.50, "S", receptionKit()),
        room("Ward A", "ward", 0.34, 0.00, 0.33, 0.50, "S", wardKit(3)),
        room("Ward B", "ward", 0.67, 0.00, 0.33, 0.50, "S", wardKit(3)),
        room("Consulting Room", "consult", 0.00, 0.50, 0.34, 0.50, "N", consultKit()),
        room("Pharmacy", "pharmacy", 0.34, 0.50, 0.33, 0.50, "N", pharmacyKit()),
        room("Restroom", "bathroom", 0.67, 0.50, 0.33, 0.50, "N", restroomKit()),
      ],
    },
    education: {
      category: "education",
      rooms: [
        room("Classroom 1", "classroom", 0.00, 0.00, 0.50, 0.55, "S", classroomKit()),
        room("Classroom 2", "classroom", 0.50, 0.00, 0.50, 0.55, "S", classroomKit()),
        room("Library", "library", 0.00, 0.55, 0.40, 0.45, "N", libraryKit()),
        room("Office", "office", 0.40, 0.55, 0.30, 0.45, "N", officeKit()),
        room("Restroom", "bathroom", 0.70, 0.55, 0.30, 0.45, "N", restroomKit()),
      ],
    },
    commerce: {
      category: "commerce",
      rooms: [
        room("Shop Floor", "shop", 0.00, 0.00, 0.72, 0.60, "S", shelfFloor(4)),
        room("Storeroom", "storeroom", 0.72, 0.00, 0.28, 0.60, "S", shelfFloor(2)),
        room("Checkout", "checkout", 0.00, 0.60, 0.40, 0.40, "N", [
          obj("checkout", "checkout", 0.16, 0.30, 0.30, 0.34, "shop"),
          obj("plant", "plant", 0.70, 0.30, 0.14, 0.34),
        ]),
        room("Cafe Corner", "seating", 0.40, 0.60, 0.32, 0.40, "N", [
          obj("table", "table", 0.20, 0.26, 0.24, 0.28, "eat"),
          obj("chair", "chair", 0.16, 0.60, 0.12, 0.12, "sit"),
          obj("chair", "chair", 0.40, 0.60, 0.12, 0.12, "sit"),
        ]),
        room("Restroom", "bathroom", 0.72, 0.60, 0.28, 0.40, "N", restroomKit()),
      ],
    },
    leisure: {
      category: "leisure",
      rooms: [
        room("Counter", "counter", 0.00, 0.00, 0.40, 0.55, "S", cafeCounterKit()),
        room("Kitchen", "kitchen", 0.40, 0.00, 0.30, 0.55, "S", kitchenKit()),
        room("Restroom", "bathroom", 0.70, 0.00, 0.30, 0.55, "S", restroomKit()),
        room("Seating", "seating", 0.00, 0.55, 1.00, 0.45, "N", seatingKit()),
      ],
    },
    government: {
      category: "government",
      rooms: [
        room("Reception", "reception", 0.00, 0.00, 0.34, 0.50, "S", receptionKit()),
        room("Office 1", "office", 0.34, 0.00, 0.33, 0.50, "S", officeKit()),
        room("Office 2", "office", 0.67, 0.00, 0.33, 0.50, "S", officeKit()),
        room("Meeting Room", "meeting", 0.00, 0.50, 0.50, 0.50, "N", meetingKit()),
        room("Archive", "library", 0.50, 0.50, 0.25, 0.50, "N", libraryKit()),
        room("Restroom", "bathroom", 0.75, 0.50, 0.25, 0.50, "N", restroomKit()),
      ],
    },
    park: {
      category: "leisure",
      outdoor: true,
      rooms: [room("Park", "park", 0.00, 0.00, 1.00, 1.00, null, parkKit())],
    },
  };
  // category aliases (match the renderer's existing fallbacks)
  BLUEPRINTS.industry = BLUEPRINTS.commerce;
  BLUEPRINTS.transit = BLUEPRINTS.government;
  BLUEPRINTS.mixed = BLUEPRINTS.residential;

  const PARK_RE = /park|公园|绿地|广场|garden|trail|greenbelt|playground|plaza/i;

  function blueprintFor(node) {
    const name = String((node && (node.label || node.id)) || "");
    if (PARK_RE.test(name)) return BLUEPRINTS.park;
    const cat = (node && node.category) || "residential";
    return BLUEPRINTS[cat] || BLUEPRINTS.residential;
  }

  // ===== the tree + its index/query API =====
  class SpatialTree {
    constructor(world) {
      this.world = world || WORLD;
      this.sectors = new Map();        // sector name -> { meta, arenas: Map }
      this._index = [];                // flat records for fast scanning
    }
    addSector(name, meta) {
      if (!this.sectors.has(name)) this.sectors.set(name, { meta: meta || {}, arenas: new Map() });
      return this;
    }
    addArena(sector, name, meta) {
      const s = this.sectors.get(sector); if (!s) return this;
      if (!s.arenas.has(name)) s.arenas.set(name, { meta: meta || {}, objects: new Map() });
      return this;
    }
    addObject(sector, arena, name, meta) {
      const s = this.sectors.get(sector); if (!s) return this;
      const a = s.arenas.get(arena); if (!a) return this;
      let key = name, i = 2;
      while (a.objects.has(key)) key = `${name} ${i++}`;   // keep object addresses unique
      const rec = Object.assign({ name: key, kind: name }, meta || {});
      a.objects.set(key, rec);
      this._index.push({
        world: this.world, sector, arena, object: key,
        kind: rec.kind, slot: rec.slot || null, geom: rec,
        address: [this.world, sector, arena, key].join(":"),
      });
      return this;
    }

    // --- read / traverse ---
    sectorNames() { return [...this.sectors.keys()]; }
    arenaNames(sector) { const s = this.sectors.get(sector); return s ? [...s.arenas.keys()] : []; }
    objectNames(sector, arena) { const s = this.sectors.get(sector); const a = s && s.arenas.get(arena); return a ? [...a.objects.keys()] : []; }
    arena(sector, name) { const s = this.sectors.get(sector); return s ? s.arenas.get(name) : null; }
    objects(sector, arena) {
      return this._index.filter((r) => (!sector || r.sector === sector) && (!arena || r.arena === arena));
    }

    // --- index / query ---
    // find by substring (matches object name OR kind) or by predicate(record)
    find(query) {
      if (typeof query === "function") return this._index.filter(query);
      const q = String(query || "").toLowerCase();
      return this._index.filter((r) => r.object.toLowerCase().includes(q) || String(r.kind).toLowerCase().includes(q));
    }
    locate(query) { return this.find(query)[0] || null; }
    bySlot(slot) { return this._index.filter((r) => r.slot === slot); }
    address(sector, arena, object) { return [this.world, sector, arena, object].filter(Boolean).join(":"); }
    resolve(address) {
      const parts = String(address || "").split(":");
      return this._index.find((r) => r.address === address)
        || (parts.length >= 4 ? this._index.find((r) => r.sector === parts[1] && r.arena === parts[2] && r.object === parts[3]) : null)
        || null;
    }

    // which room best hosts an activity slot? prefer a room owning a matching
    // object, else a room whose `type` matches, else the first room.
    arenaForActivity(sector, slot) {
      if (slot) {
        const hit = this._index.find((r) => r.sector === sector && r.slot === slot);
        if (hit) return hit.arena;
        const s = this.sectors.get(sector);
        if (s) for (const [name, a] of s.arenas) if (a.meta && a.meta.type === slot) return name;
      }
      return this.arenaNames(sector)[0] || null;
    }
    objectForActivity(sector, slot) {
      return this._index.find((r) => r.sector === sector && r.slot === slot) || null;
    }

    // building-space rect (0..1 of the interior) for an object record
    objectBuildingRect(rec) {
      const s = this.sectors.get(rec.sector); const a = s && s.arenas.get(rec.arena);
      if (!a || !a.meta) return null;
      const m = a.meta, g = rec.geom;
      return { x: m.x + g.x * m.w, y: m.y + g.y * m.h, w: g.w * m.w, h: g.h * m.h };
    }
  }

  // build a one-building tree from a citymap node
  function buildBuildingTree(node) {
    const bp = blueprintFor(node);
    const sector = String((node && (node.label || node.id)) || "Building");
    const tree = new SpatialTree(WORLD);
    tree.addSector(sector, { category: bp.category, outdoor: !!bp.outdoor });
    bp.rooms.forEach((r) => {
      tree.addArena(sector, r.name, { type: r.type, x: r.x, y: r.y, w: r.w, h: r.h, door: r.door, outdoor: !!bp.outdoor });
      r.objects.forEach((o) => tree.addObject(sector, r.name, o.name, { kind: o.kind, x: o.x, y: o.y, w: o.w, h: o.h, slot: o.slot }));
    });
    tree.sector = sector;            // convenience: the single building's name
    tree.outdoor = !!bp.outdoor;
    return tree;
  }

  const api = { WORLD, BLUEPRINTS, SpatialTree, buildBuildingTree, blueprintFor };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window !== "undefined") window.GAWorldSpatial = api;
})();
