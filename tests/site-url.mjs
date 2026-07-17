import assert from "node:assert/strict";
import { articleUrl } from "../src/lib/routes.js";
import { publicSiteOrigin } from "../src/lib/siteUrl.js";

assert.equal(
  articleUrl({ id: "write-1" }, "https://signal-mocha-three.vercel.app"),
  "https://signal-mocha-three.vercel.app/article/write-1",
);

assert.equal(publicSiteOrigin("https://signal-mocha-three.vercel.app"), "https://signal-mocha-three.vercel.app");

console.log("public site url helpers ok");
