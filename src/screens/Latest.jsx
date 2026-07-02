import { useState } from "react";
import { articleStateFor, dedupeStories } from "../utils/articleNormalize.js";
import { EmptyState, LoadingState, ScreenShell } from "./shared.jsx";

function articleTimestamp(article) {
  return String(article.createdAt || article.updated_at || article.created_at || "");
}

export function LatestScreen({ commandArticles, onOpenArticle, onBuildArticle, loading = false, account }) {
  const [filter, setFilter] = useState("All");
  const sections = ["All", "World", "Politics", "Markets", "Technology", "Climate"];
  const filteredRaw = filter === "All"
    ? commandArticles
    : commandArticles.filter((a) => {
        const section = String(a.section || "").toLowerCase();
        if (section) return section === filter.toLowerCase();
        const label = (a.tag || a.source || "").toLowerCase();
        return label.includes(filter.toLowerCase()) || (a.prompt || "").toLowerCase().includes(filter.toLowerCase());
      });
  // Most recently written first.
  const newestFirst = [...filteredRaw].sort((a, b) => articleTimestamp(b).localeCompare(articleTimestamp(a)));
  const filtered = dedupeStories(newestFirst);

  return (
    <ScreenShell eyebrow="Latest" title="Latest">
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
      {loading && !filtered.length ? (
        <LoadingState message="Rolling the presses on today's coverage..." />
      ) : filtered.length ? (
        <div className="section-grid">
          {filtered.map((article) => (
            <article className="section-card" key={article.id}>
              <div className="section-card-eyebrow">
                <span>{article.section || article.source || "news desk"}</span>
                <em>{article.sourceCount} sources</em>
              </div>
              <em className={`article-row-state article-row-state-${articleStateFor(article).kind}`}>
                {articleStateFor(article).label}
              </em>
              <h3>{article.headline}</h3>
              <p>{article.dek || article.summary}</p>
              <div className="section-card-footer">
                <strong>{article.sourceCount}</strong>
                <em>sources</em>
                <span className="section-card-date">
                  {article.createdAt ? new Date(article.createdAt).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : ""}
                </span>
              </div>
              <div className="card-action-row">
                <button className="push-btn" type="button" onClick={() => onOpenArticle(article)}>Read</button>
                <button className="push-btn push-btn-ghost" type="button" onClick={() => onBuildArticle(article)}>Refresh</button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState
          title="No stories yet for this filter"
          text="Try another filter or write from a prompt."
        />
      )}
    </ScreenShell>
  );
}
