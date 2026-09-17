// God's Companions service worker: network-first for the same-origin app
// shell, so pages never go stale; the cache is only a fallback for offline
// startup. API traffic lives on another origin and is never intercepted.
const CACHE = 'gods-companions-v1';
const SHELL = ['/', '/manifest.webmanifest'];
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return;
  event.respondWith(
    fetch(event.request).then((res) => {
      if (res && res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(event.request, copy)).catch(() => {});
      }
      return res;
    }).catch(() => caches.match(event.request).then((hit) => hit || caches.match('/')))
  );
});
