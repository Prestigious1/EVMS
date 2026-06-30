import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from users.models import User, UserRole
from users.services import record_login

logger = logging.getLogger(__name__)


def _unique_username_from_email(email: str, preferred: str = "") -> str:
    base = (preferred or "").strip() or (email.split("@")[0] if "@" in email else email)[:80]
    base = base or "user"
    candidate = base
    n = 0
    while User.objects.filter(username__iexact=candidate).exists():
        n += 1
        candidate = f"{base}{n}"
    return candidate


def register_view(request):
    if request.user.is_authenticated:
        return redirect("hall:dashboard")

    if request.method == "POST":
        preferred_username = (request.POST.get("username") or "").strip()
        email = (request.POST.get("email") or "").lower().strip()
        password = request.POST.get("password") or ""

        if not email or not password:
            messages.error(request, "Email and password are required.")
            return render(request, "users/register.html")

        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, "An account with this email already exists.")
            return render(request, "users/register.html")

        role = UserRole.STUDENT if email.endswith("@lasu.edu.ng") else UserRole.EXTERNAL
        uname = _unique_username_from_email(email, preferred_username)
        user = User(username=uname, email=email, role=role)
        user.set_password(password)
        user.save()
        login(request, user)
        return redirect("hall:dashboard")

    return render(request, "users/register.html")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("hall:dashboard")

    if request.method == "POST":
        raw_login = (request.POST.get("email") or "").strip()
        email_lower = raw_login.lower()
        password = request.POST.get("password") or ""

        user = None
        by_email = User.objects.filter(email__iexact=email_lower).first()
        if by_email:
            user = authenticate(request, username=by_email.username, password=password)
        if user is None and raw_login:
            user = authenticate(request, username=raw_login, password=password)
        if user is None:
            if settings.DEBUG:
                logger.debug(
                    "Login failed: no matching credentials for identifier=%r (email_match=%s)",
                    raw_login,
                    bool(by_email),
                )
            messages.error(request, "Invalid credentials.")
            return render(request, "users/login.html")

        if not user.is_active:
            messages.error(request, "This account is inactive. Contact support if you need help.")
            return render(request, "users/login.html")

        if getattr(user, "is_blocked", False):
            messages.error(request, "This account cannot sign in. Contact LASU Hall Management.")
            return render(request, "users/login.html")

        login(request, user)
        record_login(
            user=user,
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        return redirect("hall:dashboard")

    return render(request, "users/login.html")


@login_required
def logout_view(request):
    logout(request)
    return redirect("users:login")


@login_required
def profile_view(request):
    user = request.user
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "profile":
            user.first_name = (request.POST.get("first_name") or "").strip()
            user.last_name = (request.POST.get("last_name") or "").strip()
            user.phone_number = (request.POST.get("phone_number") or "").strip()
            user.department = (request.POST.get("department") or "").strip()
            if request.FILES.get("profile_image"):
                user.profile_image = request.FILES["profile_image"]
            user.save(update_fields=["first_name", "last_name", "phone_number", "department", "profile_image"])
            messages.success(request, "Profile updated successfully.")
            return redirect("users:profile")
        if action == "password":
            form = PasswordChangeForm(user, request.POST)
            if form.is_valid():
                user = form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Password changed successfully.")
                return redirect("users:profile")
            messages.error(request, "Please correct the password form errors.")
            return render(request, "users/profile.html", {"u": request.user, "password_form": form})
    return render(request, "users/profile.html", {"u": user, "password_form": PasswordChangeForm(user)})
