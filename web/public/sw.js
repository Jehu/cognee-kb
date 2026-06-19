// Minimaler Service Worker: App-Shell-Cache, network-first für /api.
const CACHE = 'kb-shell-v7';
const SHELL = ['/', '/chat/', '/settings/', '/manifest.webmanifest', '/icons/icon.svg'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting())
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

  // /api immer network-first, nie cachen.
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(event.request));
    return;
  }

  // Navigationen: network-first. Eine redirected Response (z.B. /chat -> /chat/)
  // darf NICHT direkt an eine Navigation zurückgegeben werden — sonst bricht der
  // Browser ab. Daher neu verpacken; offline aus dem Shell-Cache bedienen.
  if (event.request.mode === 'navigate') {
    event.respondWith((async () => {
      try {
        const res = await fetch(event.request);
        if (res.redirected) {
          const body = await res.blob();
          return new Response(body, {
            status: res.status, statusText: res.statusText, headers: res.headers });
        }
        return res;
      } catch {
        return (await caches.match(event.request)) || (await caches.match('/'));
      }
    })());
    return;
  }

  // Statische Assets: cache-first, im Hintergrund aktualisieren.
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const fresh = fetch(event.request)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((cache) => cache.put(event.request, copy));
          }
          return res;
        })
        .catch(() => cached);
      return cached || fresh;
    })
  );
});
