import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost, getAccessToken, hasApiBase } from "../../api/client.js";
import { isAdminAccount } from "../../lib/admin.js";

function stamp() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function summarizeCandidate(candidate, index) {
  const handle = candidate.author_handle ? `@${candidate.author_handle}` : "unknown";
  const topic = candidate.topic || candidate.prompt || "topic";
  return `#${index + 1} ${handle} — ${String(topic).slice(0, 72)}`;
}

function accountKey(account) {
  if (!account) return "";
  return String(account.id || account.supabase_user_id || account.email || "").trim().toLowerCase();
}

function explainAdminError(error) {
  const detail = String(error?.detail || error?.message || "").trim();
  const status = Number(error?.status || 0);
  if (!hasApiBase()) {
    return "API URL is not configured (VITE_SIGNAL_API_URL).";
  }
  if (/missing authentication token/i.test(detail)) {
    return "Your sign-in session is missing or expired. Sign out, sign back in, then reopen Settings.";
  }
  if (/invalid authentication token/i.test(detail)) {
    return "The API could not verify your session token. On Render, set SUPABASE_URL to your project URL (for ES256/JWKS) or ensure SUPABASE_JWT_SECRET matches for HS256 tokens, then redeploy.";
  }
  if (/not configured \(SUPABASE_URL or SUPABASE_JWT_SECRET\)/i.test(detail)
    || /not configured \(SUPABASE_JWT_SECRET\)/i.test(detail)
    || status === 503) {
    return "Backend auth is not configured. Set SUPABASE_URL (recommended) and/or SUPABASE_JWT_SECRET on Render.";
  }
  if (/admin access required/i.test(detail) || status === 403) {
    return "Backend rejected admin access for this account. Confirm SIGNAL_ADMIN_EMAILS includes your email.";
  }
  if (status === 401) {
    return "Your sign-in session is missing or expired. Sign out, sign back in, then reopen Settings.";
  }
  return detail || "Could not verify admin access with the API.";
}

/**
 * Admin-only X usage board.
 * Requires a live `/admin/me` success — localStorage role spoofing is not enough.
 * Once verified for an account, stay open for that Settings session.
 */
export function XUsageTerminal({ account, onToast }) {
  const [allowed, setAllowed] = useState(false);
  const [checking, setChecking] = useState(true);
  const [verifyError, setVerifyError] = useState("");
  const [lines, setLines] = useState([]);
  const [status, setStatus] = useState(null);
  const [query, setQuery] = useState("federal reserve");
  const [mode, setMode] = useState("fast");
  const [maxArticles, setMaxArticles] = useState(1);
  const [discoverLimit, setDiscoverLimit] = useState(8);
  const [dryRun, setDryRun] = useState(true);
  const [autoPost, setAutoPost] = useState(false);
  const [lastDraft, setLastDraft] = useState(null);
  const [busy, setBusy] = useState("");
  const [retryToken, setRetryToken] = useState(0);
  const scrollerRef = useRef(null);
  const onToastRef = useRef(onToast);
  const accountRef = useRef(account);
  const verifiedKeyRef = useRef("");
  const statusFetchedForKeyRef = useRef("");
  const identity = accountKey(account);

  useEffect(() => {
    onToastRef.current = onToast;
  }, [onToast]);

  useEffect(() => {
    accountRef.current = account;
  }, [account]);

  const push = useCallback((text, kind = "info") => {
    setLines((prev) => [...prev.slice(-120), { uid: `${Date.now()}-${Math.random()}`, at: stamp(), text, kind }]);
  }, []);

  useEffect(() => {
    const node = scrollerRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [lines, lastDraft]);

  useEffect(() => {
    let active = true;
    const currentAccount = accountRef.current;

    if (identity && verifiedKeyRef.current === identity) {
      setAllowed(true);
      setChecking(false);
      setVerifyError("");
      return () => {
        active = false;
      };
    }

    if (!isAdminAccount(currentAccount)) {
      verifiedKeyRef.current = "";
      setAllowed(false);
      setChecking(false);
      setVerifyError("This account is not marked as admin in the app.");
      return () => {
        active = false;
      };
    }
    if (!hasApiBase()) {
      verifiedKeyRef.current = "";
      setAllowed(false);
      setChecking(false);
      setVerifyError("API URL is not configured (VITE_SIGNAL_API_URL).");
      return () => {
        active = false;
      };
    }

    setChecking(true);
    setVerifyError("");

    (async () => {
      try {
        const token = await getAccessToken({ refresh: true });
        if (!active) return;
        if (!token) {
          verifiedKeyRef.current = "";
          setAllowed(false);
          setVerifyError("No live Supabase session token. Sign out, sign back in, then reopen Settings.");
          return;
        }
        const data = await apiGet("/admin/me");
        if (!active) return;
        if (data?.admin) {
          verifiedKeyRef.current = identity;
          setAllowed(true);
          setVerifyError("");
        } else {
          verifiedKeyRef.current = "";
          setAllowed(false);
          setVerifyError("API did not grant admin access for this session.");
        }
      } catch (error) {
        if (!active) return;
        verifiedKeyRef.current = "";
        setAllowed(false);
        setVerifyError(explainAdminError(error));
      } finally {
        if (active) setChecking(false);
      }
    })();

    return () => {
      active = false;
    };
  }, [identity, retryToken]);

  const refreshStatus = useCallback(async ({ quietToast = false } = {}) => {
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
      if (!quietToast) onToastRef.current?.("Admin X status failed — check the terminal log.");
    } finally {
      setBusy("");
    }
  }, [push]);

  useEffect(() => {
    if (!allowed || !identity) return;
    if (statusFetchedForKeyRef.current === identity) return;
    statusFetchedForKeyRef.current = identity;
    refreshStatus({ quietToast: true });
  }, [allowed, identity, refreshStatus]);

  if (checking && !allowed) {
    return (
      <div className="x-admin-terminal x-admin-terminal-locked">
        <p>Verifying admin access with the API…</p>
        <em>This can take a moment while Render wakes up.</em>
      </div>
    );
  }

  if (!allowed) {
    return (
      <div className="x-admin-terminal x-admin-terminal-locked">
        <strong>X admin terminal unavailable</strong>
        <p>{verifyError || "Admin verification failed."}</p>
        <button
          className="secondary-action"
          type="button"
          onClick={() => {
            verifiedKeyRef.current = "";
            statusFetchedForKeyRef.current = "";
            setRetryToken((value) => value + 1);
          }}
        >
          Retry admin check
        </button>
      </div>
    );
  }

  const runSearch = async () => {
    const q = query.trim();
    if (!q) return;
    setBusy("search");
    push(`search "${q}"…`);
    try {
      const data = await apiPost("/admin/x/search", { query: q, limit: Math.min(discoverLimit, 12) });
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
    push(`discover candidates (limit ${discoverLimit})…`);
    try {
      const data = await apiGet(`/admin/x/trends?limit=${encodeURIComponent(discoverLimit)}`);
      push(`discover ${data.provider} → ${data.count}/${data.rawCount} actionable`, "ok");
      (data.candidates || []).slice(0, 8).forEach((row, index) => push(summarizeCandidate(row, index)));
    } catch (error) {
      push(`discover failed: ${error?.detail || error?.message || "unknown error"}`, "error");
    } finally {
      setBusy("");
    }
  };

  const runPromote = async () => {
    setBusy("promote");
    setLastDraft(null);
    push(
      `promote — write ${maxArticles} · mode=${mode} · dryRun=${dryRun ? "on" : "off"} · autoPost=${autoPost ? "on" : "off"}…`,
    );
    try {
      const data = await apiPost("/admin/x/run", {
        max_articles: maxArticles,
        discover_limit: discoverLimit,
        query: query.trim() || undefined,
        mode,
        dry_run: dryRun,
        auto_post: autoPost,
      });
      push(
        `promote ${data.status} provider=${data.provider} discovered=${data.discovered} written=${data.written}`,
        data.status === "ok" ? "ok" : "warn",
      );
      let draft = null;
      (data.packages || []).forEach((pkg, index) => {
        const url = pkg.articleUrl || pkg.article_url || "";
        push(
          `package#${index + 1} ${pkg.status}${url ? ` → ${url}` : ""}${pkg.error ? ` (${pkg.error})` : ""}`,
          pkg.status === "ready_to_post" || pkg.status === "shared" ? "ok" : "warn",
        );
        const reply = pkg.replyText || pkg.reply_text || "";
        if (reply && !draft) {
          draft = {
            reply,
            url,
            intentUrl: pkg.intentUrl || pkg.intent_url || (pkg.share || {}).intentUrl || "",
            status: pkg.status,
          };
        }
      });
      if (draft) {
        setLastDraft(draft);
        push("draft ready — first two lines + half of third + /article link", "ok");
      }
      onToastRef.current?.(
        autoPost && !dryRun ? "Promote finished (live post attempted)." : "Promote finished — article written, post drafted.",
      );
    } catch (error) {
      push(`promote failed: ${error?.detail || error?.message || "unknown error"}`, "error");
      onToastRef.current?.("Promote failed.");
    } finally {
      setBusy("");
    }
  };

  const copyDraft = async () => {
    if (!lastDraft?.reply) return;
    try {
      await navigator.clipboard.writeText(lastDraft.reply);
      onToastRef.current?.("Draft post copied.");
      push("copied promote draft to clipboard", "ok");
    } catch {
      onToastRef.current?.("Could not copy draft.");
    }
  };

  const xc = status?.xClient || {};

  return (
    <div className="x-admin-terminal">
      <div className="x-admin-terminal-head">
        <div>
          <strong>X API usage terminal</strong>
          <em>Promote writes a sourced article, then drafts an X post with a live `/article` link.</em>
        </div>
        <div className="x-admin-badges">
          <span data-on={xc.readConfigured ? "1" : "0"}>read {xc.readConfigured ? "ready" : "off"}</span>
          <span data-on={xc.writeConfigured ? "1" : "0"}>write {xc.writeConfigured ? "ready" : "off"}</span>
          <span data-on={dryRun ? "1" : "0"}>dry-run {dryRun ? "on" : "off"}</span>
          <span data-on={autoPost ? "1" : "0"}>auto-post {autoPost ? "on" : "off"}</span>
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
        <button type="button" disabled={Boolean(busy)} onClick={() => refreshStatus()}>
          {busy === "status" ? "…" : "Status"}
        </button>
        <button type="button" disabled={Boolean(busy)} onClick={runDiscover}>
          {busy === "discover" ? "…" : "Discover"}
        </button>
        <button type="button" disabled={Boolean(busy)} onClick={runSearch}>
          {busy === "search" ? "…" : "Search"}
        </button>
        <button type="button" className="x-admin-run" disabled={Boolean(busy)} onClick={runPromote}>
          {busy === "promote" ? "Promoting…" : "Promote"}
        </button>
      </div>

      <div className="x-admin-config">
        <label>
          Mode
          <select
            aria-label="Write mode"
            value={mode}
            onChange={(event) => setMode(event.target.value)}
            disabled={Boolean(busy)}
          >
            <option value="fast">Fast</option>
            <option value="thorough">Thorough</option>
          </select>
        </label>
        <label>
          Articles
          <select
            aria-label="Max articles"
            value={maxArticles}
            onChange={(event) => setMaxArticles(Number(event.target.value))}
            disabled={Boolean(busy)}
          >
            <option value={1}>1</option>
            <option value={2}>2</option>
            <option value={3}>3</option>
          </select>
        </label>
        <label>
          Discover
          <select
            aria-label="Discover limit"
            value={discoverLimit}
            onChange={(event) => setDiscoverLimit(Number(event.target.value))}
            disabled={Boolean(busy)}
          >
            <option value={4}>4</option>
            <option value={8}>8</option>
            <option value={12}>12</option>
            <option value={16}>16</option>
          </select>
        </label>
        <label className="x-admin-config-toggle">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(event) => setDryRun(event.target.checked)}
            disabled={Boolean(busy)}
          />
          <span>Dry-run X post</span>
        </label>
        <label className="x-admin-config-toggle">
          <input
            type="checkbox"
            checked={autoPost}
            onChange={(event) => setAutoPost(event.target.checked)}
            disabled={Boolean(busy)}
          />
          <span>Auto-post when ready</span>
        </label>
      </div>

      {lastDraft ? (
        <div className="x-admin-draft">
          <div className="x-admin-draft-head">
            <strong>Promote draft</strong>
            <div className="x-admin-draft-actions">
              <button type="button" className="secondary-action" onClick={copyDraft}>
                Copy draft
              </button>
              {lastDraft.intentUrl ? (
                <a className="secondary-action" href={lastDraft.intentUrl} target="_blank" rel="noreferrer">
                  Open in X
                </a>
              ) : null}
              {lastDraft.url ? (
                <a className="secondary-action" href={lastDraft.url} target="_blank" rel="noreferrer">
                  Open article
                </a>
              ) : null}
            </div>
          </div>
          <pre>{lastDraft.reply}</pre>
        </div>
      ) : null}

      <div className="terminal-card x-admin-log" ref={scrollerRef}>
        <div className="x-admin-log-bar">
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
