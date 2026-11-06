import { useEffect, useState } from "react";
import api from "./api.js";
import Login from "./pages/Login.jsx";

const NAV_ITEMS = [];

export default function App() {
  const [user, setUser] = useState(undefined); // undefined = checking, null = logged out

  useEffect(() => {
    api.get("/auth/me/")
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  async function handleLogout() {
    await api.post("/auth/logout/");
    setUser(null);
  }

  if (user === undefined) {
    return <div className="loading-screen">Loading BodaTrack…</div>;
  }
  if (user === null) {
    return <Login onSuccess={setUser} />;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">🏍</span>
          <span className="brand-name">BodaTrack</span>
        </div>
        <nav>
          {NAV_ITEMS.map((item) => (
            <button key={item.key} className="nav-item">{item.label}</button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="whoami">{user.full_name || user.username}</div>
          <button className="btn ghost small" onClick={handleLogout}>Log out</button>
        </div>
      </aside>
      <main className="content">
        <h1>Welcome, {user.full_name || user.username} 👋</h1>
        <p className="muted">Bookkeeping pages arrive in the next commits.</p>
      </main>
    </div>
  );
}
