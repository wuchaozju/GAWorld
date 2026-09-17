"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("./core.js");


test("buildReport assembles the server's expected shape", () => {
  const report = core.buildReport({
    reportId: "abc",
    ts: 1000,
    tzOffset: 480,
    coords: {latitude: 30.27, longitude: 120.15, accuracy: 12},
    tag: "work",
    note: "  加班  ",
  });
  assert.equal(report.report_id, "abc");
  assert.equal(report.ts, 1000);
  assert.equal(report.tz_offset, 480);
  assert.equal(report.loc.lat, 30.27);
  assert.equal(report.loc.lng, 120.15);
  assert.equal(report.loc.acc_m, 12);
  assert.equal(report.loc.source, "gps");
  assert.equal(report.action_tag, "work");
  assert.equal(report.note, "加班");
});


test("buildReport marks manual fixes so the server can tell them apart", () => {
  const report = core.buildReport({
    reportId: "abc", ts: 1000, tzOffset: 0,
    coords: {latitude: 1, longitude: 2, accuracy: null},
    tag: "rest", note: "", manual: true,
  });
  assert.equal(report.loc.source, "manual");
  assert.equal(report.loc.acc_m, 0);
});


test("buildReport falls back to the other tag for an unknown one", () => {
  const report = core.buildReport({
    reportId: "a", ts: 1, tzOffset: 0,
    coords: {latitude: 1, longitude: 2, accuracy: 1},
    tag: "nonsense", note: "",
  });
  assert.equal(report.action_tag, "other");
});


test("queue drops reports the server has accepted, keeping the rest", () => {
  const queue = [{report_id: "a"}, {report_id: "b"}, {report_id: "c"}];
  assert.deepEqual(core.dropSynced(queue, ["a", "c"]), [{report_id: "b"}]);
});


test("queue is unchanged when nothing synced", () => {
  const queue = [{report_id: "a"}];
  assert.deepEqual(core.dropSynced(queue, []), [{report_id: "a"}]);
});


test("trailBounds covers every point with a non-zero span", () => {
  const bounds = core.trailBounds([
    {grid: {x: 0, y: 0}},
    {grid: {x: 4, y: 2}},
  ]);
  assert.equal(bounds.minX, 0);
  assert.equal(bounds.maxX, 4);
  assert.equal(bounds.minY, 0);
  assert.equal(bounds.maxY, 2);
});


test("trailBounds pads a single point so projection cannot divide by zero", () => {
  const bounds = core.trailBounds([{grid: {x: 3, y: 3}}]);
  assert.ok(bounds.maxX > bounds.minX);
  assert.ok(bounds.maxY > bounds.minY);
});


test("trailBounds on no points returns a usable unit box", () => {
  const bounds = core.trailBounds([]);
  assert.ok(bounds.maxX > bounds.minX);
  assert.ok(bounds.maxY > bounds.minY);
});


test("projectPoint maps grid coordinates into canvas pixels", () => {
  const bounds = {minX: 0, maxX: 10, minY: 0, maxY: 10};
  const mid = core.projectPoint({grid: {x: 5, y: 5}}, bounds, 100, 100, 0);
  assert.equal(mid.x, 50);
  assert.equal(mid.y, 50);
});


test("projectPoint flips the y axis so north is up", () => {
  const bounds = {minX: 0, maxX: 10, minY: 0, maxY: 10};
  const low = core.projectPoint({grid: {x: 0, y: 0}}, bounds, 100, 100, 0);
  const high = core.projectPoint({grid: {x: 0, y: 10}}, bounds, 100, 100, 0);
  assert.ok(high.y < low.y);
});


test("projectPoint honours padding", () => {
  const bounds = {minX: 0, maxX: 10, minY: 0, maxY: 10};
  const corner = core.projectPoint({grid: {x: 0, y: 0}}, bounds, 100, 100, 10);
  assert.equal(corner.x, 10);
});


test("visiblePoints returns the prefix up to a timestamp", () => {
  const points = [{ts: 1}, {ts: 2}, {ts: 3}];
  assert.deepEqual(core.visiblePoints(points, 2), [{ts: 1}, {ts: 2}]);
});


test("visiblePoints on an empty trail is empty", () => {
  assert.deepEqual(core.visiblePoints([], 5), []);
});


test("syncLabel reports synced state when the server says fresh", () => {
  assert.equal(core.syncLabel({fresh: true, report: {ts: 100}}, 160), "已同步");
});


test("syncLabel reports not-synced rather than showing a stale position", () => {
  assert.equal(core.syncLabel({fresh: false, report: {ts: 100}}, 99999), "未同步");
});


test("syncLabel handles an agent that has never reported", () => {
  assert.equal(core.syncLabel({fresh: false, report: null}, 100), "尚无上报");
});


test("intro shows only on a genuine first run", () => {
  assert.equal(core.shouldShowIntro(false, false), true);
});


test("intro is skipped once it has been seen", () => {
  assert.equal(core.shouldShowIntro(false, true), false);
});


test("intro never interrupts a user who already has a token", () => {
  // Cleared storage or a new device can lose the "seen" flag. Re-explaining
  // the product to a returning user is worse than never explaining it.
  assert.equal(core.shouldShowIntro(true, false), false);
  assert.equal(core.shouldShowIntro(true, true), false);
});


test("stateBars renders only numeric metrics", () => {
  const bars = core.stateBars({emotion: 0.7, stress: "bad", nonsense: 0.5});
  assert.deepEqual(bars.map(b => b.key), ["emotion"]);
  assert.equal(bars[0].percent, 70);
  assert.equal(bars[0].label, "情绪");
});


test("stateBars clamps out-of-range values", () => {
  const bars = core.stateBars({emotion: 1.8, stress: -0.4});
  const byKey = Object.fromEntries(bars.map(b => [b.key, b]));
  assert.equal(byKey.emotion.percent, 100);
  assert.equal(byKey.stress.percent, 0);
});


test("stateBars tones high-is-good and low-is-good metrics oppositely", () => {
  // Same numeric value, opposite meaning: 0.8 emotion is good, 0.8 stress is not.
  const bars = core.stateBars({emotion: 0.8, stress: 0.8});
  const byKey = Object.fromEntries(bars.map(b => [b.key, b]));
  assert.equal(byKey.emotion.tone, "good");
  assert.equal(byKey.stress.tone, "warn");
});


test("stateBars on empty state is empty", () => {
  assert.deepEqual(core.stateBars({}), []);
  assert.deepEqual(core.stateBars(null), []);
});


test("localDayKey uses the report's own timezone, not the reader's", () => {
  // 2026-08-08 23:30 UTC is already 2026-08-09 in UTC+8.
  const ts = Date.UTC(2026, 7, 8, 23, 30) / 1000;
  assert.equal(core.localDayKey({ts: ts, tz_offset: 480}), "2026-08-09");
  assert.equal(core.localDayKey({ts: ts, tz_offset: 0}), "2026-08-08");
});


test("groupReportsByDay preserves order and splits on local day", () => {
  const base = Date.UTC(2026, 7, 8, 23, 30) / 1000;
  const groups = core.groupReportsByDay([
    {report_id: "a", ts: base, tz_offset: 480},
    {report_id: "b", ts: base + 3600, tz_offset: 480},
    {report_id: "c", ts: base - 86400, tz_offset: 480},
  ]);
  assert.equal(groups.length, 2);
  assert.deepEqual(groups[0].reports.map(r => r.report_id), ["a", "b"]);
  assert.deepEqual(groups[1].reports.map(r => r.report_id), ["c"]);
});


test("groupReportsByDay on no reports is empty", () => {
  assert.deepEqual(core.groupReportsByDay([]), []);
});


test("auto-sample never fires while the page is hidden", () => {
  assert.equal(core.shouldAutoSample(0, 99999, 10, false), false);
  assert.equal(core.shouldAutoSample(null, 99999, 10, false), false);
});


test("auto-sample fires first time and then on interval", () => {
  assert.equal(core.shouldAutoSample(null, 1000, 10, true), true);
  assert.equal(core.shouldAutoSample(1000, 1000 + 9 * 60, 10, true), false);
  assert.equal(core.shouldAutoSample(1000, 1000 + 10 * 60, 10, true), true);
});


test("outOfMapNotice appears only for an out-of-map report", () => {
  assert.ok(core.outOfMapNotice({out_of_map: true}));
  assert.equal(core.outOfMapNotice({out_of_map: false}), "");
  assert.equal(core.outOfMapNotice(null), "");
});


test("outOfMapNotice says the position was recorded, not discarded", () => {
  const notice = core.outOfMapNotice({out_of_map: true, place: "北京"});
  assert.ok(notice.includes("已记录"));
  assert.ok(notice.includes("北京"));
  assert.ok(!notice.includes("不会同步"));
});


test("locationLabel prefers a matched map node", () => {
  assert.equal(
    core.locationLabel({out_of_map: false, node_id: "office"}), "office"
  );
});


test("locationLabel names an away position instead of calling it unknown", () => {
  assert.equal(
    core.locationLabel({out_of_map: true, node_id: null, place: "北京"}),
    "异地（北京）"
  );
});


test("locationLabel falls back to coordinates when there is no place name", () => {
  const label = core.locationLabel({
    out_of_map: true, node_id: null, place: "",
    loc: {lat: 51.5011, lng: -0.1246},
  });
  assert.equal(label, "异地（51.50, -0.12）");
});


test("locationLabel never returns blank for a real report", () => {
  assert.equal(core.locationLabel({out_of_map: true, node_id: null}), "异地");
});
