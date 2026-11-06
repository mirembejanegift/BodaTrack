import { useEffect, useState } from "react";
import api from "../api.js";
import { formatDateTime } from "../format.js";

export default function Audit() {
  const [entries, setEntries] = useState(null);
  const [actionFilter, setActionFilter] = useState("");
  const [error, setError] = useState("");

  function load(filter = actionFilter) {
    api.get("/audit/", filter ? { action: filter } : {})
      .then((data) => setEntries(Array.isArray(data) ? data : data.results))
      .catch((err) => setError(err.message));
  }

  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, []);

  if (error) return <div className="alert error">{error}</div>;
  if (!entries) return <div className="loading">Loading audit log…</div>;

  const actions = [...new Set(entries.map((e) => e.action))];

  return (
    <>
      <h1>Audit log</h1>
      <p className="muted">Every correction and approval is recorded here permanently.</p>

      <div className="toolbar">
        <label className="inline-label">Action
          <select value={actionFilter} onChange={(e) => { setActionFilter(e.target.value); load(e.target.value); }}>
            <option value="">All</option>
            {actions.map((action) => <option key={action} value={action}>{action.replace(/_/g, " ")}</option>)}
          </select>
        </label>
      </div>

      <table>
        <thead>
          <tr><th>When</th><th>Action</th><th>Entity</th><th>Actor</th><th>Details</th></tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.id}>
              <td>{formatDateTime(entry.created_at)}</td>
              <td><span className="badge active">{entry.action.replace(/_/g, " ")}</span></td>
              <td>{entry.entity_type} #{entry.entity_id}</td>
              <td>{entry.actor || "system"}</td>
              <td className="small muted">{JSON.stringify(entry.details)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
