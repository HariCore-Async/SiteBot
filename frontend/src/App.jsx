import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "./api.js";
import Login from "./Login.jsx";
import Sidebar from "./Sidebar.jsx";
import AddSite from "./AddSite.jsx";
import ChatView from "./ChatView.jsx";
import Admin from "./Admin.jsx";
import Dashboard from "./Dashboard.jsx";
import { applyInitialTheme } from "./ThemeToggle.jsx";

applyInitialTheme();

export default function App() {
  const [config, setConfig] = useState(null);
  const [me, setMe] = useState(undefined); // undefined = loading, null = signed out
  const [sites, setSites] = useState([]);
  const [chats, setChats] = useState([]);
  const [usage, setUsage] = useState(null);
  // view: {type: "add"} | {type: "progress", siteId} | {type: "chat", siteId, chatId} | {type: "admin"}
  const [view, setView] = useState({ type: "home" });
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    api.get("/api/config").then(setConfig).catch(() => setConfig({ google_client_id: "", dev_auth: false }));
    api
      .get("/api/me")
      .then((m) => {
        setMe(m);
        setUsage(m.usage);
      })
      .catch(() => setMe(null));
  }, []);

  const handleAuthError = useCallback((e) => {
    if (e instanceof ApiError && e.status === 401) setMe(null);
  }, []);

  const refreshSites = useCallback(() => api.get("/api/sites").then(setSites).catch(handleAuthError), [handleAuthError]);
  const refreshChats = useCallback(() => api.get("/api/chats").then(setChats).catch(handleAuthError), [handleAuthError]);
  const refreshUsage = useCallback(() => api.get("/api/usage").then(setUsage).catch(handleAuthError), [handleAuthError]);

  useEffect(() => {
    if (!me) return;
    refreshSites();
    refreshChats();
  }, [me, refreshSites, refreshChats]);

  // Keep polling while any bot is being indexed so progress and status stay live.
  const anyRunning = sites.some((s) => s.running || s.status === "queued" || s.status === "crawling" || s.status === "embedding");
  useEffect(() => {
    if (!me || !anyRunning) return;
    const t = setInterval(refreshSites, 1500);
    return () => clearInterval(t);
  }, [me, anyRunning, refreshSites]);

  const onLogin = useCallback((user) => {
    setMe(user);
    api.get("/api/usage").then(setUsage).catch(() => {});
  }, []);

  const logout = async () => {
    await api.post("/api/auth/logout").catch(() => {});
    window.google?.accounts?.id?.disableAutoSelect?.();
    setMe(null);
    setChats([]);
    setSites([]);
    setView({ type: "home" });
  };

  const go = (v) => {
    setView(v);
    setSidebarOpen(false);
  };

  const siteById = useMemo(() => Object.fromEntries(sites.map((s) => [s.id, s])), [sites]);

  if (me === undefined || !config) return <div className="splash">Loading…</div>;
  if (!me) return <Login config={config} onLogin={onLogin} />;

  let main;
  if (view.type === "admin" && me.role === "admin") {
    main = <Admin me={me} sites={sites} refreshSites={refreshSites} onUsageChange={refreshUsage} />;
  } else if (view.type === "progress" && siteById[view.siteId]) {
    main = (
      <AddSite
        sites={sites}
        site={siteById[view.siteId]}
        refreshSites={refreshSites}
        onOpen={(siteId) => go({ type: "progress", siteId })}
        onChat={(siteId) => go({ type: "chat", siteId, chatId: null })}
      />
    );
  } else if (view.type === "chat" && siteById[view.siteId]) {
    // One conversation per bot: open the existing one wherever the bot was opened from.
    const chatId = view.chatId ?? chats.find((c) => c.site_id === view.siteId)?.id ?? null;
    main = (
      <ChatView
        key={`${view.siteId}-${chatId ?? "new"}`}
        site={siteById[view.siteId]}
        chatId={chatId}
        onChatCreated={(chatId) => {
          setView({ type: "chat", siteId: view.siteId, chatId });
          refreshChats();
        }}
        onAnswered={(u) => {
          if (u) setUsage(u);
          refreshChats();
        }}
      />
    );
  } else if (view.type === "add") {
    main = (
      <AddSite
        sites={sites}
        refreshSites={refreshSites}
        onOpen={(siteId) => go({ type: "progress", siteId })}
        onChat={(siteId) => go({ type: "chat", siteId, chatId: null })}
      />
    );
  } else {
    const usedSites = new Set(chats.map((c) => c.site_id));
    const myBots = sites.filter((s) => s.ready && (s.created_by === me.id || usedSites.has(s.id)));
    main = (
      <Dashboard
        me={me}
        myBots={myBots}
        libraryCount={sites.filter((s) => s.ready).length - myBots.length}
        onCreate={() => go({ type: "add" })}
        onChat={(siteId) => go({ type: "chat", siteId, chatId: null })}
      />
    );
  }

  return (
    <div className={`app ${sidebarOpen ? "sidebar-open" : ""}`}>
      <Sidebar
        me={me}
        sites={sites}
        chats={chats}
        usage={usage}
        view={view}
        go={go}
        logout={logout}
      />
      <div className="scrim" onClick={() => setSidebarOpen(false)} />
      <main className="main">
        <button className="icon-btn menu-btn" onClick={() => setSidebarOpen(true)} aria-label="Open menu">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        {main}
      </main>
    </div>
  );
}
