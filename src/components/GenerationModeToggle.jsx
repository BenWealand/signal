const MODES = [
  {
    value: "fast",
    symbol: "⚡",
    label: "Fast",
    title: "Fast mode",
  },
  {
    value: "thorough",
    symbol: "◎",
    label: "Thorough",
    title: "Thorough mode",
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
          onClick={() => onChange(mode.value)}
        >
          <span aria-hidden="true">{mode.symbol}</span>
          <strong>{mode.label}</strong>
        </button>
      ))}
    </div>
  );
}
