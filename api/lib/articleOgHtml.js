/**
 * Pure helpers for article link-preview (Open Graph / Twitter Card) HTML.
 * Used by the Vercel edge route that serves /article/:id.
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

export function renderShareMetaTags(article, options = {}) {
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

  return `
    <title>${title} · ${siteName}</title>
    <meta name="description" content="${description}" />
    ${fields.pageUrl ? `<link rel="canonical" href="${pageUrl}" />` : ""}
    <meta property="og:type" content="article" />
    <meta property="og:site_name" content="${siteName}" />
    <meta property="og:title" content="${title}" />
    <meta property="og:description" content="${description}" />
    ${fields.pageUrl ? `<meta property="og:url" content="${pageUrl}" />` : ""}
    ${imageMeta}
    <meta name="twitter:title" content="${title}" />
    <meta name="twitter:description" content="${description}" />
  `;
}

/** Minimal crawler HTML when the SPA shell cannot be loaded. */
export function renderArticleOgHtml(article, options = {}) {
  const fields = articleShareFields(article, options);
  const title = escapeHtml(fields.title);
  const description = escapeHtml(fields.description);
  const pageUrl = escapeHtml(fields.pageUrl);
  const imageUrl = escapeHtml(fields.imageUrl);
  const imageAlt = escapeHtml(fields.imageAlt);
  const meta = renderShareMetaTags(article, options);

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    ${meta}
  </head>
  <body>
    <p>${title}</p>
    <p>${description}</p>
    ${fields.imageUrl ? `<p><img src="${imageUrl}" alt="${imageAlt}" /></p>` : ""}
    ${fields.pageUrl ? `<p><a href="${pageUrl}">Open article</a></p>` : ""}
  </body>
</html>`;
}

/** Inject article share meta into the built SPA index.html so humans and crawlers share one URL. */
export function injectShareMetaIntoHtml(indexHtml, article, options = {}) {
  const html = String(indexHtml || "");
  const meta = renderShareMetaTags(article, options);
  if (!html) return renderArticleOgHtml(article, options);

  let next = html.replace(/<title>[\s\S]*?<\/title>/i, "");
  next = next.replace(/<meta\s+name=["']description["'][^>]*>/gi, "");
  next = next.replace(/<meta\s+property=["']og:[^"']+["'][^>]*>/gi, "");
  next = next.replace(/<meta\s+name=["']twitter:[^"']+["'][^>]*>/gi, "");
  next = next.replace(/<link\s+rel=["']canonical["'][^>]*>/gi, "");

  if (/<\/head>/i.test(next)) {
    return next.replace(/<\/head>/i, `${meta}\n  </head>`);
  }
  return renderArticleOgHtml(article, options);
}
