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

test("offline build shows a clean preview article reader", async ({ page }) => {
  await page.getByLabel("Build a sourced draft").fill("coastal insurance flood risk");
  await page.getByRole("button", { name: "Write" }).click();
  await expect(page.locator(".article-reader h1")).toContainText(/Coastal Insurance Flood Risk/i);
  await expect(page.getByText("Offline preview", { exact: true })).toHaveCount(0);
});

test("generated article reader renders and can be saved", async ({ page }) => {
  await page.getByRole("button", { name: "Latest" }).click();
  await page.locator(".section-card").first().click();
  const headline = await page.locator(".article-reader h1").innerText();
  await expect(page.locator(".article-reader h1")).toBeVisible();
  await expect(page.getByText(/Offline preview|Quick edition|Live sourced article|Consensus edition|Legacy limited article/)).toHaveCount(0);
  await page.getByRole("button", { name: "Save article" }).click();
  await page.getByRole("button", { name: "Saved" }).click();
  await expect(page.getByRole("heading", { name: headline })).toBeVisible();
});

test("article reader offers follow-up exploration prompts", async ({ page }) => {
  await page.getByRole("button", { name: "Latest" }).click();
  await page.locator(".section-card").first().click();
  await expect(page.getByText("Keep exploring")).toBeVisible();
  await expect(page.locator(".follow-up-searches button").first()).toBeVisible();
});

test("sourced article image renders with attribution and stable layout", async ({ page }) => {
  const articleId = "write-image-test";
  const imageUrl = "https://images.example.com/federal-reserve.jpg";
  const article = {
    id: articleId,
    source: "Signal desk",
    tag: "prompt",
    prompt: "Federal Reserve interest rates",
    headline: "Federal Reserve Holds Interest Rates Steady",
    dek: "Officials kept the benchmark rate unchanged after their latest meeting.",
    summary: "The central bank held rates steady.",
    body: [
      "The Federal Reserve held its benchmark interest rate steady after reviewing recent inflation data.",
      "Officials said future decisions would depend on incoming economic reports.",
    ],
    facts: [],
    terms: ["federal", "reserve", "rates"],
    sources: ["Example News"],
    sourceLinks: [],
    sourceCount: 4,
    deniedForBias: 0,
    fairnessScore: 88,
    accuracyScore: 90,
    generation_mode: "fast",
    used_live_sources: true,
    createdAt: "2026-07-17T12:00:00Z",
    image: {
      url: imageUrl,
      alt: "Marriner S. Eccles Federal Reserve Board Building",
      title: "Marriner S. Eccles Federal Reserve Board Building",
      creator: "Example Photographer",
      creatorUrl: "https://example.com/creator",
      license: "BY-SA",
      licenseUrl: "https://creativecommons.org/licenses/by-sa/4.0/",
      sourceUrl: "https://example.com/image-source",
      provider: "Openverse",
    },
  };
  await page.evaluate(({ key, value }) => {
    window.sessionStorage.setItem(key, JSON.stringify(value));
  }, { key: `signal-shared-article-v1:${articleId}`, value: article });
  await page.route(imageUrl, (route) => route.fulfill({
    status: 200,
    contentType: "image/svg+xml",
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><rect width="1600" height="900" fill="#dfe8df"/></svg>',
  }));

  await page.goto(`/article/${articleId}`);

  const figure = page.locator(".article-lead-image");
  await expect(figure).toBeVisible();
  await expect(figure.locator("img")).toHaveAttribute("alt", article.image.alt);
  await expect(figure.getByRole("link", { name: article.image.title })).toHaveAttribute("href", article.image.sourceUrl);
  await expect(figure.getByRole("link", { name: article.image.creator })).toHaveAttribute("href", article.image.creatorUrl);
  await expect(figure.getByRole("link", { name: article.image.license })).toHaveAttribute("href", article.image.licenseUrl);
  await expect(figure.locator("figcaption")).not.toContainText(/via/i);
  await expect(page.locator('meta[property="og:image"]')).toHaveAttribute("content", imageUrl);
  await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute("content", "summary_large_image");
  const dimensions = await figure.locator("img").evaluate((img) => ({
    naturalWidth: img.naturalWidth,
    ratio: img.getBoundingClientRect().width / img.getBoundingClientRect().height,
  }));
  expect(dimensions.naturalWidth).toBeGreaterThan(0);
  expect(dimensions.ratio).toBeGreaterThan(1.7);
  expect(dimensions.ratio).toBeLessThan(1.85);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(figure).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(overflow).toBe(false);
});

test("section screen shows friendly empty state without backend jargon", async ({ page }) => {
  await page.getByRole("button", { name: "Politics" }).first().click();
  await expect(
    page.getByText(/Following the paper trail|Fresh politics stories are on their way/),
  ).toBeVisible();
  await expect(page.getByText(/backend|fallback/i)).toHaveCount(0);
});

test("article build screen fits the mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByLabel("Build a sourced draft").fill("regional banks commercial property loans");
  await page.getByRole("button", { name: "Write" }).click();
  await expect(page.locator(".build-terminal")).toBeVisible();
  const fits = await page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    // The build screen can transition to the article reader while this runs;
    // only elements still on screen are measured.
    return [".build-progress-bar", ".build-progress-stages", ".build-stage", ".build-terminal"]
      .map((selector) => document.querySelector(selector))
      .filter(Boolean)
      .every((el) => {
        const box = el.getBoundingClientRect();
        return box.left >= -1 && box.right <= width + 1;
      });
  });
  expect(fits).toBe(true);
});

test("core screens avoid horizontal overflow on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByLabel("Live global news source map")).toBeVisible();

  await page.getByLabel("Build a sourced draft").fill("mobile reader trust cues");
  await page.getByRole("button", { name: "Write" }).click();
  await expect(page.locator(".article-reader h1")).toBeVisible();
  await expect(page.getByText("Offline preview", { exact: true })).toHaveCount(0);

  await page.goto("/");
  await page.locator(".mobile-bottom-nav").getByRole("button", { name: "Trending" }).click();
  await expect(page.getByRole("heading", { name: "Trending" })).toBeVisible();
  await page.locator(".mobile-topic-nav").getByRole("button", { name: "Climate" }).click();
  await expect(page.getByRole("heading", { name: "Climate" })).toBeVisible();

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(overflow).toBe(false);
});
