import { supabase } from "../lib/supabase.js";

export const API_BASE = import.meta.env.VITE_SIGNAL_API_URL || "";
let wakePromise = null;
const getCache = new Map();
const STORAGE_PREFIX = "signal-cache-v1:";

export function hasApiBase() {
  return Boolean(API_BASE);
}

function readStoredEntry(path) {
  try {
    const raw = window.localStorage.getItem(`${STORAGE_PREFIX}${path}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || parsed.value === undefined) return null;
    return { value: parsed.value, expiresAt: Number(parsed.expiresAt) || 0 };
  } catch {
    return null;
  }
}

function writeStoredEntry(path, value, expiresAt) {
  try {
    window.localStorage.setItem(`${STORAGE_PREFIX}${path}`, JSON.stringify({ value, expiresAt }));
  } catch {
    // Storage may be full or unavailable; the in-memory cache still applies.
  }
}

function removeStoredEntry(path) {
  try {
    window.localStorage.removeItem(`${STORAGE_PREFIX}${path}`);
  } catch {
    // Ignore storage failures.
  }
}

export async function apiGet(path) {
  if (!API_BASE) throw new Error("API is not configured for this build.");
  await ensureAwake(path);
  const response = await fetch(`${API_BASE}${path}`, { headers: await authHeaders() });
  if (!response.ok) throw await apiError(response, path);
  return response.json();
}

export async function apiGetCached(path, { ttlMs = 5 * 60 * 1000 } = {}) {
  const now = Date.now();
  let cached = getCache.get(path);
  if (!cached || (cached.value === undefined && !cached.promise)) {
    const stored = readStoredEntry(path);
    if (stored) {
      cached = { ...(cached || {}), ...stored };
      getCache.set(path, cached);
    }
  }
  if (cached && cached.value !== undefined && cached.expiresAt > now) return cached.value;
  if (cached?.promise && cached.value === undefined) return cached.promise;

  const promise = apiGet(path)
    .then((value) => {
      getCache.set(path, { value, expiresAt: Date.now() + ttlMs });
      writeStoredEntry(path, value, Date.now() + ttlMs);
      return value;
    })
    .catch((error) => {
      if (cached?.value !== undefined) return cached.value;
      getCache.delete(path);
      throw error;
    });
  getCache.set(path, { ...(cached || {}), promise, expiresAt: cached?.expiresAt || 0 });

  // Stale-while-revalidate: serve the locally cached copy immediately while
  // the refresh continues in the background.
  if (cached?.value !== undefined) return cached.value;
  return promise;
}

export function invalidateApiCache(prefix = "") {
  for (const key of getCache.keys()) {
    if (!prefix || key.startsWith(prefix)) {
      getCache.delete(key);
      removeStoredEntry(key);
    }
  }
  if (prefix) {
    try {
      for (const storageKey of Object.keys(window.localStorage)) {
        if (storageKey.startsWith(`${STORAGE_PREFIX}${prefix}`)) {
          window.localStorage.removeItem(storageKey);
        }
      }
    } catch {
      // Ignore storage failures.
    }
  }
}

const PRELOAD_PATHS = [
  "/generated-articles",
  "/stories",
  "/news/trending?limit=18",
  "/news/trending-topics?limit=10",
  "/news/world?limit=18",
  "/news/politics?limit=18",
  "/news/markets?limit=18",
  "/news/technology?limit=18",
  "/news/climate?limit=18",
];

/**
 * Wake the backend (it sleeps after inactivity) and warm every reader-facing
 * feed so navigating to Latest, Trending, Saved, and section pages is instant.
 */
export function preloadSignalFeeds({ userId = null } = {}) {
  if (!API_BASE) return Promise.resolve([]);
  const paths = [...PRELOAD_PATHS];
  if (userId) paths.push(`/users/${userId}/saved`);
  return Promise.allSettled(paths.map((path) => apiGetCached(path, { ttlMs: 5 * 60 * 1000 })));
}

export async function apiPost(path, payload) {
  if (!API_BASE) throw new Error("API is not configured for this build.");
  await ensureAwake(path);
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw await apiError(response, path);
  return response.json();
}

async function authHeaders() {
  const { data } = await supabase.auth.getSession().catch(() => ({ data: {} }));
  const token = data?.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function apiPostAfterWake(path, payload) {
  return apiPost(path, payload);
}

export async function getArticleProgress() {
  return apiGet("/articles/progress");
}

async function wakeApi() {
  if (!API_BASE) return;
  const attempts = Number(import.meta.env.VITE_SIGNAL_WAKE_ATTEMPTS || 8);
  const timeoutMs = Number(import.meta.env.VITE_SIGNAL_WAKE_TIMEOUT_MS || 12000);
  const delayMs = Number(import.meta.env.VITE_SIGNAL_WAKE_DELAY_MS || 3500);
  let lastError = null;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${API_BASE}/health`, { signal: controller.signal });
      if (response.ok) return;
      lastError = await apiError(response, "/health");
    } catch (error) {
      lastError = error;
    } finally {
      window.clearTimeout(timeout);
    }
    if (attempt < attempts) {
      await new Promise((resolve) => window.setTimeout(resolve, delayMs));
    }
  }

  const error = new Error("The newsroom is still warming up — try again in a few seconds.");
  error.status = lastError?.status || 503;
  error.detail = error.message;
  throw error;
}

async function ensureAwake(path) {
  if (!API_BASE || path === "/health") return;
  if (!wakePromise) {
    wakePromise = wakeApi().finally(() => {
      wakePromise = null;
    });
  }
  await wakePromise;
}

async function apiError(response, path) {
  let detail = "";
  try {
    const payload = await response.json();
    detail = typeof payload.detail === "string"
      ? payload.detail
      : payload.detail?.message || JSON.stringify(payload.detail || payload);
  } catch {
    detail = await response.text().catch(() => "");
  }
  const error = new Error(detail || `API request failed: ${path}`);
  error.status = response.status;
  error.detail = detail;
  return error;
}
