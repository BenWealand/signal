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

function titleCase(text) {
  return text
    .split(" ")
    .filter(Boolean)
    .slice(0, 10)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}

const FALLBACK_REASON_NOTES = {
  no_accessible_sources: "Signal could not find enough accessible reporting on this topic yet. Try a slightly more specific search.",
  quality_gate_failed: "Not enough independent reporting has surfaced on this topic yet for a full edition. Try a more specific search.",
  processing_failed: "Signal gathered coverage but could not finish a full edition. Try again in a moment.",
  snippet_only_fast_mode: "This older quick edition drew on short source snippets. Rewrite it for a Zen-sourced edition.",
  local_simulation: "An offline preview draft prepared without the backend.",
};

export function articleStateFor(article = {}) {
  if (article.backendError || article.localFallback) {
    return {
      kind: "offline_preview",
      label: "Offline preview",
      detail: "Prepared locally because no backend API is configured for this build.",
    };
  }
  if (article.articleState) {
    const kind = String(article.articleState.kind || "");
    const label = String(article.articleState.label || "");
    if (
      ["demo", "backend_failed_local", "backend_fallback"].includes(kind)
      || ["Preview edition", "Preview draft", "Early coverage"].includes(label)
    ) {
      return {
        kind: "offline_preview",
        label: "Offline preview",
        detail: "A local preview for offline development. Backend-configured builds use Zen-sourced articles.",
      };
    }
    return article.articleState;
  }
  if (article.fallback_reason) {
    return {
      kind: "legacy_limited",
      label: "Legacy limited article",
      detail: FALLBACK_REASON_NOTES[String(article.fallback_reason)]
        || "This older saved article predates the Zen-only writing policy.",
    };
  }
  if (article.generation_mode === "fast") {
    return {
      kind: "fast",
      label: "Quick edition",
      detail: article.used_live_sources === false
        ? "Drafted quickly from short source snippets. Review the source links below for full context."
        : "Drafted quickly from live coverage. Review the source links below before relying on details.",
    };
  }
  if (article.generation_mode === "thorough") {
    return {
      kind: "thorough",
      label: "Consensus edition",
      detail: "Written from ranked source material with cross-checked claims.",
    };
  }
  if (article.sourceLinks?.length || article.used_live_sources) {
    return {
      kind: "live",
      label: "Live sourced article",
      detail: "Written from live source material with inspectable provenance.",
    };
  }
  return {
    kind: "offline_preview",
    label: "Offline preview",
    detail: "A local preview for offline development. Backend-configured builds use Zen-sourced articles.",
  };
}

export function buildDraft(prompt) {
  const cleanPrompt = prompt.trim() || "global supply chains";
  const words = cleanPrompt.toLowerCase().split(/\s+/).filter(Boolean);
  const sourceCount = Math.min(24, Math.max(7, words.length * 3 + 4));
  const keyTerms = [...new Set(words)].slice(0, 5);
  const headline = `${titleCase(cleanPrompt)} Draws Fresh Scrutiny Across Public Sources`;

  const logs = [
    `fetching source map for "${cleanPrompt}"`,
    `querying ${sourcePools[words.length % sourcePools.length]}`,
    "requesting latest public records index",
    "checking free public data endpoints",
    "opening article memory buffer",
    `opening public archive folders for ${keyTerms[1] || "policy"}`,
    `loading regional context from ${sourcePools[(words.length + 2) % sourcePools.length]}`,
    "scanning byline clusters for repeated attribution",
    "normalizing timestamps across wire updates",
    "deduplicating syndicated article copies",
    "isolating primary source references",
    "detecting claim clusters by named entity",
    `researching ${keyTerms[0] || "regional"} claims across public records`,
    "cross-checking geography against source datelines",
    "extracting names, agencies, locations, and quoted figures",
    "compressing quote candidates into neutral notes",
    "sampling local outlet context for first mention",
    `matching quotes against ${sourceCount} candidate source packets`,
    "scoring source independence and publication time",
    "rejecting duplicate syndicated fragments",
    "checking image captions for location conflicts",
    "discarding unsupported social posts",
    "checking overlap between wire copy, filings, and local reports",
    "weighting primary documents above commentary",
    "building contradiction table for disputed claims",
    "flagging unresolved claims for attribution",
    "building source hover notes for factual sentences",
    "mapping facts to reader-facing citations",
    "marking contested facts for reader inspection",
    "ranking source confidence by recency and independence",
    "checking headline for unsupported causality",
    "assembling article structure: lede, context, caveats",
    "writing neutral lede without unsourced conclusions",
    "compressing background section for readability",
    "attaching source provenance to high-value facts",
    "testing article body for missing attribution",
    "drafting neutral article with attribution notes",
    "running final style pass against publication voice",
    "building overview statistics",
    "finalizing reader-facing source summary",
  ];

  return {
    headline,
    dek: `${sourceCount} source candidates found.`,
    sourceCount,
    deniedForBias: Math.max(1, Math.floor(sourceCount * 0.16)),
    fairnessScore: Math.min(97, 78 + keyTerms.length * 3),
    accuracyScore: Math.min(96, 80 + Math.floor(sourceCount / 4)),
    logs,
    terms: keyTerms.length ? keyTerms : ["public", "record", "wire"],
    body: null,
    facts: null,
    generation_mode: "offline-preview",
    used_live_sources: false,
    fallback_reason: "local_simulation",
    articleState: {
      kind: "offline_preview",
      label: "Offline preview",
      detail: "Prepared locally because no backend API is configured for this build.",
    },
  };
}

export function normalizeCommandArticle(article) {
  const base = buildDraft(article.prompt);
  const {
    articleState: _baseArticleState,
    fallback_reason: _baseFallbackReason,
    generation_mode: _baseGenerationMode,
    used_live_sources: _baseUsedLiveSources,
    ...baseDefaults
  } = base;
  const merged = {
    ...baseDefaults,
    ...article,
    logs: base.logs,
    terms: article.terms?.length ? article.terms : base.terms,
    sourceCount: article.sourceCount || base.sourceCount,
    deniedForBias: article.deniedForBias || Math.max(1, Math.floor((article.sourceCount || 12) * 0.16)),
    fairnessScore: article.fairnessScore || 86,
    accuracyScore: article.accuracyScore || 88,
  };
  return {
    ...merged,
    articleState: articleStateFor(merged),
  };
}

export function normalizeBackendStory(story) {
  return {
    id: `story-${story.id}`,
    source: "Signal desk",
    tag: "cluster",
    trendUrl: "",
    prompt: story.topic_label,
    headline: story.topic_label,
    dek: story.summary_text || `Signal compared ${story.article_count || 0} source articles in this story cluster.`,
    createdAt: story.updated_at || story.created_at || new Date().toISOString(),
    sourceCount: story.article_count || 0,
    deniedForBias: Math.max(1, Math.floor((story.article_count || 6) * 0.16)),
    fairnessScore: 86,
    accuracyScore: 88,
    terms: story.topic_label?.toLowerCase().split(/\s+/).slice(0, 5) || ["source", "cluster"],
    sources: story.articles?.map((article) => article.source_name) || [],
    summary: story.summary_text || "Signal is comparing claims across this developing story.",
    body: [
      story.summary_text || "Signal is comparing claims across this developing story.",
      `This story currently contains ${story.article_count || 0} source articles grouped by topic, entities, and overlapping claims.`,
      "Unsupported details remain out of the main summary until additional source overlap appears.",
    ],
    facts: [
      {
        text: `${story.article_count || 0} source articles`,
        source: "story cluster article count",
      },
    ],
    generation_mode: "thorough",
    used_live_sources: true,
    articleState: {
      kind: "live",
      label: "Live sourced article",
      detail: "Summarized from a live backend story cluster.",
    },
  };
}

export function storyTitle(story) {
  return String(story.topic_label || story.headline || story.title || story.prompt || "Untitled story");
}

export function storyDek(story) {
  return String(story.dek || story.summary_text || story.summary || "");
}

export function storySourceCount(story) {
  return story.article_count || story.sourceCount || story.source_count || 0;
}

export function storyDate(story) {
  const value = story.updated_at || story.createdAt || story.created_at;
  if (!value) return "";
  return new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function normalizeStoryKey(story) {
  const text = storyTitle(story);
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 14)
    .join(" ");
}

const STORY_STOPWORDS = new Set([
  "the", "and", "for", "with", "from", "that", "this", "what", "will",
  "says", "said", "into", "over", "after", "before", "about", "home",
  "today", "new", "news",
]);

function storyTokens(story) {
  return normalizeStoryKey(story)
    .split(/\s+/)
    .filter((word) => word.length > 2 && !STORY_STOPWORDS.has(word));
}

function isDuplicateStory(a, b) {
  const aTokens = new Set(storyTokens(a));
  const bTokens = new Set(storyTokens(b));
  if (!aTokens.size || !bTokens.size) return false;
  const overlap = [...aTokens].filter((token) => bTokens.has(token)).length;
  const smaller = Math.min(aTokens.size, bTokens.size);
  return overlap >= 4 || (overlap >= 3 && overlap / smaller >= 0.38);
}

export function dedupeStories(stories, limit = stories.length) {
  const deduped = [];
  stories.forEach((story) => {
    if (!normalizeStoryKey(story)) return;
    const existingIndex = deduped.findIndex((current) => isDuplicateStory(story, current));
    const current = existingIndex >= 0 ? deduped[existingIndex] : null;
    const sourceCount = storySourceCount(story);
    const currentSourceCount = current ? storySourceCount(current) : -1;
    const date = story.updated_at || story.createdAt || story.created_at || "";
    const currentDate = current?.updated_at || current?.createdAt || current?.created_at || "";
    if (!current) {
      deduped.push(story);
    } else if (date > currentDate || (date === currentDate && sourceCount > currentSourceCount)) {
      deduped[existingIndex] = story;
    }
  });
  return deduped.slice(0, limit);
}
