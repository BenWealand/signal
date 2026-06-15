export const API_BASE = import.meta.env.VITE_SIGNAL_API_URL || "";

export function hasApiBase() {
  return Boolean(API_BASE);
}

export async function apiGet(path) {
  if (!API_BASE) throw new Error("API is not configured for this build.");
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) throw new Error(`API request failed: ${path}`);
  return response.json();
}

export async function apiPost(path, payload) {
  if (!API_BASE) throw new Error("API is not configured for this build.");
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`API request failed: ${path}`);
  return response.json();
}

export async function getArticleProgress() {
  return apiGet("/articles/progress");
}
