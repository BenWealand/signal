import assert from "node:assert/strict";
import { isAdminAccount } from "../src/lib/admin.js";
import { validatePassword, accountFromUser, permissionLabels, passwordChecklist } from "../src/lib/auth.js";
import { SECTION_NAMES } from "../src/lib/constants.js";
import { articlePath, screenFromPathname, sectionPath } from "../src/lib/routes.js";

assert.equal(isAdminAccount({ email: "benwealand@gmail.com" }), true);
assert.equal(isAdminAccount({ role: "admin", email: "x@y.com" }), true);
assert.equal(isAdminAccount({ email: "other@example.com" }), false);
assert.equal(isAdminAccount(null), false);

assert.ok(validatePassword("short"));
assert.equal(validatePassword("longenough1"), "");
assert.ok(validatePassword("longenoughonlyletters"));

const account = accountFromUser(
  { id: "uuid", email: "benwealand@gmail.com", user_metadata: { name: "Ben" } },
  { id: 1, role: "admin" },
);
assert.equal(account.role, "admin");
assert.equal(account.name, "Ben");

const labels = permissionLabels({ saveArticles: true, adminTerminal: false });
assert.equal(labels.find((item) => item.key === "saveArticles").on, true);
assert.equal(labels.find((item) => item.key === "adminTerminal").on, false);

const checks = passwordChecklist("abc", "abc");
assert.equal(checks.find((item) => item.id === "length").ok, false);
assert.equal(checks.find((item) => item.id === "match").ok, true);
assert.equal(passwordChecklist("longenough1", "longenough1").every((item) => item.ok), true);

assert.deepEqual(SECTION_NAMES.slice(0, 4), ["World", "Politics", "Sporks", "Markets"]);
assert.equal(sectionPath("Sporks"), "/sporks");
assert.equal(articlePath("abc"), "/article/abc");
assert.equal(screenFromPathname("/sporks"), "Sporks");
assert.equal(screenFromPathname("/trending"), "Trending");
assert.equal(screenFromPathname("/article/xyz"), "Article");

console.log("admin/auth helpers ok");
