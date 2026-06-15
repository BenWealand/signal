export const SECTION_QUERIES = {
  World: "international diplomacy conflict global affairs",
  Politics: "congress senate legislation government policy",
  Markets: "stock market economy financial inflation interest rates",
  Technology: "artificial intelligence semiconductor technology cybersecurity",
  Climate: "climate change environment renewable energy weather",
};

export const SECTION_NAMES = ["World", "Politics", "Markets", "Technology", "Climate"];

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

export const defaultSettings = {
  region: "Global",
  edition: "Morning",
  density: "Comfortable",
  sourceThreshold: 8,
  emailAlerts: true,
  showDisputedClaims: true,
};
