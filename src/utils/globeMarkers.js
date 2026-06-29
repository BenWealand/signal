import { SECTION_QUERIES } from "../lib/constants.js";
import { dedupeStories, storyDek, storySourceCount, storyTitle } from "./articleNormalize.js";

const LOCATION_KEYWORDS = [
  { match: ["washington", "congress", "senate", "white house", "supreme court", "capitol"], region: "Washington", location: [38.9072, -77.0369] },
  { match: ["new york", "wall street", "nasdaq", "united nations", "manhattan"], region: "New York", location: [40.7128, -74.006] },
  { match: ["london", "uk", "u.k.", "britain", "parliament", "england"], region: "London", location: [51.5072, -0.1276] },
  { match: ["paris", "france"], region: "Paris", location: [48.8566, 2.3522] },
  { match: ["berlin", "germany"], region: "Berlin", location: [52.52, 13.405] },
  { match: ["brussels", "european union", "eu"], region: "Brussels", location: [50.8503, 4.3517] },
  { match: ["kyiv", "kiev", "ukraine"], region: "Kyiv", location: [50.4501, 30.5234] },
  { match: ["moscow", "russia"], region: "Moscow", location: [55.7558, 37.6173] },
  { match: ["tokyo", "japan"], region: "Tokyo", location: [35.6762, 139.6503] },
  { match: ["beijing", "china"], region: "Beijing", location: [39.9042, 116.4074] },
  { match: ["hong kong"], region: "Hong Kong", location: [22.3193, 114.1694] },
  { match: ["taiwan", "taipei"], region: "Taipei", location: [25.033, 121.5654] },
  { match: ["india", "delhi", "new delhi"], region: "Delhi", location: [28.6139, 77.209] },
  { match: ["mexico", "mexico city"], region: "Mexico City", location: [19.4326, -99.1332] },
  { match: ["canada", "ottawa"], region: "Ottawa", location: [45.4215, -75.6972] },
  { match: ["brazil", "amazon", "brasilia"], region: "Brasilia", location: [-15.7939, -47.8828] },
  { match: ["sao paulo", "são paulo"], region: "Sao Paulo", location: [-23.5505, -46.6333] },
  { match: ["argentina", "buenos aires"], region: "Buenos Aires", location: [-34.6037, -58.3816] },
  { match: ["egypt", "cairo"], region: "Cairo", location: [30.0444, 31.2357] },
  { match: ["gaza", "israel", "jerusalem"], region: "Jerusalem", location: [31.7683, 35.2137] },
  { match: ["iran", "tehran"], region: "Tehran", location: [35.6892, 51.389] },
  { match: ["saudi", "riyadh"], region: "Riyadh", location: [24.7136, 46.6753] },
  { match: ["kenya", "nairobi"], region: "Nairobi", location: [-1.2921, 36.8219] },
  { match: ["south africa", "johannesburg"], region: "Johannesburg", location: [-26.2041, 28.0473] },
  { match: ["australia", "sydney"], region: "Sydney", location: [-33.8688, 151.2093] },
  { match: ["singapore"], region: "Singapore", location: [1.3521, 103.8198] },
  { match: ["san francisco", "silicon valley", "openai", "apple", "google", "meta", "nvidia"], region: "San Francisco", location: [37.7749, -122.4194] },
  { match: ["los angeles", "hollywood"], region: "Los Angeles", location: [34.0522, -118.2437] },
  { match: ["miami"], region: "Miami", location: [25.7617, -80.1918] },
  { match: ["chicago"], region: "Chicago", location: [41.8781, -87.6298] },
  { match: ["brooklyn"], region: "Brooklyn", location: [40.6782, -73.9442] },
];

function inferStoryLocation(story) {
  const text = `${storyTitle(story)} ${storyDek(story)} ${story.topic_label || ""} ${story.category || ""}`.toLowerCase();
  const directMatch = LOCATION_KEYWORDS.find((entry) => entry.match.some((term) => text.includes(term)));
  return directMatch || null;
}

export function makeGlobeMarkers(stories) {
  const selected = dedupeStories(stories, 16);
  return selected.flatMap((story, index) => {
    const mapped = inferStoryLocation(story);
    if (!mapped) return [];
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
  const mapped = inferStoryLocation({ ...topic, headline: text, prompt: text });
  if (!mapped) return null;
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
