(function () {
  'use strict';
  const C = window.OrganizationComparisonCore;
  const mount = document.getElementById('organizationComparison');
  if (!C || !mount) return;
  const P = '/api/research/organization-intelligence/comparisons';
  const state = {step:0, method:null, benchmark:null, study:null, ids:[], provider:'', baseline:'random', revision:0, reviewed:false};
  let context = {}, timer = null, busy = false;
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
      </div></section>
    <section data-oc-pane="1" class="rw-card" hidden><p class="oc-index">02 / CONTROL</p><h2>${L('与哪种基本方式比较？','Choose a baseline')}</h2>
      <div id="ocBaselineCards" class="oc-baselines">${kinds.map(([id,zh,eng])=>`<label><input type="radio" name="ocBaseline" value="${id}" ${id==='random'?'checked':''}>${L(zh,eng)}</label>`).join('')}</div>
      <p>${L('随机网络默认无向、无自环，连边概率为0.5。每题每次重复独立生成，题内保持不变。','Random networks are undirected, without self-links, with edge probability 0.5. A new fixed graph is drawn for each question and repeat.')}</p>
      <p>${L('默认保留基本组织的规则；若新方式还改变分工、审阅或决策，报告将比较整套组织方式。','Baseline mechanisms are retained. Changes in roles, review or decision rules are evaluated as a whole method.')}</p>
      <label class="oc-field">${L('比较范围','Comparison scope')}<select id="ocMode">${options([['auto','自动识别（推荐）','Detect automatically (recommended)'],['topology','只比较通信结构：其他规则保持一致','Communication only: match other mechanisms'],['whole_method','比较整套组织方式','Compare the whole method']])}</select></label>
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
        <label class="oc-field">${L('每次最大输出 token','Max output tokens per call')}<input id="ocTokens" type="number" min="64" max="4096" value="2048"></label></div></details>
      <p id="ocEstimate" class="oc-note"></p><div class="oc-actions">${button('ocSave','保存实验设置','Save experiment settings','primary')}${button('ocRun','开始实验','Start experiment','primary')}</div>
      <p>${L('保存不会调用实验模型。点击开始后才发生实际调用。未完成或小样本结果不作优势结论。','Saving makes no experiment calls. Starting uses the model. Incomplete or small samples cannot establish superiority.')}</p>
    </section>
    <section data-oc-pane="4" class="rw-card" hidden><p class="oc-index">05 / EVIDENCE</p><h2>${L('看成绩，也看代价','Compare scores and costs')}</h2>
      <div id="ocProgress" aria-live="polite"></div><progress id="ocBar" max="1" value="0"></progress>
      <div class="oc-actions">${button('ocPause','暂停','Pause')}${button('ocResume','继续实验','Resume')}${button('ocStop','终止','Stop')}${button('ocRefresh','刷新进度','Refresh')}</div>
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
      <div class="rw-card"><h3>${L('实验记录','Experiments')}</h3><div id="ocHistory"></div>${button('ocNew','另建实验','New experiment')}</div></aside></div></div>`;
  const $ = id => document.getElementById(id);
  function error(message='') { $('ocError').textContent = message; }
  async function api(path, body) {
    const response = await fetch(path, {credentials:'same-origin', ...(body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
    const value = await response.json();
    if (!response.ok || value.error) throw new Error(value.error || `HTTP ${response.status}`);
    return value;
  }
  function act(id, action) { $(id).addEventListener('click', async () => {
    if (busy) return;
    busy=true; $(id).disabled=true; $(id).setAttribute('aria-busy','true'); error();
    try { await action(); } catch (e) { error(e.message); } finally { busy=false; $(id).disabled=false; $(id).removeAttribute('aria-busy'); update(); }
  }); }
  function invalidate() { state.revision++; state.study=null; clearTimeout(timer); update(); }
  function chooseStep(step) { if (C.canVisit(step,state)) {state.step=step; update();} }
  function baseline() {
    if (!state.method) return null;
    const m = JSON.parse(JSON.stringify(state.method));
    m.name=T(kinds.find(k=>k[0]===state.baseline)[1],kinds.find(k=>k[0]===state.baseline)[2]);
    m.topology={kind:state.baseline,probability:.5,edges:[]};
    if ($('ocMode').value !== 'topology') {m.roles=m.roles.map((_,i)=>T(`成员 ${i+1}`,`Member ${i+1}`));m.rounds=state.baseline==='independent'?0:2;m.review=false;m.revisions=0;m.decision='auto';}
    return m;
  }
  function methodCard(m, caption, actual) { return m ? `<article class="oc-method"><p>${E(caption)}</p><h4>${E(m.name)}</h4>${C.graph(m,actual)}<p class="oc-note">${E(m.roles.join(' · '))}</p><p class="oc-note">${E(T('讨论轮数','Rounds'))}: ${m.rounds} · ${E(({auto:T('按题型汇总','Task-specific readout'),vote:T('投票','Vote'),synthesis:T('成员汇总','Member synthesis')})[m.decision]||m.decision)}${m.review?' · '+E(T('审阅与修订','Review and revise')):''}</p></article>` : `<p class="oc-note">${E(T('先提供组织方式','Provide an organization first'))}</p>`; }
  function update() {
    mount.querySelectorAll('[data-oc-pane]').forEach(el=>el.hidden=Number(el.dataset.ocPane)!==state.step);
    mount.querySelectorAll('[data-oc-step]').forEach(el=>{const i=Number(el.dataset.ocStep);el.disabled=!C.canVisit(i,state);el.setAttribute('aria-current',i===state.step?'step':'false');});
    $('ocBack').hidden=state.step===0; $('ocNext').hidden=state.step===5;
    $('ocNext').disabled=!C.canVisit(state.step+1,state);
    $('ocRun').hidden=!state.study || state.study.status!=='draft';
    const record=state.study, spec=record && record.protocol;
    $('ocCompare').innerHTML=methodCard(spec?spec.candidate:state.method,T('新的组织方式','Candidate'),record?.rows?.find(r=>r.arm==='candidate')?.edges)
      +methodCard(spec?spec.baseline:baseline(),T('对照方式','Baseline'),record?.rows?.find(r=>r.arm==='baseline')?.edges)
      +`<p class="oc-note">${E(T('图为通信结构示意；运行后显示本次某道题的实际连边。汇总和审阅步骤另按规则执行。','Graphs illustrate communication; after running they show a recorded question graph. Readout and review use their separate rules.'))}</p>`;
    const n=state.benchmark?.tasks.length || 0;
    $('ocEstimate').textContent=T(`已选${n}道题、${state.method?.roles.length||0}个角色。两组共${n*Number($('ocRepeats').value)*2}个实验单元。`,`${n} questions, ${state.method?.roles.length||0} roles; ${n*Number($('ocRepeats').value)*2} arm/question runs.`);
    if (spec) $('ocEstimate').textContent+=T(` 调用上限${spec.budget.max_requests}次；实际消耗另计。`, ` At most ${spec.budget.max_requests} requests; actual usage is reported separately.`);
    if (record) renderStudy(record);
  }
  function edit(method) {
    state.method=method; state.reviewed=false; $('ocEditor').hidden=false;
    $('ocMethodName').value=method.name; $('ocRoles').value=method.roles.join('\n'); $('ocTopology').value=method.topology.kind;
    $('ocRounds').value=method.rounds; $('ocDecision').value=method.decision;
    const review=C.reviewFields(method);$('ocReviewEnabled').checked=review.review;$('ocReview').value=review.revisions;
    $('ocRuleJson').value=JSON.stringify(method,null,2);
    $('ocRules').innerHTML=(method.rules||[]).map((r,i)=>`<label class="oc-rule">${L('规则','Rule')} ${i+1} · ${E(({source:T('来自原文','From source'),inferred:T('系统补充','Inferred'),user:T('用户修改','User edit')})[r.origin]||r.origin)}<textarea data-oc-rule="${i}" rows="2">${E(r.text)}</textarea><small>${E(r.quote||T('系统补充或用户定义，未声称为原文','Inferred or user-defined; not claimed as source text'))}</small></label>`).join('');
    $('ocLibraryName').value=method.name; update();
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
    edit(p.candidate);
    state.reviewed=true;state.study=record;state.benchmark=p.benchmark;state.provider=fields.provider;state.baseline=fields.baseline;state.ids=fields.ids;
    $('ocMaterial').value=p.candidate.source?.text||'';$('ocTitle').value=p.candidate.source?.title||'';
    if(!Array.from($('ocProvider').options).some(o=>o.value===fields.provider))$('ocProvider').add(new Option(fields.provider,fields.provider));
    $('ocProvider').value=fields.provider;
    mount.querySelectorAll('[name=ocBaseline]').forEach(el=>el.checked=el.value===fields.baseline);
    $('ocMode').value=fields.mode;
    for(const [id,key] of [['ocRepeats','repeats'],['ocDelta','delta'],['ocSeed','seed'],['ocCalls','calls'],['ocTokens','tokens']])$(id).value=fields[key];
    Array.from($('ocMembers').options).forEach(o=>o.selected=fields.ids.includes(Number(o.value)));
    preview(p.benchmark);
    state.step=record.status==='draft'?3:4;update();
  }
  function renderStudy(r) {
    const a=r.analysis||{}, running=r.status==='running';
    const labels={draft:T('设置已保存','Settings saved'),running:T('运行中','Running'),paused:T('已暂停','Paused'),interrupted:T('运行中断，可继续','Interrupted; resumable'),completed:T('已完成','Completed'),stopped:T('已终止','Stopped')};
    $('ocProgress').textContent=`${labels[r.status]||r.status} · ${r.rows.length}/${r.protocol.expected} · ${r.metrics?.calls||0} ${T('次实际调用','requests')} ${r.error?' · '+r.error:''}`;
    $('ocBar').max=r.protocol.expected; $('ocBar').value=r.rows.length;
    $('ocPause').hidden=!running; $('ocStop').hidden=!['running','paused','interrupted'].includes(r.status); $('ocResume').hidden=!['paused','interrupted'].includes(r.status);
    const f=x=>typeof x==='number'?x.toFixed(4):'—';
    $('ocResult').innerHTML=`<p class="oc-verdict" data-verdict="${E(a.verdict||'incomplete')}">${E(C.verdict(a.verdict,en()))}</p>`
      +`<p>${E(T('主指标：0–1成绩，越高越好。差异为候选减去对照。','Primary score: 0–1, higher is better. Difference is candidate minus baseline.'))}</p>`
      +`<p class="oc-note">${E(T('模型','Model'))}: ${E(r.protocol.model.model)} · ${E(r.protocol.scope==='topology'?T('仅比较通信结构','Communication structure only'):T('比较整套组织方式','Whole-method comparison'))} · ${E(r.protocol.benchmark.name)}</p>`
      +`<div class="oc-score"><div><small>${E(T('候选平均成绩','Candidate mean'))}</small><strong>${f(a.arms?.candidate?.mean)}</strong></div><div><small>${E(T('对照平均成绩','Baseline mean'))}</small><strong>${f(a.arms?.baseline?.mean)}</strong></div><div><small>${E(T('配对差异','Paired difference'))}</small><strong>${f(a.difference)}</strong></div></div>`
      +`<div class="oc-table"><table><thead><tr>${[T('组织','Arm'),T('完成率','Completion'),T('调用次数','Calls'),T('耗时（秒）','Call seconds')].map(x=>'<th>'+E(x)+'</th>').join('')}</tr></thead><tbody>${['candidate','baseline'].map(arm=>{const v=a.arms?.[arm];return v?'<tr><td>'+E(arm==='candidate'?T('候选','Candidate'):T('对照','Baseline'))+'</td><td>'+f(v.completion_rate)+'</td><td>'+v.calls+'</td><td>'+f(v.elapsed)+'</td></tr>':'';}).join('')}</tbody></table></div>`
      +`<p class="oc-note">95% CI: ${a.interval?a.interval.map(f).join(' – '):'—'} · ${a.independent_tasks||0} ${E(T('道独立题；少于30题只作探索。','independent questions; fewer than 30 is exploratory.'))}</p>`
      + (a.categories?.length ? '<details><summary>'+E(T('探索性题型比较','Exploratory category comparisons'))+'</summary>'+a.categories.map(c=>'<p>'+E(c.category)+': '+f(c.candidate)+' / '+f(c.baseline)+' · '+E(T('差异','Difference'))+' '+f(c.difference)+'</p>').join('')+'</details>':'')
      +`<p class="oc-note">${E(T('结论仅适用于本次模型、成员、题库和运行限制。token与金额未知时不估造；成绩更高不自动意味着更省资源。','Results apply to this model, roster, benchmark and limits. Unknown tokens/costs are not estimated. Higher scores do not automatically imply lower resource use.'))}</p>`;
    $('ocRows').innerHTML='<table><thead><tr>'+['题目 / Question','重复 / Repeat','组 / Arm','成绩 / Score','错误 / Error'].map(s=>`<th>${E(s)}</th>`).join('')+'</tr></thead><tbody>'+r.rows.map(row=>`<tr><td>${E(row.task_id)}</td><td>${row.repeat+1}</td><td>${E(row.arm)}</td><td>${f(row.score)}</td><td>${E(row.error)}</td></tr>`).join('')+'</tbody></table>';
  }
  async function refresh() {
    if (!state.study) return;
    const id=state.study.id, revision=state.revision;
    const r=await api(P+'/'+id);
    if (state.revision!==revision || state.study?.id!==id) return;
    state.study=r; update();clearTimeout(timer);
    if(C.shouldPoll(r)) timer=setTimeout(()=>refresh().catch(e=>error(e.message)),2000);
  }
  async function history() {
    const list=(await api(P)).studies;
    $('ocHistory').innerHTML=list.map(r=>`<button type="button" class="oi-record" data-oc-study="${E(r.id)}">${E(r.title)}<small>${E(({draft:T('设置已保存','Settings saved'),running:T('运行中','Running'),paused:T('已暂停','Paused'),interrupted:T('运行中断','Interrupted'),completed:T('已完成','Completed'),stopped:T('已终止','Stopped')})[r.status]||r.status)}</small></button>`).join('')||`<p class="oc-note">${E(T('还没有实验','No experiments yet'))}</p>`;
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
  act('ocAdopt',()=>{const m=readMethod();if(state.method.roles.length!==m.roles.length)state.benchmark=null;invalidate();state.method=m;state.reviewed=true;state.step=1;update();});
  ['ocMethodName','ocRoles','ocTopology','ocRounds','ocDecision','ocReview','ocReviewEnabled','ocRules'].forEach(id=>$(id).addEventListener('input',()=>{if(state.method){state.reviewed=false;invalidate();}}));
  mount.querySelectorAll('[name=ocBaseline]').forEach(el=>el.onchange=()=>{state.baseline=el.value;invalidate();});
  $('ocMode').onchange=invalidate;
  function preview(bank) {state.benchmark=bank;const q=bank.tasks[0];$('ocBenchmarkPreview').innerHTML=`<h3>${E(bank.name)} · ${bank.tasks.length} ${E(T('道题','questions'))}</h3><p>${E(q.prompt)}</p><p class="oc-note">${E(T('验证通过；评分范围0–1。参考答案仅供评分端使用。','Validated; scores range from 0 to 1. References are available only to the scorer.'))}</p>`;update();}
  act('ocBuiltin',async()=>{const rev=state.revision;const r=await api(P+'/benchmark',{problem:$('ocProblem').value,count:Number($('ocCount').value),slots:state.method.roles.length});if(rev!==state.revision)return;invalidate();preview(r.benchmark);});
  act('ocImport',async()=>{const file=$('ocBenchmarkFile').files[0];if(!file)throw new Error(T('请选择题库文件','Choose a benchmark file'));if(file.size>2_000_000)throw new Error(T('题库不能超过2MB','Benchmark limit: 2MB'));const rev=state.revision;const text=await file.text();const r=await api(P+'/benchmark',{text,format:/\.csv$/i.test(file.name)?'csv':'jsonl',mapping:JSON.parse($('ocMapping').value),scorer:$('ocScorer').value,name:file.name});if(rev!==state.revision)return;invalidate();preview(r.benchmark);});
  ['ocRepeats','ocDelta','ocSeed','ocCalls','ocTokens','ocMembers'].forEach(id=>$(id).addEventListener('input',invalidate));
  act('ocSave',async()=>{state.ids=Array.from($('ocMembers').selectedOptions,x=>Number(x.value));if(state.ids.length!==state.method.roles.length)throw new Error(T('居民人数必须与角色数量相同','Resident count must match role count'));const rev=state.revision;const record=await api(P,C.settings(state,{repeats:Number($('ocRepeats').value),delta:Number($('ocDelta').value),seed:Number($('ocSeed').value),limits:{calls:Number($('ocCalls').value)},max_tokens:Number($('ocTokens').value),comparison_mode:$('ocMode').value}));if(rev!==state.revision)return;state.study=record;await history();});
  act('ocRun',async()=>{await api(P+'/'+state.study.id+'/run',{});state.step=4;await refresh();});
  for(const [id,action] of [['ocPause','pause'],['ocResume','resume'],['ocStop','stop']])act(id,async()=>{await api(P+'/'+state.study.id+'/'+action,{});await refresh();});
  act('ocRefresh',refresh);
  for(const [id,route,key,type] of [['ocReport','export','markdown','text/markdown'],['ocCsv','csv','csv','text/csv'],['ocSettings','protocol','protocol','application/json'],['ocAudit','audit','record','application/json']])act(id,async()=>{const r=await api(P+'/'+state.study.id+'/'+route);download(r.filename,typeof r[key]==='string'?r[key]:JSON.stringify(r[key],null,2),type);});
  act('ocSaveMethod',async()=>{const r=await api(P+'/'+state.study.id+'/save-method',{name:$('ocLibraryName').value});$('ocSavedMethod').textContent=T(`已保存「${r.name}」版本${r.version}。在合作任务中选择相同人数即可使用。`,`Saved “${r.name}”, version ${r.version}. Select it in Cooperation with the matching team size.`);});
  $('ocNew').onclick=()=>{clearTimeout(timer);state.revision++;state.study=null;state.step=0;error();update();};
  $('ocHistory').onclick=async event=>{const b=event.target.closest('[data-oc-study]');if(!b)return;try{clearTimeout(timer);state.revision++;const revision=state.revision;const record=await api(P+'/'+b.dataset.ocStudy);if(revision!==state.revision)return;loadStudy(record);if(C.shouldPoll(state.study))await refresh();}catch(e){error(e.message);}};
  document.addEventListener('locale-changed',()=>{mount.querySelectorAll('[data-oc-en]').forEach(el=>el.textContent=en()?el.dataset.ocEn:el.dataset.ocZh);update();});
  async function init() {try{context=await api(P+'/context');$('ocProvider').innerHTML=context.providers.map(p=>`<option value="${E(p.name)}">${E(p.name)} · ${E(p.model||'')}</option>`).join('');if(context.default_provider&&context.providers.some(p=>p.name===context.default_provider))$('ocProvider').value=context.default_provider;state.provider=$('ocProvider').value;$('ocMembers').innerHTML=context.members.map((p,i)=>`<option value="${p.id}" ${i<3?'selected':''}>${E(p.name)} · ${p.id}</option>`).join('');await history();update();}catch(e){error(e.message);}}
  update();init();
}());
