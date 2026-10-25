/**
 * API client with session expiry detection, offline fallback, and error handling.
 */

export interface ApiResult<T> {
  data: T | null;
  error: string | null;
  asOf: string | null;
  isOffline: boolean;
  sessionExpired: boolean;
}

type Listener = () => void;

class ApiState {
  sessionExpired: boolean = false;
  isOffline: boolean = false;
  offlineAsOf: string | null = null;
  private listeners: Set<Listener> = new Set();

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  notify(): void {
    this.listeners.forEach((l) => l());
  }

  setSessionExpired(val: boolean): void {
    if (this.sessionExpired !== val) {
      this.sessionExpired = val;
      this.notify();
    }
  }

  setOffline(offline: boolean, asOf?: string | null): void {
    let changed = false;
    if (this.isOffline !== offline) {
      this.isOffline = offline;
      changed = true;
    }
    if (asOf !== undefined && this.offlineAsOf !== asOf) {
      this.offlineAsOf = asOf;
      changed = true;
    }
    if (changed) {
      this.notify();
    }
  }
}

export const apiState = new ApiState();

// Monitor online/offline events
if (typeof window !== "undefined") {
  window.addEventListener("online", () => {
    apiState.setOffline(false);
  });
  window.addEventListener("offline", () => {
    apiState.setOffline(true);
  });
}

const CACHE_PREFIX = "healthstats_cache_";

/**
 * Fetch a JSON API endpoint with error and session expiry handling.
 */
export async function apiFetch<T>(path: string): Promise<ApiResult<T>> {
  const cacheKey = CACHE_PREFIX + path;

  try {
    const res = await fetch(path, {
      headers: {
        Accept: "application/json",
      },
    });

    // Check for session expiry: 401, 403, or redirect
    if (res.status === 401 || res.status === 403 || res.redirected) {
      apiState.setSessionExpired(true);
      return {
        data: null,
        error: "Přihlášení vypršelo",
        asOf: null,
        isOffline: false,
        sessionExpired: true,
      };
    }

    const contentType = res.headers.get("content-type") || "";
    // If the proxy intercepted with an HTML login page or non-JSON response
    if (!contentType.includes("application/json")) {
      // If status is ok or redirect to html, it's proxy login
      apiState.setSessionExpired(true);
      return {
        data: null,
        error: "Přihlášení vypršelo",
        asOf: null,
        isOffline: false,
        sessionExpired: true,
      };
    }

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }

    const json = (await res.json()) as T & { as_of?: string };
    apiState.setOffline(false);

    // Save to local storage for offline fallback
    try {
      localStorage.setItem(
        cacheKey,
        JSON.stringify({
          data: json,
          cachedAt: new Date().toISOString(),
          asOf: json.as_of || null,
        })
      );
    } catch {
      // localStorage may be full or disabled; ignore
    }

    return {
      data: json,
      error: null,
      asOf: json.as_of || null,
      isOffline: false,
      sessionExpired: false,
    };
  } catch (err: unknown) {
    // Network failure or offline
    apiState.setOffline(true);

    // Try fallback from localStorage
    try {
      const cached = localStorage.getItem(cacheKey);
      if (cached) {
        const parsed = JSON.parse(cached);
        apiState.setOffline(true, parsed.asOf);
        return {
          data: parsed.data as T,
          error: null,
          asOf: parsed.asOf || null,
          isOffline: true,
          sessionExpired: false,
        };
      }
    } catch {
      // Ignore cache parse errors
    }

    return {
      data: null,
      error: err instanceof Error ? err.message : "Chyba sítě",
      asOf: null,
      isOffline: true,
      sessionExpired: false,
    };
  }
}
