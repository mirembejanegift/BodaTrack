import { useEffect, useState } from "react";
import api from "../api.js";

export default function Motorcycles() {
  const [motorcycles, setMotorcycles] = useState(null);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showForm, setShowForm] = useState(false);

  function load(query = search) {
    api.get("/motorcycles/", query ? { search: query } : {})
      .then((data) => setMotorcycles(Array.isArray(data) ? data : data.results))
      .catch((err) => setError(err.message));
  }

  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, []);

  if (error) return <div className="alert error">{error}</div>;
  if (!motorcycles) return <div className="loading">Loading motorcycles…</div>;

  return (
    <>
      <div className="page-header">
        <h1>Motorcycles</h1>
        <button className="btn primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? "Close" : "New motorcycle"}
        </button>
      </div>

      {notice && <div className="alert success">{notice}</div>}
      {showForm && <NewMotorcycle onCreated={(m) => { setShowForm(false); setNotice(`Motorcycle ${m.registration_number} created.`); load(); }}
        onError={setError} />}

      <div className="toolbar">
        <input placeholder="Search plate or make…" value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") load(e.target.value); }} />
        <button className="btn" onClick={() => load()}>Search</button>
      </div>

      <table>
        <thead>
          <tr><th>Registration</th><th>Make / model</th><th>Active</th></tr>
        </thead>
        <tbody>
          {motorcycles.map((m) => (
            <tr key={m.id}>
              <td>{m.registration_number}</td>
              <td>{m.make_model || "—"}</td>
              <td>{m.is_active ? "✅" : "🚫"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function NewMotorcycle({ onCreated, onError }) {
  const [form, setForm] = useState({ registration_number: "", make_model: "" });
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    try {
      const motorcycle = await api.post("/motorcycles/", form);
      onCreated(motorcycle);
      setForm({ registration_number: "", make_model: "" });
    } catch (err) {
      onError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h2>New motorcycle</h2>
      <div className="form-grid">
        <label>Registration number
          <input value={form.registration_number}
            onChange={(e) => setForm({ ...form, registration_number: e.target.value })}
            placeholder="e.g. UFA 123A" required />
        </label>
        <label>Make / model
          <input value={form.make_model} onChange={(e) => setForm({ ...form, make_model: e.target.value })}
            placeholder="e.g. TVS HLX 125" />
        </label>
      </div>
      <button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Create motorcycle"}</button>
    </form>
  );
}
