import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from reservations.models import Reservation, BookingCaseStatus, PaymentAuthorization
from reservations.services import WorkflowService

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Finds and cancels reservations whose payment deadline has expired.'

    def handle(self, *args, **options):
        now = timezone.now()
        
        # 1. Find all reservations in AWAITING_PAYMENT state
        # 2. Join with PaymentAuthorization where deadline < now
        expired_reservations = Reservation.objects.filter(
            case_status=BookingCaseStatus.AWAITING_PAYMENT,
            payment_authorization__payment_deadline__lt=now,
            payment_authorization__is_expired=False
        ).select_related("payment_authorization")

        count = 0
        for reservation in expired_reservations:
            self.stdout.write(f"Expiring reservation {reservation.booking_reference} (Deadline: {reservation.payment_authorization.payment_deadline})")
            
            # Transition the workflow to PAYMENT_EXPIRED
            result = WorkflowService.expire_payment(reservation=reservation)
            if result.ok:
                count += 1
                logger.info(f"Successfully expired reservation {reservation.booking_reference}")
            else:
                self.stderr.write(f"Failed to expire {reservation.booking_reference}: {result.error}")
                logger.error(f"Failed to expire {reservation.booking_reference}: {result.error}")

        self.stdout.write(self.style.SUCCESS(f'Successfully expired {count} reservations.'))
