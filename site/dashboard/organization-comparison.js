(function () {
  'use strict';
  const C = window.OrganizationComparisonCore;
  const mount = document.getElementById('organizationComparison');
  if (!C || !mount) return;
  const P = '/api/research/organization-intelligence/comparisons';
  const state = {step:0, method:null, benchmark:null, study:null, ids:[], provider:'', baseline:'random', baselineMethod:null, baselineDraft:null, revision:0, reviewed:false, factors:Object.assign({},C.DEFAULT_FACTORS), dirty:false, plan:null, candidates:[], savedMethods:[]};
  let context = {}, timer = null, busy = false, busyLabel = '';
  const en = () => document.documentElement.lang.startsWith('en');
  const T = (zh, eng) => en() ? eng : zh;
  const E = C.escape;
  const L = (zh, eng) => `<span data-oc-zh="${E(zh)}" data-oc-en="${E(eng)}">${E(T(zh,eng))}</span>`;
  const button = (id,zh,eng,cls='') => `<button type="button" id="${id}" class="btn ${cls}">${L(zh,eng)}</button>`;
  const steps = [['提供组织材料','Material'],['选择对照方式','Baseline'],['选择问题','Problems'],['设置对比实验','Experiment'],['分析结果','Results'],['用于合作任务','Reuse']];
  const kinds = [['random','随机网络','Random network'],['full','全员互联','Fully connected'],['hierarchy','层级组织','Hierarchy'],['independent','独立作答后汇总','Independent then combine']];
  const options = (values) => values.map(([id,zh,eng])=>`<option value="${id}" data-oc-zh="${E(zh)}" data-oc-en="${E(eng)}">${E(T(zh,eng))}</option>`).join('');
  mount.innerHTML = `<div class="oc-workbench">
    <nav class="oc-steps" aria-label="Organization comparison">${steps.map((s,i)=>`<button type="button" data-oc-step="${i}"><b>0${i+1}</b>${L(...s)}</button>`).join('')}</nav>
    <p id="ocStepLive" class="oc-sr-only" aria-live="polite"></p>
    <p id="ocError" class="oc-error" role="alert"></p>
    <div class="oc-layout"><div class="oc-main">
    <section data-oc-pane="0" class="rw-card"><p class="oc-index">01 / ORGANIZATION</p><h2>${L('把组织理论变成做事规则','Turn an organization idea into working rules')}</h2>
      <p>${L('上传论文或描述组织方式。系统先提取规则，你可以核对原文、修改补充内容。','Upload a paper or describe an organization. Review the extracted rules and their sources before testing.')}</p><p class="oc-note"><a href="/docs/ORGANIZATION_INTELLIGENCE_TUTORIAL.md" target="_blank" rel="noopener">${L('使用说明与题库导入格式','Guide and benchmark import format')}</a></p>
      <label class="oc-field">${L('材料名称','Material title')}<input id="ocTitle" maxlength="200"></label>
      <label class="oc-field">${L('论文文本或组织方式描述','Paper text or organization description')}<textarea id="ocMaterial" rows="7" placeholder="${E(T('成员如何分工、交换信息、审阅和作出决定？','How do members divide work, exchange information, review and decide?'))}"></textarea></label>
      <div class="oc-actions"><label class="btn oc-upload">${L('上传 PDF / TXT / Markdown','Upload PDF / TXT / Markdown')}<input type="file" id="ocMaterialFile" accept=".pdf,.txt,.md,.markdown"></label><span id="ocFileNote"></span></div>
      <label class="oc-field">${L('解读与实验模型','Model for reading and experiment')}<select id="ocProvider"></select></label>
      <div class="oc-actions">${button('ocAnalyze','分析组织方式','Analyze organization','primary')}${button('ocExample','使用可编辑示例规则','Use editable example rules')}</div>
      <p class="oc-note">${L('分析材料会调用模型；使用示例不会调用模型，也不代表已从论文提取规则。','Reading material calls the selected model. The editable example needs no model call and is not extracted from a paper.')}</p>
      <div id="ocEditor" hidden><h3>${L('核对组织方式','Review the organization method')}</h3>
        <label class="oc-field">${L('组织名称','Method name')}<input id="ocMethodName"></label>
        <div class="oc-fields"><label class="oc-field">${L('角色分工（每行一位，2–12位）','Roles (one per line, 2–12)')}<textarea id="ocRoles" rows="4"></textarea></label>
        <div><label class="oc-field">${L('通信结构','Communication')}<select id="ocTopology">${options(kinds)}<option value="custom">Custom / 自定义</option></select></label>
          <label class="oc-field">${L('讨论轮数','Discussion rounds')}<input id="ocRounds" type="number" min="0" max="6" value="2"></label></div></div>
        <div class="oc-fields"><label class="oc-field">${L('最终决策','Final decision')}<select id="ocDecision">${options([['auto','按题型选择投票或汇总','Vote for choices, synthesize other tasks'],['vote','投票','Vote'],['synthesis','指定成员汇总','Designated synthesizer']])}</select></label>
        <div><label class="oc-check"><input id="ocReviewEnabled" type="checkbox">${L('交叉审阅','Peer review')}</label><label class="oc-field">${L('审阅后修订次数（可为0）','Revision passes after review (may be 0)')}<input id="ocReview" type="number" min="0" max="2" value="0"></label></div></div>
        <div id="ocRules"></div>
        <details><summary>${L('自定义通信边和完整规则','Custom edges and full rules')}</summary><p class="oc-note">${L('自定义有向边使用从0开始的角色编号，例如 [[0,1],[1,2]]。高级编辑会替换全部规则。','Custom directed edges use zero-based role slots, e.g. [[0,1],[1,2]]. Advanced editing replaces the full rule set.')}</p>
          <label class="oc-field">${L('完整规则 JSON','Full rules JSON')}<textarea id="ocRuleJson" rows="12" spellcheck="false"></textarea></label>${button('ocApplyJson','应用完整规则','Apply full rules')}</details>
        <div class="oc-actions">${button('ocAdopt','采用这份组织方式','Use this organization','primary')}</div>
      </div>
      <div id="ocExtraCard" hidden><h3>${L('再比较几个组织','Compare more organizations')}</h3>
        <p class="oc-note">${L('从合作任务里保存过的组织方式中再选几个，和同一个对照一起比。最多4个组织：1个对照加最多3个候选。每个候选有自己的名字和自己的允许差异因子。','Pick more of the organizations saved for cooperation and compare them against the same control. At most 4 arms: one control and up to three candidates. Every candidate has its own name and its own set of factors allowed to differ.')}</p>
        <div class="oc-fields"><label class="oc-field">${L('已保存的组织方式','Saved organizations')}<select id="ocSavedMethod"></select></label>
          <div class="oc-actions">${button('ocAddCandidate','加入这次比较','Add to this comparison')}</div></div>
        <div id="ocCandidates" class="oc-note"></div>
      </div></section>
    <section data-oc-pane="1" class="rw-card" hidden><p class="oc-index">02 / CONTROL</p><h2>${L('与哪种基本方式比较？','Choose a baseline')}</h2>
      <div id="ocBaselineCards" class="oc-baselines">${kinds.map(([id,zh,eng])=>`<label><input type="radio" name="ocBaseline" value="${id}" ${id==='random'?'checked':''}>${L(zh,eng)}</label>`).join('')}<label><input type="radio" name="ocBaseline" value="custom">${L('自定义输入','Custom description')}</label></div>
      <div id="ocCustomBaseline" hidden>
        <label class="oc-field">${L('描述对照组织如何工作','Describe how the baseline works')}<textarea id="ocBaselineText" rows="5" placeholder="${E(T('例如：成员先独立给出答案，再由一位协调人收集理由并作最终决定。','For example: members answer independently, then a coordinator gathers reasons and decides.'))}"></textarea></label>
        <p class="oc-note">${L('生成规则会调用当前选择的模型；对照人数与候选相同。核对并采用后才能继续。','Generating rules calls the selected model. The baseline must match the candidate team size. Review and adopt the rules to continue.')}</p>
        ${button('ocAnalyzeBaseline','生成对照规则','Generate baseline rules')}
        <div id="ocBaselinePreview"></div>
        <details id="ocBaselineDetails"><summary>${L('查看与修改完整对照规则','Review and edit full baseline rules')}</summary><label class="oc-field">${L('可编辑规则 JSON','Editable rules JSON')}<textarea id="ocBaselineJson" rows="14" spellcheck="false"></textarea></label></details>
        ${button('ocAdoptBaseline','采用此对照方式','Use this baseline','primary')}<p id="ocBaselineStatus" class="oc-note" role="status"></p>
      </div>
      <p>${L('随机网络默认无向、无自环，连边概率为0.5。每题每次重复独立生成，题内保持不变。','Random networks are undirected, without self-links, with edge probability 0.5. A new fixed graph is drawn for each question and repeat.')}</p>
      <fieldset class="oc-factors"><legend>${L('允许不同的因子','Factors allowed to differ')}</legend>
        <p class="oc-note">${L('勾选的机制在两臂之间可以不同；未勾选的机制在对照臂上与候选完全相同，这样结果才能归因到一处。默认只让通信结构不同。','A ticked mechanism may differ between the two arms; the unticked ones are made identical on the baseline, so a result can be attributed. Only the communication structure differs by default.')}</p>
        <div id="ocFactors" class="oc-check-grid"></div>
        <p id="ocScopeNote" class="oc-note"></p></fieldset>
    </section>
    <section data-oc-pane="2" class="rw-card" hidden><p class="oc-index">03 / PROBLEM SET</p><h2>${L('让两种组织解决同一批问题','Give both organizations the same problems')}</h2>
      <label class="oc-field">${L('内置问题类型','Built-in task family')}<select id="ocProblem">${options([['information','分散信息整合','Distributed information'],['allocation','约束资源分配','Constrained resource allocation']])}</select></label>
      <label class="oc-field">${L('独立题目数','Independent questions')}<input id="ocCount" type="number" min="1" max="1000" value="30"></label>
      ${button('ocBuiltin','使用此题库','Use this benchmark','primary')}
      <details><summary>${L('导入自己的 benchmark','Import a benchmark')}</summary>
        <label class="oc-field">${L('题库文件（JSONL / CSV）','Benchmark file (JSONL / CSV)')}<input id="ocBenchmarkFile" type="file" accept=".jsonl,.csv"></label>
        <label class="oc-field">${L('评分方式','Scoring')}<select id="ocScorer">${options([['exact','参考答案精确匹配','Exact reference match'],['choice','选择题准确率','Choice accuracy'],['allocation','约束与目标值','Constraints and objective'],['rubric','固定量表的模型评审','Model judge with fixed rubric']])}</select></label>
        <p class="oc-note">${L('每题需要 id、category、prompt，以及 reference（开放题需 rubric）。局部信息用 observations 数组；选项用 options。参考答案不会交给成员。','Each question needs id, category, prompt, and reference (rubric for open tasks). Use observations for private inputs and options for choices. References stay hidden from members.')}</p>
        <label class="oc-field">${L('字段映射 JSON（可选，例如 {"prompt":"question"}）','Field mapping JSON (optional, e.g. {"prompt":"question"})')}<textarea id="ocMapping" rows="2">{}</textarea></label>
        ${button('ocImport','检查并导入','Validate and import')}
      </details><div id="ocBenchmarkPreview" class="oc-preview" aria-live="polite"></div>
    </section>
    <section data-oc-pane="3" class="rw-card" hidden><p class="oc-index">04 / MATCHED EXPERIMENT</p><h2>${L('先保存设置，再开始实验','Save settings, then start')}</h2>
      <p>${L('两组使用同一批居民的隔离快照、相同题目和模型。实验不会写回居民记忆。','Both arms use isolated snapshots of the same residents, questions and model. Research does not write back resident memories.')}</p>
      <label class="oc-field">${L('参与居民（按角色顺序选择，人数必须匹配）','Residents (slot order, must match role count)')}<select id="ocMembers" multiple size="7"></select></label>
      <div class="oc-fields"><label class="oc-field">${L('每题重复几次','Repeats per question')}<input id="ocRepeats" type="number" min="1" max="10" value="3"></label>
        <label class="oc-field">${L('最小改善幅度（0–1）','Minimum improvement (0–1)')}<input id="ocDelta" type="number" min="0" max="1" step="0.01" value="0"></label></div>
      <details><summary>${L('运行限制与复现设置','Limits and reproducibility')}</summary><div class="oc-fields">
        <label class="oc-field">${L('随机种子','Seed')}<input id="ocSeed" type="number" min="0" value="20261026"></label>
        <label class="oc-field">${L('每组每题最多调用','Max actor calls per arm/question')}<input id="ocCalls" type="number" min="1" max="200" value="100"></label>
        <label class="oc-field">${L('每次最大输出 token','Max output tokens per call')}<input id="ocTokens" type="number" min="64" max="4096" value="2048"></label></div>
        <p id="ocLimits" class="oc-note"></p></details>
      <p id="ocSavedProgress" class="oc-note" role="status"></p><div id="ocPlan" class="oc-note" aria-live="polite"></div><p id="ocEstimate" class="oc-note"></p><div class="oc-actions">${button('ocSave','保存实验设置','Save experiment settings','primary')}${button('ocRun','开始实验','Start experiment','primary')}</div>
      <p>${L('保存不会调用实验模型。点击开始后才发生实际调用。为降低限流风险，相邻实际请求至少间隔10秒；已有回答直接复用。未完成或小样本结果不作优势结论。','Saving makes no experiment calls. Actual requests are at least 10 seconds apart; cached responses are reused immediately. Incomplete or small samples cannot establish superiority.')}</p>
    </section>
    <section data-oc-pane="4" class="rw-card" hidden><p class="oc-index">05 / EVIDENCE</p><h2>${L('看成绩，也看代价','Compare scores and costs')}</h2>
      <div id="ocProgress" aria-live="polite"></div><p id="ocFailure" class="oc-error" role="alert"></p><p id="ocWait" class="oc-note" aria-live="polite"></p><p id="ocRecovery" class="oc-note"></p><details id="ocFailureDetails" hidden><summary>${L('查看错误诊断与恢复来源','Error diagnostics and recovery provenance')}</summary><pre id="ocFailureJson" class="oi-log"></pre></details><progress id="ocBar" max="1" value="0"></progress>
      <div class="oc-actions">${button('ocPause','暂停','Pause')}${button('ocResume','继续实验','Resume')}${button('ocRetry','重新运行（保留进度）','Retry from saved progress','primary')}${button('ocStop','终止','Stop')}${button('ocRefresh','刷新进度','Refresh')}</div>
      <div class="oc-actions">${button('ocDuplicate','复制设置另建一次','Duplicate settings')}${button('ocDelete','删除这条记录','Delete record')}</div>
      <div id="ocResult"></div><div class="oc-actions">${button('ocReport','下载报告','Download report')}${button('ocCsv','每道题成绩','Question scores')}${button('ocSettings','实验设置','Settings')}${button('ocAudit','全部调用记录','Call audit')}</div>
      <details><summary>${L('查看每道题和运行错误','Per-question details and errors')}</summary><div id="ocRows" class="oc-table"></div></details>
    </section>
    <section data-oc-pane="5" class="rw-card" hidden><p class="oc-index">06 / REUSE</p><h2>${L('让下一次合作使用这套组织方式','Use this method in your next cooperation')}</h2>
      <p>${L('保存实验中实际使用的规则版本，并附上适用范围和研究结果。保存不代表已经证明优势；更换题型、模型或人数属于未验证配置。','Save the exact tested rules with their evidence and scope. Saving does not certify superiority. Other models, task types or team sizes are unvalidated configurations.')}</p>
      <label class="oc-field">${L('在合作任务中的名称','Name in cooperation')}<input id="ocLibraryName"></label>
      <div class="oc-actions">${button('ocSaveMethod','保存到合作任务','Save to cooperation','primary')}<a href="/console#collaboration" target="_top" class="btn">${L('打开合作任务','Open cooperation')}</a></div>
      <p id="ocSavedMethod" role="status"></p>
    </section>
    <div class="oc-actions oc-bottom">${button('ocBack','上一步','Back')}${button('ocNext','下一步','Next','primary')}</div>
    </div><aside class="oc-sidebar"><div class="rw-card"><p class="oc-index">SIDE BY SIDE</p><h3>${L('待比较的两种组织','The two organizations')}</h3><div id="ocCompare"></div></div>
      <div class="rw-card"><h3>${L('实验记录','Experiments')}</h3><p id="ocHistoryStatus" class="oc-note" role="status"></p><div id="ocHistory"></div>${button('ocNew','另建实验','New experiment')}</div></aside></div></div>`;
  const $ = id => document.getElementById(id);
  function error(message='') { $('ocError').textContent = message; }
  async function api(path, body) {
    const response = await fetch(path, {credentials:'same-origin', ...(body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
    return C.responseValue(response);
  }
  const busyLabels={ocAnalyze:['正在分析…','Analyzing…'],ocAnalyzeBaseline:['正在生成规则…','Generating rules…'],ocSave:['正在保存…','Saving…'],ocRun:['正在启动…','Starting…'],ocPause:['正在请求暂停…','Requesting pause…'],ocResume:['正在继续…','Resuming…'],ocRetry:['正在恢复进度…','Recovering progress…'],ocStop:['正在终止…','Stopping…'],ocRefresh:['正在刷新…','Refreshing…'],ocBuiltin:['正在准备题库…','Preparing benchmark…'],ocImport:['正在检查…','Validating…'],ocSaveMethod:['正在保存…','Saving…']};
  function act(id, action) { $(id).addEventListener('click', async () => {
    if (busy) return;
    busy=id; busyLabel=$(id).innerHTML; error(); update();
    try { await action(); } catch (e) { error(e.message); } finally { $(id).innerHTML=busyLabel; busy=false; update(); }
  }); }
  function invalidate() {
    state.revision++;
    clearTimeout(timer);
    // A saved study is never thrown away by an edit: the record keeps running
    // with the settings it was frozen with, and the edit only affects the
    // next study. The notice says so instead of dropping the link.
    if (state.study) { state.dirty = true; }
    else { const url=new URL(location.href);url.searchParams.delete('comparison');window.history.replaceState(null,'',url); }
    update();
  }
  function chooseStep(step) { if (C.canVisit(step,state)) {state.step=step; update(); if(step===3)refreshPlan();} }
  function moveFocus() {
    const pane = mount.querySelector(`[data-oc-pane="${state.step}"]`);
    const title = pane && pane.querySelector('h2');
    if (title) { title.setAttribute('tabindex','-1'); title.focus({preventScroll:false}); }
  }
  function announceStep() {
    const name = steps[state.step];
    if (!name) return;
    $('ocStepLive').textContent = T(`第${state.step+1}步，共6步：${name[0]}`, `Step ${state.step+1} of 6: ${name[1]}`);
  }
  function baseline() {
    if (!state.method) return null;
    if(state.baseline==='custom') return C.applyFactors(state.method,state.baselineMethod,C.factorTable(state),false);
    const m = JSON.parse(JSON.stringify(state.method));
    m.name=T(kinds.find(k=>k[0]===state.baseline)[1],kinds.find(k=>k[0]===state.baseline)[2]);
    m.topology={kind:state.baseline,probability:.5,edges:[]};
    m.roles=m.roles.map((_,i)=>T(`成员 ${i+1}`,`Member ${i+1}`));m.rounds=state.baseline==='independent'?0:2;m.review=false;m.revisions=0;m.decision='auto';
    return C.applyFactors(state.method,m,C.factorTable(state),true);
  }
  function methodCard(m, caption, actual) { return m ? `<article class="oc-method"><p>${E(caption)}</p><h4>${E(m.name)}</h4>${C.graph(m,actual)}<p class="oc-note">${E(m.roles.join(' · '))}</p><p class="oc-note">${E(T('讨论轮数','Rounds'))}: ${m.rounds} · ${E(({auto:T('按题型汇总','Task-specific readout'),vote:T('投票','Vote'),synthesis:T('成员汇总','Member synthesis')})[m.decision]||m.decision)}${m.review?' · '+E(T('审阅与修订','Review and revise')):''}</p></article>` : `<p class="oc-note">${E(T('先提供组织方式','Provide an organization first'))}</p>`; }
  function scopeNote() {
    if (!state.method) return `<p class="oc-note">${E(T('先采用一份组织方式，这里会显示两臂允许不同的因子。','Adopt an organization first; the factors allowed to differ appear here.'))}</p>`;
    const changed = C.differingFactors(state.method, baseline());
    if (!changed.length) return `<p class="oc-note">${E(T('两臂目前没有差异：请至少允许一个因子不同。','No factor differs yet: allow at least one factor to differ.'))}</p>`;
    const names = changed.map(name=>C.factorLabel(name,en())).join(T('、',', '));
    return `<p class="oc-note">${E(T('本次允许不同的因子：','Factors allowed to differ: ')+names+T('；其余机制两臂完全相同。','; every other mechanism is identical on both arms.'))}</p>`;
  }
  function planSentence(plan) {
    if (!plan) return '';
    const parts = [T(`${plan.cells} 个实验单元`, `${plan.cells} cells`),
      T(`约 ${plan.total_calls} 次模型调用`, `about ${plan.total_calls} model calls`),
      T(`按当前节奏最早 ${C.duration(plan.min_seconds, en())}完成`, `finishes in about ${C.duration(plan.min_seconds, en())}`)];
    return T('本次预计：','Estimated for this run: ')+parts.join(T('；','; '))+'。';
  }
  function renderPlan(plan) {
    if (!plan) { $('ocPlan').textContent=''; return; }
    let html = E(planSentence(plan));
    if (!plan.sufficient) html += ' '+E(T('当前上限不足以完成一次实验单元，无法开始。','The current limits cannot finish one cell; the run cannot start.'));
    (plan.warnings||[]).forEach(w=>{html+=' '+E(w);});
    $('ocPlan').textContent = html;
    const l = plan.limits || {};
    $('ocLimits').textContent = l.calls ? E(T(`每个实验单元的上限：调用 ${l.calls} 次、提示 ${l.prompt_chars} 字符、输入 ${l.input_chars} 字符、输出 ${l.output_chars} 字符（按组织方式本身的形状推算）。`,
      `Per-cell limits: ${l.calls} calls, ${l.prompt_chars} prompt chars, ${l.input_chars} input chars, ${l.output_chars} output chars (derived from the shape of the method).`)) : '';
  }
  async function refreshPlan() {
    const ids = Array.from($('ocMembers').selectedOptions,x=>Number(x.value));
    if (!state.method || !state.benchmark || ids.length!==state.method.roles.length) { state.plan=null; $('ocPlan').textContent=''; return; }
    const revision = state.revision;
    try {
      const r = await api(P+'/plan', C.settings(state, {agent_ids:ids, repeats:Number($('ocRepeats').value),delta:Number($('ocDelta').value),seed:Number($('ocSeed').value),max_tokens:Number($('ocTokens').value)}));
      if (revision!==state.revision) return;
      state.plan=r.plan; renderPlan(r.plan);
    } catch (e) { state.plan=null; $('ocPlan').textContent=E(e.message); }
  }
  function update() {
    mount.querySelectorAll('button,input,select,textarea').forEach(el=>el.disabled=Boolean(busy));
    $('ocCustomBaseline').hidden=state.baseline!=='custom';
    $('ocAnalyzeBaseline').disabled=Boolean(busy)||!state.method||$('ocBaselineText').value.trim().length<10||!state.provider;
    $('ocAdoptBaseline').disabled=Boolean(busy)||!$('ocBaselineJson').value.trim()||Boolean(state.baselineMethod);
    $('ocAdoptBaseline').innerHTML=state.baselineMethod?L('已采用此对照方式','Baseline adopted'):L('采用此对照方式','Use this baseline');
    $('ocBaselineStatus').textContent=state.baselineMethod?T('已采用，修改描述或规则后需要重新采用。','Adopted. Review and adopt again after editing.'):T('请核对并采用对照规则后继续。','Review and adopt the baseline rules to continue.');
    $('ocAnalyze').disabled=Boolean(busy)||!state.provider||$('ocMaterial').value.trim().length<10;
    $('ocAdopt').disabled=Boolean(busy)||!state.method||state.reviewed;
    $('ocBuiltin').disabled=Boolean(busy)||!state.method||!state.reviewed;
    $('ocImport').disabled=Boolean(busy)||!$('ocBenchmarkFile').files.length;
    $('ocAdopt').innerHTML=state.reviewed?L('已采用组织方式','Organization adopted'):L('采用这份组织方式','Use this organization');
    mount.querySelectorAll('[data-oc-pane]').forEach(el=>el.hidden=Number(el.dataset.ocPane)!==state.step);
    mount.querySelectorAll('[data-oc-step]').forEach(el=>{const i=Number(el.dataset.ocStep);el.disabled=Boolean(busy)||!C.canVisit(i,state);el.setAttribute('aria-current',i===state.step?'step':'false');});
    $('ocBack').hidden=state.step===0; $('ocNext').hidden=state.step===5;
    $('ocNext').disabled=Boolean(busy)||!C.canVisit(state.step+1,state);
    $('ocRun').hidden=!state.study || state.study.status!=='draft';
    const record=state.study, spec=record && record.protocol;
    if(record){const url=new URL(location.href);if(url.searchParams.get('comparison')!==record.id){url.searchParams.set('comparison',record.id);window.history.replaceState(null,'',url);}}
    $('ocSave').disabled=Boolean(busy)||(Boolean(record)&&!state.dirty)||!C.canVisit(3,state)||$('ocMembers').selectedOptions.length!==state.method?.roles.length;
    $('ocSave').innerHTML=record?(state.dirty?L('保存为新实验','Save as a new experiment'):L('设置已保存','Settings saved')):L('保存实验设置','Save experiment settings');
    $('ocRun').innerHTML=record?.recovery?L('从保存进度继续','Continue from saved progress'):L('开始实验','Start experiment');
    $('ocSavedProgress').textContent=state.dirty
      ? T('设置已改动。已保存的实验仍按它自己的设置执行，不会被这次改动影响；「保存为新实验」会另建一条记录。','The settings changed. The saved experiment keeps its own frozen settings and is not affected by this edit; “Save as a new experiment” creates another record.')
      : (record?.recovery?T(`已核对并保留${record.rows.length}/${record.protocol.expected}个单元、${record.recovery.verified_responses}次回答。无需再次保存，点击「从保存进度继续」。`,`Verified ${record.rows.length}/${record.protocol.expected} cells and ${record.recovery.verified_responses} responses. Settings are saved; continue from this checkpoint.`):'');
    const extraCandidates=(spec?(spec.arms||[]).filter(a=>!a.is_control&&a.id!=='candidate'):state.candidates.map((c,i)=>({id:i?'candidate-'+(i+1):'candidate',label:c.label,is_control:false})));
    $('ocCompare').innerHTML=methodCard(spec?spec.candidate:state.method,T('新的组织方式','Candidate'),record?.rows?.find(r=>r.arm==='candidate')?.edges)
      +extraCandidates.filter(a=>a.id!=='candidate').map(a=>methodCard(spec?spec.arms.find(x=>x.id===a.id)?.method:null,a.label,record?.rows?.find(r=>r.arm===a.id)?.edges)).join('')
      +methodCard(spec?spec.baseline:baseline(),T('对照方式','Baseline'),record?.rows?.find(r=>r.arm==='baseline')?.edges)
      +`<p class="oc-note">${E(T('图为通信结构示意；运行后显示本次某道题的实际连边。汇总和审阅步骤另按规则执行。','Graphs illustrate communication; after running they show a recorded question graph. Readout and review use their separate rules.'))}</p>`
      +scopeNote();
    $('ocScopeNote').innerHTML=scopeNote();
    const n=state.benchmark?.tasks.length || 0;
    const arms=2+state.candidates.length;
    $('ocEstimate').textContent=T(`已选${n}道题、${state.method?.roles.length||0}个角色。${arms}个组织共${n*Number($('ocRepeats').value)*arms}个实验单元。`,`${n} questions, ${state.method?.roles.length||0} roles; ${arms} arms, ${n*Number($('ocRepeats').value)*arms} arm/question runs.`);
    if (spec) $('ocEstimate').textContent+=T(` 调用上限${spec.budget.max_requests}次；实际消耗另计。`, ` At most ${spec.budget.max_requests} requests; actual usage is reported separately.`);
    if (spec && spec.plan && !state.dirty) renderPlan(spec.plan);
    if (record) renderStudy(record);
    mount.querySelectorAll('[data-oc-study]').forEach(el=>{
      el.setAttribute('aria-current',el.dataset.ocStudy===record?.id?'true':'false');
      if(el.dataset.ocStudy===record?.id)el.querySelector('small:last-child').textContent=statusName(record.status)+` · ${record.rows.length}/${record.protocol.expected}`;
    });
    if(busy && $(busy)){ $(busy).setAttribute('aria-busy','true'); $(busy).textContent=T(...(busyLabels[busy]||['处理中…','Working…'])); }
    mount.querySelectorAll('button[aria-busy]').forEach(el=>{if(el.id!==busy)el.removeAttribute('aria-busy');});
    // A step change is announced and takes the focus, so a keyboard reader
    // knows where the page went.
    if (state.announcedStep !== undefined && state.announcedStep !== state.step) { moveFocus(); announceStep(); }
    state.announcedStep = state.step;
  }
  function renderCandidates() {
    const names=state.candidates.map((c,i)=>`<p>${E(c.label)} · ${E(T('候选','Candidate'))}${i+2} <button type="button" class="btn" data-oc-drop="${i}">${L('移出这次比较','Remove from this comparison')}</button></p>`).join('');
    $('ocCandidates').innerHTML=names||`<p class="oc-note">${E(T('还没有其他候选：一次只比较这一个组织也可以。','No other candidate yet: comparing this one organization alone is fine.'))}</p>`;
    mount.querySelectorAll('[data-oc-drop]').forEach(el=>el.onclick=()=>{state.candidates.splice(Number(el.dataset.ocDrop),1);invalidate();refreshPlan();});
    $('ocExtraCard').hidden=!state.method;
    $('ocAddCandidate').disabled=busy||!state.method||state.candidates.length>=3||!$('ocSavedMethod').value;
  }
  function edit(method) {
    state.method=method; state.reviewed=false; $('ocEditor').hidden=false;
    $('ocMethodName').value=method.name; $('ocRoles').value=method.roles.join('\n'); $('ocTopology').value=method.topology.kind;
    $('ocRounds').value=method.rounds; $('ocDecision').value=method.decision;
    const review=C.reviewFields(method);$('ocReviewEnabled').checked=review.review;$('ocReview').value=review.revisions;
    $('ocRuleJson').value=JSON.stringify(method,null,2);
    $('ocRules').innerHTML=(method.rules||[]).map((r,i)=>`<label class="oc-rule">${L('规则','Rule')} ${i+1} · ${E(({source:T('来自原文','From source'),inferred:T('系统补充','Inferred'),user:T('用户修改','User edit')})[r.origin]||r.origin)}<textarea data-oc-rule="${i}" rows="2">${E(r.text)}</textarea><small>${E(r.quote||T('系统补充或用户定义，未声称为原文','Inferred or user-defined; not claimed as source text'))}</small></label>`).join('');
    $('ocLibraryName').value=method.name; update(); renderCandidates();
  }
  function readMethod() {
    const m=JSON.parse(JSON.stringify(state.method));
    m.name=$('ocMethodName').value.trim();m.roles=$('ocRoles').value.split('\n').map(s=>s.trim()).filter(Boolean);
    if (m.roles.length<2 || m.roles.length>12) throw new Error(T('需要2–12个角色','Use 2–12 roles'));
    m.topology.kind=$('ocTopology').value;m.rounds=Number($('ocRounds').value);m.decision=$('ocDecision').value;
    m.review=$('ocReviewEnabled').checked;m.revisions=m.review?Number($('ocReview').value):0;
    mount.querySelectorAll('[data-oc-rule]').forEach(el=>{const r=m.rules[Number(el.dataset.ocRule)];if(r.text!==el.value){r.text=el.value;r.origin='user';}});
    return m;
  }
  function loadStudy(record) {
    const p=record.protocol, fields=C.protocolFields(p);
    state.study=null;state.baseline=fields.baseline;state.baselineMethod=fields.baseline==='custom'?p.baseline:null;
    edit(p.candidate);
    state.reviewed=true;state.study=record;state.dirty=false;state.plan=fields.plan||null;
    state.factors=Object.assign({},C.DEFAULT_FACTORS,fields.factors||{});
    state.benchmark=p.benchmark;state.provider=fields.provider;state.baseline=fields.baseline;state.ids=fields.ids;
    state.candidates=(p.arms||[]).filter(a=>!a.is_control&&a.id!=='candidate').map(a=>({label:a.label,method:a.method}));
    $('ocMaterial').value=p.candidate.source?.text||'';$('ocTitle').value=p.candidate.source?.title||'';
    if(!Array.from($('ocProvider').options).some(o=>o.value===fields.provider))$('ocProvider').add(new Option(fields.provider,fields.provider));
    $('ocProvider').value=fields.provider;
    mount.querySelectorAll('[name=ocBaseline]').forEach(el=>el.checked=el.value===fields.baseline);
    mount.querySelectorAll('[data-oc-factor]').forEach(el=>el.checked=state.factors[el.dataset.ocFactor]==='candidate');
    $('ocBaselineText').value=state.baselineMethod?.source?.text||'';
    $('ocBaselineJson').value=state.baselineMethod?JSON.stringify(state.baselineMethod,null,2):'';
    $('ocBaselinePreview').innerHTML=state.baselineMethod?methodCard(state.baselineMethod,T('自定义对照规则','Custom baseline rules')):'';
    for(const [id,key] of [['ocRepeats','repeats'],['ocDelta','delta'],['ocSeed','seed'],['ocCalls','calls'],['ocTokens','tokens']])$(id).value=fields[key];
    Array.from($('ocMembers').options).forEach(o=>o.selected=fields.ids.includes(Number(o.value)));
    preview(p.benchmark); renderCandidates();
    state.step=record.status==='draft'?3:4;
    const url=new URL(location.href);url.searchParams.set('comparison',record.id);window.history.replaceState(null,'',url);
    error();update();
  }
  function renderStudy(r) {
    const a=r.analysis||{}, c=C.controls(r,Boolean(busy));
    const labels={draft:T('设置已保存','Settings saved'),running:T('运行中','Running'),paused:T('已暂停','Paused'),interrupted:T('运行中断，可继续','Interrupted; resumable'),completed:T('已完成','Completed'),stopped:T('已终止','Stopped'),rate_limited:T('模型限流，已保留进度','Rate limited; progress saved')};
    $('ocProgress').textContent=`${r.status==='running'&&r.control?T(r.control==='stop'?'正在终止，等待当前请求结束':'正在暂停，等待当前请求结束',r.control==='stop'?'Stopping after the current request':'Pausing after the current request'):labels[r.status]||r.status} · ${r.rows.length}/${r.protocol.expected} · ${r.metrics?.calls||0} ${T('次实际调用','requests')} `;
    $('ocBar').max=r.protocol.expected; $('ocBar').value=r.rows.length;
    const cooling=C.coolingDown(r), failure=C.failureMessage(r,en());
    $('ocFailure').textContent=failure;
    $('ocWait').textContent=r.error_info?.retry_at ? T('最早可手动继续：','Earliest manual retry: ')+new Date(r.error_info.retry_at*1000).toLocaleString()+T('。这是本地等待下限，不代表服务商保证额度已恢复；页面不会自动重试。',' . This is a local lower bound, not a provider guarantee. No automatic retries.') : r.waiting ? T('正在按已保存的请求间隔等待；可以随时暂停。','Waiting for the frozen request interval; you may pause at any time.') : '';
    $('ocRecovery').textContent=r.recovery ? T(`恢复副本：复用${r.recovery.reused_cells}个已完成单元和${r.recovery.verified_responses}次已保存回答，原实验保留不变。`,`Recovery copy: reuses ${r.recovery.reused_cells} completed cells and ${r.recovery.verified_responses} saved responses; the source study is unchanged.`) : '';
    $('ocFailureDetails').hidden=!r.error_info&&!r.recovery;
    $('ocFailureJson').textContent=JSON.stringify({error:r.error_info||r.error||null,recovery:r.recovery||null},null,2);
    $('ocRun').disabled=busy||cooling;
    for(const [id,key] of [['ocPause','pause'],['ocResume','resume'],['ocRetry','retry'],['ocStop','stop']]){ $(id).hidden=!c[key];$(id).disabled=c[key+'Disabled']; }
    $('ocPause').innerHTML=c.pauseLabel==='pausing'?L('正在暂停…','Pausing…'):L('暂停','Pause');
    $('ocStop').innerHTML=r.status==='running'&&r.control==='stop'?L('正在终止…','Stopping…'):L('终止','Stop');
    $('ocRetry').innerHTML=r.retry_blocked_reason?L('请求已达上限，请另建实验','Request limit reached; create a new experiment'):cooling?L('等待服务恢复后重试','Retry after cooldown'):L('重新运行（保留进度）','Retry from saved progress');
    $('ocResume').innerHTML=cooling?L('等待后继续','Resume after cooldown'):L('继续实验','Resume');
    const f=x=>typeof x==='number'?x.toFixed(4):'—';
    $('ocResult').innerHTML=`<p class="oc-verdict" data-verdict="${E(a.verdict||'incomplete')}">${E(C.verdict(a.verdict,en()))}</p>`
      +`<p>${E(T('主指标：0–1成绩，越高越好。差异为候选减去对照。','Primary score: 0–1, higher is better. Difference is candidate minus baseline.'))}</p>`
      +`<p class="oc-note">${E(T('模型','Model'))}: ${E(r.protocol.model.model)} · ${E(r.protocol.scope==='topology'?T('仅比较通信结构','Communication structure only'):T('比较整套组织方式','Whole-method comparison'))} · ${E(r.protocol.benchmark.name)}</p>`
      +`<div class="oc-score"><div><small>${E(T('候选平均成绩','Candidate mean'))}</small><strong>${f(a.arms?.candidate?.mean)}</strong></div><div><small>${E(T('对照平均成绩','Baseline mean'))}</small><strong>${f(a.arms?.baseline?.mean)}</strong></div><div><small>${E(T('配对差异','Paired difference'))}</small><strong>${f(a.difference)}</strong></div></div>`
      +`<div class="oc-table"><table><thead><tr>${[T('组织','Arm'),T('完成率','Completion'),T('调用次数','Calls'),T('字符（入/出）','Chars (in/out)'),T('耗时（秒）','Call seconds'),T('未能测量','Not measured')].map(x=>'<th>'+E(x)+'</th>').join('')}</tr></thead><tbody>${Object.entries(a.arms||{}).map(([arm,v])=>{if(!v)return'';const label=C.armLabel(r.protocol,arm);return '<tr><td>'+E(label)+'</td><td>'+f(v.completion_rate)+'</td><td>'+v.calls+'</td><td>'+(v.input_chars??'—')+' / '+(v.output_chars??'—')+'</td><td>'+f(v.elapsed)+'</td><td>'+(v.unmeasured??0)+'</td></tr>';}).join('')}</tbody></table></div>`
      +(a.candidates&&Object.keys(a.candidates).length>1?`<div class="oc-verdicts">${Object.entries(a.candidates).map(([arm,entry])=>`<p><strong>${E(C.armLabel(r.protocol,arm))}</strong>：${E(C.verdict(entry.verdict,en()))}${(entry.interval?` · ${E(T('差异','Difference'))} ${f(entry.difference)} · 95% CI ${entry.interval.map(f).join(' – ')}`:'')}</p>`).join('')}</div>`:'')
      +`<p class="oc-note">95% CI: ${a.interval?a.interval.map(f).join(' – '):'—'} · ${a.independent_tasks||0} ${E(T('道独立题；少于30题只作探索。','independent questions; fewer than 30 is exploratory.'))}</p>`
      +(a.unmeasured_rows?`<p class="oc-note">${E(T(`有 ${a.unmeasured_rows} 个实验单元未能测量：未计入比较，也没有被当作错误答案。`,'Cells that could not be measured: '+a.unmeasured_rows+'. They are not counted, and they are not wrong answers.'))}${(a.unmeasured||[]).slice(0,6).map(u=>E(u.cell+' '+u.reason)).join(T('；','; '))}</p>`:'')
      +(r.protocol.plan?`<p class="oc-note">${E(planSentence(r.protocol.plan))}</p>`:'')
      + (a.categories?.length ? '<details><summary>'+E(T('探索性题型比较','Exploratory category comparisons'))+'</summary>'+a.categories.map(c=>'<p>'+E(c.category)+': '+f(c.candidate)+' / '+f(c.baseline)+' · '+E(T('差异','Difference'))+' '+f(c.difference)+'</p>').join('')+'</details>':'')
      +`<p class="oc-note">${E(T('结论仅适用于本次模型、成员、题库和运行限制。token与金额未知时不估造；成绩更高不自动意味着更省资源。','Results apply to this model, roster, benchmark and limits. Unknown tokens/costs are not estimated. Higher scores do not automatically imply lower resource use.'))}</p>`;
    $('ocRows').innerHTML='<table><thead><tr>'+['题目 / Question','重复 / Repeat','组 / Arm','成绩 / Score','错误 / Error'].map(s=>`<th>${E(s)}</th>`).join('')+'</tr></thead><tbody>'+r.rows.map(row=>`<tr><td>${E(row.task_id)}</td><td>${row.repeat+1}</td><td>${E(row.arm)}</td><td>${row.measured===false?E(T('未能测量','not measured')):f(row.score)}</td><td>${E(row.error||row.invalid_reason||'')}</td></tr>`).join('')+'</tbody></table>';
    $('ocDuplicate').hidden=!r; $('ocDelete').hidden=!r;
  }
  async function refresh() {
    if (!state.study) return;
    const id=state.study.id, revision=state.revision;
    const r=await api(P+'/'+id);
    if (state.revision!==revision || state.study?.id!==id) return;
    state.study=r; update();clearTimeout(timer);
    if(C.shouldPoll(r)) timer=setTimeout(()=>refresh().catch(e=>error(e.message)),r.status==='running'?2000:10000);
  }

  function renderSummary(data) {
    const totals=data.totals||{}, verdicts=data.verdicts||{}, studies=data.studies||[];
    if (!studies.length) { $('ocSummary').innerHTML=`<p class="oc-note">${E(T('这个世界里还没有对照实验。','No comparison study in this world yet.'))}</p>`; return; }
    const cards=[[T('实验','Studies'),totals.studies],[T('已完成','Completed'),totals.completed],
      [T('实际调用','Actual calls'),totals.calls],[T('输入字符','Input chars'),totals.input_chars],
      [T('输出字符','Output chars'),totals.output_chars],
      [T('调用耗时（秒）','Call seconds'),(totals.elapsed||0).toFixed(1)],
      [T('每项平均调用','Calls per study'),totals.calls_per_study]];
    const head=`<div class="oc-score">${cards.map(([label,value])=>`<div><small>${E(label)}</small><strong>${E(String(value))}</strong></div>`).join('')}</div>`;
    const tally=Object.entries(verdicts).filter(([,n])=>n).map(([key,n])=>`<span class="oc-tally">${E(C.verdict(key,en()))} ${E(String(n))}</span>`).join(' ');
    const rows=studies.map(s=>`<tr><td>${E(s.title)}</td><td>${E(new Date((s.created_at||0)*1000).toLocaleDateString())}</td>`
      +`<td>${E(statusName(s.status))}</td><td>${E(C.verdict(s.verdict,en()))}</td>`
      +`<td>${E((s.arms||[]).join(' / '))}</td><td>${E(String(s.calls||0))}</td>`
      +`<td>${E(String(s.input_chars||0))} / ${E(String(s.output_chars||0))}</td><td>${(s.elapsed||0).toFixed(1)}</td></tr>`).join('');
    $('ocSummary').innerHTML=head+`<p class="oc-note">${tally||''}</p>`
      +`<div class="oc-table"><table><thead><tr>${[T('实验','Study'),T('日期','Date'),T('状态','Status'),T('结论','Verdict'),T('组织','Arms'),T('调用','Calls'),T('字符（入/出）','Chars (in/out)'),T('耗时（秒）','Call seconds')].map(x=>'<th>'+E(x)+'</th>').join('')}</tr></thead><tbody>${rows}</tbody></table></div>`
      +`<p class="oc-note">${E(T('调用次数和字符不是 token 或金额；模型没有返回可靠计量时标为未知。','Calls and characters are not tokens or money; unknown metering is reported as unknown.'))}</p>`;
  }
  async function refreshSummary() {
    if (!$('ocSummary')) return;
    try { renderSummary(await api(P+'/summary')); } catch (e) { $('ocSummary').innerHTML=`<p class="oc-note">${E(e.message)}</p>`; }
  }
  function statusName(status) {return ({draft:T('设置已保存','Settings saved'),running:T('运行中','Running'),paused:T('已暂停','Paused'),interrupted:T('运行中断','Interrupted'),completed:T('已完成','Completed'),stopped:T('已终止','Stopped'),rate_limited:T('模型限流','Rate limited')})[status]||status;}
  async function history() {
    const list=(await api(P)).studies;
    $('ocHistory').innerHTML=list.map(r=>`<button type="button" class="oi-record" data-oc-study="${E(r.id)}">${E(r.title)}<small>${E(new Date(r.created_at*1000).toLocaleString())} · ${E(r.id.slice(-6))}</small><small>${E(statusName(r.status))} · ${r.analysis?.rows||0}/${r.analysis?.expected||'—'}</small></button>`).join('')||`<p class="oc-note">${E(T('还没有实验','No experiments yet'))}</p>`;
    update();
    await refreshSummary();
  }
  function download(filename,text,type='text/plain') {const a=document.createElement('a'),url=URL.createObjectURL(new Blob([text],{type}));a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  async function readPaper(file) {
    if (!file) return;
    if(file.size>10_000_000) throw new Error(T('文件不能超过10MB','File limit: 10MB'));
    if(/\.pdf$/i.test(file.name)) {
      const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(file);});
      return (await api('/api/research/extract',{name:file.name,data})).text;
    }
    return file.text();
  }
  mount.querySelectorAll('[data-oc-step]').forEach(el=>el.onclick=()=>chooseStep(Number(el.dataset.ocStep)));
  $('ocBack').onclick=()=>chooseStep(state.step-1);$('ocNext').onclick=()=>chooseStep(state.step+1);
  $('ocMaterialFile').onchange=async()=>{try{$('ocMaterial').value=await readPaper($('ocMaterialFile').files[0]);$('ocFileNote').textContent=$('ocMaterialFile').files[0]?.name||'';state.method=null;$('ocEditor').hidden=true;invalidate();}catch(e){error(e.message);}};
  $('ocMaterial').oninput=()=>{state.method=null;$('ocEditor').hidden=true;invalidate();};
  $('ocProvider').onchange=()=>{state.provider=$('ocProvider').value;invalidate();};
  act('ocAnalyze',async()=>{const revision=state.revision;const data=await api(P+'/analyze',{text:$('ocMaterial').value,title:$('ocTitle').value,provider:state.provider});if(revision!==state.revision)return;if(data.runnable===false)throw new Error(T('暂不能实现：','Unsupported: ')+data.unsupported.join(', '));invalidate();edit(data);});
  act('ocExample',()=>{invalidate();edit({version:'organization-method-1',name:T('分工讨论与交叉审阅','Role discussion with peer review'),description:'',roles:[T('分析','Analyze'),T('核对','Check'),T('决策','Decide')],topology:{kind:'full',probability:.5,edges:[]},rounds:2,decision:'auto',review:true,revisions:1,memory:'reset',rules:[{text:T('各自分析后交换信息，再交叉审阅并修订。','Work independently, exchange evidence, peer-review and revise.'),quote:'',origin:'inferred'}],source:{title:T('示例规则','Example rules'),text:''},unsupported:[]});});
  act('ocApplyJson',()=>{const m=JSON.parse($('ocRuleJson').value);if(!Array.isArray(m.roles)||!m.topology)throw new Error(T('规则格式不完整','Incomplete method'));invalidate();edit(m);});
  act('ocAdopt',()=>{const m=readMethod();if(state.method.roles.length!==m.roles.length){state.benchmark=null;state.baselineMethod=null;}invalidate();state.method=m;state.reviewed=true;state.step=1;update();});
  ['ocMethodName','ocRoles','ocTopology','ocRounds','ocDecision','ocReview','ocReviewEnabled','ocRules'].forEach(id=>$(id).addEventListener('input',()=>{if(state.method){state.reviewed=false;invalidate();}}));
  mount.querySelectorAll('[name=ocBaseline]').forEach(el=>el.onchange=()=>{state.baseline=el.value;invalidate();});
  mount.querySelectorAll('[data-oc-factor]').forEach(el=>el.onchange=()=>{state.factors[el.dataset.ocFactor]=el.checked?'candidate':'same';invalidate();refreshPlan();});
  $('ocBaselineText').oninput=()=>{state.baselineMethod=null;state.baselineDraft=null;$('ocBaselineJson').value='';$('ocBaselinePreview').textContent='';invalidate();};
  $('ocBaselineJson').oninput=()=>{state.baselineMethod=null;invalidate();};
  act('ocAnalyzeBaseline',async()=>{const rev=state.revision;const m=await api(P+'/analyze',{text:$('ocBaselineText').value,title:T('自定义对照','Custom baseline'),provider:state.provider,slots:state.method.roles.length});if(rev!==state.revision)return;if(m.runnable===false)throw new Error(T('暂不支持：','Unsupported: ')+m.unsupported.join(', '));state.baselineDraft=m;state.baselineMethod=null;$('ocBaselineJson').value=JSON.stringify(m,null,2);$('ocBaselinePreview').innerHTML=methodCard(m,T('待核对的对照规则','Baseline rules to review'));invalidate();});
  act('ocAdoptBaseline',()=>{const m=JSON.parse($('ocBaselineJson').value);if(!Array.isArray(m.roles)||m.roles.length!==state.method.roles.length||!m.topology)throw new Error(T('对照角色数量必须匹配，且需要通信结构。','Baseline roles must match the candidate and include a communication structure.'));state.baselineMethod=m;$('ocBaselinePreview').innerHTML=methodCard(m,T('已采用的对照规则','Adopted baseline rules'));invalidate();});
  $('ocBenchmarkFile').onchange=update;

  function preview(bank) {state.benchmark=bank;const q=bank.tasks[0];$('ocBenchmarkPreview').innerHTML=`<h3>${E(bank.name)} · ${bank.tasks.length} ${E(T('道题','questions'))}</h3><p>${E(q.prompt)}</p><p class="oc-note">${E(T('验证通过；评分范围0–1。参考答案仅供评分端使用。','Validated; scores range from 0 to 1. References are available only to the scorer.'))}</p>`;update();}
  act('ocBuiltin',async()=>{const rev=state.revision;const r=await api(P+'/benchmark',{problem:$('ocProblem').value,count:Number($('ocCount').value),slots:state.method.roles.length});if(rev!==state.revision)return;invalidate();preview(r.benchmark);});
  act('ocImport',async()=>{const file=$('ocBenchmarkFile').files[0];if(!file)throw new Error(T('请选择题库文件','Choose a benchmark file'));if(file.size>2_000_000)throw new Error(T('题库不能超过2MB','Benchmark limit: 2MB'));const rev=state.revision;const text=await file.text();const r=await api(P+'/benchmark',{text,format:/\.csv$/i.test(file.name)?'csv':'jsonl',mapping:JSON.parse($('ocMapping').value),scorer:$('ocScorer').value,name:file.name});if(rev!==state.revision)return;invalidate();preview(r.benchmark);});
  ['ocRepeats','ocDelta','ocSeed','ocCalls','ocTokens','ocMembers'].forEach(id=>$(id).addEventListener('input',()=>{invalidate();refreshPlan();}));
  act('ocSave',async()=>{state.ids=Array.from($('ocMembers').selectedOptions,x=>Number(x.value));if(state.ids.length!==state.method.roles.length)throw new Error(T('居民人数必须与角色数量相同','Resident count must match role count'));const rev=state.revision;const record=await api(P,C.settings(state,{repeats:Number($('ocRepeats').value),delta:Number($('ocDelta').value),seed:Number($('ocSeed').value),limits:{calls:Number($('ocCalls').value)},max_tokens:Number($('ocTokens').value)}));if(rev!==state.revision)return;state.study=record;state.dirty=false;state.ids=record.protocol.members.map(m=>m.id);const url=new URL(location.href);url.searchParams.set('comparison',record.id);window.history.replaceState(null,'',url);await history();});
  act('ocDuplicate',async()=>{const r=await api(P+'/'+state.study.id+'/duplicate',{});state.revision++;loadStudy(r);await history();});
  act('ocDelete',async()=>{if(!window.confirm(T('删除这条实验记录？已保存的证据会一并删除，无法恢复。','Delete this experiment record? Its saved evidence goes with it and cannot be recovered.')))return;await api(P+'/'+state.study.id+'/delete',{});state.study=null;state.dirty=false;state.step=3;const url=new URL(location.href);url.searchParams.delete('comparison');window.history.replaceState(null,'',url);await history();});
  act('ocRun',async()=>{if(state.study.resume_requires_recovery)return continueStudy();await api(P+'/'+state.study.id+'/run',{});state.step=4;await refresh();await history();});
  for(const [id,action] of [['ocPause','pause'],['ocStop','stop']])act(id,async()=>{await api(P+'/'+state.study.id+'/'+action,{});await refresh();});
  async function continueStudy(){if(state.study.resume_requires_recovery){const r=await api(P+'/'+state.study.id+'/recover',{});state.revision++;loadStudy(r);}await api(P+'/'+state.study.id+'/resume',{});state.step=4;await refresh();await history();}
  act('ocResume',continueStudy);act('ocRetry',continueStudy);
  act('ocRefresh',refresh);
  for(const [id,route,key,type] of [['ocReport','export','markdown','text/markdown'],['ocCsv','csv','csv','text/csv'],['ocSettings','protocol','protocol','application/json'],['ocAudit','audit','record','application/json']])act(id,async()=>{const r=await api(P+'/'+state.study.id+'/'+route);download(r.filename,typeof r[key]==='string'?r[key]:JSON.stringify(r[key],null,2),type);});
  act('ocSaveMethod',async()=>{const r=await api(P+'/'+state.study.id+'/save-method',{name:$('ocLibraryName').value});$('ocSavedMethod').textContent=T(`已保存「${r.name}」版本${r.version}。在合作任务中选择相同人数即可使用。`,`Saved “${r.name}”, version ${r.version}. Select it in Cooperation with the matching team size.`);});
  $('ocNew').onclick=()=>{if(busy)return;clearTimeout(timer);state.revision++;state.study=null;state.dirty=false;state.plan=null;state.step=0;const url=new URL(location.href);url.searchParams.delete('comparison');window.history.replaceState(null,'',url);error();update();};
  $('ocHistory').onclick=async event=>{const b=event.target.closest('[data-oc-study]');if(!b||busy)return;busy='history';$('ocHistoryStatus').textContent=T('正在打开实验…','Opening experiment…');update();try{clearTimeout(timer);state.revision++;const revision=state.revision;const record=await api(P+'/'+b.dataset.ocStudy);if(revision!==state.revision)return;loadStudy(record);if(C.shouldPoll(state.study))await refresh();}catch(e){error(e.message);}finally{busy=false;$('ocHistoryStatus').textContent='';update();}};
  document.addEventListener('locale-changed',()=>{mount.querySelectorAll('[data-oc-en]').forEach(el=>el.textContent=en()?el.dataset.ocEn:el.dataset.ocZh);update();});
  act('ocAddCandidate',()=>{const saved=state.savedMethods.find(m=>String(m.id)===$('ocSavedMethod').value);if(!saved)throw new Error(T('请选择已保存的组织方式','Choose a saved organization'));if(state.candidates.length>=3)throw new Error(T('一次最多比较4个组织','At most 4 arms per comparison'));const method=saved.method||saved;if(state.method&&method.roles.length!==state.method.roles.length)throw new Error(T('候选的角色数量必须与第一个候选相同','A candidate needs the same number of roles as the first one'));state.candidates.push({label:saved.name||method.name,method:method});invalidate();refreshPlan();renderCandidates();});
  async function init() {try{context=await api(P+'/context');$('ocProvider').innerHTML=context.providers.map(p=>`<option value="${E(p.name)}">${E(p.name)} · ${E(p.model||'')}</option>`).join('');if(context.default_provider&&context.providers.some(p=>p.name===context.default_provider))$('ocProvider').value=context.default_provider;state.provider=$('ocProvider').value;$('ocMembers').innerHTML=context.members.map((p,i)=>`<option value="${p.id}" ${i<3?'selected':''}>${E(p.name)} · ${p.id}</option>`).join('');$('ocFactors').innerHTML=C.FACTORS.map(([id,zh,eng])=>`<label class="oc-check"><input type="checkbox" data-oc-factor="${id}" ${C.DEFAULT_FACTORS[id]==='candidate'?'checked':''}>${L(zh,eng)}</label>`).join('');mount.querySelectorAll('[data-oc-factor]').forEach(el=>el.onchange=()=>{state.factors[el.dataset.ocFactor]=el.checked?'candidate':'same';invalidate();refreshPlan();});mount.querySelectorAll('[data-oc-pane]').forEach(el=>{const title=el.querySelector('h2');if(!title)return;if(!title.id)title.id='ocPane'+el.dataset.ocPane+'Title';el.setAttribute('role','region');el.setAttribute('aria-labelledby',title.id);});$('ocBar').setAttribute('aria-label',T('实验进度','Experiment progress'));try{const library=await api('/api/collaboration/organization-methods');state.savedMethods=library.methods||[];$('ocSavedMethod').innerHTML=state.savedMethods.map(m=>`<option value="${E(m.id)}">${E(m.name)}</option>`).join('');}catch(e){state.savedMethods=[];}renderCandidates();await history();const linked=C.studyFromSearch(location.search);if(linked){loadStudy(await api(P+'/'+linked));if(C.shouldPoll(state.study))await refresh();}update();}catch(e){error(e.message);}}
  update();init();
}());
