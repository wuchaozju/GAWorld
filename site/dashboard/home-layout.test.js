/* Unit tests for the home layout compiler (home-layout.js).
 *
 *   node site/dashboard/home-layout.test.js
 *
 * The compiler turns a resident's home design (rooms + furniture) into the
 * floor-plan tree the pixel renderer draws.
 */
"use strict";

const assert = require("assert");
const home = require("./home-layout.js");

let passed = 0;

function test(name, fn) {
  try {
    fn();
    passed += 1;
  } catch (err) {
    console.error("FAIL: " + name);
    console.error(err && err.message ? err.message : err);
    process.exit(1);
  }
}

const DESIGN = {
  home_id: "agent_1",
  home_node: "湖滨街道",
  rooms: {
    bedroom: { name: "卧室", size_sqm: 12, furniture: ["床", "床头柜", "衣柜", "窗帘"] },
    living_room: { name: "客厅", size_sqm: 18, furniture: ["沙发", "茶几", "电视", "地毯"] },
    dining_room: { name: "餐厅", size_sqm: 9, furniture: ["餐桌", "餐椅", "碗柜"] },
    kitchen: { name: "厨房", size_sqm: 8, furniture: ["灶台", "冰箱", "微波炉", "砧板"] },
    study: { name: "书房", size_sqm: 7, furniture: ["书桌", "电脑", "书柜", "台灯"] },
    bathroom: { name: "卫生间", size_sqm: 5, furniture: ["马桶", "洗手台", "淋浴"] },
  },
  at_home_activities: {
    bedroom: ["睡觉"],
    dining_room: ["吃饭"],
    kitchen: ["做饭"],
  },
};

test("maps furniture to the kinds the renderer draws", () => {
  assert.equal(home.furnitureKind("床").kind, "bed");
  assert.equal(home.furnitureKind("床").slot, "sleep");
  assert.equal(home.furnitureKind("灶台").kind, "stove");
  assert.equal(home.furnitureKind("灶台").slot, "cook");
  assert.equal(home.furnitureKind("餐桌").kind, "table");
  assert.equal(home.furnitureKind("餐桌").slot, "eat");
  assert.equal(home.furnitureKind("沙发").kind, "sofa");
  assert.equal(home.furnitureKind("书桌").kind, "desk");
  assert.equal(home.furnitureKind("马桶").kind, "toilet");
  // The bed head-board is not a bed.
  assert.equal(home.furnitureKind("床头柜").kind, "nightstand");
  // Things the renderer cannot draw are skipped, not drawn as junk.
  assert.equal(home.furnitureKind("地毯"), null);
});

test("every room of the design becomes an arena with a type", () => {
  const plan = home.buildHomePlan(DESIGN);
  const names = plan.arenaNames(plan.sector);
  assert.deepEqual(names, ["卧室", "客厅", "餐厅", "厨房", "书房", "卫生间"]);
  const living = plan.arena(plan.sector, "客厅");
  assert.equal(living.meta.type, "living");
  assert.equal(plan.arena(plan.sector, "餐厅").meta.type, "dining");
  assert.equal(plan.arena(plan.sector, "卧室").meta.type, "bedroom");
});

test("rooms tile the floor without overlapping", () => {
  const plan = home.buildHomePlan(DESIGN);
  const rooms = plan.rooms.map((room) => room.meta);
  for (const room of rooms) {
    assert.ok(room.x >= 0 && room.y >= 0, "room starts inside the plan");
    assert.ok(room.x + room.w <= 1.0001, "room ends inside the plan");
    assert.ok(room.y + room.h <= 1.0001, "room ends inside the plan");
  }
  for (let i = 0; i < rooms.length; i += 1) {
    for (let j = i + 1; j < rooms.length; j += 1) {
      const a = rooms[i];
      const b = rooms[j];
      const overlap = a.x < b.x + b.w - 1e-9 && b.x < a.x + a.w - 1e-9 &&
        a.y < b.y + b.h - 1e-9 && b.y < a.y + a.h - 1e-9;
      assert.ok(!overlap, `rooms ${i} and ${j} overlap`);
    }
  }
});

test("furniture sits inside its room and carries its slot", () => {
  const plan = home.buildHomePlan(DESIGN);
  const bed = plan.objects(plan.sector).find((rec) => rec.kind === "bed");
  assert.ok(bed, "the bed is in the plan");
  assert.equal(bed.arena, "卧室");
  assert.equal(bed.slot, "sleep");
  const room = plan.arena(plan.sector, bed.arena).meta;
  assert.ok(bed.geom.x >= 0 && bed.geom.y >= 0);
  assert.ok(bed.geom.x + bed.geom.w <= 1.0001);
  assert.ok(bed.geom.y + bed.geom.h <= 1.0001);
  // The stove serves cooking, the table serves eating.
  assert.equal(plan.objects(plan.sector, "厨房").find((rec) => rec.kind === "stove").slot, "cook");
  assert.equal(plan.objects(plan.sector, "餐厅").find((rec) => rec.kind === "table").slot, "eat");
});

test("the room that hosts an activity is found by its slot", () => {
  const plan = home.buildHomePlan(DESIGN);
  assert.equal(plan.arenaForActivity(plan.sector, "sleep"), "卧室");
  assert.equal(plan.arenaForActivity(plan.sector, "cook"), "厨房");
  assert.equal(plan.arenaForActivity(plan.sector, "eat"), "餐厅");
});

test("an empty design yields an empty plan instead of throwing", () => {
  const plan = home.buildHomePlan({});
  assert.deepEqual(plan.arenaNames(plan.sector), []);
  assert.equal(plan.arenaForActivity(plan.sector, "sleep"), null);
});

test("two rooms with the same name still get their own arena", () => {
  const plan = home.buildHomePlan({
    rooms: {
      bedroom: { name: "卧室", size_sqm: 12, furniture: ["床"] },
      bedroom_2: { name: "卧室", size_sqm: 10, furniture: ["床"] },
    },
  });
  const names = plan.arenaNames(plan.sector);
  assert.equal(new Set(names).size, 2, "arena names must be unique");
  // The room's own name stays on the label.
  assert.deepEqual(plan.rooms.map((room) => room.label), ["卧室", "卧室"]);
});

console.log("home-layout.test.js: " + passed + " passed");
