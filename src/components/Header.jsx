import { SECTION_NAMES } from "../lib/constants.js";

export function Header({
  activeScreen,
  activeSection,
  onScreenChange,
  onSectionChange,
  onOpenAccount,
  onOpenSettings,
  onOpenNotifications,
  notificationCount = 0,
  signedInUser,
}) {
  const screens = ["Home", "Latest", "Trending", "Saved"];
  const sections = SECTION_NAMES;
  const mobileScreens = ["Home", "Latest", "Trending", "Saved"];
  const displayDate = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(new Date());

  return (
    <>
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
          <button className="header-icon-button" type="button" onClick={onOpenSettings} aria-label="Settings" title="Settings">
            <SettingsIcon />
          </button>
          <button className="header-icon-button notification-button" type="button" onClick={onOpenNotifications} aria-label="Inbox" title="Inbox">
            <InboxIcon />
            {notificationCount > 0 ? <span>{notificationCount}</span> : null}
          </button>
          <button className="header-icon-button account-icon-button" type="button" onClick={onOpenAccount} aria-label={signedInUser ? "Account" : "Sign in"} title={signedInUser ? signedInUser.name : "Sign in"}>
            <AccountIcon />
          </button>
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

      <nav className="mobile-topic-nav" aria-label="Mobile topic navigation">
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
    <nav className="mobile-bottom-nav" aria-label="Mobile primary navigation">
      {mobileScreens.map((screen) => (
        <button
          className={activeScreen === screen ? "is-active" : ""}
          key={screen}
          type="button"
          onClick={() => onScreenChange(screen)}
          aria-label={screen}
        >
          <MobileNavIcon screen={screen} />
          <span>{screen}</span>
        </button>
      ))}
    </nav>
    </>
  );
}

function MobileNavIcon({ screen }) {
  if (screen === "Latest") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5 5.5h14M5 12h14M5 18.5h9" />
      </svg>
    );
  }
  if (screen === "Trending") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 16.5 9 11l4 3.5 7-8" />
        <path d="M15 6.5h5v5" />
      </svg>
    );
  }
  if (screen === "Saved") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M6.5 4.5h11v15L12 16.2l-5.5 3.3v-15Z" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4.5 10.8 12 4l7.5 6.8" />
      <path d="M6.8 10v9.2h10.4V10" />
    </svg>
  );
}

function SettingsIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 8.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6Z" />
      <path d="M19.4 13.5a7.6 7.6 0 0 0 0-3l2-1.5-2-3.4-2.4 1a8 8 0 0 0-2.6-1.5L14 2.5h-4l-.4 2.6A8 8 0 0 0 7 6.6l-2.4-1-2 3.4 2 1.5a7.6 7.6 0 0 0 0 3l-2 1.5 2 3.4 2.4-1a8 8 0 0 0 2.6 1.5l.4 2.6h4l.4-2.6a8 8 0 0 0 2.6-1.5l2.4 1 2-3.4-2-1.5Z" />
    </svg>
  );
}

function InboxIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 4h14l2 10v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-5L5 4Z" />
      <path d="M3.4 14h5.2a3.6 3.6 0 0 0 6.8 0h5.2" />
    </svg>
  );
}

function AccountIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 12a4.2 4.2 0 1 0 0-8.4 4.2 4.2 0 0 0 0 8.4Z" />
      <path d="M4.5 20.4c1.2-4.2 4-6.3 7.5-6.3s6.3 2.1 7.5 6.3" />
    </svg>
  );
}
