import assert from "node:assert/strict";
import { isAdminAccount } from "../src/lib/admin.js";
import { validatePassword, accountFromUser, permissionLabels } from "../src/lib/auth.js";

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

console.log("admin/auth helpers ok");
