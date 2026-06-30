import io
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from payments.models import Payment, PaymentStatus
from reservations.models import Reservation


def build_reports_dashboard_pdf(*, request=None) -> bytes:
    """
    Simple PDF export of reports dashboard numbers.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    logo_path = Path(settings.BASE_DIR) / "static" / "images" / "lasu_logo.png"
    if logo_path.exists():
        c.drawImage(str(logo_path), 20 * mm, height - 35 * mm, width=25 * mm, height=25 * mm, mask="auto")

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50 * mm, height - 25 * mm, "LASU Hall Management System")
    c.setFont("Helvetica", 11)
    c.drawString(50 * mm, height - 32 * mm, "Admin Reports Export")

    today = timezone.localdate()
    start_week = today - timedelta(days=today.weekday())
    start_month = today.replace(day=1)

    qs = Reservation.objects.all()
    paid_payments = Payment.objects.filter(status=PaymentStatus.PAID)

    stats = [
        ("Daily bookings", qs.filter(booking_date=today).count()),
        ("Weekly bookings", qs.filter(booking_date__gte=start_week, booking_date__lte=today).count()),
        ("Monthly bookings", qs.filter(booking_date__gte=start_month, booking_date__lte=today).count()),
        ("Yearly bookings", qs.filter(booking_date__year=today.year).count()),
        ("Total revenue (paid)", paid_payments.aggregate(total=Sum("amount"))["total"] or 0),
    ]

    y = height - 55 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, f"Generated: {timezone.localtime().strftime('%Y-%m-%d %H:%M')}"); y -= 10 * mm

    c.setFont("Helvetica", 10)
    for k, v in stats:
        c.drawString(20 * mm, y, f"{k}: {v}")
        y -= 7 * mm

    y -= 5 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Peak booking hours (top 5):"); y -= 7 * mm

    peak_hours = (
        qs.values("start_time__hour")
        .annotate(total=Count("id"))
        .order_by("-total")[:5]
    )
    c.setFont("Helvetica", 10)
    for row in peak_hours:
        label = str(row["start_time__hour"]).zfill(2) + ":00"
        c.drawString(25 * mm, y, f"{label} — {row['total']} bookings")
        y -= 7 * mm

    c.showPage()
    c.save()
    return buf.getvalue()

