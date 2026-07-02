export const API_BASE = import.meta.env.VITE_SIGNAL_API_URL || "";
let wakePromise = null;

export function hasApiBase() {
  return Boolean(API_BASE);
}

export async function apiGet(path) {
  if (!API_BASE) throw new Error("API is not configured for this build.");
  await ensureAwake(path);
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) throw await apiError(response, path);
  return response.json();
}

export async function apiPost(path, payload) {
  if (!API_BASE) throw new Error("API is not configured for this build.");
  await ensureAwake(path);
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw await apiError(response, path);
  return response.json();
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

  const error = new Error("Backend is still waking up. Try again in a moment.");
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
