
var gwURL = globalThis.GAWorldURL ? globalThis.GAWorldURL.url : function (value) { return value; };
/* OI-2 is an explicit zero-provider workflow; old OI-1 remains independently readable. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  if (!$('oi2Form')) return;
  const base = '/api/research/organization-intelligence/v2';
  const labels = {draft:'协议已冻结 · 尚未运行',running:'执行中',finalizing:'任务已提交 · 正在发布报告',paused:'已暂停 · 可继续',blocked:'待排除执行问题 · 证据已保留',completed:'全部任务已完成'};
  let runtime = null, current = null, timer = null, listTimer = null;
  async function request(path = '', body) {
    const response = await fetch(base + path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '请求失败');
    return data;
  }
  function error(exc) { $('oi2Error').textContent = exc.message; }
  function budget() {
    const n = Number($('oi2Seeds').value);
    $('oi2Budget').textContent = `${n} 个种子 · ${n*40} 道训练任务 + ${n*160} 道留出任务 · ${n*8} 个测试单元 · 外部模型请求 0`;
  }
  function table(analysis) {
    const target = $('oi2Results');
    target.replaceChildren();
    if (!analysis.complete) return;
    const table = document.createElement('table');
    const caption = document.createElement('caption');
    caption.textContent = '八条件平均净收益（扣除通信、核验与延迟成本）';
    table.appendChild(caption);
    const head = document.createElement('tr');
    for (const text of ['程序','组织记忆','成员','净收益']) { const cell = document.createElement('th'); cell.textContent = text; head.appendChild(cell); }
    table.appendChild(head);
    for (const row of analysis.cells) {
      const tr = document.createElement('tr');
      for (const text of [row.procedure?'证据核验':'等权提案',row.memory?'保留':'无',row.turnover?'全部新人':'原成员',Number(row.net_reward).toFixed(3)]) {
        const td = document.createElement('td'); td.textContent = text; tr.appendChild(td);
      }
      table.appendChild(tr);
    }
    target.appendChild(table);
    const primary = analysis.contrasts.find(r => r.id === 'primary_memory_after_turnover');
    if (primary) {
      const p = document.createElement('p');
      const ci = primary.ci95 ? `；95% 种子配对区间 [${primary.ci95.map(x=>Number(x).toFixed(3)).join(', ')}]` : '；单种子不估计区间';
      p.textContent = `主比较：全员更替后，证据程序保留组织记忆的净收益差 ${Number(primary.mean).toFixed(3)}${ci}。这是模型假设下的机制结果。`;
      target.appendChild(p);
    }
  }
  async function show(id) {
    clearTimeout(timer);
    const selected = id;
    const record = await request('/' + encodeURIComponent(id));
    if (current && current.id !== selected) return;
    current = record;
    $('oi2Study').hidden = false;
    $('oi2Status').textContent = labels[record.status] || record.status;
    $('oi2Identity').textContent = `${record.id} · ${record.protocol.version} · ${record.protocol.seeds.length} 个种子 · 冻结构建 ${record.build_id}`;
    $('oi2Progress').value = record.committed / record.total;
    $('oi2Metrics').textContent = `已提交任务 ${record.committed} / ${record.total} · 待执行 ${record.counts.pending||0} · 执行中 ${record.counts.leased||0}\n外部模型请求 0 · worker PID ${record.worker_pid || '尚未启动'} · 实际构建 ${record.worker_build || '待核对'}`;
    $('oi2Notice').textContent = record.error || (record.status === 'completed' ? '训练与测试全部完成。报告按种子计算配对差，未将任务数当作独立样本。' : '每个任务的动作、得分和组织状态原子提交；暂停或进程中断后可继续同一研究。数据未完整时不作处理效应结论。');
    $('oi2Run').hidden = ['running','finalizing','completed'].includes(record.status);
    $('oi2Run').textContent = record.status === 'draft' ? '启动冻结研究' : '继续同一研究';
    $('oi2Pause').hidden = record.status !== 'running';
    $('oi2Protocol').textContent = JSON.stringify(record.protocol,null,2);
    table({complete:false});
    if (record.status === 'completed') {
      const results = await request('/'+id+'/results');
      if (current.id === id) table(results.analysis);
    }
    if (['running','finalizing'].includes(record.status) && current.id === id) timer = setTimeout(()=>show(id).catch(error),1200);
  }
  async function refresh() {
    const context = await request();
    runtime = context.engine;
    $('oi2Runtime').textContent = `服务 ${location.origin} · PID ${runtime.pid} · 引擎 ${runtime.version} · 执行构建 ${runtime.build_id}${runtime.workspace_matches ? ' · 工作区一致' : ' · 工作区已变化，需重启服务后创建研究'}`;
    $('oi2Create').disabled = !runtime.workspace_matches || runtime.version !== 'OI-2.0';
    $('oi2Studies').replaceChildren();
    for (const record of context.studies) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'oi-record';
      button.textContent = `${record.id}\n${labels[record.status] || record.status} · ${record.committed}/${record.total}`;
      button.addEventListener('click',()=>{current={id:record.id}; show(record.id).catch(error);});
      $('oi2Studies').appendChild(button);
    }
    clearTimeout(listTimer);
    if (context.studies.some(r=>['running','finalizing'].includes(r.status))) listTimer=setTimeout(()=>refresh().catch(error),2500);
  }
  function download(name, text, type) {
    const url = URL.createObjectURL(new Blob([text],{type}));
    const anchor = document.createElement('a'); anchor.href=gwURL(url); anchor.download=name; anchor.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  $('oi2Seeds').addEventListener('input',budget);
  $('oi2Form').addEventListener('submit',async event=>{
    event.preventDefault(); $('oi2Error').textContent=''; $('oi2Create').disabled=true;
    try {
      const record = await request('',{seeds:Number($('oi2Seeds').value),seed:Number($('oi2Seed').value),expected_build:runtime?.build_id});
      current={id:record.id};
      history.replaceState(null,'',gwURL(`?tab=organization-intelligence&oi2=${record.id}`));
      await show(record.id); await refresh();
    } catch(exc) { error(exc); }
    finally { $('oi2Create').disabled = !runtime?.workspace_matches || runtime.version !== 'OI-2.0'; }
  });
  $('oi2Run').addEventListener('click',async()=>{
    if (!current) return;
    $('oi2Run').disabled=true;
    try { await request('/'+current.id+'/run',{expected_build:current.build_id}); await show(current.id); await refresh(); }
    catch(exc) { error(exc); } finally { $('oi2Run').disabled=false; }
  });
  $('oi2Pause').addEventListener('click',async()=>{
    try { await request('/'+current.id+'/pause',{}); await show(current.id); await refresh(); } catch(exc) { error(exc); }
  });
  for (const [button, suffix, key, type] of [['oi2Export','export','markdown','text/markdown'],['oi2ProtocolDownload','protocol','protocol','application/json'],['oi2ResultsDownload','results',null,'application/json']]) {
    $(button).addEventListener('click',async()=>{
      try {
        const result = await request('/'+current.id+'/'+suffix);
        const value = key === 'markdown' ? result.markdown : JSON.stringify(result,null,2);
        download(result.filename || current.id+'-results.json',value,type);
      } catch(exc) { error(exc); }
    });
  }
  if (new URLSearchParams(location.search).has('oi')) $('oiLegacy').open=true;
  refresh().then(async()=>{
    const id = new URLSearchParams(location.search).get('oi2');
    if (id) { current={id}; await show(id); }
  }).catch(exc=>{error(exc); $('oi2Runtime').textContent='无法核对 OI-2 引擎，请确认服务已更新并刷新。';});
})();
