"""DRF views: the only door into BodaTrack's money logic.

Rules enforced here rather than in the frontend:
- every business endpoint requires a logged-in staff user;
- money figures are computed server-side, never trusted from the client;
- payments are never deleted, only reversed (with a mandatory reason);
- every mutating action writes an AuditLog row (in services.py).
"""
from datetime import date
from decimal import Decimal
import os

from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, ProtectedError, Q, Sum
from django.middleware.csrf import get_token
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from . import serializers as slz
from .models import (
    AuditLog,
    Motorcycle,
    OwnershipAgreement,
    Payment,
    Rider,
    WeeklyInstalment,
)
from .services import (
    approve_legal_transfer,
    calculate_arrears,
    calculate_remaining_balance,
    generate_instalments,
    record_payment,
    reverse_payment,
)


class StaffWritePermission(permissions.BasePermission):
    """Reads: any authenticated user. Writes: staff users only."""

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return user.is_staff and user.is_active


def django_errors_to_response(exc):
    """Convert a Django ValidationError into a DRF-style 400 response."""
    messages = exc.messages if hasattr(exc, "messages") and exc.messages else [str(exc)]
    return Response({"detail": " ".join(messages)}, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------- auth

class CsrfTokenView(APIView):
    """Hands the browser its CSRF cookie before the first POST."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response({"detail": "Wrong username or password."}, status=status.HTTP_403_FORBIDDEN)
        if not user.is_active:
            return Response({"detail": "This account is disabled."}, status=status.HTTP_403_FORBIDDEN)
        login(request, user)
        return Response({"id": user.pk, "username": user.username, "is_staff": user.is_staff,
                         "full_name": user.get_full_name() or user.username})


class LogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response({"detail": "Logged out."})


class MeView(APIView):
    def get(self, request):
        user = request.user
        return Response({"id": user.pk, "username": user.username, "is_staff": user.is_staff,
                         "full_name": user.get_full_name() or user.username})


class RegisterView(APIView):
    """Self-service registration for staff accounts.

    Security note: whether a new account can immediately perform money
    operations is controlled by the DJANGO_AUTO_STAFF env var (default true,
    appropriate for a trusted shop LAN). Set it to "false" to require an
    existing admin to promote the account via the Django admin first.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = slz.RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        auto_staff = os.environ.get("DJANGO_AUTO_STAFF", "true").lower() != "false"
        user.is_staff = auto_staff
        user.save(update_fields=["is_staff"])
        AuditLog.objects.create(
            action="user_registered", entity_type="User", entity_id=user.pk,
            actor=None, details={"username": user.username, "staff": auto_staff},
        )
        login(request, user)
        return Response({"id": user.pk, "username": user.username, "is_staff": user.is_staff,
                         "full_name": user.get_full_name() or user.username},
                        status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------- business

class RiderViewSet(viewsets.ModelViewSet):
    serializer_class = slz.RiderSerializer
    permission_classes = [StaffWritePermission]

    def get_queryset(self):
        qs = Rider.objects.all()
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(Q(full_name__icontains=search) | Q(phone_number__icontains=search))
        return qs

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {"detail": "This rider has agreements or payments on record. Deactivate them instead."},
                status=status.HTTP_400_BAD_REQUEST,
            )


class MotorcycleViewSet(viewsets.ModelViewSet):
    serializer_class = slz.MotorcycleSerializer
    permission_classes = [StaffWritePermission]

    def get_queryset(self):
        qs = Motorcycle.objects.all()
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(Q(registration_number__icontains=search) | Q(make_model__icontains=search))
        return qs

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {"detail": "This motorcycle has agreements or payments on record. Deactivate it instead."},
                status=status.HTTP_400_BAD_REQUEST,
            )


class AgreementViewSet(viewsets.ModelViewSet):
    """Create/read agreements; detail includes computed arrears and balance."""
    serializer_class = slz.OwnershipAgreementSerializer
    permission_classes = [StaffWritePermission]
    http_method_names = ["get", "post", "patch", "head", "options"]  # never delete

    def get_serializer_class(self):
        if self.action == "create":
            return slz.OwnershipAgreementCreateSerializer
        return slz.OwnershipAgreementSerializer

    def get_queryset(self):
        qs = OwnershipAgreement.objects.select_related("rider", "motorcycle")
        params = self.request.query_params
        if status_filter := params.get("status"):
            qs = qs.filter(status=status_filter)
        if rider := params.get("rider"):
            qs = qs.filter(rider_id=rider)
        if motorcycle := params.get("motorcycle"):
            qs = qs.filter(motorcycle_id=motorcycle)
        if params.get("overdue") == "true":
            qs = qs.filter(
                instalments__status=WeeklyInstalment.Status.OVERDUE,
            ).distinct()
        return qs

    def perform_create(self, serializer):
        with transaction.atomic():
            agreement = serializer.save()
            try:
                generate_instalments(agreement)
            except DjangoValidationError as exc:
                raise ValidationError(str(exc))
            AuditLog.objects.create(
                action="agreement_created", entity_type="OwnershipAgreement",
                entity_id=agreement.pk, actor=self.request.user,
                details={"rider_id": agreement.rider_id, "motorcycle_id": agreement.motorcycle_id,
                         "total_price": str(agreement.total_price)},
            )

    def perform_update(self, serializer):
        """Edits are only allowed while the agreement has no payment history."""
        agreement = self.get_object()
        if agreement.payments.exists():
            raise ValidationError(
                "This agreement already has payments on record; its terms can no longer be edited."
            )
        old_status = agreement.status
        with transaction.atomic():
            agreement = serializer.save()
            generate_instalments(agreement)
            if agreement.status != old_status:
                AuditLog.objects.create(
                    action="agreement_status_changed", entity_type="OwnershipAgreement",
                    entity_id=agreement.pk, actor=self.request.user,
                    details={"from": old_status, "to": agreement.status},
                )

    @action(detail=True, methods=["get"])
    def instalments(self, request, pk=None):
        agreement = self.get_object()
        data = slz.InstalmentSerializer(agreement.instalments.all(), many=True).data
        return Response(data)

    @action(detail=True, methods=["get", "post"])
    def payments(self, request, pk=None):
        """GET: receipt history for this agreement. POST: record one payment."""
        agreement = self.get_object()
        if request.method == "GET":
            data = slz.PaymentSerializer(agreement.payments.all(), many=True).data
            return Response(data)
        serializer = slz.PaymentCreateSerializer(data=request.data, context={"agreement": agreement})
        serializer.is_valid(raise_exception=True)
        try:
            payment = record_payment(
                agreement=agreement,
                amount=serializer.validated_data["amount"],
                paid_at=serializer.validated_data["paid_at"],
                method=serializer.validated_data["method"],
                receipt_number=serializer.validated_data["receipt_number"].strip(),
                reference=serializer.validated_data.get("reference", "").strip(),
                created_by=request.user if request.user.is_authenticated else None,
            )
        except IntegrityError:
            return Response(
                {"detail": "This receipt number has already been used."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(slz.PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="transfer-approval")
    def transfer_approval(self, request, pk=None):
        """Explicit legal handover; nothing else ever grants ownership."""
        agreement = self.get_object()
        if agreement.legal_transfer_approved_at is not None:
            raise ValidationError("Legal transfer was already approved for this agreement.")
        serializer = slz.LegalTransferApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            approve_legal_transfer(
                agreement, actor=request.user,
                approval_date=serializer.validated_data["approval_date"],
            )
        except DjangoValidationError as exc:
            return django_errors_to_response(exc)
        return Response(slz.OwnershipAgreementSerializer(agreement).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        agreement = self.get_object()
        if agreement.status == OwnershipAgreement.Status.CANCELLED:
            raise ValidationError("This agreement is already cancelled.")
        old_status = agreement.status
        agreement.status = OwnershipAgreement.Status.CANCELLED
        agreement.save(update_fields=["status"])
        AuditLog.objects.create(
            action="agreement_cancelled", entity_type="OwnershipAgreement",
            entity_id=agreement.pk, actor=request.user,
            details={"previous_status": old_status,
                     "remaining_balance": str(calculate_remaining_balance(agreement))},
        )
        return Response(slz.OwnershipAgreementSerializer(agreement).data)


class PaymentViewSet(viewsets.GenericViewSet):
    """Payment list/detail plus the reversal action."""
    serializer_class = slz.PaymentSerializer
    permission_classes = [StaffWritePermission]
    http_method_names = ["get", "post", "head", "options"]  # no PATCH/DELETE, ever

    def get_queryset(self):
        qs = Payment.objects.select_related("created_by").prefetch_related("allocations__instalment")
        params = self.request.query_params
        if agreement := params.get("agreement"):
            qs = qs.filter(agreement_id=agreement)
        if payment_status := params.get("status"):
            qs = qs.filter(status=payment_status)
        if method := params.get("method"):
            qs = qs.filter(method=method)
        return qs

    def list(self, request, *args, **kwargs):
        data = self.serializer_class(self.get_queryset(), many=True).data
        return Response(data)

    def retrieve(self, request, *args, **kwargs):
        payment = self.get_object()
        return Response(self.serializer_class(payment).data)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        """Soft reversal: keeps the receipt, reverses its effect, writes the audit log."""
        payment = self.get_object()
        serializer = slz.ReversePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reverse_payment(payment, actor=request.user, reason=serializer.validated_data["reason"])
        except DjangoValidationError as exc:
            return django_errors_to_response(exc)
        return Response(self.serializer_class(payment).data)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = slz.AuditLogSerializer
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    http_method_names = ["get", "head", "options"]

    def get_queryset(self):
        qs = AuditLog.objects.all()
        params = self.request.query_params
        if action_filter := params.get("action"):
            qs = qs.filter(action=action_filter)
        if entity := params.get("entity_type"):
            qs = qs.filter(entity_type=entity)
        if entity_id := params.get("entity_id"):
            qs = qs.filter(entity_id=entity_id)
        return qs


class ArrearsReportView(APIView):
    """A money snapshot of every open agreement, as of a given date."""

    def get(self, request):
        as_of_raw = request.query_params.get("as_of")
        if as_of_raw:
            try:
                as_of = date.fromisoformat(as_of_raw)
            except ValueError:
                raise ValidationError({"as_of": "Use YYYY-MM-DD format."})
        else:
            as_of = timezone.localdate()
        agreements = OwnershipAgreement.objects.filter(
            status__in=[OwnershipAgreement.Status.ACTIVE, OwnershipAgreement.Status.FINANCIALLY_COMPLETED]
        ).select_related("rider", "motorcycle")
        rows = []
        for agreement in agreements:
            rows.append({
                "agreement_id": agreement.pk,
                "rider": agreement.rider.full_name,
                "motorcycle": agreement.motorcycle.registration_number,
                "status": agreement.status,
                "total_arrears": str(calculate_arrears(agreement, as_of)),
                "remaining_balance": str(calculate_remaining_balance(agreement)),
                "overdue_instalments": agreement.instalments.filter(
                    status=WeeklyInstalment.Status.OVERDUE,
                ).count(),
            })
        total_arrears = sum((Decimal(row["total_arrears"]) for row in rows), Decimal("0.00"))
        return Response({"as_of": as_of.isoformat(), "total_arrears": str(total_arrears), "agreements": rows})


class CollectionsReportView(APIView):
    """Cash and Mobile Money received within a date range, by method."""

    def get(self, request):
        params = request.query_params
        today = timezone.localdate()
        try:
            date_from = date.fromisoformat(params.get("from")) if params.get("from") else today.replace(day=1)
            date_to = date.fromisoformat(params.get("to")) if params.get("to") else today
        except ValueError:
            raise ValidationError({"detail": "from/to must be YYYY-MM-DD dates."})
        payments = Payment.objects.filter(
            status=Payment.Status.POSTED,
            paid_at__date__gte=date_from,
            paid_at__date__lte=date_to,
        )
        by_method = payments.values("method").annotate(total=Sum("amount"), count=Count("id"))
        rows = [{"method": row["method"], "total": str(row["total"]), "count": row["count"]} for row in by_method]
        grand_total = sum((Decimal(row["total"]) for row in rows), Decimal("0.00"))
        return Response({
            "from": date_from.isoformat(), "to": date_to.isoformat(),
            "grand_total": str(grand_total), "by_method": rows,
        })
