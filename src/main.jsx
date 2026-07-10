import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { supabase } from "./lib/supabase.js";
import { apiGet, apiPost, apiPostAfterWake, hasApiBase, isAuthenticated, subscribeWakeState } from "./api/client.js";
import { useInitialSignalData } from "./hooks/useInitialSignalData.js";
import { useStoredState } from "./hooks/useStoredState.js";
import { SESSION_ID } from "./lib/session.js";
import { defaultSettings, SECTION_NAMES, SECTION_QUERIES, starterStories, trendPromptPreviews } from "./lib/constants.js";
import { buildDraft, dedupeStories, normalizeCommandArticle, storyTitle } from "./utils/articleNormalize.js";
import { isUsefulTrendTopic, makeGlobeMarkers, normalizeTrendingTopic } from "./utils/globeMarkers.js";
import { Header } from "./components/Header.jsx";
import { BuildScreen } from "./components/BuildScreen.jsx";
import { ArticleScreen } from "./components/ArticleScreen.jsx";
import { AccountModal } from "./components/modals/AccountModal.jsx";
import { SettingsModal } from "./components/modals/SettingsModal.jsx";
import { NotificationInboxModal } from "./components/modals/NotificationInboxModal.jsx";
import { HomeScreen } from "./screens/Home.jsx";
import { LatestScreen } from "./screens/Latest.jsx";
import { TrendsScreen } from "./screens/Trends.jsx";
import { SectionScreen } from "./screens/Section.jsx";
import { SavedScreen } from "./screens/Saved.jsx";
import { WakeStatus } from "./screens/shared.jsx";
import "./styles.css";

const OFFLINE_PREVIEW_DELAY_MS = Number(import.meta.env.VITE_SIGNAL_OFFLINE_PREVIEW_DELAY_MS || 7200);

function localFailureDraft(prompt, error) {
  return normalizeCommandArticle({
    ...buildDraft(prompt),
    id: `local-${Date.now()}`,
    prompt,
    localFallback: true,
    backendError: error?.message || "Article API unavailable.",
    source: "offline browser preview",
    tag: "offline-preview",
  });
}

function articleUrl(article) {
  if (!article?.id) return window.location.href;
  const url = new URL(window.location.href);
  url.search = "";
  url.hash = "";
  url.searchParams.set("article", article.id);
  return url.toString();
}

function trackEvent(userId, actionType, fields = {}) {
  isAuthenticated().then((authed) => {
    apiPost("/history", {
      user_id: authed ? userId || null : null,
      session_id: SESSION_ID,
      action_type: actionType,
      ...fields,
    }).catch(() => {});
  });
}

function App() {
  const [prompt, setPrompt] = useState("");
  const [draftPrompt, setDraftPrompt] = useState("");
  const [phase, setPhase] = useState("idle");
  const [activeScreen, setActiveScreen] = useState("Home");
  const [activeSection, setActiveSection] = useState("World");
  const [accountOpen, setAccountOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [toast, setToast] = useState("");
  const [commandArticles, setCommandArticles] = useState([]);
  const [backendStories, setBackendStories] = useState([]);
  const [trendingTopics, setTrendingTopics] = useState([]);
  const [apiStatus, setApiStatus] = useState("offline");
  const [wakeState, setWakeState] = useState({ status: hasApiBase() ? "idle" : "disabled" });
  const [externalDraft, setExternalDraft] = useState(null);
  const [account, setAccount] = useStoredState("signal-account", null);
  const [savedArticles, setSavedArticles] = useStoredState("signal-saved-articles", []);
  const [settings, setSettings] = useStoredState("signal-settings", defaultSettings);
  const [generationMode, setGenerationMode] = useStoredState("signal-generation-mode", "fast");
  const [newsletterEmail, setNewsletterEmail] = useStoredState("signal-newsletter", "");
  const [suggestionIndex, setSuggestionIndex] = useState(0);
  const [typedSuggestion, setTypedSuggestion] = useState("");
  const [articleSocial, setArticleSocial] = useState({ likeCount: 0, liked: false, comments: [] });
  const [notifications, setNotifications] = useState([]);

  useEffect(() => {
    const unsubscribeWake = subscribeWakeState(setWakeState);
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session?.user && !account) {
        const user = session.user;
        const restoredAccount = {
          name: user.user_metadata?.name || user.email.split("@")[0],
          email: user.email,
          plan: "Reader",
          supabase_user_id: user.id,
        };
        setAccount(restoredAccount);
        apiPost("/users", restoredAccount).then((saved) => {
          setAccount((prev) => ({ ...prev, id: saved.id }));
        }).catch(() => {});
      } else if (!session && account) {
        setAccount(null);
      }
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!session) setAccount(null);
    });
    return () => {
      unsubscribeWake();
      subscription.unsubscribe();
    };
  }, []);

  const hasDraft = draftPrompt.length > 0;
  const draft = useMemo(() => externalDraft || buildDraft(draftPrompt || prompt), [draftPrompt, prompt, externalDraft]);
  const trendSuggestions = useMemo(() => {
    const liveTopicPrompts = trendingTopics
      .filter(isUsefulTrendTopic)
      .map((topic, index) => normalizeTrendingTopic(topic, index)?.headline)
      .filter(Boolean);
    const articlePrompts = dedupeStories([...commandArticles, ...backendStories, ...starterStories], 18)
      .map((story) => story.prompt || storyTitle(story))
      .filter(Boolean);
    const candidates = [
      ...liveTopicPrompts,
      ...articlePrompts,
      ...trendPromptPreviews,
      ...Object.values(SECTION_QUERIES),
    ];
    return [...new Map(
      candidates
        .map((item) => String(item || "").trim())
        .filter((item) => item.length > 8)
        .map((item) => [item.toLowerCase(), item]),
    ).values()].slice(0, 32);
  }, [commandArticles, backendStories, trendingTopics]);
  const globeMarkers = useMemo(
    () => {
      const topicMarkers = trendingTopics
        .filter(isUsefulTrendTopic)
        .map(normalizeTrendingTopic)
        .filter(Boolean);
      const articleMarkers = makeGlobeMarkers([...commandArticles, ...backendStories], activeSection);
      const seen = new Set(topicMarkers.map((marker) => marker.headline.toLowerCase()));
      return [
        ...topicMarkers,
        ...articleMarkers.filter((marker) => !seen.has(String(marker.headline || "").toLowerCase())),
      ].slice(0, 18);
    },
    [trendingTopics, commandArticles, backendStories, activeSection],
  );

  useEffect(() => {
    const timer = window.setInterval(() => {
      setSuggestionIndex((index) => (index + 1) % Math.max(1, trendSuggestions.length));
    }, 4200);
    return () => window.clearInterval(timer);
  }, [trendSuggestions.length]);

  const currentSuggestion = trendSuggestions[suggestionIndex % trendSuggestions.length] || "climate pressure on coastal insurance markets";

  const currentArticleId = externalDraft?.id || "";
  const unreadNotificationCount = notifications.filter((item) => !item.is_read).length;

  useEffect(() => {
    setTypedSuggestion("");
    let index = 0;
    const text = currentSuggestion || "Search a trend";
    const timer = window.setInterval(() => {
      index += 1;
      setTypedSuggestion(text.slice(0, index));
      if (index >= text.length) window.clearInterval(timer);
    }, 28);
    return () => window.clearInterval(timer);
  }, [currentSuggestion]);

  useEffect(() => {
    if (!currentArticleId) {
      setArticleSocial({ likeCount: 0, liked: false, comments: [] });
      return;
    }
    const params = new URLSearchParams({ session_id: SESSION_ID });
    if (account?.id) params.set("user_id", String(account.id));
    apiGet(`/articles/${encodeURIComponent(currentArticleId)}/social?${params.toString()}`)
      .then(setArticleSocial)
      .catch(() => setArticleSocial({ likeCount: 0, liked: false, comments: [] }));
  }, [currentArticleId, account?.id]);

  useEffect(() => {
    if (!account?.id) {
      setNotifications([]);
      return;
    }
    apiGet(`/users/${account.id}/notifications`).then(setNotifications).catch(() => setNotifications([]));
  }, [account?.id, notificationsOpen]);

  const { feedsLoading } = useInitialSignalData({
    account,
    setApiStatus,
    setBackendStories,
    setCommandArticles,
    setTrendingTopics,
    setPrompt,
    setDraftPrompt,
    setExternalDraft,
    setPhase,
    setActiveScreen,
    trackEvent,
  });

  const handleSubmit = (event) => {
    event.preventDefault();
    const nextPrompt = prompt.trim() || currentSuggestion || "global public records";
    setExternalDraft(null);
    setDraftPrompt(nextPrompt);
    setPhase("building");
    if (hasApiBase()) showToast("Signal is on it. Waking the newsroom and sourcing your story...");
    trackEvent(account?.id, "prompt", { prompt: nextPrompt });
    apiPostAfterWake("/articles/write", { prompt: nextPrompt, source: "reader-prompt", tag: "prompt", limit: 10, mode: generationMode, user_id: account?.id || null })
      .then((article) => {
        setExternalDraft(normalizeCommandArticle(article));
        setPhase("complete");
      })
      .catch((error) => {
        handleArticleWriteFailure(nextPrompt, error);
      });
  };

  const showToast = (message) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2400);
  };

  const handleArticleWriteFailure = (failedPrompt, error) => {
    if (error?.status === 422 && String(error.detail || error.message || "").toLowerCase().includes("blocked")) {
      setExternalDraft(null);
      setPhase("idle");
      showToast("That prompt is blocked by the Signal prompt filter.");
      return;
    }
    if (hasApiBase()) {
      setExternalDraft(null);
      setPhase("idle");
      const rawMessage = String(error?.detail || error?.message || "");
      const message = rawMessage.includes("gemini_article_unavailable")
        || rawMessage.toLowerCase().includes("gemini")
        || rawMessage.toLowerCase().includes("source")
        ? "Could not generate from enough reliable sources. Try a more specific prompt."
        : rawMessage || "The newsroom is still waking up. Wait a moment and try again.";
      showToast(message);
      return;
    }
    window.setTimeout(() => {
      setExternalDraft(localFailureDraft(failedPrompt, error));
      setPhase("complete");
    }, OFFLINE_PREVIEW_DELAY_MS);
  };

  const buildRecommendedPrompt = (nextPrompt) => {
    if (!nextPrompt) return;
    setPrompt(nextPrompt);
    setExternalDraft(null);
    setDraftPrompt(nextPrompt);
    setPhase("building");
    setActiveScreen("Latest");
    if (hasApiBase()) showToast("Signal is on it. Waking the newsroom and sourcing your story...");
    trackEvent(account?.id, "prompt", { prompt: nextPrompt, topic: "recommended-follow-up" });
    apiPostAfterWake("/articles/write", { prompt: nextPrompt, source: "recommended-follow-up", tag: "prompt", limit: 10, mode: "fast", user_id: account?.id || null })
      .then((article) => {
        setExternalDraft(normalizeCommandArticle(article));
        setPhase("complete");
      })
      .catch((error) => {
        handleArticleWriteFailure(nextPrompt, error);
      });
  };

  const handleLikeArticle = () => {
    if (!draft?.id) return;
    apiPost(`/articles/${encodeURIComponent(draft.id)}/likes`, {
      user_id: account?.id || null,
      session_id: SESSION_ID,
      actor_name: account?.name || "Reader",
    }).then(setArticleSocial).catch(() => showToast("Like could not be saved."));
  };

  const handleCommentArticle = (body, parentCommentId = null) => {
    if (!draft?.id || !body.trim()) return;
    apiPost(`/articles/${encodeURIComponent(draft.id)}/comments`, {
      user_id: account?.id || null,
      session_id: SESSION_ID,
      author_name: account?.name || "Reader",
      body,
      parent_comment_id: parentCommentId,
    })
      .then(() => apiGet(`/articles/${encodeURIComponent(draft.id)}/social?session_id=${encodeURIComponent(SESSION_ID)}${account?.id ? `&user_id=${account.id}` : ""}`))
      .then(setArticleSocial)
      .catch(() => showToast("Comment could not be saved."));
  };

  const handleLikeComment = (commentId) => {
    apiPost(`/comments/${commentId}/likes`, {
      user_id: account?.id || null,
      session_id: SESSION_ID,
      actor_name: account?.name || "Reader",
    })
      .then(() => apiGet(`/articles/${encodeURIComponent(draft.id)}/social?session_id=${encodeURIComponent(SESSION_ID)}${account?.id ? `&user_id=${account.id}` : ""}`))
      .then(setArticleSocial)
      .catch(() => showToast("Comment like could not be saved."));
  };

  const openNotifications = () => {
    setNotificationsOpen(true);
    if (account?.id) {
      apiPost(`/users/${account.id}/notifications/read`, {}).catch(() => {});
    }
  };

  const handleSaveArticle = () => {
    const item = {
      id: `${Date.now()}`,
      title: draft.headline,
      prompt: draftPrompt,
      sourceCount: draft.sourceCount,
      savedAt: new Date().toLocaleString(),
    };
    setSavedArticles((current) => [item, ...current.filter((saved) => saved.title !== item.title)].slice(0, 12));
    apiPost("/saved-stories", {
      user_id: account?.id || null,
      story_id: draft.id || item.id,
      title: draft.headline,
      source_count: draft.sourceCount,
    }).catch(() => {});
    trackEvent(account?.id, "save", { article_id: draft.id || item.id, prompt: draftPrompt });
    showToast("Article saved to your account.");
  };

  const handleShareArticle = async () => {
    const shareText = `${draft.headline} - Signal Dispatch`;
    const url = articleUrl(draft);
    if (navigator.share) {
      await navigator.share({ title: draft.headline, text: shareText, url });
      return;
    }
    await navigator.clipboard.writeText(shareText);
    showToast("Share text copied.");
  };

  const handleCopyLink = async () => {
    await navigator.clipboard.writeText(articleUrl(draft));
    showToast("Article link copied.");
  };

  const handleShareX = () => {
    const text = encodeURIComponent(`${draft.headline} - Signal Dispatch`);
    const url = encodeURIComponent(articleUrl(draft));
    window.open(`https://x.com/intent/tweet?text=${text}&url=${url}`, "_blank", "noopener,noreferrer");
  };

  const openCommandArticle = (article) => {
    const finalize = (resolved) => {
      const normalized = normalizeCommandArticle(resolved);
      setPrompt(normalized.prompt);
      setDraftPrompt(normalized.prompt);
      setExternalDraft(normalized);
      setPhase("complete");
      setActiveScreen("Latest");
      if (normalized.id) window.history.replaceState(null, "", `?article=${encodeURIComponent(normalized.id)}`);
      window.scrollTo({ top: 0, behavior: "smooth" });
      trackEvent(account?.id, "view", { prompt: normalized.prompt, article_id: String(normalized.id) });
    };

    const needsFullArticle = hasApiBase()
      && article?.id
      && (!Array.isArray(article.body) || !article.body.length || article.preview);
    if (needsFullArticle) {
      apiGet(`/generated-articles/${encodeURIComponent(article.id)}`)
        .then(finalize)
        .catch(() => finalize(article));
      return;
    }
    finalize(article);
  };

  const startCommandPrompt = (article) => {
    setPrompt(article.prompt);
    setExternalDraft(null);
    setDraftPrompt(article.prompt);
    setPhase("building");
    setActiveScreen("Latest");
    if (hasApiBase()) showToast("Signal is on it. Waking the newsroom and sourcing your story...");
    apiPostAfterWake("/articles/write", { prompt: article.prompt, source: "reader-prompt", tag: "prompt", limit: 10, mode: generationMode, user_id: account?.id || null })
      .then((result) => {
        setExternalDraft(normalizeCommandArticle(result));
        setPhase("complete");
      })
      .catch((error) => {
        handleArticleWriteFailure(article.prompt, error);
      });
  };

  const handleGlobeMarkerClick = (marker) => {
    if (marker.article) {
      openCommandArticle(marker.article);
      return;
    }
    const topic = marker.prompt || marker.headline;
    if (!topic) return;
    setPrompt(topic);
    setExternalDraft(null);
    setDraftPrompt(topic);
    setPhase("building");
    setActiveScreen("Latest");
    if (hasApiBase()) showToast("Signal is on it. Waking the newsroom and sourcing your story...");
    trackEvent(account?.id, "prompt", { prompt: topic, section: "globe-trend" });
    apiPostAfterWake("/articles/write", { prompt: topic, source: "globe-trend", tag: "trend", limit: 10, mode: generationMode, user_id: account?.id || null })
      .then((article) => {
        setExternalDraft(normalizeCommandArticle(article));
        setPhase("complete");
      })
      .catch((error) => {
        handleArticleWriteFailure(topic, error);
      });
  };

  return (
    <section className="hero-shell">
      <Header
        activeScreen={activeScreen}
        onScreenChange={(screen) => {
          setActiveScreen(screen);
          setDraftPrompt("");
          setExternalDraft(null);
          setPhase("idle");
          window.scrollTo({ top: 0, behavior: "smooth" });
        }}
        onSectionChange={setActiveSection}
        onOpenAccount={() => setAccountOpen(true)}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenNotifications={openNotifications}
        notificationCount={unreadNotificationCount}
        signedInUser={account}
      />

      <main className="hero-main">
        {!hasDraft && activeScreen === "Home" && (
          <HomeScreen
            globeMarkers={globeMarkers}
            onGlobeMarkerClick={handleGlobeMarkerClick}
            onSubmit={handleSubmit}
            prompt={prompt}
            onPromptChange={setPrompt}
            generationMode={generationMode}
            onGenerationModeChange={setGenerationMode}
            typedSuggestion={typedSuggestion}
          />
        )}

        {!hasDraft && activeScreen === "Latest" && (
          <LatestScreen
            commandArticles={[...commandArticles, ...backendStories]}
            onOpenArticle={openCommandArticle}
            loading={feedsLoading}
            account={account}
          />
        )}

        {!hasDraft && activeScreen === "Trending" && (
          <TrendsScreen commandArticles={[...commandArticles, ...backendStories]} onOpenArticle={openCommandArticle} />
        )}

        {!hasDraft && activeScreen === "Saved" && (
          <SavedScreen savedArticles={savedArticles} account={account} onOpenAccount={() => setAccountOpen(true)} />
        )}

        {!hasDraft && SECTION_NAMES.includes(activeScreen) && (
          <SectionScreen
            section={activeScreen}
            account={account}
            onOpenArticle={openCommandArticle}
            onPrompt={(topic) => {
              setPrompt(topic);
              setDraftPrompt(topic);
              setExternalDraft(null);
              setPhase("building");
              setActiveScreen("Latest");
              if (hasApiBase()) showToast("Signal is on it. Waking the newsroom and sourcing your story...");
              trackEvent(account?.id, "prompt", { prompt: topic, section: activeScreen });
                apiPostAfterWake("/articles/write", { prompt: topic, source: "reader-prompt", tag: "prompt", limit: 10, mode: generationMode, user_id: account?.id || null })
                .then((article) => { setExternalDraft(normalizeCommandArticle(article)); setPhase("complete"); })
                .catch((error) => {
                  handleArticleWriteFailure(topic, error);
                });
            }}
          />
        )}

        {hasDraft && phase === "building" && <BuildScreen draft={draft} wakeState={wakeState} />}
        {hasDraft && phase === "complete" && (
          <ArticleScreen
            draft={draft}
            prompt={prompt}
            setPrompt={setPrompt}
            onSubmit={handleSubmit}
            generationMode={generationMode}
            onGenerationModeChange={setGenerationMode}
            onSave={handleSaveArticle}
            onShare={handleShareArticle}
            onCopyLink={handleCopyLink}
            onShareX={handleShareX}
            onRecommendedPrompt={buildRecommendedPrompt}
            social={articleSocial}
            onLikeArticle={handleLikeArticle}
            onCommentArticle={handleCommentArticle}
            onLikeComment={handleLikeComment}
          />
        )}
      </main>

      {accountOpen && (
        <AccountModal
          account={account}
          savedArticles={savedArticles}
          newsletterEmail={newsletterEmail}
          onNewsletterChange={setNewsletterEmail}
          onClose={() => setAccountOpen(false)}
          onSignIn={(nextAccount) => {
            setAccount(nextAccount);
            apiPost("/users", nextAccount)
              .then((savedUser) => setAccount({ ...nextAccount, id: savedUser.id }))
              .catch(() => {});
          }}
          onSignOut={() => {
              supabase.auth.signOut().catch(() => {});
              setAccount(null);
            }}
          onClearSaved={() => setSavedArticles([])}
          onToast={showToast}
        />
      )}
      {settingsOpen && (
        <SettingsModal
          settings={settings}
          onSettingsChange={setSettings}
          onClose={() => setSettingsOpen(false)}
          onToast={showToast}
          account={account}
        />
      )}
      {notificationsOpen && (
        <NotificationInboxModal
          account={account}
          notifications={notifications}
          onClose={() => setNotificationsOpen(false)}
        />
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
      <WakeStatus state={wakeState} />
    </section>
  );
}

createRoot(document.getElementById("root")).render(<App />);
