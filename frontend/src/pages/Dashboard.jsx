import { useEffect, useState } from "react";
import api from "../api.js";
import { formatMoney, formatDateTime } from "../format.js";

export default function Dashboard({ onOpenAgreement }) {
  const [arrears, setArrears] = useState(null);
  const [collections, setCollections] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.get("/reports/arrears/"), api.get("/reports/collections/")])
      .then(([arrearsData, collectionsData]) => {
        setArrears(arrearsData);
        setCollections(collectionsData);
      })
      .catch((err) => setError(err.message));
  }, []);

  if (error) return <div className="alert error">{error}</div>;
  if (!arrears || !collections) return <div className="loading">Loading dashboard…</div>;

  const sorted = [...arrears.agreements].sort(
    (a, b) => Number(b.total_arrears) - Number(a.total_arrears),
  );

  return (
    <>
      <h1>Dashboard</h1>
      <p className="muted">
        Arrears as of {arrears.as_of} · collections {collections.from} → {collections.to}
      </p>

      <div className="cards">
        <div className="card">
          <div className="card-label">Total arrears (all bikes)</div>
          <div className="card-value danger">{formatMoney(arrears.total_arrears)}</div>
        </div>
        <div className="card">
          <div className="card-label">Collected this month</div>
          <div className="card-value success">{formatMoney(collections.grand_total)}</div>
          <div className="muted small">{collections.by_method.length} payment methods used</div>
        </div>
        <div className="card">
          <div className="card-label">Open agreements</div>
          <div className="card-value">{arrears.agreements.length}</div>
        </div>
      </div>

      <div className="cards">
        {collections.by_method.map((row) => (
          <div className="card" key={row.method}>
            <div className="card-label">
              {row.method === "cash" ? "Cash" : "Mobile Money"} · {row.count} payments
            </div>
            <div className="card-value">{formatMoney(row.total)}</div>
          </div>
        ))}
      </div>

      <h2>Arrears by agreement</h2>
      <table>
        <thead>
          <tr>
            <th>Rider</th>
            <th>Motorcycle</th>
            <th>Status</th>
            <th className="num">Arrears</th>
            <th className="num">Remaining balance</th>
            <th className="num">Overdue weeks</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={row.agreement_id} className="row-link" onClick={() => onOpenAgreement(row.agreement_id)}>
              <td>{row.rider}</td>
              <td>{row.motorcycle}</td>
              <td><span className={`badge ${row.status}`}>{row.status.replace("_", " ")}</span></td>
              <td className={`num ${Number(row.total_arrears) > 0 ? "danger" : "success"}`}>
                {formatMoney(row.total_arrears)}
              </td>
              <td className="num">{formatMoney(row.remaining_balance)}</td>
              <td className="num">{row.overdue_instalments}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
