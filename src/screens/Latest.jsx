import { useState } from "react";
import { starterStories } from "../lib/constants.js";
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
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.5rem" }}>
        {sections.map((s) => (
          <button
            key={s}
            type="button"
            className={filter === s ? "solid-button" : "secondary-action"}
            style={{ minHeight: "2rem", fontSize: "0.72rem" }}
            onClick={() => setFilter(s)}
          >
            {s}
          </button>
        ))}
        <span className={`feed-status feed-status-${apiStatus}`}>
          {apiStatus === "online" ? "Live backend data" : "Static fallback/demo data"}
        </span>
      </div>
      <div className="screen-grid">
        <section className="feed-list">
          <h3>Filed analysis <small>{filtered.length} stories</small></h3>
          {filtered.length ? (
            filtered.map((article) => (
              <article className="feed-row" key={article.id}>
                <span>
                  <span className="news-item-source">{article.source || "news desk"}</span>
                  {" "}/{" "}
                  {article.createdAt ? new Date(article.createdAt).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : ""}
                </span>
                <em className={`article-row-state article-row-state-${articleStateFor(article).kind}`}>
                  {articleStateFor(article).label}
                </em>
                <h4>{article.headline}</h4>
                <p>{article.dek || article.summary}</p>
                <div>
                  <strong>{article.sourceCount}</strong>
                  <em>sources</em>
                  <button type="button" onClick={() => onOpenArticle(article)}>Read</button>
                  <button type="button" onClick={() => onBuildArticle(article)}>Refresh</button>
                </div>
              </article>
            ))
          ) : (
            <EmptyState
              title="No stories yet for this filter"
              text="Try another filter or write from a prompt."
            />
          )}
        </section>
        <aside className="rail-panel">
          <h3>Topics</h3>
          {starterStories.map((story) => (
            <div className="mini-story" key={story.id}>
              <span>{story.section}</span>
              <strong>{story.title}</strong>
              <em>{story.sourceCount} sources</em>
            </div>
          ))}
        </aside>
      </div>
    </ScreenShell>
  );
}
