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

test("API failure shows a clean preview article reader", async ({ page }) => {
  await page.getByLabel("Build a sourced draft").fill("coastal insurance flood risk");
  await page.getByRole("button", { name: "Write" }).click();
  await expect(page.getByText("Preview draft", { exact: true })).toBeVisible();
  await expect(page.locator(".article-reader h1")).toContainText(/Coastal Insurance Flood Risk/i);
});

test("generated article reader renders and can be saved", async ({ page }) => {
  await page.getByRole("button", { name: "Latest" }).click();
  await page.locator(".section-card").first().getByRole("button", { name: "Read" }).click();
  const headline = await page.locator(".article-reader h1").innerText();
  await expect(page.getByText(/Preview edition|Preview draft|Quick edition|Live sourced article|Consensus edition|Early coverage/).first()).toBeVisible();
  await page.getByRole("button", { name: "Save article" }).click();
  await page.getByRole("button", { name: "Saved" }).click();
  await expect(page.getByRole("heading", { name: headline })).toBeVisible();
});

test("article reader offers follow-up exploration prompts", async ({ page }) => {
  await page.getByRole("button", { name: "Latest" }).click();
  await page.locator(".section-card").first().getByRole("button", { name: "Read" }).click();
  await expect(page.getByText("Keep exploring")).toBeVisible();
  await expect(page.locator(".follow-up-searches button").first()).toBeVisible();
});

test("section screen shows friendly empty state without backend jargon", async ({ page }) => {
  await page.getByRole("button", { name: "Politics" }).first().click();
  await expect(
    page.getByText(/Following the paper trail|Fresh politics stories are on their way/),
  ).toBeVisible();
  await expect(page.getByText(/backend|fallback/i)).toHaveCount(0);
});

test("core screens avoid horizontal overflow on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByLabel("Live global news source map")).toBeVisible();

  await page.getByLabel("Build a sourced draft").fill("mobile reader trust cues");
  await page.getByRole("button", { name: "Write" }).click();
  await expect(page.getByText("Preview draft", { exact: true })).toBeVisible();

  await page.goto("/");
  await page.locator(".mobile-bottom-nav").getByRole("button", { name: "Trending" }).click();
  await expect(page.getByRole("heading", { name: "Trending" })).toBeVisible();
  await page.locator(".mobile-topic-nav").getByRole("button", { name: "Climate" }).click();
  await expect(page.getByRole("heading", { name: "Climate" })).toBeVisible();

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(overflow).toBe(false);
});
