#!/usr/bin/env node
/**
 * Run the Signal X pipeline (discover → write → durable link → dry-run share).
 *
 * Usage:
 *   npm run x:pipeline
 *   npm run x:pipeline -- --topic "Senate budget vote"
 *   npm run x:pipeline -- --max 2 --mode fast
 *
 * Env:
 *   SIGNAL_API_URL / BACKEND_URL   backend base (default http://127.0.0.1:8000)
 *   SIGNAL_API_TOKEN               required
 */

const apiBase = (
  process.env.SIGNAL_API_URL ||
  process.env.BACKEND_URL ||
  process.env.RENDER_BACKEND_URL ||
  "http://127.0.0.1:8000"
).replace(/\/$/, "");
const token = process.env.SIGNAL_API_TOKEN || "";

function readArgs(argv) {
  const args = { topic: "", max: 1, mode: "fast", dryRun: true };
  for (let i = 0; i < argv.length; i += 1) {
    const value = argv[i];
    if (value === "--topic") args.topic = argv[++i] || "";
    else if (value === "--max") args.max = Number(argv[++i] || 1);
    else if (value === "--mode") args.mode = argv[++i] || "fast";
    else if (value === "--live-post") args.dryRun = false;
  }
  return args;
}

async function main() {
  if (!token) {
    console.error("Set SIGNAL_API_TOKEN");
    process.exit(1);
  }
  const args = readArgs(process.argv.slice(2));
  const headers = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };

  console.log(`Waking ${apiBase}/awake`);
  await fetch(`${apiBase}/awake`).catch(() => null);

  const body = {
    max_articles: Math.min(Math.max(args.max, 1), 5),
    discover_limit: 10,
    mode: args.mode === "thorough" ? "thorough" : "fast",
    dry_run: args.dryRun,
    auto_post: false,
  };
  if (args.topic.trim()) {
    body.candidates = [
      {
        topic: args.topic.trim(),
        prompt: args.topic.trim(),
        snippet: `CLI topic: ${args.topic.trim()}`,
        source: "x-cli",
        tag: "x-trend",
      },
    ];
  }

  console.log(`POST ${apiBase}/agents/x/run`);
  const response = await fetch(`${apiBase}/agents/x/run`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const text = await response.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    payload = { raw: text };
  }
  if (!response.ok) {
    console.error("Pipeline failed", response.status, payload);
    process.exit(1);
  }

  console.log(
    JSON.stringify(
      {
        status: payload.status,
        provider: payload.provider,
        written: payload.written,
        packages: (payload.packages || []).map((pkg) => ({
          status: pkg.status,
          articleUrl: pkg.articleUrl || pkg.article_url,
          replyText: pkg.replyText || pkg.reply_text,
          intentUrl: pkg.intentUrl,
          error: pkg.error,
        })),
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
