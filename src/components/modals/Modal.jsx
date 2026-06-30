export function Modal({ title, children, onClose, className = "" }) {
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <section className={`modal-card ${className}`} role="dialog" aria-modal="true" aria-label={title}>
        <header onClick={(event) => event.stopPropagation()}>
          <h2>{title}</h2>
          <button className="icon-close-button" type="button" onClick={onClose} aria-label="Close">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="m6 6 12 12M18 6 6 18" />
            </svg>
          </button>
        </header>
        <div className="modal-body" onClick={(event) => event.stopPropagation()}>
          {children}
        </div>
      </section>
    </div>
  );
}
