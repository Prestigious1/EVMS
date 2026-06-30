"""Shared Paystack helpers (amount in kobo, server-side checks, callback URL)."""
from __future__ import annotations

from decimal import Decimal
from django.conf import settings
from django.urls import reverse

from payments.models import Payment


def naira_to_kobo(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1")))


def amount_kobo_matches_payment(*, verify_data: dict, payment: Payment) -> bool:
    """Paystack verify `amount` is in kobo for NGN; must match our stored payment.amount."""
    try:
        paid_kobo = int(verify_data.get("amount") or 0)
    except (TypeError, ValueError):
        return False
    expected = naira_to_kobo(payment.amount or Decimal("0.00"))
    return paid_kobo == expected


def paystack_secret_configured() -> bool:
    return bool((getattr(settings, "PAYSTACK_SECRET_KEY", "") or "").strip())


def get_paystack_verify_callback_url(*, request) -> str:
    """
    Paystack redirect URL (must be absolute, publicly reachable).
    Prefer WEBSITE_ADDRESS from settings; fall back to the current request host.
    """
    base = (getattr(settings, "WEBSITE_ADDRESS", "") or "").strip().rstrip("/")
    path = reverse("payments:paystack_verify_redirect")
    if base:
        return f"{base}{path}"
    return request.build_absolute_uri(path)


def sign_checkout_token(payment_id: int) -> str:
    from django.core import signing

    return signing.TimestampSigner(salt="lasu.hall.paystack.ok").sign(str(payment_id))


def unsign_checkout_token(token: str, *, max_age: int = 86400) -> int | None:
    from django.core import signing

    try:
        return int(signing.TimestampSigner(salt="lasu.hall.paystack.ok").unsign(token, max_age=max_age))
    except (signing.BadSignature, signing.SignatureExpired, ValueError):
        return None


def sign_failure_token(*, payment_id: int, reference: str, reason: str) -> str:
    import json

    from django.core import signing

    blob = json.dumps({"p": payment_id, "ref": reference, "m": reason[:400]})
    return signing.TimestampSigner(salt="lasu.hall.paystack.fail").sign(blob)


def unsign_failure_token(token: str, *, max_age: int = 86400) -> tuple[int, str, str] | None:
    import json

    from django.core import signing

    try:
        raw = signing.TimestampSigner(salt="lasu.hall.paystack.fail").unsign(token, max_age=max_age)
        data = json.loads(raw)
        return int(data["p"]), str(data["ref"]), str(data.get("m") or "")
    except (signing.BadSignature, signing.SignatureExpired, ValueError, KeyError, TypeError):
        return None
