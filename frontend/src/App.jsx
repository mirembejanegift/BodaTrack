import { useEffect, useState } from "react";
import api from "./api.js";
import Login from "./pages/Login.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import AgreementDetail from "./pages/AgreementDetail.jsx";
import Agreements from "./pages/Agreements.jsx";

const NAV_ITEMS = [
  { key: "dashboard", label: "Dashboard" },
  { key: "agreements", label: "Agreements" },
];

export default function App() {
  const [user, setUser] = useState(undefined); // undefined = checking, null = logged out
  const [view, setView] = useState({ page: "dashboard" });

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
            <button
              key={item.key}
              className={`nav-item${view.page === item.key ? " active" : ""}`}
              onClick={() => setView({ page: item.key })}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="whoami">{user.full_name || user.username}</div>
          <button className="btn ghost small" onClick={handleLogout}>Log out</button>
        </div>
      </aside>
      <main className="content">
        {view.page === "dashboard" && <Dashboard onOpenAgreement={(id) => setView({ page: "agreement", id })} />}
        {view.page === "agreements" && <Agreements onOpenAgreement={(id) => setView({ page: "agreement", id })} />}
        {view.page === "agreement" && <AgreementDetail id={view.id} onBack={() => setView({ page: "agreements" })} />}
      </main>
    </div>
  );
}
