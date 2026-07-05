import sys
import io

with open('payments/receipt_pdf.py', 'a', encoding='utf-8') as f:
    f.write('''

def build_liability_receipt_pdf(
    *,
    liability,
    liability_type: str,
    payment=None,
    payment_proof=None,
    request=None,
) -> bytes:
    """
    Build the official A4 enterprise payment receipt PDF for a Penalty or Damage.

    Args:
        liability: Penalty or DamageReport instance
        liability_type: 'PENALTY' or 'DAMAGE'
        payment: Payment instance (optional)
        payment_proof: PaymentProof instance (optional)
        request: Django HttpRequest (optional)

    Returns:
        PDF bytes
    """
    import io
    from pathlib import Path
    import qrcode
    from decimal import Decimal
    from django.conf import settings
    from django.utils import timezone
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.lib import colors

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    logo_path = Path(settings.BASE_DIR) / "static" / "images" / "lasu_logo.png"

    reservation = liability.reservation

    # ── Gather financial data ──────────────────────────────────────────────
    total_amount    = liability.amount or Decimal("0")
    
    # Payment info
    amount_paid     = payment.amount if payment else (total_amount if liability.is_paid else Decimal("0"))
    payment_method  = payment.get_payment_method_display() if payment else "—"
    txn_ref         = (payment.transaction_reference or payment.paystack_reference) if payment else "—"
    payment_date    = payment.created_at if payment else (payment_proof.uploaded_at if payment_proof else None)
    proof_ref       = payment_proof.transaction_ref if payment_proof else txn_ref
    proof_status    = payment_proof.status if payment_proof else ("VERIFIED" if liability.is_paid else "PENDING")

    # Verified by
    verified_by = "—"
    if payment_proof and payment_proof.verified_by:
        verified_by = payment_proof.verified_by.get_full_name() or payment_proof.verified_by.email
    elif proof_status == "VERIFIED":
        verified_by = "LASU Bursary Unit"

    # IDs
    receipt_no = generate_receipt_number(
        payment_id=payment.id if payment else liability.id,
        booking_reference=f"{liability_type[:3]}-{reservation.booking_reference if reservation else 'N/A'}",
    )
    verification_hash = generate_verification_hash(
        receipt_no, reservation.booking_reference if reservation else "N/A", amount_paid
    )

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
        ("Liability Type",     "Damage Payment" if liability_type == "DAMAGE" else "Penalty Payment"),
        ("Booking Reference",  reservation.booking_reference if reservation else "—"),
        ("Payment Reference",  proof_ref or txn_ref or "—"),
    ]
    right_meta = [
        ("Generated On",  now.strftime("%d %b %Y  %H:%M UTC")),
        ("Payment Date",  payment_date.strftime("%d %b %Y") if payment_date else "—"),
        ("Status",        "PAID" if liability.is_paid else proof_status),
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

    user = liability.user
    applicant_rows = [
        ("Full Name",    user.get_full_name() or user.username),
        ("Email",        user.email or "—"),
        ("Role",         getattr(user, "role", "—")),
        ("Department",   getattr(user, "department", "") or "—"),
    ]
    if reservation:
        booking_rows = [
            ("Hall",          reservation.hall.name),
            ("Event",         reservation.event_name or "—"),
            ("Booking Date",  str(reservation.booking_date)),
            ("Time",          f"{reservation.start_time} – {reservation.end_time}"),
        ]
    else:
        booking_rows = [("Hall", "—"), ("Event", "—"), ("Date", "—"), ("Time", "—")]

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
    
    desc_title = liability.title if liability_type == "PENALTY" else "Damage Report"
    desc_text = getattr(liability, "description", "")
    if desc_text:
        desc_title += f" ({desc_text[:30]}{'...' if len(desc_text)>30 else ''})"

    fin_rows = [
        (desc_title, f"\\u20a6{total_amount:,.2f}", False),
    ]

    for i, (k, v, bold) in enumerate(fin_rows):
        bg = ROW_LIGHT if i % 2 == 0 else ROW_WHITE
        y = _draw_kv_row(c, left_x, y, CONTENT_W, k, v, bg=bg, bold_val=bold)

    y -= 1 * mm
    y = _draw_total_row(c, left_x, y, CONTENT_W, "TOTAL AMOUNT", f"\\u20a6{total_amount:,.2f}")
    y -= 1 * mm
    y = _draw_kv_row(c, left_x, y, CONTENT_W, "Payment Method", payment_method, bg=ROW_LIGHT)
    y = _draw_kv_row(c, left_x, y, CONTENT_W, "Amount Paid",    f"\\u20a6{amount_paid:,.2f}", bg=ROW_WHITE, bold_val=True)
    y -= 1 * mm
    outstanding = total_amount - amount_paid
    if outstanding < 0: outstanding = Decimal("0")
    y = _draw_outstanding_row(c, left_x, y, CONTENT_W, f"\\u20a6{outstanding:,.2f}")
    y -= 4 * mm

    # 5. Verification block + QR code
    # QR code
    verify_url = (
        request.build_absolute_uri(f"/reservations/verify/{reservation.booking_reference}/")
        if request and reservation
        else f"LASU:{reservation.booking_reference if reservation else 'N/A'}:{verification_hash[:16]}"
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
''')
