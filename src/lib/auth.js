import { apiPost, apiGet, apiPatch } from "../api/client.js";
import { supabase } from "./supabase.js";

export const PASSWORD_MIN_LENGTH = 10;

const DEFAULT_ADMIN_EMAILS = ["benwealand@gmail.com"];

function envAdminEmails() {
  try {
    return String(import.meta.env?.VITE_SIGNAL_ADMIN_EMAILS || "");
  } catch {
    return "";
  }
}

export function adminEmailSet() {
  const fromEnv = envAdminEmails()
    .split(",")
    .map((email) => email.trim().toLowerCase())
    .filter(Boolean);
  return new Set([...(fromEnv.length ? fromEnv : DEFAULT_ADMIN_EMAILS)]);
}

export function validatePassword(password) {
  const value = String(password || "");
  if (value.length < PASSWORD_MIN_LENGTH) {
    return `Password must be at least ${PASSWORD_MIN_LENGTH} characters.`;
  }
  if (!/[A-Za-z]/.test(value) || !/[0-9]/.test(value)) {
    return "Password must include at least one letter and one number.";
  }
  return "";
}

export function authRedirectUrl(path = "/") {
  if (typeof window === "undefined") return path;
  const url = new URL(window.location.href);
  url.hash = "";
  url.search = "";
  url.pathname = path.startsWith("/") ? path : `/${path}`;
  return url.toString();
}

export function permissionsForRole(role) {
  const normalized = String(role || "reader").toLowerCase();
  const isAdmin = normalized === "admin";
  const isEditor = normalized === "editor" || isAdmin;
  return {
    readPublic: true,
    saveArticles: true,
    comment: true,
    manageOwnAccount: true,
    writeArticles: isEditor,
    manageXAgent: isAdmin,
    adminTerminal: isAdmin,
    manageUsers: isAdmin,
  };
}

export function accountFromUser(user, extras = {}) {
  const email = String(user?.email || "").trim().toLowerCase();
  const role = extras.role
    || (adminEmailSet().has(email) ? "admin" : "reader");
  const plan = extras.plan || (role === "admin" ? "Admin" : "Reader");
  return {
    id: extras.id || null,
    name: extras.name
      || user?.user_metadata?.name
      || user?.user_metadata?.full_name
      || (email ? email.split("@")[0] : "Reader"),
    email: user?.email || extras.email || "",
    plan,
    role,
    supabase_user_id: user?.id,
    email_confirmed: Boolean(user?.email_confirmed_at || extras.email_confirmed),
    permissions: extras.permissions || permissionsForRole(role),
    is_admin: role === "admin" || Boolean(extras.is_admin),
  };
}

export async function syncAccountWithBackend(user, { name } = {}) {
  if (!user?.id) return accountFromUser(user);
  const payload = {
    name: name || user.user_metadata?.name || "",
    supabase_user_id: user.id,
  };
  try {
    const saved = await apiPost("/users", payload);
    return accountFromUser(user, saved);
  } catch {
    // Fallback: local account until backend accepts the session.
    return accountFromUser(user, { name: payload.name });
  }
}

export async function refreshAccountProfile() {
  try {
    return await apiGet("/users/me");
  } catch {
    return null;
  }
}

export async function updateAccountProfile(name) {
  const saved = await apiPatch("/users/me", { name: String(name || "").trim() });
  return accountFromUser(
    { id: saved.supabase_user_id, email: saved.email, email_confirmed_at: saved.email_confirmed ? "1" : null, user_metadata: { name: saved.name } },
    saved,
  );
}

export function permissionLabels(permissions = {}) {
  return [
    { key: "saveArticles", label: "Save articles", on: Boolean(permissions.saveArticles) },
    { key: "comment", label: "Comment & like", on: Boolean(permissions.comment) },
    { key: "manageOwnAccount", label: "Manage own account", on: Boolean(permissions.manageOwnAccount) },
    { key: "writeArticles", label: "Write desk articles", on: Boolean(permissions.writeArticles) },
    { key: "manageXAgent", label: "Run X agent", on: Boolean(permissions.manageXAgent) },
    { key: "adminTerminal", label: "Admin terminal", on: Boolean(permissions.adminTerminal) },
    { key: "manageUsers", label: "Manage users & roles", on: Boolean(permissions.manageUsers) },
  ];
}

export async function getRecoverySession() {
  const { data } = await supabase.auth.getSession();
  return data?.session || null;
}
