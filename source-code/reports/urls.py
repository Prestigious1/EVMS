from django.urls import path

from reports import views

app_name = "reports"

urlpatterns = [
    # New Entry Point
    path("", views.reports_home, name="reports_home"),

    # Dashboards
    path("dashboard/", views.admin_reports_dashboard, name="dashboard"),  # Legacy preserved
    path("dashboard/admin/", views.dashboard_admin, name="dashboard_admin"),
    path("dashboard/ventures/", views.dashboard_ventures, name="dashboard_ventures"),
    path("dashboard/facility/", views.dashboard_facility, name="dashboard_facility"),
    path("dashboard/bursary/", views.dashboard_bursary, name="dashboard_bursary"),

    # Report Modules
    path("centre/", views.report_centre, name="report_centre"), # Legacy preserved
    path("bookings/", views.report_bookings, name="report_bookings"),
    path("payments/", views.report_payments, name="report_payments"),
    path("revenue/", views.report_revenue, name="report_revenue"),
    path("coupons/", views.report_coupons, name="report_coupons"),
    path("damage/", views.report_damage, name="report_damage"),
    path("inspections/", views.report_inspections, name="report_inspections"),
    path("penalties/", views.report_penalties, name="report_penalties"),
    path("halls/", views.report_halls, name="report_halls"),
    path("applicants/", views.report_applicants, name="report_applicants"),
    path("management/", views.report_management, name="report_management"),
    path("notifications/", views.report_notifications, name="report_notifications"),
    path("communications/", views.report_communications, name="report_communications"),
    path("audit/", views.report_audit, name="report_audit"),
    path("system-usage/", views.report_system_usage, name="report_system_usage"),

    # Universal Export
    path("export/", views.universal_export, name="universal_export"),

    # Legacy Exports (preserved for backward compatibility)
    path("export/reservations.csv", views.export_reservations_csv, name="export_reservations_csv"),
    path("export/payments.csv", views.export_payments_csv, name="export_payments_csv"),
    path("export/dashboard.pdf", views.export_dashboard_pdf, name="export_dashboard_pdf"),
    path("export/users/csv/", views.export_users_csv, name="export_users_csv"),
    path("export/logs/csv/", views.export_logs_csv, name="export_logs_csv"),
    path("export/<str:report_type>.xlsx", views.export_report_xlsx, name="export_report_xlsx"),
]
