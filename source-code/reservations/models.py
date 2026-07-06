import math
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from hall.models import Hall


# ---------------------------------------------------------------------------
# NEW canonical booking lifecycle statuses (Phase 1-12)
# ---------------------------------------------------------------------------

class BookingCaseStatus(models.TextChoices):
    DRAFT                           = "DRAFT",                           "Draft"
    SUBMITTED                       = "SUBMITTED",                       "Submitted"
    UNDER_VENTURES_REVIEW           = "UNDER_VENTURES_REVIEW",           "Under Ventures Review"
    UNDER_FACILITY_REVIEW           = "UNDER_FACILITY_REVIEW",           "Under Facility Review"
    FACILITY_APPROVED               = "FACILITY_APPROVED",               "Facility Approved"
    FACILITY_REJECTED               = "FACILITY_REJECTED",               "Facility Rejected"
    # ── NEW: Payment Authorization stage ──────────────────────────────────
    PAYMENT_AUTHORIZATION           = "PAYMENT_AUTHORIZATION",           "Payment Authorization"
    PAYMENT_EXPIRED                 = "PAYMENT_EXPIRED",                 "Payment Expired"
    # ─────────────────────────────────────────────────────────────────────
    AWAITING_PAYMENT                = "AWAITING_PAYMENT",                "Awaiting Payment"
    PAYMENT_SUBMITTED               = "PAYMENT_SUBMITTED",               "Payment Submitted"
    UNDER_BURSARY_VERIFICATION      = "UNDER_BURSARY_VERIFICATION",      "Under Bursary Verification"
    PAYMENT_VERIFIED                = "PAYMENT_VERIFIED",                "Payment Verified"
    PAYMENT_REJECTED                = "PAYMENT_REJECTED",                "Payment Rejected"
    AWAITING_FINAL_APPROVAL         = "AWAITING_FINAL_APPROVAL",         "Awaiting Final Approval"
    BOOKING_APPROVED                = "BOOKING_APPROVED",                "Booking Approved"
    BOOKING_REJECTED                = "BOOKING_REJECTED",                "Booking Rejected"
    EVENT_COMPLETED                 = "EVENT_COMPLETED",                 "Event Completed"
    UNDER_POST_EVENT_INSPECTION     = "UNDER_POST_EVENT_INSPECTION",     "Under Post-Event Inspection"
    DAMAGE_ASSESSED                 = "DAMAGE_ASSESSED",                 "Damage Assessed"
    AWAITING_DAMAGE_PAYMENT         = "AWAITING_DAMAGE_PAYMENT",         "Awaiting Damage Payment"
    DAMAGE_PAYMENT_SUBMITTED        = "DAMAGE_PAYMENT_SUBMITTED",        "Damage Payment Submitted"
    UNDER_DAMAGE_PAYMENT_VERIFICATION = "UNDER_DAMAGE_PAYMENT_VERIFICATION", "Under Damage Payment Verification"
    DAMAGE_PAYMENT_VERIFIED         = "DAMAGE_PAYMENT_VERIFIED",         "Damage Payment Verified"
    CASE_CLOSED                     = "CASE_CLOSED",                     "Case Closed"
    USER_RESTRICTED                 = "USER_RESTRICTED",                 "User Restricted"


# ---------------------------------------------------------------------------
# Legacy status enum — preserved for backward compatibility with existing code
# ---------------------------------------------------------------------------

class ReservationStatus(models.TextChoices):
    SUBMITTED        = "SUBMITTED",        "Submitted"
    FORWARDED        = "FORWARDED",        "Forwarded"
    UNDER_REVIEW     = "UNDER_REVIEW",     "Under Review"
    REJECTED         = "REJECTED",         "Rejected"
    AVAILABLE        = "AVAILABLE",        "Available"
    APPROVED_PAYMENT = "APPROVED_PAYMENT", "Approved for Payment"
    PAYMENT_PENDING  = "PAYMENT_PENDING",  "Payment Pending"
    PAID             = "PAID",             "Paid"
    CONFIRMED        = "CONFIRMED",        "Confirmed"
    COMPLETED        = "COMPLETED",        "Completed"
    INSPECTION_PENDING = "INSPECTION_PENDING", "Inspection Pending"
    DAMAGE_REPORTED  = "DAMAGE_REPORTED",  "Damage Reported"
    CLOSED           = "CLOSED",           "Closed"
    CANCELLED        = "CANCELLED",        "Cancelled"
    # Backward-compatible aliases used by existing code paths
    PENDING          = "PENDING",          "Pending"
    APPROVED         = "APPROVED",         "Approved"


class ReservationPurpose(models.TextChoices):
    LECTURE    = "LECTURE",    "Lecture/Academic"
    EXAM       = "EXAM",       "Examination"
    EVENT      = "EVENT",      "Social/Cultural"
    MEETING    = "MEETING",    "Meeting/Conference"
    WORKSHOP   = "WORKSHOP",   "Workshop/Training"
    GRADUATION = "GRADUATION", "Graduation/Convocation"
    RELIGIOUS  = "RELIGIOUS",  "Religious Programme"
    SPORTS     = "SPORTS",     "Sports/Recreation"
    EXHIBITION = "EXHIBITION", "Exhibition/Fair"
    OTHER      = "OTHER",      "Other"


# Mapping from old legacy status → new case_status (used by data migration)
LEGACY_TO_CASE_STATUS_MAP = {
    "DRAFT":                 BookingCaseStatus.DRAFT,
    "SUBMITTED":             BookingCaseStatus.SUBMITTED,
    "UNDER_REVIEW":          BookingCaseStatus.UNDER_VENTURES_REVIEW,
    "FORWARDED":             BookingCaseStatus.UNDER_FACILITY_REVIEW,
    "AVAILABLE":             BookingCaseStatus.FACILITY_APPROVED,
    "PAYMENT_AUTHORIZATION": BookingCaseStatus.PAYMENT_AUTHORIZATION,
    "PAYMENT_EXPIRED":       BookingCaseStatus.PAYMENT_EXPIRED,
    "APPROVED_PAYMENT":      BookingCaseStatus.AWAITING_PAYMENT,
    "PAYMENT_PENDING":       BookingCaseStatus.AWAITING_PAYMENT,
    "PAID":                  BookingCaseStatus.PAYMENT_VERIFIED,
    "CONFIRMED":             BookingCaseStatus.BOOKING_APPROVED,
    "COMPLETED":             BookingCaseStatus.EVENT_COMPLETED,
    "INSPECTION_PENDING":    BookingCaseStatus.UNDER_POST_EVENT_INSPECTION,
    "DAMAGE_REPORTED":       BookingCaseStatus.DAMAGE_ASSESSED,
    "CLOSED":                BookingCaseStatus.CASE_CLOSED,
    "REJECTED":              BookingCaseStatus.BOOKING_REJECTED,
    "CANCELLED":             BookingCaseStatus.BOOKING_REJECTED,
    "PENDING":               BookingCaseStatus.SUBMITTED,
    "APPROVED":              BookingCaseStatus.BOOKING_APPROVED,
}


def _generate_reference():
    return timezone.now().strftime("LASU-%Y%m%d-%H%M%S") + f"-{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# Core Reservation model
# ---------------------------------------------------------------------------

class Reservation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    hall = models.ForeignKey(Hall, on_delete=models.PROTECT, related_name="reservations")

    event_name       = models.CharField(max_length=255, blank=True)
    purpose          = models.CharField(max_length=30, choices=ReservationPurpose.choices)
    attendees_count  = models.PositiveIntegerField(default=0)

    booking_date = models.DateField()
    start_time   = models.TimeField()
    end_time     = models.TimeField()

    # Legacy status — kept for backward compatibility
    status = models.CharField(
        max_length=30, choices=ReservationStatus.choices,
        default=ReservationStatus.SUBMITTED,
    )

    # NEW canonical lifecycle status
    case_status = models.CharField(
        max_length=50,
        choices=BookingCaseStatus.choices,
        default=BookingCaseStatus.SUBMITTED,
        db_index=True,
        help_text="Primary managed booking lifecycle status",
    )

    booking_reference = models.CharField(
        max_length=40, unique=True, default=_generate_reference, editable=False,
    )

    # Financials & Discounts
    original_total          = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Total before discounts")
    coupon_code             = models.CharField(max_length=50, blank=True)
    coupon_requested_at     = models.DateTimeField(null=True, blank=True, help_text="Timestamp when applicant requested this coupon")
    coupon_snapshot         = models.JSONField(default=dict, blank=True, help_text="Snapshot of coupon data at request time for audit trail")
    coupon_status           = models.CharField(
        max_length=20, blank=True,
        choices=[("PENDING", "Pending"), ("APPROVED", "Approved"), ("REJECTED", "Rejected"), ("MODIFIED", "Modified")],
        help_text="Ventures decision on the coupon request",
    )
    coupon_type             = models.CharField(max_length=30, blank=True, help_text="Coupon type snapshot")
    coupon_discount_value   = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Snapshot of coupon discount value")
    coupon_rules_snapshot   = models.JSONField(default=dict, blank=True, help_text="Full coupon rules at time of application")
    coupon_approval_notes   = models.TextField(blank=True, help_text="Ventures notes on coupon decision")
    coupon_approved_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="coupon_approvals",
    )
    coupon_approved_at      = models.DateTimeField(null=True, blank=True)

    discount_type            = models.CharField(max_length=20, blank=True)
    discount_value           = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount_applied  = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_cost               = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Final cost after discount determined by Ventures")
    security_deposit         = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Approval artifacts
    qr_verification_code    = models.UUIDField(null=True, blank=True, editable=False, help_text="Generated on BOOKING_APPROVED")
    booking_permit_generated = models.BooleanField(default=False)

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    notes       = models.TextField(blank=True, help_text="Additional notes from the applicant")

    class Meta:
        ordering = ["-booking_date", "-start_time"]
        indexes = [
            models.Index(fields=["hall", "booking_date", "start_time", "end_time"]),
            models.Index(fields=["user", "booking_date"]),
            models.Index(fields=["status"]),
            models.Index(fields=["case_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.booking_reference} - {self.hall.name}"

    def get_case_status_display_label(self):
        return dict(BookingCaseStatus.choices).get(self.case_status, self.case_status)

    def clean(self):
        super().clean()

        # ModelForm validation runs before user/hall are assigned on create; skip dependent checks.
        if not getattr(self, "user_id", None) or not getattr(self, "hall_id", None):
            return

        # Block users with unpaid damages/penalties.
        if DamageReport.objects.filter(user=self.user, is_paid=False, is_forgiven=False).exists() or Penalty.objects.filter(user=self.user, is_paid=False, is_forgiven=False).exists():
            raise ValidationError("You are currently blocked from booking due to unpaid damages/penalties.")

        if self.end_time <= self.start_time:
            raise ValidationError({"end_time": "End time must be after start time."})

        if self.attendees_count and self.hall.capacity and self.attendees_count > self.hall.capacity:
            raise ValidationError({"attendees_count": "Attendees exceed hall capacity."})

        # 1. Prevent overlaps with other regular Reservations
        qs = Reservation.objects.filter(hall=self.hall, booking_date=self.booking_date).exclude(id=self.id)
        qs = qs.exclude(status__in=[
            ReservationStatus.CANCELLED,
            ReservationStatus.REJECTED,
            ReservationStatus.CLOSED,
        ])
        qs = qs.filter(start_time__lt=self.end_time, end_time__gt=self.start_time)
        if qs.exists():
            raise ValidationError("This hall is already reserved for the selected time range.")

        # 2. Prevent overlaps with Hall Blocks
        from hall.models import HallBlock
        blocked = HallBlock.objects.filter(
            hall=self.hall,
            start_date__lte=self.booking_date,
            end_date__gte=self.booking_date,
        ).exists()
        if blocked:
            raise ValidationError("This date is blocked for this hall (Maintenance or Special Event).")

        # 3. Prevent overlaps with Internal Reservations
        ir_conflict = InternalReservation.objects.filter(
            hall=self.hall,
            booking_date=self.booking_date,
            start_time__lt=self.end_time,
            end_time__gt=self.start_time,
        ).exclude(status__in=[
            InternalReservationStatus.CANCELLED,
            InternalReservationStatus.REJECTED,
        ]).exists()
        if ir_conflict:
            raise ValidationError("This hall is reserved for University use during the selected time range.")


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

class TimelineEventType(models.TextChoices):
    BOOKING_SUBMITTED               = "BOOKING_SUBMITTED",               "Booking Submitted"
    VENTURES_REVIEW_STARTED         = "VENTURES_REVIEW_STARTED",         "Ventures Review Started"
    FORWARDED_TO_FACILITY           = "FORWARDED_TO_FACILITY",           "Forwarded to Facility"
    FACILITY_APPROVED               = "FACILITY_APPROVED",               "Facility Approved"
    FACILITY_REJECTED               = "FACILITY_REJECTED",               "Facility Rejected"
    RETURNED_TO_VENTURES            = "RETURNED_TO_VENTURES",            "Returned to Ventures"
    COUPON_REVIEWED                 = "COUPON_REVIEWED",                 "Coupon Reviewed"
    COUPON_ACTION                   = "COUPON_ACTION",                   "Coupon Action"
    BILLING_CONFIRMED               = "BILLING_CONFIRMED",               "Billing Confirmed"
    # ── Payment Authorization stage ───────────────────────────────────────
    PAYMENT_AUTHORIZATION_OPENED    = "PAYMENT_AUTHORIZATION_OPENED",    "Payment Authorization Opened"
    PAYMENT_AUTHORIZATION_SUBMITTED = "PAYMENT_AUTHORIZATION_SUBMITTED", "Payment Authorization Submitted"
    PAYMENT_DEADLINE_SET            = "PAYMENT_DEADLINE_SET",            "Payment Deadline Set"
    PAYMENT_DEADLINE_EXTENDED       = "PAYMENT_DEADLINE_EXTENDED",       "Payment Deadline Extended"
    PAYMENT_DEADLINE_EXPIRED        = "PAYMENT_DEADLINE_EXPIRED",        "Payment Deadline Expired"
    # ─────────────────────────────────────────────────────────────────────
    PAYMENT_REQUESTED               = "PAYMENT_REQUESTED",               "Payment Requested"
    PAYMENT_PROOF_UPLOADED          = "PAYMENT_PROOF_UPLOADED",          "Payment Proof Uploaded"
    PAYMENT_VERIFIED                = "PAYMENT_VERIFIED",                "Payment Verified"
    PAYMENT_REJECTED                = "PAYMENT_REJECTED",                "Payment Rejected"
    BOOKING_APPROVED                = "BOOKING_APPROVED",                "Booking Approved"
    BOOKING_REJECTED                = "BOOKING_REJECTED",                "Booking Rejected"
    PERMIT_GENERATED                = "PERMIT_GENERATED",                "Booking Permit Generated"
    EVENT_COMPLETED                 = "EVENT_COMPLETED",                 "Event Completed"
    INSPECTION_OPENED               = "INSPECTION_OPENED",               "Post-Event Inspection Opened"
    INSPECTION_COMPLETED            = "INSPECTION_COMPLETED",            "Inspection Completed"
    INSPECTION_REMINDER_SENT        = "INSPECTION_REMINDER_SENT",        "Inspection Reminder Sent"
    DAMAGE_ASSESSED                 = "DAMAGE_ASSESSED",                 "Damage Assessed"
    DAMAGE_INVOICE_ISSUED           = "DAMAGE_INVOICE_ISSUED",           "Damage Invoice Issued"
    DAMAGE_PAYMENT_UPLOADED         = "DAMAGE_PAYMENT_UPLOADED",         "Damage Payment Proof Uploaded"
    DAMAGE_PAYMENT_VERIFIED         = "DAMAGE_PAYMENT_VERIFIED",         "Damage Payment Verified"
    LIABILITY_FORGIVEN              = "LIABILITY_FORGIVEN",              "Liability Forgiven"
    PENALTY_CREATED                 = "PENALTY_CREATED",                 "Penalty Created"
    PENALTY_UPDATED                 = "PENALTY_UPDATED",                 "Penalty Updated"
    CASE_CLOSED                     = "CASE_CLOSED",                     "Case Closed"
    DOCUMENT_UPLOADED               = "DOCUMENT_UPLOADED",               "Document Uploaded"
    MESSAGE_SENT                    = "MESSAGE_SENT",                    "Message Sent"
    NOTE_ADDED                      = "NOTE_ADDED",                      "Note Added"
    STATUS_OVERRIDE                 = "STATUS_OVERRIDE",                 "Status Override (Admin)"
    RESTRICTION_REMOVED             = "RESTRICTION_REMOVED",             "Restriction Removed"
    INFORMATION_REQUESTED           = "INFORMATION_REQUESTED",           "Information Requested"


class BookingTimeline(models.Model):
    reservation  = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="timeline_events")
    event_type   = models.CharField(max_length=50, choices=TimelineEventType.choices)
    title        = models.CharField(max_length=255)
    description  = models.TextField(blank=True)
    actor        = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )
    actor_role   = models.CharField(max_length=30, blank=True)
    timestamp    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp"]

    def __str__(self) -> str:
        return f"{self.reservation.booking_reference} — {self.title}"


# ---------------------------------------------------------------------------
# Communication Thread
# ---------------------------------------------------------------------------

class MessageType(models.TextChoices):
    APPLICANT_VISIBLE  = "APPLICANT_VISIBLE",  "Applicant Visible"
    INTERNAL           = "INTERNAL",           "Internal Management"
    SYSTEM_GENERATED   = "SYSTEM_GENERATED",   "System Generated"


class CommunicationThread(models.Model):
    reservation = models.OneToOneField(Reservation, on_delete=models.CASCADE, related_name="thread")
    created_at  = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Thread — {self.reservation.booking_reference}"


class ThreadMessage(models.Model):
    thread       = models.ForeignKey(CommunicationThread, on_delete=models.CASCADE, related_name="messages")
    sender       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    content      = models.TextField()
    message_type = models.CharField(
        max_length=25, choices=MessageType.choices,
        default=MessageType.APPLICANT_VISIBLE,
    )
    parent       = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replies",
    )
    mentions     = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="mentioned_in_messages",
    )
    target_roles = models.CharField(
        max_length=255, blank=True,
        help_text="Comma-separated list of roles allowed to view this message (e.g. 'VENTURES,BURSARY,APPLICANT')."
    )
    created_at   = models.DateTimeField(auto_now_add=True)

    # Backward compat flag
    is_staff_note = models.BooleanField(
        default=False,
        help_text="True when message_type=INTERNAL (legacy compat)"
    )
    read_by_applicant = models.BooleanField(default=False)
    read_by_staff     = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Msg on {self.thread.reservation.booking_reference} by {self.sender}"

    def save(self, *args, **kwargs):
        # Keep is_staff_note in sync with target_roles for backward compat
        if self.target_roles and "APPLICANT" not in self.target_roles:
            self.is_staff_note = True
        elif self.message_type == MessageType.INTERNAL:
            self.is_staff_note = True
        else:
            self.is_staff_note = False
        super().save(*args, **kwargs)


class ThreadAttachment(models.Model):
    message     = models.ForeignKey(ThreadMessage, on_delete=models.CASCADE, related_name="attachments")
    file        = models.FileField(upload_to="reservations/thread_attachments/", max_length=500)
    filename    = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Attachment: {self.filename or self.file.name}"


class MessageReadStatus(models.Model):
    message   = models.ForeignKey(ThreadMessage, on_delete=models.CASCADE, related_name="read_statuses")
    user      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    read_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "user")

    def __str__(self) -> str:
        return f"{self.user} read msg {self.message_id}"


# ---------------------------------------------------------------------------
# Damage Report (enhanced)
# ---------------------------------------------------------------------------

class DamageReport(models.Model):
    user               = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    reservation        = models.ForeignKey(Reservation, on_delete=models.SET_NULL, null=True, blank=True, related_name="damage_reports")
    description        = models.TextField()
    affected_items     = models.TextField(blank=True, help_text="List of items damaged")
    amount             = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Estimated repair/replacement cost")
    cost_estimate      = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Formal assessment cost estimate")
    is_paid            = models.BooleanField(default=False)
    is_forgiven        = models.BooleanField(default=False)
    admin_waiver_reason = models.TextField(blank=True, help_text="Reason for admin forgiveness/waiver")
    waived_by          = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="damage_waivers",
    )
    waived_at          = models.DateTimeField(null=True, blank=True)
    assessment_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="damage_assessments",
    )
    assessment_date    = models.DateField(null=True, blank=True)
    invoice_generated  = models.BooleanField(default=False)
    created_at         = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Damage — {self.user} — {self.amount}"


class DamagePhoto(models.Model):
    damage_report = models.ForeignKey(DamageReport, on_delete=models.CASCADE, related_name="photos")
    photo         = models.ImageField(upload_to="reservations/damage_photos/", max_length=500)
    caption       = models.CharField(max_length=255, blank=True)
    uploaded_by   = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Photo for damage {self.damage_report_id}"


class DamageDocument(models.Model):
    damage_report = models.ForeignKey(DamageReport, on_delete=models.CASCADE, related_name="supporting_documents")
    file          = models.FileField(upload_to="reservations/damage_documents/", max_length=500)
    description   = models.CharField(max_length=255, blank=True)
    uploaded_by   = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Doc for damage {self.damage_report_id}"


# ---------------------------------------------------------------------------
# Penalty
# ---------------------------------------------------------------------------

class Penalty(models.Model):
    title       = models.CharField(max_length=200)
    description = models.TextField()
    amount      = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    user        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="penalties")
    reservation = models.ForeignKey(Reservation, on_delete=models.SET_NULL, null=True, blank=True, related_name="penalties")
    is_paid     = models.BooleanField(default=False)
    is_forgiven = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Penalty — {self.user} — {self.amount}"


# ---------------------------------------------------------------------------
# Booking Status History & Logs (retained for full backward compat)
# ---------------------------------------------------------------------------

class BookingStatusHistory(models.Model):
    reservation     = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="status_history")
    previous_status = models.CharField(max_length=50)
    new_status      = models.CharField(max_length=50)
    changed_by      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    notes           = models.TextField(blank=True)
    timestamp       = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        return f"{self.reservation.booking_reference}: {self.previous_status} -> {self.new_status}"


class BookingLog(models.Model):
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="logs")
    actor       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action      = models.CharField(max_length=255)
    details     = models.TextField(blank=True)
    timestamp   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        return f"{self.reservation.booking_reference} - {self.action}"


# ---------------------------------------------------------------------------
# Backward-compat: ReservationMessage — now wraps ThreadMessage
# New code should use ThreadMessage directly.
# ---------------------------------------------------------------------------

class ReservationMessage(models.Model):
    reservation       = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="messages")
    sender            = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    content           = models.TextField()
    is_staff_note     = models.BooleanField(default=False, help_text="Internal notes not visible to applicants")
    read_by_applicant = models.BooleanField(default=False)
    read_by_staff     = models.BooleanField(default=False)
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Message on {self.reservation.booking_reference} by {self.sender}"


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class DocumentType(models.TextChoices):
    AUTHORIZATION_LETTER = "AUTHORIZATION_LETTER", "Authorization Letter"
    PERMIT               = "PERMIT",               "Permit"
    IMAGE                = "IMAGE",                "Image"
    PAYMENT_PROOF        = "PAYMENT_PROOF",        "Payment Proof"
    DAMAGE_PROOF         = "DAMAGE_PROOF",         "Damage Payment Proof"
    OTHER                = "OTHER",                "Other"


class ReservationDocument(models.Model):
    reservation   = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="documents")
    document_type = models.CharField(max_length=50, choices=DocumentType.choices)
    file          = models.FileField(upload_to="reservations/documents/", max_length=500)
    version       = models.PositiveIntegerField(default=1)
    uploaded_by   = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at   = models.DateTimeField(auto_now_add=True)
    # Routing: comma-separated roles that can view this document.
    # Facility is NEVER a target — documents flow only between Applicant, Ventures, and Bursary.
    visible_to    = models.CharField(
        max_length=100,
        default="VENTURES",
        blank=True,
        help_text=(
            "Comma-separated list of roles that can view this document. "
            "Valid values: APPLICANT, FACILITY, VENTURES, BURSARY."
        ),
    )

    class Meta:
        unique_together = ("reservation", "document_type", "version")
        ordering = ["document_type", "version"]

    def __str__(self) -> str:
        return f"{self.reservation.booking_reference} - {self.document_type} v{self.version}"


# ---------------------------------------------------------------------------
# Hall Inspection Report (replaces simple HallInspection)
# ---------------------------------------------------------------------------

class ConditionRating(models.TextChoices):
    EXCELLENT = "EXCELLENT", "Excellent"
    GOOD      = "GOOD",      "Good"
    FAIR      = "FAIR",      "Fair"
    POOR      = "POOR",      "Poor"
    DAMAGED   = "DAMAGED",   "Damaged"


class InspectionOutcome(models.TextChoices):
    NO_DAMAGE    = "NO_DAMAGE",    "No Damage — Clear"
    DAMAGE_FOUND = "DAMAGE_FOUND", "Damage Found"


class HallInspectionReport(models.Model):
    reservation      = models.OneToOneField(Reservation, on_delete=models.CASCADE, related_name="inspection_report")
    hall_condition   = models.CharField(max_length=20, choices=ConditionRating.choices, blank=True)
    cleanliness      = models.CharField(max_length=20, choices=ConditionRating.choices, blank=True)
    furniture_status = models.CharField(max_length=20, choices=ConditionRating.choices, blank=True)
    equipment_status = models.CharField(max_length=20, choices=ConditionRating.choices, blank=True)
    damage_found     = models.BooleanField(default=False)
    notes            = models.TextField(blank=True)
    officer          = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="inspection_reports",
    )
    inspected_at     = models.DateTimeField(null=True, blank=True)
    outcome          = models.CharField(
        max_length=20, choices=InspectionOutcome.choices, blank=True,
    )

    class Meta:
        ordering = ["-inspected_at"]

    def __str__(self) -> str:
        return f"Inspection for {self.reservation.booking_reference}: {self.outcome}"


class InspectionPhoto(models.Model):
    inspection  = models.ForeignKey(HallInspectionReport, on_delete=models.CASCADE, related_name="photos")
    photo       = models.ImageField(upload_to="reservations/inspection_photos/", max_length=500)
    caption     = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Photo for inspection {self.inspection_id}"


# ---------------------------------------------------------------------------
# Legacy HallInspection — retained for backward compat (old records)
# ---------------------------------------------------------------------------

class InspectionResult(models.TextChoices):
    PASSED         = "PASSED",         "Passed"
    FAILED         = "FAILED",         "Failed"
    DAMAGE_REPORTED = "DAMAGE_REPORTED", "Damage Reported"


class HallInspection(models.Model):
    reservation  = models.OneToOneField(Reservation, on_delete=models.CASCADE, related_name="inspection")
    inspector    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    result       = models.CharField(max_length=20, choices=InspectionResult.choices)
    notes        = models.TextField(blank=True)
    inspected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-inspected_at"]

    def __str__(self) -> str:
        return f"Legacy Inspection for {self.reservation.booking_reference}: {self.result}"


# ---------------------------------------------------------------------------
# Internal Reservations (unchanged)
# ---------------------------------------------------------------------------

class InternalReservationStatus(models.TextChoices):
    DRAFT     = "DRAFT",     "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    APPROVED  = "APPROVED",  "Approved"
    REJECTED  = "REJECTED",  "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"


class InternalReservation(models.Model):
    """
    Internal university reservation for departments, faculties, and official programs.
    No payment required — blocks hall, appears on calendar and in reports.
    Created by Facility staff or Admin on behalf of the requesting department.
    """
    hall = models.ForeignKey(Hall, on_delete=models.PROTECT, related_name="internal_reservations")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_internal_reservations",
    )
    requesting_department = models.CharField(max_length=200, help_text="Department or unit requesting the hall")
    event_name            = models.CharField(max_length=255)
    purpose               = models.CharField(max_length=30, choices=ReservationPurpose.choices)
    organizer_name        = models.CharField(max_length=200, blank=True, help_text="Name of the event organizer")
    organizer_phone       = models.CharField(max_length=30, blank=True)
    attendees_count       = models.PositiveIntegerField(default=0)

    booking_date = models.DateField()
    start_time   = models.TimeField()
    end_time     = models.TimeField()

    status = models.CharField(
        max_length=20,
        choices=InternalReservationStatus.choices,
        default=InternalReservationStatus.SUBMITTED,
    )
    reference    = models.CharField(max_length=40, unique=True, editable=False)
    notes        = models.TextField(blank=True)
    is_recurring = models.BooleanField(default=False, help_text="Marks recurring departmental events")
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-booking_date", "-start_time"]
        indexes = [
            models.Index(fields=["hall", "booking_date"]),
            models.Index(fields=["status"]),
        ]

    def save(self, *args, **kwargs):
        if not self.reference:
            from django.utils import timezone as tz
            self.reference = tz.now().strftime("INT-%Y%m%d-%H%M%S") + f"-{uuid.uuid4().hex[:6]}"
        super().save(*args, **kwargs)

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.end_time and self.start_time and self.end_time <= self.start_time:
            raise ValidationError({"end_time": "End time must be after start time."})

    def __str__(self) -> str:
        return f"{self.reference} — {self.hall.name} ({self.requesting_department})"


# ---------------------------------------------------------------------------
# Payment Authorization (new — Payment Authorization stage)
# ---------------------------------------------------------------------------

class PaymentDeadlineType(models.TextChoices):
    HOURS_24 = "HOURS_24", "24 Hours"
    HOURS_48 = "HOURS_48", "48 Hours"
    HOURS_72 = "HOURS_72", "72 Hours"
    CUSTOM   = "CUSTOM",   "Custom Date & Time"


class CouponActionChoice(models.TextChoices):
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    REPLACED = "REPLACED", "Replaced"
    REMOVED  = "REMOVED",  "Removed"
    APPLIED  = "APPLIED",  "Applied"


class PaymentAuthorization(models.Model):
    """
    Created by Ventures during the PAYMENT_AUTHORIZATION stage.
    Records the financial breakdown, coupon decision, and payment deadline
    before dispatching the payment request to the applicant.
    """
    reservation     = models.OneToOneField(
        Reservation, on_delete=models.CASCADE, related_name="payment_authorization",
    )
    authorized_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payment_authorizations_created",
    )
    authorized_at   = models.DateTimeField(auto_now_add=True)

    # ── Financial breakdown ───────────────────────────────────────────────
    hall_price          = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    security_deposit    = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    extra_charges       = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    extra_charges_notes = models.CharField(max_length=255, blank=True)
    penalty_amount      = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    coupon_discount     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_rate            = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                            help_text="VAT percentage (e.g. 7.5 for 7.5%). Set 0 if not applicable.")
    vat_amount          = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    outstanding_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ── Coupon decision ───────────────────────────────────────────────────
    coupon_code         = models.CharField(max_length=50, blank=True)
    coupon_action       = models.CharField(
        max_length=20, choices=CouponActionChoice.choices, blank=True,
    )
    coupon_action_notes = models.TextField(blank=True)
    coupon_action_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="coupon_action_authorizations",
    )
    coupon_action_at    = models.DateTimeField(null=True, blank=True)

    # ── Payment deadline ──────────────────────────────────────────────────
    deadline_type           = models.CharField(
        max_length=20, choices=PaymentDeadlineType.choices, default=PaymentDeadlineType.HOURS_48,
    )
    payment_deadline        = models.DateTimeField(
        null=True, blank=True,
        help_text="Absolute datetime by which payment must be received.",
    )
    deadline_set_by         = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payment_deadlines_set",
    )
    deadline_set_at         = models.DateTimeField(null=True, blank=True)
    deadline_extended       = models.BooleanField(default=False)
    deadline_extension_count = models.PositiveIntegerField(default=0)

    # ── Status ────────────────────────────────────────────────────────────
    is_submitted    = models.BooleanField(default=False)
    submitted_at    = models.DateTimeField(null=True, blank=True)
    is_expired      = models.BooleanField(default=False)
    expired_at      = models.DateTimeField(null=True, blank=True)

    # ── Ventures notes ───────────────────────────────────────────────────
    ventures_notes  = models.TextField(blank=True)

    class Meta:
        ordering = ["-authorized_at"]

    def __str__(self) -> str:
        return f"PaymentAuth — {self.reservation.booking_reference}"

    def compute_total(self) -> None:
        """Recompute vat_amount, total_amount from component fields."""
        from decimal import Decimal
        subtotal = (
            self.hall_price
            + self.security_deposit
            + self.extra_charges
            + self.penalty_amount
            - self.discount_amount
            - self.coupon_discount
        )
        if self.vat_rate:
            self.vat_amount = (subtotal * self.vat_rate / Decimal("100")).quantize(Decimal("0.01"))
        else:
            self.vat_amount = Decimal("0")
        self.total_amount = max(subtotal + self.vat_amount, Decimal("0"))


class DeadlineExtensionLog(models.Model):
    """
    Permanent audit record of every payment deadline extension/shortening/removal.
    """
    class Action(models.TextChoices):
        EXTENDED  = "EXTENDED",  "Extended"
        SHORTENED = "SHORTENED", "Shortened"
        REMOVED   = "REMOVED",   "Removed"

    authorization = models.ForeignKey(
        PaymentAuthorization, on_delete=models.CASCADE, related_name="extension_logs",
    )
    old_deadline  = models.DateTimeField(null=True, blank=True)
    new_deadline  = models.DateTimeField(null=True, blank=True)
    action        = models.CharField(max_length=20, choices=Action.choices)
    actor         = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )
    notes         = models.TextField(blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.action} — {self.authorization.reservation.booking_reference} @ {self.created_at}"


class CouponActionLog(models.Model):
    """
    Immutable, permanent record of every coupon action taken on a booking.
    Records approved, rejected, replaced, removed, and applied events.
    """
    reservation = models.ForeignKey(
        Reservation, on_delete=models.CASCADE, related_name="coupon_action_logs",
    )
    action      = models.CharField(max_length=20, choices=CouponActionChoice.choices)
    coupon_code = models.CharField(max_length=50, blank=True)
    actor       = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )
    actor_role  = models.CharField(max_length=30, blank=True)
    old_code    = models.CharField(max_length=50, blank=True, help_text="Previous coupon code (on replace)")
    notes       = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.action}: {self.coupon_code} on {self.reservation.booking_reference}"


class InspectionReminder(models.Model):
    """
    Tracks inspection reminder notifications sent to Facility after an event ends.
    Prevents duplicate sends and gives Ventures visibility of reminder history.
    """
    reservation     = models.ForeignKey(
        Reservation, on_delete=models.CASCADE, related_name="inspection_reminders",
    )
    reminder_number = models.PositiveIntegerField(default=1, help_text="1=immediate, 2=24h, 3=48h")
    sent_at         = models.DateTimeField(auto_now_add=True)
    sent_to_roles   = models.CharField(max_length=100, default="FACILITY",
                        help_text="Comma-separated list of roles notified.")

    class Meta:
        ordering = ["-sent_at"]
        unique_together = (("reservation", "reminder_number"),)

    def __str__(self) -> str:
        return f"Reminder #{self.reminder_number} for {self.reservation.booking_reference}"


class VenturesPenaltyType(models.TextChoices):
    PENALTY         = "PENALTY",         "Penalty"
    ADMINISTRATIVE  = "ADMINISTRATIVE",  "Administrative Fee"
    LATE_CHARGE     = "LATE_CHARGE",     "Late Charge"
    ADDITIONAL      = "ADDITIONAL",      "Additional Charge"


class VenturesPenaltyRecord(models.Model):
    """
    Links a Ventures-created penalty to a reservation case with type and audit info.
    The base Penalty model stores the financial record; this stores the management context.
    """
    reservation  = models.ForeignKey(
        Reservation, on_delete=models.CASCADE, related_name="ventures_penalty_records",
    )
    penalty      = models.OneToOneField(
        Penalty, on_delete=models.CASCADE, related_name="ventures_record",
    )
    penalty_type = models.CharField(max_length=20, choices=VenturesPenaltyType.choices,
                    default=VenturesPenaltyType.PENALTY)
    created_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_ventures_penalties",
    )
    created_at   = models.DateTimeField(auto_now_add=True)
    notes        = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_penalty_type_display()} — {self.reservation.booking_reference} — ₦{self.penalty.amount}"
