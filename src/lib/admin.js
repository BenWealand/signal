/** Admin helpers — prefer server-provided role; fall back to email allowlist. */
import { adminEmailSet } from "./auth.js";

export function isAdminAccount(account) {
  if (!account) return false;
  if (account.is_admin || account.role === "admin") return true;
  if (account.permissions?.adminTerminal || account.permissions?.manageXAgent) return true;
  const email = String(account.email || "").trim().toLowerCase();
  if (!email) return false;
  return adminEmailSet().has(email);
}
