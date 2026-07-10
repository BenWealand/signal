import { useEffect, useRef, useState } from "react";
import { getArticleProgress, hasApiBase } from "../api/client.js";

const CMD_LABELS = ["fetch", "read", "write", "scan", "check", "index", "build", "parse"];

const STAGE_COLORS = {
  fetching:   "#2a7a55",
  enriching:  "#1a6090",
  processing: "#7a5a1a",
  consensus:  "#6a2a7a",
  writing:    "#1a6a3a",
  idle:       "#555a50",
};

export function BuildScreen({ draft, wakeState }) {
  const WINDOW = 15;
  const tickRef = useRef(WINDOW);

  const makeLines = (startTick, logs) =>
    Array.from({ length: WINDOW }, (_, i) => {
      const t = startTick - (WINDOW - 1 - i);
      const idx = ((t % logs.length) + logs.length) % logs.length;
      return { text: logs[idx], uid: t };
    });

  const [lines, setLines] = useState(() => makeLines(WINDOW - 1, draft.logs));
  const [progress, setProgress] = useState({
    stage: "fetching",
    stage_label: "Connecting to sources...",
    sources_found: 0,
    sources_enriched: 0,
    claims_extracted: 0,
    elapsed_s: 0,
  });

  useEffect(() => {
    tickRef.current = WINDOW - 1;
    setLines(makeLines(WINDOW - 1, draft.logs));

    // Scroll terminal
    const logInterval = window.setInterval(() => {
      tickRef.current += 1;
      const t = tickRef.current;
      const idx = ((t % draft.logs.length) + draft.logs.length) % draft.logs.length;
      setLines((prev) => [...prev.slice(1), { text: draft.logs[idx], uid: t }]);
    }, 70);

    const pollInterval = window.setInterval(async () => {
      if (!hasApiBase()) return;
      try {
        const data = await getArticleProgress();
        if (data.active || data.stage !== "idle") setProgress(data);
      } catch {
        // Offline progress remains visible when no backend progress is available.
      }
    }, 1500);

    return () => {
      window.clearInterval(logInterval);
      window.clearInterval(pollInterval);
    };
  }, [draft.logs.length]);

  const stageColor = STAGE_COLORS[progress.stage] || STAGE_COLORS.idle;
  const elapsedLabel = progress.elapsed_s > 0 ? `${progress.elapsed_s}s` : "";
  const isStuck = progress.elapsed_s > 45;
  const isWaking = ["waking", "retrying"].includes(wakeState?.status);
  const stageLabel = isWaking
    ? wakeState.message || "Waking the backend before sourcing..."
    : isStuck
      ? "Still working - thorough sourcing can take a little longer..."
      : progress.stage_label;

  return (
    <section className="writing-screen is-building">
      <div className="build-progress-bar">
        <div className="build-progress-stages">
          {["fetching","enriching","processing","consensus","writing"].map((s) => {
            const stages = ["fetching","enriching","processing","consensus","writing"];
            const current = stages.indexOf(progress.stage);
            const idx = stages.indexOf(s);
            const done = idx < current;
            const active = idx === current;
            return (
              <div key={s} className={`build-stage-pip ${done ? "done" : ""} ${active ? "active" : ""}`}>
                <span className="pip-dot" />
                <span className="pip-label">{s}</span>
              </div>
            );
          })}
        </div>

        <div className="build-progress-detail">
          <span className="build-stage-label" style={{ color: stageColor }}>
            {stageLabel}
          </span>
          <div className="build-progress-stats">
            {progress.sources_found > 0 && (
              <span><strong>{progress.sources_found}</strong> sources found</span>
            )}
            {progress.sources_enriched > 0 && (
              <span><strong>{progress.sources_enriched}</strong> with full text</span>
            )}
            {progress.claims_extracted > 0 && (
              <span><strong>{progress.claims_extracted}</strong> claims</span>
            )}
            {elapsedLabel && (
              <span className={isStuck ? "elapsed-stuck" : "elapsed"}>{elapsedLabel}</span>
            )}
          </div>
        </div>
      </div>

      <div className="build-stage">
        <div className="terminal-card build-terminal">
          <div className="terminal-bar">
            <span />
            <span />
            <span />
          </div>
          <code>
            {lines.map((line, pos) => (
              <span
                className={pos === lines.length - 1 ? "is-active" : ""}
                key={line.uid}
              >
                <i>{String(line.uid + 1).padStart(2, "0")}</i>
                <b>{CMD_LABELS[line.uid % CMD_LABELS.length]}</b>
                <em>{line.text}</em>
              </span>
            ))}
          </code>
        </div>
      </div>
    </section>
  );
}
