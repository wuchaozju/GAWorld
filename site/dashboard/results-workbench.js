/* One run, one time cursor, one resident focus. No simulation/model calls. */
(function () {
  'use strict';
  if (!document.body.hasAttribute('data-results-workbench')) return;
  const C = window.GAWorldResultsCore;
  const $ = id => document.getElementById(id);
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const t = (key, params) => params ? window.__f('results.' + key, params) : window.__('results.' + key);
  const metricLabel = key => window.__('an.metric_' + key, key);
  const initial = new URLSearchParams(location.search);
  let viewInteracted = false;
  const state = {
    runs:[], run:null, trace:null, index:0, resident:null, metrics:[], roster:[], events:[], times:[],
    view:['analysis','system'].includes(initial.get('view')) ? initial.get('view') : 'replay',
    request:0, timer:null, analyticsRun:null, series:new Map(), loading:false, initialApplied:false,
  };
  const map = new window.CityMapView($('mapCanvas'), {
    getSelectedAgentId:() => state.resident,
    onSelectAgent:id => selectResident(String(id)),
    showThoughts:true,
  });
  const indoor = window.IndoorView ? new window.IndoorView($('indoorView'), {getSelectedAgentId:() => state.resident}) : null;

  async function json(url, signal) {
    const response = await fetch(url, {cache:'no-store', signal});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }
  function frameLabel(frame, index) {
    if (!frame) return '—';
    return [frame.date || (frame.day != null ? t('day',{day:frame.day}) : ''), frame.time || frame.time_str || ''].filter(Boolean).join(' · ') || t('frame',{index:index+1});
  }
  function runName(run) {
    const parts = String(run.label || run.id).split('/').filter(Boolean);
    return parts.filter(part => !['cities','worlds','parallel_worlds','visualization'].includes(part)).join(' / ') || run.label || run.id;
  }
  function message(text) { $('resultsMessage').hidden = !text; $('resultsMessage').textContent = text || ''; }
  function syncUrl() {
    const url = new URL(location.href);
    if (state.run) url.searchParams.set('run',state.run.id);
    url.searchParams.set('view',state.view);
    url.searchParams.set('frame',String(state.index));
    if (state.resident != null) url.searchParams.set('agent',state.resident); else url.searchParams.delete('agent');
    history.replaceState(null,'',url);
    // Keep browser refresh/back/share in the parent on the same run and cursor.
    try {
      if (window.parent !== window && window.parent.location.pathname === '/console') {
        const parentUrl = new URL(window.parent.location.href);
        parentUrl.hash = 'analytics?' + url.searchParams.toString();
        window.parent.history.replaceState(null,'',parentUrl);
        const openNew = window.parent.document.getElementById('openNew');
        if (openNew) openNew.href = url.pathname + url.search;
      }
    } catch (_) { /* Standalone or cross-origin embed. */ }
  }
  function stop() {
    clearInterval(state.timer); state.timer = null;
    $('playBtn').textContent = t('play');
    $('playBtn').setAttribute('aria-pressed','false');
  }
  function seek(index) {
    const count = (state.trace && state.trace.frames || []).length;
    state.index = Math.max(0,Math.min(Math.max(0,count-1),Number(index) || 0));
    renderFrame(); syncUrl();
  }
  function play() {
    if (state.timer) return stop();
    const count = (state.trace && state.trace.frames || []).length;
    if (count < 2) return;
    if (state.index >= count-1) seek(0);
    $('playBtn').textContent = t('pause');
    $('playBtn').setAttribute('aria-pressed','true');
    state.timer = setInterval(() => {
      const next = C.advance(state.index,count);
      seek(next.index);
      if (next.done) stop();
    },Number($('speedSelect').value));
  }
  function selectedSeries(metric, id) {
    const key = JSON.stringify([metric,id]);
    if (!state.series.has(key)) state.series.set(key,C.series(state.trace,metric,id));
    return state.series.get(key);
  }
  function selectResident(id) {
    state.resident = state.roster.some(agent => agent.id === id) ? id : null;
    $('residentSelect').value = state.resident || '';
    if (window.GAWorldAnalytics) window.GAWorldAnalytics.focus(state.resident);
    renderFrame(); syncUrl();
  }
  function renderRuns() {
    const search = $('runSearch').value.trim().toLowerCase(), kind = $('runKind').value;
    const runs = state.runs.filter(run => (!kind || run.kind === kind) &&
      [run.label,run.id,run.generated_at,run.last_updated].join(' ').toLowerCase().includes(search));
    $('runCount').textContent = t('run_count',{count:runs.length});
    const selected = state.run;
    const options = runs.slice();
    // Filtering does not silently change the open run.
    if (selected && !options.some(run => run.id === selected.id)) options.unshift(selected);
    $('anRunSelect').innerHTML = options.length ? options.map(run => {
      const date = run.generated_at ? new Date(run.generated_at).toLocaleDateString(window.getLocale && window.getLocale() === 'en' ? 'en-GB' : 'zh-CN') : '';
      const source = t(run.kind === 'live' ? 'current_source' : run.kind === 'archive' ? 'archives' : 'scenarios');
      return `<option value="${esc(run.id)}">${esc(runName(run))} · ${esc(date)} · ${esc(t('frames',{count:run.frame_count || 0}))} · ${esc(source)}</option>`;
    }).join('') : `<option value="">${esc(t('no_matching_runs'))}</option>`;
    if (selected) $('anRunSelect').value = selected.id;
    $('anRunSelect').disabled = !options.length;
  }
  function renderSummary() {
    const frames = state.trace && state.trace.frames || [];
    const run = state.run;
    $('runHealth').innerHTML = run ? `<strong>${esc(t(run.finished ? 'finished' : 'unfinished'))}</strong> · ${esc(t('storage_copies',{count:run.aliases.length}))}` : '';
    const values = [
      [t('selected_run'),run ? runName(run) : '—'],
      [t('recorded_residents'),state.roster.length],
      [t('recorded_frames'),frames.length],
      [t('recorded_range'),frames.length ? [frames[0].day,frames.at(-1).day].every(day=>day != null) ? t('day_range',{first:frames[0].day,last:frames.at(-1).day}) : t('sample_order') : '—'],
    ];
    $('runSummary').innerHTML = values.map(([label,value])=>`<article><span>${esc(label)}</span><strong>${esc(value)}</strong></article>`).join('');
  }
  function renderRoster() {
    $('residentSelect').innerHTML = `<option value="">${esc(t('population'))}</option>` + state.roster.map(agent=>`<option value="${esc(agent.id)}">${esc(agent.name)}</option>`).join('');
    $('residentSelect').value = state.resident || '';
    $('residentSelect').disabled = !state.roster.length;
  }
  function renderMetrics() {
    const available = C.metrics(state.trace);
    const button = metric=>`<button type="button" data-result-metric="${esc(metric)}" aria-pressed="${state.metrics.includes(metric)}">${esc(metricLabel(metric))}</button>`;
    const remaining = available.filter(metric=>!state.metrics.includes(metric));
    $('metricPicker').innerHTML = state.metrics.map(button).join('') + (remaining.length ? `<details class="results-more-metrics"><summary>${esc(t('more_metrics'))}</summary><div>${remaining.map(button).join('')}</div></details>` : '');
  }
  function renderDetail(frame) {
    const agents = frame && frame.agents || [];
    $('residentCount').textContent = t('people',{count:agents.length});
    const agent = C.resident(state.trace,state.index,state.resident);
    if (state.resident == null) {
      $('residentDetail').innerHTML = `<h3>${esc(t('population'))}</h3><p>${esc(t('population_hint'))}</p><div class="results-state-grid">` + state.metrics.map(metric=>{
        const value = selectedSeries(metric,null)[state.index];
        return `<div><span>${esc(metricLabel(metric))}</span><strong>${value == null ? '—' : value.toFixed(3)}</strong></div>`;
      }).join('') + '</div>';
      return;
    }
    if (!agent) { $('residentDetail').innerHTML = `<p>${esc(t('resident_missing'))}</p>`; return; }
    const fields = [
      ['location',agent.resolved_location || agent.location], ['activity',agent.activity || agent.scheduled_activity],
      ['action',agent.action], ['outcome',agent.outcome],
    ];
    const thoughts = [['perception',agent.perception],['plan',agent.plan],['reflection',agent.reflection]];
    $('residentDetail').innerHTML = `<h3>${esc(agent.name || state.resident)}</h3><dl>` +
      fields.filter(([,value])=>value).map(([label,value])=>`<dt>${esc(t(label))}</dt><dd>${esc(value)}</dd>`).join('') + '</dl>' +
      '<div class="results-state-grid">' + state.metrics.map(metric=>{
        const value = selectedSeries(metric,state.resident)[state.index];
        return `<div><span>${esc(metricLabel(metric))}</span><strong>${value == null ? '—' : value.toFixed(3)}</strong></div>`;
      }).join('') + '</div>' + thoughts.filter(([,value])=>value).map(([label,value])=>`<details${label === 'plan' ? ' open' : ''}><summary>${esc(t(label))}</summary><p>${esc(value)}</p></details>`).join('');
  }
  function renderCharts() {
    const frames = state.trace && state.trace.frames || [];
    const focus = state.roster.find(agent => agent.id === state.resident);
    $('signalScope').textContent = focus ? focus.name : t('population_mean');
    if (!state.metrics.length || !frames.length) {
      $('signalCharts').innerHTML = `<p class="results-empty">${esc(t(frames.length ? 'pick_metrics' : 'no_frames'))}</p>`; return;
    }
    const denominator = state.times.at(-1) || 1;
    const x = i => 28 + state.times[i] / denominator * 244;
    $('signalCharts').innerHTML = state.metrics.map(metric => {
      const values = selectedSeries(metric,state.resident), mean = selectedSeries(metric,null);
      const finite = [...values,...mean].filter(v=>v != null);
      const low = Math.min(0,...finite), high = Math.max(1,...finite), span = high-low || 1;
      const y = value => 83 - (value-low) / span * 65;
      function path(points) {
        let pen = false;
        return points.map((value,i)=>{
          if (value == null) { pen = false; return ''; }
          const piece = `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(value).toFixed(1)}`;
          pen = true; return piece;
        }).join(' ');
      }
      const value = values[state.index];
      const label = metricLabel(metric);
      return `<article class="results-chart"><header><span>${esc(label)}</span><strong>${value == null ? '—' : value.toFixed(3)}</strong></header>
        <svg viewBox="0 0 286 108" preserveAspectRatio="none" tabindex="0" role="slider" aria-label="${esc(t('chart_seek',{metric:label}))}" aria-valuemin="1" aria-valuemax="${frames.length}" aria-valuenow="${state.index+1}" aria-valuetext="${esc(frameLabel(frames[state.index],state.index))}" data-result-chart="${esc(metric)}">
          <path d="M28 18H272M28 50H272M28 83H272" class="plot-grid" />
          <text x="0" y="21">${high.toFixed(1)}</text><text x="0" y="86">${low.toFixed(1)}</text>
          ${focus ? `<path d="${path(mean)}" class="plot-line plot-reference"/>` : ''}
          <path d="${path(values)}" class="plot-line"/>
          <line x1="${x(state.index)}" y1="12" x2="${x(state.index)}" y2="87" class="plot-cursor"/>
          ${value != null ? `<circle cx="${x(state.index)}" cy="${y(value)}" r="3.5" class="plot-point"/>` : ''}
          <text x="28" y="104">${esc(frameLabel(frames[0],0))}</text><text x="272" y="104" text-anchor="end">${esc(frameLabel(frames.at(-1),frames.length-1))}</text>
        </svg></article>`;
    }).join('') + (focus ? `<p class="results-chart-legend">${esc(t('chart_legend'))}</p>` : '');
  }
  function renderEvents() {
    const query = $('eventSearch').value.trim().toLowerCase();
    const events = state.events.filter(event => [event.name,event.description,event.type,event.topic].join(' ').toLowerCase().includes(query));
    $('eventCount').textContent = t('event_count',{count:events.length});
    $('eventList').innerHTML = events.length ? events.map(event=>`<button type="button" data-event-frame="${event.index}" data-current="${state.index === event.index}"><time>${esc(frameLabel(state.trace.frames[event.index],event.index))}</time><strong>${esc(event.name)}</strong><small>${esc(t('jump_event'))}</small></button>`).join('') : `<p class="results-empty">${esc(t('no_events'))}</p>`;
  }
  function renderFrame() {
    const frames = state.trace && state.trace.frames || [], frame = frames[state.index];
    $('frameStamp').textContent = frameLabel(frame,state.index);
    $('timeLabel').textContent = frameLabel(frame,state.index);
    $('timeline').max = String(Math.max(0,frames.length-1)); $('timeline').value = String(state.index);
    $('timeline').setAttribute('aria-valuetext',frameLabel(frame,state.index));
    $('framePosition').textContent = frames.length ? `${state.index+1} / ${frames.length}` : '0 / 0';
    $('timeJump').value = String(state.index);
    for (const id of ['timeline','timeJump','playBtn','firstFrame','previousFrame','nextFrame','lastFrame','speedSelect']) $(id).disabled = !frames.length || (id === 'playBtn' && frames.length < 2);
    $('sceneCaption').textContent = frame ? t('scene_hint',{count:(frame.agents || []).length}) : t(state.loading ? 'loading' : 'no_frames');
    $('frameContext').textContent = frame && frame.env_context || t('no_context');
    if (frame) map.render(frames.slice(Math.max(0,state.index-96),state.index+1));
    else map.renderEmpty(t(state.loading ? 'loading' : 'no_frames'));
    if (indoor) indoor.render(frame);
    renderDetail(frame); renderCharts();
    // Preserve event-list scroll and focused element while playing/scrubbing.
    $('eventList').querySelectorAll('[data-event-frame]').forEach(button => button.dataset.current = String(Number(button.dataset.eventFrame) === state.index));
  }
  async function ensureAnalytics() {
    return loadAnalytics(false);
  }
  let analyticsPending = null, analyticsTarget = null;
  function loadAnalytics(forExport) {
    if (!state.run || state.loading || (!forExport && state.view === 'replay')) return Promise.resolve(false);
    if (state.analyticsRun === state.run.id) return Promise.resolve(true);
    const runId = state.run.id;
    if (analyticsPending && analyticsTarget === runId) return analyticsPending;
    analyticsTarget = runId;
    const pending = window.GAWorldAnalytics.loadRun(runId,state.resident,state.roster).then(ok=>{
      if (ok && state.run && state.run.id === runId) {
        state.analyticsRun = runId;
        window.GAWorldAnalytics.focus(state.resident);
      }
      return ok;
    }).finally(()=>{ if (analyticsPending === pending) { analyticsPending = null; analyticsTarget = null; } });
    analyticsPending = pending;
    return pending;
  }
  function setView(view) {
    if (!['replay','analysis','system'].includes(view)) view = 'replay';
    if (view === 'system' && $('systemTab').hidden) view = 'replay';
    state.view = view;
    if (view !== 'replay') stop();
    document.querySelectorAll('[data-results-view]').forEach(button => {
      const on = button.dataset.resultsView === view;
      button.setAttribute('aria-selected',String(on)); button.tabIndex = on ? 0 : -1;
    });
    document.querySelectorAll('[data-results-pane]').forEach(pane => pane.hidden = pane.dataset.resultsPane !== view);
    $('resultsTransport').hidden = view !== 'replay';
    if (view === 'replay') { window.dispatchEvent(new Event('resize')); if (map.map) map.map.resize(); }
    ensureAnalytics(); syncUrl();
  }
  let traceRequest;
  async function loadRun(run, preserve) {
    const request = ++state.request;
    if (traceRequest) traceRequest.abort();
    traceRequest = new AbortController();
    const oldIndex = state.index, oldResident = state.resident, oldMetrics = state.metrics;
    stop(); state.loading = true; state.run = run; state.trace = null; state.index = 0; state.resident = null;
    state.metrics = []; state.roster = []; state.events = []; state.times = []; state.series.clear(); state.analyticsRun = null;
    analyticsPending = null; analyticsTarget = null;
    window.GAWorldAnalytics.clear();
    map.setTrace(null); if (indoor) indoor.setTrace(null);
    message(''); renderRuns(); renderSummary(); renderRoster(); renderMetrics(); renderEvents(); renderFrame();
    $('timeJump').innerHTML = '';
    if (!run) { state.loading = false; message(t('no_runs')); renderFrame();
      // Even with nothing selectable, the overview KPIs describe the current
      // world — render them instead of leaving the pane skeleton forever.
      if (window.GAWorldAnalytics && window.GAWorldAnalytics.load) window.GAWorldAnalytics.load();
      return; }
    try {
      const trace = await json(run.trace_url,traceRequest.signal);
      if (request !== state.request) return;
      if (!trace || !Array.isArray(trace.frames)) throw new Error(t('invalid_trace'));
      state.trace = trace; state.loading = false;
      state.roster = C.roster(trace); state.events = C.events(trace); state.times = C.frameTimes(trace);
      const available = C.metrics(trace);
      state.metrics = (preserve ? oldMetrics : ['emotion','stress','energy','econ_security']).filter(metric=>available.includes(metric));
      if (!state.metrics.length) state.metrics = available.slice(0,4);
      const target = preserve ? oldResident : state.initialApplied ? null : initial.get('agent');
      state.resident = state.roster.some(agent=>agent.id === target) ? target : null;
      map.avatarBase = run.avatar_base; map.setTrace(trace);
      if (indoor) { indoor.avatarBase = run.avatar_base; indoor.setTrace(trace); }
      $('timeJump').innerHTML = trace.frames.map((frame,index)=>`<option value="${index}">${esc(frameLabel(frame,index))}</option>`).join('');
      renderSummary(); renderRoster(); renderMetrics(); renderEvents();
      seek(preserve ? oldIndex : state.initialApplied ? 0 : Number(initial.get('frame')) || 0);
      state.initialApplied = true;
      if (!trace.frames.length) message(t('no_frames'));
      ensureAnalytics();
    } catch (error) {
      if (request !== state.request || error.name === 'AbortError') return;
      state.loading = false; message(t('load_failed',{error:error.message})); renderFrame();
    }
  }
  async function refresh(preserve) {
    const refreshButton = $('anRefreshBtn'); refreshButton.disabled = true;
    try {
      const [replay,analytics] = await Promise.allSettled([json('/api/replay/runs'),json('/api/analytics/runs')]);
      if (replay.status === 'rejected') throw replay.reason;
      state.runs = C.mergeRuns(replay.value.runs,analytics.status === 'fulfilled' ? analytics.value.runs : []);
      const wanted = state.run ? state.run.id : initial.get('run');
      // Prefer the newest recorded run; "current source" can be an old unfinished file.
      const newest = state.runs.filter(run=>run.frame_count > 0).sort((a,b)=>(b.mtime || 0)-(a.mtime || 0))[0];
      const run = C.findRun(state.runs,wanted) || newest || state.runs[0] || null;
      await loadRun(run,preserve);
      if (wanted && !C.findRun(state.runs,wanted)) message(t('run_unavailable'));
    } catch (error) { message(t('load_failed',{error:error.message})); }
    finally { refreshButton.disabled = false; }
  }

  $('anRunSelect').addEventListener('change',event=>loadRun(C.findRun(state.runs,event.target.value),false));
  $('runSearch').addEventListener('input',renderRuns); $('runKind').addEventListener('change',renderRuns);
  $('anRefreshBtn').addEventListener('click',()=>refresh(true));
  $('residentSelect').addEventListener('change',event=>selectResident(event.target.value));
  $('metricPicker').addEventListener('click',event=>{
    const button = event.target.closest('[data-result-metric]'); if (!button) return;
    const metric = button.dataset.resultMetric;
    state.metrics = state.metrics.includes(metric) ? state.metrics.filter(value=>value !== metric) : [...state.metrics,metric];
    renderMetrics(); renderFrame();
  });
  $('signalCharts').addEventListener('click',event=>{
    const chart = event.target.closest('[data-result-chart]'); if (!chart || !state.trace) return;
    const rect = chart.getBoundingClientRect();
    stop(); seek(C.nearestFrame(state.trace,((event.clientX-rect.left)/rect.width * 286-28)/244));
  });
  $('signalCharts').addEventListener('keydown',event=>{
    const chart = event.target.closest('[data-result-chart]'); if (!chart) return;
    const jump = {ArrowLeft:state.index-1,ArrowRight:state.index+1,Home:0,End:(state.trace.frames || []).length-1}[event.key];
    if (jump == null) return;
    event.preventDefault(); const metric = chart.dataset.resultChart; stop(); seek(jump);
    $('signalCharts').querySelector(`[data-result-chart="${CSS.escape(metric)}"]`).focus();
  });
  $('eventSearch').addEventListener('input',renderEvents);
  $('eventList').addEventListener('click',event=>{ const button = event.target.closest('[data-event-frame]'); if (button) { stop(); seek(button.dataset.eventFrame); } });
  $('playBtn').addEventListener('click',play);
  $('timeline').addEventListener('input',event=>{ stop(); seek(event.target.value); });
  $('timeJump').addEventListener('change',event=>{ stop(); seek(event.target.value); });
  for (const [id,index] of [['firstFrame',()=>0],['previousFrame',()=>state.index-1],['nextFrame',()=>state.index+1],['lastFrame',()=>state.trace.frames.length-1]]) {
    $(id).addEventListener('click',()=>{ stop(); seek(index()); });
  }
  $('speedSelect').addEventListener('change',()=>{ if (state.timer) { stop(); play(); } });
  $('thoughtsToggle').addEventListener('change',event=>{ map.showThoughts = event.target.checked; map.rerender(); });
  document.querySelectorAll('[data-results-view]').forEach(button=>button.addEventListener('click',()=>{ viewInteracted = true; setView(button.dataset.resultsView); }));
  document.querySelector('.results-tabs').addEventListener('keydown',event=>{
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    const buttons = [...document.querySelectorAll('[data-results-view]')].filter(button=>!button.hidden);
    const index = buttons.indexOf(event.target); if (index < 0) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length-1 : (index+(event.key === 'ArrowRight' ? 1 : -1)+buttons.length)%buttons.length;
    viewInteracted = true; buttons[next].focus(); setView(buttons[next].dataset.resultsView);
  });
  $('anExport').addEventListener('toggle',()=>{ if ($('anExport').open) loadAnalytics(true); });
  document.addEventListener('locale-changed',()=>{
    renderRuns(); renderSummary(); renderRoster(); renderMetrics(); renderEvents(); renderFrame();
    $('playBtn').textContent = t(state.timer ? 'pause' : 'play');
    $('timeJump').innerHTML = (state.trace && state.trace.frames || []).map((frame,index)=>`<option value="${index}">${esc(frameLabel(frame,index))}</option>`).join('');
    $('timeJump').value = String(state.index);
  });
  document.addEventListener('visibilitychange',()=>{ if (document.hidden) stop(); });
  window.addEventListener('pagehide',stop);
  json('/api/auth/me').then(account=>{
    $('systemTab').hidden = !(account.mode === 'single' || (account.user && account.user.role === 'admin'));
    if (!viewInteracted && initial.get('view') === 'system') setView('system');
  }).catch(()=>{});
  setView(state.view); refresh(false);
})();
