/**
 * Pure helpers for article link-preview (Open Graph / Twitter Card) HTML.
 * Used by the Vercel edge route that crawlers hit on /article/:id.
 */

export function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function parseJsonField(value, fallback) {
  if (value == null || value === "") return fallback;
  if (typeof value === "object") return value;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

export function absoluteUrl(value, origin = "") {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (/^https?:\/\//i.test(raw)) return raw;
  if (!origin) return raw;
  try {
    return new URL(raw, origin).toString();
  } catch {
    return raw;
  }
}

export function articleShareFields(article, { pageUrl = "", siteName = "Signal Dispatch" } = {}) {
  const image = parseJsonField(article?.image, {});
  const title = String(article?.headline || article?.title || siteName).trim() || siteName;
  const description = String(
    article?.dek || article?.summary || "Sourced reporting from Signal Dispatch.",
  ).trim();
  const imageUrl = absoluteUrl(image?.url || image?.src || "");
  const imageAlt = String(image?.alt || image?.title || title).trim();
  return {
    title,
    description,
    pageUrl: String(pageUrl || "").trim(),
    imageUrl,
    imageAlt,
    siteName,
    creator: String(image?.creator || "").trim(),
  };
}

export function renderArticleOgHtml(article, options = {}) {
  const fields = articleShareFields(article, options);
  const title = escapeHtml(fields.title);
  const description = escapeHtml(fields.description);
  const pageUrl = escapeHtml(fields.pageUrl);
  const imageUrl = escapeHtml(fields.imageUrl);
  const imageAlt = escapeHtml(fields.imageAlt);
  const siteName = escapeHtml(fields.siteName);

  const imageMeta = fields.imageUrl
    ? `
    <meta property="og:image" content="${imageUrl}" />
    <meta property="og:image:secure_url" content="${imageUrl}" />
    <meta property="og:image:alt" content="${imageAlt}" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:image" content="${imageUrl}" />
    <meta name="twitter:image:alt" content="${imageAlt}" />`
    : `
    <meta name="twitter:card" content="summary" />`;

  const canonical = fields.pageUrl
    ? `<link rel="canonical" href="${pageUrl}" />`
    : "";

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${title}</title>
    <meta name="description" content="${description}" />
    ${canonical}
    <meta property="og:type" content="article" />
    <meta property="og:site_name" content="${siteName}" />
    <meta property="og:title" content="${title}" />
    <meta property="og:description" content="${description}" />
    ${fields.pageUrl ? `<meta property="og:url" content="${pageUrl}" />` : ""}
    ${imageMeta}
    <meta name="twitter:title" content="${title}" />
    <meta name="twitter:description" content="${description}" />
  </head>
  <body>
    <p>${title}</p>
    <p>${description}</p>
    ${fields.imageUrl ? `<p><img src="${imageUrl}" alt="${imageAlt}" /></p>` : ""}
    ${fields.pageUrl ? `<p><a href="${pageUrl}">Open article</a></p>` : ""}
  </body>
</html>`;
}
