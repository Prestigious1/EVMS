from decimal import Decimal
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from hall.models import Hall, HallBlock
from reservations.models import (
    BookingStatusHistory,
    Reservation,
    ReservationStatus,
    ReservationDocument,
    HallInspection,
    InspectionResult,
)
from reservations.services import WorkflowService, TransitionResult
from payments.models import Coupon, DiscountType

User = get_user_model()


def _make_hall(name="Test Hall", **kwargs):
    """Helper to create a Hall with current field names."""
    defaults = {
        "category": "MULTIPURPOSE",
        "capacity": 100,
        "faculty": "General",
        "building": "Block A",
        "daily_rate": 1000,
    }
    defaults.update(kwargs)
    return Hall.objects.create(name=name, **defaults)


class WorkflowServiceTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="ventures",
            email="ventures@lasu.edu.ng",
            password="testpass123",
            role="VENTURES",
        )
        self.facility_user = User.objects.create_user(
            username="facility",
            email="facility@lasu.edu.ng",
            password="testpass123",
            role="FACILITY",
        )
        self.applicant = User.objects.create_user(
            username="student",
            email="student@lasu.edu.ng",
            password="testpass123",
            role="STUDENT",
        )
        self.bursary_user = User.objects.create_user(
            username="bursary",
            email="bursary@lasu.edu.ng",
            password="testpass123",
            role="BURSARY",
        )
        self.hall = _make_hall("Main Hall")
        from reservations.models import BookingCaseStatus
        self.reservation = Reservation.objects.create(
            user=self.applicant,
            hall=self.hall,
            purpose="EVENT",
            attendees_count=50,
            booking_date=date(2026, 7, 1),
            start_time="09:00",
            end_time="11:00",
            status=ReservationStatus.SUBMITTED,
            case_status=BookingCaseStatus.SUBMITTED,
        )

    def test_full_workflow_writes_complete_history(self):
        from reservations.models import BookingCaseStatus
        self.reservation.total_cost = Decimal("10000.00")
        self.reservation.save()
        transitions = [
            (WorkflowService.forward_to_facility, {
                "actor": self.user,
                "notes": "Forwarded to Facility",
            }),
            (WorkflowService.facility_approve, {
                "actor": self.facility_user,
                "notes": "Available",
            }),
            (WorkflowService.open_payment_authorization, {
                "actor": self.user,
                "notes": "Cost assigned",
            }),
            (WorkflowService.submit_payment_authorization, {
                "actor": self.user,
                "notes": "Cost assigned",
            }),
            (WorkflowService.submit_payment_proof, {
                "actor": self.applicant,
                "notes": "Payment initiated",
            }),
            (WorkflowService.bursary_verify_payment, {
                "actor": self.bursary_user,
                "notes": "Paid",
            }),
            (WorkflowService.ventures_final_approve, {
                "actor": self.user,
                "notes": "Confirmed",
            }),
            (WorkflowService.mark_event_completed, {
                "actor": self.facility_user,
                "notes": "Completed",
            }),
            (WorkflowService.open_inspection, {
                "actor": self.facility_user,
                "notes": "Inspection opened",
            }),
            (WorkflowService.inspection_no_damage, {
                "actor": self.facility_user,
                "notes": "No damage",
            }),
        ]
        expected_statuses = [
            BookingCaseStatus.UNDER_FACILITY_REVIEW,
            BookingCaseStatus.FACILITY_APPROVED,
            BookingCaseStatus.PAYMENT_AUTHORIZATION,
            BookingCaseStatus.AWAITING_PAYMENT,
            BookingCaseStatus.UNDER_BURSARY_VERIFICATION, # skip PAYMENT_SUBMITTED because it auto-advances
            BookingCaseStatus.AWAITING_FINAL_APPROVAL,    # skip PAYMENT_VERIFIED because it auto-advances
            BookingCaseStatus.BOOKING_APPROVED,
            BookingCaseStatus.EVENT_COMPLETED,
            BookingCaseStatus.UNDER_POST_EVENT_INSPECTION,
            BookingCaseStatus.CASE_CLOSED,
        ]
        
        from reservations.models import BookingTimeline
        for (func, kwargs), expected in zip(transitions, expected_statuses):
            result = func(reservation=self.reservation, **kwargs)
            self.assertTrue(result.ok, msg=result.error)
            self.reservation.refresh_from_db()
            self.assertEqual(self.reservation.case_status, expected)

        timeline_count = BookingTimeline.objects.filter(reservation=self.reservation).count()
        # Timeline gets +1 for submission (in real usage), +1 for each transition, +1 for PAYMENT_SUBMITTED auto-forward.
        self.assertGreater(timeline_count, len(transitions))

    def test_invalid_transition_returns_error(self):
        # SUBMITTED -> PAYMENT_VERIFIED is invalid
        result = WorkflowService.bursary_verify_payment(reservation=self.reservation, actor=self.bursary_user)
        self.assertFalse(result.ok)
        self.assertIn("Invalid transition", result.error)

    def test_reject_from_submitted(self):
        from reservations.models import BookingCaseStatus
        result = WorkflowService.ventures_reject(reservation=self.reservation, actor=self.user, notes="Rejected")
        self.assertTrue(result.ok)
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.case_status, BookingCaseStatus.BOOKING_REJECTED)

    def test_cancel_from_submitted(self):
        from reservations.models import BookingCaseStatus
        result = WorkflowService.admin_close_case(reservation=self.reservation, actor=self.applicant, notes="Cancelled")
        self.assertTrue(result.ok)
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.case_status, BookingCaseStatus.CASE_CLOSED)



class CouponTestCase(TestCase):
    """Tests for the Coupon model (now in payments.models)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="student2",
            email="student2@lasu.edu.ng",
            password="testpass123",
            role="STUDENT",
            department="Computer Science",
        )
        self.hall = _make_hall("Coupon Test Hall", category="SEMINAR", daily_rate=500)
        # Create coupon using current field names from payments.models.Coupon
        self.coupon = Coupon.objects.create(
            code="TEST20",
            name="Test 20% Discount",
            discount_type=DiscountType.PERCENTAGE,
            value=20,
            is_active=True,
            usage_per_user=2,
            min_booking_amount=1000,
            max_discount=5000,
            role_restriction="STUDENT",
            created_by=self.user,
        )

    def test_coupon_str(self):
        self.assertIn("TEST20", str(self.coupon))

    def test_coupon_is_active(self):
        self.assertTrue(self.coupon.is_active)

    def test_coupon_discount_type(self):
        self.assertEqual(self.coupon.discount_type, DiscountType.PERCENTAGE)

    def test_coupon_value(self):
        self.assertEqual(self.coupon.value, 20)

    def test_coupon_max_discount(self):
        self.assertEqual(self.coupon.max_discount, 5000)


class HallBlockTestCase(TestCase):
    def setUp(self):
        self.hall = _make_hall("Block Hall", category="LECTURE", capacity=200, daily_rate=800)

    def test_hall_block_clean_valid(self):
        block = HallBlock(hall=self.hall, start_date=date(2026, 7, 1), end_date=date(2026, 7, 5))
        block.full_clean()
        block.save()
        self.assertEqual(HallBlock.objects.count(), 1)

    def test_hall_block_clean_invalid(self):
        from django.core.exceptions import ValidationError
        block = HallBlock(hall=self.hall, start_date=date(2026, 7, 5), end_date=date(2026, 7, 1))
        with self.assertRaises(ValidationError):
            block.full_clean()
