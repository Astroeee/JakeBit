// Jakebit service worker.
// It keeps the app's own files (styles, scripts, icons) ready so the app opens fast, and shows a friendly
// page when there is no connection. Pages with personal data are never stored: they always come from the server.
const VERSION = "jakebit-v1";
const STATIC = `${VERSION}-static`;
const SHELL = ["/offline", "/static/css/style.css", "/static/js/script.js", "/static/icons/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(STATIC).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => !key.startsWith(VERSION)).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;                       // forms and logins always go to the server
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/static/")) {                  // app files: show the saved copy, refresh it in the background
    event.respondWith(
      caches.open(STATIC).then(async (cache) => {
        const saved = await cache.match(request);
        const fresh = fetch(request)
          .then((response) => { if (response.ok) cache.put(request, response.clone()); return response; })
          .catch(() => saved);
        return saved || fresh;
      })
    );
    return;
  }

  if (request.mode === "navigate") {                          // pages: network first, offline page as the fallback
    event.respondWith(fetch(request).catch(() => caches.match("/offline")));
  }
});
