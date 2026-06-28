import { GenerationModeToggle } from "./GenerationModeToggle.jsx";

export function ArticleScreen({
  draft,
  prompt,
  setPrompt,
  onSubmit,
  generationMode,
  onGenerationModeChange,
  onSave,
  onShare,
  onCopyLink,
  onShareX,
}) {
  const state = draft.articleState || {
    kind: "demo",
    label: "Local/demo fallback article",
    detail: "Static or local demo content. Treat as a product preview, not verified live reporting.",
  };
  const facts = draft.facts || [
    {
      text: draft.terms.slice(0, 3).join(" "),
      source: "Reuters public wire; regional newsroom archive; first local mention timestamp",
    },
    {
      text: `${draft.sourceCount} article and record fragments`,
      source: "Associated Press bulletin; government records desk; duplicate wire fragments removed",
    },
    {
      text: "local reports surfaced the first details",
      source: "local public radio transcript; court docket monitor; regional newsroom archive",
    },
  ];
  const sourceHost = (url) => {
    try {
      return new URL(url).hostname.replace(/^www\./, "");
    } catch {
      return url;
    }
  };

  return (
    <section className="article-result-screen">
      <form className="rewrite-bar" onSubmit={onSubmit}>
        <label htmlFor="rewrite-prompt">Rewrite from another prompt</label>
        <input
          id="rewrite-prompt"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
        />
        <GenerationModeToggle compact value={generationMode} onChange={onGenerationModeChange} />
        <button type="submit">Rewrite</button>
      </form>

      <div className="article-toolbar" aria-label="Article actions">
        <button type="button" onClick={onSave}>Save</button>
        <button type="button" onClick={onShare}>Share</button>
        <button type="button" onClick={onCopyLink}>Copy link</button>
        <button type="button" onClick={onShareX}>Share on X</button>
        <button type="button" onClick={() => window.print()}>Print</button>
      </div>

      <article className="article-reader">
        <div className={`article-state article-state-${state.kind}`}>
          <strong>{state.label}</strong>
          <span>{state.detail}</span>
        </div>
        <span>{draft.source ? `Filed from ${draft.source}` : "Signal analysis"}</span>
        <h1>{draft.headline}</h1>
        <p className="dek">{draft.dek}</p>
        {draft.body?.length ? (
          draft.body.map((paragraph, index) => (
            <p key={`${draft.id || draft.headline}-${index}`}>
              <FactText text={paragraph} facts={facts} />
            </p>
          ))
        ) : (
          <>
            <p>
              Public reporting around{" "}
              <SourcedFact source={facts[0].source}>{facts[0].text}</SourcedFact>{" "}
              is developing across several source clusters, with early signals coming
              from wire services, official records, and regional outlets.
            </p>
            <p>
              Signal compared{" "}
              <SourcedFact source={facts[1].source}>{facts[1].text}</SourcedFact>
              , prioritizing overlap between independently published accounts before
              drafting a neutral summary.
            </p>
            <p>
              The strongest pattern so far is the movement of attention:{" "}
              <SourcedFact source={facts[2].source}>{facts[2].text}</SourcedFact>
              , larger desks connected them to broader policy and market questions,
              and public datasets helped verify timing.
            </p>
            <p>
          Signal labels disputed claims, preserves source context, and keeps
          unsupported details out of the main article until additional reporting appears.
            </p>
          </>
        )}
      </article>

      <div className="article-stats">
        <div><strong>{draft.sourceCount}</strong><span>sources</span></div>
        <div><strong>{draft.deniedForBias}</strong><span>heuristic rejects</span></div>
        <div><strong>{draft.fairnessScore}</strong><span>source-balance estimate</span></div>
        <div><strong>{draft.accuracyScore}</strong><span>verification estimate</span></div>
      </div>
      <p className="score-note">
        Scores are pipeline heuristics from source diversity and claim overlap. They are not audited bias or factuality ratings.
      </p>

      {draft.sourceLinks?.length > 0 && (
        <div className="article-sources">
          <h3>Sources reviewed <span>{draft.sourceLinks.length}</span></h3>
          <ul className="source-link-list">
            {draft.sourceLinks.map((sl, i) => (
              <li key={i} className="source-link-item">
                <span className="source-link-outlet">{sl.source}</span>
                {sl.url ? (
                  <a href={sl.url} target="_blank" rel="noopener noreferrer" className="source-link-title">
                    <strong>{sl.title}</strong>
                    <em>{sourceHost(sl.url)}</em>
                  </a>
                ) : (
                  <span className="source-link-title">{sl.title}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
function FactText({ text, facts }) {
  const fact = facts.find((item) => item.text && text.includes(item.text));
  if (!fact) return text;
  const [before, after] = text.split(fact.text);
  return (
    <>
      {before}
      <SourcedFact source={fact.source}>{fact.text}</SourcedFact>
      {after}
    </>
  );
}

function SourcedFact({ children, source }) {
  return (
    <span className="sourced-fact" tabIndex="0" data-source={source}>
      {children}
    </span>
  );
}
