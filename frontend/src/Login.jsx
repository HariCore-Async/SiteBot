import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import ThemeToggle from "./ThemeToggle.jsx";

export default function Login({ config, onLogin }) {
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const buttonRef = useRef(null);

  useEffect(() => {
    if (!config.google_client_id) return;
    let cancelled = false;
    const init = () => {
      if (cancelled) return;
      if (!window.google?.accounts?.id) return setTimeout(init, 200);
      window.google.accounts.id.initialize({
        client_id: config.google_client_id,
        callback: async ({ credential }) => {
          setError("");
          try {
            onLogin(await api.post("/api/auth/google", { credential }));
          } catch (e) {
            setError(e.message);
          }
        },
      });
      window.google.accounts.id.renderButton(buttonRef.current, {
        theme: document.documentElement.dataset.theme === "dark" ? "filled_black" : "outline",
        size: "large",
        shape: "pill",
        text: "continue_with",
        width: 280,
      });
    };
    init();
    return () => {
      cancelled = true;
    };
  }, [config.google_client_id, onLogin]);

  const devLogin = async (e) => {
    e.preventDefault();
    setError("");
    try {
      onLogin(await api.post("/api/auth/dev", { email }));
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="login">
      <div className="login-theme">
        <ThemeToggle />
      </div>
      <div className="login-card">
        <div className="logo-mark">💬</div>
        <h1>SiteBot</h1>
        <p className="muted">Give it a website link. Ask questions. Get answers that come only from that site, with sources.</p>
        {config.google_client_id ? (
          <div ref={buttonRef} className="google-btn" />
        ) : (
          !config.dev_auth && <p className="error">Google sign-in isn't configured (GOOGLE_CLIENT_ID).</p>
        )}
        {config.dev_auth && (
          <form onSubmit={devLogin} className="dev-login">
            <span className="tag">Dev login</span>
            <input type="email" required placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} />
            <button className="btn primary">Sign in</button>
          </form>
        )}
        {error && <p className="error">{error}</p>}
        <p className="fine">Access is by invitation. Ask an admin to approve your email.</p>
      </div>
    </div>
  );
}
