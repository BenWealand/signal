import { useMemo, useState } from "react";
import { apiPost } from "../../api/client.js";

function replyIntentUrl(intentUrl, replyUrl) {
  const postId = String(replyUrl || "").match(/\/(?:i\/web\/)?status\/(\d+)/i)?.[1];
  if (!intentUrl || !postId) return intentUrl;
  try {
    const intent = new URL(intentUrl);
    intent.searchParams.set("in_reply_to", postId);
    return intent.toString();
  } catch {
    return intentUrl;
  }
}

export function XUrlMatchQueue({ dryRun, busy, setBusy, push, onToast }) {
  const [paste, setPaste] = useState("");
  const [rows, setRows] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const [source, setSource] = useState("");
  const [loaded, setLoaded] = useState(false);

  const orderedRows = useMemo(() => (
    [...rows].sort((left, right) => {
      const matchedOrder = Number(right.status === "matched") - Number(left.status === "matched");
      if (matchedOrder !== 0) return matchedOrder;
      return Number(right.confidence || 0) - Number(left.confidence || 0);
    })
  ), [rows]);

  const matchableIds = useMemo(
    () => rows.filter((row) => row.status === "matched" && row.articleId).map((row) => row.postId),
    [rows],
  );

  const runMatch = async () => {
    if (!paste.trim()) {
      onToast?.("Paste one or more X post URLs first.");
      return;
    }
    setBusy("url-match");
    push("matching pasted X URLs to ready articles...");
    try {
      const data = await apiPost("/admin/x/match-urls", { urls: paste, hours: 72 });
      const nextRows = data.rows || [];
      setRows(nextRows);
      setSource(data.source || "");
      setSelectedIds(nextRows.filter((row) => row.status === "matched").map((row) => row.postId));
      setLoaded(true);
      push(
        `url match ${data.source || "done"} → ${data.matched || 0}/${data.count || 0} matched from ${data.articleCount || 0} articles`,
        "ok",
      );
    } catch (error) {
      push(`url match failed: ${error?.detail || error?.message || "unknown error"}`, "error");
      onToast?.("Could not match X URLs.");
    } finally {
      setBusy("");
    }
  };

  const toggleRow = (postId) => {
    setSelectedIds((current) => (
      current.includes(postId)
        ? current.filter((id) => id !== postId)
        : [...current, postId]
    ));
  };

  const copyDraft = async (row) => {
    try {
      await navigator.clipboard.writeText(row.replyText || "");
      push(`copied matched draft for ${row.postId}`, "ok");
      onToast?.("Draft copied.");
    } catch {
      onToast?.("Could not copy draft.");
    }
  };

  const postSelected = async () => {
    const selected = rows.filter((row) => selectedIds.includes(row.postId) && row.status === "matched");
    if (!selected.length) {
      onToast?.("Select at least one matched row.");
      return;
    }
    if (!dryRun && !window.confirm(`Reply with ${selected.length} matched article${selected.length === 1 ? "" : "s"} on X now?`)) {
      return;
    }

    setBusy("url-share");
    push(`${dryRun ? "dry-run" : "live reply"} match queue started — ${selected.length} posts`);
    let completed = 0;
    let failed = 0;
    for (const row of selected) {
      try {
        const result = await apiPost("/admin/x/feed-share", {
          article_id: row.articleId,
          dry_run: dryRun,
          reply_url: row.url,
        });
        const successful = ["posted", "dry_run", "already_posted"].includes(result.status);
        if (successful) completed += 1;
        else failed += 1;
        push(
          `${row.postId}: ${result.status} → ${row.headline}${result.postUrl ? ` -> ${result.postUrl}` : ""}`,
          successful ? "ok" : "warn",
        );
        if (result.status === "posted" || result.status === "already_posted") {
          setRows((current) => current.map((item) => (
            item.postId === row.postId
              ? {
                  ...item,
                  xShare: {
                    posted: true,
                    postId: result.postId || "",
                    postUrl: result.postUrl || "",
                    replyToPostId: result.replyToPostId || row.postId,
                    replyUrl: result.replyUrl || row.url,
                  },
                }
              : item
          )));
          setSelectedIds((current) => current.filter((id) => id !== row.postId));
        }
      } catch (error) {
        failed += 1;
        push(
          `${row.postId}: failed — ${error?.detail || error?.message || "unknown error"}`,
          "error",
        );
      }
    }
    setBusy("");
    push(`url match queue finished — ${completed} complete, ${failed} failed`, failed ? "warn" : "ok");
    onToast?.(
      dryRun
        ? `Dry-run finished for ${completed} matched post${completed === 1 ? "" : "s"}.`
        : `Replied to ${completed} post${completed === 1 ? "" : "s"} on X.`,
    );
  };

  return (
    <section className="x-admin-feed-queue x-admin-url-match" aria-label="Match X URLs to ready articles">
      <div className="x-admin-feed-head">
        <div>
          <strong>Match X URLs</strong>
          <em>
            Paste many x.com links. Gemini matches each post to a ready Signal article, then you can view or reply/post one by one.
          </em>
        </div>
        <div className="x-admin-draft-actions">
          <button type="button" className="secondary-action" disabled={Boolean(busy)} onClick={runMatch}>
            {busy === "url-match" ? "Matching…" : "Match URLs"}
          </button>
          {loaded ? (
            <>
              <button
                type="button"
                className="secondary-action"
                disabled={Boolean(busy) || matchableIds.length === 0}
                onClick={() => setSelectedIds(matchableIds)}
              >
                Select matched
              </button>
              <button
                type="button"
                className="secondary-action"
                disabled={Boolean(busy) || selectedIds.length === 0}
                onClick={() => setSelectedIds([])}
              >
                Clear
              </button>
              <button
                type="button"
                className="secondary-action"
                disabled={Boolean(busy) || selectedIds.length === 0}
                onClick={postSelected}
              >
                {busy === "url-share"
                  ? "Working…"
                  : `${dryRun ? "Dry-run" : "Reply"} selected (${selectedIds.length})`}
              </button>
            </>
          ) : null}
        </div>
      </div>

      <textarea
        className="x-admin-url-paste"
        aria-label="Paste X post URLs"
        value={paste}
        onChange={(event) => setPaste(event.target.value)}
        placeholder={"https://x.com/user/status/123\nhttps://x.com/other/status/456\n…"}
        rows={5}
        disabled={Boolean(busy)}
      />

      {loaded ? (
        orderedRows.length ? (
          <div className="x-admin-feed-list">
            {source ? <p className="x-admin-feed-empty">Matcher: {source}</p> : null}
            {orderedRows.map((row) => {
              const posted = Boolean(row.xShare?.posted);
              const matched = row.status === "matched";
              return (
                <article
                  className="x-admin-feed-row"
                  key={row.postId}
                  data-posted={posted ? "1" : "0"}
                  data-matched={matched ? "1" : "0"}
                >
                  <div className="x-admin-feed-row-head">
                    <label>
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(row.postId)}
                        disabled={Boolean(busy) || !matched || posted}
                        onChange={() => toggleRow(row.postId)}
                      />
                      <span>{matched ? (row.section || "latest") : "unmatched"}</span>
                    </label>
                    <span>{Math.round((row.confidence || 0) * 100)}%</span>
                    <a href={row.url} target="_blank" rel="noreferrer">X post</a>
                    {posted && row.xShare?.postUrl ? (
                      <a href={row.xShare.postUrl} target="_blank" rel="noreferrer">Replied</a>
                    ) : (
                      <em>{matched ? "Ready" : "No article"}</em>
                    )}
                  </div>
                  <p className="x-admin-match-meta">
                    {row.author ? `@${row.author} — ` : ""}
                    {row.postText || row.lookupError || "Post text unavailable"}
                  </p>
                  {matched ? (
                    <>
                      <pre>{row.replyText}</pre>
                      <div className="x-admin-feed-row-actions">
                        <button type="button" onClick={() => copyDraft(row)}>Copy</button>
                        <a href={row.articleUrl} target="_blank" rel="noreferrer">Article</a>
                        <a href={replyIntentUrl(row.intentUrl, row.url)} target="_blank" rel="noreferrer">
                          Open in X
                        </a>
                      </div>
                    </>
                  ) : (
                    <p className="x-admin-feed-empty">{row.reason || "No matching ready article."}</p>
                  )}
                </article>
              );
            })}
          </div>
        ) : (
          <p className="x-admin-feed-empty">No X URLs were found in the pasted text.</p>
        )
      ) : null}
    </section>
  );
}
