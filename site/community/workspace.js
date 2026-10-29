
var gwHTML = globalThis.GAWorldURL ? globalThis.GAWorldURL.html : function (value) { return value; };
var gwURL = globalThis.GAWorldURL ? globalThis.GAWorldURL.url : function (value) { return value; };
(function () {
  "use strict";
  var C = window.Community, e = C.esc, app = document.getElementById("app"), params = new URLSearchParams(location.search), state;
  var view = params.get("view") || "overview", previewDraft = null, selectedSource = null, selectedFiles = [];
  function title(label, description) { return '<p class="eyebrow">MY WORKSPACE / ' + e(label) + '</p><h1>' + e(label) + '</h1><p class="muted">' + e(description || "") + '</p>'; }
  function row(name, meta, actions) { return '<article class="list-row"><div><h3>' + e(name) + '</h3><span class="hint">' + e(meta || "") + '</span></div><div class="actions">' + actions + '</div></article>'; }
  function button(action, id, label, extra) { return '<button class="button compact secondary" data-action="' + e(action) + '" data-id="' + e(id) + '" ' + (extra || "") + '>' + e(label) + '</button>'; }
  function sourceLink(kind, id, label, world) { return '<a class="button compact secondary" href="/workspace?view=publish&kind=' + encodeURIComponent(kind) + '&id=' + encodeURIComponent(id) + '&world=' + encodeURIComponent(world || "") + '">' + e(label) + '</a>'; }
  function studyRows() { return state.studies.map(function (r) { return row(r.title, (r.stage || "研究") + ' · ' + C.date(r.created_at), button("open-study", r.id, "打开研究", 'data-world="' + e(r.world_id || "") + '"') + sourceLink("study", r.id, "发布成果", r.world_id)); }).join(""); }
  function planRows() { return state.plans.map(function (r) { return row(r.title, '研究方案 · ' + C.date(r.created_at), button("open-plan", r.id, "打开方案", 'data-world="' + e(r.world_id || "") + '"') + sourceLink("plan", r.id, "分享方案", r.world_id)); }).join(""); }
  async function selectWorld(id, target) {
    if (id !== C.world) {
      await C.api("POST", "/api/worlds/select", { id: id });
      C.navigate(target || location.pathname + location.search, true);
      return false;
    }
    return true;
  }
  function overview() {
    var user = state.user;
    app.innerHTML = gwHTML(title((user.display_name || user.nickname) + '的工作空间', '提出问题，构建世界，在自己的节奏里开展研究。') + (!user.email_verified ? '<div class="alert">邮箱尚未验证，验证后即可发布、讨论和提交研究任务。<a href="/workspace?view=account">重新发送验证邮件 ↗</a></div>' : '') + '<div class="toolbar"><a class="button" href="/console#research">新建研究 +</a><a class="button secondary" href="/workspace?view=worlds">创建仿真世界</a><a class="button secondary" href="/explore">发现公开研究 ↗</a></div><div class="stats"><div class="stat"><strong>' + state.plans.length + '</strong><span>研究方案</span></div><div class="stat"><strong>' + state.studies.length + '</strong><span>研究记录</span></div><div class="stat"><strong>' + state.worlds.length + '</strong><span>私人世界</span></div><div class="stat"><strong>' + state.usage.today + '</strong><span>今日模型调用' + (state.usage.daily_limit ? ' / ' + state.usage.daily_limit : '') + '</span></div></div><div class="section-head"><h2>最近的研究</h2><a href="/workspace?view=research" class="hint">全部研究 ↗</a></div>' + (studyRows() || planRows() || C.empty("从第一个研究问题开始", "创建方案，或从社区复制获准复用的研究。")) + '<div class="section-head"><h2>工作台入口</h2></div><div class="grid"><a class="card" href="/console#research"><p class="eyebrow">RESEARCH</p><h3>研究工作台 ↗</h3><p class="muted">从问题、论文到方案、实验和报告。</p></a><a class="card" href="/workspace?view=worlds"><p class="eyebrow">SIMULATION</p><h3>仿真工作台 ↗</h3><p class="muted">管理自己的世界、居民、运行和回放。</p></a></div>');
  }
  function research() { app.innerHTML = gwHTML(title('我的研究', '此处汇总本人不同世界的研究，打开时会切换到对应世界。') + (params.get("copied") ? '<div class="alert">已复制为私人方案。请选择本人的模型、城市和居民，检查配置后再编译和启动。</div>' : '') + '<div class="toolbar"><a class="button" href="/console#research">新建研究 +</a></div><div class="section-head"><h2>研究记录</h2></div>' + (studyRows() || C.empty('暂无研究记录')) + '<div class="section-head"><h2>研究方案</h2></div>' + (planRows() || C.empty('暂无研究方案'))); }
  async function worlds() {
    var cities = await C.api('GET', '/api/city/catalogue');
    var list = cities.cities || [];
    app.innerHTML = gwHTML(title('我的仿真世界', '每个世界拥有独立居民副本、配置和运行产物。') + (state.worlds.map(function (w) { return row(w.name, (w.city || '默认城市') + ' · ' + (w.visibility === 'private' ? '私有' : '已共享') + (C.world === w.id ? ' · 当前世界' : ''), button('world-run', w.id, '进入仿真工作台') + sourceLink('simulation', w.id, '分享案例', w.id)); }).join('') || C.empty('还没有仿真世界', '选择一个现有城市模板，为自己创建独立世界。')) + '<section class="thread"><h2>创建世界</h2><form id="worldForm" class="form"><label for="worldName">世界名称</label><input id="worldName" name="name" maxlength="64" required placeholder="例如：社区治理实验室"><label for="worldCity">城市模板</label><select name="city" id="worldCity"><option value="">默认城市</option>' + list.map(function (c) { return '<option value="' + e(c.slug || c.id || c.name) + '">' + e(c.name || c.slug) + '</option>'; }).join('') + '</select><p class="hint">复制居民与配置；此操作不会启动仿真。</p><button class="button">创建私人世界</button></form></section>');
    document.getElementById('worldForm').onsubmit = async function (event) { event.preventDefault(); var btn = this.querySelector('button'); btn.disabled = true; try { await C.api('POST', '/api/worlds/create', Object.fromEntries(new FormData(this))); C.reload(); } catch (err) { C.error(err); btn.disabled = false; } };
  }
  function publications() {
    var published = state.publications.publications, drafts = state.publications.drafts;
    app.innerHTML = gwHTML(title('我的发布', '公开内容保留版本。继续修改私人研究，不会覆盖已发布的成果。') + '<div class="toolbar"><a class="button" href="/workspace?view=publish">发布研究成果 +</a></div><div class="section-head"><h2>已发布与撤回</h2></div>' + (published.map(function (p) { return row(p.title, 'v' + p.current_version + ' · ' + ({ published: '公开', withdrawn: '已撤回', hidden: '已下架' }[p.status] || p.status), (p.status === 'published' ? '<a href="/publications/' + e(p.id) + '">查看 ↗</a>' : '') + '<a class="button compact secondary" href="/workspace?view=publish&publication=' + e(p.id) + '">发布新版本</a>' + (p.status === 'published' ? button('withdraw', p.id, '撤回') : '')); }).join('') || C.empty('尚未发布成果')) + '<div class="section-head"><h2>发布草稿</h2></div>' + (drafts.map(function (d) { return row(d.content.title, '尚未公开 · ' + C.date(d.created_at), '<a class="button compact secondary" href="/workspace?view=publish&draft=' + e(d.id) + '">继续编辑与预览</a>' + button('delete-draft', d.id, '删除草稿')); }).join('') || '<p class="muted">暂无未发布的草稿。</p>'));
  }
  async function publishForm() {
    var initial = {}, publication = params.get('publication'), did = params.get('draft');
    if (publication) {
      var own = state.publications.publications.find(function (p) { return p.id === publication; });
      if (!own) throw new Error('成果不属于你');
      var saved = await C.api('POST', '/api/community/revision-source', { id: publication });
      initial = saved.content; selectedSource = initial.source && initial.source.id ? initial.source : null;
      selectedFiles = (initial.attachments || []).map(function (f) { return { name: f.name, text: f.text, mime: f.mime }; });
    } else if (did) {
      var d = state.publications.drafts.find(function (r) { return r.id === did; });
      if (!d) throw new Error('发布草稿不存在'); initial = d.content; publication = d.publication_id;
      selectedSource = initial.source && initial.source.id ? initial.source : null;
      selectedFiles = (initial.attachments || []).map(function (f) { return { name: f.name, text: f.text, mime: f.mime }; });
    }
    var sources = state.plans.map(function (r) { return { kind: 'plan', id: r.id, name: '方案 · ' + r.title, world: r.world_id || '' }; }).concat(state.studies.map(function (r) { return { kind: 'study', id: r.id, name: '研究 · ' + r.title, world: r.world_id || '' }; }), state.worlds.map(function (w) { return { kind: 'simulation', id: w.id, name: '仿真 · ' + w.name, world: w.id }; }));
    app.innerHTML = gwHTML(title('发布研究成果', '先预览，再决定公开。发布不会开放你的私人工作台。') + '<form id="publishForm" class="form"><label for="sourceSelect">选择来源</label><select id="sourceSelect"><option value="">手动撰写研究方案</option>' + sources.map(function (s, i) { return '<option value="' + i + '">' + e(s.name) + '</option>'; }).join('') + '</select><p class="hint" id="sourceHint">无运行来源的内容标为研究方案。</p><label for="pubTitle">标题</label><input id="pubTitle" name="title" maxlength="160" required><label for="pubSummary">摘要</label><textarea id="pubSummary" name="summary" maxlength="1000" style="min-height:90px"></textarea><label for="pubBody">公开正文</label><textarea id="pubBody" name="body" maxlength="100000" required style="min-height:280px"></textarea><label for="pubMethods">研究方法</label><textarea id="pubMethods" name="methods" maxlength="20000"></textarea><label for="pubLimits">局限与证据边界</label><textarea id="pubLimits" name="limitations" maxlength="10000"></textarea><label for="pubReferences">来源与引用</label><textarea id="pubReferences" name="references" maxlength="10000" style="min-height:90px"></textarea><div class="row"><div><label for="pubTags">标签（用逗号分隔）</label><input id="pubTags" name="tags" maxlength="360"></div><div><label for="pubLicense">复用许可</label><select id="pubLicense" name="license"><option value="read_only">仅供阅读</option><option value="CC-BY-4.0">CC BY 4.0 · 署名复用</option><option value="CC0-1.0">CC0 · 开放复用</option></select></div></div><label class="checks"><input id="includeTemplate" type="checkbox"><span>同时公开可复用方案（包含下方全部方案内容）</span></label><details id="templateDetails"><summary>检查将要共享的方案内容</summary><pre id="templateContent" class="article-body small"></pre></details><label for="pubFiles">选择公开附件（可选）</label><input id="pubFiles" type="file" multiple accept=".md,.txt,.csv,.json"><p id="fileHint" class="hint">仅上传有权分享的文本附件。私人原始记录不会自动附带。</p><label class="checks"><input id="rightsCheck" type="checkbox" required><span>我已检查公开内容和附件，有权分享这些材料，并已说明结果的适用范围与局限。</span></label><div class="actions"><button class="button" type="submit">保存草稿并预览 →</button></div></form><section id="publishPreview" hidden></section>');
    var form = document.getElementById('publishForm');
    document.getElementById('includeTemplate').checked = initial.include_template === true;
    function showTemplate() { document.getElementById('templateContent').textContent = selectedSource && selectedSource.template ? JSON.stringify(selectedSource.template, null, 2) : '尚未选择可复用的研究方案。'; }
    showTemplate();
    ['title','summary','body','methods','limitations','references','license'].forEach(function (k) { if (initial[k] != null) form.elements[k].value = initial[k]; });
    form.elements.tags.value = (initial.tags || []).join(', ');
    function invalidate() { previewDraft = null; document.getElementById('publishPreview').hidden = true; }
    form.addEventListener('input', invalidate);
    async function choose(source) {
      invalidate();
      if (source.world !== C.world) {
        var resume = new URLSearchParams(params);
        resume.set('view', 'publish'); resume.set('kind', source.kind); resume.set('id', source.id);
        // Keep edits and files while reloading every world-bound panel.
        var edits = Object.fromEntries(new FormData(form)); delete edits.files;
        var carry = {identity:{publication:params.get('publication') || '',draft:did || '',kind:source.kind,id:source.id}, edits:edits, files:selectedFiles, include:document.getElementById('includeTemplate').checked, rights:document.getElementById('rightsCheck').checked};
        sessionStorage.setItem('gaworld-publish-resume-' + C.user.id, JSON.stringify(carry));
        if (!await selectWorld(source.world, '/workspace?' + resume)) return;
      }
      selectedSource = await C.api('POST', '/api/community/source', { kind: source.kind, id: source.id }); showTemplate();
      form.elements.title.value = selectedSource.title; form.elements.body.value = selectedSource.body;
      document.getElementById('sourceHint').textContent = '已绑定来源版本 · ' + (C.status[selectedSource.result_status] || '方案') + '。你可以编辑将要公开的正文。';
      return true;
    }
    document.getElementById('sourceSelect').onchange = async function () { try { if (this.value === '') { selectedSource = null; showTemplate(); invalidate(); } else await choose(sources[Number(this.value)]); } catch (err) { C.error(err); } };
    if (params.get('kind') && params.get('id')) { var index = sources.findIndex(function (s) { return s.kind === params.get('kind') && s.id === params.get('id'); }); if (index >= 0) { document.getElementById('sourceSelect').value = index; if (!await choose(sources[index])) return; } }
    if (selectedSource) {
      var match = sources.findIndex(function (s) { return s.id === selectedSource.id && s.kind === selectedSource.kind; });
      if (match >= 0) { document.getElementById('sourceSelect').value = match; if (!await selectWorld(sources[match].world)) return; }
      document.getElementById('sourceHint').textContent = '来源绑定到已保存的版本；来源修改后须重新选择并预览。';
    }
    var resumeKey = 'gaworld-publish-resume-' + C.user.id;
    var carried = sessionStorage.getItem(resumeKey);
    if (carried) {
      var savedEdits = JSON.parse(carried);
      var matches = Object.keys(savedEdits.identity || {}).every(function (key) { return savedEdits.identity[key] === (params.get(key) || ''); });
      if (matches) {
      Object.keys(savedEdits.edits).forEach(function (key) {
        if (!['title', 'body', 'files'].includes(key) && form.elements[key]) form.elements[key].value = savedEdits.edits[key];
      });
      selectedFiles = savedEdits.files || [];
      document.getElementById('includeTemplate').checked = savedEdits.include;
      document.getElementById('rightsCheck').checked = savedEdits.rights;
      }
      sessionStorage.removeItem(resumeKey);
    }
    document.getElementById('fileHint').textContent = selectedFiles.length ? '已保留附件：' + selectedFiles.map(function (f) { return f.name; }).join('、') + '。重新选择文件将替换此列表。' : '未选择公开附件。';
    document.getElementById('pubFiles').onchange = async function () {
      try { selectedFiles = []; for (var file of this.files) { if (file.size > 300000) throw new Error('每个文本附件最多 300 KB'); var ext = file.name.split('.').pop(); selectedFiles.push({ name: file.name, text: await file.text(), mime: { md:'text/markdown', txt:'text/plain', csv:'text/csv', json:'application/json' }[ext] || 'text/plain' }); } document.getElementById('fileHint').textContent = '拟公开附件：' + selectedFiles.map(function (f) { return f.name; }).join('、'); invalidate(); } catch (err) { selectedFiles = []; this.value = ''; C.error(err); }
    };
    form.onsubmit = async function (event) {
      event.preventDefault(); var btn = this.querySelector('button'); btn.disabled = true;
      try {
        var body = Object.fromEntries(new FormData(this)); body.include_template = document.getElementById('includeTemplate').checked; body.tags = body.tags.split(/[,，]/).map(function (s) { return s.trim(); }).filter(Boolean); body.attachments = selectedFiles; if (publication) body.publication_id = publication;
        if (selectedSource) body.source = { kind: selectedSource.kind, id: selectedSource.id, revision: selectedSource.revision };
        previewDraft = await C.api('POST', '/api/community/drafts', body);
        var preview = document.getElementById('publishPreview'); preview.hidden = false;
        preview.innerHTML = gwHTML('<div class="preview"><p class="eyebrow">PUBLIC PREVIEW / 尚未公开</p><h2>' + e(previewDraft.title) + '</h2><span class="status">' + e(C.status[previewDraft.result_status]) + '</span><p>' + e(previewDraft.summary) + '</p><div class="article-body small">' + e(previewDraft.body) + '</div><h3>研究方法</h3><p class="article-body small">' + e(previewDraft.methods) + '</p><h3>局限与证据边界</h3><p class="article-body small">' + e(previewDraft.limitations) + '</p><h3>来源与引用</h3><p class="article-body small">' + e(previewDraft.references) + '</p>' + (previewDraft.include_template ? '<h3>同时公开的可复用方案（完整内容）</h3><pre class="article-body small">' + e(JSON.stringify((previewDraft.source || {}).template || {}, null, 2)) + '</pre>' : '') + '<p class="hint">许可：' + e(previewDraft.license) + ' · 拟公开附件：' + e(selectedFiles.map(function (f) { return f.name; }).join('、') || '无') + '</p><p class="hint">系统不会自动附带私人日志或居民原始文件；请检查正文和附件中是否含有私密信息。</p><button class="button" id="confirmPublish">确认公开发布</button></div>');
        document.getElementById('confirmPublish').onclick = async function () { this.disabled = true; try { var result = await C.api('POST', '/api/community/publish', { draft_id: previewDraft.id, revision: previewDraft.revision }); C.navigate('/publications/' + result.id + '?version=' + result.version); } catch (err) { C.error(err); this.disabled = false; } };
        preview.scrollIntoView({ behavior: 'smooth', block: 'start' });
      } catch (err) { C.error(err); } finally { btn.disabled = false; }
    };
  }
  async function bookmarks() { var r = await C.api('GET', '/api/community/bookmarks'); app.innerHTML = gwHTML(title('我的收藏') + (r.bookmarks.map(function (b) { var url = '/' + (b.target_type === 'publication' ? 'publications' : 'posts') + '/' + b.target_id; return row(b.target.title, '收藏于 ' + C.date(b.created_at), '<a href="' + e(url) + '">打开 ↗</a>' + button('unbookmark', b.target_id, '取消收藏', 'data-kind="' + e(b.target_type) + '"')); }).join('') || C.empty('还没有收藏', '到发现研究或公共广场看看。'))); }
  async function notifications() { var r = await C.api('GET', '/api/community/notifications'); app.innerHTML = gwHTML(title('消息', '回复、成果更新与社区动态。') + '<button class="link-button" data-action="seen">全部标为已读</button>' + (r.notifications.map(function (n) { return row(n.message, C.date(n.created_at) + (n.seen ? ' · 已读' : ' · 未读'), '<a href="/' + (n.target_type === 'publication' ? 'publications' : 'posts') + '/' + e(n.target_id) + '">查看 ↗</a>'); }).join('') || C.empty('暂时没有新消息'))); }
  function account() {
    var u = state.user;
    app.innerHTML = gwHTML(title('账号设置', '公开资料与私人账号设置分开管理。') + '<form id="profileForm" class="form"><label for="displayName">公开显示名</label><input name="display_name" id="displayName" maxlength="32" required value="' + e(u.display_name || u.nickname) + '"><p class="hint">登录用户名：' + e(u.nickname) + '（保持不变）</p><label for="bio">简介</label><textarea name="bio" id="bio" maxlength="2000">' + e(u.bio || '') + '</textarea><label for="interests">研究兴趣</label><input name="interests" id="interests" maxlength="500" value="' + e(u.interests || '') + '"><label for="avatar">头像 HTTPS 地址</label><input name="avatar" id="avatar" value="' + e(u.avatar || '') + '"><div class="actions"><button class="button">保存公开资料</button>' + (u.public_id ? '<a class="button secondary" href="/people/' + e(u.public_id) + '">查看个人主页 ↗</a>' : '') + '</div></form><section class="thread"><h2>登录与验证</h2><p>邮箱：' + e(u.email || '邀请码账号未绑定邮箱') + ' · ' + (u.email_verified ? '已验证' : '待验证') + '</p>' + (!u.email_verified ? '<button class="button secondary" data-action="resend">重新发送验证邮件</button>' : '') + '<form id="passwordForm" class="form"><label for="oldPassword">当前密码</label><input id="oldPassword" name="old" type="password" autocomplete="current-password" required><label for="newPassword">新密码</label><input id="newPassword" name="new" type="password" minlength="8" autocomplete="new-password" required><div class="actions"><button class="button secondary">修改密码</button></div></form><div class="toolbar"><button class="button secondary" data-action="close-sessions">退出其他设备</button><button class="button secondary" data-action="logout">退出当前账号</button><a href="/console#settings">模型与用量设置 ↗</a></div></section>');
    document.getElementById('profileForm').onsubmit = async function (event) { event.preventDefault(); try { await C.api('POST','/api/auth/profile',Object.fromEntries(new FormData(this))); C.toast('公开资料已更新'); } catch (err) { C.error(err); } };
    document.getElementById('passwordForm').onsubmit = async function (event) { event.preventDefault(); try { await C.api('POST','/api/auth/password',Object.fromEntries(new FormData(this))); C.toast('密码已修改，其他会话已退出'); this.reset(); } catch (err) { C.error(err); } };
  }
  async function moderation() {
    if (state.user.role !== 'admin' && !state.user.moderator) throw new Error('需要社区管理权限');
    var r = await C.api('GET','/api/community/reports');
    app.innerHTML = gwHTML(title('社区管理', '查看举报并记录处理理由。版主权限不包含私人研究访问。') + (r.reports.map(function (p) { return row(p.reason, p.target_type + ' · ' + p.target_id + ' · ' + p.status, '<button class="button compact secondary" data-action="moderate" data-id="' + e(p.target_id) + '" data-kind="' + e(p.target_type) + '">处理</button>'); }).join('') || C.empty('没有举报记录')) + '<section class="thread"><h2>管理公开内容</h2><form id="moderationForm" class="form"><label>目标类型</label><select name="target_type"><option value="publication">成果</option><option value="post">帖子</option><option value="comment">评论</option></select><label>目标 ID</label><input name="target_id" required><label>操作</label><select name="action"><option value="hide">下架 / 隐藏</option><option value="restore">恢复被隐藏内容</option><option value="lock">锁定讨论</option><option value="unlock">解锁讨论</option><option value="feature">精选成果</option><option value="unfeature">取消精选</option></select><label>处理理由</label><textarea name="reason" required maxlength="1000"></textarea><div class="actions"><button class="button">提交并记录审计</button></div></form></section>' + (state.user.role === 'admin' ? '<section class="thread"><h2>账号管理</h2><p><a href="/console#admin">打开管理员控制台 ↗</a></p><form id="userStatusForm" class="form"><label>用户 ID</label><input name="user_id" type="number" required min="1"><label>账号状态</label><select name="enabled"><option value="true">启用</option><option value="false">停用</option></select><label>社区管理权限</label><select name="moderator"><option value="false">普通用户</option><option value="true">社区版主</option></select><div class="actions"><button class="button secondary">更新账号权限</button></div></form></section>' : ''));
    document.getElementById('moderationForm').onsubmit = async function (event) { event.preventDefault(); try { await C.api('POST','/api/community/moderate',Object.fromEntries(new FormData(this))); location.reload(); } catch (err) { C.error(err); } };
    if (state.user.role === 'admin') {
      var limits = await C.api('GET','/api/community/settings');
      var labels = {daily_llm_calls_per_user:'每人每日模型调用',max_worlds_per_user:'每人世界数量',max_storage_mb_per_user:'私人研究存储（MB，启动前检查）',max_community_storage_mb_per_user:'社区内容存储（MB）',max_pending_publications_per_user:'每人未发布草稿数量'};
      app.insertAdjacentHTML('beforeend',gwHTML('<section class="thread"><h2>平台资源额度</h2><p class="hint">0 表示不限制。修改不会自动启动或停止已有任务。</p><form class="form" id="limitsForm">' + Object.keys(limits).map(function(k){return '<label for="limit-' + e(k) + '">' + e(labels[k] || k) + '</label><input type="number" min="0" max="1000000" required id="limit-' + e(k) + '" name="' + e(k) + '" value="' + Number(limits[k]) + '">';}).join('') + '<div class="actions"><button class="button">保存资源额度</button></div></form></section>'));
      document.getElementById('limitsForm').onsubmit=async function(event){event.preventDefault();var data=Object.fromEntries(new FormData(this));Object.keys(data).forEach(function(k){data[k]=Number(data[k]);});try{await C.api('POST','/api/community/settings',data);C.toast('额度已保存');}catch(err){C.error(err);}};
    }
    var f = document.getElementById('userStatusForm'); if (f) f.onsubmit = async function (event) { event.preventDefault(); var d = Object.fromEntries(new FormData(this)); d.user_id = Number(d.user_id); d.enabled = d.enabled === 'true'; d.moderator = d.moderator === 'true'; try { await C.api('POST','/api/auth/users/status',d); C.toast('账号状态已更新'); } catch (err) { C.error(err); } };
  }
  app.addEventListener('click', async function (event) {
    var b = event.target.closest('[data-action]'); if (!b) return; b.disabled = true;
    var action = b.dataset.action, id = b.dataset.id;
    try {
      if (action === 'world-run') { if (await selectWorld(id, '/console#dashboard')) C.navigate('/console#dashboard'); }
      if (action === 'open-plan' || action === 'open-study') { var target = '/site/dashboard/research.html?' + (action === 'open-plan' ? 'plan_id=' : 'study_id=') + encodeURIComponent(id); if (await selectWorld(b.dataset.world || '', target)) C.navigate(target); }
      if (action === 'delete-draft' && confirm('删除这份未发布草稿？')) { await C.api('POST','/api/community/drafts/delete',{id:id}); location.reload(); }
      if (action === 'withdraw' && confirm('撤回后游客将无法读取该成果及附件，确认撤回？')) { await C.api('POST','/api/community/withdraw',{ id:id }); location.reload(); }
      if (action === 'unbookmark') { await C.api('POST','/api/community/bookmarks',{ target_type:b.dataset.kind,target_id:id,enabled:false }); await bookmarks(); }
      if (action === 'seen') { await C.api('POST','/api/community/notifications/seen',{}); await notifications(); }
      if (action === 'resend') { await C.api('POST','/api/auth/resend',{ email:state.user.email }); C.toast('验证邮件已提交发送，请检查收件箱'); }
      if (action === 'close-sessions') { await C.api('POST','/api/auth/sessions/close-others',{}); C.toast('已退出其他设备'); }
      if (action === 'logout') { await C.api('POST','/api/auth/logout',{}); (C.embedded ? window.parent : window).location.href = gwURL('/explore'); }
      if (action === 'moderate') { var f = document.getElementById('moderationForm'); f.elements.target_type.value = b.dataset.kind; f.elements.target_id.value = id; f.scrollIntoView({ behavior:'smooth' }); f.elements.reason.focus(); }
    } catch (err) { C.error(err); } finally { b.disabled = false; }
  });
  C.ready.then(async function (me) {
    if (!me.user) { app.innerHTML = gwHTML(C.empty('请以账号登录', me.mode === 'single' ? '当前部署尚未启用账号。管理员初始化后可使用个人工作空间。' : '登录后进入自己的研究与仿真工作台。') + '<a class="button" href="/login">登录</a>'); return; }
    state = await C.api('GET','/api/workspace/overview'); await C.bindWorld(state.current_world);
    document.getElementById('moderationLink').hidden = !(state.user.role === 'admin' || state.user.moderator);
    document.querySelectorAll('[data-view]').forEach(function (a) { a.classList.toggle('active',a.dataset.view === view); });
    var renderers = { overview:overview,research:research,worlds:worlds,publish:publishForm,publications:publications,bookmarks:bookmarks,notifications:notifications,account:account,moderation:moderation };
    await (renderers[view] || overview)();
  }).catch(function (err) { app.innerHTML = gwHTML(C.empty('工作空间暂不可用',err.message)); });
})();
