from django.conf import settings
from users.models import LoginLog, UserRole


def record_login(*, user, ip_address=None, user_agent=None):
    if user and getattr(user, "is_authenticated", False):
        LoginLog.objects.create(
            user=user,
            ip_address=ip_address or "",
            user_agent=(user_agent or "")[:255],
        )


def can(user, capability):
    """Check if user has a given capability. Admins always return True."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "role", None) == UserRole.ADMIN or getattr(user, "is_superuser", False):
        return True
    from users.models import RoleCapability
    return RoleCapability.objects.filter(role=user.role, capability=capability).exists()


# Convenience helpers — avoid repeated string literals in views
def can_manage_halls(user):
    """Facility and Admin can manage halls. Ventures CANNOT per spec."""
    return can(user, "manage_halls")


def can_manage_payments(user):
    """Ventures and Admin can manage payments. Facility CANNOT per spec."""
    return can(user, "manage_payments")


def can_manage_coupons(user):
    """Ventures and Admin only."""
    return can(user, "manage_coupons")


def can_manage_amenities(user):
    """Facility and Admin only."""
    return can(user, "manage_amenities")


def can_manage_hall_blocks(user):
    """Facility and Admin only."""
    return can(user, "manage_hall_blocks")


def can_manage_internal_reservations(user):
    """Facility and Admin only."""
    return can(user, "manage_internal_reservations")


def can_manage_inspections(user):
    """Facility and Admin only."""
    return can(user, "manage_inspections")


def can_manage_communications(user):
    """Ventures and Admin only."""
    return can(user, "manage_communications")


def can_view_financial_reports(user):
    """Ventures and Admin only."""
    return can(user, "view_financial_reports")


def can_view_reports(user):
    """Staff, Admin, Ventures, Facility, Department."""
    return can(user, "view_reports")


def can_manage_bursary(user):
    """Bursary and Admin only — gates payment verification queue."""
    from users.models import UserRole
    return getattr(user, "role", None) in (UserRole.BURSARY, UserRole.ADMIN) or can(user, "bursary_workflow")


def can_submit_booking(user):
    """
    Returns (True, None) if the user may submit a booking,
    or (False, reason_str) if they are blocked.
    """
    if not getattr(user, "is_authenticated", False):
        return False, "You must be logged in."
    if getattr(user, "is_blocked", False):
        return False, "Your account is currently restricted due to outstanding liabilities."
    # Lazy import to avoid circular
    try:
        from reservations.models import DamageReport, Penalty
        has_damage = DamageReport.objects.filter(user=user, is_paid=False, is_forgiven=False).exists()
        has_penalty = Penalty.objects.filter(user=user, is_paid=False, is_forgiven=False).exists()
        if has_damage or has_penalty:
            return False, "You have outstanding unpaid damage/penalty charges. Please clear them before submitting a new booking."
    except Exception:
        pass
    return True, None