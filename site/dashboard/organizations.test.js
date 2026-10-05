"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

test("governance forms carry strict proposal and ballot commands", () => {
  const ui = require("./organizations.js");
  assert.deepEqual(ui.buildCommand("set_governance", {mode:"member_vote",threshold:"quorum_majority",voting_days:"1"}, "care"),
    {type:"set_governance",organization_id:"care",governance:{mode:"member_vote",threshold:"quorum_majority",voting_days:1}});
  assert.deepEqual(ui.buildCommand("propose_rule", {agent_id:"2",rule:"need_first",cap:"2.50",reason:"困难优先",title:"资助提案"}, "care"),
    {type:"propose_rule",organization_id:"care",agent_id:2,rule:"need_first",rule_params:{max_award_cents:250},reason:"困难优先",title:"资助提案"});
  assert.deepEqual(ui.buildCommand("cast_vote", {agent_id:"3",proposal_id:"p1",choice:"abstain",reason:"缺少信息"}, "care"),
    {type:"cast_vote",organization_id:"care",agent_id:3,proposal_id:"p1",choice:"abstain",reason:"缺少信息"});
  assert.throws(()=>ui.buildCommand("leader_decide", {agent_id:"1",proposal_id:"p1",choice:"abstain"}, "care"));
});

test("governance detail distinguishes approved from executed and shows denominators", () => {
  const ui = require("./organizations.js");
  const org = {organization_id:"care",name:"互助会",kind:"community",status:"open",rule:"equal_split",
    governance:{mode:"member_vote",threshold:"quorum_majority",voting_days:1}, governance_version:1,
    proposals:[{proposal_id:"p1",status:"approved",proposer_id:2,reason:"<script>x</script>",
      opened_day:1,closing_day:2,resolved_day:2,execute_not_before_day:3,base_rule_version:1,
      before:{rule:"equal_split",rule_params:{max_award_cents:100}},after:{rule:"need_first",rule_params:{max_award_cents:200}},
      electorate:[1,2,3,4],resolution_reason:"threshold_met",tally:{yes:1,no:0,abstain:1,participation:2,eligible:4},execution_command_id:"exec-p1"}]};
  let rendered = ui.renderDetail(org);
  for(const label of ["组织治理","成员表决","通过待执行","Day 3","2 / 4","exec-p1","等额分配","困难优先"]) assert.match(rendered,new RegExp(label));
  assert.doesNotMatch(rendered,/<script>/);
  assert.match(rendered,/达到通过门槛/);
  org.proposals[0].status="executed";
  org.proposals[0].execution_day=3;
  org.proposals[0].execution_rule_version=2;
  rendered=ui.renderDetail(org);
  assert.match(rendered,/已执行/);
  assert.match(rendered,/v2/);
});

test("governance operation choices follow the selected organization's authority", () => {
  const ui = require("./organizations.js");
  const org={kind:"community",governance:{mode:"leader"},proposals:[{status:"open"}]};
  assert.ok(ui.operationsFor(org,true).includes("leader_decide"));
  assert.ok(!ui.operationsFor(org,true).includes("cast_vote"));
  assert.ok(!ui.operationsFor(org,false).includes("set_governance"));
});

test("leader governance does not display a member quorum or abstention requirement",()=>{
  const ui=require("./organizations.js");
  const html=ui.renderDetail({organization_id:"firm",name:"工作坊",kind:"company",leader_id:1,
    governance:{mode:"leader",threshold:"quorum_majority",voting_days:1},
    proposals:[{proposal_id:"p1",status:"open",leader_id:1,policy:{mode:"leader"},before:{},after:{},electorate:[1,2,3]}]});
  assert.match(html,/固定决策者：#1/);
  assert.doesNotMatch(html,/至少半数参与|弃权计入参与|固定成员：/);
});

test("a new open proposal refreshes ballot forms while same-proposal polling preserves inputs", async () => {
  const elements = new Map();
  const element=id=>{
    if(!elements.has(id)) elements.set(id,{value:id==="orgKind"?"community":"",innerHTML:"",disabled:false,
      listeners:{},classList:{toggle(){}},addEventListener(name,callback){this.listeners[name]=callback;}});
    return elements.get(id);
  };
  let pid="p1";
  const org=()=>({organization_id:"care",name:"互助会",kind:"community",status:"open",
    governance:{mode:"member_vote"},proposals:[{proposal_id:pid,status:"open",before:{},after:{},electorate:[]}]});
  const context={document:{getElementById:element},setTimeout:()=>0,clearTimeout(){},fetch:async url=>({ok:true,json:async()=>
    url==="/api/organizations"?{organizations:[org()],governance_enabled:true,can_write:true}:
    url.endsWith("/commands")?{commands:[]}:url.endsWith("/history")?{history:[]}:org()})};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,"organizations.js"),"utf8"),context);
  const flush=()=>new Promise(resolve=>setImmediate(resolve));
  await flush();
  element("orgList").listeners.click({target:{closest:()=>({dataset:{orgId:"care"}})}});
  await flush();
  element("orgCommandType").value="cast_vote";
  element("orgCommandType").listeners.change();
  assert.match(element("orgCommandInputs").innerHTML,/value="p1"/);
  element("orgCommandInputs").innerHTML += "draft-preserved";
  await element("orgRefresh").listeners.click();
  assert.match(element("orgCommandInputs").innerHTML,/draft-preserved/);
  pid="p2";
  await element("orgRefresh").listeners.click();
  assert.match(element("orgCommandInputs").innerHTML,/value="p2"/);
  assert.doesNotMatch(element("orgCommandInputs").innerHTML,/value="p1"/);
});

test("profile updates carry only the editable name and goal", () => {
  const ui = require("./organizations.js");
  assert.deepEqual(ui.buildCommand("update_profile", {name:" 河畔互助会 ", goal:"基本生活保障"}, "care"),
    {type:"update_profile", organization_id:"care", name:"河畔互助会", goal:"基本生活保障"});
  assert.throws(() => ui.buildCommand("update_profile", {name:" ", goal:"目标"}, "care"));
});

test("late detail responses cannot route a management command to another organization", async () => {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) {
      const row = {value: id === "orgKind" ? "community" : "", innerHTML:"", disabled:false,
        classList:{toggle(){}}, listeners:{}, addEventListener(event, callback){this.listeners[event]=callback;}};
      elements.set(id, row);
    }
    return elements.get(id);
  };
  const makeOrg = (id) => ({organization_id:id, name:"组织 " + id, kind:"community", members:[], jobs:[], applications:[], balance_cents:100});
  let resolveA;
  const pendingA = new Promise(resolve => {resolveA=resolve;});
  const posts = [];
  const fetch = async (url, options) => {
    if (options && options.method === "POST") {
      posts.push(JSON.parse(options.body));
      return {ok:true, json:async()=>({command_id:"queued", status:"pending"})};
    }
    if (url === "/api/organizations/a") return pendingA;
    const body = url === "/api/organizations" ? {organizations:[makeOrg("a"), makeOrg("b")], enabled:true, can_write:true} :
      url === "/api/organizations/commands" ? {commands:[]} : url.endsWith("/history") ? {history:[]} : makeOrg("b");
    return {ok:true, json:async()=>body};
  };
  const context = {document:{getElementById:element}, fetch, setTimeout:()=>0, clearTimeout(){},
    FormData:class {constructor(form){this.fields=form.fields;} forEach(callback){Object.entries(this.fields).forEach(([key,value])=>callback(value,key));}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,"organizations.js"),"utf8"), context);
  const flush = () => new Promise(resolve=>setImmediate(resolve));
  await flush();
  const select = id => element("orgList").listeners.click({target:{closest:()=>({dataset:{orgId:id}})}});
  select("a");
  await flush();
  select("b");
  assert.equal(element("orgCommandFields").disabled, true, "form disabled until selection and displayed details agree");
  resolveA({ok:true,json:async()=>makeOrg("a")});
  await flush();
  await flush();
  assert.match(element("orgDetail").innerHTML, /组织 b/);
  assert.doesNotMatch(element("orgDetail").innerHTML, /组织 a/);
  const button={disabled:false};
  await element("orgCommandForm").listeners.submit({preventDefault(){}, target:{fields:{type:"fund", amount:"1", source:"government"}, querySelector:()=>button}});
  await flush();
  assert.equal(posts.length,1);
  assert.equal(posts[0].organization_id,"b");
});

test("organization management has a working dashboard module", () => {
  assert.equal(fs.existsSync(path.join(__dirname, "organizations.js")), true);
});

test("community and company templates preserve cents and their registered rules", () => {
  const ui = require("./organizations.js");
  const shared = {organization_id: "org-a", name: "互助", leader_id: "1", member_ids: "2,3",
    initial_balance: "100.25", goal: "目标", decision_interval: "1", seed: "42", cap: "20"};
  const aid = ui.buildCommand("create", {...shared, kind: "community", rule: "equal_split"});
  assert.equal(aid.initial_balance_cents, 10025);
  assert.equal(aid.funding_source, "government");
  assert.deepEqual(aid.member_ids, [2, 3]);
  assert.equal(aid.rule, "equal_split");
  const company = ui.buildCommand("create", {...shared, kind: "company", rule: "skill_first"});
  assert.equal(company.funding_source, "firms");
  assert.equal(company.rule, "skill_first");
});

test("fund and wage commands use integer cents and reject invalid money", () => {
  const ui = require("./organizations.js");
  assert.deepEqual(ui.buildCommand("fund", {amount: "99.99", source: "firms"}, "company-a"),
    {type: "fund", organization_id: "company-a", amount_cents: 9999, source: "firms"});
  assert.equal(ui.buildCommand("publish_job", {occupation: "工人", vacancies: "2", monthly_salary: "4000",
    min_income_skill: "0.6", location: "车间"}, "company-a").monthly_salary_cents, 400000);
  for (const amount of ["-1", "1.001", "NaN", "Infinity", "", "1e3"]) {
    assert.throws(() => ui.buildCommand("fund", {amount, source: "government"}, "a"));
  }
});

test("queued commands and applied results have distinct labels and escape text", () => {
  const ui = require("./organizations.js");
  const queued = ui.renderCommand({command_id: "cmd-a", organization_id: "a", type: "create", status: "pending", result: null});
  assert.match(queued, /排队等待/);
  assert.doesNotMatch(queued, /已应用/);
  assert.match(ui.renderCommand({command_id: "cmd-b", type: "fund", status: "applied", result: {paid_cents: 50}}), /已应用/);
  const rejected = ui.renderCommand({command_id: "<img onerror=x>", type: "fund", status: "rejected", result: {error: "<script>x</script>"}});
  assert.doesNotMatch(rejected, /<script>|<img/);
  assert.match(rejected, /&lt;script&gt;/);
});

test("detail shows member, funding, rule, application, job and arrears records", () => {
  const ui = require("./organizations.js");
  const detail = ui.renderDetail({organization_id: "a", name: "测试", kind: "company", status: "active", leader_id: 1,
    funding_source: "firms", balance_cents: 100, committed_cents: 20, arrears_cents: 50, rule: "skill_first",
    rule_version: 2, members: [{agent_id: 1, role: "leader", status: "active"}],
    jobs: [{job_id: "j1", occupation: "工人", vacancies: 2, monthly_salary_cents: 400000}],
    applications: [{agent_id: 2, status: "pending", type: "job", reason: "希望加入"}], rules: []});
  for (const text of ["负责人", "企业部门池", "技能匹配优先", "工资欠付", "工人", "希望加入", "成员"]) assert.match(detail, new RegExp(text));
});

test("dashboard shell exposes organization forms and console navigation", () => {
  const html = fs.readFileSync(path.join(__dirname, "organizations.html"), "utf8");
  for (const id of ["orgList", "orgDetail", "orgCommands", "orgCreateForm", "orgCommandForm", "orgStatus"]) {
    assert.match(html, new RegExp('id="' + id + '"'));
  }
  assert.match(html, /page-shell.css/);
  assert.match(html, /organizations.js/);
  assert.match(fs.readFileSync(path.join(__dirname, "../console/index.html"), "utf8"), /data-tab="organizations"/);
  assert.match(fs.readFileSync(path.join(__dirname, "../console/console.js"), "utf8"), /id: "organizations"/);
});

function exportPage(fetchExport, meta) {
  const elements = new Map(), requests = [], blobs = [], downloads = [], revoked = [];
  const element = id => {
    if (!elements.has(id)) elements.set(id, {value:id === "orgKind" ? "community" : "", disabled:false,
      classList:{toggle(){}}, listeners:{}, addEventListener(event, callback){this.listeners[event]=callback;}});
    return elements.get(id);
  };
  const context = {
    document:{getElementById:element, body:{appendChild(){}}, createElement(){
      const anchor = {remove(){}, click(){downloads.push({href:this.href, filename:this.download});}};
      return anchor;
    }},
    fetch:async (url, options) => {
      requests.push({url, options});
      if (url.startsWith("/api/organizations/exports/metrics")) return fetchExport(url);
      return {ok:true, json:async()=> url === "/api/organizations" ?
        {organizations:[], enabled:true, can_write:false, meta} : {commands:[]}};
    },
    Blob:class {constructor(parts, options){this.parts=parts; this.type=options.type; blobs.push(this);}},
    URL:{createObjectURL(){return "blob:metrics";}, revokeObjectURL(url){revoked.push(url);}},
    setTimeout:()=>0, clearTimeout(){},
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,"organizations.js"),"utf8"), context);
  return {element, requests, blobs, downloads, revoked};
}

test("completed metric download stays available to readers and preserves original integers", async () => {
  const content = '{"generation_id":"prior","day":1,"balance_cents":9007199254740993}\n';
  const page = exportPage(async()=>({ok:true, json:async()=>({filename:"organizations-prior-day-1-metrics.json",
    content_type:"application/json", content, generation_id:"prior", day:1})}),
    {generation_id:"prior", last_processed_day:1});
  assert.equal(page.element("orgDownload").disabled, true, "disabled before overview loads");
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(page.element("orgCreateFields").disabled, true, "management is readonly");
  assert.equal(page.element("orgDownload").disabled, false, "reading needs no write permission");
  await page.element("orgDownload").listeners.click();
  const request = page.requests.find(row=>row.url.startsWith("/api/organizations/exports/metrics"));
  assert.equal(request.url,"/api/organizations/exports/metrics?generation_id=prior&day=1");
  assert.notEqual(request.options.method, "POST");
  assert.equal(page.blobs[0].parts[0],content);
  assert.equal(page.blobs[0].type,"application/json");
  assert.equal(page.downloads[0].filename,"organizations-prior-day-1-metrics.json");
  assert.deepEqual(page.revoked,["blob:metrics"]);
});

test("missing completed day disables download without requesting an export", async () => {
  const page = exportPage(()=>assert.fail("no export request before completion"),
    {generation_id:"new", last_processed_day:0});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(page.element("orgDownload").disabled, true);
  await page.element("orgDownload").listeners.click();
  assert.equal(page.downloads.length,0);
});

test("export errors create no file and repeated clicks share one in-flight request", async () => {
  let finish;
  const pending = new Promise(resolve=>{finish=resolve;});
  const page = exportPage(()=>pending,{generation_id:"g1", last_processed_day:2});
  await new Promise(resolve=>setImmediate(resolve));
  const first = page.element("orgDownload").listeners.click();
  assert.equal(page.element("orgDownload").disabled,true);
  await page.element("orgDownload").listeners.click();
  finish({ok:false,status:404,json:async()=>({error:"该日没有指标档案"})});
  await first;
  assert.equal(page.requests.filter(row=>row.url.startsWith("/api/organizations/exports/metrics")).length,1);
  assert.equal(page.downloads.length,0);
  assert.match(page.element("orgStatus").textContent,/该日没有指标档案/);
  assert.equal(page.element("orgDownload").disabled,false);
});
