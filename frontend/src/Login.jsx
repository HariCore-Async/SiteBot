import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import ThemeToggle from "./ThemeToggle.jsx";
import { ArrowRightIcon, LogoMark } from "./Icons.jsx";

function GoogleButton({ clientId, onCredential }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!clientId) return;
    let cancelled = false;
    const init = () => {
      if (cancelled) return;
      if (!window.google?.accounts?.id || !ref.current) return setTimeout(init, 200);
      window.google.accounts.id.initialize({ client_id: clientId, callback: ({ credential }) => onCredential(credential) });
      window.google.accounts.id.renderButton(ref.current, {
        theme: document.documentElement.dataset.theme === "dark" ? "filled_black" : "outline",
        size: "large",
        shape: "pill",
        text: "continue_with",
        width: 320,
      });
    };
    init();
    return () => {
      cancelled = true;
    };
  }, [clientId, onCredential]);
  return <div ref={ref} className="google-btn" />;
}

function Field({ label, hint, ...props }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input {...props} />
      {hint && <small className="muted">{hint}</small>}
    </label>
  );
}

function SignIn({ onLogin, busy, run }) {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  return (
    <form
      className="auth-form"
      onSubmit={(e) => {
        e.preventDefault();
        run(async () => onLogin(await api.post("/api/auth/login", { identifier, password })));
      }}
    >
      <Field label="Email or username" autoComplete="username" required value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
      <Field label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
      <button className="btn primary block" disabled={busy}>
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}

function SignUp({ onCodeSent, busy, run }) {
  const [form, setForm] = useState({ name: "", email: "", username: "", password: "", confirm_password: "" });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const mismatch = form.confirm_password && form.password !== form.confirm_password;
  return (
    <form
      className="auth-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (mismatch) return;
        run(async () => {
          const res = await api.post("/api/auth/signup", form);
          onCodeSent(res.email);
        });
      }}
    >
      <Field label="Full name" autoComplete="name" required value={form.name} onChange={set("name")} />
      <Field label="Email" type="email" autoComplete="email" required value={form.email} onChange={set("email")} />
      <Field
        label="Username"
        autoComplete="username"
        required
        pattern="[A-Za-z0-9_.]{3,30}"
        title="3–30 letters, numbers, dots or underscores"
        value={form.username}
        onChange={set("username")}
      />
      <Field
        label="Password"
        type="password"
        autoComplete="new-password"
        required
        minLength={8}
        hint="At least 8 characters, with a letter and a number."
        value={form.password}
        onChange={set("password")}
      />
      <Field
        label="Confirm password"
        type="password"
        autoComplete="new-password"
        required
        value={form.confirm_password}
        onChange={set("confirm_password")}
        hint={mismatch ? "The passwords don't match." : ""}
      />
      <button className="btn primary block" disabled={busy || mismatch}>
        {busy ? "Sending code…" : "Create account"}
      </button>
    </form>
  );
}

function VerifyEmail({ email, onLogin, onBack, busy, run }) {
  const [code, setCode] = useState("");
  const [resent, setResent] = useState(false);
  return (
    <form
      className="auth-form"
      onSubmit={(e) => {
        e.preventDefault();
        run(async () => onLogin(await api.post("/api/auth/verify", { email, code })));
      }}
    >
      <div className="verify-intro">
        <h2>Check your email</h2>
        <p className="muted">
          We sent a 6-digit code to <strong>{email}</strong>. Enter it below to confirm the address and finish creating your account.
        </p>
      </div>
      <input
        className="otp-input"
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={6}
        required
        autoFocus
        placeholder="••••••"
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
        aria-label="Verification code"
      />
      <button className="btn primary block" disabled={busy || code.length !== 6}>
        {busy ? "Verifying…" : "Verify and continue"}
      </button>
      <div className="auth-links">
        <button
          type="button"
          className="link-btn"
          disabled={busy}
          onClick={() =>
            run(async () => {
              await api.post("/api/auth/resend", { email });
              setResent(true);
            })
          }
        >
          {resent ? "Code sent again" : "Resend code"}
        </button>
        <button type="button" className="link-btn" onClick={onBack}>
          Use a different email
        </button>
      </div>
    </form>
  );
}

const FEATURES = [
  {
    title: "Any website, one link",
    text: "Paste a link and SiteBot reads the site's public pages, and optionally its PDFs, to build a chatbot for it.",
  },
  {
    title: "Answers you can trust",
    text: "Every answer comes only from the site's own content, with links to its sources. If the site doesn't say, the bot says so.",
  },
  {
    title: "Two chats side by side",
    text: "Compare two websites at once, and pick up any conversation right where you left it.",
  },
  {
    title: "Private by invitation",
    text: "Only approved people and company domains can sign in, with per-user spending limits.",
  },
];

function Landing({ onStart }) {
  return (
    <div className="landing">
      <div className="login-theme">
        <ThemeToggle />
      </div>
      <div className="landing-inner">
        <LogoMark size={64} />
        <h1>SiteBot</h1>
        <p>Turn any website into a chatbot that answers only from what the site says.</p>
        <button className="btn primary landing-cta" onClick={onStart} autoFocus>
          Get started <ArrowRightIcon />
        </button>
      </div>
    </div>
  );
}

export default function Login({ config, onLogin }) {
  const [started, setStarted] = useState(false);
  const [mode, setMode] = useState("signin"); // signin | signup | verify
  const [pendingEmail, setPendingEmail] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [devEmail, setDevEmail] = useState("");

  const run = async (fn) => {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const switchMode = (m) => {
    setError("");
    setMode(m);
  };

  if (!started) return <Landing onStart={() => setStarted(true)} />;

  return (
    <div className="login split">
      <div className="login-theme">
        <ThemeToggle />
      </div>
      <section className="login-info">
        <div className="info-brand">
          <LogoMark size={30} /> SiteBot
        </div>
        <h2>Chat with any website.</h2>
        <p className="info-lead">Give SiteBot a link. It learns the site and answers your questions from it, with sources.</p>
        <ul className="features">
          {FEATURES.map((f, i) => (
            <li key={f.title}>
              <span className="feature-n">{i + 1}</span>
              <div>
                <strong>{f.title}</strong>
                <p>{f.text}</p>
              </div>
            </li>
          ))}
        </ul>
      </section>
      <section className="login-side">
      <div className="login-card">
        <div className="login-brand">
          <LogoMark size={40} />
          <h1>{mode === "signup" ? "Create your account" : mode === "verify" ? "Verify your email" : "Welcome back"}</h1>
          <p className="muted">
            {mode === "signup" ? "Start chatting with any website in minutes." : mode === "verify" ? "One last step." : "Sign in to SiteBot to continue."}
          </p>
        </div>

        {mode === "verify" ? (
          <VerifyEmail email={pendingEmail} onLogin={onLogin} onBack={() => switchMode("signup")} busy={busy} run={run} />
        ) : (
          <>
            <div className="auth-tabs" role="tablist">
              <button role="tab" aria-selected={mode === "signin"} className={mode === "signin" ? "active" : ""} onClick={() => switchMode("signin")}>
                Sign in
              </button>
              <button role="tab" aria-selected={mode === "signup"} className={mode === "signup" ? "active" : ""} onClick={() => switchMode("signup")}>
                Create account
              </button>
            </div>

            {config.google_client_id && (
              <>
                <GoogleButton clientId={config.google_client_id} onCredential={(credential) => run(async () => onLogin(await api.post("/api/auth/google", { credential })))} />
                <div className="divider">
                  <span>or {mode === "signin" ? "sign in" : "sign up"} with email</span>
                </div>
              </>
            )}

            {mode === "signin" ? (
              <SignIn onLogin={onLogin} busy={busy} run={run} />
            ) : (
              <SignUp
                busy={busy}
                run={run}
                onCodeSent={(email) => {
                  setPendingEmail(email);
                  setMode("verify");
                }}
              />
            )}
          </>
        )}

        {error && <p className="error">{error}</p>}

        {config.dev_auth && mode !== "verify" && (
          <form
            className="dev-login"
            onSubmit={(e) => {
              e.preventDefault();
              run(async () => onLogin(await api.post("/api/auth/dev", { email: devEmail })));
            }}
          >
            <span className="tag">Dev login (local only)</span>
            <div className="dev-row">
              <input type="email" required placeholder="you@company.com" value={devEmail} onChange={(e) => setDevEmail(e.target.value)} />
              <button className="btn ghost">Go</button>
            </div>
          </form>
        )}

        <p className="fine">Access is by invitation. Your email (or your company's domain) must be approved by an admin.</p>
      </div>
      </section>
    </div>
  );
}
