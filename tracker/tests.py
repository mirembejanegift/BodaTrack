from datetime import date, datetime, timezone as datetime_timezone
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APITestCase

from .models import AuditLog, Motorcycle, OwnershipAgreement, Payment, PaymentAllocation, Rider, WeeklyInstalment
from .services import (
    allocate_payment,
    calculate_arrears,
    calculate_remaining_balance,
    generate_instalments,
    queue_weekly_reminders,
    record_payment,
    reverse_payment,
    update_overdue_instalments,
)

class FinancialServicesTests(TestCase):
    def setUp(self):
        rider = Rider.objects.create(full_name="Amina Namusoke")
        bike = Motorcycle.objects.create(registration_number="UFA 123A")
        self.agreement = OwnershipAgreement.objects.create(
            rider=rider, motorcycle=bike, total_price=Decimal("3000000.00"),
            weekly_amount=Decimal("100000.00"), start_date=date(2026, 1, 5), weekly_due_day=0,
        )
        generate_instalments(self.agreement)

    def payment(self, amount, receipt, paid_at):
        return Payment.objects.create(
            agreement=self.agreement, amount=Decimal(amount), paid_at=paid_at,
            method=Payment.Method.CASH, receipt_number=receipt,
        )

    def test_partial_payments_reduce_weekly_arrears(self):
        payment = self.payment("40000.00", "R-001", datetime(2026, 1, 12, tzinfo=datetime_timezone.utc))
        allocate_payment(payment)

        self.assertEqual(calculate_arrears(self.agreement, date(2026, 1, 5)), Decimal("60000.00"))
        first = self.agreement.instalments.get(due_date=date(2026, 1, 5))
        # This historical due date is overdue; the partial allocation is reflected in arrears.
        self.assertEqual(first.status, WeeklyInstalment.Status.OVERDUE)
        self.assertEqual(calculate_remaining_balance(self.agreement), Decimal("2960000.00"))

    def test_overpayment_rolls_into_future_instalments_and_reduces_balance(self):
        payment = self.payment("250000.00", "R-002", datetime(2026, 1, 5, tzinfo=datetime_timezone.utc))
        allocate_payment(payment)

        allocations = list(PaymentAllocation.objects.filter(payment=payment).order_by("instalment__due_date"))
        self.assertEqual([row.amount for row in allocations], [Decimal("100000.00"), Decimal("100000.00"), Decimal("50000.00")])
        self.assertEqual(calculate_arrears(self.agreement, date(2026, 1, 19)), Decimal("50000.00"))
        self.assertEqual(calculate_remaining_balance(self.agreement), Decimal("2750000.00"))

    def test_reversal_restores_arrears_and_balance_without_deleting_payment(self):
        payment = self.payment("100000.00", "R-003", datetime(2026, 1, 5, tzinfo=datetime_timezone.utc))
        allocate_payment(payment)
        reverse_payment(payment, reason="Duplicate cash entry")

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.REVERSED)
        self.assertTrue(Payment.objects.filter(pk=payment.pk).exists())
        self.assertEqual(payment.allocations.count(), 0)
        self.assertEqual(calculate_arrears(self.agreement, date(2026, 1, 5)), Decimal("100000.00"))
        self.assertEqual(calculate_remaining_balance(self.agreement), Decimal("3000000.00"))

    def test_overdue_job_flags_oldest_unpaid_instalment(self):
        updated = update_overdue_instalments(date(2026, 1, 6))
        first = self.agreement.instalments.get(due_date=date(2026, 1, 5))
        self.assertEqual(updated, 1)
        self.assertEqual(first.status, WeeklyInstalment.Status.OVERDUE)

    def test_full_completion_is_financial_only_and_transfer_is_separate(self):
        """Paying the full price does NOT approve the legal ownership transfer."""
        from django.contrib.auth import get_user_model
        approver = get_user_model().objects.create_user("owner", password="!x", is_staff=True)
        payment = self.payment("3000000.00", "R-004", datetime(2026, 1, 5, tzinfo=datetime_timezone.utc))
        allocate_payment(payment)

        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, OwnershipAgreement.Status.FINANCIALLY_COMPLETED)
        # The balance is now zero, but ownership has NOT transferred yet.
        self.assertIsNone(self.agreement.legal_transfer_approved_at)
        self.assertIsNone(self.agreement.legal_transfer_approved_by)

        from .services import approve_legal_transfer
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            approve_legal_transfer(self.agreement, actor=None, approval_date=date(2026, 3, 2))
        approve_legal_transfer(self.agreement, actor=approver, approval_date=date(2026, 3, 2))
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.legal_transfer_approved_at, date(2026, 3, 2))


class ApiTests(APITestCase):
    """Tests that go through the HTTP layer, with CSRF/session auth rules."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.staff_user = User.objects.create_user("boss", password="S3cretPass!2026", is_staff=True)
        self.client.force_login(self.staff_user)

        self.rider = Rider.objects.create(full_name="Sarah Namboozo", phone_number="0773 333 333")
        self.bike = Motorcycle.objects.create(registration_number="UFB 456B")
        self.agreement = OwnershipAgreement.objects.create(
            rider=self.rider, motorcycle=self.bike, total_price=Decimal("2000000.00"),
            weekly_amount=Decimal("100000.00"), start_date=date(2026, 2, 2), weekly_due_day=0,
        )
        generate_instalments(self.agreement)

    def pay(self, amount, receipt, paid_at, method=Payment.Method.CASH, reference=""):
        return self.client.post(
            f"/api/agreements/{self.agreement.pk}/payments/",
            {"amount": amount, "paid_at": paid_at, "method": method,
             "receipt_number": receipt, "reference": reference},
        )

    def test_agreement_detail_exposes_computed_figures(self):
        response = self.client.get(f"/api/agreements/{self.agreement.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["remaining_balance"], "2000000.00")
        # No payments exist and every schedule row is in the past relative to
        # "today", so the full price stands as arrears.
        self.assertEqual(response.data["total_arrears"], "2000000.00")
        next_due = response.data["next_due_date"]
        self.assertIsNotNone(next_due)

    def test_record_payment_and_recompute(self):
        response = self.pay("100000.00", "BC-0001", "2026-02-02T12:00:00Z")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(PaymentAllocation.objects.count(), 1)

        response = self.client.get(f"/api/agreements/{self.agreement.pk}/")
        self.assertEqual(response.data["remaining_balance"], "1900000.00")

        audit_action = AuditLog.objects.filter(action="payment_recorded").exists()
        self.assertTrue(audit_action)

    def test_mobile_money_requires_reference(self):
        response = self.pay("50000.00", "BC-0002", "2026-02-02T12:00:00Z",
                            method=Payment.Method.MOBILE_MONEY)
        self.assertEqual(response.status_code, 400)
        self.assertIn("reference", str(response.data).lower())

    def test_mobile_money_with_reference_is_accepted(self):
        response = self.pay("50000.00", "BC-0003", "2026-02-02T12:00:00Z",
                            method=Payment.Method.MOBILE_MONEY, reference="MP12345678")
        self.assertEqual(response.status_code, 201)

    def test_duplicate_receipt_number_rejected(self):
        self.pay("50000.00", "BC-0004", "2026-02-02T12:00:00Z")
        response = self.pay("50000.00", "BC-0004", "2026-02-09T12:00:00Z")
        self.assertEqual(response.status_code, 400)
        self.assertIn("receipt", str(response.data).lower())

    def test_payment_above_remaining_balance_rejected(self):
        response = self.pay("2000100.00", "BC-0005", "2026-02-02T12:00:00Z")
        self.assertEqual(response.status_code, 400)

    def test_reversal_requires_reason(self):
        self.pay("50000.00", "BC-0006", "2026-02-02T12:00:00Z")
        payment = Payment.objects.get(receipt_number="BC-0006")
        response = self.client.post(f"/api/payments/{payment.pk}/reverse/", {"reason": ""})
        self.assertEqual(response.status_code, 400)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.POSTED)

    def test_reversal_restores_state_by_api(self):
        self.pay("100000.00", "BC-0007", "2026-02-02T12:00:00Z")
        payment = Payment.objects.get(receipt_number="BC-0007")
        response = self.client.post(
            f"/api/payments/{payment.pk}/reverse/", {"reason": "Entered twice by mistake"}
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.get(f"/api/agreements/{self.agreement.pk}/")
        self.assertEqual(response.data["remaining_balance"], "2000000.00")
        self.assertTrue(AuditLog.objects.filter(action="payment_reversed", entity_id=payment.pk).exists())

    def test_transfer_approval_requires_zero_balance(self):
        response = self.client.post(
            f"/api/agreements/{self.agreement.pk}/transfer-approval/",
            {"approval_date": "2026-10-01"},
        )
        self.assertEqual(response.status_code, 400)

    def test_transfer_approval_after_full_repayment(self):
        record_payment(
            agreement=self.agreement, amount=Decimal("2000000.00"),
            paid_at=datetime(2026, 2, 2, tzinfo=datetime_timezone.utc),
            method=Payment.Method.CASH, receipt_number="BC-0008", created_by=self.staff_user,
        )
        response = self.client.post(
            f"/api/agreements/{self.agreement.pk}/transfer-approval/",
            {"approval_date": "2026-10-01"},
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.legal_transfer_approved_at, date(2026, 10, 1))
        self.assertEqual(self.agreement.legal_transfer_approved_by, self.staff_user)
        self.assertTrue(
            AuditLog.objects.filter(action="legal_transfer_approved", entity_id=self.agreement.pk).exists()
        )

    def test_agreement_terms_locked_once_payments_exist(self):
        self.pay("50000.00", "BC-0009", "2026-02-02T12:00:00Z")
        response = self.client.patch(
            f"/api/agreements/{self.agreement.pk}/", {"weekly_amount": "120000.00"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("payments", str(response.data).lower())

    def test_reports_endpoints(self):
        self.pay("100000.00", "BC-0010", "2026-02-02T12:00:00Z")
        response = self.client.get("/api/reports/arrears/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["agreements"]), 1)

        response = self.client.get("/api/reports/collections/", {"from": "2026-01-01", "to": "2026-12-31"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["grand_total"], "100000.00")

    def test_business_endpoints_reject_anonymous_users(self):
        # DRF answers anonymous session-auth requests with 403 Forbidden.
        self.client.logout()
        response = self.client.get("/api/agreements/")
        self.assertEqual(response.status_code, 403)
        response = self.client.post(f"/api/agreements/{self.agreement.pk}/payments/", {})
        self.assertEqual(response.status_code, 403)


class RegistrationTests(APITestCase):
    """Self-service account creation."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        self.User = get_user_model()

    def test_registration_creates_active_staff_account_and_logs_in(self):
        response = self.client.post("/api/auth/register/", {
            "username": "newclerk", "password": "V8ry-Safe-2026!", "full_name": "Clerk Two",
        })
        self.assertEqual(response.status_code, 201)
        user = self.User.objects.get(username="newclerk")
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)  # DJANGO_AUTO_STAFF default

        # The new account is immediately usable.
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["username"], "newclerk")
        self.assertTrue(
            AuditLog.objects.filter(action="user_registered", entity_id=user.pk).exists()
        )

    def test_duplicate_username_rejected(self):
        self.User.objects.create_user("taken", password="Whatever-2026!")
        response = self.client.post("/api/auth/register/", {
            "username": "taken", "password": "V8ry-Safe-2026!",
        })
        self.assertEqual(response.status_code, 400)

    def test_weak_password_rejected(self):
        response = self.client.post("/api/auth/register/", {
            "username": "weakpw", "password": "password",
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.User.objects.filter(username="weakpw").exists())


class SmsTests(APITestCase):
    """Thank-you queueing, reminder queueing and the send command."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.staff_user = User.objects.create_user("boss", password="S3cretPass!2026", is_staff=True)
        self.client.force_login(self.staff_user)

        self.rider = Rider.objects.create(
            full_name="Grace Atim", phone_number="0775 555 555",
        )
        self.bike = Motorcycle.objects.create(registration_number="UFC 789C")
        self.agreement = OwnershipAgreement.objects.create(
            rider=self.rider, motorcycle=self.bike, total_price=Decimal("2000000.00"),
            weekly_amount=Decimal("100000.00"), start_date=date(2026, 2, 2), weekly_due_day=0,
        )
        generate_instalments(self.agreement)

    def test_payment_queues_a_thank_you_sms(self):
        from .models import SmsLog
        response = self.client.post(
            f"/api/agreements/{self.agreement.pk}/payments/",
            {"amount": "100000.00", "paid_at": "2026-02-02T12:00:00Z",
             "method": Payment.Method.CASH, "receipt_number": "SMS-0001"},
        )
        self.assertEqual(response.status_code, 201, response.data)
        message = SmsLog.objects.get(kind=SmsLog.Kind.RECEIPT, payment__receipt_number="SMS-0001")
        self.assertEqual(message.status, SmsLog.Status.QUEUED)
        self.assertIn("Thank you", message.body)
        self.assertIn("1,900,000", message.body)  # remaining balance appears in the text

    def test_reminders_queue_once_per_day_per_agreement(self):
        from .models import SmsLog

        from datetime import date as date_cls
        first = queue_weekly_reminders(date_cls(2026, 3, 10))
        second = queue_weekly_reminders(date_cls(2026, 3, 10))
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])  # one reminder per agreement per day

        next_day = queue_weekly_reminders(date_cls(2026, 3, 11))
        self.assertEqual(
            [row.phone_number for row in next_day], ["0775555555"]
        )

    def test_send_sms_command_marks_console_messages_sent(self):
        from django.core.management import call_command

        from .models import SmsLog

        self.client.post(
            f"/api/agreements/{self.agreement.pk}/payments/",
            {"amount": "100000.00", "paid_at": "2026-02-02T12:00:00Z",
             "method": Payment.Method.CASH, "receipt_number": "SMS-0002"},
        )
        queue_weekly_reminders(date(2026, 3, 12))
        call_command("send_sms")
        statuses = list(SmsLog.objects.values_list("status", flat=True))
        self.assertTrue(statuses)
        self.assertEqual(set(statuses), {SmsLog.Status.SENT})

    def test_rider_without_phone_gets_a_failed_log(self):
        from .models import SmsLog
        from .services import queue_weekly_reminders
        from datetime import date as date_cls
        self.rider.phone_number = ""
        self.rider.save(update_fields=["phone_number"])
        queued = queue_weekly_reminders(date_cls(2026, 3, 13))
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0].status, SmsLog.Status.FAILED)
        self.assertIn("phone", queued[0].error.lower())
