import { apiGet, hasApiBase } from "../api/client.js";
import { isSupabaseConfigured, supabase } from "./supabase.js";

const SESSION_CACHE_PREFIX = "signal-shared-article-v1:";

function parseJsonField(value, fallback) {
  if (value == null || value === "") return fallback;
  if (typeof value === "object") return value;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

/** Map a Postgres/Supabase generated_articles row to the API article shape. */
export function decodeGeneratedArticleRow(row) {
  if (!row || typeof row !== "object") return null;
  const id = row.id;
  if (!id) return null;
  return {
    id,
    ownerUserId: row.owner_user_id ?? row.ownerUserId ?? null,
    source: row.source || "news-desk",
    tag: row.tag || "trend",
    trendUrl: row.trend_url || row.trendUrl || "",
    prompt: row.prompt || "",
    headline: row.headline || "",
    dek: row.dek || "",
    summary: row.summary || "",
    body: parseJsonField(row.body, []),
    facts: parseJsonField(row.facts, []),
    terms: parseJsonField(row.terms, []),
    sources: parseJsonField(row.sources, []),
    sourceLinks: parseJsonField(row.source_links ?? row.sourceLinks, []),
    consensus: parseJsonField(row.consensus, []),
    sourceCount: Number(row.source_count ?? row.sourceCount ?? 0) || 0,
    deniedForBias: Number(row.denied_for_bias ?? row.deniedForBias ?? 0) || 0,
    fairnessScore: Number(row.fairness_score ?? row.fairnessScore ?? 0) || 0,
    accuracyScore: Number(row.accuracy_score ?? row.accuracyScore ?? 0) || 0,
    scoreMetadata: parseJsonField(row.score_metadata ?? row.scoreMetadata, {}),
    generation_mode: row.generation_mode || row.generationMode || "",
    source_quality: parseJsonField(row.source_quality ?? row.sourceQuality, {}),
    consensus_level: row.consensus_level || row.consensusLevel || "",
    used_live_sources: Boolean(row.used_live_sources ?? row.usedLiveSources),
    fallback_reason: row.fallback_reason || row.fallbackReason || "",
    section: String(row.section || "").toLowerCase(),
    status: row.status || "published",
    createdAt: row.created_at || row.createdAt || null,
  };
}

export function readArticleSessionCache(articleId) {
  try {
    const raw = window.sessionStorage.getItem(`${SESSION_CACHE_PREFIX}${articleId}`);
    if (!raw) return null;
    return decodeGeneratedArticleRow(JSON.parse(raw));
  } catch {
    return null;
  }
}

export function writeArticleSessionCache(article) {
  if (!article?.id) return;
  try {
    window.sessionStorage.setItem(`${SESSION_CACHE_PREFIX}${article.id}`, JSON.stringify(article));
  } catch {
    // Ignore quota / private-mode failures.
  }
}

export async function fetchArticleFromSupabase(articleId) {
  if (!isSupabaseConfigured || !articleId) return null;
  const { data, error } = await supabase
    .from("generated_articles")
    .select("*")
    .eq("id", articleId)
    .maybeSingle();
  if (error) throw error;
  return decodeGeneratedArticleRow(data);
}

async function fetchArticleFromApi(articleId) {
  if (!hasApiBase()) return null;
  return apiGet(`/generated-articles/${encodeURIComponent(articleId)}`);
}

async function fetchArticleFromStatic(articleId) {
  const response = await fetch(`/generated-articles.json?ts=${Date.now()}`);
  if (!response.ok) return null;
  const rows = await response.json();
  const match = Array.isArray(rows) ? rows.find((row) => String(row.id) === String(articleId)) : null;
  return match || null;
}

/**
 * Shared-link loader: Supabase PostgREST first (fast), then Render API, then static JSON.
 */
export async function fetchSharedArticle(articleId, { preferCache = true } = {}) {
  const id = String(articleId || "").trim();
  if (!id) throw new Error("Missing article id");

  if (preferCache) {
    const cached = readArticleSessionCache(id);
    if (cached?.headline) return { article: cached, source: "session-cache" };
  }

  if (isSupabaseConfigured) {
    try {
      const fromSupabase = await fetchArticleFromSupabase(id);
      if (fromSupabase?.headline) {
        writeArticleSessionCache(fromSupabase);
        return { article: fromSupabase, source: "supabase" };
      }
    } catch {
      // Fall through to API / static.
    }
  }

  try {
    const fromApi = await fetchArticleFromApi(id);
    if (fromApi?.headline || fromApi?.id) {
      writeArticleSessionCache(fromApi);
      return { article: fromApi, source: "api" };
    }
  } catch {
    // Fall through to static snapshot.
  }

  const fromStatic = await fetchArticleFromStatic(id);
  if (fromStatic) {
    writeArticleSessionCache(fromStatic);
    return { article: fromStatic, source: "static" };
  }

  throw new Error("Article not found");
}
