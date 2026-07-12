import { useEffect, useState } from "react";
import { supabase, isSupabaseConfigured } from "../../lib/supabase.js";
import {
  authRedirectUrl,
  permissionLabels,
  syncAccountWithBackend,
  updateAccountProfile,
  validatePassword,
  PASSWORD_MIN_LENGTH,
} from "../../lib/auth.js";
import { isAdminAccount } from "../../lib/admin.js";
import { Modal } from "./Modal.jsx";

const MODES = {
  signin: "Sign in",
  signup: "Create account",
  forgot: "Reset password",
  recover: "Choose a new password",
  security: "Security",
};

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
  initialMode = "",
}) {
  const [mode, setMode] = useState(initialMode || (account ? "security" : "signin"));
  const [name, setName] = useState(account?.name || "");
  const [email, setEmail] = useState(account?.email || newsletterEmail || "");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [authError, setAuthError] = useState("");
  const [info, setInfo] = useState("");

  useEffect(() => {
    if (initialMode) setMode(initialMode);
  }, [initialMode]);

  const switchMode = (next) => {
    setMode(next);
    setAuthError("");
    setInfo("");
    setPassword("");
    setConfirmPassword("");
  };

  const finishSignedIn = async (user, { toastMessage } = {}) => {
    const nextAccount = await syncAccountWithBackend(user, { name: name.trim() });
    onSignIn(nextAccount);
    onNewsletterChange(nextAccount.email || user.email || "");
    if (toastMessage) onToast(toastMessage);
  };

  const submitSignIn = async () => {
    const { data, error } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    });
    if (error) throw error;
    if (!data.session?.user) {
      throw new Error("Sign-in succeeded but no session was created. Confirm your email, then try again.");
    }
    await finishSignedIn(data.session.user, { toastMessage: "Signed in." });
  };

  const submitSignUp = async () => {
    const passwordError = validatePassword(password);
    if (passwordError) throw new Error(passwordError);
    if (!name.trim()) throw new Error("Name is required to create an account.");
    const { data, error } = await supabase.auth.signUp({
      email: email.trim(),
      password,
      options: {
        data: { name: name.trim() },
        emailRedirectTo: authRedirectUrl("/"),
      },
    });
    if (error) throw error;
    if (data.session?.user) {
      await finishSignedIn(data.session.user, { toastMessage: "Account created and signed in." });
      return;
    }
    setInfo("Account created. Check your email to confirm, then sign in.");
    onToast("Account created — confirm your email before signing in.");
    switchMode("signin");
  };

  const submitForgot = async () => {
    if (!email.trim()) throw new Error("Enter the email for your account.");
    const { error } = await supabase.auth.resetPasswordForEmail(email.trim(), {
      redirectTo: authRedirectUrl("/"),
    });
    if (error) throw error;
    setInfo("Password reset email sent. Open the link, then choose a new password here.");
    onToast("Password reset email sent.");
  };

  const submitRecover = async () => {
    const passwordError = validatePassword(password);
    if (passwordError) throw new Error(passwordError);
    if (password !== confirmPassword) throw new Error("Passwords do not match.");
    const { data, error } = await supabase.auth.updateUser({ password });
    if (error) throw error;
    if (data.user) {
      await finishSignedIn(data.user, { toastMessage: "Password updated. You are signed in." });
      setMode("security");
    }
  };

  const submitChangePassword = async () => {
    const passwordError = validatePassword(password);
    if (passwordError) throw new Error(passwordError);
    if (password !== confirmPassword) throw new Error("Passwords do not match.");
    const { error } = await supabase.auth.updateUser({ password });
    if (error) throw error;
    setPassword("");
    setConfirmPassword("");
    setInfo("Password updated.");
    onToast("Password updated.");
  };

  const resendConfirmation = async () => {
    if (!email.trim()) {
      onToast("Enter your email first.");
      return;
    }
    setLoading(true);
    setAuthError("");
    try {
      const { error } = await supabase.auth.resend({
        type: "signup",
        email: email.trim(),
        options: { emailRedirectTo: authRedirectUrl("/") },
      });
      if (error) throw error;
      setInfo("Confirmation email resent.");
      onToast("Confirmation email resent.");
    } catch (err) {
      setAuthError(err.message || "Could not resend confirmation email.");
    } finally {
      setLoading(false);
    }
  };

  const saveProfileName = async () => {
    setAuthError("");
    setInfo("");
    if (name.trim().length < 2) {
      setAuthError("Name must be at least 2 characters.");
      return;
    }
    setLoading(true);
    try {
      const next = await updateAccountProfile(name.trim());
      onSignIn(next);
      setInfo("Profile updated.");
      onToast("Profile updated.");
    } catch (err) {
      setAuthError(err?.message || "Could not update profile.");
    } finally {
      setLoading(false);
    }
  };

  const submit = async (event) => {
    event.preventDefault();
    setAuthError("");
    setInfo("");
    if (!isSupabaseConfigured) {
      setAuthError("Authentication is not configured for this deployment.");
      return;
    }
    setLoading(true);
    try {
      if (mode === "signin") {
        if (!email.trim() || !password) throw new Error("Email and password are required.");
        await submitSignIn();
      } else if (mode === "signup") {
        if (!email.trim() || !password) throw new Error("Email and password are required.");
        await submitSignUp();
      } else if (mode === "forgot") {
        await submitForgot();
      } else if (mode === "recover") {
        await submitRecover();
      } else if (mode === "security") {
        await submitChangePassword();
      }
    } catch (err) {
      const message = err?.message || "Authentication failed.";
      setAuthError(message);
      if (/confirm|verified|confirmation/i.test(message)) {
        setInfo("If your account needs email confirmation, use Resend confirmation below.");
      }
    } finally {
      setLoading(false);
    }
  };

  if (account && mode !== "recover") {
    const admin = isAdminAccount(account);
    return (
      <Modal title="Account" onClose={onClose} className="account-modal">
        <div className="account-profile-card">
          <div className="account-avatar" aria-hidden="true">{account.name?.slice(0, 1) || "S"}</div>
          <div>
            <h3>{account.name}</h3>
            <p>{account.email}</p>
          </div>
          <span>{account.plan || (admin ? "Admin" : "Reader")} plan</span>
        </div>
        <div className="modal-hero-row">
          <div>
            <span>Saved</span>
            <strong>{savedArticles.length}</strong>
            <em>articles</em>
          </div>
          <div>
            <span>Role</span>
            <strong>{account.role || (admin ? "admin" : "reader")}</strong>
            <em>{admin ? "elevated access" : "standard access"}</em>
          </div>
        </div>

        <div className="modal-section">
          <h3>Profile</h3>
          <label className="auth-inline-label">
            Display name
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              autoComplete="name"
              placeholder="Your name"
            />
          </label>
          <button className="secondary-action" type="button" onClick={saveProfileName} disabled={loading}>
            Save name
          </button>
        </div>

        <div className="modal-section">
          <h3>Permissions</h3>
          <ul className="auth-permission-list">
            {permissionLabels(account.permissions || {}).map((item) => (
              <li key={item.key} data-on={item.on ? "true" : "false"}>
                <strong>{item.on ? "On" : "Off"}</strong>
                <span>{item.label}</span>
              </li>
            ))}
          </ul>
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

        <div className="modal-section auth-security-section">
          <h3>Security</h3>
          <p className="modal-empty-copy">
            Passwords are stored by Supabase Auth (hashed). Signal never stores raw passwords.
            Minimum {PASSWORD_MIN_LENGTH} characters with letters and numbers.
          </p>
          <form className="modal-form" onSubmit={submit}>
            <label>
              New password
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                autoComplete="new-password"
                placeholder={`At least ${PASSWORD_MIN_LENGTH} characters`}
              />
            </label>
            <label>
              Confirm new password
              <input
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                type="password"
                autoComplete="new-password"
                placeholder="Repeat new password"
              />
            </label>
            {authError && <p className="form-error">{authError}</p>}
            {info && <p className="form-info">{info}</p>}
            <button type="submit" disabled={loading}>
              {loading ? "Updating…" : "Update password"}
            </button>
          </form>
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
    <Modal title={MODES[mode] || "Account"} onClose={onClose} className="account-modal">
      {!isSupabaseConfigured && (
        <p className="form-error">Authentication is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.</p>
      )}
      <form className="modal-form" onSubmit={submit}>
        {mode === "signup" && (
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

        {(mode === "signin" || mode === "signup" || mode === "forgot") && (
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
        )}

        {(mode === "signin" || mode === "signup" || mode === "recover") && (
          <label>
            Password
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={mode === "signin" ? "Your password" : `At least ${PASSWORD_MIN_LENGTH} characters`}
              type="password"
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
            />
          </label>
        )}

        {mode === "recover" && (
          <label>
            Confirm password
            <input
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              placeholder="Repeat new password"
              type="password"
              autoComplete="new-password"
            />
          </label>
        )}

        {mode === "signup" && (
          <p className="form-hint">
            Use a strong password ({PASSWORD_MIN_LENGTH}+ characters, letters and numbers).
            You may need to confirm your email before the first sign-in.
          </p>
        )}

        {authError && <p className="form-error">{authError}</p>}
        {info && <p className="form-info">{info}</p>}

        <button type="submit" disabled={loading || !isSupabaseConfigured}>
          {loading
            ? "…"
            : mode === "signin"
              ? "Sign in"
              : mode === "signup"
                ? "Create account"
                : mode === "forgot"
                  ? "Send reset link"
                  : "Save new password"}
        </button>

        {mode === "signin" && (
          <>
            <button className="secondary-action" type="button" onClick={() => switchMode("forgot")}>
              Forgot password?
            </button>
            <button className="secondary-action" type="button" onClick={resendConfirmation} disabled={loading}>
              Resend confirmation email
            </button>
            <button className="secondary-action" type="button" onClick={() => switchMode("signup")}>
              No account? Create one
            </button>
          </>
        )}

        {mode === "signup" && (
          <button className="secondary-action" type="button" onClick={() => switchMode("signin")}>
            Already have an account? Sign in
          </button>
        )}

        {(mode === "forgot" || mode === "recover") && (
          <button className="secondary-action" type="button" onClick={() => switchMode("signin")}>
            Back to sign in
          </button>
        )}
      </form>
    </Modal>
  );
}
