"""Send one test SMS through the configured gateway to verify credentials.

Usage:
  python manage.py send_test_sms --to +2567XXXXXXXX
"""
from django.core.management.base import BaseCommand, CommandError

from tracker.models import SmsLog
from tracker.sms import _backend, send_message


class Command(BaseCommand):
    help = "Send a one-off test SMS to confirm the Africas Talking setup."

    def add_arguments(self, parser):
        parser.add_argument("--to", required=True,
                            help="Phone number in +256XXXXXXXXX format.")

    def handle(self, *args, **options):
        to = options["to"].replace(" ", "")
        if not to.startswith("+256") or len(to) != 13 or not to[1:].isdigit():
            raise CommandError("Use the format +2567XXXXXXXX (13 characters).")

        backend = _backend()
        from tracker.models import Rider
        rider = Rider.objects.filter(phone_number=to).first()
        if rider is None:
            raise CommandError(
                "That number does not belong to any rider on record. "
                "The test SMS must go to a number saved on a rider (so the "
                "message can be logged against them)."
            )
        log = SmsLog.objects.create(
            rider=rider, phone_number=to,
            body="BodaTrack test message: SMS is working! 🎉",
            kind=SmsLog.Kind.RECEIPT,  # generic outbound; logged like any SMS
            status=SmsLog.Status.QUEUED,
        )
        try:
            gateway_id = send_message(log)
        except Exception as exc:  # noqa: BLE001 — failure already recorded on the log
            raise CommandError(f"SMS FAILED: {log.error or exc}") from exc
        self.stdout.write(self.style.SUCCESS(
            f"Test SMS sent to {to} via {backend.name} (gateway id: {gateway_id})."
        ))
