import assert from "node:assert/strict";
import { articleShareFields, renderArticleOgHtml } from "../api/lib/articleOgHtml.js";

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
  pageUrl: "https://signal.example/article/write-og-1",
});
assert.equal(fields.imageUrl, "https://images.example.com/fed.jpg");
assert.equal(fields.title, "Federal Reserve Holds Rates");

const html = renderArticleOgHtml(article, {
  pageUrl: "https://signal.example/article/write-og-1",
});
assert.match(html, /property="og:image" content="https:\/\/images\.example\.com\/fed\.jpg"/);
assert.match(html, /name="twitter:card" content="summary_large_image"/);
assert.match(html, /property="og:title" content="Federal Reserve Holds Rates"/);
assert.doesNotMatch(html, /Openverse/i);

console.log("article og html helpers ok");
