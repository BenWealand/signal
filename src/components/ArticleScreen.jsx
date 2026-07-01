import { GenerationModeToggle } from "./GenerationModeToggle.jsx";
import { useMemo, useState } from "react";

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
  onRecommendedPrompt,
  social,
  onLikeArticle,
  onCommentArticle,
  onLikeComment,
}) {
  const [commentBody, setCommentBody] = useState("");
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
  const followUps = useMemo(() => {
    const terms = (draft.terms || []).slice(0, 4);
    const sources = (draft.sources || []).slice(0, 2);
    const base = draft.prompt || draft.headline;
    return [
      `${base} latest source updates`,
      terms.length ? `${terms.join(" ")} local impact` : `${base} local impact`,
      sources.length ? `${base} according to ${sources.join(" and ")}` : `${base} timeline`,
      `${base} what changed in the last 24 hours`,
    ].filter(Boolean).slice(0, 4);
  }, [draft]);

  const submitComment = (event) => {
    event.preventDefault();
    const body = commentBody.trim();
    if (!body) return;
    onCommentArticle?.(body);
    setCommentBody("");
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
        <GenerationModeToggle value={generationMode} onChange={onGenerationModeChange} />
        <button type="submit">Rewrite</button>
      </form>
      <div className="follow-up-searches">
        <span>Recommended follow-up searches</span>
        <div>
          {followUps.map((item) => (
            <button type="button" key={item} onClick={() => onRecommendedPrompt?.(item)}>
              <SearchChipIcon />
              {item}
            </button>
          ))}
        </div>
      </div>

      <div className="article-toolbar" aria-label="Article actions">
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

      <div className="article-bottom-actions" aria-label="Article reactions">
        <button
          className={social?.liked ? "is-active" : ""}
          type="button"
          onClick={onLikeArticle}
          aria-label={social?.liked ? "Liked article" : "Like article"}
          title={social?.liked ? "Liked" : "Like"}
        >
          <HeartIcon filled={Boolean(social?.liked)} />
          {social?.likeCount ? <span>{social.likeCount}</span> : null}
        </button>
        <button type="button" onClick={onSave} aria-label="Save article" title="Save">
          <BookmarkIcon />
        </button>
      </div>

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

      <section className="article-discussion">
        <div className="discussion-header">
          <span>Discussion</span>
          <strong>{social?.comments?.length || 0} comments</strong>
        </div>
        <form className="comment-form" onSubmit={submitComment}>
          <textarea
            value={commentBody}
            onChange={(event) => setCommentBody(event.target.value)}
            placeholder="Add a source note, question, or correction"
            rows={3}
          />
          <button type="submit">Comment</button>
        </form>
        <div className="comment-list">
          {(social?.comments || []).map((comment) => (
            <article className="comment-row" key={comment.id}>
              <div>
                <strong>{comment.author_name || "Reader"}</strong>
                <em>{comment.created_at ? new Date(comment.created_at).toLocaleString() : ""}</em>
              </div>
              <p>{comment.body}</p>
              <button type="button" onClick={() => onLikeComment?.(comment.id)}>
                Like {comment.like_count ? comment.like_count : ""}
              </button>
            </article>
          ))}
        </div>
      </section>
    </section>
  );
}

function SearchChipIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="10.8" cy="10.8" r="5.8" />
      <path d="m15.2 15.2 4 4" />
    </svg>
  );
}

function HeartIcon({ filled = false }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        className={filled ? "is-filled" : ""}
        d="M12 20.3S4.5 15.9 3.2 9.8C2.5 6.3 4.5 4 7.2 4c1.8 0 3.3 1 4.1 2.4C12.1 5 13.6 4 15.4 4c2.7 0 4.7 2.3 4 5.8C18.1 15.9 12 20.3 12 20.3Z"
      />
    </svg>
  );
}

function BookmarkIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6.5 4.2h11v16L12 16.8l-5.5 3.4v-16Z" />
    </svg>
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
