import { useCallback, useEffect, useState } from "react";
import { apiGetCached, apiPost, invalidateApiCache, peekApiCache } from "../api/client.js";
import { SECTION_QUERIES } from "../lib/constants.js";
import { SESSION_ID } from "../lib/session.js";
import { dedupeStories, normalizeCommandArticle, storyDate, storyDek, storySourceCount, storyTitle } from "../utils/articleNormalize.js";
import { LoadingState } from "./shared.jsx";

const SECTION_LOADING_MESSAGES = {
  World: "Scanning dispatches from every continent...",
  Politics: "Following the paper trail through the capitol...",
  Markets: "Reading the tape on today's markets...",
  Technology: "Compiling the latest from labs and launchpads...",
  Climate: "Checking readings from field stations worldwide...",
};

const SECTION_CACHE_TTL_MS = 2 * 60 * 1000;

export function SectionScreen({ section, account, onPrompt, onOpenArticle }) {
  const [stories, setStories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadState, setLoadState] = useState("loading");
  const slug = section.toLowerCase().replace(" ", "-");
  const sectionPrompt = SECTION_QUERIES[section] || section.toLowerCase();

  const loadStories = useCallback(() => {
    const path = `/news/${slug}?limit=18`;
    const cached = peekApiCache(path);
    const cachedStories = Array.isArray(cached) ? dedupeStories(cached, 18) : [];
    setStories(cachedStories);
    setLoading(true);
    setLoadState(cachedStories.length ? "refreshing" : "loading");
    let cancelled = false;
    apiGetCached(path, { ttlMs: SECTION_CACHE_TTL_MS })
      .then((data) => {
        if (cancelled) return;
        setStories(dedupeStories(Array.isArray(data) ? data : [], 18));
        setLoadState("live");
      })
      .catch(() => {
        if (cancelled) return;
        setStories([]);
        setLoadState("offline");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  useEffect(() => {
    const cancel = loadStories();
    apiPost("/history", { user_id: account?.id || null, session_id: SESSION_ID, action_type: "section", section }).catch(() => {});
    return cancel;
  }, [loadStories, section, account?.id]);

  const handleRefresh = () => {
    setRefreshing(true);
    setLoadState("refreshing");
    invalidateApiCache(`/news/${slug}`);
    apiPost(`/news/refresh/${slug}`, {})
      .then(() => window.setTimeout(loadStories, 8000))
      .catch(() => setLoadState("offline"))
      .finally(() => window.setTimeout(() => setRefreshing(false), 8500));
  };

  const openStory = (story) => {
    if (story.headline) {
      onOpenArticle(normalizeCommandArticle(story));
      return;
    }
    onPrompt(storyTitle(story));
  };

  return (
    <section className="section-page">
      <div className="section-header">
        <div className="section-header-left">
          <span>Signal / {section}</span>
          <h1>{section}</h1>
        </div>
        <div className="section-actions">
          <button className="push-btn" type="button" onClick={() => onPrompt(sectionPrompt)}>Write section brief</button>
          <button className="push-btn push-btn-ghost" type="button" onClick={handleRefresh} disabled={refreshing}>
            {refreshing ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {stories[0] && (
        <div className="breaking-banner">
          <strong>Top story</strong>
          <span>{storyTitle(stories[0])}</span>
        </div>
      )}

      <div className="section-layout section-layout-main">
        <div className="section-grid">
          {(loading || loadState === "refreshing") && stories.length === 0 && (
            <LoadingState
              message={loadState === "refreshing"
                ? `Bringing in fresh ${section.toLowerCase()} coverage...`
                : SECTION_LOADING_MESSAGES[section] || `Gathering ${section.toLowerCase()} coverage...`}
            />
          )}
          {!loading && loadState !== "refreshing" && stories.length === 0 && (
            <div className="section-empty">
              <p>Fresh {section.toLowerCase()} stories are on their way. Check back in a moment or fetch them now.</p>
              <button className="push-btn" type="button" onClick={handleRefresh} disabled={refreshing}>
                {refreshing ? "Fetching..." : "Fetch now"}
              </button>
            </div>
          )}
          {stories.map((story) => (
            <article className="section-card" key={story.id} onClick={() => openStory(story)}>
              <div className="section-card-eyebrow">
                <span>{section}</span>
                <em>{storySourceCount(story)} sources</em>
              </div>
              <h3>{storyTitle(story)}</h3>
              {storyDek(story) && <p>{storyDek(story).slice(0, 150)}{storyDek(story).length > 150 ? "..." : ""}</p>}
              <div className="section-card-footer">
                <strong>{storySourceCount(story)}</strong>
                <em>sources</em>
                <span className="section-card-date">{storyDate(story)}</span>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
