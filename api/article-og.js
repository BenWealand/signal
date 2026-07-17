import { parseJsonField, renderArticleOgHtml } from "./lib/articleOgHtml.js";

export const config = { runtime: "edge" };

const BOT_FALLBACK_TITLE = "Signal Dispatch";

function env(name) {
  try {
    return (typeof process !== "undefined" && process.env && process.env[name]) || "";
  } catch {
    return "";
  }
}

async function fetchGeneratedArticle(articleId) {
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
  const row = Array.isArray(rows) ? rows[0] : null;
  if (!row) return null;
  return {
    id: row.id,
    headline: row.headline || "",
    dek: row.dek || "",
    summary: row.summary || "",
    image: parseJsonField(row.image, {}),
    status: row.status || "published",
  };
}

export default async function handler(request) {
  const requestUrl = new URL(request.url);
  const articleId = String(requestUrl.searchParams.get("id") || "").trim();
  const origin = `${requestUrl.protocol}//${requestUrl.host}`;
  const pageUrl = articleId ? `${origin}/article/${encodeURIComponent(articleId)}` : origin;

  let article = {
    headline: BOT_FALLBACK_TITLE,
    dek: "Sourced reporting from Signal Dispatch.",
    image: {},
  };
  if (articleId) {
    try {
      const loaded = await fetchGeneratedArticle(articleId);
      if (loaded?.headline) article = loaded;
    } catch {
      // Keep fallback preview metadata.
    }
  }

  const html = renderArticleOgHtml(article, { pageUrl, siteName: BOT_FALLBACK_TITLE });
  return new Response(html, {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "public, s-maxage=300, stale-while-revalidate=86400",
    },
  });
}
