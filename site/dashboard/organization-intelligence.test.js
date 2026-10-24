"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function harness(initialStatus = "draft") {
  const elements = new Map(), requests = [], timers = [];
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      value: id === "oiRepeats" ? "3" : id === "oiSeed" ? "20261020" : "",
      dataset: {}, events: {}, textContent: "", innerHTML: "", hidden: false,
      addEventListener(name, callback) { this.events[name] = callback; }
    });
    return elements.get(id);
  }
  const record = {
    id: "OI" + "a".repeat(24), status: initialStatus, calls_completed: 0, calls_started: 0,
    protocol: { model: { name: "model", model: "fixture" }, repeats: 3, budget: { requests: 327 }, arms: {}, city: "城" }
  };
  const context = {
    document: { readyState: "complete", getElementById: element },
    fetch: async (url, options) => {
      requests.push({ url, options });
      let body;
      if (url.endsWith("/run")) { record.status = "running"; body = { id: record.id }; }
      else if (url.endsWith("/organization-intelligence") && options && options.method === "POST") body = record;
      else if (url.endsWith("/organization-intelligence")) body = { providers: [{ name: "model", model: "fixture" }], studies: [record], default_provider: "model", city: "城" };
      else body = record;
      return { ok: true, json: async () => structuredClone(body) };
    },
    location: { href: "http://localhost/research.html?tab=organization-intelligence", search: "?tab=organization-intelligence" },
    history: { replaceState() {} }, URL, URLSearchParams,
    setTimeout(callback) { timers.push(callback); return timers.length; }, clearTimeout() {}
  };
  vm.runInNewContext(fs.readFileSync(__dirname + "/organization-intelligence.js", "utf8"), context);
  return { element, requests, record, timers };
}
async function settle() { for (let i = 0; i < 8; i++) await new Promise(setImmediate); }

test("freezing a protocol does not launch model calls; start is a separate explicit action", async () => {
  const h = harness();
  await settle();
  h.element("oiForm").events.submit({ preventDefault() {} });
  await settle();
  assert.equal(h.requests.filter(r => r.options && r.options.method === "POST").length, 1);
  assert.ok(!h.requests.some(r => r.url.endsWith("/run")));
  assert.equal(h.element("oiStatus").textContent, "协议已冻结");
  assert.equal(h.element("oiRun").hidden, false);
  h.element("oiRun").events.click();
  await settle();
  assert.equal(h.requests.filter(r => r.url.endsWith("/run")).length, 1);
  assert.equal(h.element("oiRun").hidden, true);
  assert.equal(h.element("oiStop").hidden, false);
  assert.equal(h.element("oiStatus").textContent, "正在运行");
});

test("partial evidence is not rendered as a treatment comparison", async () => {
  const h = harness("failed");
  h.record.error = "回答格式无效";
  h.record.analysis = { complete: false, contrasts: [{ label: "must not show", mean: 1 }] };
  await settle();
  h.element("oiForm").events.submit({ preventDefault() {} });
  await settle();
  assert.match(h.element("oiResults").textContent, /不用于判断组织收益/);
  assert.ok(!h.element("oiResults").innerHTML.includes("must not show"));
  assert.match(h.element("oiDiagnostic").textContent, /回答格式无效/);
});

test("comparison text from saved artifacts is escaped", async () => {
  const h = harness("completed");
  h.record.analysis = { complete: true, inference: "<script>bad</script>", contrasts: [{ label: "<img onerror=bad>", mean: .1 }] };
  await settle();
  h.element("oiForm").events.submit({ preventDefault() {} });
  await settle();
  assert.ok(h.element("oiResults").innerHTML.includes("&lt;img"));
  assert.ok(!h.element("oiResults").innerHTML.includes("<script>"));
});

test("polling updates the record list through completion", async () => {
  const h = harness("running");
  await settle();
  h.element("oiForm").events.submit({ preventDefault() {} });
  await settle();
  h.record.status = "completed";
  h.record.calls_completed = 327;
  h.timers.at(-1)();
  await settle();
  assert.match(h.element("oiStudies").innerHTML, /已完成 · 327 次响应/);
});

test("rate limit is actionable and recovering a draft does not submit model calls", async () => {
  const h = harness("failed");
  h.record.display_status = "rate_limited";
  h.record.can_recover = true;
  h.record.rate_limit = {kind: "token_plan_2062", retry_at: 1000, message: "MiniMax Token Plan 已限流（2062）", hint: "退避下限不代表配额恢复"};
  h.record.error = "HTTPError: long transport diagnostic";
  await settle();
  h.element("oiForm").events.submit({ preventDefault() {} });
  await settle();
  assert.match(h.element("oiStatus").textContent, /等待配额恢复/);
  assert.equal(h.element("oiRecover").hidden, false);
  assert.match(h.element("oiNotice").textContent, /2062/);
  assert.ok(!h.element("oiMetrics").textContent.includes("long transport diagnostic"));
  assert.equal(h.element("oiDiagnostic").textContent, h.record.error);
  h.element("oiRecover").events.click();
  await settle();
  assert.equal(h.requests.filter(r => r.url.endsWith("/recover")).length, 1);
  assert.ok(!h.requests.some(r => r.url.endsWith("/run")));
});

test("proxy disconnect is explained without being labelled as model answer failure", async () => {
  const h = harness("failed");
  h.record.error = "ProxyError: HTTPSConnectionPool(host='api.minimaxi.com'): Unable to connect to proxy";
  h.record.can_recover = true;
  h.record.calls_completed = 107;
  await settle();
  h.element("oiForm").events.submit({ preventDefault() {} });
  await settle();
  assert.match(h.element("oiStatus").textContent, /连接中断/);
  assert.match(h.element("oiNotice").textContent, /代理/);
  assert.match(h.element("oiNotice").textContent, /断点/);
  assert.ok(!h.element("oiNotice").textContent.includes("回答或运行异常"));
  assert.equal(h.element("oiRecover").hidden, false);
  assert.equal(h.element("oiDiagnostic").textContent, h.record.error);
  assert.ok(!h.requests.some(r => r.url.endsWith("/run")));
});
