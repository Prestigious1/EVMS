from django.shortcuts import render


def custom_403(request, exception=None):
    return render(request, "core/403.html", status=403)


def custom_404(request, exception=None):
    return render(request, "core/404.html", status=404)


def custom_500(request):
    return render(request, "core/500.html", status=500)


from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden
from django.db.models import Q
from core.models import AuditLog, ActivityLog
from users.models import LoginLog, UserRole

def _is_super_admin(user):
    return getattr(user, "is_superuser", False) or getattr(user, "role", None) == UserRole.ADMIN

@login_required
def admin_system_logs(request):
    if not _is_super_admin(request.user):
        return HttpResponseForbidden("You do not have permission to view system logs.")

    log_type = request.GET.get("type", "audit")
    q = (request.GET.get("q") or "").strip()
    
    if log_type == "login":
        qs = LoginLog.objects.select_related("user").order_by("-timestamp")
        if q:
            qs = qs.filter(Q(user__email__icontains=q) | Q(ip_address__icontains=q))
    elif log_type == "activity":
        qs = ActivityLog.objects.select_related("user").order_by("-timestamp")
        if q:
            qs = qs.filter(Q(user__email__icontains=q) | Q(action__icontains=q))
    else:
        qs = AuditLog.objects.select_related("user").order_by("-timestamp")
        if q:
            qs = qs.filter(Q(user__email__icontains=q) | Q(action__icontains=q) | Q(model_name__icontains=q))

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "core/admin_system_logs.html", {
        "page_obj": page_obj,
        "log_type": log_type,
        "q": q,
    })
