from __future__ import annotations

from typing import Optional

from django.conf import settings
from django.core.mail import send_mail
from django.utils.html import strip_tags

from core.models import AuditLog
from notifications.models import Notification


def get_client_ip(request) -> str | None:
    """Extract the real client IP from the request, respecting proxies."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def create_audit_log(
    *,
    user,
    action: str,
    model_name: str,
    object_repr: str = "",
    old_value: str = "",
    new_value: str = "",
    ip_address: str | None = None,
    request=None,
) -> AuditLog:
    """Create a rich, immutable audit log entry.

    Args:
        user: The user performing the action (may be unauthenticated).
        action: Short description of the action taken.
        model_name: Django model class name (e.g. 'Hall', 'Announcement').
        object_repr: String representation of the affected object.
        old_value: Serialised previous state (JSON string or human-readable).
        new_value: Serialised new state.
        ip_address: Explicit IP override. If omitted, extracted from `request`.
        request: Django HttpRequest used to extract IP and user role.
    """
    auth_user = user if getattr(user, "is_authenticated", False) else None
    role = getattr(auth_user, "role", "") or ""

    if ip_address is None and request is not None:
        ip_address = get_client_ip(request)

    return AuditLog.objects.create(
        user=auth_user,
        role=role,
        action=action,
        model_name=model_name,
        object_repr=object_repr,
        old_value=old_value,
        new_value=new_value,
        ip_address=ip_address,
    )


def notify_user(*, user, title: str, message: str, link: str | None = None) -> Optional[Notification]:
    """Create an in-app notification for a user. Returns None if user is None."""
    if user is None:
        return None
    return Notification.objects.create(user=user, title=title, message=message, link=link)


def email_user(*, user, subject: str, message: str, html_message: str | None = None) -> bool:
    """Send an email to a user. Fails silently if email is not configured."""
    if user is None or not getattr(user, "email", None):
        return False
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or "no-reply@example.com"
    send_mail(
        subject,
        strip_tags(html_message) if html_message else message,
        from_email,
        [user.email],
        fail_silently=True,
        html_message=html_message,
    )
    return True


def notify_and_email(*, user, title: str, message: str, link: str | None = None) -> Optional[Notification]:
    """Create an in-app notification and also send an email."""
    n = notify_user(user=user, title=title, message=message, link=link)
    email_user(user=user, subject=title, message=message)
    return n


def can_view_all(user) -> bool:
    """
    Returns True if the user can see all reservations and payments across all users.

    Granted to: ADMIN, STAFF.
    VENTURES and FACILITY see all in their own dashboards but via dedicated queries,
    not this flag — so they are intentionally excluded here.
    """
    return getattr(user, "role", None) in ("ADMIN", "STAFF")


def can_view_reports(user) -> bool:
    """
    Returns True if the user can access the reports dashboard and exports.

    Granted to: ADMIN, STAFF, and anyone with the 'view_reports' RoleCapability.
    """
    from users.services import can
    return can(user, "view_reports") or getattr(user, "role", None) in ("ADMIN", "STAFF")
