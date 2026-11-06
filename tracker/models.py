from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Rider(models.Model):
    full_name = models.CharField(max_length=200)
    phone_number = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.full_name


class Motorcycle(models.Model):
    registration_number = models.CharField(max_length=30, unique=True)
    make_model = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.registration_number


class OwnershipAgreement(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        FINANCIALLY_COMPLETED = "financially_completed", "Financially completed"
        CANCELLED = "cancelled", "Cancelled"

    rider = models.ForeignKey(Rider, on_delete=models.PROTECT, related_name="agreements")
    motorcycle = models.ForeignKey(Motorcycle, on_delete=models.PROTECT, related_name="agreements")
    total_price = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    weekly_amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    start_date = models.DateField()
    # Monday=0 ... Sunday=6. The first due date is the first matching day on/after start_date.
    weekly_due_day = models.PositiveSmallIntegerField(default=0, validators=[MinValueValidator(0)])
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.ACTIVE)
    legal_transfer_approved_at = models.DateField(null=True, blank=True)
    legal_transfer_approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name="approved_bodatrack_transfers")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(weekly_due_day__gte=0, weekly_due_day__lte=6), name="weekly_due_day_valid_range"),
            # Legal transfer must record BOTH who approved it and when, or neither.
            models.CheckConstraint(
                condition=models.Q(legal_transfer_approved_at__isnull=True, legal_transfer_approved_by__isnull=True)
                | models.Q(legal_transfer_approved_at__isnull=False, legal_transfer_approved_by__isnull=False),
                name="legal_transfer_fields_both_or_neither",
            ),
        ]

    def __str__(self):
        return f"{self.rider} — {self.motorcycle}"


class WeeklyInstalment(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        PARTIAL = "partial", "Partially paid"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"

    agreement = models.ForeignKey(OwnershipAgreement, on_delete=models.PROTECT, related_name="instalments")
    due_date = models.DateField()
    amount_due = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)

    class Meta:
        ordering = ("due_date", "id")
        constraints = [models.UniqueConstraint(fields=("agreement", "due_date"), name="unique_agreement_instalment_date")]

    @property
    def amount_paid(self):
        return self.allocations.filter(payment__status=Payment.Status.POSTED).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")

    @property
    def outstanding_amount(self):
        return max(Decimal("0.00"), self.amount_due - self.amount_paid)


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        MOBILE_MONEY = "mobile_money", "Mobile Money"

    class Status(models.TextChoices):
        POSTED = "posted", "Posted"
        REVERSED = "reversed", "Reversed"
        VOIDED = "voided", "Voided"

    agreement = models.ForeignKey(OwnershipAgreement, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    paid_at = models.DateTimeField()
    method = models.CharField(max_length=20, choices=Method.choices)
    reference = models.CharField(max_length=100, blank=True)
    receipt_number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.POSTED)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("paid_at", "id")
        constraints = [
            # A reversed payment must carry a reason and the time it was reversed;
            # expressed as two composable rules:
            #   "reversed AND empty reason" is forbidden
            #   "reversed AND no reversal timestamp" is forbidden
            # NOTE: the plain string is used because the Payment class cannot
            # reference itself inside its own Meta block.
            models.CheckConstraint(
                condition=~models.Q(status="reversed", reversal_reason=""),
                name="reversal_requires_reason",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="reversed", reversed_at__isnull=True),
                name="reversal_requires_timestamp",
            ),
        ]


class PaymentAllocation(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="allocations")
    instalment = models.ForeignKey(WeeklyInstalment, on_delete=models.PROTECT, related_name="allocations")
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("payment", "instalment"), name="unique_payment_instalment_allocation"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="allocation_amount_positive"),
        ]


class AuditLog(models.Model):
    action = models.CharField(max_length=50)
    entity_type = models.CharField(max_length=80)
    entity_id = models.PositiveBigIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    reason = models.TextField(blank=True)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
