export const SECTION_QUERIES = {
  World: "international diplomacy conflict global affairs",
  Politics: "congress senate legislation government policy",
  Sporks: "sports athletics leagues championships olympic games",
  Markets: "stock market economy financial inflation interest rates",
  Technology: "artificial intelligence semiconductor technology cybersecurity",
  Climate: "climate change environment renewable energy weather",
};

export const SECTION_NAMES = ["World", "Politics", "Sporks", "Markets", "Technology", "Climate"];

export const starterStories = [
  {
    id: "world-brief",
    section: "World",
    title: "Diplomatic cables point to a slower ceasefire timetable",
    dek: "Signal is tracking public statements, local accounts, and agency copy for overlap.",
    sourceCount: 18,
  },
  {
    id: "markets-brief",
    section: "Markets",
    title: "Regional banks face renewed pressure from commercial property loans",
    dek: "Filings and local business reports show uneven risk across midsize lenders.",
    sourceCount: 21,
  },
  {
    id: "technology-brief",
    section: "Technology",
    title: "Chip export controls shift supply routes across Asia",
    dek: "Customs data, company statements, and policy notices are being compared.",
    sourceCount: 24,
  },
  {
    id: "climate-brief",
    section: "Climate",
    title: "Coastal insurers redraw maps after another severe flood season",
    dek: "Public rate filings and local recovery records show where costs are rising.",
    sourceCount: 16,
  },
];

export const trendPromptPreviews = [
  ...starterStories.map((story) => story.title),
  "NBA draft results and team-by-team trade fallout",
  "AI chip export controls and supply chain rerouting",
  "Federal Reserve rate path after the latest inflation print",
  "Commercial real estate losses at regional banks",
  "Congress budget talks and agency funding deadlines",
  "Supreme Court rulings affecting federal regulatory power",
  "Ukraine ceasefire negotiations and European security guarantees",
  "Red Sea shipping disruption and insurance costs",
  "Climate insurance withdrawals in coastal housing markets",
  "Grid reliability risks during extreme heat alerts",
  "Cybersecurity breach disclosure rules for public companies",
  "Semiconductor earnings and data center demand",
  "Oil prices after OPEC supply guidance",
  "Election law changes before the next voting deadline",
  "Public health agencies tracking new respiratory variants",
  "Major airline delays after severe weather systems",
  "Treasury yields and mortgage rate pressure on buyers",
  "Antitrust scrutiny of cloud and AI platform deals",
];

export const defaultSettings = {
  region: "Global",
  edition: "Morning",
  density: "Comfortable",
  sourceThreshold: 8,
  emailAlerts: true,
  showDisputedClaims: true,
};
