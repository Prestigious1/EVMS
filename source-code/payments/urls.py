from django.urls import path

from payments import views


app_name = "payments"

urlpatterns = [
    path("", views.my_payments, name="my_payments"),
    path("verify/", views.paystack_verify_redirect, name="paystack_verify_redirect"),
    path("success/", views.payment_success, name="payment_success"),
    path("failed/", views.payment_failed, name="payment_failed"),
    path("reservation/<str:booking_reference>/start/", views.start_reservation_payment, name="start_reservation_payment"),
    path("penalty/<int:penalty_id>/start/", views.start_penalty_payment, name="start_penalty_payment"),
    path("damage/<int:damage_id>/start/", views.start_damage_payment, name="start_damage_payment"),
    path("paystack/callback/", views.paystack_callback, name="paystack_callback"),
    path("api/paystack/initialize/reservation/<int:reservation_id>/", views.paystack_initialize_reservation, name="paystack_initialize_reservation"),
    path("api/paystack/verify/", views.paystack_verify, name="paystack_verify"),
    path("<int:pk>/", views.payment_detail, name="payment_detail"),
    path("<int:pk>/invoice.pdf", views.invoice_pdf, name="invoice_pdf"),
    path("record-manual/", views.record_manual_payment, name="record_manual_payment"),
    # Enterprise receipt (system-generated official financial document)
    path("receipt/<str:booking_reference>/", views.enterprise_receipt_pdf, name="enterprise_receipt_pdf"),
    # Bursary payment review (redesigned full review page)
    path("bursary-review/<str:booking_reference>/", views.bursary_payment_review, name="bursary_payment_review"),
    # Coupon management
    path("coupons/", views.coupon_list, name="coupon_list"),
    path("coupons/create/", views.coupon_create, name="coupon_create"),
    path("coupons/<int:pk>/edit/", views.coupon_edit, name="coupon_edit"),
    path("coupons/<int:pk>/delete/", views.coupon_delete, name="coupon_delete"),
    path("coupons/<int:pk>/toggle/", views.coupon_toggle, name="coupon_toggle"),
]
