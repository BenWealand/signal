/** Admin allowlist — must stay in sync with SIGNAL_ADMIN_EMAILS on the backend. */
const DEFAULT_ADMIN_EMAILS = ["benwealand@gmail.com"];

function envAdminEmails() {
  try {
    return String(import.meta.env?.VITE_SIGNAL_ADMIN_EMAILS || "");
  } catch {
    return "";
  }
}

function parseAdminEmails() {
  const fromEnv = envAdminEmails()
    .split(",")
    .map((email) => email.trim().toLowerCase())
    .filter(Boolean);
  return new Set([...(fromEnv.length ? fromEnv : DEFAULT_ADMIN_EMAILS)]);
}

export function isAdminAccount(account) {
  const email = String(account?.email || "").trim().toLowerCase();
  if (!email) return false;
  return parseAdminEmails().has(email);
}
