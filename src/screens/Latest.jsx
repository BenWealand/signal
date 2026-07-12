import { useState } from "react";
import { SECTION_NAMES } from "../lib/constants.js";
import { dedupeStories } from "../utils/articleNormalize.js";
import { EmptyState, LoadingState, ScreenShell } from "./shared.jsx";

function articleTimestamp(article) {
  return String(article.createdAt || article.updated_at || article.created_at || "");
}

export function LatestScreen({ commandArticles, onOpenArticle, loading = false, account }) {
  const [filter, setFilter] = useState("All");
  const sections = ["All", ...SECTION_NAMES];
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
          {filtered.map((article) => {
            const dekRaw = article.dek || article.summary || "";
            const dek = dekRaw.length > 150 ? `${dekRaw.slice(0, 150)}...` : dekRaw;
            return (
              <article className="section-card" key={article.id} onClick={() => onOpenArticle(article)}>
                <div className="section-card-eyebrow">
                  <span>{article.section || article.source || "news desk"}</span>
                  <em>{article.sourceCount} sources</em>
                </div>
                <h3>{article.headline}</h3>
                {dek && <p>{dek}</p>}
                <div className="section-card-footer">
                  <strong>{article.sourceCount}</strong>
                  <em>sources</em>
                  <span className="section-card-date">
                    {article.createdAt ? new Date(article.createdAt).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : ""}
                  </span>
                </div>
              </article>
            );
          })}
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
