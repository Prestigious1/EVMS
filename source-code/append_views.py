import sys

with open('payments/views.py', 'a', encoding='utf-8') as f:
    f.write('''

@login_required
def damage_receipt_pdf(request, damage_id: int):
    """
    Generate and download the official A4 receipt for a Damage Payment.
    """
    from reservations.models import DamageReport
    from payments.models import PaymentStatus
    from payments.receipt_pdf import build_liability_receipt_pdf

    damage = get_object_or_404(DamageReport.objects.select_related("user", "reservation"), pk=damage_id)
    
    is_staff_viewer = (
        can_view_all(request.user)
        or getattr(request.user, "role", None) in ("VENTURES", "BURSARY", "ADMIN", "STAFF")
    )
    if not is_staff_viewer and damage.user != request.user:
        messages.error(request, "Access denied.")
        return redirect("reservations:my_reservations")
        
    if not damage.is_paid:
        messages.error(request, "Receipt is only available after payment is confirmed.")
        return redirect("reservations:detail", booking_reference=damage.reservation.booking_reference if damage.reservation else "home")

    payment = (
        Payment.objects.filter(damage_report=damage, status=PaymentStatus.PAID)
        .order_by("-created_at")
        .first()
    )
    proof = (
        PaymentProof.objects.filter(reservation=damage.reservation, payment_type="DAMAGE")
        .order_by("-uploaded_at")
        .first()
    )

    pdf_bytes = build_liability_receipt_pdf(
        liability=damage,
        liability_type="DAMAGE",
        payment=payment,
        payment_proof=proof,
        request=request,
    )
    filename = f"LASU_Damage_Receipt_{damage_id}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    create_audit_log(
        user=request.user,
        action=f"damage_receipt_downloaded:{damage_id}",
        model_name="DamageReport",
    )
    return response


@login_required
def penalty_receipt_pdf(request, penalty_id: int):
    """
    Generate and download the official A4 receipt for a Penalty Payment.
    """
    from reservations.models import Penalty
    from payments.models import PaymentStatus
    from payments.receipt_pdf import build_liability_receipt_pdf

    penalty = get_object_or_404(Penalty.objects.select_related("user", "reservation"), pk=penalty_id)
    
    is_staff_viewer = (
        can_view_all(request.user)
        or getattr(request.user, "role", None) in ("VENTURES", "BURSARY", "ADMIN", "STAFF")
    )
    if not is_staff_viewer and penalty.user != request.user:
        messages.error(request, "Access denied.")
        return redirect("reservations:my_reservations")
        
    if not penalty.is_paid:
        messages.error(request, "Receipt is only available after payment is confirmed.")
        return redirect("reservations:detail", booking_reference=penalty.reservation.booking_reference if penalty.reservation else "home")

    payment = (
        Payment.objects.filter(penalty=penalty, status=PaymentStatus.PAID)
        .order_by("-created_at")
        .first()
    )
    proof = (
        PaymentProof.objects.filter(reservation=penalty.reservation, payment_type="PENALTY")
        .order_by("-uploaded_at")
        .first()
    )

    pdf_bytes = build_liability_receipt_pdf(
        liability=penalty,
        liability_type="PENALTY",
        payment=payment,
        payment_proof=proof,
        request=request,
    )
    filename = f"LASU_Penalty_Receipt_{penalty_id}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    create_audit_log(
        user=request.user,
        action=f"penalty_receipt_downloaded:{penalty_id}",
        model_name="Penalty",
    )
    return response

''')
