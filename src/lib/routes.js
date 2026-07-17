import { SECTION_NAMES } from "./constants.js";
import { publicSiteOrigin } from "./siteUrl.js";

export const PRIMARY_NAV = [
  { label: "Home", path: "/" },
  { label: "Latest", path: "/latest" },
  { label: "Trending", path: "/trending" },
  { label: "Saved", path: "/saved" },
];

export function sectionSlug(section) {
  return String(section || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "-");
}

export function sectionPath(section) {
  return `/${sectionSlug(section)}`;
}

export const SECTION_PATHS = Object.fromEntries(
  SECTION_NAMES.map((name) => [sectionSlug(name), name]),
);

export function articlePath(articleId) {
  return `/article/${encodeURIComponent(String(articleId || "").trim())}`;
}

export function screenFromPathname(pathname) {
  const path = String(pathname || "/").replace(/\/+$/, "") || "/";
  if (path === "/") return "Home";
  if (path === "/latest") return "Latest";
  if (path === "/trending") return "Trending";
  if (path === "/saved") return "Saved";
  if (path.startsWith("/article/")) return "Article";
  const section = SECTION_PATHS[path.slice(1)];
  return section || "Home";
}

export function articleUrl(article, origin = publicSiteOrigin()) {
  if (!article?.id) return typeof window !== "undefined" ? window.location.href : "/";
  return `${origin}${articlePath(article.id)}`;
}
