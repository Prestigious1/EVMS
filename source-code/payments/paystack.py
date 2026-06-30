from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import requests
from django.conf import settings


class PaystackError(RuntimeError):
    pass


@dataclass(frozen=True)
class PaystackInitResult:
    authorization_url: str
    access_code: str
    reference: str


def _paystack_headers() -> dict[str, str]:
    secret = (getattr(settings, "PAYSTACK_SECRET_KEY", "") or "").strip()
    if not secret:
        raise PaystackError("PAYSTACK_SECRET_KEY is not configured.")
    return {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _request_json(*, method: str, url: str, payload: dict | None = None) -> dict:
    headers = _paystack_headers()
    timeout = 30
    try:
        if method.upper() == "POST":
            resp = requests.post(url, json=payload or {}, headers=headers, timeout=timeout)
        else:
            resp = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        raise PaystackError(f"Paystack network error: {e}") from e

    try:
        body = resp.json()
    except ValueError as e:
        raise PaystackError(f"Invalid JSON from Paystack (HTTP {resp.status_code}).") from e

    if not body.get("status"):
        msg = body.get("message") or f"Paystack request failed (HTTP {resp.status_code})."
        raise PaystackError(msg)

    return body


def initialize_transaction(*, email: str, amount_kobo: int, reference: str, callback_url: str, metadata: dict) -> PaystackInitResult:
    payload = {
        "email": email,
        "amount": amount_kobo,
        "reference": reference,
        "callback_url": callback_url,
        "metadata": metadata or {},
        "currency": "NGN",
    }
    res = _request_json(method="POST", url="https://api.paystack.co/transaction/initialize", payload=payload)
    data = res.get("data") or {}
    auth_url = (data.get("authorization_url") or "").strip()
    if not auth_url:
        raise PaystackError("Paystack did not return authorization_url.")
    return PaystackInitResult(
        authorization_url=auth_url,
        access_code=data.get("access_code") or "",
        reference=data.get("reference") or reference,
    )


def verify_transaction(*, reference: str) -> dict:
    ref = quote(str(reference), safe="")
    res = _request_json(method="GET", url=f"https://api.paystack.co/transaction/verify/{ref}")
    return res.get("data") or {}
