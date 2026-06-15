export function Modal({ title, children, onClose }) {
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal-card" role="dialog" aria-modal="true" aria-label={title}>
        <header>
          <h2>{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close">Close</button>
        </header>
        {children}
      </section>
    </div>
  );
}
