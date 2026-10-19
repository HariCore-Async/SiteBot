import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "./api.js";
import Login from "./Login.jsx";
import Sidebar from "./Sidebar.jsx";
import AddSite from "./AddSite.jsx";
import ChatView from "./ChatView.jsx";
import Admin from "./Admin.jsx";
import Dashboard from "./Dashboard.jsx";
import { MenuIcon } from "./Icons.jsx";
import { applyInitialTheme } from "./ThemeToggle.jsx";

applyInitialTheme();

export default function App() {
  const [config, setConfig] = useState(null);
  const [me, setMe] = useState(undefined); // undefined = loading, null = signed out
  const [sites, setSites] = useState([]);
  const [chats, setChats] = useState([]);
  const [usage, setUsage] = useState(null);
  // view: {type: "home"} | {type: "add"} | {type: "progress", siteId} | {type: "chat"} | {type: "admin"}
  const [view, setView] = useState({ type: "home" });
  // Open conversations, shown side by side (at most two). Closing one keeps its history on the server.
  const [panes, setPanes] = useState([]);
  const [activePane, setActivePane] = useState(0); // which pane shows on narrow screens
  const [toast, setToast] = useState("");
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
    setPanes([]);
  };

  const go = (v) => {
    setView(v);
    setSidebarOpen(false);
  };

  const MAX_PANES = 2;
  const showToast = (text) => {
    setToast(text);
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => setToast(""), 3500);
  };

  // Opens a bot's conversation: beside the current one if there's room.
  const openBot = (siteId) => {
    setSidebarOpen(false);
    const open = panes.filter((id) => sites.some((s) => s.id === id));
    const at = open.indexOf(siteId);
    if (at >= 0) {
      setActivePane(at);
    } else if (open.length < MAX_PANES) {
      setPanes([...open, siteId]);
      setActivePane(open.length);
    } else {
      const name = sites.find((s) => s.id === siteId)?.name || "that bot";
      showToast(`You can chat with two bots at a time. Close one to open ${name}.`);
    }
    setView({ type: "chat" });
  };

  const closePane = (siteId) => {
    const rest = panes.filter((id) => id !== siteId);
    setPanes(rest);
    setActivePane(0);
    if (!rest.length) setView({ type: "home" });
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
        onChat={openBot}
      />
    );
  } else if (view.type === "chat" && panes.some((id) => siteById[id])) {
    const open = panes.filter((id) => siteById[id]);
    const active = Math.min(activePane, open.length - 1);
    main = (
      <div className={`panes count-${open.length}`}>
        {open.length > 1 && (
          <div className="pane-tabs" role="tablist">
            {open.map((id, i) => (
              <button key={id} role="tab" aria-selected={i === active} className={i === active ? "active" : ""} onClick={() => setActivePane(i)}>
                {siteById[id].name}
              </button>
            ))}
          </div>
        )}
        {open.map((id, i) => (
          <div key={id} className={`pane ${i === active ? "active" : ""}`} onMouseDown={() => setActivePane(i)}>
            <ChatView
              site={siteById[id]}
              // One conversation per bot: always the user's existing one, if any.
              chatId={chats.find((c) => c.site_id === id)?.id ?? null}
              onChatCreated={() => refreshChats()}
              onAnswered={(u) => {
                if (u) setUsage(u);
                refreshChats();
              }}
              onClose={() => closePane(id)}
            />
          </div>
        ))}
      </div>
    );
  } else if (view.type === "add") {
    main = (
      <AddSite
        sites={sites}
        refreshSites={refreshSites}
        onOpen={(siteId) => go({ type: "progress", siteId })}
        onChat={openBot}
      />
    );
  } else {
    const usedSites = new Set(chats.map((c) => c.site_id));
    const myBots = sites.filter((s) => s.ready && (s.created_by === me.id || usedSites.has(s.id)));
    main = (
      <Dashboard
        me={me}
        myBots={myBots}
        onCreate={() => go({ type: "add" })}
        onChat={openBot}
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
        openSiteIds={view.type === "chat" ? panes : []}
        go={go}
        openBot={openBot}
        logout={logout}
      />
      <div className="scrim" onClick={() => setSidebarOpen(false)} />
      <main className="main">
        <button className="icon-btn menu-btn" onClick={() => setSidebarOpen(true)} aria-label="Open menu">
          <MenuIcon />
        </button>
        {main}
        {toast && (
          <div className="toast" role="status">
            {toast}
          </div>
        )}
      </main>
    </div>
  );
}
