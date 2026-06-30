import { useEffect, useState } from "react";
import { apiGet } from "../api/client.js";
import { starterStories } from "../lib/constants.js";
import { dedupeStories } from "../utils/articleNormalize.js";
import { ScreenShell } from "./shared.jsx";

export function TrendsScreen({ commandArticles, onOpenArticle }) {
  const [rankedTrends, setRankedTrends] = useState([]);
  const [topicStatus, setTopicStatus] = useState("loading");

  useEffect(() => {
    setTopicStatus("loading");
    apiGet("/news/trending?limit=18")
      .then((data) => {
        setRankedTrends(Array.isArray(data) ? data : []);
        setTopicStatus("live");
      })
      .catch(() => {
        setRankedTrends([]);
        setTopicStatus("fallback");
      });
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
          sourceCount: s.sourceCount,
          fairnessScore: 86,
          accuracyScore: 88,
        }));

  return (
    <ScreenShell eyebrow="Trending" title="Trending">
      <div className={`feed-status feed-status-${topicStatus}`}>
        {topicStatus === "loading" && "Loading live trend rankings..."}
        {topicStatus === "live" && "Ranked by reads, saves, likes, comments, and recency"}
        {topicStatus === "fallback" && "Showing article-derived fallback trends"}
      </div>
      <div className="trend-board">
        {trends.map((trend, index) => {
          const preview = trend.dek || trend.summary || "";
          const metrics = trend.trendMetrics || {};
          const currentRank = metrics.currentRank || index + 1;
          const previousRank = metrics.previousRank || currentRank;
          const rankDelta = previousRank - currentRank;
          const sourceLabel = trend.sources?.length
            ? trend.sources.slice(0, 3).join(", ") + (trend.sources.length > 3 ? ` +${trend.sources.length - 3}` : "")
            : trend.source || "news signal";

          return (
            <article className="trend-card" key={trend.id}>
              <span className="trend-rank-line">
                <b>#{currentRank}</b>
                <RankArrow delta={rankDelta} />
                {sourceLabel}
              </span>
              <h3>{trend.headline}</h3>
              {preview && <p>{preview}</p>}
              {trend.body?.length > 0 && !preview && <p className="trend-card-body-preview">{trend.body[0]}</p>}
              <div>
                <strong>{trend.sourceCount}</strong>
                <em>{trend.sourceCount === 1 ? "source" : "sources"}</em>
                {metrics.views !== undefined && (
                  <span className="trend-metric-strip">
                    {metrics.views} reads / {metrics.saves} saves / {metrics.likes} likes / {metrics.comments} comments
                  </span>
                )}
                {"prompt" in trend && (
                  <button type="button" onClick={() => onOpenArticle(trend)}>Open</button>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </ScreenShell>
  );
}

function RankArrow({ delta }) {
  const className = delta > 0 ? "rank-up" : delta < 0 ? "rank-down" : "rank-flat";
  return (
    <em className={className}>
      {delta === 0 ? (
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14" /></svg>
      ) : (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d={delta > 0 ? "M12 5v14M6 11l6-6 6 6" : "M12 19V5M6 13l6 6 6-6"} />
        </svg>
      )}
      {delta === 0 ? "even" : Math.abs(delta)}
    </em>
  );
}
