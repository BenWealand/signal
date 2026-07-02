import { useEffect, useState } from "react";
import { apiGetCached, preloadSignalFeeds } from "../api/client.js";
import { dedupeStories, normalizeBackendStory, normalizeCommandArticle } from "../utils/articleNormalize.js";

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

    // Wake the backend and warm every reader feed (latest, trending, saved,
    // and all sections) as soon as the app opens. Results land in the local
    // cache, so screens render instantly afterwards.
    preloadSignalFeeds({ userId: account?.id || null }).catch(() => {});

    Promise.allSettled([
      apiGetCached("/generated-articles", { ttlMs: 5 * 60 * 1000 }),
      apiGetCached("/stories", { ttlMs: 5 * 60 * 1000 }),
      linkedArticleId ? apiGetCached(`/generated-articles/${encodeURIComponent(linkedArticleId)}`, { ttlMs: 5 * 60 * 1000 }) : Promise.resolve(null),
      apiGetCached("/news/trending-topics?limit=10", { ttlMs: 5 * 60 * 1000 }),
      fetch(`/generated-articles.json?ts=${Date.now()}`).then((response) => (response.ok ? response.json() : [])),
    ])
      .then(([generatedResult, storiesResult, linkedResult, topicsResult, staticResult]) => {
        if (cancelled) return;
        const generated = generatedResult.status === "fulfilled" && Array.isArray(generatedResult.value)
          ? generatedResult.value
          : [];
        const stories = storiesResult.status === "fulfilled" && Array.isArray(storiesResult.value)
          ? storiesResult.value
          : [];
        const staticArticles = staticResult.status === "fulfilled" && Array.isArray(staticResult.value)
          ? staticResult.value
          : [];
        const topics = topicsResult.status === "fulfilled" && Array.isArray(topicsResult.value)
          ? topicsResult.value
          : [];
        setCommandArticles(dedupeStories(generated.length ? generated : staticArticles));
        setBackendStories(dedupeStories(stories.map(normalizeBackendStory)));
        setTrendingTopics(topics);
        setApiStatus(generatedResult.status === "fulfilled" || storiesResult.status === "fulfilled" ? "online" : "offline");
        setFeedsLoading(false);

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
          setFeedsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { feedsLoading };
}
