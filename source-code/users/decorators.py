from functools import wraps

from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from users.services import can


def capability_required(capability: str, login_url: str = "users:login"):
    """
    Decorator to check if user has a specific capability.
    Redirects to login if not authenticated, returns 403 if authenticated but lacks capability.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(login_url)
            if not can(request.user, capability):
                if request.headers.get("HX-Request"):
                    return HttpResponseForbidden("Insufficient permissions")
                messages.error(request, "You do not have permission to access this page.")
                return HttpResponseForbidden("Insufficient permissions")
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def role_required(*roles: str, login_url: str = "users:login"):
    """
    Decorator to check if user has one of the specified roles.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(login_url)
            if getattr(request.user, "role", None) not in roles:
                if request.headers.get("HX-Request"):
                    return HttpResponseForbidden("Insufficient permissions")
                messages.error(request, "You do not have permission to access this page.")
                return HttpResponseForbidden("Insufficient permissions")
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator