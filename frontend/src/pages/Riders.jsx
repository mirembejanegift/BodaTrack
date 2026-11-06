import { useEffect, useState } from "react";
import api from "../api.js";

export default function Riders() {
  const [riders, setRiders] = useState(null);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showForm, setShowForm] = useState(false);

  function load(query = search) {
    api.get("/riders/", query ? { search: query } : {})
      .then((data) => setRiders(Array.isArray(data) ? data : data.results))
      .catch((err) => setError(err.message));
  }

  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, []);

  if (error) return <div className="alert error">{error}</div>;
  if (!riders) return <div className="loading">Loading riders…</div>;

  return (
    <>
      <div className="page-header">
        <h1>Riders</h1>
        <button className="btn primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? "Close" : "New rider"}
        </button>
      </div>

      {notice && <div className="alert success">{notice}</div>}
      {showForm && <NewRider onCreated={(rider) => { setShowForm(false); setNotice(`Rider ${rider.full_name} created.`); load(); }}
        onError={setError} />}

      <div className="toolbar">
        <input placeholder="Search name or phone…" value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") load(e.target.value); }} />
        <button className="btn" onClick={() => load()}>Search</button>
      </div>

      <table>
        <thead>
          <tr><th>Name</th><th>Phone</th><th>Active</th></tr>
        </thead>
        <tbody>
          {riders.map((rider) => (
            <tr key={rider.id}>
              <td>{rider.full_name}</td>
              <td>{rider.phone_number || "—"}</td>
              <td>{rider.is_active ? "✅" : "🚫"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function NewRider({ onCreated, onError }) {
  const [form, setForm] = useState({ full_name: "", phone_number: "" });
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    try {
      const rider = await api.post("/riders/", form);
      onCreated(rider);
      setForm({ full_name: "", phone_number: "" });
    } catch (err) {
      onError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h2>New rider</h2>
      <div className="form-grid">
        <label>Full name
          <input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required />
        </label>
        <label>Phone number
          <input value={form.phone_number} onChange={(e) => setForm({ ...form, phone_number: e.target.value })}
            placeholder="e.g. 0772 123 456" />
        </label>
      </div>
      <button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Create rider"}</button>
    </form>
  );
}
