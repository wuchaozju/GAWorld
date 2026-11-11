/* Independent log polling: card re-renders do not lose cursors or buffers. */
(function (root) {
  "use strict";
  function createLogStream(options) {
    var schedule = options.setTimer || setTimeout;
    var cancel = options.clearTimer || clearTimeout;
    var update = options.onUpdate || function () {};
    var hidden = options.isHidden || function () { return false; };
    var timer = null;
    var generation = 0;
    var study = "";
    var attempt = 0;
    var source = { seed: "", world: "", kind: "events" };
    var data = { text: "", sources: [], next_offset: 0, file_id: "", live: false, error: "" };
    function stop() {
      generation++;
      cancel(timer);
      timer = null;
    }
    function snapshot() { return Object.assign({}, data); }
    async function poll() {
      cancel(timer);
      timer = null;
      var token = generation;
      if (hidden()) {
        timer = schedule(poll, 15000);
        return;
      }
      var query = new URLSearchParams({ seed: source.seed == null ? "" : String(source.seed),
        world: source.world || "", kind: source.kind || "events", offset: String(data.next_offset), file_id: data.file_id });
      try {
        var chunk = await options.api("GET", "/api/research/studies/" + encodeURIComponent(study) + "/logs?" + query);
        if (token !== generation) return;
        data.text = ((chunk.reset ? "" : data.text) + (chunk.text || "")).slice(-160000);
        data.next_offset = chunk.next_offset || 0;
        data.file_id = chunk.file_id || "";
        data.sources = chunk.sources || [];
        data.live = !!chunk.live;
        data.error = "";
        data.missing = !!chunk.missing;
        update(snapshot());
        if (chunk.has_more || chunk.live) timer = schedule(poll, chunk.has_more ? 100 : 1500);
      } catch (err) {
        if (token !== generation) return;
        data.error = err.message;
        update(snapshot());
        // A live source may be between registration and file creation.
        if (data.live) timer = schedule(poll, 3000);
      }
    }
    function activate(id, nextAttempt, live) {
      if (id === study && nextAttempt === attempt) {
        if (live && !data.live) { data.live = true; return poll(); }
        update(snapshot());
        return Promise.resolve();
      }
      stop();
      study = id;
      attempt = nextAttempt;
      source = { seed: "", world: "", kind: "events" };
      data = { text: "", sources: [], next_offset: 0, file_id: "", live: true, error: "" };
      return poll();
    }
    function select(next) {
      stop();
      source = next;
      data = Object.assign({}, data, { text: "", next_offset: 0, file_id: "", error: "" });
      return poll();
    }
    function refresh() { stop(); return poll(); }
    return { activate: activate, select: select, snapshot: snapshot, stop: stop, refresh: refresh };
  }
  function createRequest(options) {
    var send = options.fetch || root.fetch.bind(root);
    return function (method, path, body) {
      var controller = new AbortController();
      var timer;
      var request = (async function () {
        var res = await send(path, { method: method, signal: controller.signal,
          headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
        var data;
        try { data = await res.json(); }
        catch (_) { throw Object.assign(new Error("HTTP " + res.status), { status: res.status }); }
        if (!res.ok) throw Object.assign(new Error((data && data.error) || "HTTP " + res.status), { status: res.status });
        return data;
      })();
      var deadline = new Promise(function (_, reject) {
        timer = setTimeout(function () {
          reject(Object.assign(new Error(options.timeoutMessage || "Request timed out"), { code: "timeout" }));
          controller.abort();
        }, options.timeoutMs || 20000);
      });
      return Promise.race([request, deadline]).finally(function () { clearTimeout(timer); });
    };
  }

  // Only GETs are retried. A lost POST response must never create a second run.
  function createJobTracker(options) {
    var schedule = options.setTimer || setTimeout;
    var cancel = options.clearTimer || clearTimeout;
    var generation = 0, timer = null, failures = 0, current = null;
    function storage(method, value) {
      try { return options.storage && options.storage[method](options.storageKey, value); } catch (_) { return null; }
    }
    function stop() { generation++; cancel(timer); timer = null; }
    async function poll() {
      var token = generation;
      cancel(timer); timer = null;
      var job;
      try {
        if (!current.id) {
          var context = await options.api("GET", "/api/research/context?request_id=" + encodeURIComponent(current.request_id));
          if (token !== generation) return;
          var matched = (context.jobs || []).find(function (item) {
            return item.request_id === current.request_id && item.kind === current.kind;
          });
          if (!matched) throw Object.assign(new Error(options.missingMessage || "Submission was not found. Please submit again."), { status: 404 });
          current.id = matched.id;
          storage("setItem", JSON.stringify(current));
        }
        job = await options.api("GET", "/api/research/jobs/" + encodeURIComponent(current.id));
      } catch (error) {
        if (token !== generation) return;
        if (error.status && error.status >= 400 && error.status < 500 && error.status !== 408 && error.status !== 429) {
          storage("removeItem"); current = null;
          options.onError(error); return;
        }
        failures++;
        options.onUpdate({ status: "running", reconnecting: true, message: error.message });
        timer = schedule(poll, Math.min(15000, 1500 * Math.pow(2, Math.min(failures, 4))));
        return;
      }
      if (token !== generation) return;
      failures = 0;
      options.onUpdate(job);
      if (job.status === "running") {
        timer = schedule(poll, options.isHidden && options.isHidden() ? 15000 : 1500);
      } else {
        var kind = current.kind;
        if (kind !== "digest" || job.status !== "done") storage("removeItem");
        current = null;
        if (job.status === "done") await options.onDone(job, kind);
        else options.onError(new Error(job.message || "Task failed"));
      }
    }
    function watch(id, kind) {
      stop(); failures = 0; current = { id: id, kind: kind, request_id: current && current.kind === kind ? current.request_id : undefined };
      storage("setItem", JSON.stringify(current));
      return poll();
    }
    async function restore() {
      var saved = current;
      if (!saved) {
        try { saved = JSON.parse(storage("getItem") || "null"); } catch (_) { storage("removeItem"); }
      }
      if (!saved || (!saved.id && !saved.request_id) || !saved.kind) return false;
      stop(); current = saved; failures = 0;
      await poll(); return true;
    }
    function begin(kind) {
      stop();
      var id = root.crypto && root.crypto.randomUUID ? root.crypto.randomUUID() : Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
      current = { kind: kind, request_id: id };
      storage("setItem", JSON.stringify(current));
      return id;
    }
    function discard() { stop(); current = null; storage("removeItem"); }
    return { watch: watch, restore: restore, stop: stop, begin: begin, discard: discard };
  }

  var exported = { createLogStream: createLogStream, createRequest: createRequest, createJobTracker: createJobTracker };
  if (typeof module !== "undefined" && module.exports) module.exports = exported;
  root.GAResearchRuntime = exported;
})(typeof window !== "undefined" ? window : globalThis);
