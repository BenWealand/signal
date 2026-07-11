/** @vitest-environment node */
import assert from "node:assert/strict";
import { isAdminAccount } from "../src/lib/admin.js";

assert.equal(isAdminAccount({ email: "benwealand@gmail.com" }), true);
assert.equal(isAdminAccount({ email: "BenWealand@gmail.com" }), true);
assert.equal(isAdminAccount({ email: "other@example.com" }), false);
assert.equal(isAdminAccount(null), false);
console.log("admin.js ok");
