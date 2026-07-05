"""
EVMS Centralized Workflow Action Engine
========================================
Determines dynamically which workflow actions are available for a given
(reservation, user) pair, based solely on:

  • Current BookingCaseStatus
  • Current user role / capabilities
  • Workflow transition rules (mirrors WorkflowService.VALID_TRANSITIONS)

Rules
-----
* Only VALID actions for the current status are returned.
* Invalid/illegal actions are NEVER returned (not disabled — absent).
* If a department is the next required actor, its actions MUST appear.
* Actions carry: value, label, description, destination state, icon, variant.

This module is the ONLY place that decides what the UI renders.  The views
and templates must not add additional hard-coded action logic on top.
"""

from __future__ import annotations

from typing import Dict, List, TypedDict

from reservations.models import BookingCaseStatus, Reservation


class ActionDef(TypedDict):
    value: str           # POST value sent by the form
    label: str           # Human-readable button/option text
    desc: str            # Tooltip / secondary description
    destination: str     # Friendly label of the target status
    icon: str            # Bootstrap Icons class (without 'bi bi-')
    variant: str         # Bootstrap button colour variant (danger, success …)


# ---------------------------------------------------------------------------
# Permission helpers — intentionally defined here so the engine is self-
# contained. They delegate to users.services which is the authoritative RBAC
# source.
# ---------------------------------------------------------------------------

def _can_ventures(user) -> bool:
    try:
        from users.services import can
        return can(user, "ventures_workflow")
    except Exception:
        return getattr(user, "role", "") in ("VENTURES", "ADMIN", "STAFF")


def _can_facility(user) -> bool:
    try:
        from users.services import can
        return can(user, "facility_workflow")
    except Exception:
        return getattr(user, "role", "") in ("FACILITY", "ADMIN", "STAFF")


def _can_bursary(user) -> bool:
    try:
        from users.services import can_manage_bursary
        return can_manage_bursary(user)
    except Exception:
        return getattr(user, "role", "") in ("BURSARY", "ADMIN", "STAFF")


def _can_admin(user) -> bool:
    try:
        from core.services import can_view_all
        return can_view_all(user)
    except Exception:
        return getattr(user, "role", "") in ("ADMIN", "STAFF")


def _is_applicant(user, reservation: Reservation) -> bool:
    return user.pk == reservation.user_id


# ---------------------------------------------------------------------------
# Status label map — friendly badge labels for every BookingCaseStatus value
# ---------------------------------------------------------------------------

STATUS_BADGE_LABELS: Dict[str, str] = {
    BookingCaseStatus.DRAFT:                        "Draft",
    BookingCaseStatus.SUBMITTED:                    "Submitted — Awaiting Ventures",
    BookingCaseStatus.UNDER_VENTURES_REVIEW:        "Under Ventures Review",
    BookingCaseStatus.UNDER_FACILITY_REVIEW:        "Awaiting Facility Review",
    BookingCaseStatus.FACILITY_APPROVED:            "Facility Approved",
    BookingCaseStatus.FACILITY_REJECTED:            "Facility Rejected",
    BookingCaseStatus.PAYMENT_AUTHORIZATION:        "Payment Authorization",
    BookingCaseStatus.PAYMENT_EXPIRED:              "Payment Expired",
    BookingCaseStatus.AWAITING_PAYMENT:             "Awaiting Payment",
    BookingCaseStatus.PAYMENT_SUBMITTED:            "Payment Submitted",
    BookingCaseStatus.UNDER_BURSARY_VERIFICATION:   "Under Bursary Verification",
    BookingCaseStatus.PAYMENT_VERIFIED:             "Payment Verified",
    BookingCaseStatus.PAYMENT_REJECTED:             "Payment Rejected",
    BookingCaseStatus.AWAITING_FINAL_APPROVAL:      "Awaiting Final Approval",
    BookingCaseStatus.BOOKING_APPROVED:             "Booking Approved",
    BookingCaseStatus.BOOKING_REJECTED:             "Booking Rejected",
    BookingCaseStatus.EVENT_COMPLETED:              "Event Completed",
    BookingCaseStatus.UNDER_POST_EVENT_INSPECTION:  "Inspection In Progress",
    BookingCaseStatus.DAMAGE_ASSESSED:              "Damage Assessed",
    BookingCaseStatus.AWAITING_DAMAGE_PAYMENT:      "Awaiting Damage Payment",
    BookingCaseStatus.DAMAGE_PAYMENT_SUBMITTED:     "Damage Payment Submitted",
    BookingCaseStatus.UNDER_DAMAGE_PAYMENT_VERIFICATION: "Under Damage Payment Verification",
    BookingCaseStatus.DAMAGE_PAYMENT_VERIFIED:      "Damage Payment Verified",
    BookingCaseStatus.CASE_CLOSED:                  "Case Closed",
    BookingCaseStatus.USER_RESTRICTED:              "User Restricted",
}

# Bootstrap badge colour variant for each status
STATUS_BADGE_VARIANT: Dict[str, str] = {
    BookingCaseStatus.DRAFT:                        "secondary",
    BookingCaseStatus.SUBMITTED:                    "info",
    BookingCaseStatus.UNDER_VENTURES_REVIEW:        "primary",
    BookingCaseStatus.UNDER_FACILITY_REVIEW:        "primary",
    BookingCaseStatus.FACILITY_APPROVED:            "success",
    BookingCaseStatus.FACILITY_REJECTED:            "danger",
    BookingCaseStatus.PAYMENT_AUTHORIZATION:        "warning",
    BookingCaseStatus.PAYMENT_EXPIRED:              "danger",
    BookingCaseStatus.AWAITING_PAYMENT:             "warning",
    BookingCaseStatus.PAYMENT_SUBMITTED:            "info",
    BookingCaseStatus.UNDER_BURSARY_VERIFICATION:   "primary",
    BookingCaseStatus.PAYMENT_VERIFIED:             "success",
    BookingCaseStatus.PAYMENT_REJECTED:             "danger",
    BookingCaseStatus.AWAITING_FINAL_APPROVAL:      "warning",
    BookingCaseStatus.BOOKING_APPROVED:             "success",
    BookingCaseStatus.BOOKING_REJECTED:             "danger",
    BookingCaseStatus.EVENT_COMPLETED:              "secondary",
    BookingCaseStatus.UNDER_POST_EVENT_INSPECTION:  "warning",
    BookingCaseStatus.DAMAGE_ASSESSED:              "danger",
    BookingCaseStatus.AWAITING_DAMAGE_PAYMENT:      "danger",
    BookingCaseStatus.DAMAGE_PAYMENT_SUBMITTED:     "info",
    BookingCaseStatus.UNDER_DAMAGE_PAYMENT_VERIFICATION: "primary",
    BookingCaseStatus.DAMAGE_PAYMENT_VERIFIED:      "success",
    BookingCaseStatus.CASE_CLOSED:                  "success",
    BookingCaseStatus.USER_RESTRICTED:              "dark",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_S = BookingCaseStatus  # alias for brevity


def _a(value: str, label: str, desc: str, destination: str,
        icon: str = "arrow-right-circle", variant: str = "primary") -> ActionDef:
    return ActionDef(
        value=value, label=label, desc=desc,
        destination=destination, icon=icon, variant=variant,
    )


# ---------------------------------------------------------------------------
# WorkflowActionEngine
# ---------------------------------------------------------------------------

class WorkflowActionEngine:
    """
    Central engine that returns the set of legally-executable workflow actions
    for a given (reservation, user) combination.

    Returns a dict with keys: ventures, facility, bursary, applicant, admin.
    Each value is a list of ActionDef dicts.  Empty lists mean no valid actions.
    """

    @classmethod
    def get_available_actions(
        cls,
        reservation: Reservation,
        user,
    ) -> Dict[str, List[ActionDef]]:
        status = reservation.case_status

        result: Dict[str, List[ActionDef]] = {
            "ventures": [],
            "facility": [],
            "bursary": [],
            "applicant": [],
            "admin": [],
        }

        # ── Permission gates ──────────────────────────────────────────────
        is_ventures = _can_ventures(user) or _can_admin(user)
        is_facility = _can_facility(user) or _can_admin(user)
        is_bursary  = _can_bursary(user)  or _can_admin(user)
        is_admin    = _can_admin(user)
        is_app      = _is_applicant(user, reservation)

        # ── TERMINAL STATES — no actions possible ─────────────────────────
        _terminal = {
            _S.CASE_CLOSED, _S.BOOKING_REJECTED, _S.PAYMENT_EXPIRED,
        }

        # =====================================================================
        # VENTURES ACTIONS
        # =====================================================================
        if is_ventures:
            v = result["ventures"]

            if status == _S.SUBMITTED:
                v.append(_a("ventures_review", "Review Booking",
                            "Begin Ventures review of this booking application.",
                            "Under Ventures Review", "eye", "primary"))
                v.append(_a("forward_to_facility", "Forward to Facility",
                            "Skip internal review and forward directly to Facility for hall availability check.",
                            "Under Facility Review", "send", "info"))
                v.append(_a("reject", "Reject Booking",
                            "Reject this booking application and notify the applicant.",
                            "Booking Rejected", "x-circle", "danger"))

            elif status == _S.UNDER_VENTURES_REVIEW:
                v.append(_a("forward_to_facility", "Forward to Facility",
                            "Forward this booking to Facility Management for hall availability review.",
                            "Under Facility Review", "send", "info"))
                v.append(_a("reject", "Reject Booking",
                            "Reject this booking application with reason.",
                            "Booking Rejected", "x-circle", "danger"))

            elif status == _S.FACILITY_APPROVED:
                v.append(_a("open_payment_authorization", "Open Payment Authorization",
                            "Open the Payment Authorization panel to set billing, coupons and payment deadline.",
                            "Payment Authorization", "credit-card", "warning"))
                v.append(_a("reject", "Reject Booking",
                            "Reject this booking despite facility approval.",
                            "Booking Rejected", "x-circle", "danger"))

            elif status == _S.FACILITY_REJECTED:
                v.append(_a("return_to_ventures", "Return to Ventures Review",
                            "Re-evaluate this booking after facility rejection.",
                            "Under Ventures Review", "arrow-counterclockwise", "warning"))
                v.append(_a("reject", "Confirm Rejection",
                            "Confirm and close the booking as rejected.",
                            "Booking Rejected", "x-circle", "danger"))

            elif status == _S.PAYMENT_AUTHORIZATION:
                # Redirect to the dedicated payment-auth page — handled in view
                v.append(_a("open_payment_authorization", "Resume Payment Authorization",
                            "Continue reviewing billing details, coupon and payment deadline.",
                            "Payment Authorization", "credit-card-2-front", "warning"))

            elif status == _S.AWAITING_FINAL_APPROVAL:
                v.append(_a("final_approve", "Grant Final Approval",
                            "Grant final booking approval. Generates permit and QR code.",
                            "Booking Approved", "check-circle", "success"))
                v.append(_a("final_reject", "Reject at Final Stage",
                            "Reject this booking at final approval stage.",
                            "Booking Rejected", "x-circle", "danger"))

            elif status == _S.BOOKING_APPROVED:
                v.append(_a("mark_event_completed", "Mark Event Completed",
                            "Record that the event has taken place. Initiates post-event inspection workflow.",
                            "Event Completed", "calendar-check", "success"))

            # Penalty creation is available at most non-terminal stages
            # (exposed separately in the template via a dedicated form, not this list)

        # =====================================================================
        # FACILITY ACTIONS
        # =====================================================================
        if is_facility:
            f = result["facility"]

            if status == _S.UNDER_FACILITY_REVIEW:
                f.append(_a("facility_approve", "Approve Hall Availability",
                            "Confirm that the hall is available and suitable for this event.",
                            "Facility Approved", "check-circle", "success"))
                f.append(_a("facility_reject", "Reject Hall Availability",
                            "Reject this booking due to hall unavailability or maintenance conflict.",
                            "Facility Rejected", "x-circle", "danger"))

            elif status == _S.BOOKING_APPROVED:
                f.append(_a("mark_event_completed", "Mark Event Completed",
                            "Record that the event has taken place successfully.",
                            "Event Completed", "calendar-check", "success"))

            elif status == _S.EVENT_COMPLETED:
                f.append(_a("open_inspection", "Open Post-Event Inspection",
                            "Initiate the post-event hall inspection. This transitions the case to Under Post-Event Inspection.",
                            "Inspection In Progress", "clipboard2-check", "warning"))

            elif status == _S.UNDER_POST_EVENT_INSPECTION:
                f.append(_a("inspection_no_damage", "Close Case — No Damage",
                            "Record that no damage was found during inspection. Case will be closed immediately.",
                            "Case Closed", "check-circle-fill", "success"))
                # inspection_damage_found is submitted via the inspection form, not this dropdown

        # =====================================================================
        # BURSARY ACTIONS
        # =====================================================================
        if is_bursary:
            b = result["bursary"]

            if status == _S.UNDER_BURSARY_VERIFICATION:
                b.append(_a("verify_payment", "Verify Payment",
                            "Confirm that the payment evidence is valid. Case advances to Ventures for final approval.",
                            "Payment Verified → Awaiting Final Approval", "shield-check", "success"))
                b.append(_a("reject_payment", "Reject Payment",
                            "Reject invalid payment evidence. Applicant will be asked to re-upload.",
                            "Awaiting Payment", "shield-x", "danger"))
                b.append(_a("request_clarification", "Request Clarification",
                            "Send a clarification message to the applicant without changing the workflow status.",
                            "No status change", "chat-dots", "secondary"))

            elif status == _S.UNDER_DAMAGE_PAYMENT_VERIFICATION:
                b.append(_a("verify_damage_payment", "Verify Damage Payment",
                            "Confirm that the damage payment evidence is valid. Case will be closed.",
                            "Case Closed", "shield-check", "success"))
                b.append(_a("reject_damage_payment", "Reject Damage Payment",
                            "Reject invalid damage payment proof. Applicant must re-upload.",
                            "Awaiting Damage Payment", "shield-x", "danger"))
                b.append(_a("request_clarification", "Request Clarification",
                            "Request additional information from the applicant.",
                            "No status change", "chat-dots", "secondary"))

        # =====================================================================
        # APPLICANT ACTIONS
        # =====================================================================
        if is_app:
            ap = result["applicant"]

            if status == _S.AWAITING_PAYMENT:
                ap.append(_a("upload_payment_proof", "Upload Payment Proof",
                             "Upload your bank transfer receipt for Bursary verification.",
                             "Payment Submitted", "upload", "primary"))
                ap.append(_a("pay_online", "Pay Online via Paystack",
                             "Pay the booking fee directly online.",
                             "Payment Verified", "credit-card", "success"))

            elif status == _S.PAYMENT_REJECTED:
                ap.append(_a("upload_payment_proof", "Re-upload Payment Proof",
                             "Bursary rejected your previous evidence. Please upload a corrected receipt.",
                             "Payment Submitted", "upload", "warning"))

            elif status == _S.AWAITING_DAMAGE_PAYMENT:
                ap.append(_a("upload_damage_proof", "Upload Damage Payment Proof",
                             "Upload your damage payment receipt for Bursary verification.",
                             "Damage Payment Submitted", "upload", "danger"))
                ap.append(_a("pay_damage_online", "Pay Damage Online",
                             "Pay the assessed damage cost directly online.",
                             "Damage Payment Verified", "credit-card", "danger"))

            if status == _S.BOOKING_APPROVED:
                pass # Document downloads are handled directly in the UI template

        # =====================================================================
        # ADMIN ACTIONS
        # =====================================================================
        if is_admin:
            adm = result["admin"]

            # Forgive liability — only if there are unpaid damages / restriction active
            if status not in (_S.CASE_CLOSED, _S.DRAFT):
                adm.append(_a("forgive_liability", "Forgive Liability & Remove Restriction",
                               "Forgive all outstanding damage/penalty charges and clear user restriction.",
                               "No status change", "shield-plus", "warning"))

            # Force-close — only for non-terminal, non-draft cases
            if status not in _terminal and status != _S.DRAFT:
                adm.append(_a("force_close", "Force Close Case",
                               "Administratively close this case regardless of workflow stage.",
                               "Case Closed", "lock", "danger"))

            adm.append(_a("remove_restriction", "Re-evaluate User Restriction",
                           "Recalculate whether the user should remain restricted based on current liability.",
                           "No status change", "person-check", "secondary"))

        return result

    @classmethod
    def get_badge_label(cls, status: str) -> str:
        """Return the friendly badge label for a BookingCaseStatus value."""
        return STATUS_BADGE_LABELS.get(status, status.replace("_", " ").title())

    @classmethod
    def get_badge_variant(cls, status: str) -> str:
        """Return the Bootstrap colour variant for the status badge."""
        return STATUS_BADGE_VARIANT.get(status, "secondary")
