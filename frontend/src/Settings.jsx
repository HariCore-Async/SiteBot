import { useState } from "react";
import { api } from "./api.js";

function UsernameForm({ me, onUpdated }) {
  const [username, setUsername] = useState(me.username || "");
  const [msg, setMsg] = useState({});
  const save = async (e) => {
    e.preventDefault();
    setMsg({});
    try {
      onUpdated(await api.post("/api/me/username", { username }));
      setMsg({ ok: "Username saved." });
    } catch (err) {
      setMsg({ error: err.message });
    }
  };
  return (
    <form className="settings-card" onSubmit={save}>
      <h2>Username</h2>
      <p className="muted">You can sign in with your username or your email.</p>
      <label className="field">
        <span>Username</span>
        <input pattern="[A-Za-z0-9_.]{3,30}" title="3–30 letters, numbers, dots or underscores" required value={username} onChange={(e) => setUsername(e.target.value)} />
      </label>
      {msg.error && <p className="error">{msg.error}</p>}
      {msg.ok && <p className="notice">{msg.ok}</p>}
      <button className="btn primary" disabled={username === (me.username || "")}>
        Save username
      </button>
    </form>
  );
}

function PasswordForm({ me, onUpdated }) {
  const empty = { current_password: "", password: "", confirm_password: "" };
  const [form, setForm] = useState(empty);
  const [msg, setMsg] = useState({});
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const mismatch = form.confirm_password && form.password !== form.confirm_password;
  const save = async (e) => {
    e.preventDefault();
    setMsg({});
    try {
      onUpdated(await api.post("/api/me/password", form));
      setForm(empty);
      setMsg({ ok: me.has_password ? "Password changed." : "Password set. You can now sign in with it too." });
    } catch (err) {
      setMsg({ error: err.message });
    }
  };
  return (
    <form className="settings-card" onSubmit={save}>
      <h2>{me.has_password ? "Change password" : "Set a password"}</h2>
      <p className="muted">
        {me.has_password
          ? "Use at least 8 characters, with a letter and a number."
          : "You sign in with Google. Set a password to also sign in with your email or username."}
      </p>
      {me.has_password && (
        <label className="field">
          <span>Current password</span>
          <input type="password" autoComplete="current-password" required value={form.current_password} onChange={set("current_password")} />
        </label>
      )}
      <label className="field">
        <span>New password</span>
        <input type="password" autoComplete="new-password" required minLength={8} value={form.password} onChange={set("password")} />
      </label>
      <label className="field">
        <span>Confirm new password</span>
        <input type="password" autoComplete="new-password" required value={form.confirm_password} onChange={set("confirm_password")} />
        {mismatch && <small className="muted">The passwords don't match.</small>}
      </label>
      {msg.error && <p className="error">{msg.error}</p>}
      {msg.ok && <p className="notice">{msg.ok}</p>}
      <button className="btn primary" disabled={mismatch}>
        {me.has_password ? "Change password" : "Set password"}
      </button>
    </form>
  );
}

export default function Settings({ me, onUpdated }) {
  return (
    <div className="page settings">
      <h1>Settings</h1>
      <div className="settings-card">
        <h2>Account</h2>
        <div className="info-row">
          <span>Name</span>
          <strong>{me.name}</strong>
        </div>
        <div className="info-row">
          <span>Email</span>
          <strong>{me.email}</strong>
        </div>
      </div>
      <UsernameForm me={me} onUpdated={onUpdated} />
      <PasswordForm me={me} onUpdated={onUpdated} />
    </div>
  );
}
