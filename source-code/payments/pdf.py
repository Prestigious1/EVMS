import io
from pathlib import Path

from django.conf import settings
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def build_payment_invoice_pdf(*, payment, request=None) -> bytes:
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
    c.drawString(50 * mm, height - 32 * mm, "Payment Invoice / Receipt")

    y = height - 50 * mm
    line = 7 * mm
    c.setFont("Helvetica", 10)

    res = payment.reservation
    c.drawString(20 * mm, y, f"Payment ID: {payment.id}"); y -= line
    c.drawString(20 * mm, y, f"Reservation Ref: {getattr(res, 'booking_reference', '-')}")
    y -= line
    c.drawString(20 * mm, y, f"User: {payment.user}"); y -= line
    c.drawString(20 * mm, y, f"Amount: ₦{payment.amount} {payment.currency}"); y -= line
    c.drawString(20 * mm, y, f"Status: {payment.get_status_display()}"); y -= line
    c.drawString(20 * mm, y, f"Method: {payment.get_payment_method_display()}"); y -= line
    c.drawString(20 * mm, y, f"Provider: {getattr(payment, 'provider', '-')}")
    y -= line
    c.drawString(20 * mm, y, f"Reference: {payment.paystack_reference or payment.transaction_reference or '-'}")
    y -= (line * 2)

    if getattr(payment, "penalty_id", None):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20 * mm, y, "Penalty Payment"); y -= line
        c.setFont("Helvetica", 10)
        pen = payment.penalty
        c.drawString(20 * mm, y, f"Penalty ID: {pen.id}"); y -= line
        c.drawString(20 * mm, y, f"Title: {pen.title[:90]}"); y -= line
        c.drawString(20 * mm, y, f"Description: {pen.description[:90]}"); y -= (line * 2)
    elif getattr(payment, "damage_report_id", None):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20 * mm, y, "Damage Payment"); y -= line
        c.setFont("Helvetica", 10)
        dmg = payment.damage_report
        c.drawString(20 * mm, y, f"Damage ID: {dmg.id}"); y -= line
        c.drawString(20 * mm, y, f"Description: {dmg.description[:90]}"); y -= (line * 2)

    if res:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20 * mm, y, "Reservation Details"); y -= line
        c.setFont("Helvetica", 10)
        if getattr(res, "event_name", None):
            c.drawString(20 * mm, y, f"Event Name: {res.event_name}"); y -= line
        c.drawString(20 * mm, y, f"Hall: {res.hall.name}"); y -= line
        c.drawString(20 * mm, y, f"Date: {res.booking_date}"); y -= line
        c.drawString(20 * mm, y, f"Time: {res.start_time} - {res.end_time}"); y -= line
        c.drawString(20 * mm, y, f"Purpose: {res.get_purpose_display()}"); y -= (line * 2)

        if not getattr(payment, "penalty_id", None) and not getattr(payment, "damage_report_id", None):
            c.setFont("Helvetica-Bold", 10)
            c.drawString(20 * mm, y, "Financial Breakdown"); y -= line
            c.setFont("Helvetica", 10)
            c.drawString(20 * mm, y, f"Original Total: ₦{res.original_total}"); y -= line
            c.drawString(20 * mm, y, f"Discount Value: ₦{res.discount_value}"); y -= line
            c.drawString(20 * mm, y, f"Security Deposit: ₦{res.security_deposit}"); y -= line
            c.drawString(20 * mm, y, f"Total Paid: ₦{payment.amount}"); y -= line

    c.showPage()
    c.save()
    return buf.getvalue()

