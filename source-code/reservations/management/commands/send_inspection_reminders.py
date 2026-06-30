import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from reservations.models import Reservation, BookingCaseStatus, InspectionReminder
from reservations.services import WorkflowService

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Sends reminders to Facility officers for post-event inspections.'

    def handle(self, *args, **options):
        now = timezone.now()
        yesterday = now - timedelta(days=1)
        
        # Find bookings where event has passed (end_time was yesterday or earlier)
        # and case is UNDER_POST_EVENT_INSPECTION
        # This is a bit tricky if booking_date is just a DateField.
        # We can just filter for booking_date <= yesterday.date()
        
        pending_inspections = Reservation.objects.filter(
            case_status=BookingCaseStatus.UNDER_POST_EVENT_INSPECTION,
            booking_date__lte=yesterday.date()
        )

        count = 0
        for reservation in pending_inspections:
            # Check if we already sent a reminder recently
            last_reminder = InspectionReminder.objects.filter(
                reservation=reservation
            ).order_by("-sent_at").first()
            
            if last_reminder and (now - last_reminder.sent_at).days < 2:
                continue # Only send once every 2 days
                
            self.stdout.write(f"Sending inspection reminder for {reservation.booking_reference}")
            result = WorkflowService.send_inspection_reminder(reservation=reservation)
            
            if result.ok:
                count += 1
            else:
                self.stderr.write(f"Failed to send reminder for {reservation.booking_reference}: {result.error}")

        self.stdout.write(self.style.SUCCESS(f'Successfully sent {count} inspection reminders.'))
