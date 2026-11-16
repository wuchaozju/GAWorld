self.addEventListener?.("error", () => {});

(function () {
  if (!("serviceWorker" in navigator)) return;

  window.addEventListener("load", async () => {
    try {
      const registration = await navigator.serviceWorker.register("/css/fos/sw.js", {
        scope: "/css/fos/",
      });
      await registration.update();
    } catch {
      // Ignore registration failures on browsers with stale cached bootstrap code.
    }
  });
})();
