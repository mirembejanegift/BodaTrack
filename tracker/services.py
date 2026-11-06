"""Transactional financial operations for BodaTrack."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models.functions import Coalesce
from django.db.models import Value
from django.db import transaction
from django.db.models import F, OuterRef, Subquery, Sum
from django.utils import timezone

from .models import AuditLog, OwnershipAgreement, Payment, PaymentAllocation, WeeklyInstalment

ZERO = Decimal("0.00")


def calculate_arrears(agreement, as_of_date=None):
    """Sum unpaid portions of instalments due on/before as_of_date (Kampala today by default)."""
    as_of_date = as_of_date or timezone.localdate()
    due = WeeklyInstalment.objects.filter(agreement=agreement, due_date__lte=as_of_date)
    paid = PaymentAllocation.objects.filter(instalment__in=due, payment__status=Payment.Status.POSTED).values("instalment_id").annotate(total=Sum("amount"))
    paid_by_id = {row["instalment_id"]: row["total"] for row in paid}
    return sum((max(ZERO, item.amount_due - paid_by_id.get(item.pk, ZERO)) for item in due), ZERO)


def calculate_remaining_balance(agreement):
    """Agreement price less posted receipts; allocation timing never changes this figure."""
    received = agreement.payments.filter(status=Payment.Status.POSTED).aggregate(total=Sum("amount"))["total"] or ZERO
    return max(ZERO, agreement.total_price - received)


@transaction.atomic
def update_overdue_instalments(as_of_date=None):
    """Mark unpaid due rows overdue; suitable for a daily scheduled job and SMS queue."""
    as_of_date = as_of_date or timezone.localdate()
    candidates = WeeklyInstalment.objects.filter(due_date__lt=as_of_date).exclude(status=WeeklyInstalment.Status.PAID)
    allocations = PaymentAllocation.objects.filter(
        instalment_id=OuterRef("pk"), payment__status=Payment.Status.POSTED
    ).values("instalment_id").annotate(total=Sum("amount")).values("total")
    changed = candidates.annotate(paid_total=Coalesce(Subquery(allocations), Value(ZERO)))
    return changed.filter(paid_total__lt=F("amount_due")).update(status=WeeklyInstalment.Status.OVERDUE)


@transaction.atomic
def generate_instalments(agreement):
    """Create weekly due rows through the agreement price; existing rows are preserved."""
    agreement = OwnershipAgreement.objects.select_for_update().get(pk=agreement.pk)
    if agreement.weekly_due_day not in range(7):
        raise ValidationError("weekly_due_day must be between 0 (Monday) and 6 (Sunday).")
    first_due = agreement.start_date + timedelta(days=(agreement.weekly_due_day - agreement.start_date.weekday()) % 7)
    count = int((agreement.total_price / agreement.weekly_amount).to_integral_value(rounding="ROUND_CEILING"))
    rows = []
    remaining = agreement.total_price
    for index in range(count):
        amount = min(agreement.weekly_amount, remaining)
        due = first_due + timedelta(days=7 * index)
        item, created = WeeklyInstalment.objects.get_or_create(
            agreement=agreement, due_date=due, defaults={"amount_due": amount}
        )
        if created:
            rows.append(item)
        remaining -= amount
    return rows


@transaction.atomic
def allocate_payment(payment):
    """Rebuild FIFO allocations for this agreement so reversals restore arrears correctly.

    Payments beyond the generated schedule remain unallocated but still reduce the overall
    ownership balance. Call generate_instalments first when the schedule has not been made.
    """
    agreement = OwnershipAgreement.objects.select_for_update().get(pk=payment.agreement_id)
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status != Payment.Status.POSTED:
        raise ValidationError("Only posted payments can be allocated.")
    # Lock and clear all existing allocation rows for this agreement, then reapply valid receipts
    # by date. This is deterministic even if an earlier payment is entered late.
    list(WeeklyInstalment.objects.select_for_update().filter(agreement=agreement).order_by("due_date", "id"))
    PaymentAllocation.objects.filter(payment__agreement=agreement).delete()
    instalments = list(agreement.instalments.order_by("due_date", "id"))
    outstanding = {item.pk: item.amount_due for item in instalments}
    valid_payments = agreement.payments.filter(status=Payment.Status.POSTED).order_by("paid_at", "id")
    result = []
    for receipt in valid_payments:
        unallocated = receipt.amount
        for instalment in instalments:
            due_left = outstanding[instalment.pk]
            if due_left <= ZERO:
                continue
            applied = min(unallocated, due_left)
            if applied > ZERO:
                PaymentAllocation.objects.create(payment=receipt, instalment=instalment, amount=applied)
                outstanding[instalment.pk] -= applied
                unallocated -= applied
            if unallocated <= ZERO:
                break
    for instalment in instalments:
        if outstanding[instalment.pk] == ZERO:
            instalment.status = WeeklyInstalment.Status.PAID
        elif instalment.due_date < timezone.localdate():
            instalment.status = WeeklyInstalment.Status.OVERDUE
        elif outstanding[instalment.pk] < instalment.amount_due:
            instalment.status = WeeklyInstalment.Status.PARTIAL
        else:
            instalment.status = WeeklyInstalment.Status.SCHEDULED
    WeeklyInstalment.objects.bulk_update(instalments, ["status"])
    if calculate_remaining_balance(agreement) == ZERO:
        agreement.status = OwnershipAgreement.Status.FINANCIALLY_COMPLETED
    elif agreement.status == OwnershipAgreement.Status.FINANCIALLY_COMPLETED:
        agreement.status = OwnershipAgreement.Status.ACTIVE
    agreement.save(update_fields=["status"])
    return list(payment.allocations.select_related("instalment").order_by("instalment__due_date"))


@transaction.atomic
def record_payment(*, agreement, amount, paid_at, method, receipt_number, reference="", created_by=None):
    """Record a receipt and apply FIFO allocations in the same database transaction."""
    agreement = OwnershipAgreement.objects.select_for_update().get(pk=agreement.pk)
    payment = Payment.objects.create(
        agreement=agreement, amount=amount, paid_at=paid_at, method=method,
        receipt_number=receipt_number, reference=reference, created_by=created_by,
    )
    allocate_payment(payment)
    AuditLog.objects.create(
        action="payment_recorded", entity_type="Payment", entity_id=payment.pk,
        actor=created_by,
        details={
            "amount": str(amount), "method": method, "receipt_number": receipt_number,
            "reference": reference, "agreement_id": agreement.pk,
        },
    )
    return payment


@transaction.atomic
def reverse_payment(payment, *, actor=None, reason):
    """Reverse without deleting the receipt; write an audit event and re-run FIFO allocations."""
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status != Payment.Status.POSTED:
        raise ValidationError("Only a posted payment can be reversed.")
    if not reason.strip():
        raise ValidationError("A reason is required to reverse a payment.")
    payment.status = Payment.Status.REVERSED
    payment.reversed_at = timezone.now()
    payment.reversal_reason = reason.strip()
    payment.save(update_fields=["status", "reversed_at", "reversal_reason"])
    AuditLog.objects.create(action="payment_reversed", entity_type="Payment", entity_id=payment.pk,
                            actor=actor, reason=reason.strip(), details={"amount": str(payment.amount), "receipt_number": payment.receipt_number})
    # The supplied payment is reversed, so rebuild from all remaining posted receipts.
    agreement = OwnershipAgreement.objects.get(pk=payment.agreement_id)
    PaymentAllocation.objects.filter(payment__agreement=agreement).delete()
    # allocate_payment expects a posted payment, so rebuild valid receipts directly using a
    # temporary deterministic pass in the helper below.
    _rebuild_allocations(agreement)
    remaining = calculate_remaining_balance(agreement)
    if remaining == ZERO:
        agreement.status = OwnershipAgreement.Status.FINANCIALLY_COMPLETED
    elif agreement.status == OwnershipAgreement.Status.FINANCIALLY_COMPLETED:
        agreement.status = OwnershipAgreement.Status.ACTIVE
    agreement.save(update_fields=["status"])
    return payment


def _rebuild_allocations(agreement):
    instalments = list(agreement.instalments.order_by("due_date", "id"))
    outstanding = {item.pk: item.amount_due for item in instalments}
    for receipt in agreement.payments.filter(status=Payment.Status.POSTED).order_by("paid_at", "id"):
        remaining = receipt.amount
        for instalment in instalments:
            applied = min(remaining, outstanding[instalment.pk])
            if applied > ZERO:
                PaymentAllocation.objects.create(payment=receipt, instalment=instalment, amount=applied)
                outstanding[instalment.pk] -= applied
                remaining -= applied
            if remaining <= ZERO:
                break
    today = timezone.localdate()
    for item in instalments:
        if outstanding[item.pk] == ZERO:
            item.status = WeeklyInstalment.Status.PAID
        elif item.due_date < today:
            item.status = WeeklyInstalment.Status.OVERDUE
        elif outstanding[item.pk] < item.amount_due:
            item.status = WeeklyInstalment.Status.PARTIAL
        else:
            item.status = WeeklyInstalment.Status.SCHEDULED
    WeeklyInstalment.objects.bulk_update(instalments, ["status"])


@transaction.atomic
def approve_legal_transfer(agreement, *, actor, approval_date):
    """Explicit approval action; financial completion alone never invokes this function."""
    agreement = OwnershipAgreement.objects.select_for_update().get(pk=agreement.pk)
    if actor is None:
        raise ValidationError("A named approver is required to approve a legal transfer.")
    if calculate_remaining_balance(agreement) != ZERO:
        raise ValidationError("Legal transfer cannot be approved while an ownership balance remains.")
    agreement.legal_transfer_approved_at = approval_date
    agreement.legal_transfer_approved_by = actor
    agreement.save(update_fields=["legal_transfer_approved_at", "legal_transfer_approved_by"])
    AuditLog.objects.create(action="legal_transfer_approved", entity_type="OwnershipAgreement", entity_id=agreement.pk,
                            actor=actor, details={"approval_date": approval_date.isoformat()})
    return agreement
