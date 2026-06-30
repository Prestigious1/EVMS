from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.utils import timezone

from core.services import create_audit_log, notify_user
from reservations.models import (
    BookingCaseStatus,
    BookingLog,
    BookingStatusHistory,
    BookingTimeline,
    CommunicationThread,
    CouponActionLog,
    CouponActionChoice,
    DeadlineExtensionLog,
    HallInspectionReport,
    InspectionOutcome,
    InspectionReminder,
    PaymentAuthorization,
    PaymentDeadlineType,
    Reservation,
    ReservationStatus,
    TimelineEventType,
    VenturesPenaltyRecord,
    VenturesPenaltyType,
)


@dataclass
class TransitionResult:
    ok: bool
    error: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_timeline(
    *,
    reservation: Reservation,
    event_type: str,
    title: str,
    description: str = "",
    actor=None,
) -> BookingTimeline:
    role = getattr(actor, "role", "") if actor else ""
    return BookingTimeline.objects.create(
        reservation=reservation,
        event_type=event_type,
        title=title,
        description=description,
        actor=actor,
        actor_role=role,
    )


def _ensure_thread(reservation: Reservation) -> CommunicationThread:
    """Creates communication thread if it doesn't exist yet."""
    thread, _ = CommunicationThread.objects.get_or_create(reservation=reservation)
    return thread


def _notify_roles(
    *,
    reservation: Reservation,
    roles: list[str],
    title: str,
    message: str,
    link: str | None = None,
) -> None:
    from django.contrib.auth import get_user_model
    User = get_user_model()
    for user in User.objects.filter(role__in=roles, is_active=True):
        notify_user(user=user, title=title, message=message, link=link)


def _booking_link(reservation: Reservation) -> str:
    from django.urls import reverse
    return reverse("reservations:detail", args=[reservation.booking_reference])


# ---------------------------------------------------------------------------
# WorkflowService — full 12-phase lifecycle engine
# ---------------------------------------------------------------------------

class WorkflowService:
    """
    Centralized booking case workflow engine.
    Enforces state machine transitions using BookingCaseStatus.
    Every transition writes: StatusHistory, BookingLog, Timeline, AuditLog, Notifications.
    """

    VALID_TRANSITIONS: dict[str, set[str]] = {
        BookingCaseStatus.DRAFT: {
            BookingCaseStatus.SUBMITTED,
        },
        BookingCaseStatus.SUBMITTED: {
            BookingCaseStatus.UNDER_VENTURES_REVIEW,
            BookingCaseStatus.BOOKING_REJECTED,
            BookingCaseStatus.UNDER_FACILITY_REVIEW,
        },
        BookingCaseStatus.UNDER_VENTURES_REVIEW: {
            BookingCaseStatus.UNDER_FACILITY_REVIEW,
            BookingCaseStatus.BOOKING_REJECTED,
        },
        BookingCaseStatus.UNDER_FACILITY_REVIEW: {
            BookingCaseStatus.FACILITY_APPROVED,
            BookingCaseStatus.FACILITY_REJECTED,
        },
        BookingCaseStatus.FACILITY_APPROVED: {
            BookingCaseStatus.PAYMENT_AUTHORIZATION,   # Ventures opens payment auth page
            BookingCaseStatus.BOOKING_REJECTED,
        },
        BookingCaseStatus.FACILITY_REJECTED: {
            BookingCaseStatus.UNDER_VENTURES_REVIEW,  # Returns to Ventures for re-evaluation
            BookingCaseStatus.BOOKING_REJECTED,
        },
        BookingCaseStatus.PAYMENT_AUTHORIZATION: {
            BookingCaseStatus.AWAITING_PAYMENT,       # Ventures submits payment request
            BookingCaseStatus.BOOKING_REJECTED,
        },
        BookingCaseStatus.AWAITING_PAYMENT: {
            BookingCaseStatus.PAYMENT_SUBMITTED,
            BookingCaseStatus.PAYMENT_VERIFIED,       # Paystack online payment
            BookingCaseStatus.PAYMENT_EXPIRED,        # Deadline lapsed — auto-cancelled
            BookingCaseStatus.BOOKING_REJECTED,
        },
        BookingCaseStatus.PAYMENT_SUBMITTED: {
            BookingCaseStatus.UNDER_BURSARY_VERIFICATION,
        },
        BookingCaseStatus.UNDER_BURSARY_VERIFICATION: {
            BookingCaseStatus.PAYMENT_VERIFIED,
            BookingCaseStatus.PAYMENT_REJECTED,
        },
        BookingCaseStatus.PAYMENT_REJECTED: {
            BookingCaseStatus.AWAITING_PAYMENT,     # Applicant re-uploads
        },
        BookingCaseStatus.PAYMENT_VERIFIED: {
            BookingCaseStatus.AWAITING_FINAL_APPROVAL,
        },
        BookingCaseStatus.AWAITING_FINAL_APPROVAL: {
            BookingCaseStatus.BOOKING_APPROVED,
            BookingCaseStatus.BOOKING_REJECTED,
        },
        BookingCaseStatus.BOOKING_APPROVED: {
            BookingCaseStatus.EVENT_COMPLETED,
        },
        BookingCaseStatus.EVENT_COMPLETED: {
            BookingCaseStatus.UNDER_POST_EVENT_INSPECTION,
        },
        BookingCaseStatus.UNDER_POST_EVENT_INSPECTION: {
            BookingCaseStatus.CASE_CLOSED,          # No damage outcome
            BookingCaseStatus.DAMAGE_ASSESSED,      # Damage found
        },
        BookingCaseStatus.DAMAGE_ASSESSED: {
            BookingCaseStatus.AWAITING_DAMAGE_PAYMENT,
        },
        BookingCaseStatus.AWAITING_DAMAGE_PAYMENT: {
            BookingCaseStatus.DAMAGE_PAYMENT_SUBMITTED,
        },
        BookingCaseStatus.DAMAGE_PAYMENT_SUBMITTED: {
            BookingCaseStatus.UNDER_DAMAGE_PAYMENT_VERIFICATION,
        },
        BookingCaseStatus.UNDER_DAMAGE_PAYMENT_VERIFICATION: {
            BookingCaseStatus.DAMAGE_PAYMENT_VERIFIED,
            BookingCaseStatus.AWAITING_DAMAGE_PAYMENT,  # Rejected — re-upload
        },
        BookingCaseStatus.DAMAGE_PAYMENT_VERIFIED: {
            BookingCaseStatus.CASE_CLOSED,
        },
        # Terminal states
        BookingCaseStatus.CASE_CLOSED:      set(),
        BookingCaseStatus.BOOKING_REJECTED: set(),
        BookingCaseStatus.PAYMENT_EXPIRED:  set(),   # NEW terminal state
        BookingCaseStatus.USER_RESTRICTED:  set(),
    }

    LEGACY_VALID_TRANSITIONS: dict[str, set[str]] = {
        ReservationStatus.SUBMITTED: {
            ReservationStatus.FORWARDED,
            ReservationStatus.UNDER_REVIEW,
            ReservationStatus.REJECTED,
            ReservationStatus.CANCELLED,
        },
        ReservationStatus.FORWARDED: {
            ReservationStatus.AVAILABLE,
            ReservationStatus.REJECTED,
            ReservationStatus.CANCELLED,
        },
        ReservationStatus.UNDER_REVIEW: {
            ReservationStatus.FORWARDED,
            ReservationStatus.AVAILABLE,
            ReservationStatus.REJECTED,
            ReservationStatus.CANCELLED,
        },
        ReservationStatus.AVAILABLE: {
            ReservationStatus.APPROVED_PAYMENT,
            ReservationStatus.REJECTED,
            ReservationStatus.CANCELLED,
        },
        ReservationStatus.APPROVED_PAYMENT: {
            ReservationStatus.PAYMENT_PENDING,
            ReservationStatus.CONFIRMED,
            ReservationStatus.CANCELLED,
            ReservationStatus.REJECTED,
        },
        ReservationStatus.PAYMENT_PENDING: {
            ReservationStatus.PAID,
            ReservationStatus.CANCELLED,
        },
        ReservationStatus.PAID: {
            ReservationStatus.CONFIRMED,
            ReservationStatus.CANCELLED,
        },
        ReservationStatus.CONFIRMED: {
            ReservationStatus.COMPLETED,
            ReservationStatus.CANCELLED,
        },
        ReservationStatus.COMPLETED: {
            ReservationStatus.INSPECTION_PENDING,
            ReservationStatus.CLOSED,
        },
        ReservationStatus.INSPECTION_PENDING: {
            ReservationStatus.DAMAGE_REPORTED,
            ReservationStatus.CLOSED,
        },
        ReservationStatus.DAMAGE_REPORTED: {
            ReservationStatus.CLOSED,
        },
        ReservationStatus.CLOSED: set(),
        ReservationStatus.REJECTED: set(),
        ReservationStatus.CANCELLED: set(),
        ReservationStatus.PENDING: {ReservationStatus.APPROVED, ReservationStatus.CANCELLED, ReservationStatus.REJECTED},
        ReservationStatus.APPROVED: {ReservationStatus.CANCELLED, ReservationStatus.COMPLETED},
    }

    @classmethod
    def _allowed_next(cls, current: str, use_legacy: bool = False) -> set:
        if use_legacy:
            return cls.LEGACY_VALID_TRANSITIONS.get(current, set())
        return cls.VALID_TRANSITIONS.get(current, set())

    @classmethod
    def transition(
        cls,
        *,
        reservation: Reservation,
        to_status: str,
        actor=None,
        notes: str = "",
        use_legacy: bool = False,
    ) -> TransitionResult:
        """
        Core transition method.
        By default operates on case_status (new lifecycle).
        Pass use_legacy=True to operate on the legacy status field (for backward compat).
        """
        with transaction.atomic():
            locked_res = Reservation.objects.select_for_update().get(pk=reservation.pk)

            if use_legacy:
                current = locked_res.status
            else:
                current = locked_res.case_status

            if current == to_status:
                return TransitionResult(ok=True)

            allowed = cls._allowed_next(current, use_legacy=use_legacy)
            if to_status not in allowed:
                return TransitionResult(
                    ok=False,
                    error=f"Invalid transition from '{current}' to '{to_status}'.",
                )

            old_status = current

            if use_legacy:
                locked_res.status = to_status
            else:
                locked_res.case_status = to_status
                # Keep legacy status roughly in sync for calendar/dashboard queries
                _sync_legacy_status(locked_res, to_status)

            locked_res.save()
            reservation.case_status = locked_res.case_status
            reservation.status = locked_res.status

            BookingStatusHistory.objects.create(
                reservation=reservation,
                previous_status=old_status,
                new_status=to_status,
                changed_by=actor,
                notes=notes,
            )
            BookingLog.objects.create(
                reservation=reservation,
                actor=actor,
                action=f"status_change:{old_status}->{to_status}",
                details=notes,
            )
            create_audit_log(
                user=actor or reservation.user,
                action=f"reservation_status:{reservation.booking_reference}:{old_status}->{to_status}",
                model_name="Reservation",
                object_repr=str(reservation),
                old_value=old_status,
                new_value=to_status,
            )

            # Ensure thread exists
            _ensure_thread(reservation)

            cls._notify_status_change(reservation=reservation, old_status=old_status, new_status=to_status)

        return TransitionResult(ok=True)

    @classmethod
    def _notify_status_change(cls, *, reservation: Reservation, old_status: str, new_status: str) -> None:
        link = _booking_link(reservation)
        applicant = reservation.user

        # Always notify applicant of case progression (unless internal-only transitions)
        APPLICANT_NOTIFY_STATES = {
            BookingCaseStatus.UNDER_VENTURES_REVIEW,
            BookingCaseStatus.UNDER_FACILITY_REVIEW,
            BookingCaseStatus.FACILITY_APPROVED,
            BookingCaseStatus.FACILITY_REJECTED,
            BookingCaseStatus.AWAITING_PAYMENT,
            BookingCaseStatus.PAYMENT_SUBMITTED,
            BookingCaseStatus.PAYMENT_VERIFIED,
            BookingCaseStatus.PAYMENT_REJECTED,
            BookingCaseStatus.BOOKING_APPROVED,
            BookingCaseStatus.BOOKING_REJECTED,
            BookingCaseStatus.EVENT_COMPLETED,
            BookingCaseStatus.DAMAGE_ASSESSED,
            BookingCaseStatus.AWAITING_DAMAGE_PAYMENT,
            BookingCaseStatus.DAMAGE_PAYMENT_VERIFIED,
            BookingCaseStatus.CASE_CLOSED,
        }
        if new_status in APPLICANT_NOTIFY_STATES:
            label = dict(BookingCaseStatus.choices).get(new_status, new_status)
            notify_user(
                user=applicant,
                title=f"Booking Update — {reservation.booking_reference}",
                message=(
                    f"Your booking for {reservation.hall.name} on {reservation.booking_date} "
                    f"has been updated to: {label}."
                ),
                link=link,
            )

        # Notify Ventures on submission
        if new_status == BookingCaseStatus.SUBMITTED:
            _notify_roles(
                reservation=reservation, roles=["VENTURES", "ADMIN"],
                title="New Booking Submitted",
                message=f"Booking {reservation.booking_reference} from {reservation.user.get_full_name() or reservation.user.email} requires Ventures review.",
                link=link + "#ventures",
            )

        # Notify Facility when forwarded
        if new_status == BookingCaseStatus.UNDER_FACILITY_REVIEW:
            _notify_roles(
                reservation=reservation, roles=["FACILITY", "ADMIN"],
                title="New Booking for Facility Review",
                message=f"Booking {reservation.booking_reference} has been forwarded for facility review.",
                link=link + "#facility",
            )

        # Notify Ventures when Facility approves/rejects — prompt them to open Payment Auth
        if new_status in (BookingCaseStatus.FACILITY_APPROVED, BookingCaseStatus.FACILITY_REJECTED):
            label = "Approved" if new_status == BookingCaseStatus.FACILITY_APPROVED else "Rejected"
            extra = " Please open Payment Authorization to continue." if new_status == BookingCaseStatus.FACILITY_APPROVED else ""
            _notify_roles(
                reservation=reservation, roles=["VENTURES", "ADMIN"],
                title=f"Facility {label} Booking {reservation.booking_reference}",
                message=f"Facility has {label.lower()} booking {reservation.booking_reference}.{extra}",
                link=link + "#ventures",
            )

        # Notify Applicant + Bursary when payment authorization is submitted (AWAITING_PAYMENT)
        if new_status == BookingCaseStatus.AWAITING_PAYMENT:
            notify_user(
                user=applicant,
                title=f"Payment Request — {reservation.booking_reference}",
                message=(
                    f"Ventures has authorized payment for your booking at {reservation.hall.name}. "
                    f"Please log in to view the payment breakdown and complete payment."
                ),
                link=link,
            )
            _notify_roles(
                reservation=reservation, roles=["BURSARY", "ADMIN"],
                title=f"Payment Authorized — {reservation.booking_reference}",
                message=(
                    f"Payment has been authorized for booking {reservation.booking_reference}. "
                    f"Applicant: {reservation.user.get_full_name() or reservation.user.email}. "
                    f"Awaiting payment from applicant."
                ),
                link=link + "#bursary",
            )

        # Notify Applicant when payment expires
        if new_status == BookingCaseStatus.PAYMENT_EXPIRED:
            notify_user(
                user=applicant,
                title=f"Payment Deadline Expired — {reservation.booking_reference}",
                message=(
                    f"The payment deadline for your booking at {reservation.hall.name} has expired. "
                    f"Your booking has been cancelled. You may submit a new application."
                ),
                link=link,
            )
            _notify_roles(
                reservation=reservation, roles=["VENTURES", "FACILITY", "BURSARY", "ADMIN"],
                title=f"Payment Expired — {reservation.booking_reference}",
                message=(
                    f"Payment deadline has expired for booking {reservation.booking_reference}. "
                    f"Booking has been cancelled and hall released."
                ),
                link=link,
            )

        # Notify Bursary when payment is submitted
        if new_status in (BookingCaseStatus.PAYMENT_SUBMITTED, BookingCaseStatus.DAMAGE_PAYMENT_SUBMITTED):
            _notify_roles(
                reservation=reservation, roles=["BURSARY", "ADMIN"],
                title="Payment Proof Awaiting Verification",
                message=f"Payment proof uploaded for booking {reservation.booking_reference}. Please review.",
                link=link + "#bursary",
            )

        # Notify Ventures when payment is verified
        if new_status == BookingCaseStatus.PAYMENT_VERIFIED:
            _notify_roles(
                reservation=reservation, roles=["VENTURES", "ADMIN"],
                title="Payment Verified",
                message=f"Bursary has verified payment for {reservation.booking_reference}.",
                link=link + "#ventures",
            )

        # Notify Ventures when awaiting final approval
        if new_status == BookingCaseStatus.AWAITING_FINAL_APPROVAL:
            _notify_roles(
                reservation=reservation, roles=["VENTURES", "ADMIN"],
                title="Awaiting Final Approval",
                message=f"Payment for {reservation.booking_reference} is verified. Please perform final approval.",
                link=link + "#ventures",
            )

        # Notify Ventures + Facility when damage payment is verified
        if new_status == BookingCaseStatus.DAMAGE_PAYMENT_VERIFIED:
            _notify_roles(
                reservation=reservation, roles=["VENTURES", "FACILITY", "ADMIN"],
                title="Damage Payment Verified",
                message=f"Damage payment for booking {reservation.booking_reference} has been verified.",
                link=link + "#ventures",
            )

        # Legacy support: notify Ventures on AVAILABLE
        if new_status == ReservationStatus.AVAILABLE:
            _notify_roles(
                reservation=reservation, roles=["VENTURES", "ADMIN"],
                title="Hall Availability Confirmed",
                message=f"Facility confirmed availability for {reservation.booking_reference}.",
                link=link + "#ventures",
            )

    # =========================================================================
    # Phase 1 — Booking Submission
    # =========================================================================

    @classmethod
    def submit_reservation(cls, *, reservation: Reservation, actor=None) -> TransitionResult:
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.SUBMITTED,
            actor=actor,
            notes="Booking case submitted by applicant.",
        )
        if result.ok:
            _ensure_thread(reservation)
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.BOOKING_SUBMITTED,
                title="Booking Submitted",
                description=f"Booking submitted for {reservation.hall.name} on {reservation.booking_date}.",
                actor=actor,
            )
        return result

    # =========================================================================
    # Phase 2 — Ventures Review
    # =========================================================================

    @classmethod
    def ventures_review(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.UNDER_VENTURES_REVIEW,
            actor=actor,
            notes=notes or "Booking under Ventures review.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.VENTURES_REVIEW_STARTED,
                title="Under Ventures Review",
                description=notes or "Ventures has started reviewing this booking.",
                actor=actor,
            )
        return result

    @classmethod
    def ventures_reject(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.BOOKING_REJECTED,
            actor=actor,
            notes=notes or "Rejected by Ventures.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.BOOKING_REJECTED,
                title="Booking Rejected by Ventures",
                description=notes,
                actor=actor,
            )
        return result

    # =========================================================================
    # Phase 3 — Facility Review
    # =========================================================================

    @classmethod
    def forward_to_facility(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.UNDER_FACILITY_REVIEW,
            actor=actor,
            notes=notes or "Forwarded to Facility for hall availability review.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.FORWARDED_TO_FACILITY,
                title="Forwarded to Facility",
                description=notes or "Sent to Facility Management for hall availability review.",
                actor=actor,
            )
        return result

    @classmethod
    def facility_approve(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.FACILITY_APPROVED,
            actor=actor,
            notes=notes or "Facility has approved hall availability.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.FACILITY_APPROVED,
                title="Facility Approved",
                description=notes or "Facility Management confirmed hall availability and operational readiness.",
                actor=actor,
            )
        return result

    @classmethod
    def facility_reject(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.FACILITY_REJECTED,
            actor=actor,
            notes=notes or "Facility rejected the booking.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.FACILITY_REJECTED,
                title="Facility Rejected",
                description=notes or "Facility Management rejected the booking (unavailability or maintenance conflict).",
                actor=actor,
            )
        return result

    @classmethod
    def return_to_ventures(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        """Used when Facility rejects but Ventures wants to re-evaluate."""
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.UNDER_VENTURES_REVIEW,
            actor=actor,
            notes=notes or "Returned to Ventures after facility rejection.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.RETURNED_TO_VENTURES,
                title="Returned to Ventures",
                description=notes or "Case returned to Ventures following facility rejection.",
                actor=actor,
            )
        return result

    # =========================================================================
    # Phase 4 — Payment Authorization (NEW) — Ventures prepares financial breakdown
    # =========================================================================

    @classmethod
    def open_payment_authorization(
        cls, *, reservation: Reservation, actor=None, notes: str = "",
    ) -> TransitionResult:
        """Ventures opens the Payment Authorization page — transitions FACILITY_APPROVED → PAYMENT_AUTHORIZATION."""
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.PAYMENT_AUTHORIZATION,
            actor=actor,
            notes=notes or "Payment Authorization stage opened by Ventures.",
        )
        if result.ok:
            # Create a draft PaymentAuthorization if not already present
            auth, created = PaymentAuthorization.objects.get_or_create(
                reservation=reservation,
                defaults={
                    "authorized_by": actor,
                    "hall_price": reservation.total_cost or 0,
                    "security_deposit": reservation.security_deposit or 0,
                    "coupon_code": reservation.coupon_code or "",
                    "coupon_discount": reservation.discount_amount_applied or 0,
                },
            )
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.PAYMENT_AUTHORIZATION_OPENED,
                title="Payment Authorization Opened",
                description=notes or "Ventures has opened the Payment Authorization stage to review billing, coupons, and set a payment deadline.",
                actor=actor,
            )
        return result

    @classmethod
    def submit_payment_authorization(
        cls,
        *,
        reservation: Reservation,
        actor=None,
        notes: str = "",
        auth: "PaymentAuthorization | None" = None,
    ) -> TransitionResult:
        """
        Ventures submits the Payment Authorization.
        Transitions PAYMENT_AUTHORIZATION → AWAITING_PAYMENT.
        Notifies Applicant + Bursary.
        """
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.AWAITING_PAYMENT,
            actor=actor,
            notes=notes or "Payment Authorization submitted. Applicant payment requested.",
        )
        if result.ok:
            from django.utils import timezone as tz
            # Mark authorization as submitted
            if auth:
                auth.is_submitted = True
                auth.submitted_at = tz.now()
                auth.save(update_fields=["is_submitted", "submitted_at"])
            # Update reservation financial fields from authorization
            if auth:
                reservation.total_cost = auth.total_amount
                reservation.security_deposit = auth.security_deposit
                reservation.save(update_fields=["total_cost", "security_deposit"])

            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.PAYMENT_AUTHORIZATION_SUBMITTED,
                title="Payment Authorization Submitted",
                description=(
                    f"Payment request sent to applicant. "
                    f"Total: ₦{auth.total_amount if auth else reservation.total_cost}. "
                    f"Deadline: {auth.payment_deadline.strftime('%d %b %Y %H:%M') if auth and auth.payment_deadline else 'No deadline set'}."
                ),
                actor=actor,
            )
            if auth and auth.payment_deadline:
                _add_timeline(
                    reservation=reservation,
                    event_type=TimelineEventType.PAYMENT_DEADLINE_SET,
                    title="Payment Deadline Set",
                    description=f"Payment must be completed by {auth.payment_deadline.strftime('%d %b %Y %H:%M')}.",
                    actor=actor,
                )
        return result

    @classmethod
    def extend_payment_deadline(
        cls,
        *,
        reservation: Reservation,
        actor=None,
        new_deadline,  # datetime or None (remove deadline)
        notes: str = "",
    ) -> TransitionResult:
        """
        Ventures extends, shortens, or removes the payment deadline.
        Creates a DeadlineExtensionLog and timeline event.
        """
        from django.utils import timezone as tz
        with transaction.atomic():
            try:
                auth = PaymentAuthorization.objects.select_for_update().get(reservation=reservation)
            except PaymentAuthorization.DoesNotExist:
                return TransitionResult(ok=False, error="No Payment Authorization found for this booking.")

            old_deadline = auth.payment_deadline

            # Determine action type
            if new_deadline is None:
                action = DeadlineExtensionLog.Action.REMOVED
            elif old_deadline and new_deadline > old_deadline:
                action = DeadlineExtensionLog.Action.EXTENDED
            else:
                action = DeadlineExtensionLog.Action.SHORTENED

            auth.payment_deadline = new_deadline
            auth.deadline_extended = True
            auth.deadline_extension_count = (auth.deadline_extension_count or 0) + 1
            auth.save(update_fields=["payment_deadline", "deadline_extended", "deadline_extension_count"])

            DeadlineExtensionLog.objects.create(
                authorization=auth,
                old_deadline=old_deadline,
                new_deadline=new_deadline,
                action=action,
                actor=actor,
                notes=notes,
            )

            deadline_str = new_deadline.strftime('%d %b %Y %H:%M') if new_deadline else "No deadline"
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.PAYMENT_DEADLINE_EXTENDED,
                title=f"Payment Deadline {action.title()}",
                description=f"New deadline: {deadline_str}. Reason: {notes}",
                actor=actor,
            )
            create_audit_log(
                user=actor or reservation.user,
                action=f"payment_deadline_{action.lower()}:{reservation.booking_reference}",
                model_name="PaymentAuthorization",
                object_repr=str(auth),
                old_value=str(old_deadline),
                new_value=str(new_deadline),
            )
            BookingLog.objects.create(
                reservation=reservation,
                actor=actor,
                action=f"payment_deadline_{action.lower()}",
                details=f"Old: {old_deadline} → New: {new_deadline}. {notes}",
            )
            # Notify applicant of deadline change
            notify_user(
                user=reservation.user,
                title=f"Payment Deadline Updated — {reservation.booking_reference}",
                message=f"Your payment deadline has been updated. New deadline: {deadline_str}.",
                link=_booking_link(reservation),
            )
        return TransitionResult(ok=True)

    @classmethod
    def expire_payment(cls, *, reservation: Reservation) -> TransitionResult:
        """
        System-triggered expiry when payment deadline passes.
        Transitions AWAITING_PAYMENT → PAYMENT_EXPIRED.
        Releases hall reservation and notifies all parties.
        """
        from django.utils import timezone as tz
        with transaction.atomic():
            locked_res = Reservation.objects.select_for_update().get(pk=reservation.pk)
            if locked_res.case_status != BookingCaseStatus.AWAITING_PAYMENT:
                return TransitionResult(
                    ok=False,
                    error=f"Cannot expire — booking is in '{locked_res.case_status}' (expected AWAITING_PAYMENT).",
                )
            # Mark auth as expired
            try:
                auth = PaymentAuthorization.objects.get(reservation=reservation)
                auth.is_expired = True
                auth.expired_at = tz.now()
                auth.save(update_fields=["is_expired", "expired_at"])
            except PaymentAuthorization.DoesNotExist:
                pass

        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.PAYMENT_EXPIRED,
            actor=None,
            notes="System: payment deadline expired. Booking auto-cancelled. Hall released.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.PAYMENT_DEADLINE_EXPIRED,
                title="Payment Deadline Expired — Booking Cancelled",
                description="The payment deadline has passed without payment. Booking cancelled and hall availability released.",
                actor=None,
            )
        return result

    # =========================================================================
    # Phase 4b — Coupon & Billing Review (Ventures)
    # =========================================================================

    @classmethod
    def approve_coupon(
        cls, *,
        reservation: Reservation,
        actor=None,
        coupon_status: str = "APPROVED",
        new_coupon_code: str = "",
        notes: str = "",
    ) -> None:
        """
        Records Ventures coupon decision on the reservation.
        Also creates an immutable CouponActionLog entry.
        """
        from django.utils import timezone as tz
        old_code = reservation.coupon_code or ""

        if coupon_status == "REPLACED" and new_coupon_code:
            reservation.coupon_code = new_coupon_code
        elif coupon_status == "REMOVED":
            reservation.coupon_code = ""

        reservation.coupon_status = coupon_status
        reservation.coupon_approval_notes = notes
        reservation.coupon_approved_by = actor
        reservation.coupon_approved_at = tz.now()
        reservation.save(update_fields=[
            "coupon_code", "coupon_status", "coupon_approval_notes",
            "coupon_approved_by", "coupon_approved_at",
        ])

        # Permanent coupon action log
        action_map = {
            "APPROVED": CouponActionChoice.APPROVED,
            "REJECTED": CouponActionChoice.REJECTED,
            "REPLACED": CouponActionChoice.REPLACED,
            "REMOVED":  CouponActionChoice.REMOVED,
        }
        CouponActionLog.objects.create(
            reservation=reservation,
            action=action_map.get(coupon_status, CouponActionChoice.APPLIED),
            coupon_code=reservation.coupon_code or old_code,
            actor=actor,
            actor_role=getattr(actor, "role", "") if actor else "",
            old_code=old_code,
            notes=notes,
        )

        _add_timeline(
            reservation=reservation,
            event_type=TimelineEventType.COUPON_ACTION,
            title=f"Coupon {coupon_status.title()}",
            description=f"Coupon '{reservation.coupon_code or old_code}' was {coupon_status.lower()} by Ventures. Notes: {notes}",
            actor=actor,
        )

    @classmethod
    def billing_complete(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        """
        Legacy: Called after Ventures completes billing review.
        In new flow, use open_payment_authorization() + submit_payment_authorization() instead.
        Preserved for backward compat: transitions directly to AWAITING_PAYMENT via PAYMENT_AUTHORIZATION.
        """
        # Open auth stage silently if not already there
        if reservation.case_status == BookingCaseStatus.FACILITY_APPROVED:
            cls.open_payment_authorization(reservation=reservation, actor=actor, notes="Auto-opened via billing_complete.")

        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.AWAITING_PAYMENT,
            actor=actor,
            notes=notes or "Billing review complete. Awaiting applicant payment.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.BILLING_CONFIRMED,
                title="Billing Confirmed — Awaiting Payment",
                description=f"Ventures confirmed billing. Total: ₦{reservation.total_cost}. {notes}",
                actor=actor,
            )
        return result

    # =========================================================================
    # Phase 5 — Payment Submission (Applicant)
    # =========================================================================

    @classmethod
    def submit_payment_proof(cls, *, reservation: Reservation, actor=None, proof=None, notes: str = "") -> TransitionResult:
        """Applicant submits payment receipt. Moves to PAYMENT_SUBMITTED → UNDER_BURSARY_VERIFICATION."""
        # First move to PAYMENT_SUBMITTED
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.PAYMENT_SUBMITTED,
            actor=actor,
            notes=notes or "Applicant uploaded payment proof.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.PAYMENT_PROOF_UPLOADED,
                title="Payment Proof Uploaded",
                description=notes or "Applicant has uploaded payment evidence. Pending Bursary verification.",
                actor=actor,
            )
            # Immediately advance to UNDER_BURSARY_VERIFICATION
            cls.transition(
                reservation=reservation,
                to_status=BookingCaseStatus.UNDER_BURSARY_VERIFICATION,
                actor=None,
                notes="System: forwarded to Bursary verification queue.",
            )
        return result

    # =========================================================================
    # Phase 6 — Bursary Verification
    # =========================================================================

    @classmethod
    def bursary_verify_payment(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.PAYMENT_VERIFIED,
            actor=actor,
            notes=notes or "Payment verified by Bursary.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.PAYMENT_VERIFIED,
                title="Payment Verified by Bursary",
                description=notes or "Bursary has verified the payment proof. Case forwarded for final Ventures approval.",
                actor=actor,
            )
            # Auto-advance to AWAITING_FINAL_APPROVAL
            cls.transition(
                reservation=reservation,
                to_status=BookingCaseStatus.AWAITING_FINAL_APPROVAL,
                actor=None,
                notes="System: all prerequisites met — awaiting final Ventures approval.",
            )
        return result

    @classmethod
    def bursary_reject_payment(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.PAYMENT_REJECTED,
            actor=actor,
            notes=notes or "Payment proof rejected by Bursary.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.PAYMENT_REJECTED,
                title="Payment Proof Rejected",
                description=notes or "Bursary rejected the payment proof. Applicant must re-upload.",
                actor=actor,
            )
            # Return to AWAITING_PAYMENT so applicant can re-upload
            cls.transition(
                reservation=reservation,
                to_status=BookingCaseStatus.AWAITING_PAYMENT,
                actor=None,
                notes="System: applicant notified to re-submit payment proof.",
            )
        return result

    @classmethod
    def bursary_request_clarification(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        """
        Bursary requests clarification regarding payment evidence.
        Status does not change, but timeline/messages are updated.
        """
        with transaction.atomic():
            locked_res = Reservation.objects.select_for_update().get(pk=reservation.pk)
            
            if locked_res.case_status not in (BookingCaseStatus.UNDER_BURSARY_VERIFICATION, BookingCaseStatus.UNDER_DAMAGE_PAYMENT_VERIFICATION):
                return TransitionResult(
                    ok=False,
                    error=f"Cannot request clarification from status '{locked_res.case_status}'."
                )

            thread = _ensure_thread(reservation)
            
            from reservations.models import ThreadMessage, MessageType
            ThreadMessage.objects.create(
                thread=thread,
                sender=actor,
                content=notes or "Please provide clarification regarding your payment evidence.",
                message_type=MessageType.APPLICANT_VISIBLE,
            )

            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.INFORMATION_REQUESTED,
                title="Bursary Clarification Requested",
                description="Bursary has requested additional information regarding payment.",
                actor=actor,
            )
            
            BookingLog.objects.create(
                reservation=reservation,
                actor=actor,
                action="bursary_clarification_requested",
                details=notes,
            )
            create_audit_log(
                user=actor or reservation.user,
                action=f"bursary_clarification_requested:{reservation.booking_reference}",
                model_name="Reservation",
                object_repr=str(reservation),
                old_value=locked_res.case_status,
                new_value=locked_res.case_status,
            )

            link = _booking_link(reservation)
            notify_user(
                user=reservation.user,
                title=f"Payment Clarification Required — {reservation.booking_reference}",
                message=f"Bursary has requested clarification on your payment. Please reply in the portal.",
                link=link,
            )

        return TransitionResult(ok=True)

    # =========================================================================
    # Phase 7 — Final Ventures Approval
    # =========================================================================

    @classmethod
    def ventures_final_approve(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.BOOKING_APPROVED,
            actor=actor,
            notes=notes or "Booking officially approved by Ventures.",
        )
        if result.ok:
            # Generate QR code & mark permit
            if not reservation.qr_verification_code:
                reservation.qr_verification_code = uuid.uuid4()
            reservation.booking_permit_generated = True
            reservation.save(update_fields=["qr_verification_code", "booking_permit_generated"])

            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.BOOKING_APPROVED,
                title="Booking Officially Approved",
                description=notes or "Ventures has granted final approval. Booking permit and QR code generated.",
                actor=actor,
            )

            from reservations.pdf import build_booking_permit_pdf
            from reservations.models import ReservationDocument, DocumentType
            from django.core.files.base import ContentFile

            permit_pdf_bytes = build_booking_permit_pdf(reservation=reservation)
            doc_name = f"permit_{reservation.booking_reference}.pdf"
            
            # Use current version logic if a permit already exists
            version = 1
            existing = reservation.documents.filter(document_type=DocumentType.PERMIT).order_by('-version').first()
            if existing:
                version = existing.version + 1
            
            ReservationDocument.objects.create(
                reservation=reservation,
                document_type=DocumentType.PERMIT,
                version=version,
                uploaded_by=actor,
                visible_to="APPLICANT,FACILITY,VENTURES,BURSARY",
                file=ContentFile(permit_pdf_bytes, name=doc_name)
            )

            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.PERMIT_GENERATED,
                title="Booking Permit & QR Code Generated",
                description=f"Reference: {reservation.booking_reference}. QR: {reservation.qr_verification_code}. Permit document attached.",
                actor=None,
            )
        return result

    @classmethod
    def ventures_final_reject(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.BOOKING_REJECTED,
            actor=actor,
            notes=notes or "Booking rejected at final Ventures approval stage.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.BOOKING_REJECTED,
                title="Booking Rejected at Final Approval",
                description=notes,
                actor=actor,
            )
        return result

    # =========================================================================
    # Phase 8 — Event Execution
    # =========================================================================

    @classmethod
    def mark_event_completed(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.EVENT_COMPLETED,
            actor=actor,
            notes=notes or "Event marked as completed.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.EVENT_COMPLETED,
                title="Event Completed",
                description=notes or "The event has taken place. Post-event inspection to follow.",
                actor=actor,
            )
        return result

    # =========================================================================
    # Phase 9 — Post-Event Inspection (Facility)
    # =========================================================================

    @classmethod
    def open_inspection(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.UNDER_POST_EVENT_INSPECTION,
            actor=actor,
            notes=notes or "Post-event inspection opened by Facility.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.INSPECTION_OPENED,
                title="Post-Event Inspection Opened",
                description=notes or "Facility has commenced post-event inspection of the hall.",
                actor=actor,
            )
        return result

    @classmethod
    def inspection_no_damage(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.CASE_CLOSED,
            actor=actor,
            notes=notes or "Inspection complete — no damage found. Case closed.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.INSPECTION_COMPLETED,
                title="Inspection Complete — No Damage",
                description=notes or "Hall inspected. No damage found. Applicant remains eligible for future bookings.",
                actor=actor,
            )
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.CASE_CLOSED,
                title="Case Closed",
                description="Booking case formally closed. Applicant account remains in good standing.",
                actor=None,
            )
        return result

    @classmethod
    def inspection_damage_found(
        cls,
        *,
        reservation: Reservation,
        actor=None,
        notes: str = "",
    ) -> TransitionResult:
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.DAMAGE_ASSESSED,
            actor=actor,
            notes=notes or "Damage found during post-event inspection.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.INSPECTION_COMPLETED,
                title="Inspection Complete — Damage Found",
                description=notes or "Hall inspected. Damage found. Damage assessment initiated.",
                actor=actor,
            )
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.DAMAGE_ASSESSED,
                title="Damage Assessment Created",
                description="Damage report generated. Invoice will be issued to applicant.",
                actor=actor,
            )
            # Advance to AWAITING_DAMAGE_PAYMENT
            cls.transition(
                reservation=reservation,
                to_status=BookingCaseStatus.AWAITING_DAMAGE_PAYMENT,
                actor=None,
                notes="System: damage invoice issued. Awaiting applicant damage payment.",
            )
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.DAMAGE_INVOICE_ISSUED,
                title="Damage Invoice Issued to Applicant",
                description="Applicant has been notified to pay the damage assessment.",
                actor=None,
            )
            # Restrict user
            _sync_user_block_from_damage(reservation.user)
        return result

    # =========================================================================
    # Phase 10-11 — Damage Payment
    # =========================================================================

    @classmethod
    def submit_damage_payment_proof(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.DAMAGE_PAYMENT_SUBMITTED,
            actor=actor,
            notes=notes or "Applicant submitted damage payment proof.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.DAMAGE_PAYMENT_UPLOADED,
                title="Damage Payment Proof Uploaded",
                description=notes or "Applicant uploaded damage payment evidence. Pending Bursary verification.",
                actor=actor,
            )
            # Advance to UNDER_DAMAGE_PAYMENT_VERIFICATION
            cls.transition(
                reservation=reservation,
                to_status=BookingCaseStatus.UNDER_DAMAGE_PAYMENT_VERIFICATION,
                actor=None,
                notes="System: forwarded to Bursary for damage payment verification.",
            )
        return result

    @classmethod
    def bursary_verify_damage_payment(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.DAMAGE_PAYMENT_VERIFIED,
            actor=actor,
            notes=notes or "Damage payment verified by Bursary.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.DAMAGE_PAYMENT_VERIFIED,
                title="Damage Payment Verified",
                description=notes or "Bursary verified damage payment. Case proceeding to closure.",
                actor=actor,
            )
            # Mark damage report as paid
            from reservations.models import DamageReport
            DamageReport.objects.filter(reservation=reservation, is_paid=False, is_forgiven=False).update(is_paid=True)
            # Release user block
            _sync_user_block_from_damage(reservation.user)
            # Close the case
            cls.transition(
                reservation=reservation,
                to_status=BookingCaseStatus.CASE_CLOSED,
                actor=None,
                notes="System: damage resolved. Case closed.",
            )
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.CASE_CLOSED,
                title="Case Closed — Damage Resolved",
                description="All damages paid. Case formally closed. Applicant is eligible for future bookings.",
                actor=None,
            )
        return result

    @classmethod
    def bursary_reject_damage_payment(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        result = cls.transition(
            reservation=reservation,
            to_status=BookingCaseStatus.AWAITING_DAMAGE_PAYMENT,
            actor=actor,
            notes=notes or "Damage payment proof rejected by Bursary.",
        )
        if result.ok:
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.PAYMENT_REJECTED,
                title="Damage Payment Proof Rejected",
                description=notes or "Bursary rejected the damage payment proof. Applicant must re-upload.",
                actor=actor,
            )
        return result

    # =========================================================================
    # Admin Exceptions
    # =========================================================================

    @classmethod
    def admin_forgive_liability(
        cls,
        *,
        reservation: Reservation,
        actor=None,
        reason: str = "",
        forgive_all: bool = True,
    ) -> TransitionResult:
        from reservations.models import DamageReport, Penalty
        from django.utils import timezone as tz

        with transaction.atomic():
            if forgive_all:
                DamageReport.objects.filter(reservation=reservation, is_paid=False, is_forgiven=False).update(
                    is_forgiven=True,
                    admin_waiver_reason=reason,
                    waived_by=actor,
                    waived_at=tz.now(),
                )
                Penalty.objects.filter(reservation=reservation, is_paid=False, is_forgiven=False).update(
                    is_forgiven=True,
                )

            _sync_user_block_from_damage(reservation.user)

            BookingLog.objects.create(
                reservation=reservation,
                actor=actor,
                action="admin_forgive_liability",
                details=reason,
            )
            create_audit_log(
                user=actor,
                action=f"admin_forgive_liability:{reservation.booking_reference}",
                model_name="Reservation",
                object_repr=str(reservation),
                new_value=f"Forgiven. Reason: {reason}",
            )
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.LIABILITY_FORGIVEN,
                title="Liability Forgiven by Admin",
                description=reason,
                actor=actor,
            )
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.RESTRICTION_REMOVED,
                title="User Restriction Removed",
                description=f"Admin removed booking restriction for {reservation.user.get_full_name() or reservation.user.email}.",
                actor=actor,
            )

        return TransitionResult(ok=True)

    @classmethod
    def ventures_create_penalty(
        cls,
        *,
        reservation: Reservation,
        actor=None,
        title: str,
        description: str,
        amount,
        penalty_type: str = VenturesPenaltyType.PENALTY,
        notes: str = "",
    ) -> TransitionResult:
        """
        Ventures creates a penalty/fee on a reservation case.
        Creates both the base Penalty record and a VenturesPenaltyRecord for audit.
        """
        from reservations.models import Penalty
        from decimal import Decimal
        from django.utils import timezone as tz
        with transaction.atomic():
            penalty = Penalty.objects.create(
                title=title,
                description=description,
                amount=Decimal(str(amount)),
                user=reservation.user,
                reservation=reservation,
            )
            VenturesPenaltyRecord.objects.create(
                reservation=reservation,
                penalty=penalty,
                penalty_type=penalty_type,
                created_by=actor,
                notes=notes,
            )
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.PENALTY_CREATED,
                title=f"Penalty Created: {title}",
                description=f"Amount: ₦{penalty.amount}. Type: {penalty_type}. Notes: {notes}",
                actor=actor,
            )
            BookingLog.objects.create(
                reservation=reservation,
                actor=actor,
                action="ventures_create_penalty",
                details=f"{title}: ₦{penalty.amount}",
            )
            create_audit_log(
                user=actor or reservation.user,
                action=f"penalty_created:{reservation.booking_reference}:{title}",
                model_name="Penalty",
                object_repr=str(penalty),
                new_value=f"₦{penalty.amount} — {description}",
            )
            # Notify applicant
            notify_user(
                user=reservation.user,
                title=f"Penalty Issued — {reservation.booking_reference}",
                message=f"A {penalty_type.lower()} of ₦{penalty.amount} has been issued: {title}.",
                link=_booking_link(reservation),
            )
            # Notify Bursary
            _notify_roles(
                reservation=reservation, roles=["BURSARY", "ADMIN"],
                title=f"Penalty Created — {reservation.booking_reference}",
                message=f"Ventures created a penalty of ₦{penalty.amount} on booking {reservation.booking_reference}: {title}.",
                link=_booking_link(reservation) + "#bursary",
            )
        return TransitionResult(ok=True)

    @classmethod
    def send_inspection_reminder(
        cls,
        *,
        reservation: Reservation,
        reminder_number: int = 1,
    ) -> bool:
        """
        Sends an inspection reminder to Facility staff.
        reminder_number: 1=immediate, 2=24h post-event, 3=48h post-event.
        Returns True if reminder was sent, False if already sent.
        """
        # Prevent duplicate sends
        if InspectionReminder.objects.filter(reservation=reservation, reminder_number=reminder_number).exists():
            return False

        InspectionReminder.objects.create(
            reservation=reservation,
            reminder_number=reminder_number,
            sent_to_roles="FACILITY,ADMIN",
        )
        messages_map = {
            1: "Event completed. Please conduct the post-event hall inspection at your earliest convenience.",
            2: "Reminder: Post-event inspection is still pending (24 hours since event end).",
            3: "Urgent: Post-event inspection has not been completed (48 hours since event end). Immediate action required.",
        }
        msg = messages_map.get(reminder_number, "Please complete the post-event hall inspection.")
        _notify_roles(
            reservation=reservation, roles=["FACILITY", "ADMIN"],
            title=f"Inspection Reminder #{reminder_number} — {reservation.booking_reference}",
            message=msg,
            link=_booking_link(reservation),
        )
        _add_timeline(
            reservation=reservation,
            event_type=TimelineEventType.INSPECTION_REMINDER_SENT,
            title=f"Inspection Reminder #{reminder_number} Sent",
            description=msg,
        )
        return True

    @classmethod
    def admin_close_case(cls, *, reservation: Reservation, actor=None, notes: str = "") -> TransitionResult:
        """Admin override: force-close a case at any stage."""
        with transaction.atomic():
            reservation.case_status = BookingCaseStatus.CASE_CLOSED
            _sync_legacy_status(reservation, BookingCaseStatus.CASE_CLOSED)
            reservation.save()
            BookingLog.objects.create(
                reservation=reservation,
                actor=actor,
                action="admin_force_close",
                details=notes,
            )
            create_audit_log(
                user=actor,
                action=f"admin_force_close:{reservation.booking_reference}",
                model_name="Reservation",
                object_repr=str(reservation),
                new_value=notes,
            )
            _add_timeline(
                reservation=reservation,
                event_type=TimelineEventType.STATUS_OVERRIDE,
                title="Case Force-Closed by Admin",
                description=notes,
                actor=actor,
            )
        return TransitionResult(ok=True)

    # =========================================================================
    # Legacy transition methods (backward compat — operate on legacy status field)
    # =========================================================================

    @classmethod
    def _legacy(cls, reservation, to_status, actor=None, notes=""):
        return cls.transition(
            reservation=reservation, to_status=to_status,
            actor=actor, notes=notes, use_legacy=True,
        )

    @classmethod
    def submit_reservation_legacy(cls, reservation, actor=None):
        return cls._legacy(reservation, ReservationStatus.SUBMITTED, actor, "Submitted")

    @classmethod
    def forward_to_facility_legacy(cls, reservation, actor=None, notes="Forwarded to Facility Management"):
        return cls._legacy(reservation, ReservationStatus.FORWARDED, actor, notes)

    @classmethod
    def mark_under_review(cls, reservation, actor=None, notes="Ventures is reviewing the submission"):
        return cls._legacy(reservation, ReservationStatus.UNDER_REVIEW, actor, notes)

    @classmethod
    def mark_available(cls, reservation, actor=None, notes="Facility confirmed hall availability"):
        return cls._legacy(reservation, ReservationStatus.AVAILABLE, actor, notes)

    @classmethod
    def reject(cls, reservation, actor=None, notes="Rejected"):
        return cls._legacy(reservation, ReservationStatus.REJECTED, actor, notes)

    @classmethod
    def approve_for_payment(cls, reservation, actor=None, notes="Approved for payment"):
        return cls._legacy(reservation, ReservationStatus.APPROVED_PAYMENT, actor, notes)

    @classmethod
    def mark_payment_pending(cls, reservation, actor=None, notes="Applicant initiated payment"):
        return cls._legacy(reservation, ReservationStatus.PAYMENT_PENDING, actor, notes)

    @classmethod
    def mark_paid(cls, reservation, actor=None, notes="Payment verified and confirmed"):
        return cls._legacy(reservation, ReservationStatus.PAID, actor, notes)

    @classmethod
    def confirm(cls, reservation, actor=None, notes="Ventures officially confirmed the reservation"):
        return cls._legacy(reservation, ReservationStatus.CONFIRMED, actor, notes)

    @classmethod
    def mark_completed(cls, reservation, actor=None, notes="Event completed"):
        return cls._legacy(reservation, ReservationStatus.COMPLETED, actor, notes)

    @classmethod
    def open_inspection_legacy(cls, reservation, actor=None, notes="Post-event inspection opened"):
        return cls._legacy(reservation, ReservationStatus.INSPECTION_PENDING, actor, notes)

    @classmethod
    def record_damage(cls, reservation, actor=None, notes="Damage reported during inspection"):
        return cls._legacy(reservation, ReservationStatus.DAMAGE_REPORTED, actor, notes)

    @classmethod
    def close_reservation(cls, reservation, actor=None, notes="Booking formally closed"):
        return cls._legacy(reservation, ReservationStatus.CLOSED, actor, notes)

    @classmethod
    def cancel(cls, reservation, actor=None, notes="Cancelled"):
        return cls._legacy(reservation, ReservationStatus.CANCELLED, actor, notes)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sync_legacy_status(reservation: Reservation, new_case_status: str) -> None:
    """
    Keep the legacy `status` field roughly in sync with case_status
    so calendar/dashboard queries that filter on `status` still work.
    """
    CASE_TO_LEGACY = {
        BookingCaseStatus.DRAFT:                        ReservationStatus.SUBMITTED,
        BookingCaseStatus.SUBMITTED:                    ReservationStatus.SUBMITTED,
        BookingCaseStatus.UNDER_VENTURES_REVIEW:        ReservationStatus.UNDER_REVIEW,
        BookingCaseStatus.UNDER_FACILITY_REVIEW:        ReservationStatus.FORWARDED,
        BookingCaseStatus.FACILITY_APPROVED:            ReservationStatus.AVAILABLE,
        BookingCaseStatus.FACILITY_REJECTED:            ReservationStatus.REJECTED,
        BookingCaseStatus.PAYMENT_AUTHORIZATION:        ReservationStatus.APPROVED_PAYMENT,  # NEW
        BookingCaseStatus.AWAITING_PAYMENT:             ReservationStatus.APPROVED_PAYMENT,
        BookingCaseStatus.PAYMENT_SUBMITTED:            ReservationStatus.PAYMENT_PENDING,
        BookingCaseStatus.UNDER_BURSARY_VERIFICATION:   ReservationStatus.PAYMENT_PENDING,
        BookingCaseStatus.PAYMENT_VERIFIED:             ReservationStatus.PAID,
        BookingCaseStatus.PAYMENT_REJECTED:             ReservationStatus.PAYMENT_PENDING,
        BookingCaseStatus.AWAITING_FINAL_APPROVAL:      ReservationStatus.PAID,
        BookingCaseStatus.BOOKING_APPROVED:             ReservationStatus.CONFIRMED,
        BookingCaseStatus.BOOKING_REJECTED:             ReservationStatus.REJECTED,
        BookingCaseStatus.PAYMENT_EXPIRED:              ReservationStatus.CANCELLED,          # NEW
        BookingCaseStatus.EVENT_COMPLETED:              ReservationStatus.COMPLETED,
        BookingCaseStatus.UNDER_POST_EVENT_INSPECTION:  ReservationStatus.INSPECTION_PENDING,
        BookingCaseStatus.DAMAGE_ASSESSED:              ReservationStatus.DAMAGE_REPORTED,
        BookingCaseStatus.AWAITING_DAMAGE_PAYMENT:      ReservationStatus.DAMAGE_REPORTED,
        BookingCaseStatus.DAMAGE_PAYMENT_SUBMITTED:     ReservationStatus.DAMAGE_REPORTED,
        BookingCaseStatus.UNDER_DAMAGE_PAYMENT_VERIFICATION: ReservationStatus.DAMAGE_REPORTED,
        BookingCaseStatus.DAMAGE_PAYMENT_VERIFIED:      ReservationStatus.DAMAGE_REPORTED,
        BookingCaseStatus.CASE_CLOSED:                  ReservationStatus.CLOSED,
        BookingCaseStatus.USER_RESTRICTED:              ReservationStatus.CANCELLED,
    }
    legacy = CASE_TO_LEGACY.get(new_case_status)
    if legacy:
        reservation.status = legacy


def _sync_user_block_from_damage(user) -> None:
    """Sync the user's is_blocked flag based on outstanding damage/penalty records."""
    from reservations.models import DamageReport, Penalty
    unpaid = (
        DamageReport.objects.filter(user=user, is_paid=False, is_forgiven=False).exists()
        or Penalty.objects.filter(user=user, is_paid=False, is_forgiven=False).exists()
    )
    if user.is_blocked != unpaid:
        user.is_blocked = unpaid
        user.save(update_fields=["is_blocked"])
# End of services.py
