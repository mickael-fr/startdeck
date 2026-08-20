/* Service worker — Révision Permis C
   Stratégie :
   - App shell (HTML, icônes, manifeste) : mis en cache à l'installation.
   - Navigation : network-first avec repli sur le cache (donc mise à jour auto quand il y a du réseau,
     et fonctionnement complet hors ligne sinon).
   - Polices Google : cache-first en arrière-plan (l'app reste lisible sans elles).
   Pour publier une nouvelle version : incrémenter CACHE_VERSION ci-dessous. */

const CACHE_VERSION = "permis-c-v6";
const CORE = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./icon-192.png",
  "./icon-512.png",
  "./icon-maskable-512.png",
  "./apple-touch-icon.png",
  "./oral-1.mp3"
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then(cache =>
      // addAll échoue en bloc si une seule ressource manque : on tolère les absences
      Promise.all(CORE.map(url =>
        cache.add(new Request(url, { cache: "reload" })).catch(() => null)
      ))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE_VERSION).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", event => {
  if (event.data === "skipWaiting") self.skipWaiting();
});

self.addEventListener("fetch", event => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  const sameOrigin = url.origin === self.location.origin;

  // Navigation (ouverture de l'app) : réseau d'abord, cache en secours
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then(res => {
          const copy = res.clone();
          caches.open(CACHE_VERSION).then(c => c.put("./index.html", copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match("./index.html").then(r => r || caches.match("./")))
    );
    return;
  }

  // Ressources internes : cache d'abord
  if (sameOrigin) {
    event.respondWith(
      caches.match(req).then(hit =>
        hit || fetch(req).then(res => {
          if (res && res.status === 200) {
            const copy = res.clone();
            caches.open(CACHE_VERSION).then(c => c.put(req, copy)).catch(() => {});
          }
          return res;
        }).catch(() => hit)
      )
    );
    return;
  }

  // Externe (polices Google) : cache d'abord, sinon réseau, sinon on laisse tomber sans casser l'app
  event.respondWith(
    caches.match(req).then(hit =>
      hit || fetch(req).then(res => {
        if (res && (res.status === 200 || res.type === "opaque")) {
          const copy = res.clone();
          caches.open(CACHE_VERSION).then(c => c.put(req, copy)).catch(() => {});
        }
        return res;
      }).catch(() => hit || Response.error())
    )
  );
});
