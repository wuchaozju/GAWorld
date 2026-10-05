const test = require("node:test");
const assert = require("node:assert/strict");

const { thoughtOf, planSegments } = require("./agent-thought.js");
const indoor = require("./indoor-view.js");
const spatial = require("../simviz/spatial-tree.js");

const PLAN = "目标：尽快入睡养精蓄锐应对明天陪诊；顾虑：已近凌晨一点；打算：洗漱后尽快上床休息；预期：明早按时出门";

test("splits a labelled plan into its segments", () => {
  const segs = planSegments(PLAN);
  assert.equal(segs["目标"], "尽快入睡养精蓄锐应对明天陪诊");
  assert.equal(segs["打算"], "洗漱后尽快上床休息");
  assert.deepEqual(planSegments("just a sentence"), {});
});

test("the main thought is the plan's goal", () => {
  assert.equal(thoughtOf({ plan: PLAN, perception: "夜深了。" }), "尽快入睡养精蓄锐应对明天陪诊");
  assert.equal(thoughtOf({ plan: "打算：先吃饭" }), "先吃饭");
});

test("falls back to the first sentence of an unlabelled plan, then the perception", () => {
  assert.equal(thoughtOf({ plan: "Finish the draft. Then rest." }), "Finish the draft.");
  assert.equal(thoughtOf({ plan: "", perception: "夜深了，屋里很安静。今天没怎么说话。" }), "夜深了，屋里很安静");
  assert.equal(thoughtOf({ action: "去买菜" }), "去买菜");
  assert.equal(thoughtOf({}), "");
  assert.equal(thoughtOf(null), "");
});

test("clips long thoughts to the requested length", () => {
  const text = thoughtOf({ plan: "目标：" + "很".repeat(100) }, 10);
  assert.equal(Array.from(text).length, 10);
  assert.ok(text.endsWith("…"));
});

test("maps activities to furniture slots", () => {
  assert.equal(indoor.activitySlot("睡觉"), "sleep");
  assert.equal(indoor.activitySlot("做饭"), "cook");
  assert.equal(indoor.activitySlot("咖啡馆避雨办公"), "order");
  assert.equal(indoor.activitySlot("处理待办"), null);
});

const frame = {
  agents: [
    { agent_id: 1, location: "湖滨街道", activity: "睡觉" },
    { agent_id: 2, resolved_location: "湖滨街道", activity: "做饭" },
    { agent_id: 3, location: "工联CC", activity: "工作" },
    { agent_id: 4, location: "龙翔桥", travel: { status: "in_transit" } },
  ],
};

test("lists occupied places busiest first, without people on the road", () => {
  assert.deepEqual(indoor.occupiedLocations(frame), [
    { name: "湖滨街道", count: 2 },
    { name: "工联CC", count: 1 },
  ]);
  assert.deepEqual(indoor.agentsAt(frame, "龙翔桥"), []);
});

test("picks the pinned place, then the selected resident's, then the busiest", () => {
  assert.equal(indoor.pickLocation(frame, 3, "龙翔桥"), "龙翔桥");
  assert.equal(indoor.pickLocation(frame, 3, ""), "工联CC");
  assert.equal(indoor.pickLocation(frame, 4, ""), "湖滨街道");
  assert.equal(indoor.pickLocation({ agents: [] }, null, ""), null);
});

test("seats residents at the furniture their activity needs, one per object", () => {
  const tree = spatial.buildBuildingTree({ label: "湖滨街道", category: "residential" });
  const seats = indoor.placeAgents(tree, [
    { agent_id: 1, activity: "睡觉" },
    { agent_id: 2, activity: "睡觉" },
    { agent_id: 3, activity: "做饭" },
    { agent_id: 4, activity: "处理待办" },
  ]);
  assert.match(seats[0].room, /Bedroom/);
  assert.match(seats[1].room, /Bedroom/);
  assert.notDeepEqual([seats[0].x, seats[0].y], [seats[1].x, seats[1].y]);
  assert.equal(seats[2].room, "Kitchen");
  assert.equal(seats[3].room, "Living Room");
  for (const s of seats) {
    assert.ok(s.x >= 0 && s.x <= 1 && s.y >= 0 && s.y <= 1);
  }
});

test("a crowd without free furniture spreads around the room", () => {
  const tree = spatial.buildBuildingTree({ label: "店", category: "commerce" });
  const seats = indoor.placeAgents(tree, Array.from({ length: 4 }, (_, i) => ({ agent_id: i, activity: "闲聊" })));
  const spots = new Set(seats.map((s) => `${s.x.toFixed(3)},${s.y.toFixed(3)}`));
  assert.equal(spots.size, 4);
});

test("a block of flats shows one flat: the selected resident's, else the fullest", () => {
  const here = [
    { agent_id: 1, room: { unit: "1A", arena: "Kitchen" } },
    { agent_id: 2, room: { unit: "2B", arena: "Bedroom 1" } },
    { agent_id: 3, room: { unit: "2B", arena: "Living Room" } },
    { agent_id: 4 },
  ];
  const busiest = spatial.flatView(here, null);
  assert.equal(busiest.unit, "2B");
  assert.equal(busiest.units, 2);
  assert.deepEqual(busiest.agents.map((a) => a.agent_id), [2, 3, 4]);
  assert.deepEqual(spatial.flatView(here, 1).agents.map((a) => a.agent_id), [1, 4]);
  // traces without rooms are shown as before
  const plain = [{ agent_id: 5 }, { agent_id: 6 }];
  assert.deepEqual(spatial.flatView(plain, 5), { unit: "", units: 0, agents: plain });
});
