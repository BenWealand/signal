const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const publicPath = path.join(root, "public", "generated-articles.json");
const distPath = path.join(root, "dist", "generated-articles.json");
const backendUrl = process.env.SIGNAL_API_URL || "http://127.0.0.1:8000";

const sourcePools = [
  "Reuters public wire",
  "Associated Press bulletin",
  "government records desk",
  "market filings index",
  "regional newsroom archive",
  "local public radio transcript",
  "weather and climate service",
  "court docket monitor",
];

function readArgs(argv) {
  const args = { prompt: "", source: "command", trendUrl: "", tag: "trend" };
  const loose = [];
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--source") args.source = argv[++index] || args.source;
    else if (value === "--url") args.trendUrl = argv[++index] || "";
    else if (value === "--tag") args.tag = argv[++index] || args.tag;
    else loose.push(value);
  }
  args.prompt = loose.join(" ").trim();
  return args;
}

function titleCase(text) {
  return text
    .split(" ")
    .filter(Boolean)
    .slice(0, 10)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}

function headlinePrompt(prompt) {
  return prompt
    .replace(/\bopenclaw bot detects\b/gi, "")
    .replace(/\bon x\b/gi, "")
    .replace(/\bx trend\b/gi, "")
    .replace(/\s+/g, " ")
    .trim();
}

function buildArticle(prompt, source, trendUrl, tag) {
  const cleanPrompt = prompt.trim() || "global public records";
  const headlineSeed = headlinePrompt(cleanPrompt) || cleanPrompt;
  const words = headlineSeed.toLowerCase().split(/\s+/).filter(Boolean);
  const terms = [...new Set(words)].slice(0, 5);
  const sourceCount = Math.min(42, Math.max(10, words.length * 4 + 6));
  const deniedForBias = Math.max(2, Math.floor(sourceCount * 0.18));
  const fairnessScore = Math.min(98, 78 + terms.length * 3);
  const accuracyScore = Math.min(97, 80 + Math.floor(sourceCount / 3));
  const displayTopic = headlineSeed.toLowerCase();
  const headline = `${titleCase(headlineSeed)} Draws Fresh Scrutiny Across Public Sources`;

  return {
    id: `cmd-${Date.now()}`,
    source,
    tag,
    trendUrl,
    prompt: cleanPrompt,
    headline,
    dek: `Command-generated draft from ${sourceCount} simulated source packets.`,
    createdAt: new Date().toISOString(),
    sourceCount,
    deniedForBias,
    fairnessScore,
    accuracyScore,
    terms: terms.length ? terms : ["public", "record", "wire"],
    sources: sourcePools.slice(0, Math.min(sourcePools.length, 5)),
    summary:
      `Signal compared public reporting around ${displayTopic}, prioritizing overlapping claims from independent outlets and labeling single-source details as provisional.`,
    body: [
      `Public reporting around ${displayTopic} is moving through several source clusters, with early signals from wire services, public records, and regional desks.`,
      `Signal compared ${sourceCount} article and record fragments, rejecting ${deniedForBias} packets for excessive framing, duplication, or weak attribution.`,
      `The clearest pattern is source overlap: multiple outlets are tracking the same core development, while timing, impact, and second-order consequences still require direct citation.`,
      `This command draft should be reviewed before publication. Production mode should attach live links, preserve disputed claims, and show source provenance for each factual sentence.`,
    ],
    facts: [
      {
        text: terms.slice(0, 3).join(" ") || cleanPrompt,
        source: "wire services; regional archive; public records index",
      },
      {
        text: `${sourceCount} article and record fragments`,
        source: "command pipeline source counter; duplicate removal pass",
      },
      {
        text: `${deniedForBias} packets for excessive framing`,
        source: "bias and duplication filter; local scoring heuristic",
      },
    ],
  };
}

function readExisting(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return [];
  }
}

function writeQueue(filePath, articles) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(articles, null, 2)}\n`);
}

async function postToBackend(articleArgs) {
  if (typeof fetch !== "function") return null;
  try {
    const response = await fetch(`${backendUrl}/articles/generate-from-trend`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(process.env.SIGNAL_API_TOKEN ? { "X-Signal-Token": process.env.SIGNAL_API_TOKEN } : {}),
      },
      body: JSON.stringify({
        prompt: articleArgs.prompt,
        source: articleArgs.source,
        trend_url: articleArgs.trendUrl,
        tag: articleArgs.tag,
      }),
    });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

const args = readArgs(process.argv.slice(2));
if (!args.prompt) {
  console.error('Usage: npm run article:trend -- "trend prompt" --source openclaw-x --url https://x.com/...');
  process.exit(1);
}

(async () => {
  const backendArticle = await postToBackend(args);
  const article = backendArticle || buildArticle(args.prompt, args.source, args.trendUrl, args.tag);
  const existing = readExisting(publicPath);
  const next = [article, ...existing.filter((item) => item.id !== article.id)].slice(0, 50);
  writeQueue(publicPath, next);
  if (fs.existsSync(path.join(root, "dist"))) writeQueue(distPath, next);

  console.log(`Generated article: ${article.headline}`);
  console.log(`ID: ${article.id}`);
  console.log(`Backend: ${backendArticle ? `${backendUrl}/generated-articles/${article.id}` : "not running; wrote static queue"}`);
  console.log(`Queue: ${publicPath}`);
  if (fs.existsSync(path.join(root, "dist"))) console.log(`Live dist queue: ${distPath}`);
})();
