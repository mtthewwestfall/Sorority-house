// Service worker for the installed house: it only ever caches the shell that is
// shipped with the site. Conversations, the roster and everything else the API
// answers are left alone, so an installed copy can never show a stale girl or a
// stale message. Bump SHELL on every shell change to retire the old copy.
const SHELL = 'house-shell-v18';
const SHELL_FILES = [
  './',
  './index.html',
  './godprint.html',
  './manifest.webmanifest',
  './assets/icon-192.png',
  './assets/icon-512.png',
  './assets/icon-maskable-512.png',
  './assets/apple-touch-icon.png',
  './assets/favicon-32.png'
];

self.addEventListener('install', (event) => {
  // A missing file must not sink the install, so each one is added on its own.
  event.waitUntil(
    caches.open(SHELL)
      .then((cache) => Promise.all(SHELL_FILES.map((f) => cache.add(f).catch(() => {}))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// One normalized cache key per page: search and hash are stripped so
// ?utm tags and #anchors share the page's entry, but two different pages
// can never overwrite each other.
function pageKey(request) {
  const key = new URL(request.url);
  key.search = '';
  key.hash = '';
  return key.toString();
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  // The API, Stripe, Shopify and the girls' generated pictures stay live.
  if (url.origin !== self.location.origin) return;

  // The page itself comes from the network first so a deploy lands immediately,
  // and from the cache only when the network is gone. Each page is cached under
  // its own key; the home page is the generic offline fallback.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          // Only a page that actually loaded is worth keeping; a 404 or a 502 is
          // passed through but never becomes the copy we open offline.
          if (response.ok) {
            const copy = response.clone();
            caches.open(SHELL).then((cache) => cache.put(pageKey(request), copy)).catch(() => {});
          }
          return response;
        })
        .catch(() => {
          const key = pageKey(request);
          return caches.match(key, { ignoreSearch: true })
            .then((hit) => hit || caches.match('./index.html', { ignoreSearch: true }))
            .then((hit) => hit || Response.error());
        })
    );
    return;
  }

  // Art and icons are content-stable: serve them from the cache and refill it in
  // the background when they are new.
  event.respondWith(
    caches.match(request).then((hit) => {
      if (hit) return hit;
      return fetch(request).then((response) => {
        if (response.ok && response.type === 'basic') {
          const copy = response.clone();
          caches.open(SHELL).then((cache) => cache.put(request, copy)).catch(() => {});
        }
        return response;
      });
    })
  );
});
