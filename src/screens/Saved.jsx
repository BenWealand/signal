import { EmptyState, ScreenShell } from "./shared.jsx";

export function SavedScreen({ savedArticles, onOpenAccount }) {
  return (
    <ScreenShell eyebrow="Saved" title="Saved">
      {savedArticles.length ? (
        <div className="library-list">
          {savedArticles.map((article) => (
            <article className="feed-row" key={article.id}>
              <span>{article.savedAt}</span>
              <h4>{article.title}</h4>
              <div>
                <strong>{article.sourceCount}</strong>
                <em>sources</em>
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
