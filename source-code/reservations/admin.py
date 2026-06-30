from django.contrib import admin
from django.contrib.admin.widgets import AdminTextareaWidget
from django.db import models

from reservations.models import (
    BookingLog,
    BookingStatusHistory,
    DamageReport,
    HallInspection,
    Penalty,
    Reservation,
    ReservationDocument,
    ReservationMessage,
    PaymentAuthorization,
    DeadlineExtensionLog,
    CouponActionLog,
    InspectionReminder,
    VenturesPenaltyRecord,
)

try:
    from django_ckeditor_5.widgets import CKEditor5Widget
except Exception:  # pragma: no cover
    CKEditor5Widget = AdminTextareaWidget


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = (
        "booking_reference",
        "booking_date",
        "start_time",
        "end_time",
        "hall",
        "purpose",
        "status",
        "user",
        "total_cost",
        "created_at",
    )
    list_filter = ("status", "purpose", "booking_date", "hall")
    search_fields = ("booking_reference", "user__email", "user__username", "hall__name")
    readonly_fields = ("booking_reference", "created_at")
    actions = ["approve", "reject", "mark_completed", "mark_cancelled"]

    @admin.action(description="Approve selected reservations (approve for payment)")
    def approve(self, request, queryset):
        queryset.update(status="APPROVED_PAYMENT")

    @admin.action(description="Reject selected reservations")
    def reject(self, request, queryset):
        queryset.update(status="REJECTED")

    @admin.action(description="Mark selected reservations as completed")
    def mark_completed(self, request, queryset):
        queryset.update(status="COMPLETED")

    @admin.action(description="Cancel selected reservations")
    def mark_cancelled(self, request, queryset):
        queryset.update(status="CANCELLED")


@admin.register(DamageReport)
class DamageReportAdmin(admin.ModelAdmin):
    list_display = ("user", "reservation", "amount", "is_paid", "is_forgiven", "created_at")
    list_filter = ("is_paid", "is_forgiven", "created_at")
    search_fields = ("user__email", "reservation__booking_reference")
    actions = ["mark_paid", "forgive"]

    @admin.action(description="Mark selected damages as paid")
    def mark_paid(self, request, queryset):
        queryset.update(is_paid=True)

    @admin.action(description="Forgive selected damages (clears blocking)")
    def forgive(self, request, queryset):
        queryset.update(is_forgiven=True, is_paid=False)


@admin.register(Penalty)
class PenaltyAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "reservation", "amount", "is_paid", "is_forgiven", "created_at")
    list_filter = ("is_paid", "is_forgiven", "created_at")
    search_fields = ("title", "user__email", "reservation__booking_reference")
    actions = ["mark_paid", "forgive"]
    formfield_overrides = {
        models.TextField: {"widget": CKEditor5Widget(config_name="extends")},
    }

    @admin.action(description="Mark selected penalties as paid")
    def mark_paid(self, request, queryset):
        queryset.update(is_paid=True)

    @admin.action(description="Forgive selected penalties")
    def forgive(self, request, queryset):
        queryset.update(is_forgiven=True, is_paid=False)


@admin.register(BookingStatusHistory)
class BookingStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("reservation", "previous_status", "new_status", "changed_by", "timestamp")
    list_filter = ("new_status", "timestamp")
    search_fields = ("reservation__booking_reference",)
    readonly_fields = ("reservation", "previous_status", "new_status", "changed_by", "timestamp")


@admin.register(BookingLog)
class BookingLogAdmin(admin.ModelAdmin):
    list_display = ("reservation", "actor", "action", "timestamp")
    list_filter = ("timestamp",)
    search_fields = ("reservation__booking_reference", "action")
    readonly_fields = ("reservation", "actor", "action", "details", "timestamp")


@admin.register(ReservationMessage)
class ReservationMessageAdmin(admin.ModelAdmin):
    list_display = ("reservation", "sender", "is_staff_note", "created_at")
    list_filter = ("is_staff_note", "created_at")
    search_fields = ("reservation__booking_reference", "sender__email", "content")
    readonly_fields = ("reservation", "sender", "created_at")


@admin.register(ReservationDocument)
class ReservationDocumentAdmin(admin.ModelAdmin):
    list_display = ("reservation", "document_type", "version", "uploaded_by", "uploaded_at")
    list_filter = ("document_type", "uploaded_at")
    search_fields = ("reservation__booking_reference",)
    readonly_fields = ("reservation", "document_type", "version", "uploaded_by", "uploaded_at")


@admin.register(HallInspection)
class HallInspectionAdmin(admin.ModelAdmin):
    list_display = ("reservation", "inspector", "result", "inspected_at")
    list_filter = ("result", "inspected_at")
    search_fields = ("reservation__booking_reference", "inspector__email", "notes")
    readonly_fields = ("reservation", "inspector", "result", "inspected_at")


@admin.register(PaymentAuthorization)
class PaymentAuthorizationAdmin(admin.ModelAdmin):
    list_display = ("reservation", "authorized_by", "total_amount", "payment_deadline", "deadline_type", "is_expired", "authorized_at")
    list_filter = ("deadline_type", "is_expired", "authorized_at")
    search_fields = ("reservation__booking_reference",)


@admin.register(DeadlineExtensionLog)
class DeadlineExtensionLogAdmin(admin.ModelAdmin):
    list_display = ("authorization", "actor", "old_deadline", "new_deadline", "created_at")
    search_fields = ("authorization__reservation__booking_reference",)


@admin.register(CouponActionLog)
class CouponActionLogAdmin(admin.ModelAdmin):
    list_display = ("reservation", "action", "coupon_code", "actor", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("reservation__booking_reference", "coupon_code")


@admin.register(InspectionReminder)
class InspectionReminderAdmin(admin.ModelAdmin):
    list_display = ("reservation", "sent_at")
    search_fields = ("reservation__booking_reference",)


@admin.register(VenturesPenaltyRecord)
class VenturesPenaltyRecordAdmin(admin.ModelAdmin):
    list_display = ("reservation", "penalty", "penalty_type", "created_at")
    list_filter = ("penalty_type", "created_at")
    search_fields = ("reservation__booking_reference",)
