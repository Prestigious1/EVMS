from django.urls import path

from reports import views

app_name = "reports"

urlpatterns = [
    path("", views.admin_reports_dashboard, name="dashboard"),
    path("centre/", views.report_centre, name="report_centre"),
    path("export/reservations.csv", views.export_reservations_csv, name="export_reservations_csv"),
    path("export/payments.csv", views.export_payments_csv, name="export_payments_csv"),
    path("export/dashboard.pdf", views.export_dashboard_pdf, name="export_dashboard_pdf"),
    path("export/users/csv/", views.export_users_csv, name="export_users_csv"),
    path("export/logs/csv/", views.export_logs_csv, name="export_logs_csv"),
    path("export/<str:report_type>.xlsx", views.export_report_xlsx, name="export_report_xlsx"),
]
