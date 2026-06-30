import os
import django
import sys

sys.path.append(r"c:\Projects\EVMS\source-code")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hms_prj.settings")
django.setup()

from django.test import RequestFactory
from django.contrib.auth import get_user_model
from reports.views import admin_reports_dashboard

User = get_user_model()
user = User.objects.filter(role="ADMIN").first()
if not user:
    user = User.objects.create_superuser(username="admin123", email="admin123@test.com", password="password", role="ADMIN")

from reservations.models import Reservation, ReservationPurpose, BookingCaseStatus
from hall.models import Hall
hall = Hall.objects.first()
if not hall:
    hall = Hall.objects.create(name="Test Hall", capacity=100, price_per_hour=10)
Reservation.objects.create(
    user=user,
    hall=hall,
    event_name="Test Event",
    purpose=ReservationPurpose.MEETING,
    booking_date="2027-01-01",
    start_time="10:00:00",
    end_time="12:00:00",
    case_status=BookingCaseStatus.SUBMITTED
)

factory = RequestFactory()
request = factory.get("/reports/dashboard/")
request.user = user

try:
    response = admin_reports_dashboard(request)
    print("SUCCESS, Status Code:", response.status_code)
except Exception as e:
    import traceback
    traceback.print_exc()
