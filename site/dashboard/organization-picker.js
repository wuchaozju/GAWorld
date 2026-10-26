(function () {
  'use strict';
  const select = document.getElementById('organizationMethodSelect');
  const note = document.getElementById('organizationMethodNote');
  const refresh = document.getElementById('organizationMethodRefresh');
  if (!select || !note) return;
  let methods = [], generation = 0;
  const en = () => document.documentElement.lang.startsWith('en');
  const T = (zh, english) => en() ? english : zh;
  function selected() { return methods.find(m => m.id === select.value) || null; }
  function changed() {
    const m = selected();
    const evidence = m ? ({better:T('有优势证据','Evidence of improvement'),worse:T('本次表现较差','Lower scores in the study'),uncertain:T('尚无优势证据','No established advantage'),incomplete:T('尚未验证','Not validated')})[m.evidence?.verdict] || T('尚未验证','Not validated') : '';
    const leader = document.getElementById('leaderSelect');
    if (leader) leader.disabled=Boolean(m);
    document.querySelectorAll('#roleOverrides input').forEach(el=>el.disabled=Boolean(m));
    note.textContent=m ? T(`${m.method.roles.length}位成员 · 版本${m.version} · ${m.method.roles.join(' → ')}。验证状态：${evidence}。本任务超出原研究题库，作为未验证配置使用。`,
      `${m.method.roles.length} members · v${m.version} · ${m.method.roles.join(' → ')}. Evidence: ${evidence}. This task is outside the tested benchmark and is an unvalidated configuration.`)
      :T('使用现有的分工、执行、审阅和汇总流程。','Use the existing planning, execution, review and synthesis flow.');
  }
  async function load() {
    const current=++generation, previous=select.value;
    try {
      const response=await fetch('/api/collaboration/organization-methods',{credentials:'same-origin'});
      const result=await response.json();
      if(!response.ok||result.error)throw new Error(result.error||`HTTP ${response.status}`);
      if(current!==generation)return;
      methods=result.methods;
      select.replaceChildren(new Option(T('默认协作方式','Default cooperation'),''));
      methods.forEach(m=>select.add(new Option(`${m.name} · v${m.version} · ${m.method.roles.length} ${T('位','members')}`,m.id)));
      if(methods.some(m=>m.id===previous))select.value=previous;
      changed();
    } catch(e) {note.textContent=T('读取组织方式失败：','Could not load methods: ')+e.message;}
  }
  select.addEventListener('change',changed);
  if(refresh)refresh.addEventListener('click',load);
  document.addEventListener('locale-changed',load);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
  window.addEventListener('focus',load);
  window.OrganizationMethodPicker={selected,load};
  load();
}());
