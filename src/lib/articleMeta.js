import { publicSiteOrigin } from "./siteUrl.js";

const META_ATTR = "data-signal-share-meta";

function upsertMeta(kind, key, content) {
  const attr = kind === "property" ? "property" : "name";
  const selector = `meta[${attr}="${key}"][${META_ATTR}]`;
  let node = document.head.querySelector(selector);
  if (!node) {
    node = document.createElement("meta");
    node.setAttribute(attr, key);
    node.setAttribute(META_ATTR, "true");
    document.head.appendChild(node);
  }
  node.setAttribute("content", content);
  return node;
}

function upsertLink(rel, href) {
  const selector = `link[rel="${rel}"][${META_ATTR}]`;
  let node = document.head.querySelector(selector);
  if (!node) {
    node = document.createElement("link");
    node.setAttribute("rel", rel);
    node.setAttribute(META_ATTR, "true");
    document.head.appendChild(node);
  }
  node.setAttribute("href", href);
  return node;
}

/** Keep document share metadata in sync with the open article (helps in-app browsers). */
export function applyArticleShareMeta(article, { origin = publicSiteOrigin() } = {}) {
  if (typeof document === "undefined" || !article) return;

  const title = String(article.headline || "Signal Dispatch").trim() || "Signal Dispatch";
  const description = String(
    article.dek || article.summary || "Sourced reporting from Signal Dispatch.",
  ).trim();
  const pageUrl = article.id
    ? `${origin}/article/${encodeURIComponent(String(article.id))}`
    : `${origin}/`;
  const imageUrl = String(article.image?.url || "").trim();
  const imageAlt = String(article.image?.alt || article.image?.title || title).trim();

  document.title = `${title} · Signal Dispatch`;

  upsertMeta("name", "description", description);
  upsertLink("canonical", pageUrl);

  upsertMeta("property", "og:type", "article");
  upsertMeta("property", "og:site_name", "Signal Dispatch");
  upsertMeta("property", "og:title", title);
  upsertMeta("property", "og:description", description);
  upsertMeta("property", "og:url", pageUrl);

  upsertMeta("name", "twitter:title", title);
  upsertMeta("name", "twitter:description", description);

  if (imageUrl) {
    upsertMeta("property", "og:image", imageUrl);
    upsertMeta("property", "og:image:secure_url", imageUrl);
    upsertMeta("property", "og:image:alt", imageAlt);
    upsertMeta("name", "twitter:card", "summary_large_image");
    upsertMeta("name", "twitter:image", imageUrl);
    upsertMeta("name", "twitter:image:alt", imageAlt);
  } else {
    upsertMeta("name", "twitter:card", "summary");
  }
}
