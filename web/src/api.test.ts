// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiSend, apiState } from "./api";

describe("apiSend security and error handling", () => {
  beforeEach(() => {
    apiState.setSessionExpired(false);
    apiState.setOffline(false);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls fetch with redirect: manual and required headers", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      type: "basic",
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ status: "ok" }),
    } as unknown as Response);

    const res = await apiSend("PUT", "/api/journal/entries", { test: 1 });
    expect(fetchSpy).toHaveBeenCalledWith("/api/journal/entries", {
      method: "PUT",
      headers: {
        Accept: "application/json",
        "X-Healthstats": "1",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ test: 1 }),
      redirect: "manual",
    });
    expect(res.data).toEqual({ status: "ok" });
    expect(res.sessionExpired).toBe(false);
  });

  it("opaqueredirect response triggers session expired banner", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 0,
      type: "opaqueredirect",
      headers: new Headers(),
    } as unknown as Response);

    const res = await apiSend("PUT", "/api/journal/entries", {});
    expect(res.sessionExpired).toBe(true);
    expect(apiState.sessionExpired).toBe(true);
    expect(res.error).toBe("Přihlášení vypršelo");
  });

  it("401 Unauthorized triggers session expired banner", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 401,
      type: "basic",
      headers: new Headers({ "content-type": "application/json" }),
    } as unknown as Response);

    const res = await apiSend("PUT", "/api/journal/entries", {});
    expect(res.sessionExpired).toBe(true);
    expect(apiState.sessionExpired).toBe(true);
    expect(res.error).toBe("Přihlášení vypršelo");
  });

  it("403 Forbidden triggers session expired banner", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 403,
      type: "basic",
      headers: new Headers({ "content-type": "application/json" }),
    } as unknown as Response);

    const res = await apiSend("PUT", "/api/journal/entries", {});
    expect(res.sessionExpired).toBe(true);
    expect(apiState.sessionExpired).toBe(true);
    expect(res.error).toBe("Přihlášení vypršelo");
  });

  it("non-JSON 2xx/3xx response triggers session expired banner", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      type: "basic",
      headers: new Headers({ "content-type": "text/html" }),
      text: async () => "<html>Login</html>",
    } as unknown as Response);

    const res = await apiSend("PUT", "/api/journal/entries", {});
    expect(res.sessionExpired).toBe(true);
    expect(apiState.sessionExpired).toBe(true);
    expect(res.error).toBe("Přihlášení vypršelo");
  });

  it("5xx error returns save error line and NEVER session banner", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 500,
      type: "basic",
      headers: new Headers({ "content-type": "text/html" }),
      text: async () => "<html>Internal Server Error</html>",
    } as unknown as Response);

    const res = await apiSend("PUT", "/api/journal/entries", {});
    expect(res.sessionExpired).toBe(false);
    expect(apiState.sessionExpired).toBe(false);
    expect(res.error).toBe("Nepodařilo se uložit, zkus to znovu");
    expect(res.status).toBe(500);
  });

  it("503 Service Unavailable returns save error line and never session banner", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 503,
      type: "basic",
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ error: "journal_writes_disabled" }),
    } as unknown as Response);

    const res = await apiSend("PUT", "/api/journal/entries", {});
    expect(res.sessionExpired).toBe(false);
    expect(apiState.sessionExpired).toBe(false);
    expect(res.error).toBe("Nepodařilo se uložit, zkus to znovu");
    expect(res.status).toBe(503);
  });

  it("network error returns save error line and sets offline, NEVER session banner", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Network failure"));

    const res = await apiSend("PUT", "/api/journal/entries", {});
    expect(res.sessionExpired).toBe(false);
    expect(apiState.sessionExpired).toBe(false);
    expect(res.isOffline).toBe(true);
    expect(apiState.isOffline).toBe(true);
    expect(res.error).toBe("Nepodařilo se uložit, zkus to znovu");
  });
});
