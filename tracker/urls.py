"""API routes for BodaTrack."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("riders", views.RiderViewSet, basename="rider")
router.register("motorcycles", views.MotorcycleViewSet, basename="motorcycle")
router.register("agreements", views.AgreementViewSet, basename="agreement")
router.register("payments", views.PaymentViewSet, basename="payment")
router.register("audit", views.AuditLogViewSet, basename="audit")

urlpatterns = [
    path("", include(router.urls)),
    # Session auth helpers for the React frontend.
    path("auth/csrf/", views.CsrfTokenView.as_view(), name="auth-csrf"),
    path("auth/login/", views.LoginView.as_view(), name="auth-login"),
    path("auth/register/", views.RegisterView.as_view(), name="auth-register"),
    path("auth/logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/me/", views.MeView.as_view(), name="auth-me"),
    # Reports
    path("reports/arrears/", views.ArrearsReportView.as_view(), name="report-arrears"),
    path("reports/collections/", views.CollectionsReportView.as_view(), name="report-collections"),
]
