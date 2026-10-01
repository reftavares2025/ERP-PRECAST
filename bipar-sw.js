// Service worker do Bipar — cache mínimo pra permitir instalação como
// app (PWA) e abrir offline pra tela de bipagem, mesmo sem internet no
// galpão. Não faz cache de dados de peça (isso sempre precisa de rede).
const CACHE_NAME = "bipar-v1";
const CORE_ASSETS = ["/bipar"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  // API calls sempre vao pra rede (nunca cache de dados). So a casca do
  // app (HTML/manifest) usa cache-first pra abrir rapido/offline.
  if (event.request.url.includes("/api/")) return;

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
