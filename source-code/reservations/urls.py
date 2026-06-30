from django.urls import path

from reservations import views

app_name = "reservations"

urlpatterns = [
    path("my/", views.my_reservations, name="my_reservations"),
    path("create/<int:hall_id>/", views.create_reservation, name="create"),
    path("availability/", views.availability_api, name="availability_api"),
    path("receipt/<str:booking_reference>/", views.receipt_pdf, name="receipt_pdf"),
    path("verify/<str:booking_reference>/", views.verify_reservation, name="verify_reservation"),
    path("calendar/", views.calendar_view, name="calendar"),
    path("calendar/events/", views.calendar_events, name="calendar_events"),

    # Workflow dashboards
    path("ventures/", views.ventures_dashboard, name="ventures_dashboard"),
    path("facility/", views.facility_dashboard, name="facility_dashboard"),
    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("bursary/", views.bursary_dashboard, name="bursary_dashboard"),
    path("bursary/audit-logs/", views.bursary_audit_logs, name="bursary_audit_logs"),

    # Workflow action endpoints
    path("ventures/action/<str:booking_reference>/", views.ventures_action, name="ventures_action"),
    path("facility/action/<str:booking_reference>/", views.facility_action, name="facility_action"),
    path("bursary/action/<str:booking_reference>/", views.bursary_action, name="bursary_action"),
    path("admin/action/<str:booking_reference>/", views.admin_booking_action, name="admin_booking_action"),

    # Core detail & interaction views
    path("detail/<str:booking_reference>/", views.reservation_detail, name="detail"),
    path("upload-document/<str:booking_reference>/", views.upload_document, name="upload_document"),
    path("cancel/<str:booking_reference>/", views.cancel_reservation, name="cancel"),

    # Messaging
    path("message/<str:booking_reference>/", views.add_message, name="add_message"),
    path("thread/message/<str:booking_reference>/", views.add_thread_message, name="add_thread_message"),

    # Payment proof submission (applicant)
    path("payment-proof/<str:booking_reference>/", views.submit_payment_proof, name="submit_payment_proof"),
    path("damage-payment-proof/<str:booking_reference>/", views.submit_damage_payment_proof, name="submit_damage_payment_proof"),

    # Inspection
    path("inspection/<str:booking_reference>/", views.record_inspection, name="record_inspection"),
    path("inspection-report/<str:booking_reference>/", views.record_inspection_report, name="record_inspection_report"),

    # Penalty management
    path("penalties/", views.penalty_list, name="penalty_list"),
    path("penalty/<int:penalty_id>/forgive/", views.forgive_penalty, name="forgive_penalty"),
    path("ventures/penalty/create/<str:booking_reference>/", views.ventures_create_penalty_view, name="ventures_create_penalty"),

    # Coupon validation & application
    path("coupon/validate/", views.validate_coupon, name="validate_coupon"),
    path("coupon/apply/<str:booking_reference>/", views.apply_coupon, name="apply_coupon"),

    # Payment Authorization (NEW)
    path("payment-auth/<str:booking_reference>/", views.payment_authorization_page, name="payment_authorization"),
    path("payment-auth/<str:booking_reference>/submit/", views.submit_payment_authorization, name="submit_payment_authorization"),
    path("payment-auth/<str:booking_reference>/extend-deadline/", views.extend_payment_deadline, name="extend_payment_deadline"),

    # Admin forgiveness
    path("admin/forgive/<str:booking_reference>/", views.admin_forgive_liability_view, name="admin_forgive_liability"),

    # Internal Reservations
    path("internal/", views.internal_list, name="internal_list"),
    path("internal/create/", views.internal_create, name="internal_create"),
    path("internal/<str:reference>/edit/", views.internal_edit, name="internal_edit"),
    path("internal/<str:reference>/action/", views.internal_action, name="internal_action"),
]
