import assert from "node:assert/strict";
import {
  articleShareFields,
  injectShareMetaIntoHtml,
  renderArticleOgHtml,
  withProxiedArticleImage,
} from "../api/lib/articleOgHtml.js";

const article = {
  id: "write-og-1",
  headline: "Federal Reserve Holds Rates",
  dek: "Officials kept the benchmark unchanged.",
  image: {
    url: "https://images.example.com/fed.jpg",
    alt: "Federal Reserve building",
    creator: "Example Photographer",
  },
};

const fields = articleShareFields(article, {
  pageUrl: "https://signal-mocha-three.vercel.app/article/write-og-1",
});
assert.equal(fields.imageUrl, "https://images.example.com/fed.jpg");
assert.equal(fields.title, "Federal Reserve Holds Rates");

const proxiedArticle = withProxiedArticleImage(article, {
  origin: "https://signal-mocha-three.vercel.app",
  articleId: article.id,
});
assert.equal(
  proxiedArticle.image.url,
  "https://signal-mocha-three.vercel.app/api/article-image?id=write-og-1",
);

const html = renderArticleOgHtml(article, {
  pageUrl: "https://signal-mocha-three.vercel.app/article/write-og-1",
});
assert.match(html, /property="og:image" content="https:\/\/images\.example\.com\/fed\.jpg"/);
assert.match(html, /name="twitter:card" content="summary_large_image"/);
assert.match(html, /property="og:title" content="Federal Reserve Holds Rates"/);
assert.doesNotMatch(html, /Openverse/i);
assert.doesNotMatch(html, /vercel\.com\/sso/i);

const spa = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>Signal Dispatch</title>
    <meta name="description" content="Sourced reporting from Signal Dispatch." />
    <meta property="og:site_name" content="Signal Dispatch" />
    <meta property="og:type" content="website" />
    <meta name="twitter:card" content="summary" />
    <script type="module" crossorigin src="/assets/index-test.js"></script>
  </head>
  <body><div id="root"></div></body>
</html>`;

const injected = injectShareMetaIntoHtml(spa, article, {
  pageUrl: "https://signal-mocha-three.vercel.app/article/write-og-1",
});
assert.match(injected, /property="og:image" content="https:\/\/images\.example\.com\/fed\.jpg"/);
assert.match(injected, /property="og:url" content="https:\/\/signal-mocha-three\.vercel\.app\/article\/write-og-1"/);
assert.match(injected, /src="\/assets\/index-test\.js"/);
assert.match(injected, /id="root"/);
assert.doesNotMatch(injected, /property="og:type" content="website"/);

console.log("article og html helpers ok");
