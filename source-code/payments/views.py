from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from urllib.parse import quote

from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from core.services import create_audit_log, notify_and_email, can_view_all
from payments.models import Payment, PaymentMethod, PaymentProvider, PaymentStatus
from payments.paystack import PaystackError, initialize_transaction, verify_transaction
from payments.paystack_utils import (
    amount_kobo_matches_payment,
    get_paystack_verify_callback_url,
    naira_to_kobo,
    paystack_secret_configured,
    sign_checkout_token,
    sign_failure_token,
    unsign_checkout_token,
    unsign_failure_token,
)
from payments.pdf import build_payment_invoice_pdf
from reservations.models import DamageReport, Penalty, Reservation, ReservationStatus
from reservations.services import WorkflowService



def _new_reference(prefix: str = "PS") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def _payment_confirmation_message(payment: Payment) -> str:
    head = f"Payment received: ₦{payment.amount} (reference {payment.paystack_reference}).\n"
    r = payment.reservation
    if r and not payment.damage_report_id and not payment.penalty_id:
        return head + (
            f"Booking reference: {r.booking_reference}\n"
            f"Hall: {r.hall.name}\n"
            f"Date: {r.booking_date} {r.start_time}–{r.end_time}\n"
            "Download your receipt from the portal under My reservations or Payments."
        )
    if payment.penalty_id or payment.damage_report_id:
        return head + "This payment was recorded against a penalty or damage balance on your account.\n"
    if r:
        return head + f"Related booking reference: {r.booking_reference}\n"
    return head


def _finalize_paystack_payment(*, payment: Payment, verification_payload: dict | None, audit_user) -> None:
    if payment.status == PaymentStatus.PAID:
        return
        
    transaction_reference = (
        (verification_payload or {}).get("reference")
        or payment.paystack_reference
    )
    
    metadata = {**(payment.metadata or {}), "paystack_verify": verification_payload} if verification_payload else payment.metadata
    
    from payments.services import PaymentResolutionService
    from payments.models import PaymentProofType
    
    is_damage = bool(payment.damage_report_id)
    payment_type = PaymentProofType.DAMAGE if is_damage else PaymentProofType.BOOKING
    
    PaymentResolutionService.finalize_payment(
        reservation=payment.reservation,
        amount=payment.amount,
        method=payment.payment_method,
        transaction_reference=transaction_reference,
        actor=audit_user,
        provider=payment.provider,
        payment_type=payment_type,
        metadata=metadata,
        existing_payment=payment
    )

    if payment.damage_report_id:
        DamageReport.objects.filter(id=payment.damage_report_id).update(is_paid=True)
    if payment.penalty_id:
        Penalty.objects.filter(id=payment.penalty_id).update(is_paid=True)

    notify_and_email(
        user=payment.user,
        title="LASU Hall — payment confirmed",
        message=_payment_confirmation_message(payment),
    )


def _mark_payment_failed(*, payment: Payment, reason: str, payload: dict | None = None) -> None:
    if payment.status == PaymentStatus.PAID:
        return
    payment.status = PaymentStatus.FAILED
    meta = {**(payment.metadata or {}), "failure_reason": reason}
    if payload is not None:
        meta["paystack_verify"] = payload
    payment.metadata = meta
    payment.save(update_fields=["status", "metadata"])


@login_required
def my_payments(request):
    qs = Payment.objects.select_related("reservation", "user", "damage_report", "penalty")
    
    can_view_master = can_view_all(request.user) or getattr(request.user, "role", None) == "VENTURES"
    mode = request.GET.get("mode", "personal")
    
    if mode == "master" and can_view_master:
        pass  # keep all payments in qs
    else:
        qs = qs.filter(user=request.user)
        mode = "personal"

    q = request.GET.get("q", "").strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(
            Q(paystack_reference__icontains=q) | 
            Q(transaction_reference__icontains=q) | 
            Q(reservation__booking_reference__icontains=q) | 
            Q(user__email__icontains=q)
        )

    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)

    sort = request.GET.get("sort", "-created_at")
    if sort in ["created_at", "-created_at", "amount", "-amount"]:
        qs = qs.order_by(sort)
    else:
        qs = qs.order_by("-created_at")

    context = {
        "payments": qs,
        "mode": mode,
        "can_view_master": can_view_master,
        "q": q,
        "status": status,
        "sort": sort,
        "PaymentStatus": PaymentStatus,
    }
    return render(request, "payments/my_payments.html", context)


@login_required
def payment_detail(request, pk: int):
    payment = get_object_or_404(Payment.objects.select_related("reservation", "user", "damage_report", "penalty"), pk=pk)
    if not can_view_all(request.user) and payment.user != request.user:
        return HttpResponse(status=403)
    return render(request, "payments/payment_detail.html", {"payment": payment})


@login_required
def start_reservation_payment(request, booking_reference: str):
    reservation = get_object_or_404(
        Reservation.objects.select_related("hall", "user"),
        booking_reference=booking_reference,
    )
    if not can_view_all(request.user) and reservation.user != request.user:
        return HttpResponse(status=403)

    if reservation.status in [ReservationStatus.REJECTED, ReservationStatus.CANCELLED]:
        messages.error(request, "This reservation cannot be paid.")
        return redirect("reservations:my_reservations")

    if reservation.status not in [
        ReservationStatus.PENDING,
        ReservationStatus.PAYMENT_PENDING,
        ReservationStatus.APPROVED_PAYMENT,
    ]:
        messages.info(request, "No payment is required for this reservation in its current state.")
        return redirect("reservations:my_reservations")

    amount = reservation.total_cost or Decimal("0.00")
    if amount <= 0:
        messages.error(request, "This reservation has no payable amount.")
        return redirect("reservations:my_reservations")

    payment = (
        Payment.objects.filter(
            reservation=reservation,
            user=reservation.user,
            status=PaymentStatus.PENDING,
            damage_report__isnull=True,
            penalty__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )
    if payment and payment.amount != amount:
        _mark_payment_failed(payment=payment, reason="Superseded: reservation total changed")
        payment = None

    if payment is None:
        payment = Payment.objects.create(
            user=reservation.user,
            reservation=reservation,
            amount=amount,
            status=PaymentStatus.PENDING,
            payment_method=PaymentMethod.CARD,
            paystack_reference=_new_reference("LASU_RES"),
            transaction_reference="",
            metadata={
                "kind": "reservation",
                "amount_kobo": naira_to_kobo(amount),
                "reservation_reference": reservation.booking_reference,
            },
        )
        create_audit_log(user=request.user, action=f"payment_init:{payment.paystack_reference}", model_name="Payment")

    callback_url = get_paystack_verify_callback_url(request=request)

    if not (payment.metadata or {}).get("authorization_url") or (payment.metadata or {}).get("paystack_init_error"):
        if (payment.metadata or {}).get("paystack_init_error"):
            # If the last initialization failed (e.g. Duplicate Transaction Reference),
            # rotate the reference so we don't get stuck in a retry loop.
            payment.paystack_reference = _new_reference("LASU_RES")
            payment.save(update_fields=["paystack_reference"])
        try:
            init = initialize_transaction(
                email=payment.user.email or "no-reply@example.com",
                amount_kobo=naira_to_kobo(payment.amount),
                reference=payment.paystack_reference,
                callback_url=callback_url,
                metadata=payment.metadata,
            )
            payment.paystack_access_code = init.access_code
            payment.metadata = {
                **(payment.metadata or {}),
                "authorization_url": init.authorization_url,
            }
            payment.metadata.pop("paystack_init_error", None)
            payment.save(update_fields=["paystack_access_code", "metadata"])
        except PaystackError as e:
            payment.metadata = {**(payment.metadata or {}), "paystack_init_error": str(e)}
            payment.save(update_fields=["metadata"])

    return render(
        request,
        "payments/start_payment.html",
        {
            "payment": payment,
            "reservation": reservation,
            "callback_url": callback_url,
            "authorization_url": (payment.metadata or {}).get("authorization_url") or "",
            "amount_kobo": naira_to_kobo(payment.amount),
            "paystack_public_key": getattr(settings, "PAYSTACK_PUBLIC_KEY", "") or "",
            "paystack_configured": paystack_secret_configured(),
            "debug": settings.DEBUG,
        },
    )


@login_required
def start_damage_payment(request, damage_id: int):
    damage = get_object_or_404(DamageReport.objects.select_related("user", "reservation"), pk=damage_id)
    if not can_view_all(request.user) and damage.user != request.user:
        return HttpResponse(status=403)

    if damage.is_paid or damage.is_forgiven:
        messages.info(request, "This penalty has already been settled.")
        return redirect("reservations:my_reservations")

    amount = damage.amount or Decimal("0.00")
    paid_amount = sum(p.amount for p in Payment.objects.filter(damage_report=damage, status=PaymentStatus.PAID))
    outstanding = max(Decimal("0.00"), amount - paid_amount)
    
    if outstanding <= 0:
        messages.error(request, "This penalty has no payable amount remaining.")
        return redirect("reservations:my_reservations")
        
    amount = outstanding

    payment = Payment.objects.create(
        user=damage.user,
        reservation=damage.reservation,
        damage_report=damage,
        amount=amount,
        status=PaymentStatus.PENDING,
        payment_method=PaymentMethod.CARD,
        paystack_reference=_new_reference("LASU_DMG"),
        transaction_reference="",
        metadata={
            "kind": "penalty_legacy_damage",
            "amount_kobo": naira_to_kobo(amount),
            "damage_id": damage.id,
        },
    )
    create_audit_log(user=request.user, action=f"penalty_payment_init_legacy:{payment.paystack_reference}", model_name="Payment")

    callback_url = get_paystack_verify_callback_url(request=request)

    try:
        init = initialize_transaction(
            email=payment.user.email or "no-reply@example.com",
            amount_kobo=naira_to_kobo(payment.amount),
            reference=payment.paystack_reference,
            callback_url=callback_url,
            metadata=payment.metadata,
        )
        payment.paystack_access_code = init.access_code
        payment.metadata = {**(payment.metadata or {}), "authorization_url": init.authorization_url}
        payment.save(update_fields=["paystack_access_code", "metadata"])
    except PaystackError as e:
        payment.metadata = {**(payment.metadata or {}), "paystack_init_error": str(e)}
        payment.save(update_fields=["metadata"])

    return render(
        request,
        "payments/start_payment.html",
        {
            "payment": payment,
            "reservation": payment.reservation,
            "callback_url": callback_url,
            "authorization_url": (payment.metadata or {}).get("authorization_url") or "",
            "amount_kobo": naira_to_kobo(payment.amount),
            "paystack_public_key": getattr(settings, "PAYSTACK_PUBLIC_KEY", "") or "",
            "paystack_configured": paystack_secret_configured(),
            "debug": settings.DEBUG,
        },
    )


@login_required
def start_penalty_payment(request, penalty_id: int):
    penalty = get_object_or_404(Penalty.objects.select_related("user", "reservation"), pk=penalty_id)
    if not can_view_all(request.user) and penalty.user != request.user:
        return HttpResponse(status=403)

    if penalty.is_paid or penalty.is_forgiven:
        messages.info(request, "This penalty has already been settled.")
        return redirect("reservations:my_reservations")

    amount = penalty.amount or Decimal("0.00")
    paid_amount = sum(p.amount for p in Payment.objects.filter(penalty=penalty, status=PaymentStatus.PAID))
    outstanding = max(Decimal("0.00"), amount - paid_amount)
    
    if outstanding <= 0:
        messages.error(request, "This penalty has no payable amount remaining.")
        return redirect("reservations:my_reservations")
        
    amount = outstanding

    payment = Payment.objects.create(
        user=penalty.user,
        reservation=penalty.reservation,
        penalty=penalty,
        amount=amount,
        status=PaymentStatus.PENDING,
        payment_method=PaymentMethod.CARD,
        paystack_reference=_new_reference("LASU_PEN"),
        transaction_reference="",
        metadata={
            "kind": "penalty",
            "amount_kobo": naira_to_kobo(amount),
            "penalty_id": penalty.id,
        },
    )
    create_audit_log(user=request.user, action=f"penalty_payment_init:{payment.paystack_reference}", model_name="Payment")

    callback_url = get_paystack_verify_callback_url(request=request)
    try:
        init = initialize_transaction(
            email=payment.user.email or "no-reply@example.com",
            amount_kobo=naira_to_kobo(payment.amount),
            reference=payment.paystack_reference,
            callback_url=callback_url,
            metadata=payment.metadata,
        )
        payment.paystack_access_code = init.access_code
        payment.metadata = {**(payment.metadata or {}), "authorization_url": init.authorization_url}
        payment.save(update_fields=["paystack_access_code", "metadata"])
    except PaystackError as e:
        payment.metadata = {**(payment.metadata or {}), "paystack_init_error": str(e)}
        payment.save(update_fields=["metadata"])

    return render(
        request,
        "payments/start_payment.html",
        {
            "payment": payment,
            "reservation": payment.reservation,
            "callback_url": callback_url,
            "authorization_url": (payment.metadata or {}).get("authorization_url") or "",
            "amount_kobo": naira_to_kobo(payment.amount),
            "paystack_public_key": getattr(settings, "PAYSTACK_PUBLIC_KEY", "") or "",
            "paystack_configured": paystack_secret_configured(),
            "debug": settings.DEBUG,
        },
    )


def _redirect_payment_failed(*, payment: Payment, reference: str, reason: str) -> HttpResponseRedirect:
    tok = sign_failure_token(payment_id=payment.id, reference=reference, reason=reason)
    url = reverse("payments:payment_failed") + "?t=" + quote(tok, safe="")
    return HttpResponseRedirect(url)


@require_GET
def paystack_verify_redirect(request):
    """
    Paystack `callback_url` target: verify server-side, then redirect to /payments/success/ or /payments/failed/.
    """
    reference = (request.GET.get("reference") or "").strip()
    if not reference:
        return HttpResponseRedirect(reverse("payments:payment_failed") + "?e=missing_reference")

    payment = get_object_or_404(
        Payment.objects.select_related("reservation", "reservation__hall", "user"),
        paystack_reference=reference,
    )

    verification_payload: dict | None = None
    verified_paid = False
    secret_ok = paystack_secret_configured()

    if secret_ok:
        try:
            verification_payload = verify_transaction(reference=reference)
        except PaystackError as e:
            _mark_payment_failed(payment=payment, reason=str(e), payload={"error": str(e)})
            return _redirect_payment_failed(payment=payment, reference=reference, reason=str(e))

        st = (verification_payload.get("status") or "").lower()
        if st == "success" and amount_kobo_matches_payment(verify_data=verification_payload, payment=payment):
            verified_paid = True
        elif st == "success":
            _mark_payment_failed(
                payment=payment,
                reason="Paystack amount mismatch",
                payload=verification_payload,
            )
            return _redirect_payment_failed(
                payment=payment,
                reference=reference,
                reason="Charged amount did not match this booking.",
            )
        else:
            _mark_payment_failed(
                payment=payment,
                reason=f"Paystack status: {verification_payload.get('status')!r}",
                payload=verification_payload,
            )
            return _redirect_payment_failed(
                payment=payment,
                reference=reference,
                reason="Payment was not completed successfully.",
            )
    else:
        if settings.DEBUG and request.GET.get("success") == "1":
            verification_payload = {
                "status": "success",
                "amount": naira_to_kobo(payment.amount),
                "reference": reference,
            }
            verified_paid = True
        else:
            return _redirect_payment_failed(
                payment=payment,
                reference=reference,
                reason="Paystack is not configured; cannot verify payment.",
            )

    if verified_paid:
        audit_user = payment.user if not getattr(request.user, "is_authenticated", False) else request.user
        _finalize_paystack_payment(payment=payment, verification_payload=verification_payload, audit_user=audit_user)
        tok = sign_checkout_token(payment.id)
        return HttpResponseRedirect(reverse("payments:payment_success") + "?token=" + quote(tok, safe=""))

    return _redirect_payment_failed(
        payment=payment,
        reference=reference,
        reason="Payment verification did not complete.",
    )


@require_GET
def paystack_callback(request):
    """Legacy Paystack callback path: forwards to /payments/verify/ with the same query string."""
    target = get_paystack_verify_callback_url(request=request)
    q = request.GET.urlencode()
    if q:
        sep = "&" if "?" in target else "?"
        return HttpResponseRedirect(f"{target}{sep}{q}")
    return HttpResponseRedirect(target)


@require_GET
def payment_success(request):
    token = (request.GET.get("token") or "").strip()
    pid = unsign_checkout_token(token)
    if pid is None:
        messages.warning(request, "Invalid or expired payment confirmation link.")
        return redirect("hall:home")
    payment = get_object_or_404(
        Payment.objects.select_related("reservation", "reservation__hall", "user"),
        pk=pid,
    )
    return render(request, "payments/payment_success.html", {"payment": payment})


@require_GET
def payment_failed(request):
    reason = "Payment could not be completed."
    payment = None
    t = (request.GET.get("t") or "").strip()
    if t:
        unpacked = unsign_failure_token(t)
        if unpacked:
            pid, _ref, reason = unpacked
            payment = (
                Payment.objects.select_related("reservation", "reservation__hall", "user")
                .filter(pk=pid)
                .first()
            )
    elif request.GET.get("e") == "missing_reference":
        reason = "Missing payment reference from Paystack."
    return render(request, "payments/payment_failed.html", {"payment": payment, "reason": reason})


@login_required
def invoice_pdf(request, pk: int):
    payment = get_object_or_404(Payment.objects.select_related("reservation", "user", "damage_report", "penalty"), pk=pk)
    if not can_view_all(request.user) and payment.user != request.user:
        return HttpResponse(status=403)
    pdf_bytes = build_payment_invoice_pdf(payment=payment, request=request)
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="invoice_{payment.id}.pdf"'
    return resp


@login_required
def paystack_initialize_reservation(request, reservation_id: int):
    """
    Initialize Paystack transaction for a reservation.
    Returns JSON: {authorization_url, reference, access_code, payment_id}
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    reservation = get_object_or_404(Reservation.objects.select_related("hall", "user"), pk=reservation_id)
    if not can_view_all(request.user) and reservation.user != request.user:
        return JsonResponse({"detail": "Forbidden"}, status=403)

    amount = reservation.total_cost or Decimal("0.00")
    if amount <= 0:
        return JsonResponse({"detail": "Reservation has no payable amount."}, status=400)

    # Reuse an existing pending payment if present
    payment = (
        Payment.objects.filter(reservation=reservation, user=reservation.user, status=PaymentStatus.PENDING)
        .order_by("-created_at")
        .first()
    )
    if payment is None:
        payment = Payment.objects.create(
            user=reservation.user,
            reservation=reservation,
            amount=amount,
            status=PaymentStatus.PENDING,
            payment_method=PaymentMethod.CARD,
            paystack_reference=_new_reference("LASU_RES"),
            transaction_reference="",
            metadata={
                "kind": "reservation",
                "amount_kobo": naira_to_kobo(amount),
                "reservation_id": reservation.id,
                "reservation_reference": reservation.booking_reference,
            },
        )
        create_audit_log(user=request.user, action=f"payment_init_api:{payment.paystack_reference}", model_name="Payment")

    callback_url = get_paystack_verify_callback_url(request=request)
    try:
        init = initialize_transaction(
            email=payment.user.email or "no-reply@example.com",
            amount_kobo=naira_to_kobo(payment.amount),
            reference=payment.paystack_reference,
            callback_url=callback_url,
            metadata=payment.metadata,
        )
    except PaystackError as e:
        payment.metadata = {**(payment.metadata or {}), "paystack_init_error": str(e)}
        payment.save(update_fields=["metadata"])
        return JsonResponse({"detail": str(e)}, status=400)

    payment.paystack_access_code = init.access_code
    payment.metadata = {**(payment.metadata or {}), "authorization_url": init.authorization_url}
    payment.save(update_fields=["paystack_access_code", "metadata"])

    return JsonResponse(
        {
            "payment_id": payment.id,
            "authorization_url": init.authorization_url,
            "reference": init.reference,
            "access_code": init.access_code,
        }
    )


@login_required
def paystack_verify(request):
    """
    Verify a Paystack transaction by reference.
    POST JSON or form: reference=...
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    reference = (request.POST.get("reference") or "").strip()
    if not reference and request.headers.get("Content-Type", "").startswith("application/json"):
        try:
            import json

            body = json.loads(request.body.decode("utf-8") or "{}")
            reference = (body.get("reference") or "").strip()
        except Exception:
            reference = ""

    if not reference:
        return JsonResponse({"detail": "reference is required"}, status=400)

    payment = get_object_or_404(Payment.objects.select_related("reservation", "user", "damage_report", "penalty"), paystack_reference=reference)
    if not can_view_all(request.user) and payment.user != request.user:
        return JsonResponse({"detail": "Forbidden"}, status=403)

    try:
        data = verify_transaction(reference=reference)
    except PaystackError as e:
        return JsonResponse({"detail": str(e)}, status=400)

    if (data.get("status") or "").lower() != "success":
        return JsonResponse({"detail": "Payment not successful", "paystack": data}, status=400)

    if not amount_kobo_matches_payment(verify_data=data, payment=payment):
        return JsonResponse({"detail": "Paystack amount does not match this payment record."}, status=400)

    if payment.status != PaymentStatus.PAID:
        _finalize_paystack_payment(
            payment=payment,
            verification_payload=data,
            audit_user=request.user,
        )

    return JsonResponse(
        {
            "paid": payment.status == PaymentStatus.PAID,
            "payment_id": payment.id,
            "reservation_id": payment.reservation_id,
            "reservation_status": getattr(payment.reservation, "status", None),
            "reference": payment.paystack_reference,
        }
    )


@login_required
def record_manual_payment(request):
    """
    Record a manual payment (bank transfer, internal) on behalf of an applicant.
    All manual payments now go through PaymentResolutionService so they enter
    the Bursary verification queue — no direct PAYMENT_VERIFIED jumps.
    """
    if not getattr(request.user, "role", None) in ["ADMIN", "STAFF", "VENTURES"]:
        return HttpResponse(status=403)
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    reservation_id = request.POST.get("reservation_id")
    amount = request.POST.get("amount")
    method = (request.POST.get("method") or PaymentMethod.TRANSFER).strip().upper()
    transaction_ref = (request.POST.get("transaction_ref") or "").strip()

    if not reservation_id or not amount:
        return JsonResponse({"detail": "reservation_id and amount are required"}, status=400)

    try:
        amount_dec = Decimal(str(amount))
    except Exception:
        return JsonResponse({"detail": "Invalid amount"}, status=400)

    reservation = get_object_or_404(
        Reservation.objects.select_related("user", "hall"),
        pk=int(reservation_id),
    )

    from reservations.models import BookingCaseStatus
    if reservation.case_status in [
        BookingCaseStatus.BOOKING_REJECTED,
        BookingCaseStatus.CASE_CLOSED,
        BookingCaseStatus.PAYMENT_EXPIRED,
    ]:
        return JsonResponse({"detail": "Cannot record payment for this booking in its current state."}, status=400)

    valid_method = method if method in PaymentMethod.values else PaymentMethod.TRANSFER
    ref = transaction_ref or _new_reference("LASU_MANUAL")

    from payments.services import PaymentResolutionService
    from payments.models import PaymentProofType

    try:
        payment = PaymentResolutionService.finalize_payment(
            reservation=reservation,
            amount=amount_dec,
            method=valid_method,
            transaction_reference=ref,
            actor=request.user,
            provider=PaymentProvider.PAYSTACK,
            payment_type=PaymentProofType.BOOKING,
            metadata={"kind": "manual", "recorded_by": request.user.email},
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("record_manual_payment failed")
        return JsonResponse({"detail": str(exc)}, status=500)

    create_audit_log(
        user=request.user,
        action=f"manual_payment_recorded:{ref}",
        model_name="Payment",
    )
    return JsonResponse({
        "paid": True,
        "payment_id": payment.id,
        "reference": ref,
        "status": "UNDER_BURSARY_VERIFICATION",
        "message": "Payment recorded and queued for Bursary verification.",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Enterprise Receipt PDF Download
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def enterprise_receipt_pdf(request, booking_reference: str):
    """
    Generate and download the official A4 enterprise payment receipt.
    Available to the applicant, Bursary, Ventures, and Admin once payment
    has been submitted (PAYMENT_SUBMITTED or later stages).
    """
    from reservations.models import Reservation, BookingCaseStatus
    from payments.models import PaymentProof, PaymentProofStatus
    from payments.receipt_pdf import build_enterprise_receipt_pdf

    # Resolve reservation
    qs = Reservation.objects.select_related("user", "hall").prefetch_related("payment_proofs", "payments")
    is_staff_viewer = (
        can_view_all(request.user)
        or getattr(request.user, "role", None) in ("VENTURES", "BURSARY", "ADMIN", "STAFF")
    )
    if not is_staff_viewer:
        qs = qs.filter(user=request.user)
    reservation = get_object_or_404(qs, booking_reference=booking_reference)

    # Must be at or past PAYMENT_SUBMITTED to access official receipt
    ALLOWED_STATUSES = {
        BookingCaseStatus.PAYMENT_SUBMITTED,
        BookingCaseStatus.UNDER_BURSARY_VERIFICATION,
        BookingCaseStatus.PAYMENT_VERIFIED,
        BookingCaseStatus.PAYMENT_REJECTED,
        BookingCaseStatus.AWAITING_FINAL_APPROVAL,
        BookingCaseStatus.BOOKING_APPROVED,
        BookingCaseStatus.EVENT_COMPLETED,
        BookingCaseStatus.UNDER_POST_EVENT_INSPECTION,
        BookingCaseStatus.DAMAGE_ASSESSED,
        BookingCaseStatus.AWAITING_DAMAGE_PAYMENT,
        BookingCaseStatus.DAMAGE_PAYMENT_SUBMITTED,
        BookingCaseStatus.UNDER_DAMAGE_PAYMENT_VERIFICATION,
        BookingCaseStatus.DAMAGE_PAYMENT_VERIFIED,
        BookingCaseStatus.CASE_CLOSED,
    }
    
    APPLICANT_ALLOWED_STATUSES = {
        BookingCaseStatus.BOOKING_APPROVED,
        BookingCaseStatus.EVENT_COMPLETED,
        BookingCaseStatus.UNDER_POST_EVENT_INSPECTION,
        BookingCaseStatus.DAMAGE_ASSESSED,
        BookingCaseStatus.AWAITING_DAMAGE_PAYMENT,
        BookingCaseStatus.DAMAGE_PAYMENT_SUBMITTED,
        BookingCaseStatus.UNDER_DAMAGE_PAYMENT_VERIFICATION,
        BookingCaseStatus.DAMAGE_PAYMENT_VERIFIED,
        BookingCaseStatus.CASE_CLOSED,
    }
    
    if reservation.case_status not in ALLOWED_STATUSES:
        messages.error(request, "Official receipt is not available at this stage.")
        return redirect("reservations:detail", booking_reference=booking_reference)
        
    if not is_staff_viewer and reservation.case_status not in APPLICANT_ALLOWED_STATUSES:
        messages.error(request, "Final documents (including the official receipt) are only available after Ventures Final Approval.")
        return redirect("reservations:detail", booking_reference=booking_reference)

    # Most recent successful booking payment
    payment = (
        reservation.payments
        .filter(status=PaymentStatus.PAID, damage_report__isnull=True, penalty__isnull=True)
        .order_by("-created_at")
        .first()
    )
    # Most recent verified or pending proof
    proof = (
        reservation.payment_proofs
        .filter(payment_type="BOOKING")
        .order_by("-uploaded_at")
        .first()
    )

    from payments.receipt_pdf import build_enterprise_receipt_pdf
    pdf_bytes = build_enterprise_receipt_pdf(
        reservation=reservation,
        payment=payment,
        payment_proof=proof,
        request=request,
    )
    filename = f"LASU_Receipt_{booking_reference}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    create_audit_log(
        user=request.user,
        action=f"enterprise_receipt_downloaded:{booking_reference}",
        model_name="Reservation",
    )
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Bursary Payment Review Detail Page
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def bursary_payment_review(request, booking_reference: str):
    """
    Full Bursary payment review page:
    - A4-layout generated receipt
    - Payment evidence
    - Communication thread
    - Audit history
    - Approve / Reject / Clarification actions
    """
    from reservations.models import (
        Reservation, BookingCaseStatus, CommunicationThread,
    )
    from payments.models import PaymentProof, PaymentProofStatus
    from payments.receipt_pdf import build_enterprise_receipt_pdf
    from core.models import AuditLog

    if (
        getattr(request.user, "role", None) not in ("BURSARY", "ADMIN", "STAFF")
        and not can_view_all(request.user)
    ):
        messages.error(request, "Access denied.")
        return redirect("hall:home")

    reservation = get_object_or_404(
        Reservation.objects.select_related("user", "hall", "coupon_approved_by")
        .prefetch_related(
            "payment_proofs", "payments", "timeline_events",
            "status_history", "logs",
        ),
        booking_reference=booking_reference,
    )

    # Financial data
    auth = getattr(reservation, "payment_authorization", None)
    if not auth:
        try:
            from reservations.models import PaymentAuthorization
            auth = PaymentAuthorization.objects.filter(reservation=reservation).first()
        except Exception:
            auth = None

    # ── Fetch ALL payments for this reservation (booking + damage + penalty) ──
    all_payments_qs = (
        reservation.payments
        .select_related("damage_report", "penalty", "user")
        .order_by("-created_at")
    )

    # Most recent booking-level paid payment (for receipt header)
    booking_payment = (
        all_payments_qs
        .filter(status=PaymentStatus.PAID, damage_report__isnull=True, penalty__isnull=True)
        .first()
    )

    # Fetch proofs separately for better UI organization
    from payments.models import PaymentProofType, PaymentProofStatus
    all_proofs = reservation.payment_proofs.all().order_by("-uploaded_at")
    booking_proofs = [p for p in all_proofs if p.payment_type == PaymentProofType.BOOKING]
    damage_proofs  = [p for p in all_proofs if p.payment_type == PaymentProofType.DAMAGE]
    penalty_proofs = [p for p in all_proofs if p.payment_type == PaymentProofType.PENALTY]
    
    pending_booking_proofs = [p for p in booking_proofs if p.status == PaymentProofStatus.PENDING]
    pending_damage_proofs  = [p for p in damage_proofs if p.status == PaymentProofStatus.PENDING]
    pending_penalty_proofs = [p for p in penalty_proofs if p.status == PaymentProofStatus.PENDING]
    
    latest_proof   = booking_proofs[0] if booking_proofs else None

    # ── Build unified payment+proof rows for Bursary receipt review ──────────
    # Match proofs to payments based on reference, and keep track of matched proofs
    proof_by_ref = {}
    for p in all_proofs:
        if p.transaction_ref:
            proof_by_ref.setdefault(p.transaction_ref, []).append(p)

    accounted_proofs = set()
    unified_payments = []

    for pmt in all_payments_qs:
        matched_proofs = (
            proof_by_ref.get(pmt.transaction_reference, [])
            or proof_by_ref.get(pmt.paystack_reference, [])
        )
        for mp in matched_proofs:
            accounted_proofs.add(mp.id)

        if pmt.damage_report_id:
            label = "Damage Payment"
            badge_class = "bg-danger"
            icon = "bi-tools"
        elif pmt.penalty_id:
            label = "Penalty Payment"
            badge_class = "bg-warning text-dark"
            icon = "bi-exclamation-octagon"
        else:
            label = "Hall Booking Payment"
            badge_class = "bg-primary"
            icon = "bi-cash-coin"
            
        unified_payments.append({
            "payment":       pmt,
            "label":         label,
            "badge_class":   badge_class,
            "icon":          icon,
            "proofs":        matched_proofs,
        })

    # Also include proofs that have no matching Payment object (manual uploads)
    for proof in all_proofs:
        if proof.id not in accounted_proofs:
            if proof.payment_type == PaymentProofType.BOOKING:
                label, badge_class, icon = "Hall Booking Payment (Manual Upload)", "bg-primary text-white", "bi-cash-coin"
            elif proof.payment_type == PaymentProofType.DAMAGE:
                label, badge_class, icon = "Damage Payment (Manual Upload)", "bg-danger text-white", "bi-tools"
            else:
                label, badge_class, icon = "Penalty Payment (Manual Upload)", "bg-warning text-dark", "bi-exclamation-octagon"
            
            unified_payments.append({
                "payment":     None,
                "label":       label,
                "badge_class": badge_class,
                "icon":        icon,
                "proofs":      [proof],
            })
            accounted_proofs.add(proof.id)

    # ── Sum ALL paid amounts across payment types for financial summary ───────
    from decimal import Decimal as D
    amount_paid_total = sum(
        (p.amount for p in all_payments_qs if p.status == PaymentStatus.PAID),
        D("0")
    )

    # Communication thread
    thread, _ = CommunicationThread.objects.get_or_create(reservation=reservation)
    thread_messages = thread.messages.select_related("sender").prefetch_related("attachments").order_by("created_at")

    # Audit trail
    audit_logs = AuditLog.objects.filter(
        object_repr__icontains=booking_reference
    ).order_by("-timestamp")[:50]

    # Financial breakdown for display
    hall_price      = (auth.hall_price      if auth else reservation.total_cost) or D("0")
    coupon_discount = (auth.coupon_discount if auth else reservation.discount_amount_applied) or D("0")
    discount_amount = (auth.discount_amount if auth else reservation.discount_value) or D("0")
    security_dep    = (auth.security_deposit if auth else reservation.security_deposit) or D("0")
    extra_charges   = (auth.extra_charges   if auth else D("0")) or D("0")
    vat_amount      = (auth.vat_amount      if auth else D("0")) or D("0")
    total_amount    = (auth.total_amount    if auth else reservation.total_cost) or D("0")
    # Use booking payment for the primary receipt, but total_paid covers everything
    amount_paid     = booking_payment.amount if booking_payment else D("0")
    difference      = total_amount - amount_paid
    outstanding     = (auth.outstanding_balance if auth else D("0")) or D("0")

    # Determine if there are outstanding damages or penalties to allow manual confirmation
    has_outstanding_damages = any(not d.is_paid and not d.is_forgiven for d in reservation.damage_reports.all())
    has_outstanding_penalties = any(not p.is_paid and not p.is_forgiven for p in reservation.penalties.all())

    context = {
        "reservation":          reservation,
        "auth":                 auth,
        "booking_payment":      booking_payment,
        "booking_proofs":       booking_proofs,
        "damage_proofs":        damage_proofs,
        "penalty_proofs":       penalty_proofs,
        "pending_booking_proofs": pending_booking_proofs,
        "pending_damage_proofs":  pending_damage_proofs,
        "pending_penalty_proofs": pending_penalty_proofs,
        "has_outstanding_damages": has_outstanding_damages,
        "has_outstanding_penalties": has_outstanding_penalties,
        "latest_proof":         latest_proof,
        # Unified list for the new "All Receipts" panel
        "unified_payments":     unified_payments,
        "amount_paid_total":    amount_paid_total,
        "thread_messages":      thread_messages,
        "audit_logs":           audit_logs,
        "BookingCaseStatus":    BookingCaseStatus,
        "PaymentProofStatus":   PaymentProofStatus,
        "PaymentStatus":        PaymentStatus,
        # Financial summary
        "hall_price":           hall_price,
        "coupon_discount":      coupon_discount,
        "discount_amount":      discount_amount,
        "security_dep":         security_dep,
        "extra_charges":        extra_charges,
        "vat_amount":           vat_amount,
        "total_amount":         total_amount,
        "amount_paid":          amount_paid,
        "difference":           difference,
        "outstanding":          outstanding,
        "coupon_code":          (auth.coupon_code if auth else reservation.coupon_code) or "",
    }
    return render(request, "payments/bursary_payment_review.html", context)


# ─────────────────────────────────────────────────────────────────────────────
# Coupon Management (Admin / Ventures / Facility)
# ─────────────────────────────────────────────────────────────────────────────

def _can_manage_coupons(user):
    """Admin can manage all coupons; Ventures/Facility can manage their own department's coupons."""
    return getattr(user, "role", None) in ("ADMIN", "VENTURES", "FACILITY")


def _coupon_qs_for_user(user):
    """Return the coupon queryset scoped to the user's management role."""
    from payments.models import Coupon
    qs = Coupon.objects.select_related("created_by")
    if getattr(user, "role", None) == "ADMIN":
        return qs
    # Ventures/Facility see only their department's coupons
    dept = getattr(user, "role", "")
    return qs.filter(owner_department=dept)


@login_required
def coupon_list(request):
    """List all coupons the current user can manage."""
    if not _can_manage_coupons(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("You do not have permission to manage coupons.")
    from payments.models import Coupon
    coupons = _coupon_qs_for_user(request.user)
    return render(request, "payments/coupon_list.html", {"coupons": coupons})


@login_required
def coupon_create(request):
    """Create a new coupon."""
    if not _can_manage_coupons(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Not authorized.")

    from payments.models import Coupon, DiscountType
    from hall.models import Hall, HallCategory

    if request.method == "POST":
        code = (request.POST.get("code") or "").strip().upper()
        if not code:
            messages.error(request, "Coupon code is required.")
        elif Coupon.objects.filter(code=code).exists():
            messages.error(request, f"Coupon code '{code}' already exists.")
        else:
            coupon = Coupon(
                code=code,
                name=(request.POST.get("name") or "").strip(),
                description=(request.POST.get("description") or "").strip(),
                discount_type=request.POST.get("discount_type", DiscountType.PERCENTAGE),
                value=request.POST.get("value") or 0,
                min_booking_amount=request.POST.get("min_booking_amount") or 0,
                max_discount=request.POST.get("max_discount") or None,
                total_usage_limit=request.POST.get("total_usage_limit") or None,
                usage_per_user=request.POST.get("usage_per_user") or 1,
                valid_from=request.POST.get("valid_from") or None,
                valid_until=request.POST.get("valid_until") or None,
                faculty_restriction=(request.POST.get("faculty_restriction") or "").strip(),
                department_restriction=(request.POST.get("department_restriction") or "").strip(),
                role_restriction=(request.POST.get("role_restriction") or "").strip(),
                is_stackable=bool(request.POST.get("is_stackable")),
                is_active=bool(request.POST.get("is_active")),
                owner_department=request.POST.get("owner_department") or getattr(request.user, "role", ""),
                created_by=request.user,
            )
            coupon.save()
            # Applicable halls (M2M)
            hall_ids = request.POST.getlist("applicable_halls")
            if hall_ids:
                coupon.applicable_halls.set(Hall.objects.filter(pk__in=hall_ids))
            create_audit_log(user=request.user, action=f"Created coupon: {coupon.code}", model_name="Coupon")
            messages.success(request, f"Coupon '{coupon.code}' created successfully.")
            return redirect("payments:coupon_list")

    halls = Hall.objects.filter(is_active=True).order_by("name")
    from payments.models import DiscountType
    return render(request, "payments/coupon_form.html", {
        "coupon": None,
        "halls": halls,
        "discount_types": DiscountType.choices,
        "role_choices": [("", "All Roles"), ("STUDENT", "Student"), ("STAFF", "Staff"),
                         ("EXTERNAL", "External"), ("DEPARTMENT", "Department")],
    })


@login_required
def coupon_edit(request, pk):
    """Edit an existing coupon."""
    if not _can_manage_coupons(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Not authorized.")

    from payments.models import Coupon, DiscountType
    from hall.models import Hall

    coupon = get_object_or_404(_coupon_qs_for_user(request.user), pk=pk)

    if request.method == "POST":
        coupon.name = (request.POST.get("name") or coupon.name).strip()
        coupon.description = (request.POST.get("description") or "").strip()
        coupon.discount_type = request.POST.get("discount_type", coupon.discount_type)
        coupon.value = request.POST.get("value") or coupon.value
        coupon.min_booking_amount = request.POST.get("min_booking_amount") or 0
        coupon.max_discount = request.POST.get("max_discount") or None
        coupon.total_usage_limit = request.POST.get("total_usage_limit") or None
        coupon.usage_per_user = request.POST.get("usage_per_user") or 1
        coupon.valid_from = request.POST.get("valid_from") or None
        coupon.valid_until = request.POST.get("valid_until") or None
        coupon.faculty_restriction = (request.POST.get("faculty_restriction") or "").strip()
        coupon.department_restriction = (request.POST.get("department_restriction") or "").strip()
        coupon.role_restriction = (request.POST.get("role_restriction") or "").strip()
        coupon.is_stackable = bool(request.POST.get("is_stackable"))
        coupon.is_active = bool(request.POST.get("is_active"))
        coupon.owner_department = request.POST.get("owner_department") or coupon.owner_department
        coupon.save()
        hall_ids = request.POST.getlist("applicable_halls")
        coupon.applicable_halls.set(Hall.objects.filter(pk__in=hall_ids) if hall_ids else [])
        create_audit_log(user=request.user, action=f"Updated coupon: {coupon.code}", model_name="Coupon")
        messages.success(request, f"Coupon '{coupon.code}' updated.")
        return redirect("payments:coupon_list")

    halls = Hall.objects.filter(is_active=True).order_by("name")
    current_hall_ids = set(coupon.applicable_halls.values_list("pk", flat=True))
    return render(request, "payments/coupon_form.html", {
        "coupon": coupon,
        "halls": halls,
        "current_hall_ids": current_hall_ids,
        "discount_types": DiscountType.choices,
        "role_choices": [("", "All Roles"), ("STUDENT", "Student"), ("STAFF", "Staff"),
                         ("EXTERNAL", "External"), ("DEPARTMENT", "Department")],
    })


@login_required
def coupon_delete(request, pk):
    """Delete a coupon (POST only)."""
    if not _can_manage_coupons(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Not authorized.")
    coupon = get_object_or_404(_coupon_qs_for_user(request.user), pk=pk)
    if request.method == "POST":
        code = coupon.code
        coupon.delete()
        create_audit_log(user=request.user, action=f"Deleted coupon: {code}", model_name="Coupon")
        messages.success(request, f"Coupon '{code}' deleted.")
    return redirect("payments:coupon_list")


@login_required
def coupon_toggle(request, pk):
    """Toggle a coupon's active status."""
    if not _can_manage_coupons(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Not authorized.")
    coupon = get_object_or_404(_coupon_qs_for_user(request.user), pk=pk)
    if request.method == "POST":
        coupon.is_active = not coupon.is_active
        coupon.save(update_fields=["is_active"])
        state = "activated" if coupon.is_active else "deactivated"
        create_audit_log(user=request.user, action=f"Coupon {state}: {coupon.code}", model_name="Coupon")
        messages.success(request, f"Coupon '{coupon.code}' {state}.")
    return redirect("payments:coupon_list")



@login_required
def damage_receipt_pdf(request, damage_id: int):
    """
    Generate and download the official A4 receipt for a Damage Payment.
    """
    from reservations.models import DamageReport
    from payments.models import PaymentStatus, Payment, PaymentProof
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
    from payments.models import PaymentStatus, Payment, PaymentProof
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

