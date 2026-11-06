import { useEffect, useState } from "react";
import api from "../api.js";
import { formatMoney, formatDate, AGREEMENT_STATUS_LABELS } from "../format.js";

export default function Agreements({ onOpenAgreement }) {
  const [agreements, setAgreements] = useState(null);
  const [riders, setRiders] = useState([]);
  const [motorcycles, setMotorcycles] = useState([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");

  function load() {
    api.get("/agreements/", { status: statusFilter || undefined })
      .then(setAgreements)
      .catch((err) => setError(err.message));
  }

  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [statusFilter]);
  useEffect(() => {
    api.get("/riders/", { }).then((data) => setRiders(Array.isArray(data) ? data : data.results)).catch(() => {});
    api.get("/motorcycles/").then((data) => setMotorcycles(Array.isArray(data) ? data : data.results)).catch(() => {});
  }, []);

  if (error) return <div className="alert error">{error}</div>;
  if (!agreements) return <div className="loading">Loading agreements…</div>;

  return (
    <>
      <div className="page-header">
        <h1>Ownership agreements</h1>
        <button className="btn primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? "Close" : "New agreement"}
        </button>
      </div>

      {showForm && <NewAgreementForm riders={riders} motorcycles={motorcycles}
        onCreated={(agreement) => { setShowForm(false); onOpenAgreement(agreement.id); }}
        onError={setError} />}

      <div className="toolbar">
        <label className="inline-label">Status
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All</option>
            <option value="active">Active</option>
            <option value="financially_completed">Financially completed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </label>
      </div>

      <table>
        <thead>
          <tr>
            <th>Rider</th>
            <th>Motorcycle</th>
            <th className="num">Total price</th>
            <th className="num">Weekly</th>
            <th>Started</th>
            <th>Status</th>
            <th className="num">Arrears</th>
            <th className="num">Remaining</th>
          </tr>
        </thead>
        <tbody>
          {agreements.map((agreement) => (
            <tr key={agreement.id} className="row-link" onClick={() => onOpenAgreement(agreement.id)}>
              <td>{agreement.rider.full_name}</td>
              <td>{agreement.motorcycle.registration_number}</td>
              <td className="num">{formatMoney(agreement.total_price)}</td>
              <td className="num">{formatMoney(agreement.weekly_amount)}</td>
              <td>{formatDate(agreement.start_date)}</td>
              <td><span className={`badge ${agreement.status}`}>{AGREEMENT_STATUS_LABELS[agreement.status]}</span></td>
              <td className={`num ${Number(agreement.total_arrears) > 0 ? "danger" : "success"}`}>
                {formatMoney(agreement.total_arrears)}
              </td>
              <td className="num">{formatMoney(agreement.remaining_balance)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function NewAgreementForm({ riders, motorcycles, onCreated, onError }) {
  const [form, setForm] = useState({
    rider_id: "", motorcycle_id: "", total_price: "", weekly_amount: "",
    start_date: new Date().toISOString().slice(0, 10), weekly_due_day: 0,
  });
  const [busy, setBusy] = useState(false);

  function set(field, value) { setForm((f) => ({ ...f, [field]: value })); }

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    try {
      const agreement = await api.post("/agreements/", form);
      onCreated(agreement);
    } catch (err) {
      onError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h2>New ownership agreement</h2>
      <div className="form-grid">
        <label>Rider
          <select value={form.rider_id} onChange={(e) => set("rider_id", e.target.value)} required>
            <option value="">Choose rider…</option>
            {[...riders].sort((a, b) => a.full_name.localeCompare(b.full_name)).map((r) => (
              <option key={r.id} value={r.id}>{r.full_name}</option>
            ))}
          </select>
        </label>
        <label>Motorcycle
          <select value={form.motorcycle_id} onChange={(e) => set("motorcycle_id", e.target.value)} required>
            <option value="">Choose motorcycle…</option>
            {motorcycles.map((m) => (
              <option key={m.id} value={m.id}>{m.registration_number} {m.make_model ? `· ${m.make_model}` : ""}</option>
            ))}
          </select>
        </label>
        <label>Total price (UGX)
          <input type="number" min="1" value={form.total_price}
            onChange={(e) => set("total_price", e.target.value)} required />
        </label>
        <label>Weekly instalment (UGX)
          <input type="number" min="1" value={form.weekly_amount}
            onChange={(e) => set("weekly_amount", e.target.value)} required />
        </label>
        <label>Start date
          <input type="date" value={form.start_date}
            onChange={(e) => set("start_date", e.target.value)} required />
        </label>
        <label>Weekly due day
          <select value={form.weekly_due_day} onChange={(e) => set("weekly_due_day", e.target.value)}>
            <option value="0">Monday</option>
            <option value="1">Tuesday</option>
            <option value="2">Wednesday</option>
            <option value="3">Thursday</option>
            <option value="4">Friday</option>
            <option value="5">Saturday</option>
            <option value="6">Sunday</option>
          </select>
        </label>
      </div>
      <button className="btn primary" disabled={busy}>{busy ? "Creating…" : "Create agreement"}</button>
    </form>
  );
}
