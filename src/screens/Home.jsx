import { Globe } from "../../components/ui/globe.tsx";
import { GenerationModeToggle } from "../components/GenerationModeToggle.jsx";

export function HomeScreen({
  globeMarkers,
  onGlobeMarkerClick,
  onSubmit,
  prompt,
  onPromptChange,
  generationMode,
  onGenerationModeChange,
  typedSuggestion,
}) {
  return (
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
        <GenerationModeToggle value={generationMode} onChange={onGenerationModeChange} />
        <div className="prompt-row">
          <input
            id="article-prompt"
            value={prompt}
            onChange={(event) => onPromptChange(event.target.value)}
            placeholder={typedSuggestion || "Search a trend"}
          />
          <button className="push-btn" type="submit">Write</button>
        </div>
      </form>
    </section>
  );
}
