import { SECTION_QUERIES, starterStories } from "../lib/constants.js";
import { dedupeStories, storyDek, storySourceCount, storyTitle } from "./articleNormalize.js";

const SECTION_LOCATIONS = {
  World: { region: "London", location: [51.5072, -0.1276] },
  Politics: { region: "Washington", location: [38.9072, -77.0369] },
  Markets: { region: "New York", location: [40.7128, -74.006] },
  Technology: { region: "San Francisco", location: [37.7749, -122.4194] },
  Climate: { region: "Sao Paulo", location: [-23.5505, -46.6333] },
};

const TREND_LOCATIONS = [
  { region: "London", location: [51.5072, -0.1276] },
  { region: "Washington", location: [38.9072, -77.0369] },
  { region: "New York", location: [40.7128, -74.006] },
  { region: "San Francisco", location: [37.7749, -122.4194] },
  { region: "Tokyo", location: [35.6762, 139.6503] },
  { region: "Sao Paulo", location: [-23.5505, -46.6333] },
  { region: "Delhi", location: [28.6139, 77.209] },
  { region: "Cairo", location: [30.0444, 31.2357] },
  { region: "Berlin", location: [52.52, 13.405] },
  { region: "Sydney", location: [-33.8688, 151.2093] },
  { region: "Singapore", location: [1.3521, 103.8198] },
  { region: "Nairobi", location: [-1.2921, 36.8219] },
];

const LOCATION_KEYWORDS = [
  { match: ["washington", "congress", "senate", "white house", "supreme court"], region: "Washington", location: [38.9072, -77.0369] },
  { match: ["new york", "wall street", "nasdaq", "united nations"], region: "New York", location: [40.7128, -74.006] },
  { match: ["london", "uk", "britain", "parliament"], region: "London", location: [51.5072, -0.1276] },
  { match: ["berlin", "germany", "european union", "brussels"], region: "Berlin", location: [52.52, 13.405] },
  { match: ["tokyo", "japan"], region: "Tokyo", location: [35.6762, 139.6503] },
  { match: ["china", "beijing", "hong kong"], region: "Beijing", location: [39.9042, 116.4074] },
  { match: ["india", "delhi", "rourkela", "nit"], region: "Delhi", location: [28.6139, 77.209] },
  { match: ["middle east", "egypt", "cairo", "gaza", "israel"], region: "Cairo", location: [30.0444, 31.2357] },
  { match: ["brazil", "amazon", "sao paulo"], region: "Sao Paulo", location: [-23.5505, -46.6333] },
  { match: ["africa", "kenya", "nairobi"], region: "Nairobi", location: [-1.2921, 36.8219] },
  { match: ["australia", "sydney"], region: "Sydney", location: [-33.8688, 151.2093] },
  { match: ["singapore", "asean"], region: "Singapore", location: [1.3521, 103.8198] },
  { match: ["ai", "openai", "google", "apple", "meta", "nvidia", "silicon valley"], region: "San Francisco", location: [37.7749, -122.4194] },
];

function inferStorySection(story, fallback = "World") {
  const text = `${story.section || ""} ${story.source || ""} ${story.prompt || ""} ${storyTitle(story)}`.toLowerCase();
  if (text.includes("politic") || text.includes("congress") || text.includes("senate") || text.includes("government")) return "Politics";
  if (text.includes("market") || text.includes("stock") || text.includes("inflation") || text.includes("bank") || text.includes("econom")) return "Markets";
  if (text.includes("technology") || text.includes("ai") || text.includes("chip") || text.includes("cyber") || text.includes("semiconductor")) return "Technology";
  if (text.includes("climate") || text.includes("weather") || text.includes("insurance") || text.includes("environment")) return "Climate";
  return SECTION_LOCATIONS[story.section] ? story.section : fallback;
}

function inferStoryLocation(story, index, fallbackSection) {
  const text = `${storyTitle(story)} ${storyDek(story)} ${story.topic_label || ""} ${story.category || ""}`.toLowerCase();
  const directMatch = LOCATION_KEYWORDS.find((entry) => entry.match.some((term) => text.includes(term)));
  if (directMatch) return directMatch;
  const sectionMatch = SECTION_LOCATIONS[inferStorySection(story, fallbackSection)];
  return index % 2 === 0 && sectionMatch ? sectionMatch : TREND_LOCATIONS[index % TREND_LOCATIONS.length];
}

export function makeGlobeMarkers(stories, activeSection) {
  const selected = dedupeStories(stories, 10);
  const source = selected.length ? selected : starterStories;
  return source.map((story, index) => {
    const mapped = inferStoryLocation(story, index, activeSection);
    return {
      id: `trend-${index}-${String(story.id || storyTitle(story)).replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`,
      location: mapped.location,
      region: mapped.region,
      headline: storyTitle(story),
      prompt: story.prompt || storyTitle(story),
      article: story.headline ? story : null,
      size: Math.min(0.035, 0.018 + Math.max(1, storySourceCount(story)) / 900),
    };
  });
}

export function normalizeTrendingTopic(topic, index = 0) {
  const text = String(topic.entity_text || topic.prompt || topic.headline || topic.title || "").trim();
  const mapped = inferStoryLocation({ ...topic, headline: text, prompt: text }, index, "World");
  return {
    id: `topic-${index}-${String(text).replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`,
    location: mapped.location,
    region: mapped.region,
    headline: text,
    prompt: text,
    article: null,
    size: Math.min(0.038, 0.019 + Math.max(1, topic.mentions || topic.sourceCount || 1) / 180),
  };
}

export function isUsefulTrendTopic(topic) {
  const text = String(topic.entity_text || topic.prompt || topic.headline || topic.title || "").toLowerCase();
  if (text.length < 8) return false;
  return !Object.values(SECTION_QUERIES).some((query) => text === query.toLowerCase())
    && !text.includes("wire services latest");
}
