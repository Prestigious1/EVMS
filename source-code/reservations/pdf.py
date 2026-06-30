import io
from pathlib import Path

import qrcode
from django.conf import settings
from reportlab.lib.utils import ImageReader
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def build_reservation_receipt_pdf(*, reservation, request=None) -> bytes:
    """
    Generate a simple PDF receipt with LASU logo + QR code.
    Requires `reportlab` installed.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    # Logo
    logo_path = Path(settings.BASE_DIR) / "static" / "images" / "lasu_logo.png"
    if logo_path.exists():
        c.drawImage(str(logo_path), 20 * mm, height - 35 * mm, width=25 * mm, height=25 * mm, mask="auto")

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50 * mm, height - 25 * mm, "LASU Hall Management System")
    c.setFont("Helvetica", 11)
    c.drawString(50 * mm, height - 32 * mm, "Reservation Receipt")

    y = height - 50 * mm
    line = 7 * mm
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, f"Reference: {reservation.booking_reference}"); y -= line
    c.drawString(20 * mm, y, f"Hall: {reservation.hall.name}"); y -= line
    c.drawString(20 * mm, y, f"Date: {reservation.booking_date}"); y -= line
    c.drawString(20 * mm, y, f"Time: {reservation.start_time} - {reservation.end_time}"); y -= line
    c.drawString(20 * mm, y, f"Purpose: {reservation.get_purpose_display()}"); y -= line
    c.drawString(20 * mm, y, f"Status: {reservation.get_status_display()}"); y -= line
    c.drawString(20 * mm, y, f"Total Cost: ₦{reservation.total_cost}"); y -= (line * 2)

    # QR code (verification URL)
    if request:
        verify_url = request.build_absolute_uri(f"/reservations/verify/{reservation.booking_reference}/")
    else:
        verify_url = f"LASU:{reservation.booking_reference}"
    qr = qrcode.make(verify_url)
    qr_buf = io.BytesIO()
    qr.save(qr_buf, format="PNG")
    qr_buf.seek(0)
    c.drawImage(ImageReader(qr_buf), width - 55 * mm, height - 60 * mm, width=35 * mm, height=35 * mm, mask="auto")
    c.setFont("Helvetica", 8)
    c.drawString(width - 55 * mm, height - 62 * mm, "Scan to verify")

    c.showPage()
    c.save()
    return buf.getvalue()


def build_booking_permit_pdf(*, reservation, request=None) -> bytes:
    """
    Generate a formal PDF booking permit with LASU logo + QR code.
    Requires `reportlab` installed.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    # Logo
    logo_path = Path(settings.BASE_DIR) / "static" / "images" / "lasu_logo.png"
    if logo_path.exists():
        c.drawImage(str(logo_path), 20 * mm, height - 35 * mm, width=25 * mm, height=25 * mm, mask="auto")

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50 * mm, height - 25 * mm, "LASU Hall Management System")
    c.setFont("Helvetica", 11)
    c.drawString(50 * mm, height - 32 * mm, "Booking Permit")

    y = height - 50 * mm
    line = 7 * mm
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, f"Reference: {reservation.booking_reference}"); y -= line
    c.drawString(20 * mm, y, f"Applicant: {reservation.user.get_full_name() or reservation.user.email}"); y -= line
    if getattr(reservation, "event_name", None):
        c.drawString(20 * mm, y, f"Event Name: {reservation.event_name}"); y -= line
    c.drawString(20 * mm, y, f"Hall: {reservation.hall.name}"); y -= line
    c.drawString(20 * mm, y, f"Date: {reservation.booking_date}"); y -= line
    c.drawString(20 * mm, y, f"Time: {reservation.start_time} - {reservation.end_time}"); y -= line
    c.drawString(20 * mm, y, f"Purpose: {reservation.get_purpose_display()}"); y -= (line * 2)

    c.setFont("Helvetica-Bold", 12)
    c.drawString(20 * mm, y, "AUTHORISED ENTRY"); y -= line
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, "This document serves as the official permit for the event described above."); y -= line
    c.drawString(20 * mm, y, "Please present this permit to the Facility Management or Security upon request."); y -= (line * 2)

    # QR code (verification URL)
    if request:
        verify_url = request.build_absolute_uri(f"/reservations/verify/{reservation.booking_reference}/")
    else:
        verify_url = f"LASU:{reservation.booking_reference}:{reservation.qr_verification_code}"
    qr = qrcode.make(verify_url)
    qr_buf = io.BytesIO()
    qr.save(qr_buf, format="PNG")
    qr_buf.seek(0)
    c.drawImage(ImageReader(qr_buf), width - 55 * mm, height - 60 * mm, width=35 * mm, height=35 * mm, mask="auto")
    c.setFont("Helvetica", 8)
    c.drawString(width - 55 * mm, height - 62 * mm, "Scan to verify validity")

    c.showPage()
    c.save()
    return buf.getvalue()
