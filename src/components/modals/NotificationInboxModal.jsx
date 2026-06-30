import { Modal } from "./Modal.jsx";

export function NotificationInboxModal({ account, notifications, onClose }) {
  return (
    <Modal title="Inbox" onClose={onClose} className="notification-inbox">
      <div className="modal-hero-row">
        <div>
          <span>Notifications</span>
          <strong>{notifications.filter((item) => !item.is_read).length}</strong>
          <em>unread</em>
        </div>
        <div>
          <span>Activity</span>
          <strong>{notifications.length}</strong>
          <em>total</em>
        </div>
      </div>
      {account ? (
        notifications.length ? (
          <div className="notification-list">
            {notifications.map((item) => (
              <article className={`notification-row ${item.is_read ? "" : "is-unread"}`} key={item.id}>
                <span className="notification-dot" aria-hidden="true" />
                <div>
                  <strong>{item.message}</strong>
                  <em>{item.created_at ? new Date(item.created_at).toLocaleString() : ""}</em>
                </div>
                <button type="button" aria-label="Notification options">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 7.2h.01M12 12h.01M12 16.8h.01" />
                  </svg>
                </button>
              </article>
            ))}
          </div>
        ) : (
          <p className="modal-empty-copy">No notifications yet.</p>
        )
      ) : (
        <p className="modal-empty-copy">Sign in to receive comment, reply, like, read, and save alerts.</p>
      )}
    </Modal>
  );
}
