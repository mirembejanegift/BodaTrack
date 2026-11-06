import { useState } from "react";
import api from "../api.js";

export default function Login({ onSuccess }) {
  const [mode, setMode] = useState("login"); // "login" | "register"
  const [form, setForm] = useState({ username: "", password: "", full_name: "" });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  function set(field, value) { setForm((f) => ({ ...f, [field]: value })); }

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const user = mode === "login"
        ? await api.post("/auth/login/", { username: form.username, password: form.password })
        : await api.post("/auth/register/", {
            username: form.username, password: form.password, full_name: form.full_name,
          });
      onSuccess(user);
    } catch (err) {
      if (mode === "register") {
        setNotice("Registration failed — if the username exists, switch to 'Sign in'.");
      }
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const registering = mode === "register";

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <h1>🏍 BodaTrack</h1>
        <p className="muted">Boda boda ownership instalments</p>

        {registering && (
          <>
            <label>
              Your full name
              <input value={form.full_name} onChange={(e) => set("full_name", e.target.value)}
                placeholder="Used in the audit log" />
            </label>
          </>
        )}
        <label>
          Username
          <input value={form.username} onChange={(e) => set("username", e.target.value)} autoFocus required
            minLength={3} />
        </label>
        <label>
          {registering ? "Choose a password (at least 8 characters)" : "Password"}
          <input type="password" value={form.password} onChange={(e) => set("password", e.target.value)}
            required minLength={registering ? 8 : 1} />
        </label>

        {error && <div className="alert error">{error}</div>}
        {notice && <div className="alert success">{notice}</div>}

        <button className="btn primary block" disabled={busy}>
          {busy ? (registering ? "Creating account…" : "Signing in…")
                : (registering ? "Create my account" : "Sign in")}
        </button>

        <button
          type="button"
          className="btn ghost small block"
          onClick={() => { setMode(registering ? "login" : "register"); setError(""); setNotice(""); }}
        >
          {registering ? "← Back to sign in" : "New here? Create an account"}
        </button>
        {registering && (
          <p className="muted small">
            Accounts created here can join the shop team. An existing admin can
            always remove access from Django admin afterwards.
          </p>
        )}
      </form>
    </div>
  );
}
