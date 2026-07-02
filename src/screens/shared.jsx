export function ScreenShell({ eyebrow, title, children }) {
  return (
    <section className="app-screen">
      <header>
        <span>{eyebrow}</span>
        <h1>{title}</h1>
      </header>
      {children}
    </section>
  );
}

export function EmptyState({ title, text, action }) {
  return (
    <div className="empty-state">
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}

export function LoadingState({ message, compact = false }) {
  return (
    <div className={`loading-state${compact ? " is-compact" : ""}`} role="status" aria-live="polite">
      <span className="loading-ring" aria-hidden="true" />
      <p>{message}</p>
    </div>
  );
}
