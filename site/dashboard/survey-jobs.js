/* Safe HTTP reads and reconnectable progress tracking; never replay a run POST. */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GAWorldSurveyJobs = api;
})(globalThis, function () {
  "use strict";

  function transient(status) {
    return [408, 425, 429, 500, 502, 503, 504].indexOf(status) >= 0;
  }

  function createClient(options) {
    var delay = options.delay || function (ms) {
      return new Promise(function (resolve) { setTimeout(resolve, ms); });
    };
    async function once(method, path, body) {
      var controller = new AbortController();
      var timer = setTimeout(function () { controller.abort(); }, options.timeoutMs || 20000);
      try {
        var response = await options.fetch(path, {
          method: method, signal: controller.signal,
          headers: { "Content-Type": "application/json" },
          body: body ? JSON.stringify(body) : undefined,
        });
        var payload;
        try { payload = await response.json(); }
        catch (_) {
          return { error: "HTTP " + response.status, httpStatus: response.status,
            retryable: response.ok || transient(response.status) };
        }
        if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
          return { error: "Invalid JSON response", httpStatus: response.status,
            retryable: response.ok || transient(response.status) };
        }
        if (response.ok) return payload;
        return { error: payload && payload.error || "HTTP " + response.status,
          httpStatus: response.status, retryable: transient(response.status) };
      } catch (error) {
        return { error: error.message || String(error), httpStatus: 0, retryable: true };
      } finally {
        clearTimeout(timer);
      }
    }
    return async function (method, path, body) {
      for (var attempt = 0; ; attempt++) {
        var result = await once(method, path, body);
        if (method !== "GET" || !result || !result.retryable || attempt >= 2) return result;
        await delay(1000 * Math.pow(2, attempt));
      }
    };
  }

  function followJob(options) {
    var stopped = false, timer = null, failures = 0, progress = 0;
    var schedule = options.setTimer || setTimeout;
    var cancel = options.clearTimer || clearTimeout;
    function stop() {
      stopped = true;
      if (timer !== null) cancel(timer);
    }
    async function tick() {
      var job;
      try { job = await options.request("GET", "/api/interview/jobs/" + encodeURIComponent(options.jobId)); }
      catch (error) { job = { error: error.message, retryable: true }; }
      if (stopped) return;
      if (job && job.retryable) {
        failures++;
        options.onRetry(progress);
        timer = schedule(tick, Math.min(30000, 1000 * Math.pow(2, Math.min(failures - 1, 5))));
        return;
      }
      if (!job || job.error || !job.status || job.status === "error" || job.status === "failed") {
        stop();
        options.onFail(job && (job.message || (typeof job.error === "string" && job.error)) || "Unknown job");
        return;
      }
      failures = 0;
      if (job.status === "running") {
        progress = Number(job.progress) || 0;
        options.onProgress(job);
        timer = schedule(tick, 1500);
      } else if (job.status === "done" && job.result) {
        stop();
        options.onDone(job.result);
      } else {
        stop();
        options.onFail("Unknown job status");
      }
    }
    return { stop: stop, ready: tick() };
  }

  return { createClient: createClient, followJob: followJob };
});
