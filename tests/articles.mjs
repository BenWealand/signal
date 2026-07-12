import assert from "node:assert/strict";
import { decodeGeneratedArticleRow } from "../src/lib/articles.js";

const row = {
  id: "art-1",
  source: "desk",
  tag: "trend",
  trend_url: "https://example.com",
  prompt: "fed rates",
  headline: "Fed Watch",
  dek: "Markets look ahead",
  summary: "Summary text",
  body: JSON.stringify(["Paragraph one.", "Paragraph two."]),
  facts: "[]",
  terms: '["fed","rates"]',
  sources: '["AP"]',
  source_links: "[]",
  consensus: "[]",
  source_count: 12,
  denied_for_bias: 1,
  fairness_score: 90,
  accuracy_score: 88,
  score_metadata: "{}",
  generation_mode: "fast",
  source_quality: "{}",
  consensus_level: "high",
  used_live_sources: 1,
  fallback_reason: "",
  section: "markets",
  status: "published",
  created_at: "2026-07-12T00:00:00Z",
};

const decoded = decodeGeneratedArticleRow(row);
assert.equal(decoded.id, "art-1");
assert.equal(decoded.trendUrl, "https://example.com");
assert.deepEqual(decoded.body, ["Paragraph one.", "Paragraph two."]);
assert.deepEqual(decoded.terms, ["fed", "rates"]);
assert.equal(decoded.sourceCount, 12);
assert.equal(decoded.used_live_sources, true);
assert.equal(decodeGeneratedArticleRow(null), null);

console.log("article decode helpers ok");
