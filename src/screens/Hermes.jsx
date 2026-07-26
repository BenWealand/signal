import { useEffect } from "react";
import { XUsageTerminal } from "../components/modals/XUsageTerminal.jsx";

export function HermesScreen({ account, onToast }) {
  useEffect(() => {
    const previousTitle = document.title;
    document.title = "Hermes | Signal Dispatch";
    return () => {
      document.title = previousTitle;
    };
  }, []);

  return (
    <section className="app-screen hermes-screen">
      <header>
        <span>Admin publishing</span>
        <div className="hermes-title-row">
          <h1>Hermes</h1>
          <p>X publishing desk</p>
        </div>
      </header>

      <div className="hermes-workspace" aria-label="Hermes X publishing desk">
        <XUsageTerminal account={account} onToast={onToast} />
      </div>
    </section>
  );
}
