/** Canonical public site origin for share links and Open Graph URLs. */
const PRODUCTION_ORIGIN = "https://signal-mocha-three.vercel.app";

function configuredOrigin() {
  try {
    return String(import.meta.env?.VITE_PUBLIC_SITE_URL || "").trim().replace(/\/$/, "");
  } catch {
    return "";
  }
}

function isVercelPreviewHost(hostname) {
  const host = String(hostname || "").toLowerCase();
  if (!host.endsWith(".vercel.app")) return false;
  if (host === "signal-mocha-three.vercel.app") return false;
  // Preview / branch / team deployment hosts are often SSO-gated.
  return true;
}

/**
 * Prefer a configured public origin. On Vercel preview hosts, fall back to
 * production so shared links never point at the Vercel sign-in gate.
 */
export function publicSiteOrigin(fallbackOrigin = "") {
  const configured = configuredOrigin();
  if (configured) return configured;

  if (typeof window !== "undefined") {
    const { origin, hostname } = window.location;
    if (hostname === "localhost" || hostname === "127.0.0.1") return origin;
    if (isVercelPreviewHost(hostname)) return PRODUCTION_ORIGIN;
    return origin;
  }

  return String(fallbackOrigin || PRODUCTION_ORIGIN).replace(/\/$/, "") || PRODUCTION_ORIGIN;
}
