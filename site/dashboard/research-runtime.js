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
  var exported = { createLogStream: createLogStream };
  if (typeof module !== "undefined" && module.exports) module.exports = exported;
  root.GAResearchRuntime = exported;
})(typeof window !== "undefined" ? window : globalThis);
