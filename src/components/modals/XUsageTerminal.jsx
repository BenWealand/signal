import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost, hasApiBase } from "../../api/client.js";
import { isAdminAccount } from "../../lib/admin.js";

function stamp() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function summarizeCandidate(candidate, index) {
  const handle = candidate.author_handle ? `@${candidate.author_handle}` : "unknown";
  const topic = candidate.topic || candidate.prompt || "topic";
  return `#${index + 1} ${handle} — ${String(topic).slice(0, 72)}`;
}

/**
 * Admin-only X usage board.
 * Requires a live `/admin/me` success — localStorage role spoofing is not enough.
 */
export function XUsageTerminal({ account, onToast }) {
  const [allowed, setAllowed] = useState(false);
  const [checking, setChecking] = useState(true);
  const [lines, setLines] = useState([]);
  const [status, setStatus] = useState(null);
  const [query, setQuery] = useState("federal reserve");
  const [busy, setBusy] = useState("");
  const scrollerRef = useRef(null);

  const push = useCallback((text, kind = "info") => {
    setLines((prev) => [...prev.slice(-120), { uid: `${Date.now()}-${Math.random()}`, at: stamp(), text, kind }]);
  }, []);

  useEffect(() => {
    const node = scrollerRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [lines]);

  useEffect(() => {
    let active = true;
    setChecking(true);
    setAllowed(false);

    if (!isAdminAccount(account) || !hasApiBase()) {
      setChecking(false);
      return () => {
        active = false;
      };
    }

    apiGet("/admin/me")
      .then((data) => {
        if (!active) return;
        if (data?.admin) {
          setAllowed(true);
        } else {
          setAllowed(false);
        }
      })
      .catch(() => {
        if (active) setAllowed(false);
      })
      .finally(() => {
        if (active) setChecking(false);
      });

    return () => {
      active = false;
    };
  }, [account]);

  const refreshStatus = useCallback(async () => {
    if (!hasApiBase()) {
      push("No API base configured (VITE_SIGNAL_API_URL).", "error");
      return;
    }
    setBusy("status");
    try {
      const data = await apiGet("/admin/x/status");
      setStatus(data);
      const xc = data.xClient || {};
      push(
        `status ok — read=${xc.readConfigured ? "yes" : "no"} write=${xc.writeConfigured ? "yes" : "no"} dryRun=${xc.dryRunDefault ? "on" : "off"}`,
        "ok",
      );
    } catch (error) {
      push(`status failed: ${error?.detail || error?.message || "unknown error"}`, "error");
      onToast?.("Admin X status failed — sign in as the admin account.");
      setAllowed(false);
    } finally {
      setBusy("");
    }
  }, [onToast, push]);

  useEffect(() => {
    if (allowed) refreshStatus();
  }, [allowed, refreshStatus]);

  if (checking) {
    return (
      <div className="x-admin-terminal x-admin-terminal-locked">
        <p>Verifying admin access…</p>
      </div>
    );
  }

  if (!allowed) {
    return null;
  }

  const runSearch = async () => {
    const q = query.trim();
    if (!q) return;
    setBusy("search");
    push(`search "${q}"…`);
    try {
      const data = await apiPost("/admin/x/search", { query: q, limit: 6 });
      const rows = data.candidates || [];
      push(`search ${data.provider || "x-api"} → ${rows.length} hits`, "ok");
      rows.slice(0, 6).forEach((row, index) => push(summarizeCandidate(row, index)));
    } catch (error) {
      push(`search failed: ${error?.detail || error?.message || "unknown error"}`, "error");
    } finally {
      setBusy("");
    }
  };

  const runDiscover = async () => {
    setBusy("discover");
    push("discover candidates (desk → X search)…");
    try {
      const data = await apiGet("/admin/x/trends?limit=8");
      push(`discover ${data.provider} → ${data.count}/${data.rawCount} actionable`, "ok");
      (data.candidates || []).slice(0, 8).forEach((row, index) => push(summarizeCandidate(row, index)));
    } catch (error) {
      push(`discover failed: ${error?.detail || error?.message || "unknown error"}`, "error");
    } finally {
      setBusy("");
    }
  };

  const runAgent = async () => {
    setBusy("run");
    push("run agent (max 1 article, dry_run=true)…");
    try {
      const data = await apiPost("/admin/x/run", {
        max_articles: 1,
        discover_limit: 8,
        query: query.trim() || undefined,
        mode: "fast",
        dry_run: true,
        auto_post: false,
      });
      push(
        `run ${data.status} provider=${data.provider} discovered=${data.discovered} written=${data.written}`,
        data.status === "ok" ? "ok" : "warn",
      );
      (data.packages || []).forEach((pkg, index) => {
        const url = pkg.articleUrl || pkg.article_url || "";
        push(
          `package#${index + 1} ${pkg.status}${url ? ` → ${url}` : ""}${pkg.error ? ` (${pkg.error})` : ""}`,
          pkg.status === "ready_to_post" || pkg.status === "shared" ? "ok" : "warn",
        );
        if (pkg.replyText || pkg.reply_text) {
          push(`reply: ${String(pkg.replyText || pkg.reply_text).slice(0, 160)}`);
        }
      });
      onToast?.("X agent run finished (dry-run).");
    } catch (error) {
      push(`run failed: ${error?.detail || error?.message || "unknown error"}`, "error");
      onToast?.("X agent run failed.");
    } finally {
      setBusy("");
    }
  };

  const xc = status?.xClient || {};

  return (
    <div className="x-admin-terminal">
      <div className="x-admin-terminal-head">
        <div>
          <strong>X API usage terminal</strong>
          <em>Admin only — search, discover, and dry-run the agent.</em>
        </div>
        <div className="x-admin-badges">
          <span data-on={xc.readConfigured ? "1" : "0"}>read {xc.readConfigured ? "ready" : "off"}</span>
          <span data-on={xc.writeConfigured ? "1" : "0"}>write {xc.writeConfigured ? "ready" : "off"}</span>
          <span data-on={xc.dryRunDefault ? "1" : "0"}>dry-run {xc.dryRunDefault ? "on" : "off"}</span>
        </div>
      </div>

      <div className="x-admin-controls">
        <input
          aria-label="X search query"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search query or topic seed"
          onKeyDown={(event) => {
            if (event.key === "Enter") runSearch();
          }}
        />
        <button type="button" disabled={Boolean(busy)} onClick={refreshStatus}>
          {busy === "status" ? "…" : "Status"}
        </button>
        <button type="button" disabled={Boolean(busy)} onClick={runDiscover}>
          {busy === "discover" ? "…" : "Discover"}
        </button>
        <button type="button" disabled={Boolean(busy)} onClick={runSearch}>
          {busy === "search" ? "…" : "Search"}
        </button>
        <button type="button" className="x-admin-run" disabled={Boolean(busy)} onClick={runAgent}>
          {busy === "run" ? "Running…" : "Run agent"}
        </button>
      </div>

      <div className="terminal-card build-terminal x-admin-log" ref={scrollerRef}>
        <div className="terminal-bar">
          <span>signal://admin/x</span>
          <span>{busy ? `busy:${busy}` : "idle"}</span>
        </div>
        <code>
          {lines.length === 0 ? (
            <span className="is-active"><em>Waiting for commands…</em></span>
          ) : (
            lines.map((line) => (
              <span key={line.uid} data-kind={line.kind}>
                <i>{line.at}</i> <em>{line.text}</em>
              </span>
            ))
          )}
        </code>
      </div>
    </div>
  );
}
