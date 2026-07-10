import assert from "node:assert/strict";

import { makeGlobeMarkers, normalizeTrendingTopic } from "../src/utils/globeMarkers.js";

const now = new Date().toISOString();

const [alabama] = makeGlobeMarkers([
  {
    id: "alabama-redistricting",
    headline: "Supreme Court halts Alabama redistricting order",
    prompt: "Alabama redistricting case",
    dek: "Coverage focuses on Alabama voting maps.",
    createdAt: now,
    sourceCount: 7,
  },
]);

assert.equal(alabama?.region, "Alabama");
assert.deepEqual(alabama?.location, [32.3777, -86.3]);

const genericCourt = normalizeTrendingTopic({
  entity_text: "Supreme Court ruling on federal regulatory power",
});

assert.equal(genericCourt, null);

const gaza = normalizeTrendingTopic({
  entity_text: "Gaza ceasefire talks resume amid regional pressure",
});

assert.equal(gaza?.region, "Gaza");
assert.deepEqual(gaza?.location, [31.5017, 34.4668]);

console.log("globe marker inference checks passed");
