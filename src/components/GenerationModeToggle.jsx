const MODES = [
  {
    value: "fast",
    label: "Fast",
    title: "Fast mode",
    description: "Quicker source scan for interactive drafts.",
    Icon: FastIcon,
  },
  {
    value: "thorough",
    label: "Thorough",
    title: "Thorough mode",
    description: "Deeper source review with stricter gates.",
    Icon: ThoroughIcon,
  },
];

export function GenerationModeToggle({ value = "fast", onChange, compact = false }) {
  const activeValue = value === "thorough" ? "thorough" : "fast";

  return (
    <div
      className={`generation-mode-toggle ${compact ? "is-compact" : ""}`}
      role="radiogroup"
      aria-label="Article generation mode"
      data-mode={activeValue}
    >
      <span className="mode-indicator" aria-hidden="true" />
      {MODES.map((mode) => (
        <button
          key={mode.value}
          type="button"
          className={activeValue === mode.value ? "is-active" : ""}
          role="radio"
          aria-checked={activeValue === mode.value}
          title={mode.title}
          data-tooltip={mode.description}
          onClick={() => onChange(mode.value)}
        >
          <span className="mode-icon" aria-hidden="true">
            <mode.Icon />
          </span>
          <strong>{mode.label}</strong>
        </button>
      ))}
    </div>
  );
}

function FastIcon() {
  return (
    <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
      <path d="M13.2 2.6 5.1 13.1h6.3l-.9 8.3 8.4-11.2h-6.2l.5-7.6Z" />
    </svg>
  );
}

function ThoroughIcon() {
  return (
    <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
      <circle cx="12" cy="12" r="7.2" />
      <circle cx="12" cy="12" r="3.1" />
      <path d="M12 2.7v3.1M12 18.2v3.1M2.7 12h3.1M18.2 12h3.1" />
    </svg>
  );
}
