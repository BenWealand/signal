import { useState } from "react";
import { supabase } from "../../lib/supabase.js";
import { Modal } from "./Modal.jsx";

export function AccountModal({
  account,
  savedArticles,
  newsletterEmail,
  onNewsletterChange,
  onClose,
  onSignIn,
  onSignOut,
  onClearSaved,
  onToast,
}) {
  const [isSignUp, setIsSignUp] = useState(!account);
  const [name, setName] = useState(account?.name || "");
  const [email, setEmail] = useState(account?.email || newsletterEmail || "");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [authError, setAuthError] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    setAuthError("");
    if (!email.trim() || !password.trim()) {
      onToast("Email and password are required.");
      return;
    }
    if (isSignUp && !name.trim()) {
      onToast("Name is required to create an account.");
      return;
    }
    setLoading(true);
    try {
      let user;
      if (isSignUp) {
        const { data, error } = await supabase.auth.signUp({
          email: email.trim(),
          password,
          options: { data: { name: name.trim() } },
        });
        if (error) throw error;
        user = data.user;
        onToast("Account created - check your email to confirm.");
      } else {
        const { data, error } = await supabase.auth.signInWithPassword({
          email: email.trim(),
          password,
        });
        if (error) throw error;
        user = data.user;
      }
      const nextAccount = {
        name: name.trim() || user.user_metadata?.name || user.email.split("@")[0],
        email: user.email,
        plan: "Reader",
        supabase_user_id: user.id,
      };
      onSignIn(nextAccount);
      onNewsletterChange(user.email);
      if (!isSignUp) onToast("Signed in.");
    } catch (err) {
      setAuthError(err.message || "Authentication failed.");
    } finally {
      setLoading(false);
    }
  };

  if (account) {
    return (
      <Modal title="Account" onClose={onClose} className="account-modal">
        <div className="account-profile-card">
          <div className="account-avatar" aria-hidden="true">{account.name?.slice(0, 1) || "S"}</div>
          <div>
            <h3>{account.name}</h3>
            <p>{account.email}</p>
          </div>
          <span>{account.plan} plan</span>
        </div>
        <div className="modal-hero-row">
          <div>
            <span>Saved</span>
            <strong>{savedArticles.length}</strong>
            <em>articles</em>
          </div>
          <div>
            <span>Status</span>
            <strong>Live</strong>
            <em>synced account</em>
          </div>
        </div>
        <div className="modal-section">
          <h3>Saved articles</h3>
          {savedArticles.length ? (
            <>
              <ul className="saved-list">
                {savedArticles.map((article) => (
                  <li key={article.id}>
                    <strong>{article.title}</strong>
                    <span>{article.sourceCount} sources - {article.savedAt}</span>
                  </li>
                ))}
              </ul>
              <button className="secondary-action" type="button" onClick={onClearSaved}>Clear saved</button>
            </>
          ) : (
            <p className="modal-empty-copy">No saved articles yet.</p>
          )}
        </div>
        <div className="modal-action-footer">
          <button className="secondary-action" type="button" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title={isSignUp ? "Create account" : "Sign in"} onClose={onClose} className="account-modal">
      <form className="modal-form" onSubmit={submit}>
        {isSignUp && (
          <label>
            Name
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Reader name"
              autoComplete="name"
            />
          </label>
        )}
        <label>
          Email
          <input
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
            type="email"
            autoComplete="email"
          />
        </label>
        <label>
          Password
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder={isSignUp ? "Choose a password" : "Your password"}
            type="password"
            autoComplete={isSignUp ? "new-password" : "current-password"}
          />
        </label>
        {authError && <p className="form-error">{authError}</p>}
        <button type="submit" disabled={loading}>
          {loading ? "..." : isSignUp ? "Create account" : "Sign in"}
        </button>
        <button
          className="secondary-action"
          type="button"
          onClick={() => { setIsSignUp((v) => !v); setAuthError(""); }}
        >
          {isSignUp ? "Already have an account? Sign in" : "No account? Create one"}
        </button>
      </form>
    </Modal>
  );
}
