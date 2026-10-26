/* OI-2 is an explicit zero-provider workflow; old OI-1 remains independently readable. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  if (!$('oi2Form')) return;
  const base = '/api/research/organization-intelligence/v2';
  const labels = {draft:'设置已保存，尚未开始',running:'正在做题',finalizing:'题目已做完，正在整理报告',paused:'已暂停，可以继续',blocked:'暂时无法继续，已完成内容已保存',completed:'实验已完成'};
  let runtime = null, current = null, timer = null, listTimer = null;
  async function request(path = '', body) {
    const response = await fetch(base + path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '请求失败');
    return data;
  }
  function error(exc) {
    const raw = exc.message || String(exc);
    let message = '操作没有完成，现有实验记录已保留。请展开下方说明查看原因。';
    if (/构建|握手|工作区|引擎版本/.test(raw)) message = '实验服务已更新，请重新读取这次实验；如果仍无法操作，请重启服务并刷新页面。';
    else if (/冻结失败|seed|seeds/.test(raw)) message = '实验设置没有保存成功。请检查组数和题目编号后重试。';
    else if (/找不到研究/.test(raw)) message = '没有找到这次实验，请从右侧重新选择一条记录。';
    else if (/fetch|network|连接/i.test(raw)) message = '暂时无法连接到实验服务，请确认服务正在运行，再刷新页面。';
    $('oi2Error').textContent = message;
    $('oi2ErrorDiagnostic').textContent = raw;
    $('oi2ErrorDetails').hidden = false;
  }
  function budget() {
    const n = Number($('oi2Seeds').value);
    $('oi2Budget').textContent = `将做 ${n} 组，共 ${n*200} 题：${n*40} 题练习，${n*160} 题正式比较。不调用大模型。`;
  }
  function table(analysis) {
    const target = $('oi2Results');
    target.replaceChildren();
    if (!analysis.complete) return;
    const table = document.createElement('table');
    const caption = document.createElement('caption');
    caption.textContent = '八种情况的平均成绩（已扣除沟通、查证和等待的成本，分数越高越好）';
    table.appendChild(caption);
    const head = document.createElement('tr');
    for (const text of ['做事方式','团队记录','成员','平均成绩']) { const cell = document.createElement('th'); cell.textContent = text; head.appendChild(cell); }
    table.appendChild(head);
    for (const row of analysis.cells) {
      const tr = document.createElement('tr');
      for (const text of [row.procedure?'汇集信息并查证':'各自判断后投票',row.memory?'保留':'不保留',row.turnover?'全部换新':'保持原成员',Number(row.net_reward).toFixed(3)]) {
        const td = document.createElement('td'); td.textContent = text; tr.appendChild(td);
      }
      table.appendChild(tr);
    }
    target.appendChild(table);
    const primary = analysis.contrasts.find(r => r.id === 'primary_memory_after_turnover');
    if (primary) {
      const p = document.createElement('p');
      const mean = Number(primary.mean);
      const difference = mean === 0 ? '没有差别' : `${mean > 0 ? '高' : '低'} ${Math.abs(mean).toFixed(3)} 分`;
      const comparison = mean === 0 ? '保留团队记录和不保留的团队，平均成绩没有差别' : `保留团队记录的平均成绩比不保留的团队${difference}`;
      p.textContent = `最想知道的结果：在采用「汇集信息并查证」且成员全部换新的团队中，${comparison}。这是本次程序实验的比较，不能直接代表现实团队。`;
      target.appendChild(p);
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = '这个差别有多确定？';
      details.appendChild(summary);
      const explanation = document.createElement('p');
      if (primary.ci95) {
        const [low, high] = primary.ci95;
        explanation.textContent = `根据 ${primary.n_seeds || current.protocol.seeds.length} 组重复实验，差值的统计估计范围是 [${Number(low).toFixed(3)}, ${Number(high).toFixed(3)}]（95%置信区间）。${low <= 0 && high >= 0 ? '这个范围跨过 0，暂时不能确定保留团队记录是否有帮助。' : low > 0 ? '这个范围都高于 0，本轮结果支持保留记录有帮助；仍需更多实验检查。' : '这个范围都低于 0，本轮结果显示保留记录反而降低了成绩。'}每组只算一次重复，不把每道题都当成独立团队。`;
      } else explanation.textContent = '这次只做了一组，暂时无法估计结果有多稳定。可以用更多组重复实验检查。';
      details.appendChild(explanation);
      target.appendChild(details);
    }
  }
  async function show(id) {
    clearTimeout(timer);
    const selected = id;
    const record = await request('/' + encodeURIComponent(id));
    if (current && current.id !== selected) return;
    current = record;
    $('oi2Study').hidden = false;
    $('oi2StudyTitle').textContent = record.status === 'completed' ? '3 · 查看结果' : '2 · 运行实验';
    $('oi2Status').textContent = labels[record.status] || record.status;
    $('oi2Identity').textContent = `重复 ${record.protocol.seeds.length} 组，每组比较八种情况。`;
    $('oi2Progress').value = record.committed / record.total;
    $('oi2Metrics').textContent = `已完成 ${record.committed} / ${record.total} 题，剩余 ${Math.max(0,record.total-record.committed)} 题。\n这次实验不调用大模型。`;
    const notices = {
      draft:'设置已保存，实验还没开始。确认后点击「开始实验」；保存设置不会自动运行。',
      running:'正在按保存的设置做题。可以随时暂停，稍后接着做；所有题做完后再给出比较结果。',
      paused:'进度已保存。点击「继续实验」可以接着做，已完成的题不会重做。',
      blocked:'运行遇到了问题，已完成的内容已保存。排除问题后可以继续，具体原因见下方运行信息。',
      finalizing:'所有题都已做完，正在整理结果和报告，请稍候。',
      completed:'练习和正式比较都已完成。下表比较八种情况的平均成绩，分数越高越好。'
    };
    $('oi2Notice').textContent = notices[record.status] || '进度已保存。';
    $('oi2Run').hidden = ['running','finalizing','completed'].includes(record.status);
    $('oi2Run').textContent = record.status === 'draft' ? '开始实验' : '继续实验';
    $('oi2Pause').hidden = record.status !== 'running';
    $('oi2Protocol').textContent = JSON.stringify(record.protocol,null,2);
    $('oi2Technical').textContent = `研究编号：${record.id}\n版本：${record.protocol.version}\n保存的构建：${record.build_id}\n实际运行构建：${record.worker_build || '尚未运行'}\n运行进程：${record.worker_pid || '尚未启动'}${record.error ? '\n原始错误：'+record.error : ''}`;
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
    const compatible = runtime.workspace_matches && runtime.version === 'OI-2.0';
    $('oi2Ready').textContent = compatible ? '检查通过，可以保存实验设置。保存后再点击「开始实验」。' : '暂时不能新建实验：服务版本需要更新，请重启服务并刷新页面。';
    $('oi2Runtime').textContent = `服务 ${location.origin} · PID ${runtime.pid} · 引擎 ${runtime.version} · 执行构建 ${runtime.build_id}${runtime.workspace_matches ? ' · 工作区一致' : ' · 工作区已变化，需重启服务后创建研究'}`;
    $('oi2Create').disabled = !compatible;
    $('oi2Studies').replaceChildren();
    for (const record of context.studies) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'oi-record';
      const date = record.created_at ? new Date(record.created_at*1000).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '实验记录';
      button.textContent = `${date} · ${labels[record.status] || record.status}\n已完成 ${record.committed} / ${record.total} 题`;
      button.addEventListener('click',()=>{current={id:record.id}; show(record.id).catch(error);});
      $('oi2Studies').appendChild(button);
    }
    clearTimeout(listTimer);
    if (context.studies.some(r=>['running','finalizing'].includes(r.status))) listTimer=setTimeout(()=>refresh().catch(error),2500);
  }
  function download(name, text, type) {
    const url = URL.createObjectURL(new Blob([text],{type}));
    const anchor = document.createElement('a'); anchor.href=url; anchor.download=name; anchor.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  $('oi2Seeds').addEventListener('input',budget);
  $('oi2Form').addEventListener('submit',async event=>{
    event.preventDefault(); $('oi2Error').textContent=''; $('oi2ErrorDetails').hidden=true; $('oi2Create').disabled=true;
    try {
      const record = await request('',{seeds:Number($('oi2Seeds').value),seed:Number($('oi2Seed').value),expected_build:runtime?.build_id});
      current={id:record.id};
      history.replaceState(null,'',`?tab=organization-intelligence&oi2=${record.id}`);
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
  budget();
  refresh().then(async()=>{
    const id = new URLSearchParams(location.search).get('oi2');
    if (id) { current={id}; await show(id); }
  }).catch(exc=>{error(exc); $('oi2Ready').textContent='暂时无法检查实验服务，请确认服务正在运行，再刷新页面。';});
})();
