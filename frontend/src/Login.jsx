import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import ThemeToggle from "./ThemeToggle.jsx";
import { ArrowRightIcon, LogoMark } from "./Icons.jsx";
import Showcase from "./Showcase.jsx";

// Google Identity Services must be initialised once per page; re-initialising on every render breaks the button.
let gisClientId = null;
const gisCallback = { current: null };

function GoogleButton({ clientId, onCredential }) {
  const ref = useRef(null);
  gisCallback.current = onCredential;
  useEffect(() => {
    if (!clientId) return;
    let cancelled = false;
    const init = () => {
      if (cancelled) return;
      if (!window.google?.accounts?.id || !ref.current) return setTimeout(init, 200);
      if (gisClientId !== clientId) {
        window.google.accounts.id.initialize({ client_id: clientId, callback: ({ credential }) => gisCallback.current?.(credential) });
        gisClientId = clientId;
      }
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
  }, [clientId]);
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

function ForgotPassword({ onLogin, onBack, busy, run }) {
  const [identifier, setIdentifier] = useState("");
  const [sent, setSent] = useState(false);
  const [form, setForm] = useState({ code: "", password: "", confirm_password: "" });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: k === "code" ? e.target.value.replace(/\D/g, "") : e.target.value }));
  const mismatch = form.confirm_password && form.password !== form.confirm_password;

  if (!sent) {
    return (
      <form
        className="auth-form"
        onSubmit={(e) => {
          e.preventDefault();
          run(async () => {
            await api.post("/api/auth/forgot", { identifier });
            setSent(true);
          });
        }}
      >
        <div className="verify-intro">
          <h2>Reset your password</h2>
          <p className="muted">Enter your email or username. If there's an account, we'll email it a 6-digit code.</p>
        </div>
        <Field label="Email or username" autoComplete="username" required autoFocus value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
        <button className="btn primary block" disabled={busy}>
          {busy ? "Sending…" : "Send code"}
        </button>
        <div className="auth-links">
          <button type="button" className="link-btn" onClick={onBack}>
            Back to sign in
          </button>
        </div>
      </form>
    );
  }
  return (
    <form
      className="auth-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (mismatch) return;
        run(async () => onLogin(await api.post("/api/auth/reset", { identifier, ...form })));
      }}
    >
      <div className="verify-intro">
        <h2>Check your email</h2>
        <p className="muted">If {identifier} has an account, we've sent it a code. Enter it and choose a new password.</p>
      </div>
      <input
        className="otp-input"
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={6}
        required
        autoFocus
        placeholder="••••••"
        value={form.code}
        onChange={set("code")}
        aria-label="Reset code"
      />
      <Field label="New password" type="password" autoComplete="new-password" required minLength={8} hint="At least 8 characters, with a letter and a number." value={form.password} onChange={set("password")} />
      <Field
        label="Confirm new password"
        type="password"
        autoComplete="new-password"
        required
        value={form.confirm_password}
        onChange={set("confirm_password")}
        hint={mismatch ? "The passwords don't match." : ""}
      />
      <button className="btn primary block" disabled={busy || form.code.length !== 6 || mismatch}>
        {busy ? "Saving…" : "Set new password"}
      </button>
      <div className="auth-links">
        <button type="button" className="link-btn" onClick={() => run(async () => api.post("/api/auth/forgot", { identifier }))}>
          Resend code
        </button>
        <button type="button" className="link-btn" onClick={onBack}>
          Back to sign in
        </button>
      </div>
    </form>
  );
}

function SignIn({ onLogin, onForgot, busy, run }) {
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
      <div className="forgot-row">
        <button type="button" className="link-btn" onClick={onForgot}>
          Forgot password?
        </button>
      </div>
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

const VALUES = [
  {
    title: "Grounded in the source",
    text: "Every answer is drawn from the website's own pages and cited, so it can be checked in one click.",
  },
  {
    title: "Honest about its limits",
    text: "When a site doesn't cover something, SiteBot says so rather than guessing.",
  },
  {
    title: "Built for teams",
    text: "Invite-only access, per-user budgets and side-by-side chats for comparing sites.",
  },
];

function CheckMark() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m5 12.5 4.5 4.5L19 7.5" />
    </svg>
  );
}

function Landing({ onStart }) {
  return (
    <div className="landing">
      <header className="landing-nav">
        <div className="info-brand">
          <LogoMark size={28} /> SiteBot
        </div>
        <div className="landing-nav-actions">
          <ThemeToggle />
          <button className="btn ghost small" onClick={() => onStart("signin")}>
            Sign in
          </button>
        </div>
      </header>

      <main className="landing-hero">
        <span className="eyebrow">Grounded answers, with sources</span>
        <h1>
          Every website,
          <br />
          now a conversation.
        </h1>
        <p>SiteBot reads a website and answers questions about it, using only what the site says.</p>
        <div className="landing-actions">
          <button className="btn primary landing-cta" onClick={() => onStart("signup")} autoFocus>
            Get started <ArrowRightIcon />
          </button>
          <button className="btn landing-cta secondary" onClick={() => onStart("signin")}>
            Sign in
          </button>
        </div>

        <Showcase />
      </main>
    </div>
  );
}

export default function Login({ config, onLogin }) {
  const [started, setStarted] = useState(false);
  const [mode, setMode] = useState("signin"); // signin | signup | verify
  const [pendingEmail, setPendingEmail] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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

  if (!started)
    return (
      <Landing
        onStart={(m) => {
          setMode(m);
          setStarted(true);
        }}
      />
    );

  return (
    <div className="login split">
      <div className="login-theme">
        <ThemeToggle />
      </div>
      <section className="login-info">
        <button className="info-brand plain" onClick={() => setStarted(false)} title="Back to the start page">
          <LogoMark size={30} /> SiteBot
        </button>
        <h2>Answers straight from the source.</h2>
        <p className="info-lead">
          SiteBot turns any website into an assistant that answers from that site alone, and shows where every answer came from.
        </p>
        <ul className="values">
          {VALUES.map((v) => (
            <li key={v.title}>
              <span className="value-check">
                <CheckMark />
              </span>
              <div>
                <strong>{v.title}</strong>
                <p>{v.text}</p>
              </div>
            </li>
          ))}
        </ul>
      </section>
      <section className="login-side">
      <div className="login-card">
        <div className="login-brand">
          <LogoMark size={40} />
          <h1>{mode === "signup" ? "Create your account" : mode === "verify" ? "Verify your email" : mode === "forgot" ? "Forgot password" : "Welcome back"}</h1>
          <p className="muted">
            {mode === "signup"
              ? "Start chatting with any website in minutes."
              : mode === "verify"
                ? "One last step."
                : mode === "forgot"
                  ? "We'll help you set a new one."
                  : "Sign in to SiteBot to continue."}
          </p>
        </div>

        {mode === "forgot" ? (
          <ForgotPassword onLogin={onLogin} onBack={() => switchMode("signin")} busy={busy} run={run} />
        ) : mode === "verify" ? (
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
              <SignIn onLogin={onLogin} onForgot={() => switchMode("forgot")} busy={busy} run={run} />
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


        {config.require_approval && (
          <p className="fine">Access is by invitation. Your email (or your company's domain) must be approved by an admin.</p>
        )}
      </div>
      </section>
    </div>
  );
}
