/** Money helper: whole-UGX display. Backend values are strings to avoid
 * float precision loss; we parse into Number only for display. */
export function formatMoney(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (Number.isNaN(number)) return "—";
  return `UGX ${number.toLocaleString("en-UG", { maximumFractionDigits: 0 })}`;
}

export function formatDate(value) {
  if (!value) return "—";
  return String(value).slice(0, 10);
}

export function formatDateTime(value) {
  if (!value) return "—";
  return String(value).replace("T", " ").slice(0, 16);
}

export const AGREEMENT_STATUS_LABELS = {
  active: "Active",
  financially_completed: "Financially completed",
  cancelled: "Cancelled",
};

export const INSTALMENT_STATUS_LABELS = {
  scheduled: "Scheduled",
  partial: "Partially paid",
  paid: "Paid",
  overdue: "Overdue",
};

export const PAYMENT_METHOD_LABELS = {
  cash: "Cash",
  mobile_money: "Mobile Money",
};

export const PAYMENT_STATUS_LABELS = {
  posted: "Posted",
  reversed: "Reversed",
  voided: "Voided",
};
