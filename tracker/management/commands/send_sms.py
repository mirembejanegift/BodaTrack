"""Deliver queued SMS and/or queue payment reminders, then flush the queue.

Typical use (e.g. every morning via Windows Task Scheduler):
    python manage.py send_sms --reminders
Sending receipt thank-yous requires no flags; they are already queued when a
payment is recorded.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from tracker.models import SmsLog
from tracker.services import queue_weekly_reminders
from tracker.sms import send_all_queued, send_message


class Command(BaseCommand):
    help = "Queue weekly arrears reminders (optional) and send all queued SMS."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reminders", action="store_true",
            help="Queue reminder SMS for riders with arrears before sending.",
        )
        parser.add_argument(
            "--force-reminders", action="store_true",
            help="Queue reminders even if today is not Saturday (override).",
        )
        parser.add_argument(
            "--retry-failed", action="store_true",
            help="Also retry messages that failed on earlier attempts.",
        )

    def handle(self, *args, **options):
        if options["reminders"]:
            # Weekly rhythm: reminders go out on Saturdays only, once a week,
            # so riders are not chased daily. Saturday = weekday 5.
            if timezone.localdate().weekday() == 5 or options["force_reminders"]:
                reminders = queue_weekly_reminders()
                self.stdout.write(f"Queued {len(reminders)} reminder message(s).")
            else:
                self.stdout.write(
                    "Today is not Saturday - reminders are queued once a week "
                    "on Saturdays. Use --force-reminders to override."
                )
        sent, failed = send_all_queued()
        self.stdout.write(f"SMS sent: {sent}, failed: {failed}.")
        if options["retry_failed"] and failed:
            retryable = SmsLog.objects.filter(status=SmsLog.Status.FAILED)
            retried = ok = 0
            for log in retryable:
                if not log.phone_number:
                    continue  # permanent failure: no phone number on record
                retried += 1
                try:
                    send_message(log)
                    ok += 1
                except Exception:  # noqa: BLE001 — logged on the SmsLog row
                    pass
            self.stdout.write(f"Retried {retried} failed message(s); {ok} recovered.")
        if failed:
            self.stderr.write("Some messages failed; check the SMS log in the "
                              "Django admin (tracker / Sms logs) for error details.")
