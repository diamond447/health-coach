/**
 * The service worker (public/sw.js) run against in-memory fakes of the cache and fetch
 * APIs: what it precaches, and that API copies expire.
 */
import { readFileSync } from "fs";
import { resolve } from "path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const ORIGIN = "https://health.example.com";
const HOUR = 60 * 60 * 1000;

type Handler = (event: FakeEvent) => void;

class FakeCache {
  entries = new Map<string, Response>();
  key(req: RequestInfo | URL): string {
    if (typeof req === "string") return new URL(req, ORIGIN).href;
    if (req instanceof URL) return req.href;
    return req.url;
  }
  async put(req: RequestInfo, res: Response) {
    this.entries.set(this.key(req), res);
  }
  async match(req: RequestInfo) {
    const res = this.entries.get(this.key(req));
    return res ? res.clone() : undefined;
  }
  async keys() {
    return [...this.entries.keys()].map((url) => new Request(url));
  }
  async delete(req: RequestInfo) {
    return this.entries.delete(this.key(req));
  }
}

class FakeCaches {
  stores = new Map<string, FakeCache>();
  async open(name: string) {
    if (!this.stores.has(name)) this.stores.set(name, new FakeCache());
    return this.stores.get(name)!;
  }
  async keys() {
    return [...this.stores.keys()];
  }
  async delete(name: string) {
    return this.stores.delete(name);
  }
  async match(req: RequestInfo, opts?: { cacheName?: string }) {
    const names = opts?.cacheName ? [opts.cacheName] : [...this.stores.keys()];
    for (const name of names) {
      const hit = await this.stores.get(name)?.match(req);
      if (hit) return hit;
    }
    return undefined;
  }
  byPrefix(prefix: string): FakeCache {
    const name = [...this.stores.keys()].find((n) => n.startsWith(prefix));
    if (!name) throw new Error(`no cache ${prefix}`);
    return this.stores.get(name)!;
  }
}

class FakeEvent {
  response?: Promise<Response>;
  waits: Promise<unknown>[] = [];
  constructor(public request: Request | { url: string; method: string; mode: string }) {}
  respondWith(p: Promise<Response>) {
    this.response = p;
  }
  waitUntil(p: Promise<unknown>) {
    this.waits.push(p);
  }
  async settled() {
    const res = await this.response;
    await Promise.all(this.waits);
    return res;
  }
}

function basic(body: string, init: ResponseInit = {}, redirected = false): Response {
  const res = new Response(body, { status: 200, ...init });
  Object.defineProperty(res, "type", { value: "basic" });
  Object.defineProperty(res, "redirected", { value: redirected });
  return res;
}

function json(body: unknown): Response {
  return basic(JSON.stringify(body), { headers: { "content-type": "application/json" } });
}

let handlers: Record<string, Handler>;
let caches: FakeCaches;
let fetchMock: ReturnType<typeof vi.fn>;

function loadWorker(assets: string[]) {
  const src = readFileSync(resolve(__dirname, "../public/sw.js"), "utf-8")
    .replace(/__BUILD_VERSION__/g, "test")
    .replace('"__PRECACHE_ASSETS__"', JSON.stringify(JSON.stringify(assets)));
  handlers = {};
  caches = new FakeCaches();
  fetchMock = vi.fn();
  const self = {
    location: { origin: ORIGIN },
    addEventListener: (type: string, fn: Handler) => (handlers[type] = fn),
    skipWaiting: () => undefined,
    clients: { claim: () => undefined },
  };
  new Function("self", "caches", "fetch", src)(self, caches, fetchMock);
}

async function get(path: string): Promise<Response | undefined> {
  const event = new FakeEvent(new Request(ORIGIN + path));
  handlers.fetch(event);
  return event.settled();
}

describe("service worker", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-04T08:00:00Z"));
    loadWorker(["/assets/index-abc.js", "/assets/TrendsScreen-def.js"]);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("precaches the shell and every built chunk, but not a login redirect", async () => {
    fetchMock.mockImplementation(async (req: Request) =>
      new URL(req.url, ORIGIN).pathname === "/"
        ? basic("<login>", {}, true) // expired session: proxy redirected to login
        : basic("ok"),
    );
    const event = new FakeEvent({ url: ORIGIN + "/", method: "GET", mode: "navigate" });
    handlers.install(event);
    await event.settled();
    const shell = caches.byPrefix("healthstats-shell-test");
    const cached = [...shell.entries.keys()].map((u) => new URL(u).pathname);
    expect(cached).toContain("/assets/index-abc.js");
    expect(cached).toContain("/assets/TrendsScreen-def.js");
    expect(cached).toContain("/manifest.webmanifest");
    expect(cached).not.toContain("/");
    // Requests go out with redirect: "manual" so a redirect is never followed into cache
    expect(fetchMock.mock.calls.every(([req]) => req.redirect === "manual")).toBe(true);
  });

  it("serves API copies offline only while they are fresh", async () => {
    fetchMock.mockResolvedValueOnce(json({ recovery: 71 }));
    expect(await (await get("/api/recovery?date=2026-11-04"))!.json()).toEqual({ recovery: 71 });

    fetchMock.mockRejectedValue(new TypeError("offline"));
    vi.setSystemTime(Date.now() + 11 * HOUR);
    const offline = await get("/api/recovery?date=2026-11-04");
    expect(offline!.status).toBe(200);
    expect(await offline!.json()).toEqual({ recovery: 71 });

    vi.setSystemTime(Date.now() + 2 * HOUR); // 13 h after it was fetched
    const stale = await get("/api/recovery?date=2026-11-04");
    expect(stale!.status).toBe(503);
    expect(caches.byPrefix("healthstats-api-test").entries.size).toBe(0);
  });

  it("keeps a bounded number of API responses", async () => {
    fetchMock.mockImplementation(async () => json({ ok: true }));
    for (let i = 0; i < 70; i++) {
      vi.setSystemTime(Date.now() + 1000);
      await get(`/api/day?date=2026-01-${String(i).padStart(2, "0")}`);
    }
    const api = caches.byPrefix("healthstats-api-test");
    expect(api.entries.size).toBe(60);
    expect([...api.entries.keys()].some((u) => u.endsWith("date=2026-01-69"))).toBe(true);
    expect([...api.entries.keys()].some((u) => u.endsWith("date=2026-01-00"))).toBe(false);
  });

  it("leaves writes, errors and other origins alone", async () => {
    const put = new FakeEvent(new Request(ORIGIN + "/api/journal/entries", { method: "PUT" }));
    handlers.fetch(put);
    expect(put.response).toBeUndefined();
    const other = new FakeEvent(new Request("https://cdn.example.org/x.js"));
    handlers.fetch(other);
    expect(other.response).toBeUndefined();

    fetchMock.mockResolvedValueOnce(
      basic("{}", { status: 500, headers: { "content-type": "application/json" } }),
    );
    expect((await get("/api/day"))!.status).toBe(500);
    expect(caches.stores.get("healthstats-api-test")?.entries.size ?? 0).toBe(0);
  });

  it("drops caches of older versions on activate", async () => {
    await caches.open("healthstats-oldversion");
    await caches.open("healthstats-api-older");
    const event = new FakeEvent({ url: ORIGIN + "/", method: "GET", mode: "navigate" });
    handlers.activate(event);
    await event.settled();
    expect(await caches.keys()).toEqual(["healthstats-api-test"]);
  });
});
