import { useEffect, useState } from "react";
import { apiGetCached, apiGetFresh } from "../api/client.js";
import { SECTION_NAMES, starterStories } from "../lib/constants.js";
import { dedupeStories } from "../utils/articleNormalize.js";
import { LoadingState, ScreenShell } from "./shared.jsx";

function articleMatchesSection(article, filter) {
  if (filter === "All") return true;
  const wanted = filter.toLowerCase();
  const aliases = wanted === "sports" ? new Set(["sports", "sporks"]) : new Set([wanted]);
  const section = String(article.section || "").toLowerCase();
  if (section) return aliases.has(section);
  const label = `${article.tag || ""} ${article.source || ""} ${article.prompt || ""}`.toLowerCase();
  return [...aliases].some((alias) => label.includes(alias));
}

export function TrendsScreen({ commandArticles, onOpenArticle }) {
  const [rankedTrends, setRankedTrends] = useState([]);
  const [topicStatus, setTopicStatus] = useState("loading");
  const [filter, setFilter] = useState("All");
  const sections = ["All", ...SECTION_NAMES];

  useEffect(() => {
    setTopicStatus("loading");
    apiGetCached("/news/trending?limit=18", { ttlMs: 30 * 1000 })
      .then((data) => {
        setRankedTrends(Array.isArray(data) ? data : []);
        setTopicStatus("live");
      })
      .catch(() => {
        setRankedTrends([]);
        setTopicStatus("fallback");
      });
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      apiGetFresh("/news/trending?limit=18", { ttlMs: 30 * 1000 })
        .then((data) => {
          setRankedTrends(Array.isArray(data) ? data : []);
          setTopicStatus("live");
        })
        .catch(() => {});
    }, 30 * 1000);
    return () => window.clearInterval(timer);
  }, []);

  const trends = rankedTrends.length
    ? rankedTrends
    : commandArticles.length
      ? dedupeStories([...commandArticles].sort((a, b) => (b.sourceCount || 0) - (a.sourceCount || 0)), 18)
      : starterStories.map((s) => ({
          id: s.id,
          headline: s.title,
          summary: s.dek,
          source: s.section,
          section: s.section,
          sourceCount: s.sourceCount,
          fairnessScore: 86,
          accuracyScore: 88,
        }));

  const filtered = trends.filter((trend) => articleMatchesSection(trend, filter));

  if (topicStatus === "loading" && !trends.length) {
    return (
      <ScreenShell eyebrow="Trending" title="Trending">
        <LoadingState message="Charting what the world is reading..." />
      </ScreenShell>
    );
  }

  return (
    <ScreenShell eyebrow="Trending" title="Trending">
      <p className="screen-caption">Ranked by views, likes, comments, relevance, and recency</p>
      <div className="feed-filter-bar">
        {sections.map((s) => (
          <button
            key={s}
            type="button"
            className={filter === s ? "is-active" : ""}
            onClick={() => setFilter(s)}
          >
            {s}
          </button>
        ))}
      </div>
      <div className="section-grid">
        {filtered.map((trend, index) => {
          const previewRaw = trend.dek || trend.summary || trend.body?.[0] || "";
          const preview = previewRaw.length > 150 ? `${previewRaw.slice(0, 150)}...` : previewRaw;
          const metrics = trend.trendMetrics || {};
          const currentRank = metrics.currentRank || index + 1;
          const previousRank = metrics.previousRank || currentRank;
          const rankDelta = previousRank - currentRank;
          const sectionLabel = trend.section || trend.tag || trend.source || "Trending";
          const openable = "prompt" in trend;
          const dateLabel = trendDate(trend) || (metrics.views !== undefined ? `${metrics.views} reads` : "");

          return (
            <article
              className={`section-card${openable ? "" : " is-static"}`}
              key={trend.id}
              onClick={openable ? () => onOpenArticle(trend) : undefined}
            >
              <div className="section-card-eyebrow">
                <span>#{currentRank} · {sectionLabel}</span>
                <RankArrow delta={rankDelta} />
              </div>
              <h3>{trend.headline}</h3>
              {preview && <p>{preview}</p>}
              <div className="section-card-footer">
                <strong>{trend.sourceCount}</strong>
                <em>{trend.sourceCount === 1 ? "source" : "sources"}</em>
                <span className="section-card-date">{dateLabel}</span>
              </div>
            </article>
          );
        })}
      </div>
      {!filtered.length ? (
        <p className="modal-empty-copy">No trending stories yet for this filter.</p>
      ) : null}
    </ScreenShell>
  );
}

function trendDate(trend) {
  const raw = trend.createdAt || trend.updated_at || trend.created_at || "";
  if (!raw) return "";
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function RankArrow({ delta }) {
  const className = delta > 0 ? "rank-up" : delta < 0 ? "rank-down" : "rank-flat";
  const label = delta === 0 ? "Holding steady" : delta > 0 ? `Up ${delta}` : `Down ${Math.abs(delta)}`;
  return (
    <em className={`trend-rank-indicator ${className}`} title={label} aria-label={label}>
      {delta === 0 ? (
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14" /></svg>
      ) : (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d={delta > 0 ? "M12 5v14M6 11l6-6 6 6" : "M12 19V5M6 13l6 6 6-6"} />
        </svg>
      )}
      {delta !== 0 && Math.abs(delta)}
    </em>
  );
}
