/* Unit tests for spatial-tree.js — run with: node spatial-tree.test.js
 * Validates the room floor-plans tile cleanly and the store/index API works.
 */
const { SpatialTree, buildBuildingTree, BLUEPRINTS, blueprintFor, WORLD } = require("./spatial-tree.js");

let failures = 0;
const ok = (cond, msg) => { if (!cond) { failures++; console.error("  ✗ " + msg); } else console.log("  ✓ " + msg); };
const within01 = (v) => v >= -1e-9 && v <= 1 + 1e-9;
function overlap(a, b) {
  // true if rects overlap with real area (shared edges are fine)
  const ix = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const iy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  return ix > 1e-6 && iy > 1e-6;
}

console.log("\n[blueprints] every category tiles in-bounds, no overlaps, objects in-room");
const cats = Object.keys(BLUEPRINTS);
ok(cats.length >= 7, `defines ${cats.length} blueprints`);
let totalArea = 0, nChecked = 0;
for (const cat of cats) {
  const bp = BLUEPRINTS[cat];
  let area = 0;
  for (const r of bp.rooms) {
    ok(within01(r.x) && within01(r.y) && within01(r.x + r.w) && within01(r.y + r.h), `${cat}/${r.name}: room in [0,1]`);
    area += r.w * r.h;
    for (const o of r.objects) {
      const inb = within01(o.x) && within01(o.y) && within01(o.x + o.w) && within01(o.y + o.h);
      ok(inb, `${cat}/${r.name}/${o.name}: object in room bounds`);
    }
  }
  for (let i = 0; i < bp.rooms.length; i++)
    for (let j = i + 1; j < bp.rooms.length; j++)
      ok(!overlap(bp.rooms[i], bp.rooms[j]), `${cat}: rooms "${bp.rooms[i].name}" & "${bp.rooms[j].name}" don't overlap`);
  // non-outdoor plans should cover ~the whole interior
  if (!bp.outdoor) { ok(Math.abs(area - 1) < 0.02, `${cat}: rooms cover the interior (area=${area.toFixed(3)})`); totalArea += area; nChecked++; }
}

console.log("\n[tree] store: building → room → object");
const node = { id: "N-01", label: "N-01 Maple Court", category: "residential" };
const tree = buildBuildingTree(node);
ok(tree.world === WORLD, "world name set");
ok(tree.sectorNames().length === 1 && tree.sectorNames()[0] === "N-01 Maple Court", "one sector named after the building");
ok(tree.arenaNames(tree.sector).includes("Bedroom 1"), "sector contains Bedroom 1 arena");
ok(tree.objects(tree.sector).length > 20, `sector holds many objects (${tree.objects(tree.sector).length})`);

console.log("\n[tree] index: find / locate / address / resolve");
const beds = tree.find("bed");
ok(beds.length >= 3, `find('bed') → ${beds.length} matches across rooms`);
ok(beds.every((r) => r.address.split(":").length === 4), "addresses are world:sector:arena:object");
const loc = tree.locate("piano");
ok(loc && loc.arena === "Living Room", `locate('piano') → ${loc && loc.arena}`);
ok(tree.resolve(loc.address) === loc, "resolve(address) round-trips to the same record");
ok(tree.resolve("nope:nope:nope:nope") === null, "resolve(unknown) → null");

console.log("\n[tree] unique object addresses (duplicate names disambiguated)");
const addrs = tree.objects(tree.sector).map((r) => r.address);
ok(new Set(addrs).size === addrs.length, `all ${addrs.length} object addresses unique`);

console.log("\n[tree] activity → room/object routing");
ok(tree.bySlot("sleep").length >= 3, `bySlot('sleep') → ${tree.bySlot("sleep").length} beds`);
const ar = tree.arenaForActivity(tree.sector, "sleep");
ok(/Bedroom/.test(ar), `arenaForActivity('sleep') → ${ar}`);
ok(tree.arenaForActivity(tree.sector, "toilet").startsWith("Bathroom"), "arenaForActivity('toilet') → a bathroom");
ok(tree.arenaForActivity(tree.sector, "eat") !== null, "arenaForActivity('eat') resolves");
const cook = tree.objectForActivity(tree.sector, "cook");
ok(cook && cook.arena === "Kitchen", `objectForActivity('cook') → ${cook && cook.arena}`);

console.log("\n[tree] object building-space rect stays in [0,1]");
let allIn = true;
for (const rec of tree.objects(tree.sector)) {
  const b = tree.objectBuildingRect(rec);
  if (!b || !(within01(b.x) && within01(b.y) && within01(b.x + b.w) && within01(b.y + b.h))) { allIn = false; break; }
}
ok(allIn, "every object's building-space rect is within the interior");

console.log("\n[tree] park / outdoor + aliases + fallback");
const park = buildBuildingTree({ id: "P", label: "Riverside Park", category: "leisure" });
ok(park.outdoor === true, "park name → outdoor blueprint");
ok(blueprintFor({ category: "industry" }) === BLUEPRINTS.commerce, "industry aliases commerce");
ok(blueprintFor({ category: "weird-unknown" }) === BLUEPRINTS.residential, "unknown category falls back to residential");

console.log(`\n${failures ? "FAIL" : "PASS"} — ${failures} failure(s)\n`);
process.exit(failures ? 1 : 0);
