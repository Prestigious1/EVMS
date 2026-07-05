from __future__ import annotations

import uuid
from typing import Optional

from django.conf import settings
from django.core.mail import send_mail
from django.utils.html import strip_tags

from core.models import AuditLog, ActivityLog
from notifications.models import Notification


def get_client_ip(request) -> str | None:
    """Extract the real client IP from the request, respecting proxies."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def get_user_agent_info(request) -> tuple[str, str]:
    """Parse browser name and OS from the User-Agent string.

    Returns:
        (browser, os_info) — both strings, may be empty.
    """
    ua = request.META.get("HTTP_USER_AGENT", "") if request else ""
    browser = ""
    os_info = ""

    if ua:
        ua_lower = ua.lower()

        # OS detection (order matters — most specific first)
        if "windows nt 10" in ua_lower:
            os_info = "Windows 10/11"
        elif "windows nt 6.3" in ua_lower:
            os_info = "Windows 8.1"
        elif "windows nt 6.1" in ua_lower:
            os_info = "Windows 7"
        elif "windows" in ua_lower:
            os_info = "Windows"
        elif "mac os x" in ua_lower:
            os_info = "macOS"
        elif "android" in ua_lower:
            os_info = "Android"
        elif "iphone" in ua_lower or "ipad" in ua_lower:
            os_info = "iOS"
        elif "linux" in ua_lower:
            os_info = "Linux"
        else:
            os_info = "Unknown OS"

        # Browser detection (order matters — Edge before Chrome, Chrome before Safari)
        if "edg/" in ua_lower:
            browser = "Microsoft Edge"
        elif "opr/" in ua_lower or "opera" in ua_lower:
            browser = "Opera"
        elif "firefox/" in ua_lower:
            browser = "Firefox"
        elif "chrome/" in ua_lower:
            browser = "Chrome"
        elif "safari/" in ua_lower:
            browser = "Safari"
        elif "msie" in ua_lower or "trident/" in ua_lower:
            browser = "Internet Explorer"
        else:
            browser = "Unknown Browser"

    return browser, os_info


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
    affected_module: str = "",
    reason: str = "",
    comments: str = "",
) -> AuditLog:
    """Create a rich, immutable audit log entry.

    Args:
        user: The user performing the action (may be unauthenticated).
        action: Short description of the action taken.
        model_name: Django model class name (e.g. 'Hall', 'Announcement').
        object_repr: String representation of the affected object.
        old_value: Serialised previous state (JSON string or human-readable).
        new_value: Serialised new state.
        ip_address: Explicit IP override. If omitted, extracted from ``request``.
        request: Django HttpRequest used to extract IP, user-agent, role.
        affected_module: App/module where the action occurred (e.g. 'reservations').
        reason: Reason for the action if provided.
        comments: Additional context or notes.
    """
    auth_user = user if getattr(user, "is_authenticated", False) else None
    role = getattr(auth_user, "role", "") or ""
    department = getattr(auth_user, "department", "") or ""

    if ip_address is None and request is not None:
        ip_address = get_client_ip(request)

    browser, os_info = get_user_agent_info(request)
    request_id = str(uuid.uuid4())[:16] if request else ""

    return AuditLog.objects.create(
        user=auth_user,
        role=role,
        department=department,
        action=action,
        model_name=model_name,
        object_repr=object_repr,
        affected_module=affected_module or model_name.lower(),
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        comments=comments,
        ip_address=ip_address,
        browser=browser,
        os_info=os_info,
        request_id=request_id,
    )


def create_activity_log(
    *,
    user,
    action: str,
    affected_object: str = "",
    previous_value: str = "",
    new_value: str = "",
    request=None,
) -> ActivityLog:
    """Create an activity log entry (lightweight, non-immutable)."""
    auth_user = user if getattr(user, "is_authenticated", False) else None
    role = getattr(auth_user, "role", "") or ""
    ip = get_client_ip(request) if request else None
    return ActivityLog.objects.create(
        user=auth_user,
        role=role,
        action=action,
        affected_object=affected_object,
        previous_value=previous_value,
        new_value=new_value,
        ip_address=ip,
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

    Granted to: ADMIN, STAFF, VENTURES, FACILITY, BURSARY, and anyone with the
    'view_reports' RoleCapability.
    """
    from users.services import can
    role = getattr(user, "role", None)
    return can(user, "view_reports") or role in ("ADMIN", "STAFF", "VENTURES", "FACILITY", "BURSARY")
