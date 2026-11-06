import { useEffect, useState } from "react";
import api from "../api.js";
import {
  formatMoney, formatDate, formatDateTime,
  AGREEMENT_STATUS_LABELS, INSTALMENT_STATUS_LABELS,
  PAYMENT_METHOD_LABELS, PAYMENT_STATUS_LABELS,
} from "../format.js";

export default function AgreementDetail({ id, onBack }) {
  const [agreement, setAgreement] = useState(null);
  const [instalments, setInstalments] = useState([]);
  const [payments, setPayments] = useState([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function load() {
    Promise.all([
      api.get(`/agreements/${id}/`),
      api.get(`/agreements/${id}/instalments/`),
      api.get(`/agreements/${id}/payments/`),
    ])
      .then(([agreementData, instalmentData, paymentData]) => {
        setAgreement(agreementData);
        setInstalments(instalmentData);
        setPayments(paymentData);
      })
      .catch((err) => setError(err.message));
  }

  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [id]);

  if (error) return <div className="alert error">{error}</div>;
  if (!agreement) return <div className="loading">Loading agreement…</div>;

  return (
    <>
      <button className="btn ghost small" onClick={onBack}>← All agreements</button>
      <h1>
        {agreement.rider.full_name}
        <span className="muted"> · {agreement.motorcycle.registration_number}</span>
      </h1>
      <p className="muted">
        {formatMoney(agreement.total_price)} total · {formatMoney(agreement.weekly_amount)} weekly ·
        due every {WEEKDAYS[agreement.weekly_due_day]} · started {formatDate(agreement.start_date)} ·
        <span className={`badge ${agreement.status}`}>{AGREEMENT_STATUS_LABELS[agreement.status]}</span>
      </p>
      {notice && <div className="alert success">{notice}</div>}

      <div className="cards">
        <div className="card">
          <div className="card-label">Arrears (past-due weeks)</div>
          <div className={`card-value ${Number(agreement.total_arrears) > 0 ? "danger" : "success"}`}>
            {formatMoney(agreement.total_arrears)}
          </div>
        </div>
        <div className="card">
          <div className="card-label">Remaining ownership balance</div>
          <div className="card-value">{formatMoney(agreement.remaining_balance)}</div>
        </div>
        <div className="card">
          <div className="card-label">Next due date</div>
          <div className="card-value">{agreement.next_due_date ? formatDate(agreement.next_due_date) : "—"}</div>
        </div>
        <div className="card">
          <div className="card-label">Legal transfer</div>
          <div className="card-value small">
            {agreement.legal_transfer_approved_at
              ? `Approved ${formatDate(agreement.legal_transfer_approved_at)}`
              : "Not approved"}
          </div>
        </div>
      </div>

      <RecordPayment agreement={agreement} onDone={(message) => { setNotice(message); setError(""); load(); }}
        onApiError={setError} />

      <h2>Payment history</h2>
      <table>
        <thead>
          <tr>
            <th>Receipt #</th>
            <th>Method</th>
            <th>Reference</th>
            <th className="num">Amount</th>
            <th>Paid at</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {payments.length === 0 && (
            <tr><td colSpan="7" className="muted">No payments recorded yet.</td></tr>
          )}
          {payments.map((payment) => (
            <tr key={payment.id} className={payment.status === "reversed" ? "dimmed" : ""}>
              <td>{payment.receipt_number}</td>
              <td>{PAYMENT_METHOD_LABELS[payment.method]}</td>
              <td>{payment.reference || "—"}</td>
              <td className="num">{formatMoney(payment.amount)}</td>
              <td>{formatDateTime(payment.paid_at)}</td>
              <td><span className={`badge ${payment.status}`}>{PAYMENT_STATUS_LABELS[payment.status]}</span></td>
              <td>
                {payment.status === "posted" && (
                  <ReverseButton payment={payment}
                    onDone={(message) => { setNotice(message); load(); }}
                    onApiError={setError} />
                )}
                {payment.status === "reversed" && (
                  <span className="muted small" title={payment.reversal_reason}>
                    Reason: {payment.reversal_reason}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Weekly instalment schedule</h2>
      <table>
        <thead>
          <tr>
            <th>Week #</th>
            <th>Due date</th>
            <th className="num">Due</th>
            <th className="num">Paid</th>
            <th className="num">Outstanding</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {instalments.map((instalment, index) => (
            <tr key={instalment.id}>
              <td>{index + 1}</td>
              <td>{formatDate(instalment.due_date)}</td>
              <td className="num">{formatMoney(instalment.amount_due)}</td>
              <td className="num success">{formatMoney(instalment.amount_paid)}</td>
              <td className="num">
                <span className={Number(instalment.outstanding_amount) > 0 ? "danger" : ""}>
                  {formatMoney(instalment.outstanding_amount)}
                </span>
              </td>
              <td><span className={`badge ${instalment.status}`}>{INSTALMENT_STATUS_LABELS[instalment.status]}</span></td>
            </tr>
          ))}
        </tbody>
      </table>

      {Number(agreement.remaining_balance) === 0 &&
        agreement.status === "financially_completed" &&
        !agreement.legal_transfer_approved_at && (
        <LegalTransfer agreement={agreement}
          onDone={(message) => { setNotice(message); load(); }}
          onApiError={setError} />
      )}

      {agreement.status === "active" && (
        <CancelAgreement agreement={agreement} onDone={(message) => { setNotice(message); load(); }}
          onApiError={setError} />
      )}
    </>
  );
}

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function RecordPayment({ agreement, onDone, onApiError }) {
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({ amount: "", receipt_number: "", method: "cash", reference: "", paid_date: today });
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  function set(field, value) { setForm((f) => ({ ...f, [field]: value })); }

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setFormError("");
    try {
      const payment = await api.post(`/agreements/${agreement.id}/payments/`, {
        amount: form.amount,
        receipt_number: form.receipt_number,
        method: form.method,
        reference: form.reference,
        paid_at: `${form.paid_date}T12:00:00`,
      });
      onDone(`Payment ${payment.receipt_number} recorded.`);
      setForm({ amount: "", receipt_number: "", method: form.method, reference: "", paid_date: today });
    } catch (err) {
      setFormError(err.message); onApiError("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h2>Record a payment</h2>
      <div className="form-grid">
        <label>Amount (UGX)
          <input type="number" min="1" value={form.amount} onChange={(e) => set("amount", e.target.value)} required />
        </label>
        <label>Receipt number
          <input value={form.receipt_number} onChange={(e) => set("receipt_number", e.target.value)}
            placeholder="e.g. RB-0123" required />
        </label>
        <label>Method
          <select value={form.method} onChange={(e) => set("method", e.target.value)}>
            <option value="cash">Cash</option>
            <option value="mobile_money">Mobile Money</option>
          </select>
        </label>
        {form.method === "mobile_money" ? (
          <label>Mobile Money reference
            <input value={form.reference} onChange={(e) => set("reference", e.target.value)}
              placeholder="e.g. MP24012345" required />
          </label>
        ) : (
          <label>Reference (optional)
            <input value={form.reference} onChange={(e) => set("reference", e.target.value)} />
          </label>
        )}
        <label>Payment date
          <input type="date" value={form.paid_date} onChange={(e) => set("paid_date", e.target.value)} required />
        </label>
      </div>
      {formError && <div className="alert error">{formError}</div>}
      <button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Record payment"}</button>
      <p className="muted small">
        The oldest unpaid week is paid first automatically. Receipt numbers must be unique.
      </p>
    </form>
  );
}

function ReverseButton({ payment, onDone, onApiError }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.post(`/payments/${payment.id}/reverse/`, { reason });
      setOpen(false);
      onDone(`Payment ${payment.receipt_number} reversed; arrears restored.`);
    } catch (err) {
      setError(err.message); onApiError("");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return <button className="btn danger small" onClick={() => setOpen(true)}>Reverse</button>;
  }
  return (
    <form className="inline-form" onSubmit={submit}>
      <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why is this being reversed?" required minLength={5} autoFocus />
      <button className="btn danger small" disabled={busy}>{busy ? "…" : "Confirm"}</button>
      <button type="button" className="btn ghost small" onClick={() => setOpen(false)}>Cancel</button>
      {error && <div className="alert error">{error}</div>}
    </form>
  );
}

function LegalTransfer({ agreement, onDone, onApiError }) {
  const [busy, setBusy] = useState(false);

  async function approve() {
    if (!window.confirm("Approve the legal transfer of this motorcycle to the rider?")) return;
    setBusy(true);
    try {
      await api.post(`/agreements/${agreement.id}/transfer-approval/`, {});
      onDone("Legal transfer approved and logged in the audit trail.");
    } catch (err) {
      onApiError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel highlight">
      <h2>Ownership transfer</h2>
      <p className="muted">
        The balance is fully paid. Approving records the approver and date in the audit log —
        it is a separate legal step from paying off the bike.
      </p>
      <button className="btn primary" onClick={approve} disabled={busy}>
        {busy ? "Approving…" : "Approve legal transfer of ownership"}
      </button>
    </div>
  );
}

function CancelAgreement({ agreement, onDone, onApiError }) {
  async function cancel() {
    if (!window.confirm("Cancel this agreement? Payments will be blocked but history is kept.")) return;
    try {
      await api.post(`/agreements/${agreement.id}/cancel/`);
      onDone("Agreement cancelled.");
    } catch (err) {
      onApiError(err.message);
    }
  }
  return <button className="btn ghost" onClick={cancel}>Cancel agreement</button>;
}
