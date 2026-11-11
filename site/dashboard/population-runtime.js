/* Durable population task tracking. Network loss never means task failure. */
(function (root) {
  "use strict";

  function createRequest(options) {
    var send = options.fetch || root.fetch.bind(root);
    return function (method, path, body) {
      var controller = new AbortController(), timer;
      var operation = (async function () {
        var res = await send(path, { method: method, signal: controller.signal,
          headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
        var data;
        try { data = await res.json(); }
        catch (_) { throw Object.assign(new Error("HTTP " + res.status), { status: res.status }); }
        if (!res.ok) throw Object.assign(new Error(data.error || "HTTP " + res.status), { status: res.status });
        return data;
      })();
      var deadline = new Promise(function (_, reject) {
        timer = setTimeout(function () {
          controller.abort();
          reject(Object.assign(new Error("Request timed out"), { code: "timeout" }));
        }, options.timeoutMs || 20000);
      });
      return Promise.race([operation, deadline]).finally(function () { clearTimeout(timer); });
    };
  }

  function requestId() {
    if (root.crypto && root.crypto.randomUUID) return "pop-" + root.crypto.randomUUID();
    return "pop-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
  }

  function create(options) {
    var request = options.request || createRequest(options);
    var schedule = options.setTimer || setTimeout, cancel = options.clearTimer || clearTimeout;
    var key = options.storageKey || "gaworld.population.active";
    var current = null, generation = 0, timer = null, failures = 0, finished = false;
    function store(value) {
      try { if (options.storage) options.storage.setItem(key, JSON.stringify(value)); } catch (_) { /* optional */ }
    }
    function emit(name) {
      if (options[name]) options[name].apply(null, Array.prototype.slice.call(arguments, 1));
    }
    function halt() { generation++; cancel(timer); timer = null; }
    function snapshot() { return current ? Object.assign({}, current) : null; }
    function wait(fn, delay) { timer = schedule(fn, delay); }
    async function accept(job, token) {
      if (token !== generation || finished) return;
      if (!job || !job.status) throw Error("Invalid task response");
      current.job_id = job.id || current.job_id;
      current.kind = job.kind || current.kind;
      current.population_job_id = job.population_job_id || current.population_job_id;
      current.status = job.status;
      store(current);
      emit("onProgress", job);
      if (job.status === "running") { wait(poll, 1000); return; }
      finished = true;
      if (job.status === "done") emit("onDone", job, snapshot());
      else emit("onError", job.message || "Task interrupted", job.error || {}, snapshot());
    }
    async function poll() {
      if (!current || finished) return;
      cancel(timer); timer = null;
      var token = generation;
      var path = current.job_id ? "/api/population/jobs/" + encodeURIComponent(current.job_id)
        : "/api/population/recover?request_id=" + encodeURIComponent(current.request_id);
      try {
        var job = await request("GET", path);
        if (token !== generation) return;
        failures = 0;
        await accept(job, token);
      } catch (err) {
        if (token !== generation) return;
        failures++;
        var terminal = [400, 401, 403].includes(err.status) || (err.status === 404 && current.job_id);
        if (terminal) {
          finished = true;
          emit("onError", err.message, { code: "task_unavailable", status: err.status }, snapshot());
          return;
        }
        if (failures >= (options.maxFailures || 6)) {
          emit("onDisconnected", snapshot());
          return;
        }
        emit("onReconnecting", failures, snapshot());
        wait(poll, Math.min(15000, 1000 * Math.pow(2, failures - 1)));
      }
    }
    async function start(kind, path, payload) {
      halt(); failures = 0; finished = false;
      var token = generation;
      current = { kind: kind, request_id: requestId(), job_id: "", status: "submitting",
        population_job_id: payload.population_job_id || "" };
      store(current);
      try {
        var submitted = await request("POST", path, Object.assign({}, payload, { request_id: current.request_id }));
        if (token !== generation) return;
        if (!submitted.job_id) throw Error("Missing task identifier");
        current.job_id = submitted.job_id; store(current);
      } catch (err) {
        if (token !== generation) return;
        if ([400, 401, 403, 404, 409, 422].includes(err.status)) {
          finished = true;
          emit("onError", err.message, { code: "submission_rejected", status: err.status }, snapshot());
          return;
        }
        emit("onReconnecting", 0, snapshot());
      }
      return poll();
    }
    function restore() {
      var saved;
      try { saved = options.storage && JSON.parse(options.storage.getItem(key)); } catch (_) { return Promise.resolve(); }
      if (!saved || !/^[A-Za-z0-9_-]{8,80}$/.test(saved.request_id || "") || !["pop", "group", "validate"].includes(saved.kind)) {
        return Promise.resolve();
      }
      halt(); failures = 0; finished = false; current = saved;
      emit("onRestoring", snapshot());
      return poll();
    }
    function reconnect() {
      if (!current) return Promise.resolve();
      halt(); failures = 0; finished = false;
      return poll();
    }
    return { start: start, restore: restore, reconnect: reconnect, snapshot: snapshot, stop: halt,
      request: request };
  }

  var api = { create: create, createRequest: createRequest };
  root.GAWorldPopulationRuntime = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
