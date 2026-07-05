from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import models
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.services import can_view_all, can_view_reports, create_audit_log
from hall.models import Hall
from hall.views import hall_booking_context
from reservations.forms import ReservationCreateForm
from reservations.models import (
    BookingCaseStatus,
    BookingTimeline,
    CommunicationThread,
    ConditionRating,
    CouponActionLog,
    DamageDocument,
    DamagePhoto,
    DamageReport,
    DocumentType,
    HallInspectionReport,
    InspectionOutcome,
    MessageType,
    PaymentAuthorization,
    PaymentDeadlineType,
    Penalty,
    Reservation,
    ReservationDocument,
    ReservationStatus,
    ThreadMessage,
    VenturesPenaltyType,
)
from reservations.pdf import build_reservation_receipt_pdf
from reservations.services import WorkflowService, TransitionResult
from users.decorators import capability_required, role_required
from users.services import can, can_manage_bursary


def _can_view_all(user):
    return can_view_all(user)


def _can_manage_ventures(user):
    return can(user, "ventures_workflow")


def _can_manage_facility(user):
    return can(user, "facility_workflow")


def _can_manage_bursary(user):
    return can_manage_bursary(user)


@capability_required("own_bookings")
def my_reservations(request):
    qs = Reservation.objects.select_related("hall", "user")
    
    can_view_master = _can_view_all(request.user) or _can_manage_ventures(request.user)
    mode = request.GET.get("mode", "personal")
    
    if mode == "master" and can_view_master:
        pass  # Ventures and Admin have full access to master reservations
    else:
        qs = qs.filter(user=request.user)
        mode = "personal"

    q = request.GET.get("q", "").strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(booking_reference__icontains=q) | Q(purpose__icontains=q) | Q(hall__name__icontains=q) | Q(event_name__icontains=q))

    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)

    sort = request.GET.get("sort", "-booking_date")
    if sort in ["booking_date", "-booking_date", "total_cost", "-total_cost", "created_at", "-created_at"]:
        qs = qs.order_by(sort)
    else:
        qs = qs.order_by("-booking_date")

    context = {
        "reservations": qs,
        "mode": mode,
        "can_view_master": can_view_master,
        "q": q,
        "status": status,
        "sort": sort,
        "ReservationStatus": ReservationStatus,
    }
    return render(request, "reservations/my_reservations.html", context)


@capability_required("own_bookings")
def create_reservation(request, hall_id: int):
    from django.db import transaction
    
    with transaction.atomic():
        try:
            hall = Hall.objects.select_for_update(nowait=False).get(id=hall_id, is_active=True)
        except Hall.DoesNotExist:
            from django.http import Http404
            raise Http404("Hall does not exist")

        if request.method != "POST":
            return redirect("hall:hall_detail", pk=hall.id)

        form = ReservationCreateForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, "hall/hall_detail.html", hall_booking_context(request, hall, form))

        reservation: Reservation = form.save(commit=False)
        reservation.user = request.user
        reservation.hall = hall
        
        # Prevent ModelForm from saving an unvalidated coupon code
        reservation.coupon_code = ""
        reservation.coupon_status = ""
        reservation.coupon_snapshot = dict()
        reservation.coupon_requested_at = None

        try:
            reservation.full_clean()
        except ValidationError as e:
            for msg in e.messages:
                messages.error(request, msg)
            return render(request, "hall/hall_detail.html", hall_booking_context(request, hall, form))

        reservation.save()

        coupon_code = form.cleaned_data.get("coupon_code")
        if coupon_code:
            from payments.models import Coupon
            from django.utils import timezone as tz

            coupon_error = None
            try:
                coupon = Coupon.objects.get(code=coupon_code.upper(), is_active=True)

                # Full validation — mirrors the validate_coupon API
                now = tz.now()
                if coupon.valid_from and now < coupon.valid_from:
                    coupon_error = "The coupon code is not yet valid. Your request was submitted without it."
                elif coupon.valid_until and now > coupon.valid_until:
                    coupon_error = "The coupon code has expired. Your request was submitted without it."
                elif coupon.usage_per_user:
                    used = Reservation.objects.filter(
                        user=request.user,
                        coupon_code=coupon.code,
                        coupon_status="APPROVED",
                    ).exclude(status__in=["CANCELLED", "REJECTED"]).count()
                    if used >= coupon.usage_per_user:
                        coupon_error = "You have already used this coupon the maximum number of times. Your request was submitted without it."

                if not coupon_error:
                    # Coupon passed all checks — attach it with PENDING status
                    reservation.coupon_code = coupon.code
                    reservation.coupon_requested_at = now
                    reservation.coupon_status = "PENDING"
                    reservation.coupon_snapshot = {
                        "code": coupon.code,
                        "name": coupon.name,
                        "discount_type": coupon.discount_type,
                        "value": str(coupon.value),
                    }
                    reservation.save(update_fields=[
                        "coupon_code", "coupon_requested_at",
                        "coupon_status", "coupon_snapshot",
                    ])
                else:
                    messages.warning(request, coupon_error)

            except Coupon.DoesNotExist:
                messages.warning(request, "The coupon code provided is invalid or inactive. Your request was submitted without it.")

        # Document uploads (versioned by document_type)
        uploaded_files = form.cleaned_data.get("documents") or []
        doc_type_map = {}
        for f in uploaded_files:
            ext = f.name.rsplit(".", 1)[-1].lower()
            if ext in {"pdf", "docx"}:
                doc_type = DocumentType.AUTHORIZATION_LETTER
            elif ext in {"png", "jpg", "jpeg"}:
                doc_type = DocumentType.IMAGE
            else:
                doc_type = DocumentType.OTHER
            doc_type_map.setdefault(doc_type, 0)
            doc_type_map[doc_type] += 1
            version = doc_type_map[doc_type]
            ReservationDocument.objects.create(
                reservation=reservation,
                document_type=doc_type,
                file=f,
                version=version,
                uploaded_by=request.user,
            )

        # All bookings enter the workflow at SUBMITTED
        reservation.status = ReservationStatus.SUBMITTED
        reservation.save(update_fields=["status"])
        WorkflowService.submit_reservation(reservation=reservation, actor=request.user)

    messages.success(
        request,
        f"Reservation submitted (reference {reservation.booking_reference}). "
        "It will be reviewed by LASU Ventures who will assign the total cost.",
    )
    return redirect("reservations:my_reservations")


@capability_required("own_bookings")
def availability_api(request):
    hall_id = request.GET.get("hall_id")
    booking_date = request.GET.get("booking_date")
    start_time = request.GET.get("start_time")
    end_time = request.GET.get("end_time")

    if not all([hall_id, booking_date, start_time, end_time]):
        return JsonResponse({"available": False, "message": "Select date and time range."}, status=400)

    try:
        hall = Hall.objects.get(id=int(hall_id), is_active=True)
        day = datetime.strptime(booking_date, "%Y-%m-%d").date()
        start_t = datetime.strptime(start_time, "%H:%M").time()
        end_t = datetime.strptime(end_time, "%H:%M").time()
    except Exception:
        return JsonResponse({"available": False, "message": "Invalid input."}, status=400)

    if end_t <= start_t:
        return JsonResponse({"available": False, "message": "End time must be after start time."}, status=400)

    # Check for hall blocks first
    from hall.models import HallBlock
    blocked = HallBlock.objects.filter(
        hall=hall,
        start_date__lte=day,
        end_date__gte=day,
    ).exists()
    if blocked:
        return JsonResponse({"available": False, "message": "This date is blocked for this hall ❌"})

    conflict = Reservation.objects.filter(
        hall=hall,
        booking_date=day,
        start_time__lt=end_t,
        end_time__gt=start_t,
    ).exclude(status__in=["CANCELLED", "REJECTED", "CLOSED"]).exists()

    if not conflict:
        from reservations.models import InternalReservation, InternalReservationStatus
        conflict = InternalReservation.objects.filter(
            hall=hall,
            booking_date=day,
            start_time__lt=end_t,
            end_time__gt=start_t,
        ).exclude(status__in=[InternalReservationStatus.CANCELLED, InternalReservationStatus.REJECTED]).exists()

    if conflict:
        return JsonResponse({"available": False, "message": "Already booked ❌"})
    return JsonResponse({"available": True, "message": "Available ✅"})


@login_required
def receipt_pdf(request, booking_reference: str):
    reservation = get_object_or_404(Reservation, booking_reference=booking_reference)
    if not _can_view_all(request.user) and reservation.user != request.user:
        return HttpResponse(status=403)
    pdf_bytes = build_reservation_receipt_pdf(reservation=reservation, request=request)
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{booking_reference}.pdf"'
    return resp


@login_required
def verify_reservation(request, booking_reference: str):
    reservation = get_object_or_404(Reservation, booking_reference=booking_reference)
    if not _can_view_all(request.user) and reservation.user != request.user:
        return HttpResponse(status=403)
    return render(request, "reservations/verify.html", {"reservation": reservation})


@login_required
def calendar_view(request):
    mode = request.GET.get("mode", "user")
    hall_id = request.GET.get("hall_id", "")
    
    if mode == "admin" and not _can_view_all(request.user):
        mode = "user"
    elif mode == "ventures":
        # Ventures have NO ACCESS to master calendar
        mode = "user"
    elif mode == "facility" and not _can_manage_facility(request.user):
        mode = "user"
    
    # Only Admin and Facility can view Master Calendar
    can_view_master = _can_view_all(request.user) or _can_manage_facility(request.user)
    
    from hall.models import Hall
    halls = Hall.objects.filter(is_active=True).order_by("name")
    
    return render(request, "reservations/calendar.html", {
        "mode": mode,
        "can_view_master": can_view_master,
        "halls": halls,
        "selected_hall_id": hall_id
    })


def calendar_events(request):
    """
    Returns JSON events for FullCalendar.
    Supports mode: public, user, facility, admin
    """
    mode = request.GET.get("mode", "public")
    hall_id = request.GET.get("hall_id")
    
    if mode != "public" and not request.user.is_authenticated:
        return JsonResponse([], safe=False)

    qs = Reservation.objects.select_related("hall", "user")
    if hall_id:
        qs = qs.filter(hall_id=hall_id)

    # 1. Filter based on mode
    if mode == "public":
        # Public only sees blocks and non-terminal reservations (without PII)
        qs = qs.exclude(status__in=[ReservationStatus.CANCELLED, ReservationStatus.REJECTED, ReservationStatus.CLOSED])
    elif mode == "user":
        qs = qs.filter(user=request.user)
    elif mode == "ventures":
        # Ventures NO ACCESS to Master Calendar events
        return JsonResponse([], safe=False)
    elif mode == "facility":
        if not _can_manage_facility(request.user) and not _can_view_all(request.user):
            return JsonResponse([], safe=False)
        qs = qs.filter(status__in=[
            ReservationStatus.FORWARDED, ReservationStatus.AVAILABLE,
            ReservationStatus.APPROVED_PAYMENT, ReservationStatus.PAYMENT_PENDING,
            ReservationStatus.PAID, ReservationStatus.CONFIRMED,
            ReservationStatus.COMPLETED, ReservationStatus.INSPECTION_PENDING,
            ReservationStatus.DAMAGE_REPORTED
        ])
    elif mode == "admin":
        if not _can_view_all(request.user):
            return JsonResponse([], safe=False)

    events = []
    for r in qs:
        start_dt = datetime.combine(r.booking_date, r.start_time)
        end_dt = datetime.combine(r.booking_date, r.end_time)
        color = _calendar_color_for_status(r.status)
        
        if mode == "public":
            is_booked = r.status in [ReservationStatus.PAID, ReservationStatus.CONFIRMED]
            title = "Booked" if is_booked else "Pending"
            events.append({
                "id": f"res-{r.id}",
                "title": title,
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "color": "#ef4444" if is_booked else "#f97316", # Red or Orange
                "display": "block",
            })
        else:
            events.append({
                "id": f"res-{r.id}",
                "title": f"{r.hall.name} | {r.purpose}",
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "color": color,
                "url": f"/reservations/detail/{r.booking_reference}/",
                "extendedProps": {
                    "status": r.status,
                    "reference": r.booking_reference,
                    "user": r.user.get_full_name() or r.user.email,
                    "hall": r.hall.name,
                },
            })

    # 2. Add Hall Blocks
    if mode in ["public", "ventures", "facility", "admin"]:
        from hall.models import HallBlock
        block_qs = HallBlock.objects.select_related("hall").all()
        if hall_id:
            block_qs = block_qs.filter(hall_id=hall_id)
            
        for block in block_qs:
            is_maintenance = "maintenance" in block.reason.lower() or "repair" in block.reason.lower()
            if mode == "public":
                title = "Maintenance" if is_maintenance else "Blocked"
                color = "#a855f7" if is_maintenance else "#4b5563" # Purple or Dark Gray
            else:
                title = f"🚫 BLOCKED: {block.hall.name}" + (f" — {block.reason}" if block.reason else "")
                color = "rgba(220, 53, 69, 0.4)"

            events.append({
                "id": f"block-{block.id}",
                "title": title,
                "start": block.start_date.isoformat(),
                "end": (block.end_date).isoformat() + "T23:59:59",  # Make sure it covers the end date fully
                "display": "block" if mode == "public" else "background",
                "color": color,
            })

    # 3. Add Internal Reservations
    if mode in ["public", "ventures", "facility", "admin"]:
        from reservations.models import InternalReservation, InternalReservationStatus
        ir_qs = InternalReservation.objects.select_related("hall").all()
        if hall_id:
            ir_qs = ir_qs.filter(hall_id=hall_id)
        if mode == "public":
            ir_qs = ir_qs.exclude(status__in=[InternalReservationStatus.CANCELLED, InternalReservationStatus.REJECTED, InternalReservationStatus.DRAFT])
        for ir in ir_qs:
            start_dt = datetime.combine(ir.booking_date, ir.start_time)
            end_dt = datetime.combine(ir.booking_date, ir.end_time)
            events.append({
                "id": f"internal-{ir.id}",
                "title": "University Use" if mode == "public" else f"🏛️ Internal: {ir.requesting_department}",
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "color": "#3b82f6" if mode == "public" else "#6366f1", # Blue
                "display": "block",
            })

    return JsonResponse(events, safe=False)


def _calendar_color_for_status(status: str) -> str:
    mapping = {
        ReservationStatus.AVAILABLE: "#22c55e",         # Green: Facility confirmed available
        ReservationStatus.APPROVED_PAYMENT: "#f59e0b",  # Amber: Approved, awaiting payment
        ReservationStatus.PAYMENT_PENDING: "#f59e0b",   # Amber: Payment initiated
        ReservationStatus.PAID: "#ef4444",              # Red: Paid and booked (hard block)
        ReservationStatus.CONFIRMED: "#ef4444",         # Red: Confirmed booking (hard block)
        ReservationStatus.COMPLETED: "#6b7280",         # Gray: Event completed
        ReservationStatus.INSPECTION_PENDING: "#8b5cf6", # Purple: Inspection ongoing
        ReservationStatus.DAMAGE_REPORTED: "#ef4444",   # Red: Damage reported
        ReservationStatus.CLOSED: "#6b7280",            # Gray: Closed
        ReservationStatus.REJECTED: "#6b7280",          # Gray: Rejected
        ReservationStatus.CANCELLED: "#6b7280",         # Gray: Cancelled
        ReservationStatus.SUBMITTED: "#3b82f6",         # Blue: Awaiting review
        ReservationStatus.FORWARDED: "#3b82f6",         # Blue: Forwarded to facility
        ReservationStatus.UNDER_REVIEW: "#3b82f6",      # Blue: Under review
    }
    return mapping.get(status, "#9ca3af")  # Default gray


# ---------------------------------------------------------------------------
# Workflow dashboards for Ventures and Facility Management
# ---------------------------------------------------------------------------

@login_required
def ventures_dashboard(request):
    if not _can_manage_ventures(request.user) and not _can_view_all(request.user):
        return HttpResponse(status=403)

    from django.utils import timezone as tz
    from django.db.models import Sum
    from payments.models import Payment, PaymentStatus
    from payments.models import Coupon

    today = tz.localdate()
    month_start = today.replace(day=1)

    qs = Reservation.objects.select_related("hall", "user").order_by("-created_at")

    # ── KPI counts (using .count() to avoid in-memory evaluation) ──
    kpi_pending_reviews = qs.filter(
        status__in=[ReservationStatus.SUBMITTED, ReservationStatus.UNDER_REVIEW]
    ).count()
    kpi_awaiting_facility = qs.filter(status=ReservationStatus.FORWARDED).count()
    kpi_awaiting_payment = qs.filter(
        status__in=[ReservationStatus.APPROVED_PAYMENT, ReservationStatus.PAYMENT_PENDING]
    ).count()
    kpi_paid_pending_confirm = qs.filter(status=ReservationStatus.PAID).count()
    kpi_confirmed = qs.filter(status=ReservationStatus.CONFIRMED).count()
    kpi_approved = qs.filter(
        status__in=[ReservationStatus.CONFIRMED, ReservationStatus.COMPLETED]
    ).count()

    # Revenue this month (paid payments)
    revenue_this_month = (
        Payment.objects.filter(
            status=PaymentStatus.PAID,
            reservation__isnull=False,
            created_at__date__gte=month_start,
        ).aggregate(total=Sum("amount"))["total"] or 0
    )

    # Coupons applied this month — only count genuinely validated/approved coupons
    coupons_applied = qs.filter(
        coupon_code__isnull=False,
        coupon_status="APPROVED",
        created_at__date__gte=month_start,
    ).exclude(coupon_code="").count()

    # ── Activity feeds (small slices for panels) ──
    recent_applications = qs.filter(status=ReservationStatus.SUBMITTED)[:6]
    recently_approved = qs.filter(
        status__in=[ReservationStatus.CONFIRMED, ReservationStatus.APPROVED_PAYMENT]
    ).order_by("-updated_at")[:6]
    recently_rejected = qs.filter(
        status__in=[ReservationStatus.REJECTED, ReservationStatus.CANCELLED]
    ).order_by("-updated_at")[:5]
    payments_waiting = qs.filter(
        status__in=[ReservationStatus.APPROVED_PAYMENT, ReservationStatus.PAYMENT_PENDING]
    ).order_by("-created_at")[:6]

    # Latest messages from notifications
    from notifications.models import Notification
    latest_notifications = Notification.objects.filter(
        user=request.user, is_read=False
    ).order_by("-created_at")[:5]

    context = {
        # KPI cards
        "kpi_pending_reviews": kpi_pending_reviews,
        "kpi_awaiting_facility": kpi_awaiting_facility,
        "kpi_awaiting_payment": kpi_awaiting_payment,
        "kpi_paid_pending_confirm": kpi_paid_pending_confirm,
        "kpi_confirmed": kpi_confirmed,
        "kpi_approved": kpi_approved,
        "revenue_this_month": revenue_this_month,
        "coupons_applied": coupons_applied,
        # Activity panels
        "recent_applications": recent_applications,
        "recently_approved": recently_approved,
        "recently_rejected": recently_rejected,
        "payments_waiting": payments_waiting,
        "latest_notifications": latest_notifications,
        # Legacy section tables (preserved)
        "sections": [
            ("Submitted", qs.filter(status=ReservationStatus.SUBMITTED), "bi-inbox", "primary"),
            ("Under Review", qs.filter(status=ReservationStatus.UNDER_REVIEW), "bi-hourglass-split", "warning"),
            ("Forwarded to Facility", qs.filter(status=ReservationStatus.FORWARDED), "bi-arrow-right", "info"),
            ("Available (Facility Confirmed)", qs.filter(status=ReservationStatus.AVAILABLE), "bi-check-circle", "success"),
            ("Approved for Payment", qs.filter(status=ReservationStatus.APPROVED_PAYMENT), "bi-cash-stack", "success"),
            ("Payment Pending", qs.filter(status=ReservationStatus.PAYMENT_PENDING), "bi-credit-card", "warning"),
            ("Paid — Awaiting Confirmation", qs.filter(status=ReservationStatus.PAID), "bi-check2-all", "success"),
            ("Confirmed", qs.filter(status=ReservationStatus.CONFIRMED), "bi-calendar-check", "success"),
            ("Completed", qs.filter(status=ReservationStatus.COMPLETED), "bi-flag", "secondary"),
            ("Rejected", qs.filter(status=ReservationStatus.REJECTED), "bi-x-circle", "danger"),
            ("Cancelled", qs.filter(status=ReservationStatus.CANCELLED), "bi-slash-circle", "danger"),
        ]
    }
    return render(request, "reservations/ventures_dashboard.html", context)


@login_required
def facility_dashboard(request):
    if not _can_manage_facility(request.user) and not _can_view_all(request.user):
        return HttpResponse(status=403)

    from django.utils import timezone as tz
    from hall.models import Hall, HallBlock
    from reservations.models import HallInspectionReport
    from notifications.models import Notification

    today = tz.localdate()

    qs = Reservation.objects.select_related("hall", "user").order_by("-created_at")

    # ── KPI counts ──
    available_halls = Hall.objects.filter(is_active=True, is_archived=False).count()
    blocked_halls = HallBlock.objects.filter(
        start_date__lte=today, end_date__gte=today
    ).values("hall").distinct().count()
    maintenance_today = HallBlock.objects.filter(
        start_date__lte=today, end_date__gte=today
    ).count()
    pending_facility_reviews = qs.filter(
        status__in=[ReservationStatus.FORWARDED, ReservationStatus.UNDER_REVIEW]
    ).count()
    pending_inspections = qs.filter(status=ReservationStatus.INSPECTION_PENDING).count()
    todays_events = qs.filter(
        booking_date=today,
        status__in=[ReservationStatus.CONFIRMED, ReservationStatus.COMPLETED]
    ).count()
    upcoming_events = qs.filter(
        booking_date__gt=today,
        status__in=[ReservationStatus.CONFIRMED, ReservationStatus.APPROVED_PAYMENT]
    ).count()

    # Internal reservations count
    try:
        from reservations.models import InternalReservation
        internal_count = InternalReservation.objects.filter(
            booking_date__gte=today
        ).count()
    except Exception:
        internal_count = 0

    # ── Activity feeds ──
    recent_blocks = HallBlock.objects.select_related("hall", "created_by").order_by("-created_at")[:5]
    upcoming_inspection_qs = qs.filter(
        status=ReservationStatus.INSPECTION_PENDING
    ).order_by("booking_date")[:6]
    recently_forwarded = qs.filter(status=ReservationStatus.FORWARDED).order_by("-created_at")[:6]
    damage_reported = qs.filter(status=ReservationStatus.DAMAGE_REPORTED).order_by("-updated_at")[:5]
    latest_notifications = Notification.objects.filter(
        user=request.user, is_read=False
    ).order_by("-created_at")[:5]

    context = {
        # KPI cards
        "kpi_available_halls": available_halls,
        "kpi_blocked_halls": blocked_halls,
        "kpi_maintenance_today": maintenance_today,
        "kpi_pending_reviews": pending_facility_reviews,
        "kpi_pending_inspections": pending_inspections,
        "kpi_internal_count": internal_count,
        "kpi_todays_events": todays_events,
        "kpi_upcoming_events": upcoming_events,
        # Activity panels
        "recent_blocks": recent_blocks,
        "upcoming_inspection_qs": upcoming_inspection_qs,
        "recently_forwarded": recently_forwarded,
        "damage_reported": damage_reported,
        "latest_notifications": latest_notifications,
        # Legacy section tables (preserved)
        "sections": [
            ("Forwarded — Awaiting Review", qs.filter(status=ReservationStatus.FORWARDED), "bi-arrow-right", "primary"),
            ("Under Facility Review", qs.filter(status=ReservationStatus.UNDER_REVIEW), "bi-hourglass-split", "warning"),
            ("Available (Confirmed)", qs.filter(status=ReservationStatus.AVAILABLE), "bi-check-circle", "success"),
            ("Completed — Awaiting Inspection", qs.filter(status=ReservationStatus.COMPLETED), "bi-flag", "secondary"),
            ("Inspection Pending", qs.filter(status=ReservationStatus.INSPECTION_PENDING), "bi-clipboard-check", "warning"),
            ("Damage Reported", qs.filter(status=ReservationStatus.DAMAGE_REPORTED), "bi-exclamation-triangle", "danger"),
            ("Closed", qs.filter(status=ReservationStatus.CLOSED), "bi-archive", "secondary"),
            ("Rejected", qs.filter(status=ReservationStatus.REJECTED), "bi-x-circle", "danger"),
        ]
    }
    return render(request, "reservations/facility_dashboard.html", context)


@login_required
def admin_dashboard(request):
    if not _can_view_all(request.user):
        return HttpResponse(status=403)

    qs = Reservation.objects.select_related("hall", "user").order_by("-created_at")
    context = {
        "all_reservations": qs,
        "total": qs.count(),
        "pending_count": qs.filter(status__in=[
            ReservationStatus.SUBMITTED,
            ReservationStatus.FORWARDED,
            ReservationStatus.UNDER_REVIEW,
            ReservationStatus.AVAILABLE,
            ReservationStatus.APPROVED_PAYMENT,
            ReservationStatus.PAYMENT_PENDING,
            ReservationStatus.PAID,
        ]).count(),
        "completed_count": qs.filter(status=ReservationStatus.COMPLETED).count(),
        "closed_count": qs.filter(status=ReservationStatus.CLOSED).count(),
    }
    return render(request, "reservations/admin_dashboard.html", context)


# ---------------------------------------------------------------------------
# Workflow action endpoints for Ventures / Facility
# ---------------------------------------------------------------------------

@login_required
def ventures_action(request, booking_reference: str):
    if not _can_manage_ventures(request.user) and not _can_view_all(request.user):
        return HttpResponse(status=403)
    reservation = get_object_or_404(Reservation, booking_reference=booking_reference)
    action = (request.POST.get("action") or "").strip()
    notes = (request.POST.get("notes") or request.POST.get("reason") or "").strip()

    # ---- New lifecycle actions (case_status) ----
    if action in ("ventures_review", "approve"):
        # "approve" is the alias sent from the detail-page dropdown
        result = WorkflowService.ventures_review(reservation=reservation, actor=request.user, notes=notes)
    elif action == "forward_to_facility":
        result = WorkflowService.forward_to_facility(reservation=reservation, actor=request.user, notes=notes)
    elif action == "open_payment_authorization":
        # NEW: Ventures opens the Payment Authorization stage (from FACILITY_APPROVED)
        result = WorkflowService.open_payment_authorization(
            reservation=reservation, actor=request.user, notes=notes,
        )
        if result.ok:
            # Redirect to dedicated payment authorization page
            return redirect("reservations:payment_authorization", booking_reference=booking_reference)
    elif action == "billing_complete":
        quoted = request.POST.get("quoted_amount") or "0"
        deposit = request.POST.get("security_deposit") or "0"
        try:
            if not reservation.original_total:
                reservation.original_total = Decimal(quoted)
            reservation.total_cost = Decimal(quoted)
            reservation.security_deposit = Decimal(deposit)
            reservation.save(update_fields=["original_total", "total_cost", "security_deposit"])
        except Exception:
            pass
        result = WorkflowService.billing_complete(reservation=reservation, actor=request.user, notes=notes)
    elif action == "approve_coupon":
        coupon_status = request.POST.get("coupon_status", "APPROVED")
        new_coupon_code = (request.POST.get("new_coupon_code") or "").strip().upper()
        WorkflowService.approve_coupon(
            reservation=reservation, actor=request.user,
            coupon_status=coupon_status, new_coupon_code=new_coupon_code, notes=notes,
        )
        result = TransitionResult(ok=True)
    elif action == "final_approve":
        result = WorkflowService.ventures_final_approve(reservation=reservation, actor=request.user, notes=notes)
    elif action == "final_reject":
        result = WorkflowService.ventures_final_reject(reservation=reservation, actor=request.user, notes=notes)
    elif action in ("ventures_reject", "reject"):
        # "reject" is the alias sent from the detail-page dropdown
        result = WorkflowService.ventures_reject(reservation=reservation, actor=request.user, notes=notes)
    elif action == "return_to_ventures":
        result = WorkflowService.return_to_ventures(reservation=reservation, actor=request.user, notes=notes)
    elif action == "mark_event_completed":
        result = WorkflowService.mark_event_completed(reservation=reservation, actor=request.user, notes=notes)
    # ---- Legacy actions (legacy status field) ----
    elif action == "forward":
        result = WorkflowService.forward_to_facility_legacy(reservation=reservation, actor=request.user, notes=notes)
    elif action == "review":
        result = WorkflowService.mark_under_review(reservation=reservation, actor=request.user, notes=notes)
    elif action == "available":
        result = WorkflowService.mark_available(reservation=reservation, actor=request.user, notes=notes)
    elif action == "approve_payment":
        quoted = request.POST.get("quoted_amount") or "0"
        try:
            reservation.total_cost = Decimal(quoted)
            reservation.save(update_fields=["total_cost"])
        except Exception:
            pass
        result = WorkflowService.approve_for_payment(reservation=reservation, actor=request.user)
    elif action == "confirm":
        result = WorkflowService.confirm(reservation=reservation, actor=request.user)
    elif action == "complete":
        result = WorkflowService.mark_completed(reservation=reservation, actor=request.user)
    elif action == "cancel":
        result = WorkflowService.cancel(reservation=reservation, actor=request.user, notes=notes or "Cancelled by Ventures")
    elif action == "open_inspection":
        result = WorkflowService.open_inspection_legacy(reservation=reservation, actor=request.user)
    else:
        result = TransitionResult(ok=False, error="Unknown action")

    if result.ok:
        messages.success(request, f"Action '{action}' performed on {booking_reference}.")
    else:
        messages.error(request, result.error or "Action failed")

    # Always redirect back to the #ventures tab of the detail page so the user
    # lands on the correct panel — not whatever tab HTTP_REFERER happened to record.
    from django.urls import reverse
    detail_url = reverse("reservations:detail", kwargs={"booking_reference": booking_reference})
    return redirect(f"{detail_url}#ventures")


@login_required
def facility_action(request, booking_reference: str):
    if not _can_manage_facility(request.user) and not _can_view_all(request.user):
        return HttpResponse(status=403)
    reservation = get_object_or_404(Reservation, booking_reference=booking_reference)
    action = (request.POST.get("action") or "").strip()
    notes = (request.POST.get("notes") or request.POST.get("reason") or "").strip()

    # ---- New lifecycle actions (case_status) ----
    if action == "facility_approve":
        result = WorkflowService.facility_approve(reservation=reservation, actor=request.user, notes=notes)
    elif action == "facility_reject":
        result = WorkflowService.facility_reject(reservation=reservation, actor=request.user, notes=notes)
    elif action == "open_inspection":
        result = WorkflowService.open_inspection(reservation=reservation, actor=request.user, notes=notes)
    elif action == "inspection_no_damage":
        result = WorkflowService.inspection_no_damage(reservation=reservation, actor=request.user, notes=notes)
    elif action == "inspection_damage_found":
        # Used when Facility reports damage via the quick-action form (not the full report form)
        result = WorkflowService.inspection_damage_found(
            reservation=reservation, actor=request.user,
            notes=notes or "Damage found during post-event inspection."
        )
    elif action == "mark_event_completed":
        result = WorkflowService.mark_event_completed(reservation=reservation, actor=request.user, notes=notes)
    # ---- Legacy aliases (mapped to new lifecycle for backward compatibility) ----
    elif action == "reject":
        result = WorkflowService.facility_reject(reservation=reservation, actor=request.user, notes=notes or "Rejected by Facility")
    elif action in ("mark_available", "approve"):
        result = WorkflowService.facility_approve(reservation=reservation, actor=request.user, notes=notes or "Facility confirmed hall availability")
    elif action == "damage_reported":
        result = WorkflowService.record_damage(reservation=reservation, actor=request.user)
    elif action == "close":
        result = WorkflowService.inspection_no_damage(reservation=reservation, actor=request.user, notes=notes or "Booking formally closed")
    else:
        result = TransitionResult(ok=False, error="Unknown facility action")

    if result.ok:
        messages.success(request, f"Action '{action}' completed for booking {booking_reference}.")
    else:
        messages.error(request, result.error or "Action failed")

    # Always redirect back to the #facility tab of the detail page
    from django.urls import reverse
    detail_url = reverse("reservations:detail", kwargs={"booking_reference": booking_reference})
    return redirect(f"{detail_url}#facility")


# --- Core Interaction Views ---

@login_required
def reservation_detail(request, booking_reference: str):
    qs = Reservation.objects.select_related(
        "hall", "user", "coupon_approved_by"
    ).prefetch_related(
        "status_history", "logs", "messages", "documents",
        "penalties", "payments", "payment_proofs",
        "timeline_events", "damage_reports",
    )
    is_staff = (
        can_view_all(request.user)
        or _can_manage_ventures(request.user)
        or _can_manage_facility(request.user)
        or _can_manage_bursary(request.user)
    )
    if not is_staff:
        qs = qs.filter(user=request.user)
    reservation = get_object_or_404(qs, booking_reference=booking_reference)

    # Get/create the communication thread
    thread, _ = CommunicationThread.objects.get_or_create(reservation=reservation)
    thread_messages = thread.messages.select_related("sender").prefetch_related("attachments").order_by("created_at")

    # Filter messages by visibility using target_roles
    all_thread_messages = list(thread.messages.select_related("sender").prefetch_related("attachments").order_by("created_at"))
    
    if can_view_all(request.user):
        visible_messages = all_thread_messages
    else:
        if not is_staff:
            role_token = "APPLICANT"
        elif _can_manage_facility(request.user):
            role_token = "FACILITY"
        elif _can_manage_ventures(request.user):
            role_token = "VENTURES"
        elif _can_manage_bursary(request.user):
            role_token = "BURSARY"
        else:
            role_token = "UNKNOWN"

        visible_messages = []
        for m in all_thread_messages:
            if m.sender == request.user:
                visible_messages.append(m)
            elif m.target_roles:
                if role_token in m.target_roles:
                    visible_messages.append(m)
            else:
                # Legacy fallback
                if role_token == "APPLICANT":
                    if not m.is_staff_note:
                        visible_messages.append(m)
                else:
                    visible_messages.append(m)

    # Compute default_reply_roles for Applicant (or others)
    default_reply_roles = ["VENTURES"]
    for m in reversed(visible_messages):
        if m.sender != request.user:
            if _can_manage_bursary(m.sender):
                default_reply_roles = ["BURSARY"]
            else:
                default_reply_roles = ["VENTURES"]
            break

    # Mark as read
    if not is_staff:
        reservation.messages.filter(read_by_applicant=False, is_staff_note=False).update(read_by_applicant=True)
    else:
        reservation.messages.filter(read_by_staff=False).update(read_by_staff=True)

    # Inspection report
    inspection_report = getattr(reservation, "inspection_report", None)
    legacy_inspection = getattr(reservation, "inspection", None)

    # Latest damage report
    damage_report = reservation.damage_reports.order_by("-created_at").first()

    # Payment proofs
    payment_proofs = reservation.payment_proofs.all()
    booking_proofs = payment_proofs.filter(payment_type="BOOKING")
    damage_proofs = payment_proofs.filter(payment_type="DAMAGE")
    
    from payments.models import PaymentProofStatus
    booking_proofs_pending = booking_proofs.filter(status=PaymentProofStatus.PENDING)
    damage_proofs_pending = damage_proofs.filter(status=PaymentProofStatus.PENDING)
    has_pending_proofs = payment_proofs.filter(status=PaymentProofStatus.PENDING).exists()
    latest_booking_proof = booking_proofs.order_by("-uploaded_at").first()
    latest_damage_proof = damage_proofs.order_by("-uploaded_at").first()

    # Get successful online/offline booking payment for receipt viewing
    successful_booking_payment = reservation.payments.filter(
        status="PAID", damage_report__isnull=True, penalty__isnull=True
    ).order_by("-created_at").first()
    # Audit logs for this booking
    from core.models import AuditLog
    audit_logs = AuditLog.objects.filter(
        object_repr__icontains=reservation.booking_reference
    ).order_by("-timestamp")[:100]

    # Outstanding liability
    from reservations.models import Penalty
    outstanding_damage = reservation.damage_reports.filter(is_paid=False, is_forgiven=False)
    outstanding_penalties = reservation.penalties.filter(is_paid=False, is_forgiven=False)

    # --- Filter documents by viewer's role ---
    # Everyone sees documents they uploaded.
    # Additionally, they see documents where their role is in visible_to.
    all_documents = reservation.documents.all()
    if _can_view_all(request.user):
        filtered_documents = all_documents
    elif _can_manage_ventures(request.user):
        filtered_documents = all_documents.filter(models.Q(visible_to__icontains="VENTURES") | models.Q(uploaded_by=request.user)).distinct()
    elif _can_manage_bursary(request.user):
        filtered_documents = all_documents.filter(models.Q(visible_to__icontains="BURSARY") | models.Q(uploaded_by=request.user)).distinct()
    elif _can_manage_facility(request.user):
        filtered_documents = all_documents.filter(models.Q(visible_to__icontains="FACILITY") | models.Q(uploaded_by=request.user)).distinct()
    else:
        # Applicant sees their own uploads or docs routed to APPLICANT
        filtered_documents = all_documents.filter(models.Q(visible_to__icontains="APPLICANT") | models.Q(uploaded_by=request.user)).distinct()

    from reservations.action_engine import WorkflowActionEngine
    dynamic_actions = WorkflowActionEngine.get_available_actions(reservation, request.user)
    badge_label   = WorkflowActionEngine.get_badge_label(reservation.case_status)
    badge_variant = WorkflowActionEngine.get_badge_variant(reservation.case_status)

    # Audit logs for this booking
    from core.models import AuditLog
    audit_logs = AuditLog.objects.filter(
        object_repr__icontains=reservation.booking_reference
    ).order_by("-timestamp")[:100]

    # Payment authorization (for Ventures)
    payment_auth = getattr(reservation, "payment_authorization", None)
    try:
        if payment_auth is None:
            from reservations.models import PaymentAuthorization
            payment_auth = PaymentAuthorization.objects.filter(reservation=reservation).first()
    except Exception:
        payment_auth = None

    context = {
        "reservation": reservation,
        "thread_messages": visible_messages,
        "default_reply_roles": default_reply_roles,
        "inspection_report": inspection_report,
        "legacy_inspection": legacy_inspection,
        "latest_damage_report": damage_report,
        "payment_proofs": payment_proofs,
        "booking_proofs": booking_proofs,
        "damage_proofs": damage_proofs,
        "latest_booking_proof": latest_booking_proof,
        "latest_damage_proof": latest_damage_proof,
        "has_pending_proofs": has_pending_proofs,
        "successful_booking_payment": successful_booking_payment,
        "payment_auth": payment_auth,
        # Legacy compat
        "history": reservation.status_history.all(),
        "logs": reservation.logs.all(),
        "messages": reservation.messages.all(),
        "penalties": reservation.penalties.all(),
        "outstanding_damage": outstanding_damage,
        "outstanding_penalties": outstanding_penalties,
        "audit_logs": audit_logs,
        # Badge helpers
        "badge_label": badge_label,
        "badge_variant": badge_variant,
        # Enums for templates
        "DocumentType": DocumentType,
        "MessageType": MessageType,
        "ConditionRating": ConditionRating,
        "InspectionOutcome": InspectionOutcome,
        "BookingCaseStatus": BookingCaseStatus,
        "PaymentDeadlineType": PaymentDeadlineType,
        # Permissions
        "can_manage_ventures": _can_manage_ventures(request.user),
        "can_manage_facility": _can_manage_facility(request.user),
        "can_manage_bursary": _can_manage_bursary(request.user),
        "can_view_all": _can_view_all(request.user),
        "is_staff": is_staff,
        "is_applicant": request.user == reservation.user,
        "dynamic_actions": dynamic_actions,
    }
    return render(request, "reservations/reservation_detail.html", context)



@login_required
def upload_document(request, booking_reference: str):
    if request.method != "POST":
        return HttpResponse(status=405)
    qs = Reservation.objects.all()
    if not can_view_all(request.user) and not _can_manage_ventures(request.user):
        qs = qs.filter(user=request.user)
    reservation = get_object_or_404(qs, booking_reference=booking_reference)

    doc_type = request.POST.get("document_type")
    doc_file = request.FILES.get("file")

    # --- Determine visible_to routing ---
    # Allowed targets depend on the user's role
    if _can_view_all(request.user):
        allowed_roles = {"APPLICANT", "FACILITY", "VENTURES", "BURSARY"}
        default_roles = ["APPLICANT"]
    elif _can_manage_ventures(request.user):
        allowed_roles = {"APPLICANT", "FACILITY", "BURSARY"}
        default_roles = ["APPLICANT"]
    elif _can_manage_bursary(request.user):
        allowed_roles = {"APPLICANT", "FACILITY", "VENTURES"}
        default_roles = ["APPLICANT"]
    elif _can_manage_facility(request.user):
        allowed_roles = {"VENTURES", "BURSARY"}
        default_roles = ["VENTURES"]
    else:
        # Applicant
        allowed_roles = {"VENTURES", "BURSARY"}
        default_roles = ["VENTURES"]

    posted_roles = request.POST.getlist("visible_to")
    valid_roles = [r for r in posted_roles if r in allowed_roles]
    # Always default to something if nothing valid was posted
    if not valid_roles:
        valid_roles = default_roles
    visible_to_value = ",".join(valid_roles)

    if doc_type and doc_file:
        try:
            import filetype
            file_head = doc_file.read(2048)
            kind = filetype.guess(file_head)
            doc_file.seek(0)
            
            # If kind is None, we don't reject it (could be DOCX or other valid formats)
            if kind and kind.mime not in ["application/pdf", "image/jpeg", "image/png", "image/webp", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip", "application/msword"]:
                messages.error(request, f"Invalid file type: {kind.mime}. Only PDF, Word, JPEG, PNG, and WebP are allowed.")
                return redirect("reservations:detail", booking_reference=booking_reference)
        except Exception:
            pass

        max_size = 10 * 1024 * 1024
        if doc_file.size > max_size:
            messages.error(request, "File exceeds the 10MB size limit.")
        else:
            version = ReservationDocument.objects.filter(reservation=reservation, document_type=doc_type).count() + 1
            ReservationDocument.objects.create(
                reservation=reservation,
                document_type=doc_type,
                file=doc_file,
                version=version,
                uploaded_by=request.user,
                visible_to=visible_to_value,
            )
            messages.success(request, f"{doc_type} uploaded successfully.")
    else:
        messages.error(request, "Document type and file are required.")
    return redirect("reservations:detail", booking_reference=booking_reference)



@login_required
def cancel_reservation(request, booking_reference: str):
    if request.method != "POST":
        return HttpResponse(status=405)
    reservation = get_object_or_404(Reservation, booking_reference=booking_reference, user=request.user)
    reason = request.POST.get("reason") or "Cancelled by Applicant"
    result = WorkflowService.cancel(reservation=reservation, actor=request.user, notes=reason)
    if result.ok:
        messages.success(request, "Reservation cancelled successfully.")
    else:
        messages.error(request, result.error or "Could not cancel reservation.")
    return redirect("reservations:detail", booking_reference=booking_reference)


@login_required
def add_message(request, booking_reference: str):
    """Legacy message endpoint — preserved for backward compat."""
    if request.method != "POST":
        return HttpResponse(status=405)
    qs = Reservation.objects.all()
    if not can_view_all(request.user) and not _can_manage_ventures(request.user) and not _can_manage_facility(request.user):
        qs = qs.filter(user=request.user)
    reservation = get_object_or_404(qs, booking_reference=booking_reference)

    content = (request.POST.get("content") or "").strip()
    is_staff_note = request.POST.get("is_staff_note") == "true"

    if not (_can_manage_ventures(request.user) or _can_manage_facility(request.user) or can_view_all(request.user) or _can_manage_bursary(request.user)):
        is_staff_note = False

    if content:
        from reservations.models import ReservationMessage
        ReservationMessage.objects.create(
            reservation=reservation,
            sender=request.user,
            content=content,
            is_staff_note=is_staff_note,
            read_by_applicant=not is_staff_note and request.user == reservation.user,
            read_by_staff=is_staff_note or (_can_manage_ventures(request.user) or _can_manage_facility(request.user) or can_view_all(request.user))
        )
        messages.success(request, "Message added.")
    return redirect("reservations:detail", booking_reference=booking_reference)


@login_required
def add_thread_message(request, booking_reference: str):
    """Primary message endpoint using the new CommunicationThread system."""
    if request.method != "POST":
        return HttpResponse(status=405)

    qs = Reservation.objects.all()
    is_staff_user = (
        can_view_all(request.user) or _can_manage_ventures(request.user)
        or _can_manage_facility(request.user) or _can_manage_bursary(request.user)
    )
    if not is_staff_user:
        qs = qs.filter(user=request.user)
    reservation = get_object_or_404(qs, booking_reference=booking_reference)

    content = (request.POST.get("content") or "").strip()
    
    # Process target roles
    posted_targets = request.POST.getlist("target_roles")
    valid_targets = []
    
    # Enforce role-based targeting rules
    if can_view_all(request.user):
        # Admin can target anyone requested
        allowed_targets = {"VENTURES", "BURSARY", "FACILITY", "APPLICANT"}
    elif _can_manage_facility(request.user):
        # Facility can only communicate with Ventures and Bursary
        allowed_targets = {"VENTURES", "BURSARY"}
    elif _can_manage_ventures(request.user):
        # Ventures can communicate with anyone (except itself)
        allowed_targets = {"FACILITY", "BURSARY", "APPLICANT"}
    elif _can_manage_bursary(request.user):
        # Bursary can communicate with anyone (except itself)
        allowed_targets = {"FACILITY", "VENTURES", "APPLICANT"}
    else:
        # Applicant can communicate with Ventures and Bursary
        allowed_targets = {"VENTURES", "BURSARY"}
        
    for t in posted_targets:
        if t in allowed_targets:
            valid_targets.append(t)
            
    # Always default to something if valid_targets is empty to prevent hidden messages
    if not valid_targets:
        if not is_staff_user:
            valid_targets = ["VENTURES"]
        else:
            valid_targets = ["VENTURES"] if not _can_manage_ventures(request.user) else ["BURSARY"]
            
    # Default message type based on whether Applicant is a target
    if "APPLICANT" in valid_targets or not is_staff_user:
        raw_type = MessageType.APPLICANT_VISIBLE
    else:
        raw_type = MessageType.INTERNAL

    thread, _ = CommunicationThread.objects.get_or_create(reservation=reservation)

    if content:
        target_roles_str = ",".join(valid_targets)
        ThreadMessage.objects.create(
            thread=thread,
            sender=request.user,
            content=content,
            message_type=raw_type,
            target_roles=target_roles_str,
            read_by_applicant=(request.user == reservation.user),
            read_by_staff=is_staff_user,
        )
        messages.success(request, "Message sent.")
    return redirect("reservations:detail", booking_reference=booking_reference)


@login_required
def record_inspection(request, booking_reference: str):
    if not _can_manage_facility(request.user) and not can_view_all(request.user):
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse(status=405)

    reservation = get_object_or_404(Reservation, booking_reference=booking_reference)
    result_choice = request.POST.get("result")
    notes = request.POST.get("notes", "")

    from reservations.models import HallInspection, InspectionResult, DamageReport
    from django.utils import timezone

    if result_choice not in [c[0] for c in InspectionResult.choices]:
        messages.error(request, "Invalid inspection result.")
        return redirect("reservations:detail", booking_reference=booking_reference)

    HallInspection.objects.update_or_create(
        reservation=reservation,
        defaults={
            "inspector": request.user,
            "result": result_choice,
            "notes": notes,
            "inspected_at": timezone.now()
        }
    )
    messages.success(request, f"Inspection recorded: {result_choice}")

    if result_choice == InspectionResult.DAMAGE_REPORTED:
        amount_str = request.POST.get("damage_amount")
        desc = request.POST.get("damage_description") or notes
        try:
            amount = Decimal(amount_str) if amount_str else Decimal("0")
        except Exception:
            amount = Decimal("0")

        DamageReport.objects.create(
            reservation=reservation,
            user=reservation.user,
            amount=amount,
            description=desc
        )
        messages.warning(request, f"Damage report created for ₦{amount}.")
        WorkflowService.record_damage(reservation=reservation, actor=request.user)

    return redirect("reservations:detail", booking_reference=booking_reference)


@login_required
def penalty_list(request):
    if not _can_manage_ventures(request.user) and not can_view_all(request.user):
        return HttpResponse(status=403)

    from reservations.models import Penalty
    qs = Penalty.objects.select_related("user", "reservation").all()

    user_query = request.GET.get("user")
    if user_query:
        qs = qs.filter(
            models.Q(user__email__icontains=user_query)
            | models.Q(user__username__icontains=user_query)
            | models.Q(user__first_name__icontains=user_query)
            | models.Q(user__last_name__icontains=user_query)
        )

    return render(request, "reservations/penalty_list.html", {"penalties": qs, "user_query": user_query or ""})


@login_required
def forgive_penalty(request, penalty_id: int):
    if not _can_manage_ventures(request.user) and not can_view_all(request.user):
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse(status=405)

    from reservations.models import Penalty
    penalty = get_object_or_404(Penalty, id=penalty_id)
    penalty.is_forgiven = True
    penalty.save(update_fields=["is_forgiven"])

    from reservations.signals import _sync_user_block_status
    _sync_user_block_status(penalty.user)

    messages.success(request, f"Penalty for {penalty.user} has been forgiven.")
    return redirect("reservations:penalty_list")


@login_required
def forgive_damage(request, damage_id: int):
    if not _can_manage_facility(request.user) and not _can_manage_ventures(request.user) and not can_view_all(request.user):
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse(status=405)

    from reservations.models import DamageReport
    damage = get_object_or_404(DamageReport, id=damage_id)
    damage.is_forgiven = True
    
    from django.utils import timezone as tz
    damage.waived_at = tz.now()
    damage.waived_by = request.user
    damage.save(update_fields=["is_forgiven", "waived_at", "waived_by"])

    from reservations.signals import _sync_user_block_status
    _sync_user_block_status(damage.user)

    messages.success(request, f"Damage for {damage.user} has been forgiven.")
    return redirect("reservations:detail", booking_reference=damage.reservation.booking_reference)


# ─────────────────────────────────────────────────────────────────────────────
# Coupon Validation API & Application
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def validate_coupon(request):
    """
    GET /reservations/coupon/validate/?code=LASU2026&amount=50000
    Returns JSON with discount details or an error.
    """
    if request.method != "GET":
        return JsonResponse({"error": "GET only"}, status=405)

    code = (request.GET.get("code") or "").strip().upper()
    try:
        amount = Decimal(request.GET.get("amount") or "0")
    except Exception:
        return JsonResponse({"error": "Invalid amount."}, status=400)

    if not code:
        return JsonResponse({"error": "No coupon code provided."}, status=400)

    from payments.models import Coupon, DiscountType
    from django.utils import timezone as tz

    try:
        coupon = Coupon.objects.get(code=code, is_active=True)
    except Coupon.DoesNotExist:
        return JsonResponse({"valid": False, "error": "Coupon code is invalid or inactive."})

    now = tz.now()
    if coupon.valid_from and now < coupon.valid_from:
        return JsonResponse({"valid": False, "error": "This coupon is not yet valid."})
    if coupon.valid_until and now > coupon.valid_until:
        return JsonResponse({"valid": False, "error": "This coupon has expired."})
    if coupon.min_booking_amount and amount < coupon.min_booking_amount:
        return JsonResponse({"valid": False, "error": f"Minimum booking amount is ₦{coupon.min_booking_amount}."})

    # Per-user usage limit check
    if coupon.usage_per_user:
        from reservations.models import Reservation
        used = Reservation.objects.filter(
            user=request.user, coupon_code=coupon.code
        ).exclude(status__in=["CANCELLED", "REJECTED"]).count()
        if used >= coupon.usage_per_user:
            return JsonResponse({"valid": False, "error": "You have already used this coupon the maximum number of times."})

    # Compute discount
    if coupon.discount_type == DiscountType.PERCENTAGE:
        discount = (amount * coupon.value / Decimal("100")).quantize(Decimal("0.01"))
        if coupon.max_discount and discount > coupon.max_discount:
            discount = coupon.max_discount
    else:
        discount = min(coupon.value, amount)

    final = (amount - discount).quantize(Decimal("0.01"))
    return JsonResponse({
        "valid": True,
        "code": coupon.code,
        "name": coupon.name,
        "discount_type": coupon.discount_type,
        "discount_value": str(coupon.value),
        "discount_amount": str(discount),
        "original_amount": str(amount),
        "final_amount": str(final),
    })


@login_required
def apply_coupon(request, booking_reference: str):
    """
    POST by Ventures/Admin to stamp a coupon discount on a reservation
    before generating the payment request. This freezes the discount values
    on the reservation so future coupon edits do not alter historical data.
    """
    if not _can_manage_ventures(request.user) and not can_view_all(request.user):
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse(status=405)

    from django.db import transaction

    with transaction.atomic():
        reservation = get_object_or_404(Reservation.objects.select_for_update(), booking_reference=booking_reference)
        code = (request.POST.get("coupon_code") or "").strip().upper()

        if not code:
            # Clear existing coupon
            reservation.coupon_code = ""
            reservation.coupon_status = "REJECTED" if reservation.coupon_requested_at else ""
            reservation.discount_type = ""
            reservation.discount_value = Decimal("0")
            reservation.discount_amount_applied = Decimal("0")
            reservation.save(update_fields=["coupon_code", "coupon_status", "discount_type", "discount_value", "discount_amount_applied"])
            messages.info(request, "Coupon cleared.")
            return redirect("reservations:detail", booking_reference=booking_reference)

        from payments.models import Coupon, DiscountType
        from django.utils import timezone as tz

        try:
            coupon = Coupon.objects.get(code=code, is_active=True)
        except Coupon.DoesNotExist:
            messages.error(request, f"Coupon '{code}' is invalid or inactive.")
            return redirect("reservations:detail", booking_reference=booking_reference)

        amount = reservation.original_total or reservation.total_cost
        if coupon.discount_type == DiscountType.PERCENTAGE:
            discount = (amount * coupon.value / Decimal("100")).quantize(Decimal("0.01"))
            if coupon.max_discount and discount > coupon.max_discount:
                discount = coupon.max_discount
        else:
            discount = min(coupon.value, amount)

        # Freeze all discount fields on the reservation
        reservation.coupon_code = coupon.code
        reservation.coupon_status = "APPROVED" if reservation.coupon_requested_at else ""
        reservation.discount_type = coupon.discount_type
        reservation.discount_value = coupon.value
        reservation.discount_amount_applied = discount
        if not reservation.original_total:
            reservation.original_total = reservation.total_cost
        reservation.total_cost = max(reservation.original_total - discount, Decimal("0"))
        reservation.save(update_fields=[
            "coupon_code", "coupon_status", "discount_type", "discount_value",
            "discount_amount_applied", "original_total", "total_cost",
        ])

    from core.services import create_audit_log
    create_audit_log(
        user=request.user,
        action=f"Applied coupon {coupon.code} to {booking_reference}: -₦{discount}",
        model_name="Reservation",
    )
    messages.success(request, f"Coupon '{coupon.code}' applied. Discount: ₦{discount}.")
    return redirect("reservations:detail", booking_reference=booking_reference)

# ---------------------------------------------------------------------------
# New lifecycle action views
# ---------------------------------------------------------------------------

@login_required
def bursary_dashboard(request):
    """Bursary payment verification queue — enriched with full dashboard context."""
    if not _can_manage_bursary(request.user) and not _can_view_all(request.user):
        from django.contrib import messages as django_messages
        django_messages.error(request, "You do not have permission to access the Bursary Dashboard.")
        return redirect("hall:home")

    from django.utils import timezone
    from datetime import timedelta
    from core.models import AuditLog
    from payments.models import PaymentProof, PaymentProofStatus
    from reservations.models import TimelineEventType

    today = timezone.localdate()

    # ── Payment queues ──────────────────────────────────────────────────────
    pending_booking = Reservation.objects.filter(
        case_status=BookingCaseStatus.PAYMENT_SUBMITTED,
    ).select_related("hall", "user").prefetch_related("payment_proofs").order_by("-created_at")

    pending_damage = Reservation.objects.filter(
        case_status=BookingCaseStatus.DAMAGE_PAYMENT_SUBMITTED,
    ).select_related("hall", "user").prefetch_related("payment_proofs").order_by("-created_at")

    under_bursary_verification = Reservation.objects.filter(
        case_status=BookingCaseStatus.UNDER_BURSARY_VERIFICATION,
    ).select_related("hall", "user").prefetch_related("payment_proofs").order_by("-created_at")

    under_damage_verification = Reservation.objects.filter(
        case_status=BookingCaseStatus.UNDER_DAMAGE_PAYMENT_VERIFICATION,
    ).select_related("hall", "user").prefetch_related("payment_proofs").order_by("-created_at")

    verified_recent = Reservation.objects.filter(
        case_status__in=[BookingCaseStatus.PAYMENT_VERIFIED, BookingCaseStatus.DAMAGE_PAYMENT_VERIFIED],
    ).select_related("hall", "user").prefetch_related("payment_proofs").order_by("-updated_at")[:10]

    rejected_recent = Reservation.objects.filter(
        case_status__in=[BookingCaseStatus.PAYMENT_REJECTED],
    ).select_related("hall", "user").prefetch_related("payment_proofs").order_by("-updated_at")[:10]

    awaiting_clarification = Reservation.objects.filter(
        case_status__in=[BookingCaseStatus.UNDER_BURSARY_VERIFICATION, BookingCaseStatus.UNDER_DAMAGE_PAYMENT_VERIFICATION],
        timeline_events__event_type=TimelineEventType.INFORMATION_REQUESTED
    ).select_related("hall", "user").prefetch_related("payment_proofs").distinct().order_by("-updated_at")


    # ── Summary stats ───────────────────────────────────────────────────────
    total_pending = pending_booking.count() + pending_damage.count()
    total_under_review = under_bursary_verification.count() + under_damage_verification.count()
    total_awaiting_clarification = awaiting_clarification.count()

    verified_today = Reservation.objects.filter(
        case_status__in=[BookingCaseStatus.PAYMENT_VERIFIED, BookingCaseStatus.DAMAGE_PAYMENT_VERIFIED],
        updated_at__date=today,
    ).count() if hasattr(Reservation, "updated_at") else 0

    rejected_today = Reservation.objects.filter(
        case_status=BookingCaseStatus.PAYMENT_REJECTED,
        updated_at__date=today,
    ).count() if hasattr(Reservation, "updated_at") else 0

    # ── 7-day verification trend ────────────────────────────────────────────
    trend_labels = []
    trend_verified = []
    trend_rejected = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        trend_labels.append(day.strftime("%d %b"))
        if hasattr(Reservation, "updated_at"):
            trend_verified.append(
                Reservation.objects.filter(
                    case_status__in=[BookingCaseStatus.PAYMENT_VERIFIED, BookingCaseStatus.DAMAGE_PAYMENT_VERIFIED],
                    updated_at__date=day,
                ).count()
            )
            trend_rejected.append(
                Reservation.objects.filter(
                    case_status=BookingCaseStatus.PAYMENT_REJECTED,
                    updated_at__date=day,
                ).count()
            )
        else:
            trend_verified.append(0)
            trend_rejected.append(0)

    # ── Recent bursary activity from audit log ──────────────────────────────
    recent_activity = AuditLog.objects.filter(
        role="BURSARY"
    ).select_related("user").order_by("-timestamp")[:20]

    context = {
        # Queues
        "pending_booking": pending_booking,
        "pending_damage": pending_damage,
        "under_bursary_verification": under_bursary_verification,
        "under_damage_verification": under_damage_verification,
        "verified_recent": verified_recent,
        "rejected_recent": rejected_recent,
        "awaiting_clarification": awaiting_clarification,
        # Stats
        "total_pending": total_pending,
        "total_under_review": total_under_review,
        "total_awaiting_clarification": total_awaiting_clarification,
        "verified_today": verified_today,
        "rejected_today": rejected_today,
        # Chart data (JSON-serialisable)
        "trend_labels": trend_labels,
        "trend_verified": trend_verified,
        "trend_rejected": trend_rejected,
        # Activity
        "recent_activity": recent_activity,
    }
    return render(request, "reservations/bursary_dashboard.html", context)



@login_required
def bursary_action(request, booking_reference: str):
    """Bursary verifies or rejects payment proofs."""
    if not _can_manage_bursary(request.user) and not _can_view_all(request.user):
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse(status=405)

    reservation = get_object_or_404(Reservation, booking_reference=booking_reference)
    action = (request.POST.get("action") or "").strip()
    notes = (request.POST.get("notes") or "").strip()

    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    client_ip = x_forwarded_for.split(',')[0].strip() if x_forwarded_for else request.META.get('REMOTE_ADDR')
    enhanced_notes = f"{notes}\n\n[Action taken from IP: {client_ip}]" if notes else f"[Action taken from IP: {client_ip}]"

    from payments.models import PaymentProof, PaymentProofStatus
    from django.utils import timezone
    from reservations.models import BookingCaseStatus, DamageReport, Penalty

    # Helper to check if booking is already past booking payment phase
    past_booking_payment = reservation.case_status not in [
        BookingCaseStatus.DRAFT, BookingCaseStatus.SUBMITTED, BookingCaseStatus.UNDER_VENTURES_REVIEW,
        BookingCaseStatus.UNDER_FACILITY_REVIEW, BookingCaseStatus.FACILITY_APPROVED, BookingCaseStatus.PAYMENT_AUTHORIZATION,
        BookingCaseStatus.AWAITING_PAYMENT, BookingCaseStatus.PAYMENT_SUBMITTED, BookingCaseStatus.UNDER_BURSARY_VERIFICATION,
        BookingCaseStatus.PAYMENT_REJECTED
    ]

    # Helper to check if damage payment is already past the verification phase
    past_damage_payment = reservation.case_status not in [
        BookingCaseStatus.UNDER_DAMAGE_PAYMENT_VERIFICATION,
        BookingCaseStatus.DAMAGE_PAYMENT_SUBMITTED,
        BookingCaseStatus.AWAITING_DAMAGE_PAYMENT,
    ]

    from reservations.services import TransitionResult, _sync_user_block_from_damage

    if action == "verify_payment":
        if past_booking_payment:
            # Booking already moved forward (e.g. via online payment). Just clean up the proof.
            result = TransitionResult(ok=True)
        else:
            result = WorkflowService.bursary_verify_payment(
                reservation=reservation, actor=request.user, notes=enhanced_notes
            )

        if result.ok:
            PaymentProof.objects.filter(reservation=reservation, status=PaymentProofStatus.PENDING, payment_type="BOOKING").update(
                status=PaymentProofStatus.VERIFIED, verified_by=request.user, verified_at=timezone.now(), bursary_notes=notes
            )
    elif action == "reject_payment":
        if past_booking_payment:
            result = TransitionResult(ok=True)
        else:
            result = WorkflowService.bursary_reject_payment(
                reservation=reservation, actor=request.user, notes=enhanced_notes
            )

        if result.ok:
            PaymentProof.objects.filter(reservation=reservation, status=PaymentProofStatus.PENDING, payment_type="BOOKING").update(
                status=PaymentProofStatus.REJECTED, verified_by=request.user, verified_at=timezone.now(), bursary_notes=notes
            )
    elif action == "verify_damage_payment":
        if past_damage_payment:
            # Damage already processed (case moved on). Just mark any remaining pending proofs
            # as verified, ensure damage is marked paid, and sync user block.
            PaymentProof.objects.filter(reservation=reservation, status=PaymentProofStatus.PENDING, payment_type="DAMAGE").update(
                status=PaymentProofStatus.VERIFIED, verified_by=request.user, verified_at=timezone.now(), bursary_notes=notes
            )
            DamageReport.objects.filter(reservation=reservation, is_paid=False, is_forgiven=False).update(is_paid=True)
            _sync_user_block_from_damage(reservation.user)
            result = TransitionResult(ok=True)
        else:
            result = WorkflowService.bursary_verify_damage_payment(
                reservation=reservation, actor=request.user, notes=enhanced_notes
            )
            if result.ok:
                PaymentProof.objects.filter(reservation=reservation, status=PaymentProofStatus.PENDING, payment_type="DAMAGE").update(
                    status=PaymentProofStatus.VERIFIED, verified_by=request.user, verified_at=timezone.now(), bursary_notes=notes
                )
    elif action == "reject_damage_payment":
        if past_damage_payment:
            # Already processed — silently succeed (cannot reject an already-verified payment)
            result = TransitionResult(ok=True)
        else:
            result = WorkflowService.bursary_reject_damage_payment(
                reservation=reservation, actor=request.user, notes=enhanced_notes
            )
            if result.ok:
                PaymentProof.objects.filter(reservation=reservation, status=PaymentProofStatus.PENDING, payment_type="DAMAGE").update(
                    status=PaymentProofStatus.REJECTED, verified_by=request.user, verified_at=timezone.now(), bursary_notes=notes
                )
    elif action == "verify_penalty_payment":
        # Check if ALL penalties are already resolved (paid or forgiven)
        has_unpaid_penalties = Penalty.objects.filter(
            reservation=reservation, is_paid=False, is_forgiven=False
        ).exists()
        has_pending_penalty_proofs = PaymentProof.objects.filter(
            reservation=reservation, status=PaymentProofStatus.PENDING, payment_type="PENALTY"
        ).exists()

        if not has_unpaid_penalties and not has_pending_penalty_proofs:
            # Nothing to process — silently succeed
            result = TransitionResult(ok=True)
        else:
            result = WorkflowService.bursary_verify_penalty_payment(
                reservation=reservation, actor=request.user, notes=enhanced_notes
            )
            if result.ok:
                PaymentProof.objects.filter(reservation=reservation, status=PaymentProofStatus.PENDING, payment_type="PENALTY").update(
                    status=PaymentProofStatus.VERIFIED, verified_by=request.user, verified_at=timezone.now(), bursary_notes=notes
                )
                # Ensure user block is released
                _sync_user_block_from_damage(reservation.user)
    elif action == "reject_penalty_payment":
        result = WorkflowService.bursary_reject_penalty_payment(
            reservation=reservation, actor=request.user, notes=enhanced_notes
        )
        if result.ok:
            PaymentProof.objects.filter(reservation=reservation, status=PaymentProofStatus.PENDING, payment_type="PENALTY").update(
                status=PaymentProofStatus.REJECTED, verified_by=request.user, verified_at=timezone.now(), bursary_notes=notes
            )
    elif action == "request_clarification":
        result = WorkflowService.bursary_request_clarification(
            reservation=reservation, actor=request.user, notes=notes
        )
    else:
        result = TransitionResult(ok=False, error="Unknown bursary action.")

    if result.ok:
        messages.success(request, f"Bursary action '{action}' completed for {booking_reference}.")
    else:
        messages.error(request, result.error or "Action failed.")
    return redirect(request.META.get("HTTP_REFERER") or "reservations:bursary_dashboard")


@login_required
def bursary_audit_logs(request):
    """Paginated audit log view scoped to BURSARY role actions."""
    if not _can_manage_bursary(request.user) and not _can_view_all(request.user):
        messages.error(request, "You do not have permission to view the Bursary audit log.")
        return redirect("hall:home")

    from core.models import AuditLog
    from django.core.paginator import Paginator
    from django.db.models import Q

    qs = AuditLog.objects.filter(role="BURSARY").select_related("user").order_by("-timestamp")

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(action__icontains=q) | Q(user__email__icontains=q) | Q(model_name__icontains=q)
        )

    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "reservations/bursary_audit_logs.html", {
        "page_obj": page_obj,
        "q": q,
    })


@login_required
def submit_payment_proof(request, booking_reference: str):

    """Applicant uploads booking payment receipt."""
    if request.method != "POST":
        return HttpResponse(status=405)

    reservation = get_object_or_404(Reservation, booking_reference=booking_reference, user=request.user)

    if reservation.case_status not in (
        BookingCaseStatus.AWAITING_PAYMENT,
        BookingCaseStatus.PAYMENT_REJECTED,
    ):
        messages.error(request, "Payment proof cannot be submitted at this stage.")
        return redirect("reservations:detail", booking_reference=booking_reference)

    receipt_file = request.FILES.get("receipt_file")
    transaction_ref = (request.POST.get("transaction_ref") or "").strip()
    amount_claimed_str = request.POST.get("amount_claimed") or "0"

    if not receipt_file:
        messages.error(request, "Please upload a payment receipt file.")
        return redirect("reservations:detail", booking_reference=booking_reference)

    # Validate file size & type
    max_size = 5 * 1024 * 1024
    if receipt_file.size > max_size:
        messages.error(request, "File exceeds the 5MB size limit.")
        return redirect("reservations:detail", booking_reference=booking_reference)

    try:
        import filetype
        file_head = receipt_file.read(2048)
        kind = filetype.guess(file_head)
        receipt_file.seek(0)
        if kind and kind.mime not in ["application/pdf", "image/jpeg", "image/png", "image/webp"]:
            messages.error(request, "Invalid file type. Please upload PDF, JPEG, or PNG.")
            return redirect("reservations:detail", booking_reference=booking_reference)
    except Exception:
        pass

    from payments.services import PaymentResolutionService
    from payments.models import PaymentMethod, PaymentProofType
    try:
        amount_claimed = Decimal(amount_claimed_str)
    except Exception:
        amount_claimed = Decimal("0")

    from payments.models import Payment, PaymentStatus
    existing_payment = Payment.objects.filter(
        reservation=reservation,
        user=request.user,
        status=PaymentStatus.PENDING,
        damage_report__isnull=True,
        penalty__isnull=True,
    ).order_by("-created_at").first()

    try:
        PaymentResolutionService.finalize_payment(
            reservation=reservation,
            amount=amount_claimed,
            method=PaymentMethod.TRANSFER,
            provider="MANUAL",
            transaction_reference=transaction_ref,
            actor=request.user,
            proof_file=receipt_file,
            payment_type=PaymentProofType.BOOKING,
            existing_payment=existing_payment
        )
        messages.success(request, "Payment proof submitted. Awaiting Bursary verification.")
    except Exception as e:
        messages.warning(request, f"Proof uploaded but workflow update failed: {e}")
    return redirect("reservations:detail", booking_reference=booking_reference)


@login_required
def submit_damage_payment_proof(request, booking_reference: str):
    """Applicant uploads damage payment receipt."""
    if request.method != "POST":
        return HttpResponse(status=405)

    reservation = get_object_or_404(Reservation, booking_reference=booking_reference, user=request.user)

    if reservation.case_status not in (
        BookingCaseStatus.AWAITING_DAMAGE_PAYMENT,
    ):
        messages.error(request, "Damage payment cannot be submitted at this stage.")
        return redirect("reservations:detail", booking_reference=booking_reference)

    receipt_file = request.FILES.get("receipt_file")
    import uuid
    transaction_ref = (request.POST.get("transaction_ref") or "").strip()
    if not transaction_ref:
        transaction_ref = f"MANUAL-{uuid.uuid4().hex[:8].upper()}"
    amount_claimed_str = request.POST.get("amount_claimed") or "0"

    if not receipt_file:
        messages.error(request, "Please upload a damage payment receipt.")
        return redirect("reservations:detail", booking_reference=booking_reference)

    from payments.services import PaymentResolutionService
    from payments.models import PaymentMethod, PaymentProofType
    try:
        amount_claimed = Decimal(amount_claimed_str)
    except Exception:
        amount_claimed = Decimal("0")

    from payments.models import Payment, PaymentStatus
    existing_payment = Payment.objects.filter(
        reservation=reservation,
        user=request.user,
        status=PaymentStatus.PENDING,
        damage_report__isnull=False,
    ).order_by("-created_at").first()

    try:
        PaymentResolutionService.finalize_payment(
            reservation=reservation,
            amount=amount_claimed,
            method=PaymentMethod.TRANSFER,
            provider="MANUAL",
            transaction_reference=transaction_ref,
            actor=request.user,
            proof_file=receipt_file,
            payment_type=PaymentProofType.DAMAGE,
            existing_payment=existing_payment
        )
        messages.success(request, "Damage payment proof submitted successfully. Awaiting Bursary verification.")
    except Exception as e:
        messages.warning(request, f"Proof uploaded but workflow update failed: {e}")
    return redirect("reservations:detail", booking_reference=booking_reference)


@login_required
def submit_penalty_payment_proof(request, booking_reference: str):
    """Applicant uploads penalty payment receipt."""
    if request.method != "POST":
        return HttpResponse(status=405)

    reservation = get_object_or_404(Reservation, booking_reference=booking_reference, user=request.user)

    receipt_file = request.FILES.get("receipt_file")
    import uuid
    transaction_ref = (request.POST.get("transaction_ref") or "").strip()
    if not transaction_ref:
        transaction_ref = f"MANUAL-{uuid.uuid4().hex[:8].upper()}"
    amount_claimed_str = request.POST.get("amount_claimed") or "0"

    if not receipt_file:
        messages.error(request, "Please upload a penalty payment receipt.")
        return redirect("reservations:detail", booking_reference=booking_reference)

    from payments.services import PaymentResolutionService
    from payments.models import PaymentMethod, PaymentProofType
    try:
        amount_claimed = Decimal(amount_claimed_str)
    except Exception:
        amount_claimed = Decimal("0")

    from payments.models import Payment, PaymentStatus
    existing_payment = Payment.objects.filter(
        reservation=reservation,
        user=request.user,
        status=PaymentStatus.PENDING,
        penalty__isnull=False,
    ).order_by("-created_at").first()

    try:
        PaymentResolutionService.finalize_payment(
            reservation=reservation,
            amount=amount_claimed,
            method=PaymentMethod.TRANSFER,
            provider="MANUAL",
            transaction_reference=transaction_ref,
            actor=request.user,
            proof_file=receipt_file,
            payment_type=PaymentProofType.PENALTY,
            existing_payment=existing_payment
        )
        messages.success(request, "Penalty payment proof submitted successfully. Awaiting Bursary verification.")
    except Exception as e:
        messages.warning(request, f"Proof uploaded but workflow update failed: {e}")
    return redirect("reservations:detail", booking_reference=booking_reference)


@login_required
def record_inspection_report(request, booking_reference: str):
    """Facility submits the full post-event inspection report."""
    if not _can_manage_facility(request.user) and not _can_view_all(request.user):
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse(status=405)

    reservation = get_object_or_404(Reservation, booking_reference=booking_reference)

    hall_condition   = request.POST.get("hall_condition", "")
    cleanliness      = request.POST.get("cleanliness", "")
    furniture_status = request.POST.get("furniture_status", "")
    equipment_status = request.POST.get("equipment_status", "")
    outcome          = request.POST.get("outcome", "")
    notes            = (request.POST.get("notes") or "").strip()
    damage_found     = (outcome == InspectionOutcome.DAMAGE_FOUND)

    report, _ = HallInspectionReport.objects.update_or_create(
        reservation=reservation,
        defaults={
            "hall_condition":   hall_condition,
            "cleanliness":      cleanliness,
            "furniture_status": furniture_status,
            "equipment_status": equipment_status,
            "damage_found":     damage_found,
            "notes":            notes,
            "officer":          request.user,
            "inspected_at":     timezone.now(),
            "outcome":          outcome,
        },
    )

    # Handle inspection photos
    for photo_file in request.FILES.getlist("photos"):
        from reservations.models import InspectionPhoto
        InspectionPhoto.objects.create(inspection=report, photo=photo_file)

    if outcome == InspectionOutcome.DAMAGE_FOUND:
        # Parse damage details
        desc         = (request.POST.get("damage_description") or notes).strip()
        affected     = (request.POST.get("affected_items") or "").strip()
        amount_str   = request.POST.get("damage_amount") or "0"
        try:
            amount = Decimal(amount_str)
        except Exception:
            amount = Decimal("0")

        damage = DamageReport.objects.create(
            reservation=reservation,
            user=reservation.user,
            description=desc,
            affected_items=affected,
            amount=amount,
            cost_estimate=amount,
            assessment_officer=request.user,
            assessment_date=timezone.now().date(),
        )

        # Handle damage photos
        for photo_file in request.FILES.getlist("damage_photos"):
            DamagePhoto.objects.create(damage_report=damage, photo=photo_file, uploaded_by=request.user)

        # Handle damage documents
        for doc_file in request.FILES.getlist("damage_documents"):
            DamageDocument.objects.create(damage_report=damage, file=doc_file, uploaded_by=request.user)

        result = WorkflowService.inspection_damage_found(
            reservation=reservation, actor=request.user,
            notes=f"Damage found. Amount: ₦{amount}. {desc}",
        )
        messages.warning(request, f"Inspection completed — damage reported (₦{amount}).")
    else:
        result = WorkflowService.inspection_no_damage(
            reservation=reservation, actor=request.user, notes=notes,
        )
        messages.success(request, "Inspection completed — no damage found. Case closed.")

    if not result.ok:
        messages.error(request, result.error)
    return redirect("reservations:detail", booking_reference=booking_reference)


@login_required
def admin_booking_action(request, booking_reference: str):
    """Admin override actions — force close, forgive liability, remove restriction."""
    if not _can_view_all(request.user):
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse(status=405)

    reservation = get_object_or_404(Reservation, booking_reference=booking_reference)
    action = (request.POST.get("action") or "").strip()
    reason = (request.POST.get("reason") or "").strip()

    if action == "forgive_liability":
        result = WorkflowService.admin_forgive_liability(
            reservation=reservation, actor=request.user, reason=reason,
        )
        messages.success(request, "Liability forgiven and user restriction removed.")
    elif action == "force_close":
        result = WorkflowService.admin_close_case(
            reservation=reservation, actor=request.user, notes=reason,
        )
        messages.success(request, "Case force-closed.")
    elif action == "remove_restriction":
        from reservations.services import _sync_user_block_from_damage
        _sync_user_block_from_damage(reservation.user)
        result = TransitionResult(ok=True)
        messages.success(request, "User restriction re-evaluated.")
    else:
        result = TransitionResult(ok=False, error="Unknown admin action.")

    if not result.ok:
        messages.error(request, result.error or "Action failed.")
    return redirect("reservations:detail", booking_reference=booking_reference)


# ---------------------------------------------------------------------------
# Internal Reservation Management
# ---------------------------------------------------------------------------

@login_required
@capability_required("manage_internal_reservations")
def internal_list(request):
    from reservations.models import InternalReservation
    qs = InternalReservation.objects.all().order_by("-booking_date", "-start_time")
    return render(request, "reservations/internal_list.html", {"reservations": qs})

@login_required
@capability_required("manage_internal_reservations")
def internal_create(request):
    from reservations.forms import InternalReservationForm
    if request.method == "POST":
        form = InternalReservationForm(request.POST)
        if form.is_valid():
            ir = form.save(commit=False)
            ir.created_by = request.user
            ir.save()
            messages.success(request, f"Internal reservation {ir.reference} created successfully.")
            return redirect("reservations:internal_list")
    else:
        form = InternalReservationForm()
    return render(request, "reservations/internal_form.html", {"form": form, "title": "Create Internal Reservation"})

@login_required
@capability_required("manage_internal_reservations")
def internal_edit(request, reference):
    from reservations.models import InternalReservation
    from reservations.forms import InternalReservationForm
    ir = get_object_or_404(InternalReservation, reference=reference)
    if request.method == "POST":
        form = InternalReservationForm(request.POST, instance=ir)
        if form.is_valid():
            form.save()
            messages.success(request, f"Internal reservation {ir.reference} updated successfully.")
            return redirect("reservations:internal_list")
    else:
        form = InternalReservationForm(instance=ir)
    return render(request, "reservations/internal_form.html", {"form": form, "title": f"Edit {ir.reference}"})

@login_required
@capability_required("manage_internal_reservations")
def internal_action(request, reference):
    from reservations.models import InternalReservation, InternalReservationStatus
    ir = get_object_or_404(InternalReservation, reference=reference)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "approve":
            ir.status = InternalReservationStatus.APPROVED
        elif action == "reject":
            ir.status = InternalReservationStatus.REJECTED
        elif action == "cancel":
            ir.status = InternalReservationStatus.CANCELLED
        ir.save()
        messages.success(request, f"Reservation {ir.reference} marked as {ir.status}.")
    return redirect("reservations:internal_list")


@login_required
def validate_coupon(request):
    from payments.models import Coupon
    code = request.GET.get("code", "").strip()
    hall_id = request.GET.get("hall_id")
    if not code:
        return JsonResponse({"valid": False, "message": "No code provided."})
    try:
        coupon = Coupon.objects.get(code__iexact=code)
    except Coupon.DoesNotExist:
        return JsonResponse({"valid": False, "message": "Invalid coupon code."})
    
    if not coupon.is_active:
        return JsonResponse({"valid": False, "message": "This coupon is no longer active."})
    
    from django.utils import timezone
    now = timezone.now()
    if coupon.valid_from and now < coupon.valid_from:
        return JsonResponse({"valid": False, "message": "This coupon is not yet valid."})
    if coupon.valid_until and now > coupon.valid_until:
        return JsonResponse({"valid": False, "message": "This coupon has expired."})
    
    if hall_id and coupon.applicable_halls.exists():
        if not coupon.applicable_halls.filter(id=hall_id).exists():
            return JsonResponse({"valid": False, "message": "This coupon does not apply to the selected hall."})
            
    discount_str = f"{coupon.value}%" if coupon.discount_type == "PERCENTAGE" else f"₦{coupon.value}"
    return JsonResponse({
        "valid": True, 
        "message": f"Valid coupon! {discount_str} discount.",
        "discount_type": coupon.discount_type,
        "value": str(coupon.value)
    })


# ===========================================================================
# Payment Authorization Views (NEW)
# ===========================================================================

@login_required
def payment_authorization_page(request, booking_reference: str):
    """
    GET: Renders the Payment Authorization page for Ventures.
    Shows full booking summary, coupon panel, financial breakdown, and deadline picker.
    POST: Handles coupon action (approve/reject/replace/remove) via AJAX.
    """
    if not _can_manage_ventures(request.user) and not _can_view_all(request.user):
        messages.error(request, "You do not have permission to access the Payment Authorization page.")
        return redirect("reservations:ventures_dashboard")

    reservation = get_object_or_404(
        Reservation.objects.select_related("hall", "user").prefetch_related(
            "coupon_action_logs", "ventures_penalty_records",
        ),
        booking_reference=booking_reference,
    )

    # Guard: only accessible in PAYMENT_AUTHORIZATION or AWAITING_PAYMENT stage
    if reservation.case_status not in (
        BookingCaseStatus.PAYMENT_AUTHORIZATION,
        BookingCaseStatus.AWAITING_PAYMENT,
    ):
        messages.warning(request, f"Booking {booking_reference} is not in the Payment Authorization stage.")
        return redirect("reservations:detail", booking_reference=booking_reference)

    # Lazy expiry check: process any expired deadlines on page load
    _check_and_expire_deadline(reservation)
    if reservation.case_status == BookingCaseStatus.PAYMENT_EXPIRED:
        messages.warning(request, "The payment deadline has expired. This booking has been cancelled.")
        return redirect("reservations:detail", booking_reference=booking_reference)

    # Fetch or initialize PaymentAuthorization
    auth, created = PaymentAuthorization.objects.get_or_create(
        reservation=reservation,
        defaults={
            "authorized_by": request.user,
            "hall_price": reservation.total_cost or 0,
            "security_deposit": reservation.security_deposit or 0,
            "coupon_code": reservation.coupon_code or "",
            "coupon_discount": reservation.discount_amount_applied or 0,
        },
    )

    # Resolve coupon object if present
    coupon_obj = None
    if reservation.coupon_code:
        from payments.models import Coupon
        coupon_obj = Coupon.objects.filter(code=reservation.coupon_code, is_active=True).first()

    # Outstanding penalties
    outstanding_penalties = Penalty.objects.filter(
        reservation=reservation, is_paid=False, is_forgiven=False,
    )

    context = {
        "reservation": reservation,
        "auth": auth,
        "coupon_obj": coupon_obj,
        "outstanding_penalties": outstanding_penalties,
        "coupon_action_logs": reservation.coupon_action_logs.all()[:10],
        "deadline_types": PaymentDeadlineType.choices,
        "penalty_types": VenturesPenaltyType.choices,
        "extension_logs": auth.extension_logs.all() if not created else [],
        "stage_label": reservation.get_case_status_display(),
        "is_awaiting_payment": reservation.case_status == BookingCaseStatus.AWAITING_PAYMENT,
    }
    return render(request, "reservations/payment_authorization.html", context)


@login_required
def submit_payment_authorization(request, booking_reference: str):
    """
    POST: Ventures submits the Payment Authorization.
    Updates financial breakdown, sets deadline, transitions to AWAITING_PAYMENT.
    """
    if not _can_manage_ventures(request.user) and not _can_view_all(request.user):
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse(status=405)

    from django.db import transaction
    from django.utils import timezone as tz
    from datetime import timedelta

    reservation = get_object_or_404(Reservation, booking_reference=booking_reference)

    if reservation.case_status != BookingCaseStatus.PAYMENT_AUTHORIZATION:
        messages.error(request, "Payment Authorization can only be submitted from PAYMENT_AUTHORIZATION stage.")
        return redirect("reservations:payment_authorization", booking_reference=booking_reference)

    with transaction.atomic():
        auth, _ = PaymentAuthorization.objects.select_for_update().get_or_create(
            reservation=reservation,
            defaults={"authorized_by": request.user},
        )

        # ── Financial breakdown ────────────────────────────────────────────────────────
        def _dec(field, fallback="0"):
            try:
                return Decimal(request.POST.get(field) or fallback)
            except Exception:
                return Decimal(fallback)

        auth.hall_price          = _dec("hall_price")
        auth.security_deposit    = _dec("security_deposit")
        auth.extra_charges       = _dec("extra_charges")
        auth.extra_charges_notes = (request.POST.get("extra_charges_notes") or "").strip()
        auth.penalty_amount      = _dec("penalty_amount")
        auth.discount_amount     = _dec("discount_amount")
        auth.coupon_discount     = _dec("coupon_discount")
        auth.vat_rate            = _dec("vat_rate")
        auth.outstanding_balance = _dec("outstanding_balance")
        auth.ventures_notes      = (request.POST.get("ventures_notes") or "").strip()
        auth.authorized_by       = request.user
        auth.compute_total()

        # ── Coupon decision ───────────────────────────────────────────────────────────
        coupon_action = (request.POST.get("coupon_action") or "").strip()
        new_coupon_code = (request.POST.get("new_coupon_code") or "").strip().upper()
        coupon_notes = (request.POST.get("coupon_action_notes") or "").strip()
        if coupon_action:
            auth.coupon_code        = reservation.coupon_code or ""
            auth.coupon_action       = coupon_action
            auth.coupon_action_notes = coupon_notes
            auth.coupon_action_by    = request.user
            auth.coupon_action_at    = tz.now()
            WorkflowService.approve_coupon(
                reservation=reservation,
                actor=request.user,
                coupon_status=coupon_action,
                new_coupon_code=new_coupon_code,
                notes=coupon_notes,
            )

        # ── Payment deadline ───────────────────────────────────────────────────────────
        deadline_type = (request.POST.get("deadline_type") or PaymentDeadlineType.HOURS_48)
        auth.deadline_type = deadline_type
        now = tz.now()
        if deadline_type == PaymentDeadlineType.HOURS_24:
            auth.payment_deadline = now + timedelta(hours=24)
        elif deadline_type == PaymentDeadlineType.HOURS_48:
            auth.payment_deadline = now + timedelta(hours=48)
        elif deadline_type == PaymentDeadlineType.HOURS_72:
            auth.payment_deadline = now + timedelta(hours=72)
        elif deadline_type == PaymentDeadlineType.CUSTOM:
            custom_deadline_str = (request.POST.get("custom_deadline") or "").strip()
            if custom_deadline_str:
                try:
                    auth.payment_deadline = tz.make_aware(
                        datetime.strptime(custom_deadline_str, "%Y-%m-%dT%H:%M")
                    )
                except ValueError:
                    messages.error(request, "Invalid custom deadline format. Please use YYYY-MM-DDTHH:MM.")
                    return redirect("reservations:payment_authorization", booking_reference=booking_reference)

        auth.deadline_set_by = request.user
        auth.deadline_set_at = now
        auth.save()

    # Transition workflow
    result = WorkflowService.submit_payment_authorization(
        reservation=reservation, actor=request.user,
        notes=f"Payment authorization submitted by {request.user.get_full_name() or request.user.email}.",
        auth=auth,
    )

    if result.ok:
        messages.success(request, f"Payment Authorization submitted. Applicant has been notified.")
        return redirect("reservations:detail", booking_reference=booking_reference)
    else:
        messages.error(request, result.error or "Submission failed.")
        return redirect("reservations:payment_authorization", booking_reference=booking_reference)


@login_required
def extend_payment_deadline(request, booking_reference: str):
    """
    POST: Ventures extends or updates the payment deadline.
    Creates a DeadlineExtensionLog and notifies the applicant.
    """
    if not _can_manage_ventures(request.user) and not _can_view_all(request.user):
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse(status=405)

    from django.utils import timezone as tz
    from datetime import timedelta

    reservation = get_object_or_404(Reservation, booking_reference=booking_reference)

    deadline_type = (request.POST.get("deadline_type") or "").strip()
    notes = (request.POST.get("notes") or "").strip()
    now = tz.now()

    if deadline_type == "HOURS_24":
        new_deadline = now + timedelta(hours=24)
    elif deadline_type == "HOURS_48":
        new_deadline = now + timedelta(hours=48)
    elif deadline_type == "HOURS_72":
        new_deadline = now + timedelta(hours=72)
    elif deadline_type == "REMOVE":
        new_deadline = None
    elif deadline_type == "CUSTOM":
        custom_str = (request.POST.get("custom_deadline") or "").strip()
        try:
            new_deadline = tz.make_aware(datetime.strptime(custom_str, "%Y-%m-%dT%H:%M"))
        except (ValueError, Exception) as e:
            messages.error(request, f"Invalid deadline format: {e}")
            return redirect(request.META.get("HTTP_REFERER") or "reservations:detail", booking_reference=booking_reference)
    else:
        messages.error(request, "Invalid deadline type.")
        return redirect(request.META.get("HTTP_REFERER") or "reservations:detail", booking_reference=booking_reference)

    result = WorkflowService.extend_payment_deadline(
        reservation=reservation,
        actor=request.user,
        new_deadline=new_deadline,
        notes=notes,
    )

    if result.ok:
        deadline_str = new_deadline.strftime("%d %b %Y %H:%M") if new_deadline else "removed"
        messages.success(request, f"Payment deadline updated to {deadline_str}.")
    else:
        messages.error(request, result.error or "Failed to update deadline.")

    return redirect(request.META.get("HTTP_REFERER") or "reservations:detail", booking_reference=booking_reference)


@login_required
def ventures_create_penalty_view(request, booking_reference: str):
    """
    POST: Ventures creates a penalty/fee on a reservation case.
    """
    if not _can_manage_ventures(request.user) and not _can_view_all(request.user):
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse(status=405)

    reservation = get_object_or_404(Reservation, booking_reference=booking_reference)

    title         = (request.POST.get("title") or "").strip()
    description   = (request.POST.get("description") or "").strip()
    amount_str    = (request.POST.get("amount") or "0").strip()
    penalty_type  = (request.POST.get("penalty_type") or VenturesPenaltyType.PENALTY).strip()
    notes         = (request.POST.get("notes") or "").strip()

    if not title:
        messages.error(request, "Penalty title is required.")
        return redirect(request.META.get("HTTP_REFERER") or "reservations:detail", booking_reference=booking_reference)

    try:
        amount = Decimal(amount_str)
        if amount <= 0:
            raise ValueError("Amount must be positive.")
    except Exception:
        messages.error(request, "Invalid penalty amount.")
        return redirect(request.META.get("HTTP_REFERER") or "reservations:detail", booking_reference=booking_reference)

    result = WorkflowService.ventures_create_penalty(
        reservation=reservation,
        actor=request.user,
        title=title,
        description=description,
        amount=amount,
        penalty_type=penalty_type,
        notes=notes,
    )

    if result.ok:
        messages.success(request, f"Penalty '{title}' of ₦{amount} created successfully.")
    else:
        messages.error(request, result.error or "Failed to create penalty.")

    return redirect(request.META.get("HTTP_REFERER") or "reservations:detail", booking_reference=booking_reference)


@login_required
def admin_forgive_liability_view(request, booking_reference: str):
    """
    POST: Admin forgives outstanding damage/penalty liabilities for a booking.
    Requires a reason. Creates audit log and timeline event.
    """
    if not _can_view_all(request.user):
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse(status=405)

    reservation = get_object_or_404(Reservation, booking_reference=booking_reference)
    reason = (request.POST.get("reason") or "").strip()

    if not reason:
        messages.error(request, "A reason is required to forgive liability.")
        return redirect(request.META.get("HTTP_REFERER") or "reservations:detail", booking_reference=booking_reference)

    result = WorkflowService.admin_forgive_liability(
        reservation=reservation,
        actor=request.user,
        reason=reason,
        forgive_all=True,
    )

    if result.ok:
        messages.success(request, "Liability forgiven and user restrictions updated.")
    else:
        messages.error(request, result.error or "Failed to forgive liability.")

    return redirect(request.META.get("HTTP_REFERER") or "reservations:detail", booking_reference=booking_reference)


@login_required
def facility_create_damage(request, booking_reference: str):
    """
    POST: Facility or Ventures creates a DamageReport on a booking.
    Ventures can also create damage (per policy). Facility can create damage only.
    """
    if not _can_manage_facility(request.user) and not _can_manage_ventures(request.user) and not _can_view_all(request.user):
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse(status=405)

    reservation = get_object_or_404(Reservation, booking_reference=booking_reference)
    description = (request.POST.get("description") or "").strip()
    amount_str = (request.POST.get("amount") or "").strip()
    affected_items = (request.POST.get("affected_items") or "").strip()

    if not description:
        messages.error(request, "Damage description is required.")
        return redirect(request.META.get("HTTP_REFERER") or "reservations:detail", booking_reference=booking_reference)

    try:
        amount = Decimal(amount_str)
        if amount < 0:
            raise ValueError("Amount cannot be negative.")
    except Exception:
        messages.error(request, "Invalid damage amount.")
        return redirect(request.META.get("HTTP_REFERER") or "reservations:detail", booking_reference=booking_reference)

    from reservations.models import DamageReport
    damage = DamageReport.objects.create(
        reservation=reservation,
        user=reservation.user,
        amount=amount,
        description=description,
        affected_items=affected_items,
    )

    from core.models import AuditLog
    create_audit_log(
        user=request.user,
        action=f"facility_create_damage:{booking_reference}",
        model_name="DamageReport",
        object_repr=str(damage),
        new_value=f"₦{amount} — {description}",
    )

    from reservations.signals import _sync_user_block_status
    _sync_user_block_status(reservation.user)

    messages.success(request, f"Damage report created for ₦{amount}.")
    return redirect(request.META.get("HTTP_REFERER") or "reservations:detail", booking_reference=booking_reference)


# ---------------------------------------------------------------------------
# Internal helper: lazy deadline expiry check
# ---------------------------------------------------------------------------

def _check_and_expire_deadline(reservation: Reservation) -> None:
    """
    Called on page load to lazily expire any bookings whose payment deadline has passed.
    This supplements the cron-based management command.
    """
    if reservation.case_status != BookingCaseStatus.AWAITING_PAYMENT:
        return
    try:
        auth = reservation.payment_authorization
    except Exception:
        return
    if auth and auth.payment_deadline and not auth.is_expired:
        from django.utils import timezone as tz
        if tz.now() >= auth.payment_deadline:
            WorkflowService.expire_payment(reservation=reservation)
