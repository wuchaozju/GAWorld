const test = require('node:test');
const assert = require('node:assert/strict');
const N = require('./navigation.js');
const tabs = [{id:'dashboard',src:'/dashboard'}, {id:'research',src:'/site/dashboard/research.html'}, ...N.tabs];

test('workspace links select personal views and preserve source selection', () => {
  assert.equal(N.consoleUrl('/workspace'), '/console#workspace');
  assert.equal(N.consoleUrl('/workspace?view=research&copied=p1'), '/console#myresearch?copied=p1');
  const route = N.resolve('publish?kind=plan&id=p1&world=w1', tabs);
  assert.equal(route.id, 'publish');
  const src = new URL(route.src, 'http://localhost');
  assert.equal(src.pathname, '/workspace');
  assert.equal(src.searchParams.get('view'), 'publish');
  assert.equal(src.searchParams.get('world'), 'w1');
});

test('public detail links preserve versions, filters and comment anchors', () => {
  const url = N.consoleUrl('/publications/p1?version=2#thread');
  assert.equal(url, '/console#explore/publications/p1?version=2&anchor=thread');
  const route = N.resolve(url.split('#')[1], tabs);
  assert.equal(route.id, 'explore');
  assert.equal(route.src, '/publications/p1?version=2#thread');
  assert.equal(N.consoleUrl('/posts/a1'), '/console#plaza/posts/a1');
  assert.equal(N.consoleUrl('/people/u1'), '/console#explore/people/u1');
  assert.equal(N.consoleUrl('/explore?tag=social'), '/console#explore?tag=social');
});

test('research links stay within the original workbench and legacy worlds work', () => {
  assert.equal(N.consoleUrl('/site/dashboard/research.html?plan_id=p1'), '/console#research?plan_id=p1');
  assert.equal(N.resolve('research?study_id=s1', tabs).src, '/site/dashboard/research.html?study_id=s1');
  assert.equal(N.resolve('worlds', tabs).src, '/site/dashboard/research.html?tab=worlds');
});

test('navigation never accepts foreign or arbitrary iframe destinations', () => {
  for (const url of ['https://evil.test/workspace', '//evil.test/explore', '/api/community/publications', '/workspace/other']) {
    assert.equal(N.consoleUrl(url), null, url);
  }
  for (const hash of ['explore/../../api/config', 'plaza/publications/x', 'explore/posts/x', 'research/other', 'bad']) {
    assert.equal(N.resolve(hash, tabs).id, 'dashboard', hash);
  }
  assert.equal(N.consoleUrl('/console#research'), '/console#research');
});

test('legacy static workspace entry uses the same integrated views', () => {
  assert.equal(N.consoleUrl('/site/community/workspace.html?view=account'), '/console#account');
});

test('replay and analytics links share one view and keep run/cursor parameters', () => {
  const resultsTabs = [...tabs,{id:'analytics',src:'/site/dashboard/analytics.html'}];
  assert.deepEqual(N.resolve('simviz?run=output%2Fworlds%2Fw1%2Fvisualization&frame=17&agent=2',resultsTabs), {
    id:'analytics',src:'/site/dashboard/analytics.html?run=output%2Fworlds%2Fw1%2Fvisualization&frame=17&agent=2',personal:undefined,
  });
  assert.equal(N.consoleUrl('/site/simviz/index.html?run=r1'),'/console#analytics?run=r1');
  assert.equal(N.consoleUrl('/site/dashboard/analytics.html?run=r1&view=analysis'),'/console#analytics?run=r1&view=analysis');
});
