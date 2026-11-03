const CACHE_NAME = "financas-ia-v3";
const STATIC_ASSETS = [
    "/static/manifest.json",
    "/static/icons/icon-192x192.png",
    "/static/icons/icon-512x512.png",
    "/static/icons/icon-maskable-192x192.png",
    "/static/icons/icon-maskable-512x512.png",
    "/static/account-menu.css",
    "/static/account-menu.js",
    "/static/dashboard.css",
    "/static/dashboard.js",
    "/static/reconciliation.css",
    "/static/reconciliation.js",
];

// Instalação: cacheia apenas assets estáticos
self.addEventListener("install", event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

// Ativação: remove caches antigos
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

// Verifica se uma requisição é um asset estático cacheável
function isStaticAsset(url) {
    const pathname = new URL(url).pathname;
    return STATIC_ASSETS.includes(pathname);
}

// Resposta em caso de falha de navegação
function offlineResponse() {
    return new Response(
        "<!DOCTYPE html><html lang='pt-BR'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>Finanças IA</title><style>body{font-family:system-ui,sans-serif;background:#0b1119;color:#eef5fa;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;padding:20px;}</style></head><body><div><h1>📴 Sem conexão</h1><p>Você está offline. Conecte-se à internet para continuar.</p><button onclick='location.reload()' style='margin-top:20px;padding:10px 16px;border-radius:12px;border:none;background:#62e6ba;color:#09231d;font-weight:700;cursor:pointer;'>Tentar novamente</button></div></body></html>",
        { headers: { "Content-Type": "text/html" } }
    );
}

self.addEventListener("fetch", event => {
    if (event.request.method !== "GET") return;

    const url = new URL(event.request.url);

    // Assets estáticos: cache first, depois network
    if (isStaticAsset(event.request.url)) {
        event.respondWith(
            caches.match(event.request).then(cached => {
                if (cached) return cached;

                return fetch(event.request).then(response => {
                    if (response.status === 200 && response.type === "basic") {
                        const clone = response.clone();
                        caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                    }
                    return response;
                });
            })
        );
        return;
    }

    // Páginas/navegação: network first, cache apenas como fallback
    if (event.request.mode === "navigate" || url.pathname.startsWith("/")) {
        event.respondWith(
            fetch(event.request)
                .then(response => {
                    // Não cacheia páginas dinâmicas
                    return response;
                })
                .catch(() => {
                    // Se for navegação, mostra página offline
                    if (event.request.mode === "navigate") {
                        return offlineResponse();
                    }
                    // Para outros recursos, deixa falhar naturalmente
                    throw new Error("Network request failed");
                })
        );
        return;
    }
});
