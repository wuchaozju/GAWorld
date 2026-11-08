(function () {
  'use strict';
  const core = window.OrganizationPickerCore;
  const select = document.getElementById('organizationMethodSelect');
  const note = document.getElementById('organizationMethodNote');
  const refresh = document.getElementById('organizationMethodRefresh');
  if (!select || !note || !core) return;
  let methods = [], entries = [], generation = 0, members = 0;
  const en = () => document.documentElement.lang.startsWith('en');
  const T = (zh, english) => en() ? english : zh;

  function selected() { return methods.find(m => m.id === select.value) || null; }
  function current() { return entries.find(e => e.id === select.value) || null; }
  function teamSize() {
    return document.querySelectorAll('#memberPicker .member-card.is-selected').length;
  }

  function changed() {
    const entry = current();
    const leader = document.getElementById('leaderSelect');
    if (leader) leader.disabled = Boolean(entry);
    document.querySelectorAll('#roleOverrides input').forEach(el => el.disabled = Boolean(entry));
    note.textContent = core.describe(entry, members, en());
  }

  function render(previous) {
    entries = core.entries(methods);
    select.replaceChildren(new Option(T('默认协作方式', 'Default cooperation'), ''));
    entries.forEach(entry => select.add(new Option(core.label(entry, en()), entry.id)));
    if (entries.some(entry => entry.id === previous)) select.value = previous;
    changed();
  }

  async function load() {
    const currentGeneration = ++generation, previous = select.value;
    try {
      const response = await fetch('/api/collaboration/organization-methods?include=builtin', { credentials: 'same-origin' });
      const result = await response.json();
      if (!response.ok || result.error) throw new Error(result.error || `HTTP ${response.status}`);
      if (currentGeneration !== generation) return;
      methods = result.methods || [];
      render(previous);
    } catch (e) {
      if (currentGeneration !== generation) return;
      note.textContent = T('读取组织方式失败：', 'Could not load methods: ') + e.message;
    }
  }

  select.addEventListener('change', changed);
  if (refresh) {
    refresh.addEventListener('click', function () {
      const run = () => load();
      if (typeof window.withButtonBusy === 'function') {
        window.withButtonBusy(refresh, 'oi3.refreshing', T('正在刷新…', 'Refreshing…'), run);
      } else {
        run();
      }
    });
  }
  // The team size decides how many roles a built-in structure runs with.
  document.addEventListener('collab:roster-change', function (event) {
    const count = Number((event.detail && event.detail.count) || 0);
    if (count === members) return;
    members = count;
    changed();
  });
  document.addEventListener('locale-changed', load);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
  window.addEventListener('focus', load);
  window.OrganizationMethodPicker = { selected, load };
  members = teamSize();
  load();
}());
