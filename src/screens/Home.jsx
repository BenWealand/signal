import { Globe } from "../../components/ui/globe.tsx";

function NewsDashboard({
  activeSection,
  stories,
  newsletterEmail,
  onNewsletterChange,
  onToast,
  onPromptStory,
}) {
  const submitNewsletter = (event) => {
    event.preventDefault();
    onToast(newsletterEmail ? "Newsletter preference saved." : "Add an email before subscribing.");
  };

  return (
    <section className="news-dashboard" aria-label="News dashboard">
      <div className="dashboard-header">
        <span>{activeSection}</span>
        <h2>Top Stories</h2>
      </div>

      <div className="story-grid">
        {stories.map((story) => (
          <article className="story-card" key={story.id}>
            <span>{story.section}</span>
            <h3>{story.title}</h3>
            <p>{story.dek}</p>
            <div>
              <strong>{story.sourceCount}</strong>
              <em>sources</em>
              <button type="button" onClick={() => onPromptStory(story)}>Use as prompt</button>
            </div>
          </article>
        ))}
      </div>

      <aside className="service-panel">
        <div>
          <span>Coverage</span>
          <div className="service-stat-row"><strong>{stories.length}</strong><em>stories</em></div>
          <div className="service-stat-row"><strong>{stories.reduce((sum, story) => sum + (story.sourceCount || 0), 0)}</strong><em>sources</em></div>
        </div>
        <form onSubmit={submitNewsletter}>
          <label htmlFor="newsletter-email">Briefing email</label>
          <input
            id="newsletter-email"
            value={newsletterEmail}
            onChange={(event) => onNewsletterChange(event.target.value)}
            placeholder="you@example.com"
            type="email"
          />
          <button type="submit">Save</button>
        </form>
      </aside>
    </section>
  );
}

export function HomeScreen({
  activeSection,
  globeMarkers,
  onGlobeMarkerClick,
  onSubmit,
  prompt,
  onPromptChange,
  typedSuggestion,
  stories,
  newsletterEmail,
  onNewsletterChange,
  onToast,
  onPromptStory,
}) {
  return (
    <>
      <section className="globe-stage" aria-label="Live global news source map">
        <Globe className="hero-globe" markers={globeMarkers} onMarkerClick={onGlobeMarkerClick} />
        <div className="globe-fade" />
        <div className="hero-copy">
          <span>Home</span>
          <h1>Signal turns source overlap into readable reporting.</h1>
          <p>It gathers recent coverage, removes repeats, and drafts from visible source material.</p>
        </div>

        <form className="writer-panel compact-writer" onSubmit={onSubmit}>
          <div className="writer-heading">
            <span>Write</span>
          </div>
          <label htmlFor="article-prompt">Build a sourced draft</label>
          <p className="writer-hint">Use a specific topic, place, company, policy, or event. Add names or dates when they matter.</p>
          <div className="prompt-row">
            <input
              id="article-prompt"
              value={prompt}
              onChange={(event) => onPromptChange(event.target.value)}
              placeholder={typedSuggestion || "Search a trend"}
            />
            <button type="submit">Write</button>
          </div>
        </form>
      </section>

      <NewsDashboard
        activeSection={activeSection}
        stories={stories}
        newsletterEmail={newsletterEmail}
        onNewsletterChange={onNewsletterChange}
        onToast={onToast}
        onPromptStory={onPromptStory}
      />
    </>
  );
}
