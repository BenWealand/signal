import { useMemo, useState } from "react";
import { apiGet, apiPost } from "../../api/client.js";

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

export function XFeedDraftQueue({ dryRun, replyUrl, busy, setBusy, push, onToast }) {
  const [drafts, setDrafts] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const [loaded, setLoaded] = useState(false);

  const orderedDrafts = useMemo(() => (
    [...drafts].sort((left, right) => {
      const postedOrder = Number(Boolean(left.xShare?.posted)) - Number(Boolean(right.xShare?.posted));
      if (postedOrder !== 0) return postedOrder;
      return new Date(right.createdAt || 0).getTime() - new Date(left.createdAt || 0).getTime();
    })
  ), [drafts]);

  const loadDrafts = async () => {
    setBusy("feed-drafts");
    push("loading stored feed drafts from the last 24 hours...");
    try {
      const data = await apiGet("/admin/x/feed-drafts?hours=24&limit=200");
      const rows = data.drafts || [];
      setDrafts(rows);
      setSelectedIds(rows.filter((draft) => !draft.xShare?.posted).map((draft) => draft.articleId));
      setLoaded(true);
      push(`feed drafts ready - ${data.count || 0} total, ${data.unposted || 0} unposted`, "ok");
    } catch (error) {
      push(`feed drafts failed: ${error?.detail || error?.message || "unknown error"}`, "error");
      onToast?.("Could not load feed drafts.");
    } finally {
      setBusy("");
    }
  };

  const toggleDraft = (articleId) => {
    setSelectedIds((current) => (
      current.includes(articleId)
        ? current.filter((id) => id !== articleId)
        : [...current, articleId]
    ));
  };

  const copyDraft = async (draft) => {
    try {
      await navigator.clipboard.writeText(draft.replyText || "");
      push(`copied feed draft: ${draft.headline}`, "ok");
      onToast?.("Draft copied.");
    } catch {
      onToast?.("Could not copy draft.");
    }
  };

  const postSelected = async () => {
    const selected = drafts.filter((draft) => selectedIds.includes(draft.articleId));
    if (!selected.length) {
      onToast?.("Select at least one feed draft.");
      return;
    }

    const replying = Boolean(replyUrl.trim());
    const action = replying ? "Reply with" : "Post";
    if (!dryRun && !window.confirm(`${action} ${selected.length} article${selected.length === 1 ? "" : "s"} on X now?`)) {
      return;
    }

    setBusy("feed-share");
    push(`${dryRun ? "dry-run" : replying ? "live reply" : "live post"} queue started - ${selected.length} drafts`);
    let completed = 0;
    let failed = 0;
    for (const draft of selected) {
      try {
        const result = await apiPost("/admin/x/feed-share", {
          article_id: draft.articleId,
          dry_run: dryRun,
          reply_url: replyUrl.trim() || undefined,
        });
        const successful = ["posted", "dry_run", "already_posted"].includes(result.status);
        if (successful) completed += 1;
        else failed += 1;
        push(
          `${draft.section || "latest"}: ${result.status} - ${draft.headline}${result.postUrl ? ` -> ${result.postUrl}` : ""}`,
          successful ? "ok" : "warn",
        );
        if (result.status === "posted" || result.status === "already_posted") {
          setDrafts((current) => current.map((item) => (
            item.articleId === draft.articleId
              ? {
                  ...item,
                  xShare: {
                    posted: true,
                    postId: result.postId || "",
                    postUrl: result.postUrl || "",
                    replyToPostId: result.replyToPostId || "",
                    replyUrl: result.replyUrl || "",
                  },
                }
              : item
          )));
          setSelectedIds((current) => current.filter((id) => id !== draft.articleId));
        }
      } catch (error) {
        failed += 1;
        push(
          `${draft.section || "latest"}: failed - ${draft.headline} (${error?.detail || error?.message || "unknown error"})`,
          "error",
        );
      }
    }
    setBusy("");
    push(`feed queue finished - ${completed} complete, ${failed} failed`, failed ? "warn" : "ok");
    onToast?.(
      dryRun
        ? `Dry-run finished for ${completed} draft${completed === 1 ? "" : "s"}.`
        : `${replying ? "Replied with" : "Posted"} ${completed} article${completed === 1 ? "" : "s"} on X.`,
    );
  };

  return (
    <section className="x-admin-feed-queue" aria-label="Recent feed article drafts">
      <div className="x-admin-feed-head">
        <div>
          <strong>Feed drafts</strong>
          <em>
            {replyUrl.trim()
              ? "Selected articles will be posted as replies to the X link above."
              : "Unique Gemini articles published across Signal desks in the last 24 hours."}
          </em>
        </div>
        <div className="x-admin-draft-actions">
          <button type="button" className="secondary-action" disabled={Boolean(busy)} onClick={loadDrafts}>
            {busy === "feed-drafts" ? "Loading..." : "Load 24h drafts"}
          </button>
          {loaded ? (
            <>
              <button
                type="button"
                className="secondary-action"
                disabled={Boolean(busy)}
                onClick={() => setSelectedIds(
                  drafts.filter((draft) => !draft.xShare?.posted).map((draft) => draft.articleId),
                )}
              >
                Select unposted
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
                {busy === "feed-share"
                  ? "Working..."
                  : `${dryRun ? "Dry-run" : replyUrl.trim() ? "Reply" : "Post"} selected (${selectedIds.length})`}
              </button>
            </>
          ) : null}
        </div>
      </div>

      {loaded ? (
        orderedDrafts.length ? (
          <div className="x-admin-feed-list">
            {orderedDrafts.map((draft) => {
              const posted = Boolean(draft.xShare?.posted);
              const replied = Boolean(draft.xShare?.replyToPostId);
              return (
                <article className="x-admin-feed-row" key={draft.articleId} data-posted={posted ? "1" : "0"}>
                  <div className="x-admin-feed-row-head">
                    <label>
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(draft.articleId)}
                        disabled={Boolean(busy) || posted}
                        onChange={() => toggleDraft(draft.articleId)}
                      />
                      <span>{draft.section || "latest"}</span>
                    </label>
                    <span>{draft.sourceCount || 0} sources</span>
                    <time dateTime={draft.createdAt || ""}>
                      {draft.createdAt ? new Date(draft.createdAt).toLocaleString() : "Recent"}
                    </time>
                    {posted && draft.xShare.postUrl ? (
                      <a href={draft.xShare.postUrl} target="_blank" rel="noreferrer">
                        {replied ? "Replied" : "Posted"}
                      </a>
                    ) : (
                      <em>{posted ? "Posted" : "Ready"}</em>
                    )}
                  </div>
                  <pre>{draft.replyText}</pre>
                  <div className="x-admin-feed-row-actions">
                    <button type="button" onClick={() => copyDraft(draft)}>Copy</button>
                    <a href={draft.articleUrl} target="_blank" rel="noreferrer">Article</a>
                    <a href={replyIntentUrl(draft.intentUrl, replyUrl)} target="_blank" rel="noreferrer">
                      Open in X
                    </a>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <p className="x-admin-feed-empty">No eligible Gemini articles were published in the last 24 hours.</p>
        )
      ) : null}
    </section>
  );
}
