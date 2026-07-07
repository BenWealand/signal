import { useEffect, useState } from "react";
import { apiGetCached, apiGetFresh, hasApiBase, preloadSignalFeeds } from "../api/client.js";
import { dedupeStories, normalizeBackendStory, normalizeCommandArticle } from "../utils/articleNormalize.js";

const BOOTSTRAP_PATH = "/feeds/bootstrap?latest_limit=25&story_limit=20&trending_limit=18&section_limit=18&topics_limit=10";
const BOOTSTRAP_CACHE_TTL_MS = 2 * 60 * 1000;
const LATEST_REFRESH_MS = 30 * 1000;

export function useInitialSignalData({
  account,
  setApiStatus,
  setBackendStories,
  setCommandArticles,
  setTrendingTopics,
  setPrompt,
  setDraftPrompt,
  setExternalDraft,
  setPhase,
  setActiveScreen,
  trackEvent,
}) {
  const [feedsLoading, setFeedsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const linkedArticleId = new URLSearchParams(window.location.search).get("article");

    // Wake the backend and warm every reader feed in one bootstrap request.
    preloadSignalFeeds({ userId: account?.id || null }).catch(() => {});

    Promise.allSettled([
      hasApiBase()
        ? apiGetCached(BOOTSTRAP_PATH, { ttlMs: BOOTSTRAP_CACHE_TTL_MS })
        : Promise.resolve(null),
      linkedArticleId && hasApiBase()
        ? apiGetCached(`/generated-articles/${encodeURIComponent(linkedArticleId)}`, { ttlMs: BOOTSTRAP_CACHE_TTL_MS })
        : Promise.resolve(null),
      fetch(`/generated-articles.json?ts=${Date.now()}`).then((response) => (response.ok ? response.json() : [])),
    ])
      .then(([bootstrapResult, linkedResult, staticResult]) => {
        if (cancelled) return;
        const bootstrap = bootstrapResult.status === "fulfilled" ? bootstrapResult.value : null;
        const generated = Array.isArray(bootstrap?.latest) ? bootstrap.latest : [];
        const stories = Array.isArray(bootstrap?.stories) ? bootstrap.stories : [];
        const topics = Array.isArray(bootstrap?.trendingTopics) ? bootstrap.trendingTopics : [];
        const staticArticles = staticResult.status === "fulfilled" && Array.isArray(staticResult.value)
          ? staticResult.value
          : [];

        setCommandArticles(dedupeStories(generated.length ? generated : staticArticles));
        setBackendStories(dedupeStories(stories.map(normalizeBackendStory)));
        setTrendingTopics(topics);
        setApiStatus(bootstrapResult.status === "fulfilled" ? "online" : "offline");

        const linkedFromApi = linkedResult.status === "fulfilled" && linkedResult.value ? linkedResult.value : null;
        const linkedFromStatic = linkedArticleId
          ? staticArticles.find((article) => String(article.id) === linkedArticleId)
          : null;
        if (linkedFromApi || linkedFromStatic) {
          const linkedArticle = normalizeCommandArticle(linkedFromApi || linkedFromStatic);
          setPrompt(linkedArticle.prompt);
          setDraftPrompt(linkedArticle.prompt);
          setExternalDraft(linkedArticle);
          setPhase("complete");
          setActiveScreen("Latest");
          trackEvent(account?.id, "view", { prompt: linkedArticle.prompt, article_id: String(linkedArticle.id) });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCommandArticles([]);
          setBackendStories([]);
          setApiStatus("offline");
        }
      })
      .finally(() => {
        if (!cancelled) setFeedsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // Keep Latest current: refresh the bootstrap bundle every minute.
  useEffect(() => {
    if (!hasApiBase()) return undefined;
    const timer = window.setInterval(() => {
      apiGetFresh(BOOTSTRAP_PATH, { ttlMs: BOOTSTRAP_CACHE_TTL_MS })
        .then((bootstrap) => {
          if (!bootstrap || typeof bootstrap !== "object") return;
          if (Array.isArray(bootstrap.latest) && bootstrap.latest.length) {
            setCommandArticles(dedupeStories(bootstrap.latest));
          }
          if (Array.isArray(bootstrap.stories)) {
            setBackendStories(dedupeStories(bootstrap.stories.map(normalizeBackendStory)));
          }
          if (Array.isArray(bootstrap.trendingTopics)) {
            setTrendingTopics(bootstrap.trendingTopics);
          }
        })
        .catch(() => {});
    }, LATEST_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  return { feedsLoading };
}
