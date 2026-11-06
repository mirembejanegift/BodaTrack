"""Request/response shapes for the BodaTrack API.

Read serializers expose computed money figures (as strings, so no precision is
lost in JSON). Write serializers validate business rules BEFORE anything is
saved: the client only describes a payment, it never computes allocations.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import (
    AuditLog,
    Motorcycle,
    OwnershipAgreement,
    Payment,
    Rider,
    WeeklyInstalment,
)
from .services import calculate_arrears, calculate_remaining_balance

ZERO = "0.00"


class RiderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rider
        fields = ("id", "full_name", "phone_number", "is_active")


class MotorcycleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Motorcycle
        fields = ("id", "registration_number", "make_model", "is_active")


class RiderLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rider
        fields = ("id", "full_name", "phone_number")


class MotorcycleLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Motorcycle
        fields = ("id", "registration_number", "make_model")


class InstalmentSerializer(serializers.ModelSerializer):
    amount_paid = serializers.SerializerMethodField()
    outstanding_amount = serializers.SerializerMethodField()

    class Meta:
        model = WeeklyInstalment
        fields = ("id", "agreement", "due_date", "amount_due", "amount_paid",
                  "outstanding_amount", "status")

    def get_amount_paid(self, obj):
        return str(obj.amount_paid)

    def get_outstanding_amount(self, obj):
        return str(obj.outstanding_amount)


class OwnershipAgreementSerializer(serializers.ModelSerializer):
    rider = RiderLiteSerializer(read_only=True)
    motorcycle = MotorcycleLiteSerializer(read_only=True)
    total_arrears = serializers.SerializerMethodField()
    remaining_balance = serializers.SerializerMethodField()
    next_due_date = serializers.SerializerMethodField()

    class Meta:
        model = OwnershipAgreement
        fields = ("id", "rider", "motorcycle", "total_price", "weekly_amount",
                  "start_date", "weekly_due_day", "status", "legal_transfer_approved_at",
                  "legal_transfer_approved_by", "total_arrears", "remaining_balance",
                  "next_due_date", "created_at")

    def get_total_arrears(self, obj):
        return str(calculate_arrears(obj))

    def get_remaining_balance(self, obj):
        return str(calculate_remaining_balance(obj))

    def get_next_due_date(self, obj):
        row = obj.instalments.filter(
            status__in=[WeeklyInstalment.Status.SCHEDULED, WeeklyInstalment.Status.PARTIAL],
        ).order_by("due_date").first()
        return row.due_date if row else None


class OwnershipAgreementCreateSerializer(serializers.ModelSerializer):
    rider_id = serializers.PrimaryKeyRelatedField(source="rider", queryset=Rider.objects.filter(is_active=True))
    motorcycle_id = serializers.PrimaryKeyRelatedField(source="motorcycle", queryset=Motorcycle.objects.filter(is_active=True))

    class Meta:
        model = OwnershipAgreement
        fields = ("rider_id", "motorcycle_id", "total_price", "weekly_amount",
                  "start_date", "weekly_due_day")

    def validate(self, data):
        motorcycle = data["motorcycle"]
        other_active = OwnershipAgreement.objects.filter(
            motorcycle=motorcycle,
            status=OwnershipAgreement.Status.ACTIVE,
        )
        if other_active.exists():
            raise serializers.ValidationError(
                {"motorcycle_id": "This motorcycle already has an active ownership agreement."}
            )
        return data


class PaymentAllocationInlineSerializer(serializers.Serializer):
    instalment_id = serializers.IntegerField()
    due_date = serializers.DateField(source="instalment.due_date", read_only=True)
    amount = serializers.CharField()


class PaymentSerializer(serializers.ModelSerializer):
    agreement = serializers.PrimaryKeyRelatedField(read_only=True)
    created_by = serializers.StringRelatedField()
    allocations = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = ("id", "agreement", "amount", "paid_at", "method", "reference",
                  "receipt_number", "status", "created_by", "reversed_at",
                  "reversal_reason", "created_at", "allocations")

    def get_allocations(self, obj):
        return PaymentAllocationInlineSerializer(
            obj.allocations.select_related("instalment"), many=True,
        ).data


class PaymentCreateSerializer(serializers.Serializer):
    """Validates a receipt. Allocation is always computed server-side (FIFO)."""
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    paid_at = serializers.DateTimeField()
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    receipt_number = serializers.CharField(max_length=40)
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")

    def validate(self, data):
        agreement = self.context["agreement"]
        if agreement.status == OwnershipAgreement.Status.CANCELLED:
            raise serializers.ValidationError("Payments cannot be recorded against a cancelled agreement.")

        if data["method"] == Payment.Method.MOBILE_MONEY and not data.get("reference", "").strip():
            raise serializers.ValidationError(
                {"reference": "A Mobile Money transaction reference is required for mobile money payments."}
            )

        if Payment.objects.filter(receipt_number=data["receipt_number"]).exists():
            raise serializers.ValidationError(
                {"receipt_number": "This receipt number has already been used."}
            )

        remaining = calculate_remaining_balance(agreement)
        if data["amount"] > remaining:
            raise serializers.ValidationError(
                {"amount": f"Amount exceeds the remaining ownership balance (UGX {remaining})."}
            )
        return data


class ReversePaymentSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, min_length=5, error_messages={
        "min_length": "A reversal reason of at least 5 characters is required.",
    })


class LegalTransferApprovalSerializer(serializers.Serializer):
    approval_date = serializers.DateField(default=timezone.localdate)


class AuditLogSerializer(serializers.ModelSerializer):
    actor = serializers.StringRelatedField()

    class Meta:
        model = AuditLog
        fields = ("id", "action", "entity_type", "entity_id", "actor", "reason", "details", "created_at")


class RegisterSerializer(serializers.Serializer):
    """Self-service account creation for new staff members."""
    username = serializers.CharField(max_length=150, min_length=3)
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    password = serializers.CharField(max_length=128, write_only=True)

    def validate_username(self, value):
        User = get_user_model()
        if User.objects.filter(username__iexact=value.strip()).exists():
            raise serializers.ValidationError("This username has already been registered.")
        return value.strip()

    def validate_password(self, value):
        # Django's standard strength rules (minimum length, common passwords).
        validate_password(value)
        return value

    def create(self, validated_data):
        User = get_user_model()
        user = User.objects.create_user(
            username=validated_data["username"],
            password=validated_data["password"],
            first_name=validated_data.get("full_name", ""),
        )
        return user
