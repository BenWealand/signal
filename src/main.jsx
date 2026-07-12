import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Analytics } from "@vercel/analytics/react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import { supabase } from "./lib/supabase.js";
import { apiGet, apiPost, writeArticle, hasApiBase, isAuthenticated } from "./api/client.js";
import { useInitialSignalData } from "./hooks/useInitialSignalData.js";
import { useStoredState } from "./hooks/useStoredState.js";
import { SESSION_ID } from "./lib/session.js";
import { defaultSettings, SECTION_NAMES, SECTION_QUERIES, starterStories, trendPromptPreviews } from "./lib/constants.js";
import { articlePath, articleUrl as buildArticleUrl, screenFromPathname, sectionSlug } from "./lib/routes.js";
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
import { syncAccountWithBackend } from "./lib/auth.js";
import { fetchSharedArticle, readArticleSessionCache, writeArticleSessionCache } from "./lib/articles.js";
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

function LegacyArticleRedirect() {
  const params = new URLSearchParams(useLocation().search);
  const articleId = params.get("article");
  if (!articleId) return <Navigate to="/" replace />;
  return <Navigate to={articlePath(articleId)} replace />;
}

function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const activeScreen = screenFromPathname(location.pathname);
  const activeSection = SECTION_NAMES.includes(activeScreen) ? activeScreen : "World";

  const [prompt, setPrompt] = useState("");
  const [draftPrompt, setDraftPrompt] = useState("");
  const [phase, setPhase] = useState("idle");
  const [accountOpen, setAccountOpen] = useState(false);
  const [accountMode, setAccountMode] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [toast, setToast] = useState("");
  const [commandArticles, setCommandArticles] = useState([]);
  const [backendStories, setBackendStories] = useState([]);
  const [trendingTopics, setTrendingTopics] = useState([]);
  const [apiStatus, setApiStatus] = useState("offline");
  const [externalDraft, setExternalDraft] = useState(null);
  const [activeBuildId, setActiveBuildId] = useState("");
  const [buildProgress, setBuildProgress] = useState(null);
  const [account, setAccount] = useStoredState("signal-account", null);
  const [savedArticles, setSavedArticles] = useStoredState("signal-saved-articles", []);
  const [settings, setSettings] = useStoredState("signal-settings", defaultSettings);
  const [generationMode, setGenerationMode] = useStoredState("signal-generation-mode", "fast");
  const [newsletterEmail, setNewsletterEmail] = useStoredState("signal-newsletter", "");
  const [suggestionIndex, setSuggestionIndex] = useState(0);
  const [typedSuggestion, setTypedSuggestion] = useState("");
  const [articleSocial, setArticleSocial] = useState({ likeCount: 0, liked: false, comments: [] });
  const [notifications, setNotifications] = useState([]);
  const toastTimerRef = useRef(0);

  useEffect(() => {
    let active = true;

    const applySession = async (session, { openRecover = false } = {}) => {
      if (!active) return;
      if (!session?.user) {
        setAccount(null);
        return;
      }
      const next = await syncAccountWithBackend(session.user);
      if (!active) return;
      setAccount(next);
      if (openRecover) {
        setAccountMode("recover");
        setAccountOpen(true);
      }
    };

    supabase.auth.getSession().then(({ data: { session } }) => {
      applySession(session);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === "PASSWORD_RECOVERY") {
        applySession(session, { openRecover: true });
        return;
      }
      if (event === "SIGNED_OUT") {
        setAccount(null);
        return;
      }
      if (session?.user) {
        applySession(session);
      } else {
        setAccount(null);
      }
    });

    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, []);

  // Support legacy share links: /?article=<id> → /article/<id>
  useEffect(() => {
    const legacyId = new URLSearchParams(location.search).get("article");
    if (legacyId && (location.pathname === "/" || location.pathname === "")) {
      navigate(articlePath(legacyId), { replace: true });
    }
  }, [location.pathname, location.search, navigate]);

  // Leaving article/write views via nav should clear the overlay draft.
  useEffect(() => {
    if (activeScreen === "Article" || phase === "building") return;
    if (draftPrompt || externalDraft || phase !== "idle") {
      setDraftPrompt("");
      setExternalDraft(null);
      setPhase("idle");
      setActiveBuildId("");
      setBuildProgress(null);
    }
  }, [location.pathname]);

  const hasDraft = draftPrompt.length > 0 || phase === "building" || activeScreen === "Article";
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
  });

  const clearDraft = () => {
    setDraftPrompt("");
    setExternalDraft(null);
    setPhase("idle");
    setActiveBuildId("");
    setBuildProgress(null);
  };

  const startArticleWrite = (nextPrompt, {
    source = "reader-prompt",
    tag = "prompt",
    mode = generationMode,
  } = {}) => {
    setExternalDraft(null);
    setDraftPrompt(nextPrompt);
    setPhase("building");
    setActiveBuildId("");
    setBuildProgress({ stage: "fetching", stage_label: "Connecting to sources..." });
    return writeArticle(
      {
        prompt: nextPrompt,
        source,
        tag,
        limit: mode === "thorough" ? 8 : 10,
        mode,
        user_id: account?.id || null,
      },
      {
        onProgress: (progress) => {
          if (progress?.build_id || progress?.buildId) {
            setActiveBuildId(progress.build_id || progress.buildId);
          }
          setBuildProgress(progress);
        },
      },
    )
      .then((article) => {
        const normalized = normalizeCommandArticle(article);
        setExternalDraft(normalized);
        setActiveBuildId(article.buildId || "");
        setBuildProgress(null);
        setPhase("complete");
        writeArticleSessionCache(normalized);
        if (normalized.id) {
          navigate(articlePath(normalized.id));
        }
      })
      .catch((error) => {
        setActiveBuildId("");
        setBuildProgress(null);
        handleArticleWriteFailure(nextPrompt, error);
      });
  };

  const handleSubmit = (event) => {
    event.preventDefault();
    const nextPrompt = prompt.trim() || currentSuggestion || "global public records";
    trackEvent(account?.id, "prompt", { prompt: nextPrompt });
    startArticleWrite(nextPrompt);
  };

  const showToast = (message, durationMs = 2400) => {
    setToast(message);
    window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(""), durationMs);
  };

  const handleArticleWriteFailure = (failedPrompt, error) => {
    if (error?.status === 422 && String(error.detail || error.message || "").toLowerCase().includes("blocked")) {
      clearDraft();
      showToast("That prompt is blocked by the Signal prompt filter.", 6000);
      return;
    }
    if (hasApiBase()) {
      clearDraft();
      const rawMessage = String(error?.detail || error?.message || "");
      const message = rawMessage.includes("gemini_article_unavailable")
        || rawMessage.toLowerCase().includes("gemini")
        || rawMessage.toLowerCase().includes("source")
        ? "Could not generate from enough reliable sources. Try a more specific prompt."
        : rawMessage || "Signal could not finish that write. Wait a moment and try again.";
      showToast(message, 6000);
      return;
    }
    window.setTimeout(() => {
      const offline = localFailureDraft(failedPrompt, error);
      setExternalDraft(offline);
      setPhase("complete");
      if (offline.id) navigate(articlePath(offline.id));
    }, OFFLINE_PREVIEW_DELAY_MS);
  };

  const buildRecommendedPrompt = (nextPrompt) => {
    if (!nextPrompt) return;
    setPrompt(nextPrompt);
    trackEvent(account?.id, "prompt", { prompt: nextPrompt, topic: "recommended-follow-up" });
    startArticleWrite(nextPrompt, {
      source: "recommended-follow-up",
      mode: "fast",
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
      articleId: draft.id || "",
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
    const url = buildArticleUrl(draft);
    if (navigator.share) {
      await navigator.share({ title: draft.headline, text: shareText, url });
      return;
    }
    await navigator.clipboard.writeText(shareText);
    showToast("Share text copied.");
  };

  const handleCopyLink = async () => {
    await navigator.clipboard.writeText(buildArticleUrl(draft));
    showToast("Article link copied.");
  };

  const handleShareX = () => {
    const text = encodeURIComponent(`${draft.headline} - Signal Dispatch`);
    const url = encodeURIComponent(buildArticleUrl(draft));
    window.open(`https://x.com/intent/tweet?text=${text}&url=${url}`, "_blank", "noopener,noreferrer");
  };

  const openCommandArticle = (article) => {
    const finalize = (resolved) => {
      const normalized = normalizeCommandArticle(resolved);
      setPrompt(normalized.prompt);
      setDraftPrompt(normalized.prompt);
      setExternalDraft(normalized);
      setPhase("complete");
      writeArticleSessionCache(normalized);
      if (normalized.id) {
        navigate(articlePath(normalized.id));
      }
      window.scrollTo({ top: 0, behavior: "smooth" });
      trackEvent(account?.id, "view", { prompt: normalized.prompt, article_id: String(normalized.id) });
    };

    const needsFullArticle = Boolean(article?.id)
      && (!Array.isArray(article.body) || !article.body.length || article.preview);
    if (needsFullArticle) {
      fetchSharedArticle(article.id, { preferCache: true })
        .then(({ article: full }) => finalize(full))
        .catch(() => finalize(article));
      return;
    }
    finalize(article);
  };

  const handleGlobeMarkerClick = (marker) => {
    if (marker.article) {
      openCommandArticle(marker.article);
      return;
    }
    const topic = marker.prompt || marker.headline;
    if (!topic) return;
    setPrompt(topic);
    trackEvent(account?.id, "prompt", { prompt: topic, section: "globe-trend" });
    startArticleWrite(topic, { source: "globe-trend", tag: "trend" });
  };

  const showBuild = phase === "building";
  const showArticle = activeScreen === "Article" && phase === "complete" && Boolean(externalDraft);

  return (
    <section className="hero-shell">
      <Header
        activeScreen={activeScreen}
        onNavigateAway={clearDraft}
        onOpenAccount={() => setAccountOpen(true)}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenNotifications={openNotifications}
        notificationCount={unreadNotificationCount}
        signedInUser={account}
      />

      <main className="hero-main">
        {showBuild ? (
          <BuildScreen
            draft={draft}
            buildId={activeBuildId}
            progress={buildProgress}
          />
        ) : null}

        <Routes>
          <Route
            index
            element={(
              showBuild || showArticle ? null : (
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
              )
            )}
          />
          <Route
            path="latest"
            element={(
              showBuild || showArticle ? null : (
                <LatestScreen
                  commandArticles={[...commandArticles, ...backendStories]}
                  onOpenArticle={openCommandArticle}
                  loading={feedsLoading}
                  account={account}
                />
              )
            )}
          />
          <Route
            path="trending"
            element={(
              showBuild || showArticle ? null : (
                <TrendsScreen commandArticles={[...commandArticles, ...backendStories]} onOpenArticle={openCommandArticle} />
              )
            )}
          />
          <Route
            path="saved"
            element={(
              showBuild || showArticle ? null : (
                <SavedScreen
                  savedArticles={savedArticles}
                  account={account}
                  onOpenAccount={() => setAccountOpen(true)}
                  onOpenArticle={openCommandArticle}
                />
              )
            )}
          />
          {SECTION_NAMES.map((section) => (
            <Route
              key={section}
              path={sectionSlug(section)}
              element={(
                showBuild || showArticle ? null : (
                  <SectionScreen
                    section={section}
                    account={account}
                    onOpenArticle={openCommandArticle}
                    onPrompt={(topic) => {
                      setPrompt(topic);
                      trackEvent(account?.id, "prompt", { prompt: topic, section });
                      startArticleWrite(topic);
                    }}
                  />
                )
              )}
            />
          ))}
          <Route path="sporks" element={<Navigate to="/sports" replace />} />
          <Route
            path="article/:articleId"
            element={(
              <ArticleRoute
                externalDraft={externalDraft}
                setExternalDraft={setExternalDraft}
                setDraftPrompt={setDraftPrompt}
                setPrompt={setPrompt}
                setPhase={setPhase}
                phase={phase}
                showBuild={showBuild}
                draft={draft}
                prompt={prompt}
                generationMode={generationMode}
                setGenerationMode={setGenerationMode}
                handleSubmit={handleSubmit}
                handleSaveArticle={handleSaveArticle}
                handleShareArticle={handleShareArticle}
                handleCopyLink={handleCopyLink}
                handleShareX={handleShareX}
                buildRecommendedPrompt={buildRecommendedPrompt}
                articleSocial={articleSocial}
                handleLikeArticle={handleLikeArticle}
                handleCommentArticle={handleCommentArticle}
                handleLikeComment={handleLikeComment}
                account={account}
                trackEvent={trackEvent}
                showToast={showToast}
              />
            )}
          />
          <Route path="*" element={<LegacyOrHome />} />
        </Routes>
      </main>

      {accountOpen && (
        <AccountModal
          account={account}
          savedArticles={savedArticles}
          onNewsletterChange={setNewsletterEmail}
          initialMode={accountMode}
          onClose={() => {
            setAccountOpen(false);
            setAccountMode("");
          }}
          onSignIn={(nextAccount) => {
            setAccount(nextAccount);
            setAccountMode("");
          }}
          onSignOut={() => {
            supabase.auth.signOut().catch(() => {});
            setAccount(null);
            setAccountMode("");
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
      <Analytics />
    </section>
  );
}

function LegacyOrHome() {
  const location = useLocation();
  if (new URLSearchParams(location.search).get("article")) {
    return <LegacyArticleRedirect />;
  }
  return <Navigate to="/" replace />;
}

function ArticleRoute({
  externalDraft,
  setExternalDraft,
  setDraftPrompt,
  setPrompt,
  setPhase,
  phase,
  showBuild,
  draft,
  prompt,
  generationMode,
  setGenerationMode,
  handleSubmit,
  handleSaveArticle,
  handleShareArticle,
  handleCopyLink,
  handleShareX,
  buildRecommendedPrompt,
  articleSocial,
  handleLikeArticle,
  handleCommentArticle,
  handleLikeComment,
  account,
  trackEvent,
  showToast,
}) {
  const { articleId } = useParams();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!articleId) return;
    if (externalDraft?.id && String(externalDraft.id) === String(articleId) && phase === "complete") {
      return;
    }
    let cancelled = false;
    setPhase("complete");

    const cached = readArticleSessionCache(articleId);
    if (cached?.headline) {
      const normalized = normalizeCommandArticle(cached);
      setPrompt(normalized.prompt);
      setDraftPrompt(normalized.prompt);
      setExternalDraft(normalized);
      setLoading(false);
    } else {
      setLoading(true);
    }

    fetchSharedArticle(articleId, { preferCache: false })
      .then(({ article }) => {
        if (cancelled) return;
        const normalized = normalizeCommandArticle(article);
        setPrompt(normalized.prompt);
        setDraftPrompt(normalized.prompt);
        setExternalDraft(normalized);
        setPhase("complete");
        trackEvent(account?.id, "view", { prompt: normalized.prompt, article_id: String(normalized.id) });
      })
      .catch(() => {
        if (!cancelled && !cached?.headline) showToast("Could not open that article.", 4000);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [articleId]);

  if (showBuild) return null;
  if (loading && !externalDraft) {
    return <div className="loading-state">Opening article…</div>;
  }
  if (!externalDraft) return null;

  return (
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
  );
}

createRoot(document.getElementById("root")).render(
  <BrowserRouter>
    <App />
  </BrowserRouter>,
);
