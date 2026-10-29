const CACHE_NAME = "financas-ia-v1";
const STATIC_ASSETS = [
    "/",
    "/login",
    "/static/manifest.json",
    "/static/icons/icon-192x192.png",
    "/static/icons/icon-512x512.png",
    "/static/account-menu.css",
    "/static/account-menu.js",
    "/static/dashboard.css",
    "/static/dashboard.js",
    "/static/reconciliation.css",
    "/static/reconciliation.js"
];

self.addEventListener("install", event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

self.addEventListener("activate", event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
            )
        )
    );
    self.clients.claim();
});

self.addEventListener("fetch", event => {
    if (event.request.method !== "GET") return;

    event.respondWith(
        caches.match(event.request).then(cached => {
            if (cached) return cached;

            return fetch(event.request)
                .then(response => {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then(cache => {
                        if (response.status === 200 && response.type === "basic") {
                            cache.put(event.request, clone);
                        }
                    });
                    return response;
                })
                .catch(() => {
                    if (event.request.mode === "navigate") {
                        return new Response(
                            "<h1>Finanças IA</h1><p>Você está offline. Conecte-se à internet para continuar.</p>",
                            { headers: { "Content-Type": "text/html" } }
                        );
                    }
                });
        })
    );
});
