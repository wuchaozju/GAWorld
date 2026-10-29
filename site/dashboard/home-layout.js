/* Home layout — turn a resident's home design into a floor plan.
 *
 * The home-environment plugin designs every resident's flat: rooms (living
 * room, bedroom, dining room, kitchen, …), the furniture in each room and how
 * big it is. The indoor renderer draws floor plans from a *tree* (rooms with
 * geometry, furniture with slots), so this module compiles the home design
 * into such a tree — the resident's own flat, with their own furniture.
 *
 *   const plan = buildHomePlan(home.design);
 *   plan.arenaNames(plan.sector);   // ["卧室", "厨房", …]
 *
 * Furniture names are Chinese ("床", "灶台", "餐桌"), so they are matched by
 * keyword against the kinds the pixel renderer knows how to draw (bed, sofa,
 * stove, …). The slot is what an activity needs to sit there: sleep → bed,
 * cook → stove, eat → dining table.
 */
(function (global) {
  "use strict";

  // Which room type the renderer paints each home room as (floor + rug style).
  const ROOM_TYPES = {
    living_room: "living",
    bedroom: "bedroom",
    bedroom_2: "bedroom",
    dining_room: "dining",
    kitchen: "kitchen",
    study: "study",
    bathroom: "bathroom",
    balcony: "living",
  };

  // Furniture name → [kind, slot]. First match wins; the kind is one the
  // pixel renderer draws, the slot is the activity it serves.
  const FURNITURE_RULES = [
    [/床(?!头柜)/, "bed", "sleep"],
    [/床头柜|床头灯/, "nightstand", null],
    [/衣柜/, "wardrobe", null],
    [/梳妆台|电视柜|柜台/, "counter", null],
    [/沙发/, "sofa", "watch"],
    [/茶几/, "coffee_table", null],
    [/电视/, "tv", null],
    [/冰箱/, "fridge", null],
    [/洗衣机/, "machine", null],
    [/微波炉|烤箱|电饭煲|电水壶|咖啡机/, "coffee_machine", null],
    [/抽油烟机|油烟机/, "machine", null],
    [/灶台|炉灶|灶/, "stove", "cook"],
    [/砧板|菜板/, "crate", null],
    [/餐桌|饭桌|饭桌|桌子/, "table", "eat"],
    [/书柜|书架/, "bookshelf", "read"],
    [/碗柜|餐边柜|柜/, "shelf", null],
    [/书桌|写字台/, "desk", "work"],
    [/椅/, "chair", "sit"],
    [/马桶/, "toilet", "toilet"],
    [/淋浴|浴缸/, "bathtub", "wash"],
    [/洗手台|水槽/, "sink", "wash"],
    [/毛巾/, "shelf", null],
    [/晾衣架/, "crate", null],
    [/花盆|绿植/, "plant", null],
    [/花瓶/, "crate", null],
    [/灯/, "crate", null],
    [
      /地毯|抱枕|窗帘|镜子|耳机|打印机|吹风机|遮阳伞|被子|床垫|电脑|显示器|音箱|地毯/,
      null,
      null,
    ],
  ];

  // Default footprint of each kind inside its room (0..1 of the room).
  const KIND_SIZES = {
    bed: [0.46, 0.34],
    sofa: [0.34, 0.18],
    chair: [0.12, 0.12],
    table: [0.24, 0.24],
    desk: [0.34, 0.18],
    coffee_table: [0.20, 0.10],
    bookshelf: [0.18, 0.16],
    wardrobe: [0.18, 0.30],
    counter: [0.50, 0.16],
    nightstand: [0.14, 0.14],
    fridge: [0.16, 0.30],
    stove: [0.16, 0.12],
    sink: [0.20, 0.16],
    toilet: [0.28, 0.32],
    bathtub: [0.40, 0.64],
    tv: [0.30, 0.10],
    plant: [0.12, 0.18],
    shelf: [0.20, 0.12],
    crate: [0.14, 0.12],
    machine: [0.16, 0.14],
    coffee_machine: [0.14, 0.16],
  };

  /** The (kind, slot) a piece of furniture maps to, or null when it is not drawn. */
  function furnitureKind(name) {
    const text = String(name || "");
    for (const [pattern, kind, slot] of FURNITURE_RULES) {
      if (pattern.test(text)) return kind ? { kind, slot } : null;
    }
    return null;
  }

  /** Rooms of a home design, in a stable order (the design's own order). */
  function homeRooms(design) {
    const rooms = (design && design.rooms) || {};
    return Object.keys(rooms).map((key) => {
      const room = rooms[key] || {};
      return {
        key,
        name: room.name || key,
        type: ROOM_TYPES[key] || "living",
        size_sqm: Number(room.size_sqm) || 0,
        furniture: Array.isArray(room.furniture) ? room.furniture : [],
      };
    });
  }

  // Pack the furniture of one room into a small grid of cells.
  function placeFurniture(room) {
    const items = [];
    for (const name of room.furniture) {
      const hit = furnitureKind(name);
      if (!hit || !hit.kind) continue;
      items.push({ name: String(name), kind: hit.kind, slot: hit.slot });
    }
    if (!items.length) return [];
    const cols = Math.min(3, Math.max(1, Math.ceil(Math.sqrt(items.length))));
    const rows = Math.ceil(items.length / cols);
    const cellW = 1 / cols;
    const cellH = 1 / rows;
    return items.map((item, index) => {
      const col = index % cols;
      const row = Math.floor(index / cols);
      const size = KIND_SIZES[item.kind] || [0.18, 0.14];
      const w = Math.min(size[0], cellW * 0.9);
      const h = Math.min(size[1], cellH * 0.9);
      const x = col * cellW + (cellW - w) / 2;
      const y = row * cellH + (cellH - h) / 2;
      return { ...item, x, y, w, h };
    });
  }

  /**
   * Build the floor-plan tree of a home design.
   *
   * The returned object answers the same questions the spatial tree does:
   * `arenaNames`, `arena`, `objects`, `arenaForActivity`, `objectBuildingRect`.
   */
  function buildHomePlan(design, options) {
    const opts = options || {};
    const rooms = homeRooms(design);
    const sector = String(opts.sector || "home");
    const tree = {
      sector,
      layoutType: "home",
      layoutLabel: opts.label || "家",
      world: "home",
      rooms: [],
      _arenas: new Map(),
      _objects: [],
    };

    tree.arenaNames = () => tree.rooms.map((room) => room.name);
    tree.arena = (_sector, name) => tree._arenas.get(name) || null;
    tree.objects = (_sector, arena) => tree._objects.filter((rec) => !arena || rec.arena === arena);
    tree.arenaForActivity = (_sector, slot) => {
      if (slot) {
        const hit = tree._objects.find((rec) => rec.slot === slot);
        if (hit) return hit.arena;
      }
      return tree.rooms.length ? tree.rooms[0].name : null;
    };
    tree.objectBuildingRect = (rec) => {
      const arena = tree._arenas.get(rec.arena);
      if (!arena) return null;
      const meta = arena.meta;
      return {
        x: meta.x + rec.geom.x * meta.w,
        y: meta.y + rec.geom.y * meta.h,
        w: rec.geom.w * meta.w,
        h: rec.geom.h * meta.h,
      };
    };

    if (!rooms.length) return tree;

    // Rooms in a grid: as square a block as the room count allows.
    const cols = Math.ceil(Math.sqrt(rooms.length));
    const rows = Math.ceil(rooms.length / cols);
    const gap = 0.015;
    const cellW = 1 / cols;
    const cellH = 1 / rows;

    rooms.forEach((room, index) => {
      const col = index % cols;
      const row = Math.floor(index / cols);
      const x = col * cellW + gap / 2;
      const y = row * cellH + gap / 2;
      const w = cellW - gap;
      const h = cellH - gap;
      // Arena names must be unique (the renderer looks rooms up by name); the
      // room's own name stays on the label.
      let arenaName = room.name;
      if (tree._arenas.has(arenaName)) {
        let i = 2;
        while (tree._arenas.has(`${room.name} ${i}`)) i += 1;
        arenaName = `${room.name} ${i}`;
      }
      const meta = { type: room.type, x, y, w, h, door: "S", label: room.name };
      tree._arenas.set(arenaName, { meta, objects: new Map() });
      tree.rooms.push({ key: room.key, name: arenaName, label: room.name, type: room.type, size_sqm: room.size_sqm, meta });

      for (const item of placeFurniture(room)) {
        const rec = {
          world: "home",
          sector,
          arena: arenaName,
          object: item.name,
          kind: item.kind,
          slot: item.slot || null,
          geom: { x: item.x, y: item.y, w: item.w, h: item.h },
          address: ["home", sector, arenaName, item.name].join(":"),
        };
        tree._objects.push(rec);
      }
    });

    return tree;
  }

  const api = { ROOM_TYPES, FURNITURE_RULES, furnitureKind, homeRooms, placeFurniture, buildHomePlan };
  global.GAWorldHome = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
