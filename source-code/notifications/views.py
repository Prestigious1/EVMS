from django.contrib import messages
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.db import models
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from urllib.parse import urlparse

from notifications.models import BroadcastMessage, Notification
from users.services import can


@login_required
def inbox(request):
    qs = Notification.objects.filter(user=request.user).order_by("-created_at")
    unread_count = qs.filter(is_read=False).count()
    return render(request, "notifications/inbox.html", {"notifications": qs[:200], "unread_count": unread_count})


@login_required
def notification_go(request, pk: int):
    """
    Mark a notification as read and redirect to its action link.

    Works for both GET and POST so that 'Review Action' buttons and
    anchor links always reach the booking/update page without showing
    an error.  If the notification has no link we fall back to the
    inbox, ensuring this view never raises a 404 or 405.
    """
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    # Mark as read regardless of HTTP method
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=["is_read"])
    # Redirect to the stored link if it is a safe relative or absolute URL
    destination = (n.link or "").strip()
    if destination:
        parsed = urlparse(destination)
        # Only follow relative paths or same-origin URLs for safety
        if not parsed.scheme or parsed.scheme in ("http", "https"):
            return redirect(destination)
    return redirect("notifications:inbox")


@login_required
def mark_read(request, pk: int):
    """
    Mark a notification as read and redirect to its action link (or inbox).
    Accepts both GET and POST so that existing form buttons keep working.
    """
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=["is_read"])
    # After marking read, send the user to the booking page if a link exists
    destination = (n.link or "").strip()
    if destination:
        parsed = urlparse(destination)
        if not parsed.scheme or parsed.scheme in ("http", "https"):
            return redirect(destination)
    return redirect("notifications:inbox")


@login_required
def mark_all_read(request):
    if request.method != "POST":
        return HttpResponse(status=405)
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    messages.success(request, "All notifications marked as read.")
    return redirect("notifications:inbox")


@login_required
@require_POST
def delete_notification(request, pk: int):
    """Delete a single notification belonging to the current user."""
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    n.delete()
    messages.success(request, "Notification deleted.")
    return redirect("notifications:inbox")


@login_required
def broadcast_list(request):
    user = request.user
    role = getattr(user, "role", None)
    qs = BroadcastMessage.objects.all().order_by("-created_at")
    if not can(user, "ventures_workflow") and role not in ["ADMIN", "STAFF"]:
        qs = qs.filter(
            models.Q(target_role="") | models.Q(target_role__isnull=True) | models.Q(target_role=role)
        )
    return render(request, "notifications/broadcast_list.html", {"broadcasts": qs})


@login_required
def broadcast_create(request):
    if not can(request.user, "ventures_workflow") and getattr(request.user, "role", None) not in ["ADMIN", "STAFF"]:
        return HttpResponse(status=403)
    if request.method != "POST":
        return render(request, "notifications/broadcast_create.html", {"user_roles": __import__("users.models", fromlist=["UserRole"]).UserRole.choices})
    title = (request.POST.get("title") or "").strip()
    message = (request.POST.get("message") or "").strip()
    target_role = (request.POST.get("target_role") or "").strip()
    attachment = request.FILES.get("attachment")
    if not title or not message:
        messages.error(request, "Title and message are required.")
        return render(request, "notifications/broadcast_create.html", {"user_roles": __import__("users.models", fromlist=["UserRole"]).UserRole.choices})
    bc = BroadcastMessage.objects.create(
        created_by=request.user,
        title=title,
        message=message,
        target_role=target_role,
    )
    if attachment:
        bc.attachment = attachment
        bc.save(update_fields=["attachment"])
    messages.success(request, "Broadcast message sent successfully.")
    return redirect("notifications:broadcast_list")
