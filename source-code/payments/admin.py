from django.contrib import admin

from payments.models import Coupon, Payment


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "discount_type", "value", "is_active", "owner_department", "valid_until", "created_by", "created_at")
    list_filter = ("discount_type", "is_active", "owner_department", "valid_until")
    search_fields = ("code", "name", "description")
    filter_horizontal = ("applicable_halls",)
    readonly_fields = ("created_by", "created_at")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "reservation",
        "damage_report",
        "penalty",
        "user",
        "amount",
        "currency",
        "status",
        "provider",
        "payment_method",
        "paystack_reference",
        "transaction_reference",
        "created_at",
    )
    list_filter = ("status", "provider", "payment_method", "created_at")
    search_fields = ("reservation__booking_reference", "user__email", "paystack_reference", "transaction_reference", "penalty__title")

