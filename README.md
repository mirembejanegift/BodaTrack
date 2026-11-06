# BodaTrack

A web application for managing boda boda motorcycle ownership instalments.
Riders make weekly payments (cash or Mobile Money) towards owning the bike;
BodaTrack tracks every receipt, computes arrears, and keeps an audit trail of
all corrections.

## Stack

- **Backend**: Python · Django · Django REST Framework · PostgreSQL
- **Frontend**: React · Vite · plain CSS
- **Secrets/config**: environment variables (`.env`)

## How money is modelled (read this first)

- **Arrears** = unpaid portions of instalments whose due date has passed.
  Answers "how far behind is this rider?".
- **Remaining ownership balance** = total price − all valid payments.
  Answers "how much is left to own the bike?". It is computed from payment
  totals, so allocation quirks can never distort it.
- **⚠️ A zero balance does NOT transfer ownership.** Paying off the bike only
  sets the agreement status to "financially completed". Legal ownership
  transfer is a separate, explicit staff approval that records who approved it
  and when, in the audit log.
- Payments are **never deleted**. A wrong entry is *reversed* with a mandatory
  reason; the receipt stays on file and the outage is written to the audit log.
  After a reversal, arrears and balances are automatically recomputed.
- A payment always clears the **oldest unpaid week first** (FIFO). Multiple
  payments per week are fine; overpayments roll forward automatically.

## Running

### 1. Backend

```powershell
cd BodaTrack
# create .env from .env.example and fill in DB + secret values
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# set up the database (PostgreSQL must be reachable per .env)
python manage.py migrate

# create demo riders, bikes, agreements and payments (dev only)
python manage.py seed_demo --username admin --password <a-strong-password>

python manage.py runserver
```

The API is served at `http://127.0.0.1:8000/api/` and Django admin at
`http://127.0.0.1:8000/admin/`.

### 2. Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` and sign in with the staff user created above.
The Vite dev server proxies `/api` to Django, so cookies and CSRF work without
extra configuration.

## Tests

```powershell
# quick run without PostgreSQL (SQLite fallback, dev only)
$env:DJANGO_TEST_SQLITE = "true"; python manage.py test tracker

# against the real configured database (recommended in CI)
python manage.py test tracker
```

The suite covers: instalment schedule generation, FIFO allocation, partial
payments, missed weeks, overpayment rolling forward, reversal restoring
arrears, duplicate receipt rejection, Mobile Money reference enforcement,
payment limits vs. remaining balance, agreement term locking, the arrears vs.
remaining-balance distinction, and the legal-transfer approval gate.

## API overview

Endpoints live under `/api/` and require staff login (session + CSRF):

| Area | Endpoints |
|---|---|
| Riders | `GET/POST/PATCH /api/riders/` (+ search) |
| Motorcycles | `GET/POST/PATCH /api/motorcycles/` (+ search) |
| Agreements | `GET/POST/PATCH /api/agreements/` · `/api/agreements/{id}/instalments/` · `/cancel/` |
| Payments | `GET/POST /api/agreements/{id}/payments/` · `GET /api/payments/` · `POST /api/payments/{id}/reverse/` |
| Ownership transfer | `POST /api/agreements/{id}/transfer-approval/` (zero balance required) |
| Reports | `GET /api/reports/arrears/` · `GET /api/reports/collections/?from=YYYY-MM-DD&to=…` |
| Audit | `GET /api/audit/` (filter by `action`, `entity_type`, `entity_id`) |
| Auth | `GET /api/auth/csrf/` · `POST /api/auth/login/` · `POST /api/auth/logout/` · `GET /api/auth/me/` |

## Security notes for production

- Set real values in `.env`: long random `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=false`,
  correct `DJANGO_ALLOWED_HOSTS` and CSRF/CORS origins, PostgreSQL credentials.
- All money computation is server-side; the frontend only ever displays results.
- Business endpoints require staff sessions; the Django admin blocks payment
  edits and deletes — corrections must go through the reversal endpoint.
- Append-only `AuditLog` records every payment, reversal, cancellation and
  transfer approval.

## Project layout

```
BodaTrack/
├── bodatrack/          # project config (settings, urls, wsgi/asgi)
├── tracker/            # the business app
│   ├── models.py       # Rider, Motorcycle, OwnershipAgreement, WeeklyInstalment,
│   │                   # Payment, PaymentAllocation, AuditLog
│   ├── services.py     # money rules (schedule, FIFO, reversal, transfer gate)
│   ├── serializers.py  # DRF request/response shapes
│   ├── views.py        # API endpoints
│   ├── urls.py, admin.py, migrations/
│   └── management/commands/seed_demo.py
├── frontend/           # React + Vite app
│   └── src/            # pages: Dashboard, Agreements, AgreementDetail,
│                       # Riders, Motorcycles, Audit (+ Login)
├── requirements.txt
└── .env.example
```
