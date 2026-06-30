from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.services import notify_and_email
from reservations.models import Reservation


class Command(BaseCommand):
    help = "Send reminder notifications/emails for upcoming approved reservations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--minutes",
            type=int,
            default=60,
            help="How many minutes before start time to remind (default: 60).",
        )

    def handle(self, *args, **options):
        minutes = int(options["minutes"])
        now = timezone.localtime()
        today = now.date()

        # We keep reminders simple and safe: look at today's approved reservations only.
        qs = Reservation.objects.select_related("user", "hall").filter(
            booking_date=today,
            status="APPROVED_PAYMENT",
            reminded_at__isnull=True,
        )

        sent = 0
        window_start = now + timedelta(minutes=minutes - 5)
        window_end = now + timedelta(minutes=minutes + 5)

        for r in qs.iterator():
            start_dt = timezone.make_aware(timezone.datetime.combine(r.booking_date, r.start_time))
            start_dt = timezone.localtime(start_dt)
            if window_start <= start_dt <= window_end:
                notify_and_email(
                    user=r.user,
                    title="Upcoming hall reservation reminder",
                    message=(
                        f"Reminder: {r.hall.name} is reserved for you today at {r.start_time} "
                        f"({r.booking_reference})."
                    ),
                )
                r.reminded_at = timezone.now()
                r.save(update_fields=["reminded_at"])
                sent += 1

        self.stdout.write(self.style.SUCCESS(f"Reminders sent: {sent}"))

