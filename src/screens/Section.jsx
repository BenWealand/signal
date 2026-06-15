import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../api/client.js";
import { SECTION_QUERIES } from "../lib/constants.js";
import { SESSION_ID } from "../lib/session.js";
import { dedupeStories, normalizeCommandArticle, storyDate, storyDek, storySourceCount, storyTitle } from "../utils/articleNormalize.js";

export function SectionScreen({ section, account, onPrompt, onOpenArticle }) {
  const [stories, setStories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadState, setLoadState] = useState("loading");
  const slug = section.toLowerCase().replace(" ", "-");
  const sectionPrompt = SECTION_QUERIES[section] || section.toLowerCase();

  const loadStories = useCallback(() => {
    setLoading(true);
    setLoadState("loading");
    apiGet(`/news/${slug}?limit=18`)
      .then((data) => {
        setStories(dedupeStories(Array.isArray(data) ? data : [], 18));
        setLoadState("live");
      })
      .catch(() => {
        setStories([]);
        setLoadState("offline");
      })
      .finally(() => setLoading(false));
  }, [slug]);

  useEffect(() => {
    loadStories();
    apiPost("/history", { user_id: account?.id || null, session_id: SESSION_ID, action_type: "section", section }).catch(() => {});
  }, [loadStories, section, account?.id]);

  const handleRefresh = () => {
    setRefreshing(true);
    setLoadState("refreshing");
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
          <button className="section-refresh-btn" type="button" onClick={() => onPrompt(sectionPrompt)}>Write section brief</button>
          <button className="section-refresh-btn secondary" type="button" onClick={handleRefresh} disabled={refreshing}>
            {refreshing ? "Fetching..." : "Refresh"}
          </button>
        </div>
      </div>

      {stories[0] && (
        <div className="breaking-banner">
          <strong>Top story</strong>
          <span>{storyTitle(stories[0])}</span>
        </div>
      )}

      <div className={`feed-status feed-status-${loadState}`}>
        {loadState === "loading" && `Loading live ${section.toLowerCase()} coverage...`}
        {loadState === "refreshing" && "Refresh requested from the backend..."}
        {loadState === "live" && "Live backend section coverage"}
        {loadState === "offline" && "Backend unavailable - no local section data is being invented"}
      </div>

      <div className="section-layout section-layout-main">
        <div className="section-grid">
          {loading && <div className="section-loading">Loading {section.toLowerCase()}...</div>}
          {!loading && stories.length === 0 && (
            <div className="section-empty">
              <p>No {section.toLowerCase()} stories indexed yet.</p>
              <button className="section-refresh-btn" type="button" onClick={handleRefresh} disabled={refreshing}>
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
