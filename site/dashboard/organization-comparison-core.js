(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.OrganizationComparisonCore = api;
}(typeof window === 'undefined' ? globalThis : window, function () {
  'use strict';
  function escape(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function canVisit(step, state) {
    if (step > 0 && state.reviewed === false) return false;
    if (step >= 2 && state.baseline === 'custom' && !state.baselineMethod) return false;
    return step === 0 || (step <= 2 && Boolean(state.method))
      || (step === 3 && Boolean(state.method && state.benchmark)) || (step >= 4 && Boolean(state.study));
  }
  function settings(state, values) {
    return Object.assign({candidate: state.method, benchmark: state.benchmark,
      agent_ids: state.ids.slice(), provider: state.provider, baseline: state.baseline || 'random',
      ...(state.baseline === 'custom' ? {baseline_method:state.baselineMethod} : {})}, values);
  }
  async function responseValue(response) {
    const value=await response.json();
    if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
    return value;
  }
  function effectiveBaseline(candidate, control, mode) {
    if (!control) return null;
    const value=JSON.parse(JSON.stringify(control));
    if (mode==='topology') for(const key of ['roles','rounds','decision','review','revisions'])value[key]=candidate[key];
    return value;
  }
  function controls(study, busy=false) {
    const s=study?.status, pending=s==='running'&&Boolean(study?.control), cooling=coolingDown(study);
    return {pause:s==='running'&&study.control!=='stop',pauseDisabled:busy||pending,pauseLabel:pending?'pausing':'pause',
      resume:s==='paused',resumeDisabled:busy||cooling,
      retry:['interrupted','rate_limited'].includes(s),retryDisabled:busy||cooling||Boolean(study?.retry_blocked_reason),
      stop:['running','paused','interrupted','rate_limited'].includes(s),stopDisabled:busy||pending};
  }
  function studyFromSearch(search) {const id=new URLSearchParams(search).get('comparison');return /^C[a-f0-9]{24}$/.test(id||'')?id:null;}
  function coolingDown(study, now=Date.now()/1000) {return Boolean(study?.error_info?.retry_at > now);}
  function shouldPoll(study) { return Boolean(study && (['running','rate_limited'].includes(study.status) || (study.status==='draft' && coolingDown(study)))); }
  function failureMessage(study, en) {
    const kind=study.error_info?.kind;
    const labels={token_plan_rate_limit:['MiniMax Token Plan 达到速率限制（HTTP 429，2062），已保留进度。','MiniMax Token Plan rate limit (HTTP 429, 2062). Progress is saved.'],
      token_plan_quota:['MiniMax Token Plan 可用用量已达上限（HTTP 429，2067），请检查套餐用量。','MiniMax Token Plan allowance exhausted (HTTP 429, 2067). Check the plan allowance.'],
      rate_limit:['模型服务限流（HTTP 429），已保留进度。','Provider rate limit (HTTP 429). Progress is saved.'],
      authentication:['模型凭证或访问权限未通过，请检查配置。','Model credentials or permissions were rejected. Check the configuration.'],
      network:['连接模型服务失败或超时，已保留进度。','Model connection failed or timed out. Progress is saved.']};
    if(labels[kind]) return labels[kind][en?1:0];
    if(study.error==='HTTPError')return en?'The model service rejected a request. Progress is saved.':'模型服务拒绝了请求，已保留进度；旧记录未保存具体状态码。';
    if(study.error==='ConnectionError')return labels.network[en?1:0];
    return String(study.error||'');
  }
  function reviewFields(method) {return {review:method.review === true,revisions:method.revisions || 0};}
  function protocolFields(p) {return {provider:p.model.name,ids:p.members.map(m=>m.id),baseline:p.baseline_kind || p.baseline.topology.kind,
    mode:p.scope,repeats:p.repeats,seed:p.seed,delta:p.delta,calls:p.limits.calls,tokens:p.max_tokens};}
  function verdict(value, en) {
    const text = {better:['有证据表明候选组织成绩更高','Evidence of higher scores'], worse:['有证据表明候选组织成绩更低','Evidence of lower scores'],
      uncertain:['尚无充分证据表明候选组织更有效','Insufficient evidence of improvement'], incomplete:['实验尚不完整，暂不能判断','Incomplete experiment; no conclusion yet']};
    return (text[value] || text.incomplete)[en ? 1 : 0];
  }
  function graph(method, actual) {
    if (!method || !Array.isArray(method.roles)) return '';
    const n = Math.min(12, method.roles.length);
    const points = method.roles.slice(0,n).map((r,i) => ({x:130 + Math.cos(i * 2*Math.PI/n - Math.PI/2)*82,
      y:108 + Math.sin(i * 2*Math.PI/n - Math.PI/2)*72, label:r}));
    const links = [];
    if (actual) links.push(...actual);
    else if (method.topology.kind === 'custom') links.push(...method.topology.edges || []);
    else for (let a=0; a<n; a++) for (let b=a+1; b<n; b++) {
      if (method.topology.kind === 'full' || (method.topology.kind === 'hierarchy' && a===0)
        || (method.topology.kind === 'random' && (a+b)%2)) links.push([a,b]);
    }
    return '<svg viewBox="0 0 260 220" role="img" aria-label="Communication graph"><defs><marker id="ocArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker></defs>'
      + links.map(([a,b]) => points[a] && points[b] ? `<line x1="${points[a].x}" y1="${points[a].y}" x2="${points[b].x}" y2="${points[b].y}" class="oc-edge" ${method.topology.kind==='custom'?'marker-end="url(#ocArrow)"':''}/>`:'').join('')
      + points.map((p,i) => `<g><circle cx="${p.x}" cy="${p.y}" r="17"/><text x="${p.x}" y="${p.y+5}" text-anchor="middle">${i+1}</text><text class="oc-role" x="${p.x}" y="${p.y+32}" text-anchor="middle">${escape(p.label.slice(0,9))}</text></g>`).join('')+'</svg>';
  }
  return {escape, canVisit, settings, shouldPoll, verdict, graph, reviewFields, protocolFields, coolingDown, failureMessage, studyFromSearch, responseValue, controls, effectiveBaseline};
}));
