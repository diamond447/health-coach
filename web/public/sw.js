// Healthstats Service Worker
//
// App shell: index.html, the hashed JS chunks of this build (listed by the Vite build in
// PRECACHE_ASSETS), the manifest and icons are cached on install, so every screen works
// offline from the first visit. Cache-first; a new build gets a new cache.
//
// API: network-first. A copy of each successful GET is kept for API_MAX_AGE_MS and at
// most API_MAX_ENTRIES responses, only as a fallback while offline; older copies are
// never served and are deleted. Health data is not kept indefinitely.
const VERSION = "__BUILD_VERSION__";
const SHELL_CACHE = `healthstats-shell-${VERSION}`;
const API_CACHE = `healthstats-api-${VERSION}`;
const API_MAX_AGE_MS = 12 * 60 * 60 * 1000;
const API_MAX_ENTRIES = 60;
const CACHED_AT = "x-sw-cached-at";

// Replaced by the build with a JSON list of /assets/... files; empty in development.
const PRECACHE_JSON = "__PRECACHE_ASSETS__";
const PRECACHE_ASSETS = PRECACHE_JSON.startsWith("[") ? JSON.parse(PRECACHE_JSON) : [];
const APP_SHELL = [
  "/",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-maskable-192.png",
  "/icons/icon-maskable-512.png",
  "/icons/apple-touch-icon.png",
  ...PRECACHE_ASSETS,
];

// Only a plain same-origin 200 is worth keeping: behind the auth proxy an expired session
// answers with a redirect to the login page, which must not end up in the cache.
function cacheable(response) {
  return response.ok && response.type === "basic" && !response.redirected;
}

async function precache() {
  const cache = await caches.open(SHELL_CACHE);
  await Promise.all(
    APP_SHELL.map(async (url) => {
      try {
        const request = new Request(new URL(url, self.location.origin), {
          redirect: "manual",
          cache: "reload",
        });
        const response = await fetch(request);
        if (cacheable(response)) await cache.put(url, response);
      } catch {
        // Offline or blocked: the runtime cache below fills it in later.
      }
    }),
  );
}

function isFresh(response, now) {
  const cachedAt = Number(response.headers.get(CACHED_AT));
  return Number.isFinite(cachedAt) && cachedAt > 0 && now - cachedAt <= API_MAX_AGE_MS;
}

async function trimApiCache(now) {
  const cache = await caches.open(API_CACHE);
  const entries = [];
  for (const request of await cache.keys()) {
    const response = await cache.match(request);
    const cachedAt = response ? Number(response.headers.get(CACHED_AT)) || 0 : 0;
    entries.push({ request, cachedAt });
  }
  entries.sort((a, b) => b.cachedAt - a.cachedAt);
  await Promise.all(
    entries
      .filter((e, i) => i >= API_MAX_ENTRIES || now - e.cachedAt > API_MAX_AGE_MS)
      .map((e) => cache.delete(e.request)),
  );
}

async function storeApiResponse(request, response, now) {
  const headers = new Headers(response.headers);
  headers.set(CACHED_AT, String(now));
  const body = await response.blob();
  const cache = await caches.open(API_CACHE);
  await cache.put(
    request,
    new Response(body, { status: response.status, statusText: response.statusText, headers }),
  );
  await trimApiCache(now);
}

async function apiNetworkFirst(event) {
  const now = Date.now();
  try {
    const response = await fetch(event.request);
    const contentType = response.headers.get("content-type") || "";
    if (cacheable(response) && contentType.includes("application/json")) {
      event.waitUntil(storeApiResponse(event.request, response.clone(), now));
    }
    return response;
  } catch {
    const cache = await caches.open(API_CACHE);
    const cached = await cache.match(event.request);
    if (cached && isFresh(cached, now)) return cached;
    if (cached) await cache.delete(event.request);
    return new Response(JSON.stringify({ error: "Offline" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
  }
}

async function navigationNetworkFirst(event) {
  try {
    const response = await fetch(event.request);
    if (cacheable(response)) {
      const copy = response.clone();
      event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.put("/", copy)));
    }
    return response;
  } catch {
    const cached = await caches.match("/", { cacheName: SHELL_CACHE });
    return cached || Response.error();
  }
}

async function shellCacheFirst(event) {
  const cached = await caches.match(event.request, { cacheName: SHELL_CACHE });
  if (cached) return cached;
  const response = await fetch(event.request);
  if (cacheable(response) && event.request.method === "GET") {
    const copy = response.clone();
    event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.put(event.request, copy)));
  }
  return response;
}

self.addEventListener("install", (event) => {
  event.waitUntil(precache());
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== SHELL_CACHE && key !== API_CACHE)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => trimApiCache(Date.now())),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || event.request.method !== "GET") {
    return; // writes and other origins go straight to the network
  }
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(apiNetworkFirst(event));
  } else if (event.request.mode === "navigate") {
    event.respondWith(navigationNetworkFirst(event));
  } else {
    event.respondWith(shellCacheFirst(event));
  }
});
