import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from users.models import User, UserRole, LoginLog
from core.services import create_audit_log

logger = logging.getLogger(__name__)


def _is_super_admin(user):
    return getattr(user, "is_superuser", False) or getattr(user, "role", None) == UserRole.ADMIN


@login_required
def admin_user_list(request):
    if not _is_super_admin(request.user):
        return HttpResponseForbidden("You do not have permission to access the User Management console.")

    qs = User.objects.all().order_by("-date_joined")

    # Search
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(username__icontains=q) |
            Q(email__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q)
        )

    # Filters
    role = request.GET.get("role")
    if role:
        qs = qs.filter(role=role)
        
    status = request.GET.get("status")
    if status == "active":
        qs = qs.filter(is_active=True, is_blocked=False)
    elif status == "blocked":
        qs = qs.filter(is_blocked=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)

    # Sorting
    sort = request.GET.get("sort")
    if sort in ["email", "-email", "username", "-username", "date_joined", "-date_joined", "role", "-role"]:
        qs = qs.order_by(sort)

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "page_obj": page_obj,
        "q": q,
        "role": role,
        "status": status,
        "sort": sort,
        "roles": UserRole.choices,
        "total_users": User.objects.count(),
        "blocked_users": User.objects.filter(is_blocked=True).count(),
        "active_users": User.objects.filter(is_active=True).count(),
    }
    return render(request, "users/admin_user_list.html", context)


@login_required
def admin_user_detail(request, pk):
    if not _is_super_admin(request.user):
        return HttpResponseForbidden("You do not have permission to access the User Management console.")

    user = get_object_or_404(User, pk=pk)
    recent_logins = LoginLog.objects.filter(user=user).order_by("-timestamp")[:10]
    
    # We will get their reservations manually using related name if exists, or import Reservation
    from reservations.models import Reservation
    recent_bookings = Reservation.objects.filter(user=user).order_by("-created_at")[:10]

    context = {
        "u": user,
        "recent_logins": recent_logins,
        "recent_bookings": recent_bookings,
    }
    return render(request, "users/admin_user_detail.html", context)


@login_required
def admin_user_create(request):
    if not _is_super_admin(request.user):
        return HttpResponseForbidden("You do not have permission to access the User Management console.")

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        username = (request.POST.get("username") or "").strip()
        first_name = (request.POST.get("first_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()
        role = request.POST.get("role")
        department = (request.POST.get("department") or "").strip()
        password = request.POST.get("password") or ""

        if not email or not username or not password:
            messages.error(request, "Email, username, and password are required.")
        elif User.objects.filter(email=email).exists():
            messages.error(request, "A user with this email already exists.")
        elif User.objects.filter(username=username).exists():
            messages.error(request, "A user with this username already exists.")
        else:
            user = User(
                email=email,
                username=username,
                first_name=first_name,
                last_name=last_name,
                role=role,
                department=department,
                is_active=True,
                is_verified=True
            )
            user.set_password(password)
            user.save()
            create_audit_log(user=request.user, action=f"Created user {user.email} with role {user.role}", model_name="User")
            messages.success(request, f"User {user.email} created successfully.")
            return redirect("users:admin_user_list")

    return render(request, "users/admin_user_form.html", {
        "roles": UserRole.choices,
        "u": None
    })


@login_required
def admin_user_update(request, pk):
    if not _is_super_admin(request.user):
        return HttpResponseForbidden("You do not have permission to access the User Management console.")

    user = get_object_or_404(User, pk=pk)

    if request.method == "POST":
        user.first_name = (request.POST.get("first_name") or "").strip()
        user.last_name = (request.POST.get("last_name") or "").strip()
        user.department = (request.POST.get("department") or "").strip()
        
        # Don't let superadmins accidentally demote themselves unless there's another superadmin
        new_role = request.POST.get("role")
        if user == request.user and new_role != UserRole.ADMIN:
            messages.warning(request, "You cannot remove your own ADMIN role.")
        else:
            user.role = new_role

        user.is_blocked = request.POST.get("is_blocked") == "on"
        user.is_active = request.POST.get("is_active") == "on"
        user.is_verified = request.POST.get("is_verified") == "on"

        password = request.POST.get("password") or ""
        if password:
            user.set_password(password)

        user.save()
        create_audit_log(user=request.user, action=f"Updated user {user.email}", model_name="User")
        messages.success(request, f"User {user.email} updated successfully.")
        return redirect("users:admin_user_detail", pk=user.pk)

    return render(request, "users/admin_user_form.html", {
        "roles": UserRole.choices,
        "u": user
    })
