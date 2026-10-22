(function () {
  "use strict";
  var C = window.Community, e = C.esc, app = document.getElementById("app"), params = new URLSearchParams(location.search);
  var parts = location.pathname.split("/").filter(Boolean), current, targetType, targetId;
  function pager(count) {
    var offset = Math.max(0, Number(params.get("offset")) || 0);
    function url(next) { var q = new URLSearchParams(params); q.set("offset", next); return location.pathname + "?" + q; }
    return '<div class="pager">' + (offset ? '<a href="' + e(url(Math.max(0, offset - 24))) + '">← 上一页</a>' : '<span></span>') + (count === 24 ? '<a href="' + e(url(offset + 24)) + '">下一页 →</a>' : '') + '</div>';
  }
  async function explore() {
    var q = new URLSearchParams(params);
    var result = await C.api("GET", "/api/community/publications?" + q);
    app.innerHTML = '<section class="hero"><div><p class="eyebrow">OPEN RESEARCH / GAWorld</p><h1>让研究被看见，<br>让问题继续生长。</h1><p>发现用智能体探索社会的研究、方法与仿真案例。阅读结果，也阅读它们的条件与局限。</p></div><div class="hero-aside"><strong>从一个问题开始。</strong><p>在自己的工作台探索，在这里分享与讨论。</p><a class="button" href="/workspace">进入我的工作空间 ↗</a></div></section><form id="searchForm" class="toolbar"><input name="q" aria-label="搜索研究" placeholder="搜索问题、研究或方法" value="' + e(params.get("q") || "") + '"><select name="kind" aria-label="成果类型"><option value="">全部成果</option><option value="plan">研究方案</option><option value="study">研究报告</option><option value="simulation">仿真案例</option></select><input name="tag" aria-label="标签" placeholder="按标签筛选" value="' + e(params.get("tag") || "") + '" style="flex:0 1 170px;min-width:120px"><button class="button" type="submit">搜索</button></form><div class="section-head"><h2>公开研究</h2><span class="hint">最新发布 · 精选优先</span></div><div class="grid">' + (result.publications.map(C.card).join("") || C.empty("第一项公开研究，等你发布", "研究方案、部分结果和完整报告都可以分享，请清楚说明证据边界。")) + '</div>' + pager(result.publications.length);
    app.querySelector('[name="kind"]').value = params.get("kind") || "";
    document.getElementById("searchForm").onsubmit = function (event) { event.preventDefault(); var values = new URLSearchParams(new FormData(event.target)); location.href = "/explore?" + values; };
  }
  async function plaza() {
    var result = await C.api("GET", "/api/community/posts?" + params);
    app.innerHTML = '<section class="hero"><div><p class="eyebrow">THE COMMONS</p><h1>好研究，从交流开始。</h1><p>分享一项成果，提出一个还没解开的疑问，或一起打磨研究方法。</p></div><div class="hero-aside"><a class="button" href="#new-post">发起讨论 +</a></div></section><div class="toolbar"><a class="tag" href="/plaza">全部讨论</a><a class="tag" href="/plaza?category=share">成果分享</a><a class="tag" href="/plaza?category=question">研究问题</a><a class="tag" href="/plaza?category=method">方法讨论</a></div><div>' + (result.posts.map(function (p) { return '<article class="list-row"><div><span class="tag">' + e({ question: "研究问题", method: "方法讨论", share: "成果分享" }[p.category]) + '</span><h3><a href="/posts/' + encodeURIComponent(p.id) + '">' + e(p.title) + '</a></h3><p class="hint">' + C.author(p.author) + ' · ' + C.date(p.created_at) + '</p></div><a href="/posts/' + encodeURIComponent(p.id) + '">参与讨论 ↗</a></article>'; }).join("") || C.empty("这里还没有讨论", "分享一个你正在思考的研究问题。")) + '</div>' + pager(result.posts.length) + '<section class="thread" id="new-post"><h2>发起讨论</h2>' + (C.user ? '<form id="postForm" class="form"><label for="postTitle">标题</label><input id="postTitle" name="title" maxlength="160" required><label for="postCategory">讨论分类</label><select id="postCategory" name="category"><option value="question">研究问题</option><option value="method">方法讨论</option><option value="share">成果分享</option></select><div id="shareTarget" hidden><label for="postPublication">选择公开成果</label><select id="postPublication" name="publication_id"></select></div><label for="postBody">内容</label><textarea id="postBody" name="body" maxlength="20000" required></textarea><div class="actions"><button class="button">发布讨论</button></div></form>' : '<p class="muted"><a href="/login?next=/plaza">登录</a>后发起讨论。</p>') + '</section>';
    if (C.user) {
      document.getElementById("postCategory").onchange = async function () {
        var share = this.value === "share"; document.getElementById("shareTarget").hidden = !share;
        if (share) { var r = await C.api("GET", "/api/community/publications"); document.getElementById("postPublication").innerHTML = r.publications.map(function (p) { return '<option value="' + e(p.id) + '">' + e(p.title) + '</option>'; }).join(""); }
      };
      document.getElementById("postForm").onsubmit = async function (event) { event.preventDefault(); var button = this.querySelector("button"); button.disabled = true; try { var p = await C.api("POST", "/api/community/posts", Object.fromEntries(new FormData(this))); location.href = "/posts/" + encodeURIComponent(p.id); } catch (err) { C.error(err); button.disabled = false; } };
    }
  }
  async function detail() {
    targetType = parts[0] === "publications" ? "publication" : "post"; targetId = parts[1];
    var isPub = targetType === "publication", endpoint = isPub ? "publications" : "posts";
    current = await C.api("GET", "/api/community/" + endpoint + "/" + encodeURIComponent(targetId) + "?" + params);
    document.title = current.title + " · GAWorld";
    var versions = isPub ? '<label for="versionSelect">成果版本</label><select class="version-select" id="versionSelect">' + current.versions.map(function (v) { return '<option value="' + Number(v) + '">v' + Number(v) + (v === current.current_version ? ' · 最新' : '') + '</option>'; }).join("") + '</select><p class="hint">讨论对应具体版本，旧版本保留原结论。</p>' : '';
    var files = isPub ? current.attachments.map(function (a) { return '<button class="link-button" data-action="attachment" data-id="' + e(a.id) + '">↓ ' + e(a.name) + '</button><br>'; }).join("") : '';
    app.innerHTML = '<a class="hint" href="' + (isPub ? '/explore' : '/plaza') + '">← ' + (isPub ? '发现研究' : '公共广场') + '</a><div class="article-layout"><article class="article"><p class="eyebrow" style="margin-top:32px">' + (isPub ? 'RESEARCH / ' + e(C.kind[current.kind]) : 'DISCUSSION / 研究交流') + '</p><h1>' + e(current.title) + '</h1><div class="article-meta">' + C.author(current.author) + '<span>' + C.date(current.published_at || current.created_at) + '</span>' + (isPub ? '<span class="status">' + e(C.status[current.result_status]) + '</span><span>v' + Number(current.version) + '</span>' : '') + '</div>' + (current.summary ? '<div class="article-summary">' + e(current.summary) + '</div>' : '') + '<div class="article-body">' + e(current.body) + '</div>' + (current.methods ? '<h2>研究方法</h2><div class="article-body small">' + e(current.methods) + '</div>' : '') + (current.limitations ? '<h2>局限与证据边界</h2><div class="article-body small">' + e(current.limitations) + '</div>' : '') + (current.references ? '<h2>来源与引用</h2><div class="article-body small">' + e(current.references) + '</div>' : '') + (isPub && current.include_template ? '<details><summary>公开的可复用方案</summary><pre class="article-body small">' + e(JSON.stringify(current.public_template || {}, null, 2)) + '</pre></details>' : '') + (!isPub && current.publication_id ? '<a class="button secondary" href="/publications/' + encodeURIComponent(current.publication_id) + '">阅读相关成果 ↗</a>' : '') + '<section id="thread" class="thread"></section></article><aside style="padding-top:38px"><div class="side-panel">' + versions + '<p>讨论' + (current.locked ? '已锁定' : '开放中') + '</p><button class="button secondary" data-action="bookmark">收藏</button>' + (isPub && current.reusable ? '<button class="button" data-action="fork">复制到我的工作台 ↗</button><p class="hint">创建私人草稿，检查配置后自行启动。</p>' : '') + '<button class="link-button" data-action="report" style="margin-top:18px">举报或申请管理处理</button></div>' + (isPub ? '<div class="side-panel"><p>复用许可 · ' + e(current.license) + '</p><p class="hint">发布内容是作者选定的版本。仿真结果应结合方法与局限解读。</p>' + files + '</div>' : '') + '</aside></div>';
    if (isPub) { var select = document.getElementById("versionSelect"); select.value = current.version; select.onchange = function () { location.href = "/publications/" + encodeURIComponent(targetId) + "?version=" + this.value; }; }
    await thread();
  }
  async function thread() {
    var version = targetType === "publication" ? current.version : 0;
    var result = await C.api("GET", "/api/community/comments?" + new URLSearchParams({ target_type: targetType, target_id: targetId, version: params.get("all_comments") ? 0 : version }));
    var rows = result.comments, root = document.getElementById("thread");
    function comment(c) { return '<div class="comment ' + (c.parent_id ? 'reply' : '') + '"><div class="comment-head">' + C.author(c.author) + '<span>' + C.date(c.created_at) + (c.version ? ' · v' + Number(c.version) : '') + (c.edited_at ? ' · 已编辑' : '') + '</span></div><p>' + e(c.body) + '</p><div class="comment-actions">' + (C.user && !current.locked && !c.parent_id ? '<button class="link-button" data-action="reply" data-id="' + e(c.id) + '">回复</button>' : '') + (C.user && C.user.id === c.author_id && c.status === 'published' ? '<button class="link-button" data-action="edit-comment" data-id="' + e(c.id) + '">编辑</button><button class="link-button" data-action="delete-comment" data-id="' + e(c.id) + '">删除</button>' : '') + '<button class="link-button" data-action="report-comment" data-id="' + e(c.id) + '">举报</button></div></div>'; }
    root.innerHTML = '<div class="section-head" style="margin-top:0"><h2>讨论 <span class="hint">' + rows.length + '</span></h2>' + (targetType === 'publication' ? '<a class="hint" href="?version=' + version + (params.get("all_comments") ? '' : '&all_comments=1') + '#thread">' + (params.get("all_comments") ? '仅当前版本' : '查看全部版本') + '</a>' : '') + '</div>' + (rows.length ? rows.filter(function (r) { return !r.parent_id; }).map(function (r) { return comment(r) + rows.filter(function (child) { return child.parent_id === r.id; }).map(comment).join(""); }).join("") : '<p class="muted">还没有讨论，留下你的问题或建议。</p>') + (current.locked ? '<p class="hint">此讨论已锁定。</p>' : C.user ? '<form id="commentForm"><p class="hint" id="replyHint">围绕方法、结果和证据展开讨论。</p><input type="hidden" name="parent_id"><label for="commentBody" class="hint">你的评论</label><textarea id="commentBody" name="body" maxlength="5000" required placeholder="写下你的问题或看法…"></textarea><button class="button" style="margin-top:14px">发表评论</button></form>' : '<p><a href="/login?next=' + encodeURIComponent(location.pathname + location.search) + '">登录后参与讨论 ↗</a></p>');
    if (document.getElementById("commentForm")) document.getElementById("commentForm").onsubmit = async function (event) {
      event.preventDefault(); var btn = this.querySelector("button"); btn.disabled = true;
      try { await C.api("POST", "/api/community/comments", Object.assign(Object.fromEntries(new FormData(this)), { target_type: targetType, target_id: targetId, version: version })); await thread(); C.toast("评论已发布"); } catch (err) { C.error(err); btn.disabled = false; }
    };
  }
  app.addEventListener("click", async function (event) {
    var button = event.target.closest("[data-action]"); if (!button) return;
    var action = button.dataset.action, id = button.dataset.id;
    if (action !== "attachment" && !C.loginRequired()) return;
    button.disabled = true;
    try {
      if (action === "bookmark") { await C.api("POST", "/api/community/bookmarks", { target_type: targetType, target_id: targetId, enabled: true }); C.toast("已收藏，可在工作空间查看"); }
      if (action === "reply") { document.querySelector('[name="parent_id"]').value = id; document.getElementById("replyHint").textContent = "正在回复该评论；刷新页面可取消。"; document.getElementById("commentBody").focus(); }
      if (action === "edit-comment") { var body = prompt("编辑评论（页面显示编辑标记）", button.closest(".comment").querySelector("p").textContent); if (body) { await C.api("POST", "/api/community/comments/edit", { id: id, body: body }); await thread(); } }
      if (action === "delete-comment" && confirm("删除这条评论？回复关系将保留。")) { await C.api("POST", "/api/community/comments/delete", { id: id }); await thread(); }
      if (action === "report" || action === "report-comment") { var reason = prompt("请说明举报或管理请求的原因"); if (reason) { await C.api("POST", "/api/community/reports", { target_type: action === "report-comment" ? "comment" : targetType, target_id: action === "report-comment" ? id : targetId, reason: reason }); C.toast("已提交，等待社区管理者处理"); } }
      if (action === "fork") {
        var workspace = await C.api("GET", "/api/workspace/overview"); C.world = workspace.current_world;
        var result = await C.api("POST", "/api/community/fork", { id: targetId, version: current.version, world_id: C.world });
        C.toast("已创建私人研究草稿；请配置本人的城市、居民和模型。");
        location.href = "/workspace?view=research&copied=" + encodeURIComponent(result.plan_id);
      }
      if (action === "attachment") {
        var file = await C.api("GET", "/api/community/attachment?" + new URLSearchParams({ id: targetId, version: current.version, attachment_id: id }));
        var url = URL.createObjectURL(new Blob([file.text], { type: file.mime })), a = document.createElement("a"); a.href = url; a.download = file.name; a.click(); setTimeout(function () { URL.revokeObjectURL(url); }, 500);
      }
    } catch (err) { C.error(err); } finally { button.disabled = false; }
  });
  async function profile() {
    var p = await C.api("GET", "/api/community/people/" + encodeURIComponent(parts[1]));
    app.innerHTML = '<section class="hero"><div><p class="eyebrow">RESEARCHER</p><h1>' + e(p.display_name) + '</h1><p style="white-space:pre-wrap">' + e(p.bio || "这位研究者还没有填写简介。") + '</p><p>' + e(p.interests) + '</p></div><div class="hero-aside"><strong>公开研究</strong><p>这里展示作者主动公开的成果。</p></div></section><div class="section-head"><h2>已发布成果</h2></div><div class="grid">' + (p.publications.map(C.card).join("") || C.empty("暂未发布成果")) + '</div>';
  }
  C.ready.then(function () { if (parts[0] === "publications" || parts[0] === "posts") return detail(); if (parts[0] === "people") return profile(); return parts[0] === "plaza" ? plaza() : explore(); }).catch(function (err) { app.innerHTML = C.empty("页面暂不可用", err.message); });
})();
