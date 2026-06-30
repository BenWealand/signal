import { EmptyState, ScreenShell } from "./shared.jsx";

export function SavedScreen({ savedArticles, onOpenAccount }) {
  return (
    <ScreenShell eyebrow="Saved" title="Saved">
      {savedArticles.length ? (
        <div className="section-grid">
          {savedArticles.map((article) => (
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
          action={<button type="button" onClick={onOpenAccount}>Sign in to sync saves</button>}
        />
      )}
    </ScreenShell>
  );
}
