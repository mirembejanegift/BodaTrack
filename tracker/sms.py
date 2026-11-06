"""Outbound SMS for BodaTrack.

Messages are never sent directly from a payment view — they are queued in the
SmsLog table and flushed by `python manage.py send_sms`. This has two benefits:

1. A payment transaction never fails just because a phone gateway is slow.
2. Every SMS is a durable record: queued, sent, or failed with the error text.

Backends are selected with the SMS_BACKEND environment variable:
- "console"        (default, dev): prints the SMS to the server log.
- "africastalking": sends via the Africa's Talking gateway using
  AFRICAS_TALKING_USERNAME, AFRICAS_TALKING_API_KEY and optionally
  AFRICAS_TALKING_SENDER_ID (e.g. your approved sender name).
"""
import json
import os
import urllib.error
import urllib.request

from django.utils import timezone

from .models import SmsLog
from .services import calculate_remaining_balance


# ---------------------------------------------------------------- queueing

def queue_message(*, rider, body, kind, agreement=None, payment=None, for_date=None):
    """Queue one SMS. Riders without a phone number get a FAILED row so the
    omission is visible in reports instead of silently vanishing."""
    phone = (rider.phone_number or "").replace(" ", "")
    status = SmsLog.Status.QUEUED if phone else SmsLog.Status.FAILED
    error = "" if phone else "Rider has no phone number on record."
    return SmsLog.objects.create(
        rider=rider, agreement=agreement, payment=payment, for_date=for_date,
        phone_number=phone, body=body, kind=kind,
        status=status, error=error,
    )


def receipt_body(payment):
    """Thank-you text after a successful payment."""
    agreement = payment.agreement
    remaining = calculate_remaining_balance(agreement)
    return (
        f"Thank you {agreement.rider.full_name}! "
        f"Receipt {payment.receipt_number}: UGX {payment.amount:,.0f} received. "
        f"Remaining balance: UGX {remaining:,.0f}."
    )


def reminder_body(agreement, arrears, next_due):
    """Reminder text for a rider behind on past-due weeks."""
    due_text = f"Next instalment due {next_due}." if next_due else ""
    return (
        f"Hello {agreement.rider.full_name}, this is a payment reminder. "
        f"Weekly arrears: UGX {arrears:,.0f}. "
        f"Total remaining on your bike ({agreement.motorcycle.registration_number}): "
        f"UGX {calculate_remaining_balance(agreement):,.0f}. {due_text}"
    )


# ---------------------------------------------------------------- backends

class _ConsoleBackend:
    """Development backend: prints the message instead of costing money."""
    name = "console"
    requires_credentials = False

    def send(self, log):
        print(f"[SMS -> {log.phone_number}] {log.body}")
        return "console"


class _AfricasTalkingBackend:
    name = "africastalking"
    requires_credentials = True
    _SUCCESS_CODES = {100, 101, 102}  # processed / sent / queued

    def send(self, log):
        username = os.environ.get("AFRICAS_TALKING_USERNAME", "")
        api_key = os.environ.get("AFRICAS_TALKING_API_KEY", "")
        sender = os.environ.get("AFRICAS_TALKING_SENDER_ID", "AFRICASTKNG")
        if not username or not api_key:
            raise RuntimeError(
                "AFRICAS_TALKING_USERNAME and AFRICAS_TALKING_API_KEY must be set in .env."
            )
        payload = json.dumps({
            "username": username,
            "to": [log.phone_number],
            "message": log.body,
            "from": sender,
        }).encode()
        request = urllib.request.Request(
            "https://api.africastalking.com/version1/messaging",
            data=payload,
            headers={
                "apiKey": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode())
        recipients = data.get("SMSMessageData", {}).get("Recipients", [])
        if not recipients:
            raise RuntimeError(f"Gateway returned no recipients: {data}")
        first = recipients[0]
        if int(first.get("statusCode", 1)) not in self._SUCCESS_CODES:
            raise RuntimeError(f"Gateway rejected message: {first}")
        return str(first.get("messageId", "sent"))


def _backend():
    name = os.environ.get("SMS_BACKEND", "console")
    return _AfricasTalkingBackend() if name == "africastalking" else _ConsoleBackend()


def send_message(log):
    """Attempt delivery of one queued message and record the outcome."""
    try:
        backend = _backend()
        gateway_id = backend.send(log)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode()[:300]
        except Exception:  # noqa: BLE001
            pass
        log.status = SmsLog.Status.FAILED
        log.error = f"HTTP {exc.code}: {detail or exc.reason}"
        log.save(update_fields=["status", "error"])
        raise
    except Exception as exc:  # noqa: BLE001 — record every delivery failure
        log.status = SmsLog.Status.FAILED
        log.error = str(exc)[:500]
        log.save(update_fields=["status", "error"])
        raise
    log.status = SmsLog.Status.SENT
    log.error = ""
    log.sent_at = timezone.now()
    log.save(update_fields=["status", "error", "sent_at"])
    return gateway_id


def send_all_queued(limit=500):
    """Flush the queue; returns (sent_count, failed_count)."""
    sent = failed = 0
    for log in SmsLog.objects.filter(status=SmsLog.Status.QUEUED)[:limit]:
        try:
            send_message(log)
            sent += 1
        except Exception:  # noqa: BLE001 — send_message already recorded the failure
            failed += 1
    return sent, failed
