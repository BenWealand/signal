export const config = { runtime: "edge" };

function env(name) {
  try {
    return (typeof process !== "undefined" && process.env && process.env[name]) || "";
  } catch {
    return "";
  }
}

function parseImageField(value) {
  if (!value) return {};
  if (typeof value === "object") return value;
  try {
    return JSON.parse(value);
  } catch {
    return {};
  }
}

function safeExternalImageUrl(value) {
  const raw = String(value || "").trim();
  try {
    const url = new URL(raw);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : "";
  } catch {
    return "";
  }
}

async function imageUrlFromSupabase(articleId) {
  const supabaseUrl = String(env("VITE_SUPABASE_URL") || env("SUPABASE_URL") || "").replace(/\/$/, "");
  const anonKey = env("VITE_SUPABASE_ANON_KEY") || env("SUPABASE_ANON_KEY") || "";
  if (!supabaseUrl || !anonKey) return "";

  const endpoint = new URL(`${supabaseUrl}/rest/v1/generated_articles`);
  endpoint.searchParams.set("id", `eq.${articleId}`);
  endpoint.searchParams.set("select", "image");
  endpoint.searchParams.set("limit", "1");
  const response = await fetch(endpoint, {
    headers: {
      apikey: anonKey,
      Authorization: `Bearer ${anonKey}`,
      Accept: "application/json",
    },
  });
  if (!response.ok) return "";
  const rows = await response.json();
  const image = parseImageField(Array.isArray(rows) ? rows[0]?.image : null);
  return safeExternalImageUrl(image?.url || image?.src || "");
}

async function imageUrlFromApi(articleId) {
  const apiBase = String(env("VITE_SIGNAL_API_URL") || env("SIGNAL_API_URL") || "").replace(/\/$/, "");
  if (!apiBase) return "";
  try {
    const response = await fetch(`${apiBase}/generated-articles/${encodeURIComponent(articleId)}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return "";
    const article = await response.json();
    const image = parseImageField(article?.image);
    return safeExternalImageUrl(image?.url || image?.src || "");
  } catch {
    return "";
  }
}

async function loadImageUrl(articleId) {
  try {
    const fromSupabase = await imageUrlFromSupabase(articleId);
    if (fromSupabase) return fromSupabase;
  } catch {
    // Fall through to the backend API.
  }
  return imageUrlFromApi(articleId);
}

export default async function handler(request) {
  if (request.method && request.method !== "GET" && request.method !== "HEAD") {
    return new Response(JSON.stringify({ detail: "Method not allowed" }), {
      status: 405,
      headers: { "content-type": "application/json; charset=utf-8", allow: "GET, HEAD" },
    });
  }

  const requestUrl = new URL(request.url);
  const articleId = String(requestUrl.searchParams.get("id") || "").trim();
  if (!articleId) return new Response("Article id is required", { status: 400 });

  const sourceUrl = await loadImageUrl(articleId);
  if (!sourceUrl) return new Response("Article image not found", { status: 404 });

  let upstream;
  try {
    upstream = await fetch(sourceUrl, {
      headers: {
        Accept: "image/avif,image/webp,image/png,image/jpeg,image/*,*/*;q=0.8",
        "User-Agent": "Signal-Dispatch-Link-Preview/1.0",
      },
      redirect: "follow",
    });
  } catch {
    return new Response("Article image unavailable", { status: 502 });
  }
  const contentType = String(upstream.headers.get("content-type") || "").toLowerCase();
  if (!upstream.ok || !contentType.startsWith("image/")) {
    return new Response("Article image unavailable", { status: 502 });
  }

  return new Response(request.method === "HEAD" ? null : upstream.body, {
    status: 200,
    headers: {
      "content-type": contentType,
      "cache-control": "public, s-maxage=86400, stale-while-revalidate=604800",
      "access-control-allow-origin": "*",
      "x-content-type-options": "nosniff",
    },
  });
}
