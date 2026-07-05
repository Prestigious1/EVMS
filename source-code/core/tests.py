from datetime import date, time
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from core.models import Announcement
from hall.models import Hall, HallImage
from payments.models import Payment
from reservations.models import Reservation
from users.models import User


class ResetProjectDataCommandTests(TestCase):
    def test_command_keeps_halls_announcements_and_users_but_removes_booking_data(self):
        admin = User.objects.create_user(
            username="admin_reset",
            email="admin_reset@example.com",
            password="StrongPass123!",
            role="ADMIN",
            is_staff=True,
            is_superuser=True,
        )
        user = User.objects.create_user(
            username="student_reset",
            email="student_reset@example.com",
            password="StrongPass123!",
            role="STUDENT",
        )

        hall = Hall.objects.create(
            name="Test Hall",
            faculty="Science",
            building="Main Block",
            location_description="Ground floor",
            daily_rate=Decimal("50000.00"),
            security_deposit=Decimal("10000.00"),
        )
        HallImage.objects.create(hall=hall, image="halls/gallery/test.jpg", is_cover=True)
        announcement = Announcement.objects.create(title="Welcome", content="Hello", created_by=admin)

        reservation = Reservation.objects.create(
            user=user,
            hall=hall,
            purpose="MEETING",
            booking_date=date(2026, 1, 10),
            start_time=time(9, 0),
            end_time=time(11, 0),
            status="SUBMITTED",
            case_status="SUBMITTED",
        )
        Payment.objects.create(
            user=user,
            reservation=reservation,
            amount=Decimal("50000.00"),
            payment_method="TRANSFER",
        )

        call_command("reset_project_data", confirm=True, verbosity=0)

        self.assertTrue(Hall.objects.filter(pk=hall.pk).exists())
        self.assertTrue(HallImage.objects.filter(hall=hall).exists())
        self.assertTrue(Announcement.objects.filter(pk=announcement.pk).exists())
        self.assertTrue(User.objects.filter(pk=admin.pk).exists())
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertFalse(Reservation.objects.exists())
        self.assertFalse(Payment.objects.exists())
