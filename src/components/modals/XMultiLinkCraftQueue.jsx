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

/**
 * Paste many X links → craft one Signal article → view/reply each post in X
 * (same row actions pattern as the 24h feed drafts queue).
 */
export function XMultiLinkCraftQueue({ dryRun, mode, busy, setBusy, push, onToast }) {
  const [paste, setPaste] = useState("");
  const [focus, setFocus] = useState("");
  const [article, setArticle] = useState(null);
  const [rows, setRows] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const [loaded, setLoaded] = useState(false);

  const orderedRows = useMemo(() => (
    [...rows].sort((left, right) => {
      const readyOrder = Number(right.status === "ready") - Number(left.status === "ready");
      if (readyOrder !== 0) return readyOrder;
      return String(left.postId).localeCompare(String(right.postId));
    })
  ), [rows]);

  const readyIds = useMemo(
    () => rows.filter((row) => row.status === "ready" && !row.xShare?.posted).map((row) => row.postId),
    [rows],
  );

  const craftArticle = async () => {
    if (!paste.trim()) {
      onToast?.("Paste one or more X post URLs first.");
      return;
    }
    setBusy("multi-craft");
    push(`crafting one article from pasted X links (mode=${mode})…`);
    try {
      const data = await apiPost("/admin/x/craft-from-urls", {
        urls: paste,
        prompt: focus.trim() || undefined,
        mode,
        limit: 10,
      });
      const nextRows = data.posts || [];
      setArticle({
        articleId: data.articleId,
        articleUrl: data.articleUrl,
        headline: data.headline,
        section: data.section,
        sourceCount: data.sourceCount,
        replyText: data.replyText,
        intentUrl: data.intentUrl,
      });
      setRows(nextRows);
      setSelectedIds(nextRows.filter((row) => row.status === "ready").map((row) => row.postId));
      setLoaded(true);
      push(
        `multi-link craft ok → ${data.headline || data.articleId} · ${data.ready || 0}/${data.count || 0} posts ready`,
        "ok",
      );
      onToast?.("Article crafted — open each post in X below.");
    } catch (error) {
      push(`multi-link craft failed: ${error?.detail || error?.message || "unknown error"}`, "error");
      onToast?.("Could not craft article from those X links.");
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

  const copyDraft = async (text, label = "draft") => {
    try {
      await navigator.clipboard.writeText(text || "");
      push(`copied ${label}`, "ok");
      onToast?.("Draft copied.");
    } catch {
      onToast?.("Could not copy draft.");
    }
  };

  const openSelectedInX = () => {
    const selected = rows.filter((row) => selectedIds.includes(row.postId) && row.status === "ready");
    if (!selected.length) {
      onToast?.("Select at least one ready post.");
      return;
    }
    selected.forEach((row, index) => {
      const href = replyIntentUrl(row.intentUrl, row.url);
      if (!href) return;
      window.setTimeout(() => {
        window.open(href, "_blank", "noopener,noreferrer");
      }, index * 350);
    });
    push(`opened ${selected.length} X compose window${selected.length === 1 ? "" : "s"}`, "ok");
  };

  const replySelected = async () => {
    const selected = rows.filter((row) => selectedIds.includes(row.postId) && row.status === "ready");
    if (!selected.length) {
      onToast?.("Select at least one ready post.");
      return;
    }
    if (!dryRun && !window.confirm(`Reply to ${selected.length} X post${selected.length === 1 ? "" : "s"} with this article now?`)) {
      return;
    }

    setBusy("multi-share");
    push(`${dryRun ? "dry-run" : "live reply"} multi-link queue — ${selected.length} posts`);
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
          `${row.postId}: ${result.status}${result.postUrl ? ` → ${result.postUrl}` : ""}`,
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
    push(`multi-link queue finished — ${completed} complete, ${failed} failed`, failed ? "warn" : "ok");
    onToast?.(
      dryRun
        ? `Dry-run finished for ${completed} post${completed === 1 ? "" : "s"}.`
        : `Replied to ${completed} post${completed === 1 ? "" : "s"} on X.`,
    );
  };

  return (
    <section className="x-admin-feed-queue x-admin-url-match" aria-label="Craft article from multiple X links">
      <div className="x-admin-feed-head">
        <div>
          <strong>Craft from X links</strong>
          <em>
            Paste many x.com links into one box. Signal writes a single article, then you can open each post in X — same workflow as 24h drafts.
          </em>
        </div>
        <div className="x-admin-draft-actions">
          <button type="button" className="secondary-action" disabled={Boolean(busy)} onClick={craftArticle}>
            {busy === "multi-craft" ? "Crafting…" : "Craft article"}
          </button>
          {loaded ? (
            <>
              <button
                type="button"
                className="secondary-action"
                disabled={Boolean(busy) || readyIds.length === 0}
                onClick={() => setSelectedIds(readyIds)}
              >
                Select ready
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
                onClick={openSelectedInX}
              >
                Open selected in X ({selectedIds.length})
              </button>
              <button
                type="button"
                className="secondary-action"
                disabled={Boolean(busy) || selectedIds.length === 0}
                onClick={replySelected}
              >
                {busy === "multi-share"
                  ? "Working…"
                  : `${dryRun ? "Dry-run" : "Reply"} selected (${selectedIds.length})`}
              </button>
            </>
          ) : null}
        </div>
      </div>

      <textarea
        className="x-admin-url-paste"
        aria-label="Paste multiple X post URLs"
        value={paste}
        onChange={(event) => setPaste(event.target.value)}
        placeholder={"https://x.com/user/status/123\nhttps://x.com/other/status/456\nhttps://x.com/third/status/789"}
        rows={5}
        disabled={Boolean(busy)}
      />
      <input
        className="x-admin-multi-focus"
        aria-label="Optional focus for the article"
        value={focus}
        onChange={(event) => setFocus(event.target.value)}
        placeholder="Optional focus (e.g. overnight Senate budget vote)"
        disabled={Boolean(busy)}
      />

      {loaded && article ? (
        <div className="x-admin-draft">
          <div className="x-admin-draft-head">
            <strong>Shared article draft</strong>
            <div className="x-admin-draft-actions">
              <button type="button" className="secondary-action" onClick={() => copyDraft(article.replyText, "shared draft")}>
                Copy draft
              </button>
              {article.articleUrl ? (
                <a className="secondary-action" href={article.articleUrl} target="_blank" rel="noreferrer">
                  Open article
                </a>
              ) : null}
            </div>
          </div>
          <p className="x-admin-match-meta">
            {article.section || "latest"} · {article.sourceCount || 0} sources · {article.headline}
          </p>
          <pre>{article.replyText}</pre>
        </div>
      ) : null}

      {loaded ? (
        orderedRows.length ? (
          <div className="x-admin-feed-list">
            {orderedRows.map((row) => {
              const posted = Boolean(row.xShare?.posted);
              const ready = row.status === "ready";
              return (
                <article
                  className="x-admin-feed-row"
                  key={row.postId}
                  data-posted={posted ? "1" : "0"}
                  data-matched={ready ? "1" : "0"}
                >
                  <div className="x-admin-feed-row-head">
                    <label>
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(row.postId)}
                        disabled={Boolean(busy) || !ready || posted}
                        onChange={() => toggleRow(row.postId)}
                      />
                      <span>{ready ? (row.section || "latest") : "lookup failed"}</span>
                    </label>
                    <a href={row.url} target="_blank" rel="noreferrer">X post</a>
                    {posted && row.xShare?.postUrl ? (
                      <a href={row.xShare.postUrl} target="_blank" rel="noreferrer">Replied</a>
                    ) : (
                      <em>{ready ? "Ready" : "Failed"}</em>
                    )}
                  </div>
                  <p className="x-admin-match-meta">
                    {row.author ? `@${row.author} — ` : ""}
                    {row.postText || row.lookupError || "Post text unavailable"}
                  </p>
                  {ready ? (
                    <>
                      <pre>{row.replyText}</pre>
                      <div className="x-admin-feed-row-actions">
                        <button type="button" onClick={() => copyDraft(row.replyText, row.postId)}>Copy</button>
                        <a href={row.articleUrl} target="_blank" rel="noreferrer">Article</a>
                        <a href={replyIntentUrl(row.intentUrl, row.url)} target="_blank" rel="noreferrer">
                          Open in X
                        </a>
                      </div>
                    </>
                  ) : (
                    <p className="x-admin-feed-empty">{row.lookupError || "Could not load this X post."}</p>
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
