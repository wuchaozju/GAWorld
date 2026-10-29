/* Read-only trace operations shared by the results UI and its Node tests. */
(function (root) {
  'use strict';
  const frames = trace => trace && Array.isArray(trace.frames) ? trace.frames : [];
  const agents = frame => frame && Array.isArray(frame.agents) ? frame.agents : [];
  const numeric = value => typeof value === 'number' && Number.isFinite(value);

  function mergeRuns(replay, analytics) {
    const capabilities = new Map((analytics || []).map(run => [run.id, run.sections || {}]));
    const groups = new Map();
    for (const run of replay || []) {
      if (!run || !run.id || !run.trace_url) continue;
      const base = run.id.replace(/\/runs\/[^/]+$/, '');
      const key = run.generated_at
        ? JSON.stringify([base, run.generated_at, run.frame_count, !!run.finished]) : run.id;
      const item = {...run, sections:capabilities.get(run.id) || {}, aliases:[run.id]};
      const previous = groups.get(key);
      if (!previous) { groups.set(key, item); continue; }
      const preferItem = previous.kind === 'archive' && item.kind !== 'archive';
      const chosen = preferItem ? item : previous;
      chosen.aliases = [...new Set([...previous.aliases, ...item.aliases])];
      groups.set(key, chosen);
    }
    return [...groups.values()];
  }
  function findRun(runs, id) {
    return (runs || []).find(run => run.id === id || (run.aliases || []).includes(id)) || null;
  }
  function frameTimes(trace) {
    const list = frames(trace);
    const clocks = list.map(frame => {
      const match = /^(\d{1,2}):(\d{2})/.exec(frame.time || '');
      return numeric(frame.day) && match ? frame.day * 1440 + Number(match[1]) * 60 + Number(match[2]) : null;
    });
    // Missing/nonmonotone clocks use the explicit sample order, never fabricated dates.
    if (clocks.some((clock, i) => clock === null || (i && clock < clocks[i - 1])) ||
      (clocks.length > 1 && clocks.at(-1) === clocks[0])) return list.map((_,i) => i);
    return clocks.map(clock => clock - clocks[0]);
  }
  function nearestFrame(trace, fraction) {
    const times = frameTimes(trace);
    const target = Math.max(0, Math.min(1, Number(fraction) || 0)) * (times.at(-1) || 0);
    let closest = 0;
    times.forEach((time,i) => { if (Math.abs(time-target) < Math.abs(times[closest]-target)) closest = i; });
    return closest;
  }
  function resident(trace, index, id) {
    return agents(frames(trace)[index]).find(agent => String(agent.agent_id) === String(id)) || null;
  }
  function roster(trace) {
    const map = new Map();
    for (const agent of (trace && trace.agents) || []) {
      if (agent.id != null) map.set(String(agent.id), {id:String(agent.id),name:agent.name || String(agent.id)});
    }
    for (const frame of frames(trace)) for (const agent of agents(frame)) {
      if (agent.agent_id != null) map.set(String(agent.agent_id), {id:String(agent.agent_id), name:agent.name || String(agent.agent_id)});
    }
    return [...map.values()];
  }
  function metrics(trace) {
    const keys = new Set();
    for (const frame of frames(trace)) for (const agent of agents(frame)) {
      for (const [key,value] of Object.entries(agent.state || {})) if (numeric(value)) keys.add(key);
    }
    return [...keys].sort();
  }
  function series(trace, metric, id) {
    return frames(trace).map(frame => {
      const values = agents(frame)
        .filter(agent => id == null || String(agent.agent_id) === String(id))
        .map(agent => (agent.state || {})[metric]).filter(numeric);
      return values.length ? values.reduce((sum,value)=>sum+value,0) / values.length : null;
    });
  }
  function events(trace) {
    const seen = new Set(), output = [];
    frames(trace).forEach((frame,index) => {
      for (const event of Array.isArray(frame.env_events) ? frame.env_events : []) {
        const key = event.id || JSON.stringify([event.name,event.type,event.topic,event.start_day,event.start_time]);
        if (seen.has(key)) continue;
        seen.add(key);
        output.push({...event, index, name:event.name || event.title || event.topic || event.type || '—'});
      }
    });
    return output;
  }
  function advance(index, count) {
    const next = Math.min(Math.max(0, count-1), index+1);
    return {index:next, done:next >= count-1};
  }
  function labelAnalytics(section, payload, residents) {
    const names = new Map((residents || []).map(agent=>[String(agent.id),agent.name]));
    const out = {...payload};
    const keys = {history:['agents'],economy:['ledger','wealth'],social:['nodes'],behavior:['agents','habits']}[section] || [];
    for (const key of keys) out[key] = (payload[key] || []).map(row=>{
      if (section === 'social' && row.kind !== 'agent') return row;
      const name = names.get(String(row.agent_id == null ? row.id : row.agent_id));
      return name ? {...row,[section === 'social' ? 'label' : 'name']:name} : row;
    });
    return out;
  }
  const api = {mergeRuns,findRun,frameTimes,nearestFrame,resident,roster,metrics,series,events,advance,labelAnalytics};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.GAWorldResultsCore = api;
})(typeof window !== 'undefined' ? window : globalThis);
