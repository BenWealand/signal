import { useState } from "react";
import { articleStateFor, dedupeStories } from "../utils/articleNormalize.js";
import { EmptyState, ScreenShell } from "./shared.jsx";

export function LatestScreen({ commandArticles, onOpenArticle, onBuildArticle, apiStatus, account }) {
  const [filter, setFilter] = useState("All");
  const sections = ["All", "World", "Politics", "Markets", "Technology", "Climate"];
  const filteredRaw = filter === "All"
    ? commandArticles
    : commandArticles.filter((a) => {
        const label = (a.tag || a.source || "").toLowerCase();
        return label.includes(filter.toLowerCase()) || (a.prompt || "").toLowerCase().includes(filter.toLowerCase());
      });
  const filtered = dedupeStories(filteredRaw);

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
        <span className={`feed-status feed-status-${apiStatus}`}>
          {apiStatus === "online" ? "Live backend data" : "Static fallback/demo data"}
        </span>
      </div>
      {filtered.length ? (
        <div className="section-grid">
          {filtered.map((article) => (
            <article className="section-card" key={article.id}>
              <div className="section-card-eyebrow">
                <span>{article.source || "news desk"}</span>
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
                <button type="button" onClick={() => onOpenArticle(article)}>Read</button>
                <button type="button" onClick={() => onBuildArticle(article)}>Refresh</button>
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
