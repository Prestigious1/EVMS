from django.conf import settings
from django.db import models

from reservations.models import DamageReport, Penalty, Reservation
from hall.models import DepartmentChoices


class DiscountType(models.TextChoices):
    PERCENTAGE = "PERCENTAGE", "Percentage"
    FIXED = "FIXED", "Fixed Amount"


class Coupon(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, verbose_name="Active")
    
    discount_type = models.CharField(max_length=20, choices=DiscountType.choices)
    value = models.DecimalField(max_digits=12, decimal_places=2)
    
    min_booking_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    max_discount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    
    applicable_halls = models.ManyToManyField("hall.Hall", blank=True, related_name="coupons")
    applicable_categories = models.JSONField(default=list, blank=True)
    
    total_usage_limit = models.PositiveIntegerField(null=True, blank=True)
    usage_per_user = models.PositiveIntegerField(default=1)
    
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    
    faculty_restriction = models.CharField(max_length=200, blank=True)
    department_restriction = models.CharField(max_length=200, blank=True)
    role_restriction = models.CharField(max_length=50, blank=True)
    
    is_stackable = models.BooleanField(default=False)
    
    owner_department = models.CharField(max_length=30, choices=DepartmentChoices.choices, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PAID = "PAID", "Paid"
    FAILED = "FAILED", "Failed"


class PaymentMethod(models.TextChoices):
    CARD = "CARD", "Card"
    TRANSFER = "TRANSFER", "Transfer"


class PaymentProvider(models.TextChoices):
    PAYSTACK = "PAYSTACK", "Paystack"


class Payment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="payments")
    damage_report = models.ForeignKey(
        DamageReport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    penalty = models.ForeignKey(
        Penalty,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices)
    provider = models.CharField(max_length=20, choices=PaymentProvider.choices, default=PaymentProvider.PAYSTACK)

    currency = models.CharField(max_length=3, default="NGN")
    paystack_reference = models.CharField(max_length=120, blank=True)
    paystack_access_code = models.CharField(max_length=120, blank=True)
    transaction_reference = models.CharField(max_length=80, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.reservation.booking_reference} - {self.amount} - {self.status}"


class PaymentProofType(models.TextChoices):
    BOOKING = "BOOKING", "Booking Payment"
    DAMAGE  = "DAMAGE",  "Damage Payment"


class PaymentProofStatus(models.TextChoices):
    PENDING   = "PENDING",   "Pending Verification"
    VERIFIED  = "VERIFIED",  "Verified"
    REJECTED  = "REJECTED",  "Rejected"


class PaymentProof(models.Model):
    """
    Stores manual payment evidence uploaded by the applicant.
    Bursary reviews and either verifies or rejects each proof.
    """
    reservation     = models.ForeignKey(
        "reservations.Reservation",
        on_delete=models.CASCADE,
        related_name="payment_proofs",
    )
    uploaded_by     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payment_proofs")
    receipt_file    = models.FileField(upload_to="payments/proofs/", help_text="Scanned/photographed receipt or bank evidence")
    transaction_ref = models.CharField(max_length=120, blank=True, help_text="Bank/payment transaction reference number")
    amount_claimed  = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Amount applicant claims to have paid")
    payment_type    = models.CharField(max_length=10, choices=PaymentProofType.choices, default=PaymentProofType.BOOKING)
    status          = models.CharField(max_length=10, choices=PaymentProofStatus.choices, default=PaymentProofStatus.PENDING)
    bursary_notes   = models.TextField(blank=True, help_text="Bursary verification notes")
    verified_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="verified_payment_proofs",
    )
    verified_at     = models.DateTimeField(null=True, blank=True)
    uploaded_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return f"Proof for {self.reservation.booking_reference} — {self.payment_type} — {self.status}"

