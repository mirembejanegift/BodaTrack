"""Import BodaTrack's original Excel payment tracker.

Each sheet represents one rider's schedule:
  row1: "<NAME>'S PAYMENT SCHEDULE"   (may be missing on some sheets)
  row2: "104 WEEKS-90,000 WEEKLY..."  => total price = weeks x weekly
  row3: phone number(s)               => first number becomes rider phone
  row4: No. | DATE | INSTALLMENT | AMOUNT PAID | ARREARS | COMMENT
  rows5+: "Initial deposit" payment and numbered weekly payments.

Usage:
  python manage.py import_excel --file "path\\to.xlsx" [--dry-run]
"""
import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tracker.models import AuditLog, Motorcycle, OwnershipAgreement, Payment, Rider
from tracker.services import generate_instalments, record_payment

DEFAULT_FILE = r"C:\Users\mirem\Downloads\Boda Payment Tracker for all.xlsx"

WEEKS_RE = re.compile(r"(\d+)\s*WEEKS\D*(\d[\d,]*)", re.IGNORECASE)
NAME_RE = re.compile(r"(\S+)'S PAYMENT", re.IGNORECASE)
PHONE_RE = re.compile(r"^(?:256)?7\d{8}$")
MOBILE_HINT_RE = re.compile(r"\b(mtn|airtel|mo(mo)?\b|mobile)", re.IGNORECASE)
DATE_RE = re.compile(r"\d{2}[./]\d{2}[./]\d{4}")


def parse_weeks_line(text):
    match = WEEKS_RE.search(str(text))
    if not match:
        return None
    weeks = int(match.group(1))
    weekly = Decimal(match.group(2).replace(",", ""))
    return weeks, weekly


def parse_phones(raw):
    """All 9-digit Ugandan mobile numbers, normalised to +256XXXXXXXXX."""
    found = []
    for part in re.split(r"[/,\n]", str(raw)):
        digits = re.sub(r"\D", "", part)
        for candidate in [digits[-9:], digits]:
            if PHONE_RE.match(candidate):
                found.append("+256" + candidate)
                break
    return list(dict.fromkeys(found))


def parse_date(value):
    text = str(value or "").strip()
    match = DATE_RE.search(text)
    if not match:
        return None
    for fmt in ("%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(match.group(0).replace("/", "."), fmt).date()
        except ValueError:
            continue
    return None


def as_money(value):
    if value in (None, "", " "):
        return None
    try:
        return Decimal(str(value).replace(",", "") or "0")
    except InvalidOperation:
        return None


def extract_sheet_rows(ws):
    """Returns (rider_name, phones, weeks, weekly, deposits, dated, extras,
    week_dates, footer_total)."""
    all_rows = list(ws.iter_rows(values_only=True))
    # Locate the header row ("No. | DATE | ...") so title-less sheets with an
    # early "Initial deposit" row are not skipped.
    header_idx = next((i for i, row in enumerate(all_rows)
                       if str(row[0] or "").strip().lower().startswith("no.")), 3)
    rows = all_rows[header_idx + 1:]
    max_idx = len(all_rows)
    rider_name, phones, weeks, weekly = None, [], None, None

    for row in all_rows[:header_idx]:
        joined = " ".join(str(c) for c in row if c is not None).strip()
        if not joined:
            continue
        if weeks is None:
            parsed = parse_weeks_line(joined)
            if parsed:
                weeks, weekly = parsed
                continue
        if not phones:
            if "WEEK" in joined.upper() and "'" in joined and NAME_RE.search(joined):
                rider_name = NAME_RE.search(joined).group(1).title()
                continue
            if PHONE_RE.match(re.sub(r"\D", "", joined)[-9:]) or "/" in joined:
                phones = parse_phones(joined)
                continue
        if "PAYMENT" in joined.upper() and "'" in joined:
            match = NAME_RE.search(joined)
            if match:
                rider_name = match.group(1).title()

    if rider_name is None:
        rider_name = ws.title.replace("PT-", "").replace("-", " ").title().strip()
    if weeks is None or weekly is None:
        raise CommandError(f"Sheet '{ws.title}': could not read the weeks/weekly line.")

    deposits, dated, extras, week_dates, footer_total = [], [], [], [], None
    for offset, row in enumerate(rows):
        row_index = offset + 5  # 1-based, for reporting
        cells = ["" if c is None else str(c).strip() for c in row[:6]]
        no_cell, date_cell, instal_cell, paid_cell = cells[0], cells[1], cells[2], cells[3]
        comment = cells[5]
        paid = as_money(paid_cell)
        if paid is None or paid <= 0:
            continue  # missed week, footer or empty row

        is_deposit = "deposit" in date_cell.lower()
        paid_date = parse_date(date_cell)
        footer_row = offset >= len(rows) - 4

        if is_deposit:
            deposits.append({"amount": paid, "comment": comment, "row": row_index})
            continue
        if paid_date:
            dated.append({"date": paid_date, "amount": paid, "comment": comment,
                          "row": row_index})
            week_dates.append(paid_date)
        elif "total" in (no_cell.lower() + date_cell.lower()) or footer_row:
            if footer_total is None or paid > footer_total:
                footer_total = paid  # grand-total row: used for parity verification
        elif no_cell and not no_cell.replace(".", "").isdigit():
            continue  # labels with no digits
        else:
            extras.append({"amount": paid, "comment": comment, "row": row_index})

    week_dates.sort()
    return rider_name, phones, weeks, weekly, deposits, dated, extras, week_dates, footer_total


class Command(BaseCommand):
    help = "Import the original Excel payment tracker into BodaTrack."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=DEFAULT_FILE)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--operator", default="admin",
                            help="Existing staff username recorded as the importer.")

    def handle(self, *args, **options):
        import openpyxl

        wb = openpyxl.load_workbook(options["file"], data_only=True)
        User = get_user_model()
        operator = User.objects.filter(username=options["operator"]).first()
        dry = options["dry_run"]

        plan = []
        for ws in wb.worksheets:
            try:
                plan.append((ws.title, extract_sheet_rows(ws)))
            except CommandError as exc:
                self.stderr.write(str(exc))
                continue

        for sheet, (rider_name, phones, weeks, weekly, deposits, dated, extras,
                    week_dates, footer_total) in plan:
            total_price = Decimal(weeks) * weekly
            imported_total = sum(
                (item["amount"] for item in deposits + dated + extras), Decimal("0")
            )
            parity = ""
            if footer_total is not None:
                sheet_paid = imported_total - sum((d["amount"] for d in deposits), Decimal("0"))
                parity = ("MATCH" if footer_total == sheet_paid
                          else f"MISMATCH! footer={footer_total} import={sheet_paid}")
            self.stdout.write(
                f"Sheet: {rider_name} | phone: {phones[0] if phones else 'MISSING'} | "
                f"{weeks} weeks x {weekly} = {total_price} | "
                f"deposits {len(deposits)} + weeks {len(dated)} + extras {len(extras)}"
                f" = {imported_total} | total-row {parity}"
            )

        if dry:
            self.stdout.write(self.style.WARNING("Dry run only - nothing was imported."))
            return

        created = {"riders": 0, "agreements": 0, "payments": 0}
        serial = iter(f"TBC-{n:03d}" for n in range(1, 200))
        with transaction.atomic():
            for sheet, (rider_name, phones, weeks, weekly, deposits, dated, extras,
                        week_dates, footer_total) in plan:
                rider, created_rider = Rider.objects.get_or_create(
                    full_name__iexact=rider_name,
                    defaults={"full_name": rider_name,
                              "phone_number": phones[0] if phones else ""},
                )
                created["riders"] += int(created_rider)
                if phones and not rider.phone_number:
                    rider.phone_number = phones[0]
                    rider.save(update_fields=["phone_number"])

                motorcycle = Motorcycle.objects.get_or_create(
                    registration_number=next(serial),
                    defaults={"make_model": "Logbook plate not yet recorded"},
                )[0]

                start_date = week_dates[0]
                due_day = start_date.weekday() if week_dates else 0
                agreement = OwnershipAgreement.objects.create(
                    rider=rider, motorcycle=motorcycle,
                    total_price=Decimal(weeks) * weekly,
                    weekly_amount=weekly,
                    start_date=start_date,
                    weekly_due_day=due_day,
                )
                created["agreements"] += 1
                generate_instalments(agreement)

                sheet_report = []

                def record(receipt, amount, paid_at, comment, sequence=None):
                    is_mobile = bool(MOBILE_HINT_RE.search(comment or ""))
                    record_payment(
                        agreement=agreement,
                        amount=amount.quantize(Decimal("0.01")),
                        paid_at=datetime.combine(paid_at, datetime.min.time()).replace(
                            tzinfo=timezone.utc),
                        method=Payment.Method.MOBILE_MONEY if is_mobile else Payment.Method.CASH,
                        receipt_number=receipt,
                        created_by=operator,
                    )
                    created["payments"] += 1
                    if comment:
                        sheet_report.append({"receipt": receipt, "comment": comment})

                for deposit in deposits:
                    record(
                        f"LEGACY-{sheet}-D{deposit['row']}", deposit["amount"],
                        start_date - timedelta(days=3), deposit["comment"],
                    )
                for week in dated:
                    record(
                        f"LEGACY-{sheet}-R{week['row']}", week["amount"],
                        week["date"], week["comment"],
                    )
                for extra in extras:
                    # Undated mid-sheet payments attach to the next due week.
                    extras_date = next(
                        (d for d in week_dates if d > (start_date - timedelta(days=1))),
                        start_date,
                    )
                    record(
                        f"LEGACY-{sheet}-X{extra['row']}", extra["amount"],
                        extras_date, extra["comment"],
                    )

                if sheet_report:
                    AuditLog.objects.create(
                        action="legacy_comments_preserved",
                        entity_type="OwnershipAgreement", entity_id=agreement.pk,
                        actor=operator, details={"sheet": sheet, "rows": sheet_report},
                    )

        self.stdout.write(self.style.SUCCESS(
            f"Import complete: {created['riders']} riders, {created['agreements']} agreements, "
            f"{created['payments']} payments (incl. deposits)."
        ))
        self.stdout.write(
            "Note: motorcycle plates were not in the workbook, so placeholder plates "
            "TBC-001.. were linked; update them in the app/admin with the real plates."
        )
        missing_phones = [
            f"{r.id}:{r.full_name}" for r in Rider.objects.filter(phone_number="")
        ]
        if missing_phones:
            self.stdout.write(f"Riders without phone numbers: {', '.join(missing_phones)}")
