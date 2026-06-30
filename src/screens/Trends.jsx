import { useEffect, useState } from "react";
import { apiGet } from "../api/client.js";
import { starterStories } from "../lib/constants.js";
import { dedupeStories } from "../utils/articleNormalize.js";
import { ScreenShell } from "./shared.jsx";

export function TrendsScreen({ commandArticles, onOpenArticle }) {
  const [topics, setTopics] = useState([]);
  const [rankedTrends, setRankedTrends] = useState([]);
  const [topicStatus, setTopicStatus] = useState("loading");

  useEffect(() => {
    setTopicStatus("loading");
    Promise.allSettled([
      apiGet("/news/trending?limit=18"),
      apiGet("/news/trending-topics?limit=12"),
    ])
      .then(([trendResult, topicResult]) => {
        setRankedTrends(trendResult.status === "fulfilled" && Array.isArray(trendResult.value) ? trendResult.value : []);
        setTopics(topicResult.status === "fulfilled" && Array.isArray(topicResult.value) ? topicResult.value : []);
        setTopicStatus(trendResult.status === "fulfilled" || topicResult.status === "fulfilled" ? "live" : "fallback");
      })
      .catch(() => {
        setRankedTrends([]);
        setTopics([]);
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
      <div className="section-layout">
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
                  <em className={rankDelta > 0 ? "rank-up" : rankDelta < 0 ? "rank-down" : "rank-flat"}>
                    {rankDelta > 0 ? `▲ ${rankDelta}` : rankDelta < 0 ? `▼ ${Math.abs(rankDelta)}` : "━"}
                  </em>
                  {sourceLabel}
                </span>
                <h3>{trend.headline}</h3>
                {preview && <p>{preview}</p>}
                {trend.body?.length > 0 && !preview && (
                  <p className="trend-card-body-preview">{trend.body[0]}</p>
                )}
                <div>
                  <strong>{trend.sourceCount}</strong>
                  <em>{trend.sourceCount === 1 ? "source" : "sources"}</em>
                  {metrics.views !== undefined && (
                    <span className="trend-metric-strip">
                      {metrics.views} reads · {metrics.saves} saves · {metrics.likes} likes · {metrics.comments} comments
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
        {topics.length > 0 && (
          <aside className="trending-sidebar">
            <h3>Trending now</h3>
            {topics.map((t, i) => {
              const typeLabel = {
                PERSON: "Person", ORG: "Org", GPE: "Place", LOC: "Place",
                EVENT: "Event", PRODUCT: "Product", topic: "Topic",
              }[t.entity_type] || t.entity_type || "Topic";
              return (
                <div className="trending-topic-row" key={`${t.entity_text}-${i}`}>
                  <span className="trending-rank">#{i + 1}</span>
                  <div className="trending-topic-info">
                    <strong>{t.entity_text}</strong>
                    <em>{typeLabel}{t.mentions > 1 ? ` · ${t.mentions} mentions` : ""}</em>
                  </div>
                </div>
              );
            })}
          </aside>
        )}
      </div>
    </ScreenShell>
  );
}
