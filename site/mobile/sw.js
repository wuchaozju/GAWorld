/* App-shell cache so the client opens without signal.
 *
 * Without this, losing signal means the page will not load at all and the
 * IndexedDB offline queue never gets a chance to work — the queue only helps
 * if the app can start.
 *
 * Bump CACHE_NAME on every shell change. A stale cached bundle is the classic
 * service-worker failure, so the shell list is kept short and explicit rather
 * than pattern-matched.
 */
const CACHE_NAME = "gaworld-twin-v5";
const SHELL = [
  "./",
  "./index.html",
  "./styles.css",
  "./core.js?v=5",
  "./app.js?v=5",
  "./manifest.webmanifest",
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) { return cache.addAll(SHELL); })
  );
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(names.map(function (name) {
        return name === CACHE_NAME ? null : caches.delete(name);
      }));
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", function (event) {
  const url = new URL(event.request.url);
  /* API calls must never be served from cache: a cached snapshot would show a
   * stale position as if it were current, which is exactly what the spec's
   * "not synced" state exists to prevent. */
  if (url.pathname.startsWith("/api/")) {
    return;
  }
  event.respondWith(
    caches.match(event.request).then(function (hit) {
      return hit || fetch(event.request);
    })
  );
});
