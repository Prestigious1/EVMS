import csv
import json
from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum, Q, Avg
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from core.services import can_view_reports
from payments.models import Payment, PaymentStatus
from reservations.models import Reservation, ReservationStatus, DamageReport
from reports.pdf import build_reports_dashboard_pdf
from hall.models import Hall, HallBlock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _date_filtered_qs(request, qs, field_name: str):
    period = (request.GET.get("period") or "monthly").lower()
    today = timezone.localdate()
    start = None
    end = None
    if period == "daily":
        start, end = today, today
    elif period == "weekly":
        start = today - timedelta(days=today.weekday())
        end = today
    elif period == "monthly":
        start = today.replace(day=1)
        end = today
    elif period == "quarterly":
        quarter_month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=quarter_month, day=1)
        end = today
    elif period == "yearly":
        start = today.replace(month=1, day=1)
        end = today
    elif period == "custom":
        try:
            start = datetime.strptime(request.GET.get("start_date") or "", "%Y-%m-%d").date()
            end = datetime.strptime(request.GET.get("end_date") or "", "%Y-%m-%d").date()
        except Exception:
            start = end = None
    if start and end:
        return qs.filter(**{f"{field_name}__gte": start, f"{field_name}__lte": end}), start, end, period
    return qs, None, None, period


def _xlsx_response(filename: str):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    resp = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return wb, ws, resp


def _get_role_scope(user):
    """Return the analytics scope string for this user."""
    role = getattr(user, "role", None) or ""
    if getattr(user, "is_superuser", False) or role in ("ADMIN", "STAFF"):
        return "full"
    if role == "FACILITY":
        return "facility"
    if role == "VENTURES":
        return "ventures"
    if role == "BURSARY":
        return "bursary"
    return "none"


# ---------------------------------------------------------------------------
# Analytics Dashboard
# ---------------------------------------------------------------------------

@login_required
def admin_reports_dashboard(request):
    if not can_view_reports(request.user):
        return HttpResponse(status=403)

    scope = _get_role_scope(request.user)
    today = timezone.localdate()
    start_week = today - timedelta(days=today.weekday())
    start_month = today.replace(day=1)
    start_year = today.replace(month=1, day=1)

    qs = Reservation.objects.all()
    qs, start_date, end_date, period = _date_filtered_qs(request, qs, "booking_date")

    paid_payments = Payment.objects.filter(status=PaymentStatus.PAID)

    # ------------------------------------------------------------------
    # OVERVIEW — all scopes
    # ------------------------------------------------------------------
    total_bookings      = qs.count()
    active_bookings     = qs.exclude(status__in=["CANCELLED", "REJECTED", "COMPLETED", "CLOSED"]).count()
    completed_bookings  = qs.filter(status="COMPLETED").count()
    cancelled_bookings  = qs.filter(status__in=["CANCELLED", "REJECTED"]).count()
    pending_reviews     = qs.filter(status__in=["SUBMITTED", "UNDER_REVIEW"]).count()
    halls_total         = Hall.objects.filter(is_active=True).count()

    # ------------------------------------------------------------------
    # REVENUE  (Ventures / Admin / Bursary)
    # ------------------------------------------------------------------
    revenue_total   = paid_payments.aggregate(total=Sum("amount"))["total"] or 0
    booking_revenue = paid_payments.filter(reservation__isnull=False).aggregate(total=Sum("amount"))["total"] or 0
    penalty_revenue = paid_payments.filter(penalty__isnull=False).aggregate(total=Sum("amount"))["total"] or 0
    damage_revenue  = paid_payments.filter(damage_report__isnull=False).aggregate(total=Sum("amount"))["total"] or 0
    outstanding_payments = Reservation.objects.filter(
        status__in=["APPROVED_PAYMENT", "PAYMENT_PENDING"]
    ).count()

    # Revenue by month (current year)
    revenue_by_month = (
        paid_payments.filter(created_at__year=today.year)
        .values("created_at__month")
        .annotate(total=Sum("amount"))
        .order_by("created_at__month")
    )
    revenue_labels = [str(r["created_at__month"]).zfill(2) for r in revenue_by_month]
    revenue_totals = [float(r["total"] or 0) for r in revenue_by_month]

    # ------------------------------------------------------------------
    # BOOKINGS  (Ventures / Admin)
    # ------------------------------------------------------------------
    bookings_by_month = (
        Reservation.objects.filter(booking_date__year=today.year)
        .values("booking_date__month")
        .annotate(total=Count("id"))
        .order_by("booking_date__month")
    )
    booking_month_labels = [str(r["booking_date__month"]).zfill(2) for r in bookings_by_month]
    booking_month_counts = [r["total"] for r in bookings_by_month]

    status_dist = qs.values("status").annotate(total=Count("id")).order_by("status")
    status_labels = [s["status"] for s in status_dist]
    status_counts = [s["total"] for s in status_dist]

    # Purpose distribution
    purpose_dist = qs.values("purpose").annotate(total=Count("id")).order_by("-total")[:8]
    purpose_labels = [p["purpose"] for p in purpose_dist]
    purpose_counts = [p["total"] for p in purpose_dist]

    # ------------------------------------------------------------------
    # HALL UTILISATION  (Facility / Admin)
    # ------------------------------------------------------------------
    most_used = (
        qs.values("hall__name")
        .annotate(total=Count("id"))
        .order_by("-total")[:10]
    )

    # Peak booking hours
    peak_hours = (
        qs.values("start_time__hour")
        .annotate(total=Count("id"))
        .order_by("-total")[:8]
    )
    peak_labels = [str(row["start_time__hour"]).zfill(2) + ":00" for row in peak_hours]
    peak_counts = [row["total"] for row in peak_hours]

    # Hall utilisation: bookings per hall (top 8)
    hall_usage = (
        Reservation.objects.values("hall__name")
        .annotate(total=Count("id"))
        .order_by("-total")[:8]
    )
    hall_usage_labels = [h["hall__name"] for h in hall_usage]
    hall_usage_counts = [h["total"] for h in hall_usage]

    # ------------------------------------------------------------------
    # PAYMENTS  (Bursary / Ventures / Admin)
    # ------------------------------------------------------------------
    payment_method_dist = (
        paid_payments.values("payment_method")
        .annotate(total=Count("id"))
        .order_by("-total")
    )
    pay_method_labels = [p["payment_method"] or "UNKNOWN" for p in payment_method_dist]
    pay_method_counts = [p["total"] for p in payment_method_dist]

    daily_stats = {
        "daily":   qs.filter(booking_date=today).count(),
        "weekly":  qs.filter(booking_date__gte=start_week, booking_date__lte=today).count(),
        "monthly": qs.filter(booking_date__gte=start_month, booking_date__lte=today).count(),
        "yearly":  qs.filter(booking_date__gte=start_year, booking_date__lte=today).count(),
    }

    # ------------------------------------------------------------------
    # DAMAGE RECORDS  (Facility / Admin)
    # ------------------------------------------------------------------
    try:
        damage_total    = DamageReport.objects.count()
        damage_paid     = DamageReport.objects.filter(is_paid=True).count()
        damage_pending  = DamageReport.objects.filter(is_paid=False, is_forgiven=False).count()
        damage_recovery = round((damage_paid / damage_total * 100), 1) if damage_total else 0
    except Exception:
        damage_total = damage_paid = damage_pending = 0
        damage_recovery = 0

    # ------------------------------------------------------------------
    # COUPONS  (Ventures / Admin)
    # ------------------------------------------------------------------
    try:
        from payments.models import Coupon
        coupons_total  = Coupon.objects.count()
        coupons_active = Coupon.objects.filter(is_active=True).count()
        coupons_used   = Reservation.objects.exclude(coupon_code="").exclude(coupon_code__isnull=True).count()
    except Exception:
        coupons_total = coupons_active = coupons_used = 0

    # ------------------------------------------------------------------
    # USERS  (Admin only)
    # ------------------------------------------------------------------
    users_total = users_active = users_new_month = 0
    if scope == "full":
        from users.models import User
        users_total      = User.objects.count()
        users_active     = User.objects.filter(is_active=True, is_blocked=False).count()
        users_new_month  = User.objects.filter(date_joined__date__gte=start_month).count()

    return render(
        request,
        "reports/dashboard.html",
        {
            "scope": scope,
            # Overview
            "total_bookings":      total_bookings,
            "active_bookings":     active_bookings,
            "completed_bookings":  completed_bookings,
            "cancelled_bookings":  cancelled_bookings,
            "pending_reviews":     pending_reviews,
            "halls_total":         halls_total,
            "daily_stats":         daily_stats,
            # Revenue
            "revenue_total":       revenue_total,
            "booking_revenue":     booking_revenue,
            "penalty_revenue":     penalty_revenue,
            "damage_revenue":      damage_revenue,
            "outstanding_payments": outstanding_payments,
            "revenue_labels":      revenue_labels,
            "revenue_totals":      revenue_totals,
            # Bookings
            "booking_month_labels": booking_month_labels,
            "booking_month_counts": booking_month_counts,
            "status_labels":       status_labels,
            "status_counts":       status_counts,
            "purpose_labels":      purpose_labels,
            "purpose_counts":      purpose_counts,
            # Hall Utilisation
            "most_used":           most_used,
            "hall_usage_labels":   hall_usage_labels,
            "hall_usage_counts":   hall_usage_counts,
            "peak_labels":         peak_labels,
            "peak_counts":         peak_counts,
            # Payments
            "pay_method_labels":   pay_method_labels,
            "pay_method_counts":   pay_method_counts,
            # Damage
            "damage_total":        damage_total,
            "damage_paid":         damage_paid,
            "damage_pending":      damage_pending,
            "damage_recovery":     damage_recovery,
            # Coupons
            "coupons_total":       coupons_total,
            "coupons_active":      coupons_active,
            "coupons_used":        coupons_used,
            # Users
            "users_total":         users_total,
            "users_active":        users_active,
            "users_new_month":     users_new_month,
            # Filter state
            "period":     period,
            "start_date": start_date,
            "end_date":   end_date,
            "now":        timezone.localtime(),
        },
    )


# ---------------------------------------------------------------------------
# Report Centre
# ---------------------------------------------------------------------------

@login_required
def report_centre(request):
    if not can_view_reports(request.user):
        return HttpResponse(status=403)

    scope = _get_role_scope(request.user)
    today = timezone.localdate()
    month_start = today.replace(day=1)

    # Determine visible categories by role
    all_categories = {
        "bookings":      ("Booking Reports",         "bi-calendar-check", "#60a5fa",  ["full", "ventures", "facility"]),
        "financial":     ("Financial Reports",        "bi-cash-stack",     "#facc15",  ["full", "ventures", "bursary"]),
        "facility":      ("Facility Reports",         "bi-building-gear",  "#34d399",  ["full", "facility"]),
        "utilisation":   ("Hall Utilisation Reports", "bi-bar-chart-fill", "#818cf8",  ["full", "facility"]),
        "payments":      ("Payment Reports",          "bi-credit-card",    "#fbbf24",  ["full", "ventures", "bursary"]),
        "damage":        ("Damage Reports",           "bi-tools",          "#f87171",  ["full", "facility", "bursary"]),
        "coupons":       ("Coupon Reports",           "bi-ticket-perforated", "#c084fc", ["full", "ventures"]),
        "audit":         ("Audit Reports",            "bi-journal-check",  "#94a3b8",  ["full"]),
        "communication": ("Communication Reports",    "bi-chat-dots",      "#60a5fa",  ["full", "ventures"]),
        "inspection":    ("Inspection Reports",       "bi-clipboard-check","#fbbf24",  ["full", "facility"]),
    }
    visible_categories = {
        k: v for k, v in all_categories.items()
        if scope in v[3]
    }

    active_cat = request.GET.get("category", list(visible_categories.keys())[0] if visible_categories else "bookings")
    search_q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "")
    period = request.GET.get("period", "monthly")
    qs, start_date, end_date, period = _date_filtered_qs(
        request, Reservation.objects.select_related("hall", "user"), "booking_date"
    )

    # Apply search
    if search_q:
        from django.db.models import Q as DQ
        qs = qs.filter(
            DQ(booking_reference__icontains=search_q) |
            DQ(event_name__icontains=search_q) |
            DQ(hall__name__icontains=search_q) |
            DQ(user__email__icontains=search_q)
        )
    if status_filter:
        qs = qs.filter(status=status_filter)

    # Summary cards
    summary = {
        "total": qs.count(),
        "completed": qs.filter(status="COMPLETED").count(),
        "cancelled": qs.filter(status__in=["CANCELLED", "REJECTED"]).count(),
        "revenue": Payment.objects.filter(
            status=PaymentStatus.PAID,
            created_at__date__gte=month_start
        ).aggregate(total=Sum("amount"))["total"] or 0,
    }

    return render(request, "reports/report_centre.html", {
        "scope": scope,
        "visible_categories": visible_categories,
        "active_cat": active_cat,
        "reservations": qs.order_by("-booking_date")[:200],
        "search_q": search_q,
        "status_filter": status_filter,
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "summary": summary,
        "ReservationStatus": ReservationStatus,
    })


# ---------------------------------------------------------------------------
# CSV Exports
# ---------------------------------------------------------------------------

@login_required
def export_reservations_csv(request):
    if not can_view_reports(request.user):
        return HttpResponse(status=403)

    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="reservations.csv"'
    writer = csv.writer(resp)
    writer.writerow(["reference", "user", "hall", "date", "start_time", "end_time", "purpose", "status", "total_cost"])

    for r in Reservation.objects.select_related("user", "hall").order_by("-created_at")[:5000]:
        writer.writerow([
            r.booking_reference,
            getattr(r.user, "email", ""),
            r.hall.name,
            r.booking_date,
            r.start_time,
            r.end_time,
            r.purpose,
            r.status,
            r.total_cost,
        ])

    return resp


@login_required
def export_payments_csv(request):
    if not can_view_reports(request.user):
        return HttpResponse(status=403)

    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="payments.csv"'
    writer = csv.writer(resp)
    writer.writerow(["id", "user", "reservation_ref", "amount", "currency", "status", "method", "provider", "reference", "created_at"])

    qs = Payment.objects.select_related("user", "reservation").order_by("-created_at")[:5000]
    for p in qs:
        writer.writerow([
            p.id,
            getattr(p.user, "email", ""),
            getattr(p.reservation, "booking_reference", ""),
            p.amount,
            p.currency,
            p.status,
            p.payment_method,
            getattr(p, "provider", ""),
            p.paystack_reference or p.transaction_reference,
            p.created_at,
        ])
    return resp


@login_required
def export_dashboard_pdf(request):
    if not can_view_reports(request.user):
        return HttpResponse(status=403)

    pdf_bytes = build_reports_dashboard_pdf(request=request)
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = 'attachment; filename="reports_dashboard.pdf"'
    return resp


@login_required
def export_report_xlsx(request, report_type: str):
    if not can_view_reports(request.user):
        return HttpResponse(status=403)

    if report_type == "hall-usage":
        qs = Reservation.objects.all()
        qs, *_ = _date_filtered_qs(request, qs, "booking_date")
        rows = qs.values("hall__name").annotate(total=Count("id")).order_by("-total")
        wb, ws, resp = _xlsx_response("hall_usage_report.xlsx")
        ws.append(["Hall", "Bookings"])
        for r in rows:
            ws.append([r["hall__name"], r["total"]])
    elif report_type == "all-halls":
        wb, ws, resp = _xlsx_response("all_halls_report.xlsx")
        ws.append(["Name", "Type", "Capacity", "Faculty", "Building", "Price/hour", "Active"])
        for h in Hall.objects.order_by("faculty", "building", "name"):
            ws.append([h.name, h.category, h.capacity, h.faculty, h.building, float(h.daily_rate), h.is_active])
    elif report_type == "revenue":
        qs = Payment.objects.filter(status=PaymentStatus.PAID)
        qs, *_ = _date_filtered_qs(request, qs, "created_at")
        wb, ws, resp = _xlsx_response("revenue_report.xlsx")
        ws.append(["Payment ID", "Reservation", "User", "Amount", "Date"])
        for p in qs.select_related("reservation", "user"):
            ws.append([p.id, getattr(p.reservation, "booking_reference", ""), getattr(p.user, "email", ""), float(p.amount), p.created_at.strftime("%Y-%m-%d %H:%M")])
        ws.append([])
        ws.append(["TOTAL", "", "", float(qs.aggregate(total=Sum("amount"))["total"] or 0), ""])
    elif report_type == "bookings":
        qs = Reservation.objects.all()
        qs, *_ = _date_filtered_qs(request, qs, "booking_date")
        wb, ws, resp = _xlsx_response("booking_report.xlsx")
        ws.append(["Reference", "User", "Hall", "Date", "Start", "End", "Status", "Total"])
        for r in qs.select_related("user", "hall"):
            ws.append([r.booking_reference, getattr(r.user, "email", ""), r.hall.name, str(r.booking_date), str(r.start_time), str(r.end_time), r.status, float(r.total_cost)])
    else:
        return HttpResponse("Invalid report type", status=400)

    wb.save(resp)
    return resp


@login_required
def export_users_csv(request):
    from users.models import User
    from core.services import can_view_reports
    if getattr(request.user, "role", None) != "ADMIN" and not getattr(request.user, "is_superuser", False) and not can_view_reports(request.user):
        return HttpResponse(status=403)

    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="users.csv"'
    writer = csv.writer(resp)
    writer.writerow(["ID", "Email", "Username", "First Name", "Last Name", "Role", "Department", "Joined", "Status"])

    qs = User.objects.all().order_by("-date_joined")
    for u in qs:
        status = "Blocked" if u.is_blocked else ("Active" if u.is_active else "Inactive")
        writer.writerow([
            u.id, u.email, u.username, u.first_name, u.last_name,
            u.get_role_display(), u.department, u.date_joined.strftime("%Y-%m-%d"), status
        ])
    return resp


@login_required
def export_logs_csv(request):
    from core.models import AuditLog, ActivityLog
    from users.models import LoginLog
    if getattr(request.user, "role", None) != "ADMIN" and not getattr(request.user, "is_superuser", False):
        return HttpResponse(status=403)

    log_type = request.GET.get("type", "audit")
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="system_logs_{log_type}.csv"'
    writer = csv.writer(resp)

    if log_type == "login":
        writer.writerow(["Timestamp", "User Email", "IP Address", "User Agent"])
        qs = LoginLog.objects.select_related("user").order_by("-timestamp")[:10000]
        for log in qs:
            writer.writerow([log.timestamp.strftime("%Y-%m-%d %H:%M:%S"), getattr(log.user, "email", "Unknown"), log.ip_address, log.user_agent])
    elif log_type == "activity":
        writer.writerow(["Timestamp", "User Email", "Action", "Affected Object"])
        qs = ActivityLog.objects.select_related("user").order_by("-timestamp")[:10000]
        for log in qs:
            writer.writerow([log.timestamp.strftime("%Y-%m-%d %H:%M:%S"), getattr(log.user, "email", "Unknown"), log.action, log.affected_object])
    else:
        writer.writerow(["Timestamp", "User Email", "Model", "Action"])
        qs = AuditLog.objects.select_related("user").order_by("-timestamp")[:10000]
        for log in qs:
            writer.writerow([log.timestamp.strftime("%Y-%m-%d %H:%M:%S"), getattr(log.user, "email", "Unknown"), log.model_name, log.action])

    return resp



