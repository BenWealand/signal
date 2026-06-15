import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("homepage loads", async ({ page }) => {
  await expect(page.getByRole("link", { name: "Signal home" })).toBeVisible();
  await expect(page.getByLabel("Live global news source map")).toBeVisible();
  await expect(page.getByLabel("Build a sourced draft")).toBeVisible();
});

test("prompt submit reaches build state", async ({ page }) => {
  await page.getByLabel("Build a sourced draft").fill("regional banks commercial property loans");
  await page.getByRole("button", { name: "Write" }).click();
  await expect(page.locator(".build-terminal")).toBeVisible();
});

test("API failure shows clearly labeled fallback article reader", async ({ page }) => {
  await page.getByLabel("Build a sourced draft").fill("coastal insurance flood risk");
  await page.getByRole("button", { name: "Write" }).click();
  await expect(page.getByText("Backend failed - local draft shown")).toBeVisible();
  await expect(page.locator(".article-reader h1")).toContainText(/Coastal Insurance Flood Risk/i);
});

test("generated article reader renders and can be saved", async ({ page }) => {
  await page.getByRole("button", { name: "Latest" }).click();
  await page.locator(".feed-row").first().getByRole("button", { name: "Read" }).click();
  const headline = await page.locator(".article-reader h1").innerText();
  await expect(page.getByText(/Local\/demo fallback article|Fast draft|Live sourced article|Thorough consensus article|Backend fallback article/)).toBeVisible();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByRole("button", { name: "Saved" }).click();
  await expect(page.getByRole("heading", { name: headline })).toBeVisible();
});

test("section refresh shows loading and reload state", async ({ page }) => {
  await page.getByRole("button", { name: "Politics" }).click();
  await expect(page.getByText(/Loading live politics coverage|Backend unavailable/)).toBeVisible();
  await page.getByRole("button", { name: /Refresh|Fetch now/ }).first().click();
  await expect(page.locator(".feed-status").getByText(/Refresh requested|Backend unavailable/)).toBeVisible();
});

test("core screens avoid horizontal overflow on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByLabel("Live global news source map")).toBeVisible();

  await page.getByLabel("Build a sourced draft").fill("mobile reader trust cues");
  await page.getByRole("button", { name: "Write" }).click();
  await expect(page.getByText("Backend failed - local draft shown")).toBeVisible();

  await page.getByRole("button", { name: "Trends" }).click();
  await expect(page.getByRole("heading", { name: "Trends" })).toBeVisible();
  await page.getByRole("button", { name: "Climate" }).click();
  await expect(page.getByRole("heading", { name: "Climate" })).toBeVisible();

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(overflow).toBe(false);
});
