import {
  parseJsonField,
  injectShareMetaIntoHtml,
  renderArticleOgHtml,
} from "./lib/articleOgHtml.js";

export const config = { runtime: "edge" };

const SITE_NAME = "Signal Dispatch";
const DEFAULT_PUBLIC_ORIGIN = "https://signal-mocha-three.vercel.app";

function env(name) {
  try {
    return (typeof process !== "undefined" && process.env && process.env[name]) || "";
  } catch {
    return "";
  }
}

function publicOrigin(requestUrl) {
  const configured = String(
    env("VITE_PUBLIC_SITE_URL") || env("PUBLIC_SITE_URL") || env("PUBLIC_ARTICLE_BASE_URL") || "",
  ).replace(/\/$/, "");
  if (configured) return configured;

  const host = requestUrl.hostname || "";
  // Preview deployments are often SSO-protected; never advertise them as share URLs.
  if (host.endsWith(".vercel.app") && host !== "signal-mocha-three.vercel.app") {
    return DEFAULT_PUBLIC_ORIGIN;
  }
  return `${requestUrl.protocol}//${requestUrl.host}`;
}

function normalizeArticle(row) {
  if (!row || typeof row !== "object") return null;
  const id = row.id;
  const headline = row.headline || row.title || "";
  if (!id && !headline) return null;
  return {
    id,
    headline,
    dek: row.dek || "",
    summary: row.summary || "",
    image: parseJsonField(row.image, {}),
    status: row.status || "published",
  };
}

async function fetchFromSupabase(articleId) {
  const supabaseUrl = String(env("VITE_SUPABASE_URL") || env("SUPABASE_URL") || "").replace(/\/$/, "");
  const anonKey = env("VITE_SUPABASE_ANON_KEY") || env("SUPABASE_ANON_KEY") || "";
  if (!supabaseUrl || !anonKey || !articleId) return null;

  const endpoint = new URL(`${supabaseUrl}/rest/v1/generated_articles`);
  endpoint.searchParams.set("id", `eq.${articleId}`);
  endpoint.searchParams.set("select", "id,headline,dek,summary,image,status");
  endpoint.searchParams.set("limit", "1");

  const response = await fetch(endpoint.toString(), {
    headers: {
      apikey: anonKey,
      Authorization: `Bearer ${anonKey}`,
      Accept: "application/json",
    },
  });
  if (!response.ok) return null;
  const rows = await response.json();
  return normalizeArticle(Array.isArray(rows) ? rows[0] : null);
}

async function fetchFromStaticSnapshot(origin, articleId) {
  try {
    const response = await fetch(`${origin}/generated-articles.json?ts=${Date.now()}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return null;
    const rows = await response.json();
    const match = Array.isArray(rows)
      ? rows.find((row) => String(row?.id) === String(articleId))
      : null;
    return normalizeArticle(match);
  } catch {
    return null;
  }
}

async function fetchFromApi(articleId) {
  const apiBase = String(env("VITE_SIGNAL_API_URL") || env("SIGNAL_API_URL") || "").replace(/\/$/, "");
  if (!apiBase || !articleId) return null;
  try {
    const response = await fetch(`${apiBase}/generated-articles/${encodeURIComponent(articleId)}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return null;
    return normalizeArticle(await response.json());
  } catch {
    return null;
  }
}

async function loadArticle(articleId, requestOrigin) {
  if (!articleId) return null;
  const fromSupabase = await fetchFromSupabase(articleId);
  if (fromSupabase?.headline) return fromSupabase;
  const fromApi = await fetchFromApi(articleId);
  if (fromApi?.headline) return fromApi;
  const fromStatic = await fetchFromStaticSnapshot(requestOrigin, articleId);
  if (fromStatic?.headline) return fromStatic;
  return null;
}

async function loadSpaShell(requestOrigin) {
  for (const path of ["/index.html", "/"]) {
    try {
      const response = await fetch(`${requestOrigin}${path}`, {
        headers: { Accept: "text/html" },
      });
      if (!response.ok) continue;
      const html = await response.text();
      if (html.includes("id=\"root\"") || html.includes("id='root'")) return html;
    } catch {
      // Try the next candidate path.
    }
  }
  return "";
}

export default async function handler(request) {
  const requestUrl = new URL(request.url);
  const articleId = String(requestUrl.searchParams.get("id") || "").trim();
  const requestOrigin = `${requestUrl.protocol}//${requestUrl.host}`;
  const shareOrigin = publicOrigin(requestUrl);
  const pageUrl = articleId
    ? `${shareOrigin}/article/${encodeURIComponent(articleId)}`
    : shareOrigin;

  let article = {
    headline: SITE_NAME,
    dek: "Sourced reporting from Signal Dispatch.",
    image: {},
  };
  if (articleId) {
    try {
      const loaded = await loadArticle(articleId, requestOrigin);
      if (loaded?.headline) article = loaded;
    } catch {
      // Keep fallback preview metadata.
    }
  }

  const spaShell = await loadSpaShell(requestOrigin);
  const html = spaShell
    ? injectShareMetaIntoHtml(spaShell, article, { pageUrl, siteName: SITE_NAME })
    : renderArticleOgHtml(article, { pageUrl, siteName: SITE_NAME });

  return new Response(html, {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "public, s-maxage=60, stale-while-revalidate=86400",
    },
  });
}
