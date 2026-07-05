"""
EVMS Reports & Analytics Views
================================
Provides role-specific dashboards (Admin, Ventures, Facility, Bursary)
and 14 report modules, all using the Universal Report Engine.

Existing views (admin_reports_dashboard, report_centre, export_*) are
preserved with backward-compatible signatures.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum, Q, Avg, F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone

from core.services import can_view_reports, create_audit_log
from payments.models import Payment, PaymentProof, PaymentStatus, Coupon
from reservations.models import (
    Reservation, ReservationStatus, BookingCaseStatus,
    DamageReport, Penalty, HallInspectionReport, BookingTimeline,
    CommunicationThread, ThreadMessage,
)
from reports.pdf import build_reports_dashboard_pdf
from hall.models import Hall, HallBlock
from reports.engine import (
    apply_date_range, apply_booking_filters, apply_payment_filters,
    apply_damage_filters, apply_audit_filters,
    search_bookings, search_payments, search_payment_proofs,
    search_audit_logs, search_users,
    apply_sort, paginate,
    export_to_csv, export_to_xlsx, export_to_pdf,
    get_role_scope, can_access_report, PERIOD_CHOICES,
    BOOKING_SORT_FIELDS, PAYMENT_SORT_FIELDS,
)


# ---------------------------------------------------------------------------
# RBAC guard helpers
# ---------------------------------------------------------------------------

def _require_scope(request, *allowed_scopes):
    """Return (scope, None) if allowed, or (scope, redirect) if forbidden."""
    scope = get_role_scope(request.user)
    if scope not in allowed_scopes and scope != "full":
        return scope, HttpResponse(status=403)
    return scope, None


# ---------------------------------------------------------------------------
# Entry Point — role-based redirect
# ---------------------------------------------------------------------------

@login_required
def reports_home(request):
    """Redirect user to their role-specific dashboard."""
    scope = get_role_scope(request.user)
    if scope == "full":
        return redirect("reports:dashboard_admin")
    elif scope == "ventures":
        return redirect("reports:dashboard_ventures")
    elif scope == "facility":
        return redirect("reports:dashboard_facility")
    elif scope == "bursary":
        return redirect("reports:dashboard_bursary")
    else:
        return HttpResponse("You do not have access to the BI centre.", status=403)


# ===========================================================================
# DASHBOARD VIEWS
# ===========================================================================

@login_required
def dashboard_admin(request):
    """Admin / Staff — full university overview."""
    if not can_view_reports(request.user):
        return HttpResponse(status=403)

    scope = get_role_scope(request.user)
    if scope not in ("full",):
        return redirect("reports:reports_home")

    today = timezone.localdate()
    now = timezone.localtime()
    start_month = today.replace(day=1)
    start_year = today.replace(month=1, day=1)
    start_week = today - timedelta(days=today.weekday())

    # — KPI Bookings —
    total_bookings     = Reservation.objects.count()
    active_bookings    = Reservation.objects.exclude(
        case_status__in=["BOOKING_REJECTED", "CASE_CLOSED", "EVENT_COMPLETED"]
    ).count()
    completed_bookings = Reservation.objects.filter(case_status="EVENT_COMPLETED").count()
    pending_reviews    = Reservation.objects.filter(
        case_status__in=["SUBMITTED", "UNDER_VENTURES_REVIEW", "UNDER_FACILITY_REVIEW"]
    ).count()
    awaiting_payment   = Reservation.objects.filter(
        case_status__in=["AWAITING_PAYMENT", "PAYMENT_AUTHORIZATION"]
    ).count()
    booking_approved   = Reservation.objects.filter(case_status="BOOKING_APPROVED").count()

    # — KPI Revenue —
    paid_payments = Payment.objects.filter(status=PaymentStatus.PAID)
    revenue_total   = paid_payments.aggregate(t=Sum("amount"))["t"] or 0
    revenue_month   = paid_payments.filter(
        created_at__date__gte=start_month
    ).aggregate(t=Sum("amount"))["t"] or 0
    revenue_year    = paid_payments.filter(
        created_at__date__gte=start_year
    ).aggregate(t=Sum("amount"))["t"] or 0

    # — KPI Users —
    from users.models import User
    users_total     = User.objects.count()
    users_active    = User.objects.filter(is_active=True, is_blocked=False).count()
    users_new_month = User.objects.filter(date_joined__date__gte=start_month).count()
    role_stats = User.objects.values("role").annotate(total=Count("id")).order_by("-total")

    # — KPI Halls —
    halls_total  = Hall.objects.filter(is_active=True).count()
    halls_blocked = HallBlock.objects.filter(
        start_date__lte=today, end_date__gte=today
    ).count()

    # — KPI Damage —
    damage_total   = DamageReport.objects.count()
    damage_pending = DamageReport.objects.filter(is_paid=False, is_forgiven=False).count()

    # — KPI Coupons —
    coupons_active = Coupon.objects.filter(is_active=True).count()
    coupons_used   = Reservation.objects.exclude(coupon_code="").count()

    # — Revenue by month chart (current year) —
    rev_by_month = (
        paid_payments.filter(created_at__year=today.year)
        .values("created_at__month")
        .annotate(total=Sum("amount"))
        .order_by("created_at__month")
    )
    revenue_labels = [str(r["created_at__month"]).zfill(2) for r in rev_by_month]
    revenue_totals = [float(r["total"] or 0) for r in rev_by_month]

    # — Bookings by month chart (current year) —
    book_by_month = (
        Reservation.objects.filter(booking_date__year=today.year)
        .values("booking_date__month")
        .annotate(total=Count("id"))
        .order_by("booking_date__month")
    )
    booking_month_labels = [str(r["booking_date__month"]).zfill(2) for r in book_by_month]
    booking_month_counts = [r["total"] for r in book_by_month]

    # — Case status distribution —
    case_dist = (
        Reservation.objects.values("case_status")
        .annotate(total=Count("id"))
        .order_by("-total")[:12]
    )
    case_labels = [r["case_status"] for r in case_dist]
    case_counts = [r["total"] for r in case_dist]

    # — Hall utilisation —
    hall_usage = (
        Reservation.objects.values("hall__name")
        .annotate(total=Count("id"))
        .order_by("-total")[:8]
    )
    hall_labels = [h["hall__name"] for h in hall_usage]
    hall_counts = [h["total"] for h in hall_usage]

    # — Payment method distribution —
    pay_dist = (
        paid_payments.values("payment_method")
        .annotate(total=Count("id"))
        .order_by("-total")
    )
    pay_method_labels = [p["payment_method"] or "UNKNOWN" for p in pay_dist]
    pay_method_counts = [p["total"] for p in pay_dist]

    # — Purpose distribution —
    purpose_dist = (
        Reservation.objects.values("purpose")
        .annotate(total=Count("id"))
        .order_by("-total")[:8]
    )
    purpose_labels = [p["purpose"] for p in purpose_dist]
    purpose_counts = [p["total"] for p in purpose_dist]

    # — Daily stats —
    daily_stats = {
        "today":  Reservation.objects.filter(booking_date=today).count(),
        "week":   Reservation.objects.filter(booking_date__gte=start_week).count(),
        "month":  Reservation.objects.filter(booking_date__gte=start_month).count(),
        "year":   Reservation.objects.filter(booking_date__gte=start_year).count(),
    }

    # — Recent audit activity —
    from core.models import AuditLog
    recent_audit = AuditLog.objects.select_related("user").order_by("-timestamp")[:10]

    # — Pending actions —
    pending_bursary  = PaymentProof.objects.filter(status="PENDING").count()
    pending_inspection = Reservation.objects.filter(
        case_status="UNDER_POST_EVENT_INSPECTION"
    ).count()
    pending_damage_payment = Reservation.objects.filter(
        case_status="UNDER_DAMAGE_PAYMENT_VERIFICATION"
    ).count()
    final_approval_pending = Reservation.objects.filter(
        case_status="AWAITING_FINAL_APPROVAL"
    ).count()

    create_audit_log(
        user=request.user,
        action="Viewed Admin Dashboard",
        model_name="Dashboard",
        affected_module="reports",
        request=request,
    )

    return render(request, "reports/dashboard_admin.html", {
        "scope": scope,
        "now": now,
        # KPI Bookings
        "total_bookings": total_bookings,
        "active_bookings": active_bookings,
        "completed_bookings": completed_bookings,
        "pending_reviews": pending_reviews,
        "awaiting_payment": awaiting_payment,
        "booking_approved": booking_approved,
        # KPI Revenue
        "revenue_total": revenue_total,
        "revenue_month": revenue_month,
        "revenue_year": revenue_year,
        # KPI Users
        "users_total": users_total,
        "users_active": users_active,
        "users_new_month": users_new_month,
        "role_stats": role_stats,
        # KPI Halls
        "halls_total": halls_total,
        "halls_blocked": halls_blocked,
        # KPI Damage
        "damage_total": damage_total,
        "damage_pending": damage_pending,
        # KPI Coupons
        "coupons_active": coupons_active,
        "coupons_used": coupons_used,
        # Charts
        "revenue_labels": json.dumps(revenue_labels),
        "revenue_totals": json.dumps(revenue_totals),
        "booking_month_labels": json.dumps(booking_month_labels),
        "booking_month_counts": json.dumps(booking_month_counts),
        "case_labels": json.dumps(case_labels),
        "case_counts": json.dumps(case_counts),
        "hall_labels": json.dumps(hall_labels),
        "hall_counts": json.dumps(hall_counts),
        "pay_method_labels": json.dumps(pay_method_labels),
        "pay_method_counts": json.dumps(pay_method_counts),
        "purpose_labels": json.dumps(purpose_labels),
        "purpose_counts": json.dumps(purpose_counts),
        # Daily
        "daily_stats": daily_stats,
        # Pending actions
        "pending_bursary": pending_bursary,
        "pending_inspection": pending_inspection,
        "pending_damage_payment": pending_damage_payment,
        "final_approval_pending": final_approval_pending,
        # Audit
        "recent_audit": recent_audit,
    })


@login_required
def dashboard_ventures(request):
    """Ventures — bookings, coupon, financial overview."""
    scope = get_role_scope(request.user)
    if scope not in ("full", "ventures"):
        return HttpResponse(status=403)

    today = timezone.localdate()
    now = timezone.localtime()
    start_month = today.replace(day=1)

    pending_venture_review = Reservation.objects.filter(
        case_status__in=["SUBMITTED", "UNDER_VENTURES_REVIEW"]
    ).count()
    awaiting_facility = Reservation.objects.filter(
        case_status="UNDER_FACILITY_REVIEW"
    ).count()
    payment_auth_open = Reservation.objects.filter(
        case_status="PAYMENT_AUTHORIZATION"
    ).count()
    awaiting_final    = Reservation.objects.filter(
        case_status="AWAITING_FINAL_APPROVAL"
    ).count()
    booking_approved  = Reservation.objects.filter(
        case_status="BOOKING_APPROVED"
    ).count()
    booking_rejected  = Reservation.objects.filter(
        case_status="BOOKING_REJECTED"
    ).count()

    # Revenue
    paid_payments = Payment.objects.filter(status=PaymentStatus.PAID)
    revenue_total = paid_payments.aggregate(t=Sum("amount"))["t"] or 0
    revenue_month = paid_payments.filter(
        created_at__date__gte=start_month
    ).aggregate(t=Sum("amount"))["t"] or 0

    # Coupon stats
    coupons_total  = Coupon.objects.count()
    coupons_active = Coupon.objects.filter(is_active=True).count()
    coupon_pending = Reservation.objects.filter(coupon_status="PENDING").count()
    coupon_approved = Reservation.objects.filter(coupon_status="APPROVED").count()
    coupon_rejected = Reservation.objects.filter(coupon_status="REJECTED").count()

    # Booking trend (current month, daily)
    daily_bookings = (
        Reservation.objects.filter(created_at__date__gte=start_month)
        .values("created_at__date")
        .annotate(total=Count("id"))
        .order_by("created_at__date")
    )
    trend_labels = [str(r["created_at__date"]) for r in daily_bookings]
    trend_counts = [r["total"] for r in daily_bookings]

    # Applicant type breakdown
    from users.models import User
    applicant_roles = (
        Reservation.objects.values("user__role")
        .annotate(total=Count("id"))
        .order_by("-total")
    )
    app_role_labels = [r["user__role"] or "UNKNOWN" for r in applicant_roles]
    app_role_counts = [r["total"] for r in applicant_roles]

    # Recent bookings needing action
    recent_pending = (
        Reservation.objects
        .filter(case_status__in=["SUBMITTED", "UNDER_VENTURES_REVIEW", "AWAITING_FINAL_APPROVAL"])
        .select_related("user", "hall")
        .order_by("-created_at")[:10]
    )

    create_audit_log(
        user=request.user,
        action="Viewed Ventures Dashboard",
        model_name="Dashboard",
        affected_module="reports",
        request=request,
    )

    return render(request, "reports/dashboard_ventures.html", {
        "scope": scope,
        "now": now,
        # Pending Actions KPIs
        "pending_venture_review": pending_venture_review,
        "awaiting_facility": awaiting_facility,
        "payment_auth_open": payment_auth_open,
        "awaiting_final": awaiting_final,
        "booking_approved": booking_approved,
        "booking_rejected": booking_rejected,
        # Revenue
        "revenue_total": revenue_total,
        "revenue_month": revenue_month,
        # Coupons
        "coupons_total": coupons_total,
        "coupons_active": coupons_active,
        "coupon_pending": coupon_pending,
        "coupon_approved": coupon_approved,
        "coupon_rejected": coupon_rejected,
        # Charts
        "trend_labels": json.dumps(trend_labels),
        "trend_counts": json.dumps(trend_counts),
        "app_role_labels": json.dumps(app_role_labels),
        "app_role_counts": json.dumps(app_role_counts),
        # Recent
        "recent_pending": recent_pending,
    })


@login_required
def dashboard_facility(request):
    """Facility — hall availability, inspections, maintenance."""
    scope = get_role_scope(request.user)
    if scope not in ("full", "facility"):
        return HttpResponse(status=403)

    today = timezone.localdate()
    now = timezone.localtime()

    # Availability queue
    pending_facility_review = Reservation.objects.filter(
        case_status="UNDER_FACILITY_REVIEW"
    ).count()
    upcoming_events = Reservation.objects.filter(
        case_status="BOOKING_APPROVED",
        booking_date__gte=today,
        booking_date__lte=today + timedelta(days=7),
    ).count()
    occupied_today = Reservation.objects.filter(
        case_status="BOOKING_APPROVED",
        booking_date=today,
    ).count()
    blocked_halls = HallBlock.objects.filter(
        start_date__lte=today, end_date__gte=today
    ).count()

    # Inspection queue
    inspection_queue = Reservation.objects.filter(
        case_status="UNDER_POST_EVENT_INSPECTION"
    ).count()
    damage_pending   = Reservation.objects.filter(
        case_status__in=["DAMAGE_ASSESSED", "AWAITING_DAMAGE_PAYMENT"]
    ).count()
    completed_inspections_month = HallInspectionReport.objects.filter(
        inspected_at__date__gte=today.replace(day=1),
    ).count()

    # Hall utilisation (top 8)
    hall_usage = (
        Reservation.objects.filter(booking_date__gte=today.replace(month=1, day=1))
        .values("hall__name")
        .annotate(total=Count("id"))
        .order_by("-total")[:8]
    )
    hall_labels = [h["hall__name"] for h in hall_usage]
    hall_counts = [h["total"] for h in hall_usage]

    # Upcoming bookings needing facility review
    facility_queue = (
        Reservation.objects
        .filter(case_status="UNDER_FACILITY_REVIEW")
        .select_related("user", "hall")
        .order_by("-created_at")[:10]
    )

    # Upcoming events this week
    upcoming_list = (
        Reservation.objects
        .filter(case_status="BOOKING_APPROVED", booking_date__gte=today,
                booking_date__lte=today + timedelta(days=14))
        .select_related("user", "hall")
        .order_by("booking_date", "start_time")[:15]
    )

    # Active hall blocks
    active_blocks = HallBlock.objects.select_related("hall").filter(
        end_date__gte=today
    ).order_by("start_date")[:10]

    # Hall status overview
    halls_all = Hall.objects.all()
    halls_active   = halls_all.filter(is_active=True, is_archived=False).count()
    halls_inactive = halls_all.filter(is_active=False).count()
    halls_archived = halls_all.filter(is_archived=True).count()

    create_audit_log(
        user=request.user,
        action="Viewed Facility Dashboard",
        model_name="Dashboard",
        affected_module="reports",
        request=request,
    )

    return render(request, "reports/dashboard_facility.html", {
        "scope": scope,
        "now": now,
        "today": today,
        # KPIs
        "pending_facility_review": pending_facility_review,
        "upcoming_events": upcoming_events,
        "occupied_today": occupied_today,
        "blocked_halls": blocked_halls,
        "inspection_queue": inspection_queue,
        "damage_pending": damage_pending,
        "completed_inspections_month": completed_inspections_month,
        # Hall stats
        "halls_active": halls_active,
        "halls_inactive": halls_inactive,
        "halls_archived": halls_archived,
        # Charts
        "hall_labels": json.dumps(hall_labels),
        "hall_counts": json.dumps(hall_counts),
        # Lists
        "facility_queue": facility_queue,
        "upcoming_list": upcoming_list,
        "active_blocks": active_blocks,
    })


@login_required
def dashboard_bursary(request):
    """Bursary — payment verification, revenue, collections."""
    scope = get_role_scope(request.user)
    if scope not in ("full", "bursary"):
        return HttpResponse(status=403)

    today = timezone.localdate()
    now = timezone.localtime()
    start_month = today.replace(day=1)

    # Payment queues
    pending_verification = PaymentProof.objects.filter(status="PENDING").count()
    pending_damage_verif = PaymentProof.objects.filter(
        status="PENDING", payment_type="DAMAGE"
    ).count()
    verified_today  = PaymentProof.objects.filter(
        status="VERIFIED", verified_at__date=today
    ).count()
    rejected_total  = PaymentProof.objects.filter(status="REJECTED").count()

    # Revenue
    paid_payments = Payment.objects.filter(status=PaymentStatus.PAID)
    revenue_total = paid_payments.aggregate(t=Sum("amount"))["t"] or 0
    revenue_month = paid_payments.filter(
        created_at__date__gte=start_month
    ).aggregate(t=Sum("amount"))["t"] or 0
    revenue_today = paid_payments.filter(
        created_at__date=today
    ).aggregate(t=Sum("amount"))["t"] or 0

    # Outstanding
    outstanding_count = Reservation.objects.filter(
        case_status__in=["AWAITING_PAYMENT", "PAYMENT_SUBMITTED", "UNDER_BURSARY_VERIFICATION"]
    ).count()
    outstanding_damage = DamageReport.objects.filter(
        is_paid=False, is_forgiven=False
    ).count()
    damage_amount_outstanding = (
        DamageReport.objects.filter(is_paid=False, is_forgiven=False)
        .aggregate(t=Sum("amount"))["t"] or 0
    )

    # Daily collections (last 30 days)
    daily_collections = (
        paid_payments.filter(created_at__date__gte=today - timedelta(days=29))
        .values("created_at__date")
        .annotate(total=Sum("amount"))
        .order_by("created_at__date")
    )
    coll_labels = [str(r["created_at__date"]) for r in daily_collections]
    coll_totals = [float(r["total"] or 0) for r in daily_collections]

    # Payment method split
    pay_dist = (
        paid_payments.values("payment_method")
        .annotate(total=Count("id"), amount=Sum("amount"))
        .order_by("-total")
    )
    pay_method_labels = [p["payment_method"] or "UNKNOWN" for p in pay_dist]
    pay_method_counts = [p["total"] for p in pay_dist]
    pay_method_amounts = [float(p["amount"] or 0) for p in pay_dist]

    # Pending proofs
    pending_proofs = (
        PaymentProof.objects
        .filter(status="PENDING")
        .select_related("reservation", "uploaded_by")
        .order_by("uploaded_at")[:15]
    )

    create_audit_log(
        user=request.user,
        action="Viewed Bursary Dashboard",
        model_name="Dashboard",
        affected_module="reports",
        request=request,
    )

    return render(request, "reports/dashboard_bursary.html", {
        "scope": scope,
        "now": now,
        # KPIs
        "pending_verification": pending_verification,
        "pending_damage_verif": pending_damage_verif,
        "verified_today": verified_today,
        "rejected_total": rejected_total,
        # Revenue
        "revenue_total": revenue_total,
        "revenue_month": revenue_month,
        "revenue_today": revenue_today,
        # Outstanding
        "outstanding_count": outstanding_count,
        "outstanding_damage": outstanding_damage,
        "damage_amount_outstanding": damage_amount_outstanding,
        # Charts
        "coll_labels": json.dumps(coll_labels),
        "coll_totals": json.dumps(coll_totals),
        "pay_method_labels": json.dumps(pay_method_labels),
        "pay_method_counts": json.dumps(pay_method_counts),
        "pay_method_amounts": json.dumps(pay_method_amounts),
        # Lists
        "pending_proofs": pending_proofs,
    })


# ===========================================================================
# REPORT MODULE VIEWS
# ===========================================================================

def _report_context_base(request, report_key: str):
    """Build common context dict for all report views."""
    if not can_view_reports(request.user):
        return None, HttpResponse(status=403)
    if not can_access_report(request.user, report_key):
        return None, HttpResponse(status=403)
    scope = get_role_scope(request.user)
    q = (request.GET.get("q") or "").strip()
    sort = request.GET.get("sort", "newest")
    per_page = int(request.GET.get("per_page", 25))
    return {
        "scope": scope,
        "q": q,
        "sort": sort,
        "per_page": per_page,
        "period_choices": PERIOD_CHOICES,
        "now": timezone.localtime(),
        "report_key": report_key,
    }, None


@login_required
def report_bookings(request):
    ctx, err = _report_context_base(request, "bookings")
    if err:
        return err

    qs = Reservation.objects.select_related("user", "hall").all()
    qs, start, end, period = apply_date_range(request, qs, "booking_date")
    qs = apply_booking_filters(request, qs)
    qs = search_bookings(qs, ctx["q"])
    qs = apply_sort(qs, ctx["sort"], BOOKING_SORT_FIELDS)

    # Aggregates
    agg = qs.aggregate(
        total_revenue=Sum("total_cost"),
        avg_cost=Avg("total_cost"),
    )

    page_obj = paginate(request, qs, ctx["per_page"])
    ctx.update({
        "page_obj": page_obj,
        "start_date": start,
        "end_date": end,
        "period": period,
        "total_count": qs.count(),
        "total_revenue": agg["total_revenue"] or 0,
        "avg_cost": agg["avg_cost"] or 0,
        "halls": Hall.objects.filter(is_active=True).order_by("name"),
        "BookingCaseStatus": BookingCaseStatus,
        "ReservationStatus": ReservationStatus,
    })

    create_audit_log(
        user=request.user, action="Generated Booking Report",
        model_name="Reservation", affected_module="reports", request=request,
    )
    return render(request, "reports/report_bookings.html", ctx)


@login_required
def report_payments(request):
    ctx, err = _report_context_base(request, "payments")
    if err:
        return err

    qs = PaymentProof.objects.select_related("reservation", "uploaded_by", "verified_by").all()
    qs, start, end, period = apply_date_range(request, qs, "uploaded_at")
    qs = search_payment_proofs(qs, ctx["q"])

    if v := request.GET.get("status"):
        qs = qs.filter(status=v)
    if v := request.GET.get("payment_type"):
        qs = qs.filter(payment_type=v)

    agg = qs.aggregate(total=Sum("amount_claimed"))

    page_obj = paginate(request, qs, ctx["per_page"])
    ctx.update({
        "page_obj": page_obj,
        "start_date": start,
        "end_date": end,
        "period": period,
        "total_count": qs.count(),
        "total_claimed": agg["total"] or 0,
        "halls": Hall.objects.filter(is_active=True).order_by("name"),
    })

    create_audit_log(
        user=request.user, action="Generated Payment Report",
        model_name="PaymentProof", affected_module="reports", request=request,
    )
    return render(request, "reports/report_payments.html", ctx)


@login_required
def report_revenue(request):
    ctx, err = _report_context_base(request, "revenue")
    if err:
        return err

    qs = Payment.objects.filter(status=PaymentStatus.PAID).select_related("user", "reservation")
    qs, start, end, period = apply_date_range(request, qs, "created_at")
    qs = search_payments(qs, ctx["q"])
    qs = apply_payment_filters(request, qs)
    qs = apply_sort(qs, ctx["sort"], PAYMENT_SORT_FIELDS)

    agg = qs.aggregate(
        total=Sum("amount"),
        booking_rev=Sum("amount", filter=Q(reservation__isnull=False, damage_report__isnull=True, penalty__isnull=True)),
        damage_rev=Sum("amount", filter=Q(damage_report__isnull=False)),
        penalty_rev=Sum("amount", filter=Q(penalty__isnull=False)),
    )

    # Revenue by month for chart
    today = timezone.localdate()
    rev_monthly = (
        Payment.objects.filter(status=PaymentStatus.PAID, created_at__year=today.year)
        .values("created_at__month")
        .annotate(total=Sum("amount"))
        .order_by("created_at__month")
    )
    rev_labels = [str(r["created_at__month"]).zfill(2) for r in rev_monthly]
    rev_data   = [float(r["total"] or 0) for r in rev_monthly]

    page_obj = paginate(request, qs, ctx["per_page"])
    ctx.update({
        "page_obj": page_obj,
        "start_date": start,
        "end_date": end,
        "period": period,
        "total_count": qs.count(),
        "revenue_total": agg["total"] or 0,
        "booking_revenue": agg["booking_rev"] or 0,
        "damage_revenue": agg["damage_rev"] or 0,
        "penalty_revenue": agg["penalty_rev"] or 0,
        "rev_labels": json.dumps(rev_labels),
        "rev_data": json.dumps(rev_data),
        "halls": Hall.objects.filter(is_active=True).order_by("name"),
    })

    create_audit_log(
        user=request.user, action="Generated Revenue Report",
        model_name="Payment", affected_module="reports", request=request,
    )
    return render(request, "reports/report_revenue.html", ctx)


@login_required
def report_coupons(request):
    ctx, err = _report_context_base(request, "coupons")
    if err:
        return err

    qs = Reservation.objects.filter(
        coupon_code__isnull=False
    ).exclude(coupon_code="").select_related("user", "hall")
    qs, start, end, period = apply_date_range(request, qs, "created_at")

    q = ctx["q"]
    if q:
        qs = qs.filter(
            Q(coupon_code__icontains=q) |
            Q(user__email__icontains=q) |
            Q(booking_reference__icontains=q)
        )

    if v := request.GET.get("coupon_status"):
        qs = qs.filter(coupon_status=v)

    # Coupon analytics
    coupon_agg = (
        qs.values("coupon_code")
        .annotate(
            usage=Count("id"),
            total_discount=Sum("discount_amount_applied"),
        )
        .order_by("-usage")[:20]
    )

    top_coupon_labels = [r["coupon_code"] for r in coupon_agg]
    top_coupon_counts = [r["usage"] for r in coupon_agg]
    top_coupon_discounts = [float(r["total_discount"] or 0) for r in coupon_agg]

    total_discount = qs.aggregate(t=Sum("discount_amount_applied"))["t"] or 0

    page_obj = paginate(request, qs, ctx["per_page"])
    ctx.update({
        "page_obj": page_obj,
        "start_date": start,
        "end_date": end,
        "period": period,
        "total_count": qs.count(),
        "total_discount": total_discount,
        "top_coupon_labels": json.dumps(top_coupon_labels),
        "top_coupon_counts": json.dumps(top_coupon_counts),
        "top_coupon_discounts": json.dumps(top_coupon_discounts),
        "all_coupons": Coupon.objects.order_by("-created_at")[:100],
    })

    create_audit_log(
        user=request.user, action="Generated Coupon Report",
        model_name="Coupon", affected_module="reports", request=request,
    )
    return render(request, "reports/report_coupons.html", ctx)


@login_required
def report_damage(request):
    ctx, err = _report_context_base(request, "damage")
    if err:
        return err

    qs = DamageReport.objects.select_related(
        "user", "reservation", "reservation__hall", "assessment_officer"
    ).all()
    qs, start, end, period = apply_date_range(request, qs, "created_at")
    qs = apply_damage_filters(request, qs)

    q = ctx["q"]
    if q:
        qs = qs.filter(
            Q(user__email__icontains=q) |
            Q(description__icontains=q) |
            Q(reservation__booking_reference__icontains=q)
        )

    agg = qs.aggregate(
        total_amount=Sum("amount"),
        paid_amount=Sum("amount", filter=Q(is_paid=True)),
        pending_amount=Sum("amount", filter=Q(is_paid=False, is_forgiven=False)),
    )

    page_obj = paginate(request, qs, ctx["per_page"])
    ctx.update({
        "page_obj": page_obj,
        "start_date": start,
        "end_date": end,
        "period": period,
        "total_count": qs.count(),
        "total_amount": agg["total_amount"] or 0,
        "paid_amount": agg["paid_amount"] or 0,
        "pending_amount": agg["pending_amount"] or 0,
        "halls": Hall.objects.filter(is_active=True).order_by("name"),
    })

    create_audit_log(
        user=request.user, action="Generated Damage Report",
        model_name="DamageReport", affected_module="reports", request=request,
    )
    return render(request, "reports/report_damage.html", ctx)


@login_required
def report_inspections(request):
    ctx, err = _report_context_base(request, "inspections")
    if err:
        return err

    qs = HallInspectionReport.objects.select_related(
        "reservation", "reservation__hall", "reservation__user", "officer"
    ).all()
    qs, start, end, period = apply_date_range(request, qs, "inspected_at")

    q = ctx["q"]
    if q:
        qs = qs.filter(
            Q(reservation__booking_reference__icontains=q) |
            Q(reservation__hall__name__icontains=q) |
            Q(officer__email__icontains=q)
        )

    if v := request.GET.get("outcome"):
        qs = qs.filter(outcome=v)
    if v := request.GET.get("hall"):
        qs = qs.filter(reservation__hall_id=v)

    damage_found = qs.filter(damage_found=True).count()
    no_damage    = qs.filter(damage_found=False).count()

    page_obj = paginate(request, qs, ctx["per_page"])
    ctx.update({
        "page_obj": page_obj,
        "start_date": start,
        "end_date": end,
        "period": period,
        "total_count": qs.count(),
        "damage_found": damage_found,
        "no_damage": no_damage,
        "halls": Hall.objects.filter(is_active=True).order_by("name"),
    })

    create_audit_log(
        user=request.user, action="Generated Inspection Report",
        model_name="HallInspectionReport", affected_module="reports", request=request,
    )
    return render(request, "reports/report_inspections.html", ctx)


@login_required
def report_penalties(request):
    ctx, err = _report_context_base(request, "penalties")
    if err:
        return err

    qs = Penalty.objects.select_related("user", "reservation", "reservation__hall").all()
    qs, start, end, period = apply_date_range(request, qs, "created_at")

    q = ctx["q"]
    if q:
        qs = qs.filter(
            Q(user__email__icontains=q) |
            Q(title__icontains=q) |
            Q(reservation__booking_reference__icontains=q)
        )

    if v := request.GET.get("is_paid"):
        qs = qs.filter(is_paid=v == "true")
    if v := request.GET.get("is_forgiven"):
        qs = qs.filter(is_forgiven=v == "true")

    agg = qs.aggregate(
        total_amount=Sum("amount"),
        paid_amount=Sum("amount", filter=Q(is_paid=True)),
        outstanding=Sum("amount", filter=Q(is_paid=False, is_forgiven=False)),
    )

    page_obj = paginate(request, qs, ctx["per_page"])
    ctx.update({
        "page_obj": page_obj,
        "start_date": start,
        "end_date": end,
        "period": period,
        "total_count": qs.count(),
        "total_amount": agg["total_amount"] or 0,
        "paid_amount": agg["paid_amount"] or 0,
        "outstanding": agg["outstanding"] or 0,
    })

    create_audit_log(
        user=request.user, action="Generated Penalty Report",
        model_name="Penalty", affected_module="reports", request=request,
    )
    return render(request, "reports/report_penalties.html", ctx)


@login_required
def report_halls(request):
    ctx, err = _report_context_base(request, "halls")
    if err:
        return err

    qs = Hall.objects.prefetch_related("gallery_images", "amenities").all()

    q = ctx["q"]
    if q:
        qs = qs.filter(
            Q(name__icontains=q) |
            Q(faculty__icontains=q) |
            Q(building__icontains=q)
        )

    if v := request.GET.get("category"):
        qs = qs.filter(category=v)
    if v := request.GET.get("faculty"):
        qs = qs.filter(faculty__icontains=v)
    if v := request.GET.get("department"):
        qs = qs.filter(owner_department=v)
    if v := request.GET.get("is_active"):
        qs = qs.filter(is_active=v == "true")

    # Hall utilisation - bookings per hall (current year)
    today = timezone.localdate()
    hall_booking_counts = {
        r["hall_id"]: r["total"]
        for r in Reservation.objects.filter(
            booking_date__year=today.year
        ).values("hall_id").annotate(total=Count("id"))
    }
    halls_with_usage = []
    for hall in qs:
        hall._booking_count = hall_booking_counts.get(hall.pk, 0)
        halls_with_usage.append(hall)

    page_obj = paginate(request, qs, ctx["per_page"])
    ctx.update({
        "page_obj": page_obj,
        "total_count": qs.count(),
        "hall_booking_counts": hall_booking_counts,
        "active_count": qs.filter(is_active=True, is_archived=False).count(),
        "inactive_count": qs.filter(is_active=False).count(),
        "archived_count": qs.filter(is_archived=True).count(),
        "from hall.models import HallCategory": None,
    })
    # Override with from import
    from hall.models import HallCategory, DepartmentChoices
    ctx["HallCategory"] = HallCategory
    ctx["DepartmentChoices"] = DepartmentChoices

    create_audit_log(
        user=request.user, action="Generated Hall Report",
        model_name="Hall", affected_module="reports", request=request,
    )
    return render(request, "reports/report_halls.html", ctx)


@login_required
def report_applicants(request):
    ctx, err = _report_context_base(request, "applicants")
    if err:
        return err

    from users.models import User
    qs = User.objects.filter(
        role__in=["STUDENT", "EXTERNAL", "DEPARTMENT", "STAFF"]
    ).prefetch_related("reservations")
    qs, start, end, period = apply_date_range(request, qs, "date_joined")
    qs = search_users(qs, ctx["q"])

    if v := request.GET.get("role"):
        qs = qs.filter(role=v)
    if v := request.GET.get("department"):
        qs = qs.filter(department__icontains=v)
    if v := request.GET.get("is_blocked"):
        qs = qs.filter(is_blocked=v == "true")

    # Annotate with booking count
    qs = qs.annotate(booking_count=Count("reservation"))

    if ctx["sort"] == "most_active":
        qs = qs.order_by("-booking_count")
    elif ctx["sort"] == "least_active":
        qs = qs.order_by("booking_count")
    elif ctx["sort"] == "newest":
        qs = qs.order_by("-date_joined")
    elif ctx["sort"] == "oldest":
        qs = qs.order_by("date_joined")
    else:
        qs = qs.order_by("-date_joined")

    page_obj = paginate(request, qs, ctx["per_page"])
    ctx.update({
        "page_obj": page_obj,
        "start_date": start,
        "end_date": end,
        "period": period,
        "total_count": qs.count(),
        "blocked_count": qs.filter(is_blocked=True).count(),
    })

    from users.models import UserRole
    ctx["UserRole"] = UserRole

    create_audit_log(
        user=request.user, action="Generated Applicant Report",
        model_name="User", affected_module="reports", request=request,
    )
    return render(request, "reports/report_applicants.html", ctx)


@login_required
def report_management(request):
    ctx, err = _report_context_base(request, "management")
    if err:
        return err

    today = timezone.localdate()
    start_month = today.replace(day=1)

    # Response time analytics — how fast ventures reviews bookings
    from django.db.models.functions import TruncDate

    # Ventures performance
    ventures_reviewed = Reservation.objects.filter(
        case_status__in=["FACILITY_APPROVED", "FACILITY_REJECTED", "PAYMENT_AUTHORIZATION", "BOOKING_APPROVED", "BOOKING_REJECTED"]
    ).count()

    # Bursary performance
    bursary_verified = PaymentProof.objects.filter(
        status="VERIFIED",
        verified_at__date__gte=start_month,
    ).count()
    bursary_rejected = PaymentProof.objects.filter(
        status="REJECTED",
        verified_at__date__gte=start_month,
    ).count()

    # Facility performance
    facility_reviewed = HallInspectionReport.objects.filter(
        inspected_at__date__gte=start_month,
    ).count()

    # Most active management users
    from core.models import AuditLog
    active_managers = (
        AuditLog.objects.filter(
            timestamp__date__gte=start_month,
            role__in=["ADMIN", "VENTURES", "FACILITY", "BURSARY", "STAFF"],
        )
        .values("user__email", "user__first_name", "user__last_name", "role")
        .annotate(action_count=Count("id"))
        .order_by("-action_count")[:10]
    )

    # Actions per role
    role_activity = (
        AuditLog.objects.filter(timestamp__date__gte=start_month)
        .values("role")
        .annotate(total=Count("id"))
        .order_by("-total")
    )
    role_labels = [r["role"] for r in role_activity]
    role_counts = [r["total"] for r in role_activity]

    ctx.update({
        "ventures_reviewed": ventures_reviewed,
        "bursary_verified": bursary_verified,
        "bursary_rejected": bursary_rejected,
        "facility_reviewed": facility_reviewed,
        "active_managers": active_managers,
        "role_labels": json.dumps(role_labels),
        "role_counts": json.dumps(role_counts),
    })

    create_audit_log(
        user=request.user, action="Generated Management Performance Report",
        model_name="AuditLog", affected_module="reports", request=request,
    )
    return render(request, "reports/report_management.html", ctx)


@login_required
def report_notifications(request):
    ctx, err = _report_context_base(request, "notifications")
    if err:
        return err

    from notifications.models import Notification
    qs = Notification.objects.select_related("user").all()
    qs, start, end, period = apply_date_range(request, qs, "created_at")

    q = ctx["q"]
    if q:
        qs = qs.filter(
            Q(title__icontains=q) |
            Q(message__icontains=q) |
            Q(user__email__icontains=q)
        )

    if v := request.GET.get("is_read"):
        qs = qs.filter(is_read=v == "true")

    unread_count = qs.filter(is_read=False).count()
    read_count   = qs.filter(is_read=True).count()

    page_obj = paginate(request, qs, ctx["per_page"])
    ctx.update({
        "page_obj": page_obj,
        "start_date": start,
        "end_date": end,
        "period": period,
        "total_count": qs.count(),
        "unread_count": unread_count,
        "read_count": read_count,
    })

    create_audit_log(
        user=request.user, action="Generated Notification Report",
        model_name="Notification", affected_module="reports", request=request,
    )
    return render(request, "reports/report_notifications.html", ctx)


@login_required
def report_communications(request):
    ctx, err = _report_context_base(request, "communications")
    if err:
        return err

    qs = ThreadMessage.objects.select_related(
        "thread__reservation", "thread__reservation__hall", "sender"
    ).all()
    qs, start, end, period = apply_date_range(request, qs, "created_at")

    q = ctx["q"]
    if q:
        qs = qs.filter(
            Q(content__icontains=q) |
            Q(sender__email__icontains=q) |
            Q(thread__reservation__booking_reference__icontains=q)
        )

    if v := request.GET.get("message_type"):
        qs = qs.filter(message_type=v)

    page_obj = paginate(request, qs, ctx["per_page"])
    ctx.update({
        "page_obj": page_obj,
        "start_date": start,
        "end_date": end,
        "period": period,
        "total_count": qs.count(),
    })

    create_audit_log(
        user=request.user, action="Generated Communication Report",
        model_name="ThreadMessage", affected_module="reports", request=request,
    )
    return render(request, "reports/report_communications.html", ctx)


@login_required
def report_audit(request):
    """Full audit trail — Admin only."""
    if get_role_scope(request.user) != "full":
        return HttpResponse(status=403)

    ctx, err = _report_context_base(request, "audit")
    if err:
        return err

    from core.models import AuditLog
    qs = AuditLog.objects.select_related("user").all()
    qs, start, end, period = apply_date_range(request, qs, "timestamp", default="today")
    qs = apply_audit_filters(request, qs)
    qs = search_audit_logs(qs, ctx["q"])

    if ctx["sort"] == "oldest":
        qs = qs.order_by("timestamp")
    else:
        qs = qs.order_by("-timestamp")

    page_obj = paginate(request, qs, ctx["per_page"])
    ctx.update({
        "page_obj": page_obj,
        "start_date": start,
        "end_date": end,
        "period": period,
        "total_count": qs.count(),
    })

    from users.models import UserRole
    ctx["UserRole"] = UserRole

    return render(request, "reports/report_audit.html", ctx)


@login_required
def report_system_usage(request):
    """System usage and login activity — Admin only."""
    if get_role_scope(request.user) != "full":
        return HttpResponse(status=403)

    ctx, err = _report_context_base(request, "system_usage")
    if err:
        return err

    from users.models import LoginLog, User
    from core.models import AuditLog

    qs = LoginLog.objects.select_related("user").all()
    qs, start, end, period = apply_date_range(request, qs, "timestamp", default="last7")

    q = ctx["q"]
    if q:
        qs = qs.filter(
            Q(user__email__icontains=q) |
            Q(ip_address__icontains=q)
        )

    # Browser / OS stats from login logs
    browser_dist = (
        qs.values("user_agent")
        .annotate(total=Count("id"))
        .order_by("-total")[:10]
    )

    # Activity by role (current period)
    role_activity = (
        AuditLog.objects.filter(timestamp__date__gte=start or timezone.localdate())
        .values("role")
        .annotate(total=Count("id"))
        .order_by("-total")
    )
    role_labels = [r["role"] or "UNKNOWN" for r in role_activity]
    role_counts = [r["total"] for r in role_activity]

    # Login trend (last 14 days)
    today = timezone.localdate()
    login_trend = (
        LoginLog.objects.filter(timestamp__date__gte=today - timedelta(days=13))
        .values("timestamp__date")
        .annotate(total=Count("id"))
        .order_by("timestamp__date")
    )
    trend_labels = [str(r["timestamp__date"]) for r in login_trend]
    trend_counts = [r["total"] for r in login_trend]

    page_obj = paginate(request, qs, ctx["per_page"])
    ctx.update({
        "page_obj": page_obj,
        "start_date": start,
        "end_date": end,
        "period": period,
        "total_count": qs.count(),
        "unique_users": qs.values("user").distinct().count(),
        "role_labels": json.dumps(role_labels),
        "role_counts": json.dumps(role_counts),
        "trend_labels": json.dumps(trend_labels),
        "trend_counts": json.dumps(trend_counts),
    })

    return render(request, "reports/report_system_usage.html", ctx)


# ===========================================================================
# UNIVERSAL EXPORT ENDPOINT
# ===========================================================================

@login_required
def universal_export(request):
    """Unified export endpoint: ?report=bookings&format=csv|xlsx|pdf"""
    if not can_view_reports(request.user):
        return HttpResponse(status=403)

    report   = request.GET.get("report", "bookings")
    fmt      = request.GET.get("format", "csv")
    today    = timezone.localdate()
    gen_by   = request.user.get_full_name() or request.user.email

    if not can_access_report(request.user, report):
        return HttpResponse(status=403)

    # Build rows + headers per report type
    if report == "bookings":
        qs = Reservation.objects.select_related("user", "hall").all()
        qs, *_ = apply_date_range(request, qs, "booking_date")
        qs = apply_booking_filters(request, qs)
        qs = search_bookings(qs, (request.GET.get("q") or "").strip())
        headers = ["Reference", "Applicant", "Hall", "Faculty", "Date", "Start", "End",
                   "Purpose", "Case Status", "Total Cost (₦)", "Coupon", "Created"]
        rows = [
            [
                r.booking_reference,
                getattr(r.user, "email", ""),
                r.hall.name,
                r.hall.faculty,
                str(r.booking_date),
                str(r.start_time),
                str(r.end_time),
                r.purpose,
                r.case_status,
                float(r.total_cost),
                r.coupon_code or "",
                r.created_at.strftime("%Y-%m-%d %H:%M"),
            ]
            for r in qs[:5000]
        ]
        title = "Booking Report"
        filename_base = f"bookings_{today}"

    elif report == "payments":
        qs = PaymentProof.objects.select_related("reservation", "uploaded_by", "verified_by").all()
        qs, *_ = apply_date_range(request, qs, "uploaded_at")
        qs = search_payment_proofs(qs, (request.GET.get("q") or "").strip())
        headers = ["Booking Ref", "Applicant", "Type", "Amount Claimed (₦)",
                   "Transaction Ref", "Status", "Verified By", "Uploaded At"]
        rows = [
            [
                getattr(p.reservation, "booking_reference", ""),
                getattr(p.uploaded_by, "email", ""),
                p.payment_type,
                float(p.amount_claimed),
                p.transaction_ref,
                p.status,
                getattr(p.verified_by, "email", ""),
                p.uploaded_at.strftime("%Y-%m-%d %H:%M"),
            ]
            for p in qs[:5000]
        ]
        title = "Payment Report"
        filename_base = f"payments_{today}"

    elif report == "revenue":
        qs = Payment.objects.filter(status=PaymentStatus.PAID).select_related("user", "reservation").all()
        qs, *_ = apply_date_range(request, qs, "created_at")
        headers = ["ID", "Booking Ref", "Applicant", "Amount (₦)", "Method", "Provider", "Date"]
        rows = [
            [
                p.id,
                getattr(p.reservation, "booking_reference", ""),
                getattr(p.user, "email", ""),
                float(p.amount),
                p.payment_method,
                p.provider,
                p.created_at.strftime("%Y-%m-%d %H:%M"),
            ]
            for p in qs[:5000]
        ]
        title = "Revenue Report"
        filename_base = f"revenue_{today}"

    elif report == "damage":
        qs = DamageReport.objects.select_related("user", "reservation", "reservation__hall").all()
        qs, *_ = apply_date_range(request, qs, "created_at")
        headers = ["ID", "Applicant", "Booking Ref", "Hall", "Amount (₦)", "Paid", "Forgiven", "Created"]
        rows = [
            [
                d.id,
                getattr(d.user, "email", ""),
                getattr(d.reservation, "booking_reference", ""),
                getattr(getattr(d.reservation, "hall", None), "name", ""),
                float(d.amount),
                "Yes" if d.is_paid else "No",
                "Yes" if d.is_forgiven else "No",
                d.created_at.strftime("%Y-%m-%d %H:%M"),
            ]
            for d in qs[:5000]
        ]
        title = "Damage Report"
        filename_base = f"damage_{today}"

    elif report == "audit":
        if get_role_scope(request.user) != "full":
            return HttpResponse(status=403)
        from core.models import AuditLog
        qs = AuditLog.objects.select_related("user").all()
        qs, *_ = apply_date_range(request, qs, "timestamp", default="today")
        headers = ["Timestamp", "User", "Role", "Department", "Module", "Model",
                   "Action", "IP Address", "Browser", "OS", "Request ID"]
        rows = [
            [
                a.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                getattr(a.user, "email", "Unknown"),
                a.role,
                a.department,
                a.affected_module,
                a.model_name,
                a.action,
                a.ip_address or "",
                a.browser,
                a.os_info,
                a.request_id,
            ]
            for a in qs[:10000]
        ]
        title = "Audit Trail Report"
        filename_base = f"audit_{today}"

    elif report == "halls":
        qs = Hall.objects.all()
        headers = ["ID", "Name", "Category", "Capacity", "Faculty", "Building",
                   "Daily Rate (₦)", "Security Deposit (₦)", "Active", "Archived"]
        rows = [
            [
                h.id, h.name, h.category, h.capacity, h.faculty,
                h.building, float(h.daily_rate), float(h.security_deposit),
                "Yes" if h.is_active else "No",
                "Yes" if h.is_archived else "No",
            ]
            for h in qs
        ]
        title = "Hall Report"
        filename_base = f"halls_{today}"

    else:
        return HttpResponse("Invalid report type.", status=400)

    create_audit_log(
        user=request.user,
        action=f"Exported {report.title()} Report as {fmt.upper()}",
        model_name="Report",
        affected_module="reports",
        request=request,
    )

    filename = f"{filename_base}.{fmt}"

    if fmt == "csv":
        return export_to_csv(None, filename=filename, headers=headers, rows=rows)
    elif fmt == "xlsx":
        return export_to_xlsx(
            filename=filename,
            sheet_title=title,
            headers=headers,
            rows=rows,
            report_title=title,
            generated_by=gen_by,
        )
    elif fmt == "pdf":
        return export_to_pdf(
            filename=f"{filename_base}.pdf",
            report_title=title,
            headers=headers,
            rows=rows[:500],  # PDF limit for readability
            generated_by=gen_by,
        )
    else:
        return HttpResponse("Unsupported format.", status=400)


# ===========================================================================
# LEGACY VIEWS (preserved for backward compatibility)
# ===========================================================================

@login_required
def admin_reports_dashboard(request):
    """Legacy shared dashboard — now redirects to role-specific dashboard."""
    scope = get_role_scope(request.user)
    if scope == "full":
        return dashboard_admin(request)
    elif scope == "ventures":
        return dashboard_ventures(request)
    elif scope == "facility":
        return dashboard_facility(request)
    elif scope == "bursary":
        return dashboard_bursary(request)
    else:
        if not can_view_reports(request.user):
            return HttpResponse(status=403)
        return dashboard_admin(request)


def _date_filtered_qs(request, qs, field_name: str):
    """Legacy helper — wraps the new engine for backward compat."""
    qs, start, end, period = apply_date_range(request, qs, field_name)
    return qs, start, end, period


@login_required
def report_centre(request):
    if not can_view_reports(request.user):
        return HttpResponse(status=403)

    scope = get_role_scope(request.user)
    today = timezone.localdate()
    month_start = today.replace(day=1)

    search_q = (request.GET.get("q") or "").strip()
    status_filter = request.GET.get("status", "")
    period = request.GET.get("period", "this_month")
    qs = Reservation.objects.select_related("hall", "user")
    qs, start_date, end_date, period = apply_date_range(request, qs, "booking_date")

    if search_q:
        qs = search_bookings(qs, search_q)
    if status_filter:
        qs = qs.filter(status=status_filter)

    summary = {
        "total":     qs.count(),
        "completed": qs.filter(case_status="EVENT_COMPLETED").count(),
        "cancelled": qs.filter(case_status__in=["BOOKING_REJECTED", "CASE_CLOSED"]).count(),
        "revenue":   Payment.objects.filter(
            status=PaymentStatus.PAID,
            created_at__date__gte=month_start
        ).aggregate(total=Sum("amount"))["total"] or 0,
    }

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
    visible_categories = {k: v for k, v in all_categories.items() if scope in v[3]}
    active_cat = request.GET.get("category", list(visible_categories.keys())[0] if visible_categories else "bookings")

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
# Legacy CSV / XLSX / PDF exports (preserved)
# ---------------------------------------------------------------------------

@login_required
def export_reservations_csv(request):
    if not can_view_reports(request.user):
        return HttpResponse(status=403)
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="reservations.csv"'
    writer = csv.writer(resp)
    writer.writerow(["reference", "user", "hall", "date", "start_time", "end_time", "purpose", "case_status", "total_cost"])
    for r in Reservation.objects.select_related("user", "hall").order_by("-created_at")[:5000]:
        writer.writerow([
            r.booking_reference,
            getattr(r.user, "email", ""),
            r.hall.name,
            r.booking_date,
            r.start_time,
            r.end_time,
            r.purpose,
            r.case_status,
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

    from openpyxl import Workbook
    today = timezone.localdate()

    def _xlsx_response(filename: str):
        wb = Workbook()
        ws = wb.active
        resp = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        return wb, ws, resp

    if report_type == "hall-usage":
        qs = Reservation.objects.all()
        qs, *_ = apply_date_range(request, qs, "booking_date")
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
        qs, *_ = apply_date_range(request, qs, "created_at")
        wb, ws, resp = _xlsx_response("revenue_report.xlsx")
        ws.append(["Payment ID", "Reservation", "User", "Amount", "Date"])
        for p in qs.select_related("reservation", "user"):
            ws.append([p.id, getattr(p.reservation, "booking_reference", ""), getattr(p.user, "email", ""), float(p.amount), p.created_at.strftime("%Y-%m-%d %H:%M")])
        ws.append([])
        ws.append(["TOTAL", "", "", float(qs.aggregate(total=Sum("amount"))["total"] or 0), ""])
    elif report_type == "bookings":
        qs = Reservation.objects.all()
        qs, *_ = apply_date_range(request, qs, "booking_date")
        wb, ws, resp = _xlsx_response("booking_report.xlsx")
        ws.append(["Reference", "User", "Hall", "Date", "Start", "End", "Status", "Total"])
        for r in qs.select_related("user", "hall"):
            ws.append([r.booking_reference, getattr(r.user, "email", ""), r.hall.name, str(r.booking_date), str(r.start_time), str(r.end_time), r.case_status, float(r.total_cost)])
    else:
        return HttpResponse("Invalid report type", status=400)

    wb.save(resp)
    return resp


@login_required
def export_users_csv(request):
    from users.models import User
    if getattr(request.user, "role", None) != "ADMIN" and not getattr(request.user, "is_superuser", False) and not can_view_reports(request.user):
        return HttpResponse(status=403)
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="users.csv"'
    writer = csv.writer(resp)
    writer.writerow(["ID", "Email", "Username", "First Name", "Last Name", "Role", "Department", "Joined", "Status"])
    for u in User.objects.all().order_by("-date_joined"):
        status = "Blocked" if u.is_blocked else ("Active" if u.is_active else "Inactive")
        writer.writerow([u.id, u.email, u.username, u.first_name, u.last_name, u.get_role_display(), u.department, u.date_joined.strftime("%Y-%m-%d"), status])
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
        for log in LoginLog.objects.select_related("user").order_by("-timestamp")[:10000]:
            writer.writerow([log.timestamp.strftime("%Y-%m-%d %H:%M:%S"), getattr(log.user, "email", "Unknown"), log.ip_address, log.user_agent])
    elif log_type == "activity":
        writer.writerow(["Timestamp", "User Email", "Action", "Affected Object"])
        for log in ActivityLog.objects.select_related("user").order_by("-timestamp")[:10000]:
            writer.writerow([log.timestamp.strftime("%Y-%m-%d %H:%M:%S"), getattr(log.user, "email", "Unknown"), log.action, log.affected_object])
    else:
        writer.writerow(["Timestamp", "User Email", "Role", "Module", "Model", "Action", "IP", "Browser", "OS"])
        for log in AuditLog.objects.select_related("user").order_by("-timestamp")[:10000]:
            writer.writerow([
                log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                getattr(log.user, "email", "Unknown"),
                log.role,
                log.affected_module,
                log.model_name,
                log.action,
                log.ip_address or "",
                log.browser,
                log.os_info,
            ])

    return resp
