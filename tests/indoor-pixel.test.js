const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const spatial = require('../site/simviz/spatial-tree.js');

test('location uses identify distinct Chinese and English interior presets', () => {
  const cases = [
    ['湖畔小区', 'residential'], ['Park View Apartments', 'apartment'],
    ['乌镇宾馆', 'hotel'], ['市人民医院', 'medical'], ['社区卫生服务站', 'clinic'],
    ['和平药店', 'pharmacy'], ["Scott's College", 'education'], ['城市图书馆', 'library'],
    ['日用品超市', 'commerce'], ['Garden Cafe', 'cafe'], ['河畔餐厅', 'restaurant'],
    ['科技公司办公楼', 'office'], ['街道办事处', 'government'], ['纺织工厂', 'industry'],
    ['乌镇汽车站', 'transit'], ['阳光健身房', 'gym'], ['Riverside Park', 'park'],
  ];
  for (const [label, type] of cases) {
    const tree = spatial.buildBuildingTree({id: label, label, category: 'mixed'});
    assert.equal(tree.layoutType, type, label);
    assert.ok(tree.layoutLabel, 'exposes a readable layout type');
  }
  assert.notEqual(spatial.BLUEPRINTS.industry, spatial.BLUEPRINTS.commerce);
  assert.notEqual(spatial.BLUEPRINTS.transit, spatial.BLUEPRINTS.government);
});

test('specific uses override broad categories while explicit interior types take precedence', () => {
  for (const [node, expected] of [
    [{label:'Park Cafe', category:'leisure'}, 'cafe'],
    [{label:'Garden Hospital', category:'medical'}, 'medical'],
    [{label:'Park View Apartments', category:'residential'}, 'apartment'],
    [{label:'青禾诊所', category:'residential'}, 'clinic'],
    [{label:'A-21', category:'commerce', tags:{amenity:'library'}}, 'library'],
    [{label:'Main Hall', category:'commerce', building_type:'hotel'}, 'hotel'],
    [{label:'Main Hall', category:'leisure', tags:{leisure:'fitness_centre'}}, 'gym'],
    [{label:'Main Hall', category:'commerce', tags:{tourism:'hotel'}}, 'hotel'],
    [{label:'Main Hall', category:'residential', building_type:'house', tags:{amenity:'clinic'}}, 'clinic'],
    [{label:'Main Hall', category:'mixed', tags:{office:'architect'}}, 'office'],
    [{label:'学校旧址', category:'education', interior_type:'office'}, 'office'],
    [{label:'A-99', category:'medical'}, 'medical'],
    [{label:'A-99', category:'unknown'}, 'mixed'],
  ]) assert.equal(spatial.buildBuildingTree(node).layoutType, expected, JSON.stringify(node));
});

test('interior variants stay stable per place without changing shared blueprints', () => {
  const before = JSON.stringify(spatial.BLUEPRINTS);
  const snapshot = tree => tree.arenaNames(tree.sector).map(name => ({
    name, meta:tree.arena(tree.sector,name).meta,
    objects:tree.objects(tree.sector,name).map(o=>o.geom),
  }));
  const a = spatial.buildBuildingTree({id:'place-a', label:'住宅甲', category:'residential'});
  const aAgain = spatial.buildBuildingTree({id:'place-a', label:'住宅甲', category:'residential'});
  const b = spatial.buildBuildingTree({id:'place-b', label:'住宅乙', category:'residential'});
  assert.deepEqual(snapshot(a), snapshot(aAgain));
  assert.notDeepEqual(snapshot(a).map(r=>r.meta), snapshot(b).map(r=>r.meta),
    'same-purpose places can have different stable room arrangements');
  assert.equal(JSON.stringify(spatial.BLUEPRINTS), before);
});

test('every new preset and its mirrored variant has bounded furniture and a complete floor', () => {
  for (const type of ['residential','apartment','hotel','medical','clinic','pharmacy','education',
    'library','commerce','cafe','restaurant','office','government','industry','transit','gym','mixed','park']) {
    for (const id of ['place-a','place-b']) {
      const tree = spatial.buildBuildingTree({id, interior_type:type});
      assert.equal(tree.layoutType,type);
      const rooms = tree.arenaNames(tree.sector).map(name=>tree.arena(tree.sector,name).meta);
      assert.ok(Math.abs(rooms.reduce((sum,r)=>sum+r.w*r.h,0)-1)<1e-6);
      for (const r of rooms) assert.ok(r.x>=-1e-9 && r.y>=0 && r.x+r.w<=1+1e-9 && r.y+r.h<=1+1e-9);
      for (let i=0;i<rooms.length;i++) for (let j=i+1;j<rooms.length;j++) {
        const a=rooms[i], b=rooms[j];
        assert.ok(Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x)<1e-8 ||
          Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y)<1e-8, `${type}: rooms do not overlap`);
      }
      for (const rec of tree.objects(tree.sector)) {
        const box=tree.objectBuildingRect(rec);
        assert.ok(box.x>=-1e-9 && box.y>=0 && box.x+box.w<=1+1e-9 && box.y+box.h<=1+1e-9);
      }
    }
  }
});

function sceneFor(category = 'residential', width = 1000, height = 700, agents = []) {
  const calls = [], texts = [];
  const graphics = () => new Proxy({}, { get: (_, method) => (...args) => {
    calls.push({ method, args }); return {};
  } });
  class Scene { constructor(config) { this.config = config; } }
  const games = [];
  class Game { constructor(config) { games.push(this); this.config = config; } destroy() { this.destroyed = true; } }
  const sandbox = {
    document: { readyState: 'loading', addEventListener() {}, getElementById() { return null; } },
    window: { GAWorldSpatial: spatial }, Phaser: { Scene, Game, Scale: { NONE: 0, RESIZE: 5 }, Math: { Clamp: (n, lo, hi) => Math.max(lo, Math.min(hi, n)) } },
    performance: { now: () => 1000 }, console,
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../site/simviz/phaser-app.js'), 'utf8'), sandbox);
  const api = sandbox.window.__SIMVIZ__;
  api.state.trace = { map: { nodes: [{ id: 'home', label: '示例建筑', category }] } };
  api.state.frames = [{ agents }];
  const scene = new api.IndoorScene();
  scene.scale = { width, height, on() {}, off() {} };
  scene.cameras = { main: { setBackgroundColor() {} } };
  scene.events = { once() {} };
  scene.input = { on() {}, off() {} };
  scene.add = { graphics, text(x, y, text) {
    const label = { x, y, text, setOrigin() { return this; }, setDepth() { return this; },
      setInteractive() { return this; }, on() { return this; }, destroy() {} };
    texts.push(label); return label;
  } };
  scene.init({ nodeId: 'home' }); scene.create();
  return { scene, calls, texts, api, sandbox, games };
}

test('indoor scene paints every blueprint instead of returning a blank grass canvas', () => {
  for (const category of ['residential', 'apartment', 'hotel', 'medical', 'clinic', 'pharmacy',
    'education', 'library', 'commerce', 'cafe', 'restaurant', 'office', 'government', 'industry', 'transit', 'gym', 'mixed']) {
    const { scene, calls, texts } = sceneFor(category);
    assert.ok(texts.length >= scene.tree.arenaNames(scene.tree.sector).length, `${category} has room labels`);
    assert.ok(calls.filter(c => c.method === 'fillPath').length > 30, `${category} paints its furniture`);
    for (const call of calls) {
      assert.ok(call.args.filter(a => typeof a === 'number').every(Number.isFinite), `${category}: ${call.method} uses finite geometry`);
    }
  }
});

test('location presets route residents to their own facilities', () => {
  for (const [category, activity, roomType] of [
    ['gym','跑步健身','fitness'], ['industry','工作','workshop'], ['transit','休息','waiting'],
    ['library','阅读','library'], ['restaurant','吃饭','seating'], ['clinic','问诊','consult'],
  ]) {
    const {scene, api} = sceneFor(category, 1000, 700, [{agent_id:1,location:'home',activity}]);
    const spot = scene.residentPlacements[0];
    const scale = (scene.viewBounds.right-scene.viewBounds.left)/1860;
    const room = scene.tree.arenaNames(scene.tree.sector).map(name=>scene.tree.arena(scene.tree.sector,name).meta)
      .find(r=>spot.ux>=r.x*1100*scale && spot.ux<=(r.x+r.w)*1100*scale &&
        spot.uy>=r.y*760*scale && spot.uy<=(r.y+r.h)*760*scale);
    assert.equal(room?.type,roomType,category);
    if (category==='gym') assert.equal(api.activitySlot(activity),'exercise');
  }
});

test('resting residents sit on station benches and office sofas', () => {
  for (const category of ['transit','office']) {
    const {scene}=sceneFor(category,1000,700,[{agent_id:1,location:'home',activity:'休息'}]);
    assert.equal(scene.residentPlacements[0].pose,'sit',category);
    assert.ok(scene.residentPlacements[0].seat);
    assert.equal(scene.residentPlacements[0].lying,false);
  }
});

test('complete building fits both desktop and narrow canvases', () => {
  for (const [width, height] of [[1000, 700], [360, 252]]) {
    const { scene } = sceneFor('residential', width, height);
    assert.ok(scene.viewBounds, 'records fitted scene bounds');
    const b = scene.viewBounds;
    assert.ok(b.left >= 0 && b.right <= width && b.top >= 52 && b.bottom <= height - 20,
      `building fits ${width}x${height}: ${JSON.stringify(b)}`);
  }
});

test('connected residents are painted on the same depth-sorted layer as furniture', () => {
  const { scene, calls, texts } = sceneFor('residential', 1000, 700, [
    { agent_id: 1, name: '居民甲', location: 'home', activity: '做饭' },
    { agent_id: 2, name: '居民乙', location: 'home', activity: '睡觉' },
    { agent_id: 3, name: '居民丙', location: 'home', activity: '工作' },
    { agent_id: 4, name: '在路上', location: 'home', travel: { status: 'in_transit' } },
  ]);
  assert.equal(scene.gAgents, scene.gObjs);
  assert.ok(texts.some(t => t.text.includes('3 人在场')));
  assert.ok(texts.some(t => t.text.includes('居民甲')));
  assert.ok(!texts.some(t => t.text.includes('在路上')));
  assert.ok(calls.some(c => c.method === 'fillRect'));
});

test('each shared room boundary becomes one partition with an open doorway', () => {
  const { scene } = sceneFor();
  const rooms = [
    { x: 0, y: 0, w: 100, h: 100, meta: { door: 'S' } },
    { x: 0, y: 100, w: 100, h: 100, meta: { door: 'N' } },
  ];
  const partitions = scene.partitionEdgesOf(rooms[0], rooms).concat(scene.partitionEdgesOf(rooms[1], rooms));
  assert.equal(partitions.length, 1);
  assert.equal(partitions[0].door, true);
});

test('standing pixel characters reach the floor and never float above their shoes', () => {
  const { scene, calls } = sceneFor();
  calls.length = 0;
  scene.drawIsoAgent({ agent_id: 1, name: '甲' }, 100, 100, 0x0d8a73, false, false,
    { sx: 100, sy: 100, scale: 1 });
  const rects = calls.filter(c => c.method === 'fillRect').map(c => c.args);
  assert.ok(rects.length > 20, 'face, clothes and limbs have pixel details');
  const footY = 200;
  assert.ok(rects.every(([, y, , h]) => y >= footY - 80 && y + h <= footY + 2),
    'all character pixels stay within a connected, grounded body height');
});

test('working and resting residents keep their activity spot while the replay is paused', () => {
  const { scene } = sceneFor();
  const a = { agent_id: 1 };
  scene.wanderStep(a, 100, 100, 0, 0, 200, 200);
  scene.wander[1].hold = 0;
  const position = scene.wanderStep(a, 100, 100, 0, 0, 200, 200);
  assert.equal(position.x, 100);
  assert.equal(position.y, 100);
  assert.equal(position.walking, false);
});

test('sleep is on a mattress, work uses a chair, and cooking stands clear of the stove', () => {
  const { scene } = sceneFor('residential', 1000, 700, [
    { agent_id: 1, location: 'home', activity: '睡觉' },
    { agent_id: 2, location: 'home', activity: '工作' },
    { agent_id: 3, location: 'home', activity: '做饭' },
  ]);
  assert.ok(scene.residentPlacements);
  const [sleep, work, cook] = scene.residentPlacements;
  assert.equal(sleep.lying, true);
  assert.ok(sleep.depth > sleep.objectDepth, 'sleeping character paints above the mattress');
  assert.equal(work.pose, 'sit');
  assert.equal(cook.pose, 'stand');
  assert.ok(cook.uy > cook.objectFront, 'cooking character stands in front of furniture');
});

test('zoom enlarges indoor detail and reset restores the whole-building view', () => {
  const { scene } = sceneFor();
  const original = scene.viewBounds.right - scene.viewBounds.left;
  scene.setZoom(2);
  assert.ok(scene.viewBounds.right - scene.viewBounds.left > original * 1.9);
  scene.setZoom(1);
  assert.equal(scene.viewBounds.right - scene.viewBounds.left, original);
});

test('paused frames do not repeatedly destroy and recreate their scene', () => {
  const { scene, calls } = sceneFor();
  const before = calls.length;
  scene.update(1000); scene.update(2000);
  assert.equal(calls.length, before);
});

test('study furniture leaves the work chair visible in front of the rear bookcase', () => {
  const tree = spatial.buildBuildingTree({ category: 'residential' });
  const objects = tree.objects(tree.sector, 'Study');
  const bookcase = objects.find(o => o.kind === 'bookshelf').geom;
  const chair = objects.find(o => o.kind === 'chair').geom;
  assert.ok(bookcase.y + bookcase.h < chair.y);
});

test('rear shell walls paint before beds and desks', () => {
  const { scene } = sceneFor();
  const order = [];
  scene.drawIsoWall = (edge) => order.push(`wall:${edge.side}`);
  scene.drawIsoFurn = (rec) => order.push(`furniture:${rec.kind}`);
  scene.draw();
  assert.ok(order.indexOf('wall:N') < order.indexOf('furniture:bed'));
  assert.ok(order.indexOf('wall:W') < order.indexOf('furniture:desk'));
});

test('seated pelvis aligns with the chair surface while shoes reach the floor', () => {
  const { scene, calls } = sceneFor();
  calls.length = 0;
  scene.drawIsoAgent({ agent_id: 1, name: '甲' }, 100, 120, 0x0d8a73, false, false,
    { sx: 100, sy: 100, scale: 1 }, 'sit', { x: 100, y: 100, height: 27 });
  const beltIndex = calls.findIndex(c => c.method === 'fillStyle' && c.args[0] === 0x4b5849);
  const belt = calls.slice(beltIndex + 1).find(c => c.method === 'fillRect').args;
  assert.ok(Math.abs(belt[1] - 173) <= 1, `pelvis y=${belt[1]} should align with chair top y=173`);
  const bottom = Math.max(...calls.filter(c => c.method === 'fillRect').map(c => c.args[1] + c.args[3]));
  assert.ok(Math.abs(bottom - 210) <= 1, `shoes y=${bottom} should reach floor y=210`);
});

test('embedded renderer consumes its own frame and never changes the village state', () => {
  const { api, sandbox, games } = sceneFor();
  assert.equal(typeof sandbox.window.createIndoorRenderer, 'function');
  const renderer = sandbox.window.createIndoorRenderer({});
  const node = { id: 'office', label: '办公室', category: 'government' };
  const frame = { agents: [{ agent_id: 7, location: '办公室', activity: '工作' }] };
  const trace = { map: { nodes: [node] } };
  renderer.render(trace, frame, node, 7);
  const embedded = games[0].config.scene[0];
  assert.equal(embedded.viewState.frames[0], frame);
  assert.equal(embedded.viewState.selectedId, 7);
  assert.equal(embedded.nodeId, 'office');
  assert.equal(api.state.trace.map.nodes[0].id, 'home');
  assert.equal(embedded.embedded, true);
  renderer.destroy();
  assert.equal(games[0].destroyed, true);
});

test('embedded canvas keeps a valid buffer when its console iframe is hidden', () => {
  const { sandbox, games } = sceneFor();
  const host = { clientWidth: 800, clientHeight: 560 };
  const renderer = sandbox.window.createIndoorRenderer(host);
  const game = games[0], sizes = [];
  assert.equal(game.config.scale.mode, sandbox.Phaser.Scale.NONE,
    'Phaser must not automatically resize hidden iframes to 0x0');
  assert.equal(game.config.scale.width, 800);
  assert.equal(game.config.scale.height, 560);
  game.scale = { resize: (w, h) => {
    assert.ok(w > 0 && h > 0, 'WebGL attachments require positive dimensions');
    sizes.push([w, h]);
  } };
  renderer.resize();
  assert.equal(sizes.length, 0, 'waits until Phaser has booted');
  game.isBooted = true;
  renderer.resize();
  host.clientWidth = 0; host.clientHeight = 0;
  renderer.resize();
  host.clientWidth = 684; host.clientHeight = 366;
  renderer.resize();
  assert.deepEqual(sizes, [[800, 560], [684, 366]],
    'preserves its buffer while hidden and fits again when shown');
});

test('changing runs or clearing a frame invalidates embedded building and resident state', () => {
  const { sandbox, games } = sceneFor();
  assert.equal(typeof sandbox.window.createIndoorRenderer, 'function');
  const renderer = sandbox.window.createIndoorRenderer({});
  const first = { id: 'home', category: 'residential' }, second = { id: 'home', category: 'medical' };
  renderer.render({map: {nodes: [first]}}, {agents: [{agent_id: 1}]}, first, null);
  const embedded = games[0].config.scene[0];
  embedded.tree = { old: true }; embedded.wander = {1: {}};
  renderer.render({map: {nodes: [second]}}, {agents: [{agent_id: 2}]}, second, null);
  assert.equal(embedded.tree, null);
  assert.equal(Object.keys(embedded.wander).length, 0);
  assert.equal(embedded.viewState.frames[0].agents[0].agent_id, 2);
  renderer.render(null, null, null, null);
  assert.equal(embedded.nodeId, null);
  assert.equal(embedded.viewState.frames.length, 0);
});

function indoorUi() {
  class Element {
    constructor() { this.children = []; this.listeners = {}; this.style = {}; this.dataset = {}; this.hidden = false; this.clientWidth = 800; this.clientHeight = 560; this.classList = { add() {}, toggle() {} }; }
    append(...children) { this.children.push(...children); }
    addEventListener(name, fn) { this.listeners[name] = fn; }
    setAttribute(name, value) { this[name] = value; }
    click() { this.listeners.click?.(); }
    getClientRects() { return this.hidden ? [] : [{}]; }
  }
  const city = new Element(), cityBtn = new Element(), indoorBtn = new Element(), host = new Element();
  cityBtn.dataset.sceneMode = 'city'; indoorBtn.dataset.sceneMode = 'indoor';
  const root = { querySelectorAll: () => [cityBtn, indoorBtn], querySelector: () => city };
  host.closest = () => root;
  const calls = [], zooms = [], renderers = [];
  const global = { GAWorldSpatial: spatial, createIndoorRenderer() {
    const renderer = { render: (...args) => calls.push(args), resize() {}, setZoom: value => zooms.push(value), destroy() {} };
    renderers.push(renderer); return renderer;
  } };
  const sandbox = { window: global, document: { getElementById: () => ({}), createElement: () => new Element() } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../site/dashboard/indoor-view.js'), 'utf8'), sandbox);
  const view = new global.IndoorView(host, { getSelectedAgentId: () => 2 });
  return {view, host, city, cityBtn, indoorBtn, calls, zooms, renderers};
}

test('live and replay UI switch to the shared pixel renderer using the current frame', () => {
  const {view, host, city, indoorBtn, cityBtn, calls} = indoorUi();
  assert.equal(host.hidden, true, 'starts in city mode');
  const trace = {map: {nodes: [{id: 'home', label: '住宅', category: 'residential'}]}};
  const frame = {agents: [{agent_id: 2, location: '住宅', activity: '睡觉'}]};
  view.setTrace(trace); view.render(frame);
  indoorBtn.click();
  assert.equal(host.hidden, false); assert.equal(city.hidden, true);
  assert.equal(calls.at(-1)[0], trace); assert.equal(calls.at(-1)[1], frame);
  assert.equal(calls.at(-1)[2].id, 'home'); assert.equal(calls.at(-1)[3], 2);
  const next = {agents: [{agent_id: 2, location: '学校', activity: '学习'}]};
  view.render(next);
  assert.equal(calls.at(-1)[1], next); assert.equal(calls.at(-1)[2].id, '学校');
  cityBtn.click();
  assert.equal(host.hidden, true); assert.equal(city.hidden, false);
});

test('changing trace clears a pinned building and clearing frames clears the pixel view', () => {
  const {view, indoorBtn, calls} = indoorUi();
  indoorBtn.click();
  view.pinned = '旧住处';
  view.setTrace({map: {nodes: []}});
  assert.equal(view.pinned, '');
  view.render(null);
  assert.equal(calls.at(-1)[1], null);
  assert.equal(calls.at(-1)[2], null);
});

test('actual empty places are selectable and expose their indoor use', () => {
  const {view, indoorBtn, calls} = indoorUi();
  const clinic = {id:'clinic-1', label:'乌镇社区卫生服务站', category:'medical', kind:'place'};
  view.setTrace({map:{nodes:[clinic]}});
  view.render({agents:[]});
  assert.ok(view.select.innerHTML.includes(clinic.label), 'includes place nodes, not only hubs');
  view.select.value=clinic.label; view.select.listeners.change(); indoorBtn.click();
  assert.equal(calls.at(-1)[2],clinic);
  assert.ok(view.subEl.textContent.includes('诊所'),view.subEl.textContent);
});

async function replayUi() {
  const elements = new Map();
  for (const id of ['runSelect', 'mapCanvas', 'timeline', 'playBtn', 'latestBtn', 'refreshBtn', 'speedSelect', 'statusText', 'frameStamp', 'frameTitle', 'agentList', 'indoorView']) {
    elements.set(id, {value: '', listeners: {}, addEventListener(name, fn) {this.listeners[name] = fn;},
      getBoundingClientRect: () => ({width: 800, height: 600})});
  }
  const calls = [];
  let runs = [{id: 'one', trace_url: '/one.json'}];
  const trace = {frames: [{agents: [{agent_id: 1, location: '住宅'}]}, {agents: [{agent_id: 2, location: '学校'}]}]};
  const global = {
    document: {getElementById: id => elements.get(id), addEventListener() {}},
    addEventListener() {}, location: {search: ''},
    CityMapView: class {setTrace(trace) {this.trace = trace;} render() {} renderEmpty() {}},
    IndoorView: class {setTrace(t) {this.trace = t;} render(frame) {calls.push({trace: this.trace, frame});}},
  };
  const sandbox = {window: global, URLSearchParams, fetch: async url => ({ok: true, json: async () => url.startsWith('/api/replay/runs') ? {runs} : trace})};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../site/simviz/replay.js'), 'utf8'), sandbox);
  const state = global.GAWorldReplay.attachUi(global.document);
  await new Promise(setImmediate);
  return {state, calls, elements, emptyRuns: () => {runs = [];}};
}

test('replay scrubbing supplies the same exact frame to the pixel indoor mode', async () => {
  const {state, calls, elements} = await replayUi();
  assert.equal(calls.at(-1).frame, state.trace.frames[1]);
  elements.get('timeline').value = '0'; elements.get('timeline').listeners.input();
  assert.equal(calls.at(-1).frame, state.trace.frames[0]);
});

test('refreshing an empty replay run list removes the previous indoor residents', async () => {
  const {state, calls, elements, emptyRuns} = await replayUi();
  emptyRuns(); elements.get('refreshBtn').listeners.click();
  await new Promise(setImmediate);
  assert.equal(state.trace, null);
  assert.equal(state.view.trace, null);
  assert.equal(calls.at(-1).trace, null);
  assert.equal(calls.at(-1).frame, undefined);
});

test('selecting a replay resident updates the indoor follow target', async () => {
  const {state, elements} = await replayUi();
  assert.equal(typeof elements.get('agentList').listeners.click, 'function');
  elements.get('agentList').listeners.click({target: {closest: () => ({dataset: {agentId: '2'}})}});
  assert.equal(state.selectedId, 2);
});

test('building labels and node ids count the same physically present residents', () => {
  const indoor = require('../site/dashboard/indoor-view.js');
  const node = {id: 'home-1', label: '住宅一'};
  const frame = {agents: [{agent_id: 1, resolved_location: 'home-1'},
    {agent_id: 2, resolved_location: '住宅一'},
    {agent_id: 3, resolved_location: 'home-1', travel: {status: 'in_transit'}}]};
  assert.equal(indoor.agentsAt(frame, '住宅一', node).length, 2);
});
