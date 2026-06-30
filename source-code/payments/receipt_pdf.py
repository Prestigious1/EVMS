"""
Enterprise Payment Receipt PDF Generator
==========================================
Generates the official LASU Hall Management System payment receipt.
This is the authoritative financial document — not the uploaded file.

Fields per specification:
  University Header, Receipt Number, Booking Reference, Payment Reference,
  Applicant Details, Hall, Event, Payment Date/Time, Original Hall Price,
  Coupon Applied, Discount, Security Deposit, Additional Charges, VAT,
  Amount Paid, Outstanding Balance, Payment Method, Verified Status,
  QR Verification, Digital Verification Hash.
"""
from __future__ import annotations

import hashlib
import io
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import qrcode
from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


# ---------------------------------------------------------------------------
# Receipt Number Generator
# ---------------------------------------------------------------------------

def generate_receipt_number(payment_id: int, booking_reference: str) -> str:
    """Generate a unique, deterministic receipt number."""
    suffix = hashlib.sha256(f"{payment_id}-{booking_reference}".encode()).hexdigest()[:8].upper()
    return f"RCP-{booking_reference[:12]}-{suffix}"


def generate_verification_hash(receipt_number: str, booking_reference: str, amount: Decimal) -> str:
    """Deterministic digital hash for receipt authenticity verification."""
    secret = getattr(settings, "SECRET_KEY", "evms-secret")[:16]
    payload = f"{secret}:{receipt_number}:{booking_reference}:{amount}"
    return hashlib.sha256(payload.encode()).hexdigest().upper()


# ---------------------------------------------------------------------------
# A4 Layout Constants
# ---------------------------------------------------------------------------

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm
CONTENT_W = PAGE_W - 2 * MARGIN
LINE_H = 6.5 * mm
SECTION_H = 5 * mm

# Colour palette (LASU green + gold accent)
LASU_GREEN  = colors.HexColor("#1a5e2f")
LASU_GOLD   = colors.HexColor("#c9a227")
HEADER_BG   = colors.HexColor("#1a5e2f")
ROW_LIGHT   = colors.HexColor("#f3f8f5")
ROW_WHITE   = colors.white
BORDER      = colors.HexColor("#c5d8cb")
TEXT_DARK   = colors.HexColor("#1a1a1a")
TEXT_MUTED  = colors.HexColor("#5a5a5a")
TEXT_WHITE  = colors.white


# ---------------------------------------------------------------------------
# Drawing Helpers
# ---------------------------------------------------------------------------

def _draw_header_band(c: canvas.Canvas, y: float, logo_path: Path) -> float:
    """Draw university header band. Returns y position after header."""
    band_h = 30 * mm
    c.setFillColor(HEADER_BG)
    c.rect(0, y - band_h, PAGE_W, band_h, fill=1, stroke=0)

    # Logo
    if logo_path.exists():
        try:
            c.drawImage(
                str(logo_path),
                MARGIN, y - band_h + 3 * mm,
                width=22 * mm, height=22 * mm,
                mask="auto",
            )
        except Exception:
            pass

    # University name
    c.setFillColor(TEXT_WHITE)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(MARGIN + 26 * mm, y - 10 * mm, "LAGOS STATE UNIVERSITY")
    c.setFont("Helvetica", 9)
    c.drawString(MARGIN + 26 * mm, y - 16 * mm, "Event Hall Management System — Financial Services")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN + 26 * mm, y - 22 * mm, "OFFICIAL PAYMENT RECEIPT")

    # Right-aligned: RECEIPT label
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(PAGE_W - MARGIN, y - 10 * mm, "VERIFIED RECEIPT")

    return y - band_h - 4 * mm


def _draw_kv_row(c: canvas.Canvas, x: float, y: float, w: float, key: str, value: str, *, bg=None, bold_val: bool = False) -> float:
    """Draw a key-value row. Returns y after row."""
    col_w = w * 0.38
    if bg:
        c.setFillColor(bg)
        c.rect(x, y - LINE_H + 1 * mm, w, LINE_H, fill=1, stroke=0)
    c.setFillColor(TEXT_MUTED)
    c.setFont("Helvetica", 8.5)
    c.drawString(x + 2 * mm, y - LINE_H + 3 * mm, key)
    c.setFillColor(TEXT_DARK)
    c.setFont("Helvetica-Bold" if bold_val else "Helvetica", 8.5)
    c.drawString(x + col_w, y - LINE_H + 3 * mm, str(value))
    return y - LINE_H


def _draw_section_header(c: canvas.Canvas, x: float, y: float, w: float, title: str) -> float:
    c.setFillColor(LASU_GREEN)
    c.rect(x, y - SECTION_H, w, SECTION_H, fill=1, stroke=0)
    c.setFillColor(TEXT_WHITE)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x + 2 * mm, y - SECTION_H + 1.5 * mm, title.upper())
    return y - SECTION_H - 1 * mm


def _draw_divider(c: canvas.Canvas, x: float, y: float, w: float) -> float:
    c.setStrokeColor(BORDER)
    c.line(x, y, x + w, y)
    return y - 2 * mm


def _draw_total_row(c: canvas.Canvas, x: float, y: float, w: float, key: str, value: str) -> float:
    """Bold total row with accent background."""
    c.setFillColor(LASU_GREEN)
    c.rect(x, y - LINE_H + 1 * mm, w, LINE_H, fill=1, stroke=0)
    c.setFillColor(TEXT_WHITE)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x + 2 * mm, y - LINE_H + 3 * mm, key)
    c.drawRightString(x + w - 2 * mm, y - LINE_H + 3 * mm, value)
    return y - LINE_H


def _draw_outstanding_row(c: canvas.Canvas, x: float, y: float, w: float, value: str) -> float:
    bg = colors.HexColor("#fff3cd") if value != "₦0.00" else colors.HexColor("#d1fae5")
    c.setFillColor(bg)
    c.rect(x, y - LINE_H + 1 * mm, w, LINE_H, fill=1, stroke=0)
    label_color = colors.HexColor("#92400e") if value != "₦0.00" else colors.HexColor("#065f46")
    c.setFillColor(label_color)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(x + 2 * mm, y - LINE_H + 3 * mm, "Outstanding Balance")
    c.drawRightString(x + w - 2 * mm, y - LINE_H + 3 * mm, value)
    return y - LINE_H


# ---------------------------------------------------------------------------
# Main Builder
# ---------------------------------------------------------------------------

def build_enterprise_receipt_pdf(
    *,
    reservation,
    payment=None,
    payment_proof=None,
    request=None,
) -> bytes:
    """
    Build the official A4 enterprise payment receipt PDF.

    Args:
        reservation: Reservation instance
        payment: Payment instance (most recent successful booking payment)
        payment_proof: PaymentProof instance (most recent verified proof)
        request: Django HttpRequest (optional — for QR URL)

    Returns:
        PDF bytes
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    logo_path = Path(settings.BASE_DIR) / "static" / "images" / "lasu_logo.png"

    # ── Gather financial data ──────────────────────────────────────────────
    auth = getattr(reservation, "payment_authorization", None)
    if auth is None:
        try:
            from reservations.models import PaymentAuthorization
            auth = PaymentAuthorization.objects.filter(reservation=reservation).first()
        except Exception:
            auth = None

    hall_price      = (auth.hall_price      if auth else reservation.total_cost) or Decimal("0")
    coupon_code     = (auth.coupon_code     if auth else reservation.coupon_code) or ""
    coupon_discount = (auth.coupon_discount if auth else reservation.discount_amount_applied) or Decimal("0")
    discount_amount = (auth.discount_amount if auth else reservation.discount_value) or Decimal("0")
    security_deposit = (auth.security_deposit if auth else reservation.security_deposit) or Decimal("0")
    extra_charges   = (auth.extra_charges   if auth else Decimal("0")) or Decimal("0")
    extra_notes     = (auth.extra_charges_notes if auth else "") or ""
    vat_amount      = (auth.vat_amount      if auth else Decimal("0")) or Decimal("0")
    vat_rate        = (auth.vat_rate        if auth else Decimal("0")) or Decimal("0")
    total_amount    = (auth.total_amount    if auth else reservation.total_cost) or Decimal("0")
    outstanding     = (auth.outstanding_balance if auth else Decimal("0")) or Decimal("0")

    # Payment info
    amount_paid     = payment.amount if payment else Decimal("0")
    payment_method  = payment.get_payment_method_display() if payment else "—"
    txn_ref         = (payment.transaction_reference or payment.paystack_reference) if payment else "—"
    payment_date    = payment.created_at if payment else None
    proof_ref       = payment_proof.transaction_ref if payment_proof else txn_ref
    proof_status    = payment_proof.status if payment_proof else ("VERIFIED" if payment else "PENDING")

    # Verified by
    verified_by = "—"
    if payment_proof and payment_proof.verified_by:
        verified_by = payment_proof.verified_by.get_full_name() or payment_proof.verified_by.email
    elif proof_status == "VERIFIED":
        verified_by = "LASU Bursary Unit"

    # IDs
    receipt_no = generate_receipt_number(
        payment_id=payment.id if payment else 0,
        booking_reference=reservation.booking_reference,
    )
    verification_hash = generate_verification_hash(
        receipt_no, reservation.booking_reference, amount_paid
    )

    # Now timestamp
    now = timezone.now()

    # ── Start drawing ──────────────────────────────────────────────────────
    y = PAGE_H - MARGIN

    # 1. Header band
    y = _draw_header_band(c, y, logo_path)
    y -= 3 * mm

    # 2. Receipt meta (two-column)
    left_x = MARGIN
    right_x = PAGE_W / 2 + 5 * mm
    half_w = CONTENT_W / 2 - 5 * mm

    y = _draw_section_header(c, left_x, y, CONTENT_W, "Receipt Information")
    y -= 1 * mm

    meta_rows = [
        ("Receipt Number",     receipt_no),
        ("Booking Reference",  reservation.booking_reference),
        ("Payment Reference",  proof_ref or txn_ref or "—"),
        ("Generated On",       now.strftime("%d %b %Y  %H:%M UTC")),
    ]
    right_meta = [
        ("Payment Date",  payment_date.strftime("%d %b %Y") if payment_date else "—"),
        ("Payment Time",  payment_date.strftime("%H:%M UTC") if payment_date else "—"),
        ("Status",        proof_status),
        ("Verified By",   verified_by),
    ]
    start_y = y
    for i, (k, v) in enumerate(meta_rows):
        bg = ROW_LIGHT if i % 2 == 0 else ROW_WHITE
        y = _draw_kv_row(c, left_x, y, half_w, k, v, bg=bg, bold_val=(k in ("Receipt Number",)))

    y_right = start_y
    for i, (k, v) in enumerate(right_meta):
        bg = ROW_LIGHT if i % 2 == 0 else ROW_WHITE
        y_right = _draw_kv_row(c, right_x, y_right, half_w, k, v, bg=bg)

    y = min(y, y_right) - 4 * mm

    # 3. Applicant & Booking Info (two columns)
    y = _draw_section_header(c, left_x, y, CONTENT_W, "Applicant & Booking Information")
    y -= 1 * mm

    applicant_rows = [
        ("Full Name",    reservation.user.get_full_name() or reservation.user.username),
        ("Email",        reservation.user.email or "—"),
        ("Role",         getattr(reservation.user, "role", "—")),
        ("Department",   getattr(reservation.user, "department", "") or "—"),
    ]
    booking_rows = [
        ("Hall",          reservation.hall.name),
        ("Event",         reservation.event_name or "—"),
        ("Booking Date",  str(reservation.booking_date)),
        ("Time",          f"{reservation.start_time} – {reservation.end_time}"),
    ]
    start_y = y
    for i, (k, v) in enumerate(applicant_rows):
        bg = ROW_LIGHT if i % 2 == 0 else ROW_WHITE
        y = _draw_kv_row(c, left_x, y, half_w, k, v, bg=bg)

    y_right = start_y
    for i, (k, v) in enumerate(booking_rows):
        bg = ROW_LIGHT if i % 2 == 0 else ROW_WHITE
        y_right = _draw_kv_row(c, right_x, y_right, half_w, k, v, bg=bg)

    y = min(y, y_right) - 4 * mm

    # 4. Financial Breakdown
    y = _draw_section_header(c, left_x, y, CONTENT_W, "Financial Breakdown")
    y -= 1 * mm

    fin_rows: list[tuple[str, str, bool]] = [
        ("Original Hall Price",        f"\u20a6{hall_price:,.2f}",         False),
    ]
    if coupon_code and coupon_discount:
        fin_rows.append(("Coupon Applied",  f"{coupon_code}",               False))
        fin_rows.append(("Coupon Discount", f"- \u20a6{coupon_discount:,.2f}", False))
    if discount_amount:
        fin_rows.append(("Additional Discount", f"- \u20a6{discount_amount:,.2f}", False))
    if security_deposit:
        fin_rows.append(("Security Deposit",   f"\u20a6{security_deposit:,.2f}", False))
    if extra_charges:
        label = f"Additional Charges{(' — ' + extra_notes) if extra_notes else ''}"
        fin_rows.append((label, f"\u20a6{extra_charges:,.2f}", False))
    if vat_rate:
        fin_rows.append((f"VAT ({vat_rate}%)", f"\u20a6{vat_amount:,.2f}", False))

    for i, (k, v, bold) in enumerate(fin_rows):
        bg = ROW_LIGHT if i % 2 == 0 else ROW_WHITE
        y = _draw_kv_row(c, left_x, y, CONTENT_W, k, v, bg=bg, bold_val=bold)

    y -= 1 * mm
    y = _draw_total_row(c, left_x, y, CONTENT_W, "TOTAL AMOUNT", f"\u20a6{total_amount:,.2f}")
    y -= 1 * mm
    y = _draw_kv_row(c, left_x, y, CONTENT_W, "Payment Method", payment_method, bg=ROW_LIGHT)
    y = _draw_kv_row(c, left_x, y, CONTENT_W, "Amount Paid",    f"\u20a6{amount_paid:,.2f}", bg=ROW_WHITE, bold_val=True)
    y -= 1 * mm
    y = _draw_outstanding_row(c, left_x, y, CONTENT_W, f"\u20a6{outstanding:,.2f}")
    y -= 4 * mm

    # 5. Verification block + QR code
    # QR code
    verify_url = (
        request.build_absolute_uri(f"/reservations/verify/{reservation.booking_reference}/")
        if request
        else f"LASU:{reservation.booking_reference}:{verification_hash[:16]}"
    )
    qr = qrcode.make(verify_url)
    qr_buf = io.BytesIO()
    qr.save(qr_buf, format="PNG")
    qr_buf.seek(0)

    qr_size = 28 * mm
    qr_x = PAGE_W - MARGIN - qr_size
    qr_y = y - qr_size - 6 * mm

    # Verification text block
    y = _draw_section_header(c, left_x, y, CONTENT_W - qr_size - 6 * mm, "Digital Verification")
    y -= 1 * mm

    verif_rows = [
        ("Digital Hash",  verification_hash[:32] + "..."),
        ("Receipt No",    receipt_no),
        ("QR Scan",       "Scan QR code to verify authenticity"),
    ]
    for i, (k, v) in enumerate(verif_rows):
        bg = ROW_LIGHT if i % 2 == 0 else ROW_WHITE
        y = _draw_kv_row(c, left_x, y, CONTENT_W - qr_size - 8 * mm, k, v, bg=bg)

    # Draw QR
    c.drawImage(ImageReader(qr_buf), qr_x, qr_y, width=qr_size, height=qr_size, mask="auto")
    c.setFont("Helvetica", 6)
    c.setFillColor(TEXT_MUTED)
    c.drawCentredString(qr_x + qr_size / 2, qr_y - 4 * mm, "Scan to verify")

    y = min(y, qr_y) - 6 * mm

    # 6. Footer
    c.setFillColor(HEADER_BG)
    footer_h = 10 * mm
    c.rect(0, MARGIN / 2, PAGE_W, footer_h, fill=1, stroke=0)
    c.setFillColor(TEXT_WHITE)
    c.setFont("Helvetica", 7)
    c.drawCentredString(
        PAGE_W / 2, MARGIN / 2 + 6 * mm,
        "LASU Hall Management System — This receipt is a system-generated official financial document."
    )
    c.drawCentredString(
        PAGE_W / 2, MARGIN / 2 + 2 * mm,
        "For verification contact: hms@lasu.edu.ng | Lagos State University, Ojo, Lagos."
    )

    c.showPage()
    c.save()
    return buf.getvalue()
