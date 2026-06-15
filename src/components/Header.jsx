import { SECTION_NAMES } from "../lib/constants.js";

export function Header({
  activeScreen,
  activeSection,
  onScreenChange,
  onSectionChange,
  onOpenAccount,
  onOpenSettings,
  signedInUser,
}) {
  const screens = ["Home", "Latest", "Trends", "Saved"];
  const sections = SECTION_NAMES;
  const displayDate = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(new Date());

  return (
    <header className="site-header">
      <div className="header-kicker">
        <span>{displayDate}</span>
        <strong>Live</strong>
        <span>Global</span>
      </div>

      <div className="masthead-row">
        <a className="brand" href="/" aria-label="Signal home">
          <strong>Signal Dispatch</strong>
        </a>
        <div className="header-actions">
          <button className="text-button" type="button" onClick={onOpenSettings}>Settings</button>
          <button className="text-button" type="button" onClick={onOpenAccount}>
            {signedInUser ? signedInUser.name : "Sign in"}
          </button>
          <button className="solid-button" type="button" onClick={onOpenAccount}>Subscribe</button>
        </div>
      </div>

      <nav className="section-nav" aria-label="Primary navigation">
        {screens.map((screen) => (
          <button
            className={activeScreen === screen ? "is-active" : ""}
            key={screen}
            type="button"
            onClick={() => onScreenChange(screen)}
          >
            {screen}
          </button>
        ))}
      </nav>

      <nav className="topic-nav" aria-label="Topic navigation">
        {sections.map((section) => (
          <button
            className={activeScreen === section || (activeScreen === "Home" && activeSection === section) ? "is-active" : ""}
            key={section}
            type="button"
            onClick={() => {
              onSectionChange(section);
              onScreenChange(section);
            }}
          >
            {section}
          </button>
        ))}
      </nav>
    </header>
  );
}
