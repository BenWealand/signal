import { useEffect, useState } from "react";
import { apiGetCached, hasApiBase } from "../api/client.js";
import { EmptyState, LoadingState, ScreenShell } from "./shared.jsx";

export function SavedScreen({ savedArticles, account, onOpenAccount }) {
  const [serverSaves, setServerSaves] = useState([]);
  const [loading, setLoading] = useState(Boolean(account?.id && hasApiBase()));

  useEffect(() => {
    if (!account?.id || !hasApiBase()) {
      setServerSaves([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    apiGetCached(`/users/${account.id}/saved`, { ttlMs: 5 * 60 * 1000 })
      .then((rows) => {
        if (cancelled) return;
        setServerSaves(Array.isArray(rows) ? rows : []);
      })
      .catch(() => {
        if (!cancelled) setServerSaves([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [account?.id]);

  const seen = new Set(savedArticles.map((item) => String(item.title || "").toLowerCase()));
  const merged = [
    ...savedArticles,
    ...serverSaves
      .map((row) => ({
        id: `server-${row.id || row.story_id}`,
        title: row.title,
        sourceCount: row.source_count || 0,
        savedAt: row.created_at ? new Date(row.created_at).toLocaleString() : "",
      }))
      .filter((row) => row.title && !seen.has(String(row.title).toLowerCase())),
  ];

  return (
    <ScreenShell eyebrow="Saved" title="Saved">
      {loading && !merged.length ? (
        <LoadingState message="Opening your reading library..." />
      ) : merged.length ? (
        <div className="section-grid">
          {merged.map((article) => (
            <article className="section-card" key={article.id}>
              <div className="section-card-eyebrow">
                <span>Saved</span>
                <em>{article.sourceCount} sources</em>
              </div>
              <h3>{article.title}</h3>
              <p>Kept in your reading library for follow-up review.</p>
              <div className="section-card-footer">
                <strong>{article.sourceCount}</strong>
                <em>sources</em>
                <span className="section-card-date">{article.savedAt}</span>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState
          title="No saved articles"
          text="Open an article and press Save."
          action={<button className="push-btn" type="button" onClick={onOpenAccount}>Sign in to sync saves</button>}
        />
      )}
    </ScreenShell>
  );
}
