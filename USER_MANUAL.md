# BodaTrack User Manual

A plain-language guide to running a boda boda ownership-instalment business
with BodaTrack. No technical background needed.

---

## 1. What BodaTrack does

- Records every payment a rider makes (cash or Mobile Money) against the
  motorcycle they are buying from you.
- Keeps a weekly schedule of what the rider owes and works out two separate
  figures at any moment:
  - **Arrears** — instalments whose due date has passed and were not fully paid.
    *The answer to "how far behind is this rider this week?"*
  - **Remaining ownership balance** — the bike price minus every valid payment.
    *The answer to "how much is left before the rider owns the bike?"*
- **Important rule:** paying off the bike does **not** automatically transfer
  ownership. Real ownership transfer is a separate approval you make explicitly
  (see section 6), and it is recorded with your name and the date.
- Sends **thank-you SMS** to riders after each payment and can send **payment
  reminder SMS** to riders behind on their instalments.
- Keeps a permanent **audit log** of every change, correction and approval —
  payments are never deleted; mistakes are *reversed* with a reason.

---

## 2. Starting the system each day

Open two terminals (PowerShell) and keep them running while you work:

**Terminal 1 — the server:**
```powershell
cd C:\Users\mirem\OneDrive\Desktop\BodaTracker\BodaTrack
python manage.py runserver
```

**Terminal 2 — the website:**
```powershell
cd C:\Users\mirem\OneDrive\Desktop\BodaTracker\BodaTrack\frontend
npm run dev
```

Then open **http://localhost:5173** in your browser.

If the website says "refused to connect", one of the two terminals is not
running — start both.

---

## 3. Signing in and creating accounts

**Sign in** with your username and password.

**A new staff member can create their own account:**
1. On the login screen, click **"New here? Create an account"**.
2. Enter their full name, a username and a password (at least 8 characters,
   not a common word).
3. Click **Create my account** — they are signed in immediately and can work.

**Removing someone's access later:** open
`http://127.0.0.1:8000/admin/` → **Users** → untick **Staff status** for that
person's account (or delete inactive users). All their past audit entries remain.

---

## 4. Everyday work — recording a payment

When a rider pays (cash or Mobile Money):

1. Open the **Agreements** page and click the rider/bike row.
2. In **"Record a payment"** fill in:
   - **Amount** — exactly what the rider paid today.
   - **Receipt number** — write the same receipt number you give the rider
     on the paper receipt. Every receipt number can be used **only once**;
     the system will refuse and warn you about duplicates.
   - **Method** — Cash or Mobile Money.
   - **Mobile Money reference** — for Mobile Money payments you MUST copy the
     transaction ID from your phone (e.g. `MP240402.1629.C12345`). Cash
     payments leave it empty.
   - **Payment date** — the actual day the money was handed over. If you report
     a payment one or two days late, use the original payment date.
3. Click **Record payment**.
4. A green message confirms it. The system automatically:
   - clears the **oldest unpaid week first** (so partial payments are fair),
   - updates arrears and the remaining balance immediately,
   - queues a **thank-you SMS** for the rider (see section 7).

Multiple payments in one week are normal — enter each one as a separate
payment. A payment that is less than the week's instalment is fine; the week
shows as *Partially paid* and the rest stays as arrears.

---

## 5. Correcting a mistake — reversing a payment

If a payment was entered twice, or with the wrong amount:

1. Open the agreement's **Payment history**.
2. On the wrong row click **Reverse**.
3. Type **why** you are reversing it (minimum 5 characters, e.g.
   "Double entry of receipt RB-0123").
4. Confirm.

Nothing is deleted: the receipt stays on file marked **Reversed**, arrears and
the balance are restored automatically, and the record of who reversed it and
why is kept forever in the **Audit log**. If you don't know why you're
reversing, it isn't a legal reversal — investigate first.

---

## 6. Finishing a loan — ownership transfer

When a rider pays their **last** instalment:

1. The agreement status changes to **Financially completed** and its
   remaining balance reads 0.00. **This alone does not transfer ownership.**
2. On the agreement page a panel appears:
   **"Approve legal transfer of ownership"**.
3. Read it, confirm, and the approval records **your name and today's date**
   in the audit log. Only then has ownership legally passed to the rider.

Did the complete paperwork (logbook transfer) separately, as required by law —
BodaTrack records the approval but does not replace any legal process.

Cancelling an agreement (e.g. a rider quits) is possible via the agreement
page; the payment history is kept but new payments are blocked.

---

## 7. SMS messages (thank-you and reminders)

**Thank-you SMS** (reason: "receipt") are queued automatically every time you
record a payment — nothing for you to click.

**Payment reminder SMS** (reason: "reminder"): run this command once a day,
for example every morning:

```powershell
cd C:\Users\mirem\OneDrive\Desktop\BodaTracker\BodaTrack
python manage.py send_sms --reminders
```

It:
- queues one reminder per rider with arrears (and only one per day per rider,
  even if you run it twice),
- sends all queued messages (receipts + reminders) through the SMS gateway,
- tells you how many were sent and how many failed.

**Connecting a real SMS gateway (Africas Talking / MTN):**
1. Open `BodaTrack\.env` and set:
   ```
   SMS_BACKEND=africastalking
   AFRICAS_TALKING_USERNAME=your-username
   AFRICAS_TALKING_API_KEY=your-api-key
   AFRICAS_TALKING_SENDER_ID=your-sender-name
   ```
2. Restart the server terminal.
3. Run `python manage.py send_sms` as often as you like; it only costs for
   messages actually sent.

**Riders without a phone number** get their reminder marked **Failed** with
"no phone number on record" — add their number on the **Riders** page and the
next run will reach them.

**Checking what was sent:** open `http://127.0.0.1:8000/admin/` → **tracker →
Sms logs** — every message, its text, status and any error.

**Automation (optional):** you can schedule `python manage.py send_sms --reminders`
daily at e.g. 09:00 with **Task Scheduler** (Action → Start a program →
`python`; Arguments → `manage.py send_sms --reminders`; Start in → the
BodaTrack folder).

---

## 8. Reports

- **Dashboard** — total arrears, collections this month split into cash vs
  Mobile Money, and a per-agreement arrears table. Riders with the biggest
  arrears appear first — call them first.
- **Collect report** (`/api/reports/collections/`) — cash and Mobile Money
  received for any date range (useful for reconciling with MTN statements).
- **Audit log** — the permanent record: who recorded, reversed, cancelled and
  approved what, and when.

---

## 9. Moving from demo data to YOUR real data

Current system contains clearly marked demo data (fake names like "Amina
Namusoke"). To switch:

1. Stop both terminals (Ctrl+C in each).
2. Delete the database and recreate it (this deletes ONLY local demo data):
   ```powershell
   $env:PGPASSWORD="mirembe123"; & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -c "DROP DATABASE IF EXISTS bodatrack;"
   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -c "CREATE DATABASE bodatrack;"
   python manage.py migrate
   python manage.py changepassword admin    # choose the real password
   ```
3. Restart both terminals and enter your real data:
   - **Riders** page → add each rider (with a phone number — needed for SMS).
   - **Motorcycles** page → add each bike with its real registration plate.
   - **Agreements** page → for each bike on hire-purchase, create an agreement
     with the real total price, weekly amount, and the original start date.
4. If riders have already paid weeks before you start recording: enter those
   past payments into the agreement's payment list **with the real payment
   dates** (start of each week is fine), method and receipt references. Give
   them a "legacy-01", "legacy-02"… style receipt number if none exists on
   the paper. The system will then compute today's true arrears and balances.

---

## 10. Backing up your data (do this!)

Your whole business record is in PostgreSQL. Weekly backup:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -U postgres -h localhost --no-password --format custom --file "BodaTrack-backup-$(Get-Date -Format yyyy-MM-dd).db" bodatrack
```

(Enter the database password when asked.) Save the `.db` file on a separate
USB stick or upload it somewhere safe. To restore a backup you would run
`psql -U postgres -c "CREATE DATABASE bodatrack2;"` and then
`pg_restore -U postgres -d bodatrack2 BodaTrack-backup-2026-11-06.db`.

---

## 11. When something looks wrong

| Symptom | Where to check |
|---|---|
| "localhost refused to connect" | Start the two terminals in section 2. |
| Login rejected | Check username/password; users created by other staff can be inspected in Django admin. |
| "This receipt number has already been used" | It's working as designed — check today's entries or use the next receipt in the book. |
| "Amount exceeds the remaining ownership balance" | The bike's balance is smaller than the amount — confirm which payment is being recorded. |
| Rider's SMS shows Failed | Their phone number is missing or wrong — fix it on the Riders page. |
| Numbers look wrong after a correction | Open the **Audit log** to see exactly what changed; arrears and balance always recompute automatically. |

---

## 12. The golden rules (for every staff member)

1. Every payment gets a unique receipt number — no exceptions.
2. Mobile Money payments must include the transaction reference.
3. Never use the "record" form to fix a mistake — record payments, reverse
   mistaken ones, and write the honest reason.
4. To give a rider their bike, the balance must be zero AND an owner must
   approve the transfer explicitly.
5. The system's word is final on money: it calculates arrears and balances
   server-side; screens only display what the database says.
