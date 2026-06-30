import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../../api/client.js";
import { SESSION_ID } from "../../lib/session.js";
import { Modal } from "./Modal.jsx";

export function SettingsModal({ settings, onSettingsChange, onClose, onToast, account }) {
  const [autoPrefs, setAutoPrefs] = useState(null);

  useEffect(() => {
    if (account?.id) {
      apiGet(`/users/${account.id}/preferences/auto`).then(setAutoPrefs).catch(() => {});
    } else {
      apiPost("/history", { session_id: SESSION_ID, action_type: "prefs_check" }).catch(() => {});
    }
  }, [account?.id]);

  const update = (path, value) => {
    onSettingsChange((current) => ({ ...current, [path]: value }));
  };

  return (
    <Modal title="Settings" onClose={onClose} className="settings-modal">
      {autoPrefs && (autoPrefs.preferred_sections?.length > 0 || autoPrefs.preferred_topics?.length > 0) && (
        <div className="modal-section modal-section-flat">
          <p className="pref-section-header">Inferred from your activity</p>
          {autoPrefs.preferred_sections?.length > 0 && (
            <>
              <p className="pref-section-header pref-section-header-accent">Top sections</p>
              <div className="pref-tags">
                {autoPrefs.preferred_sections.map((section) => <span className="pref-tag" key={section}>{section}</span>)}
              </div>
            </>
          )}
          {autoPrefs.preferred_topics?.length > 0 && (
            <>
              <p className="pref-section-header pref-section-header-accent">Top topics</p>
              <div className="pref-tags">
                {autoPrefs.preferred_topics.map((topic) => <span className="pref-tag" key={topic}>{topic}</span>)}
              </div>
            </>
          )}
        </div>
      )}

      <div className="settings-grid">
        <label>
          Region
          <select value={settings.region} onChange={(event) => update("region", event.target.value)}>
            <option>Global</option>
            <option>United States</option>
            <option>Europe</option>
            <option>Asia-Pacific</option>
          </select>
        </label>
        <label>
          Edition
          <select value={settings.edition} onChange={(event) => update("edition", event.target.value)}>
            <option>Morning</option>
            <option>Afternoon</option>
            <option>Evening</option>
          </select>
        </label>
        <label>
          Reading density
          <select value={settings.density} onChange={(event) => update("density", event.target.value)}>
            <option>Comfortable</option>
            <option>Compact</option>
          </select>
        </label>
        <label>
          Minimum sources
          <input
            min="3"
            max="30"
            type="number"
            value={settings.sourceThreshold}
            onChange={(event) => update("sourceThreshold", Number(event.target.value))}
          />
        </label>
      </div>

      <div className="settings-list">
        <label className="settings-toggle-row">
          <span>
            <strong>Email alerts</strong>
            <em>Notify you when tracked stories move.</em>
          </span>
          <input
            checked={settings.emailAlerts}
            onChange={(event) => update("emailAlerts", event.target.checked)}
            type="checkbox"
          />
        </label>
        <label className="settings-toggle-row">
          <span>
            <strong>Label disputed claims</strong>
            <em>Surface disagreement across sources.</em>
          </span>
          <input
            checked={settings.showDisputedClaims}
            onChange={(event) => update("showDisputedClaims", event.target.checked)}
            type="checkbox"
          />
        </label>
      </div>

      <div className="modal-action-footer">
        <button className="secondary-action" type="button" onClick={() => onToast("Settings saved locally.")}>
          Confirm settings
        </button>
      </div>
    </Modal>
  );
}
