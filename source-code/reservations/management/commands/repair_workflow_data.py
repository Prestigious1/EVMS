from django.core.management.base import BaseCommand
from reservations.models import Reservation, BookingCaseStatus, ReservationStatus

class Command(BaseCommand):
    help = 'Repairs diverged case_status for reservations that were progressed via legacy methods.'

    def handle(self, *args, **options):
        reservations = Reservation.objects.all()
        fixed_count = 0
        
        for res in reservations:
            # Bug 1/2: Facility approved legacy path, but stuck at UNDER_VENTURES_REVIEW or UNDER_FACILITY_REVIEW
            if res.status == ReservationStatus.AVAILABLE and res.case_status in (BookingCaseStatus.UNDER_VENTURES_REVIEW, BookingCaseStatus.UNDER_FACILITY_REVIEW):
                res.case_status = BookingCaseStatus.FACILITY_APPROVED
                res.save(update_fields=['case_status'])
                self.stdout.write(self.style.SUCCESS(f"Fixed {res.booking_reference}: {res.case_status} -> FACILITY_APPROVED"))
                fixed_count += 1
            # Bug 3: Ventures rejected legacy path, but stuck elsewhere
            elif res.status == ReservationStatus.REJECTED and res.case_status not in (BookingCaseStatus.BOOKING_REJECTED, BookingCaseStatus.FACILITY_REJECTED):
                res.case_status = BookingCaseStatus.BOOKING_REJECTED
                res.save(update_fields=['case_status'])
                self.stdout.write(self.style.SUCCESS(f"Fixed {res.booking_reference}: {res.case_status} -> BOOKING_REJECTED"))
                fixed_count += 1
            
        self.stdout.write(self.style.SUCCESS(f"Successfully repaired {fixed_count} reservations."))
