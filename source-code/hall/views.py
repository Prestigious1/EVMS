import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from datetime import timedelta

from django.db import models, transaction
from django.db.models import Q
from django.views.decorators.http import require_POST

from core.models import Announcement, ContactMessage, FAQ, AuditLog
from core.services import create_audit_log, get_client_ip
from hall.forms import (
    AmenityForm, HallBlockForm,
    get_hall_form_for_role, get_editable_fields_for_role,
    FACILITY_FIELDS, VENTURES_FIELDS,
)
from hall.models import Hall, HallAmenity, HallBookmark, HallBlock, HallCategory, HallImage, Amenity
from notifications.models import Notification
from reservations.models import Reservation
from reservations.forms import ReservationCreateForm
from users.decorators import capability_required, role_required


# ─────────────────────────────────────────────────────────────────────────────
# Permission helpers
# ─────────────────────────────────────────────────────────────────────────────

def _can_manage_halls(user):
    """Admin, Facility, AND Ventures can access hall management area.

    Ventures may create halls and edit pricing. Facility and Admin are the
    operational owners. Specific destructive/operational actions (blocking,
    archiving, image management, amenity management) are gated separately.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    role = getattr(user, "role", None)
    if role in ("ADMIN", "FACILITY", "VENTURES") or getattr(user, "is_superuser", False):
        return True
    from users.services import can
    return can(user, "manage_halls")


def _can_manage_hall_operations(user):
    """Only Facility and Admin can perform operational hall management.

    This covers: blocking halls, managing images, managing amenities.
    Ventures is explicitly excluded from these operational actions.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    role = getattr(user, "role", None)
    return role in ("ADMIN", "FACILITY") or getattr(user, "is_superuser", False)


def _is_admin(user):
    return getattr(user, "role", None) == "ADMIN" or getattr(user, "is_superuser", False)


def _user_role(user):
    return getattr(user, "role", None) or ""


# ─────────────────────────────────────────────────────────────────────────────
# Public / General pages
# ─────────────────────────────────────────────────────────────────────────────

def home(request):
    halls = Hall.objects.filter(is_active=True, is_archived=False)[:6]
    hero_halls = (
        Hall.objects.filter(is_active=True, is_archived=False)
        .exclude(gallery_images__isnull=True)
        .distinct()[:5]
    )
    announcements = Announcement.objects.filter(is_published=True).order_by("-created_at")[:3]

    from django.contrib.auth import get_user_model
    context = {
        "halls": halls,
        "hero_halls": hero_halls,
        "announcements": announcements,
        "total_halls": Hall.objects.filter(is_active=True, is_archived=False).count(),
        "completed_events": Reservation.objects.filter(status="COMPLETED").count(),
        "active_users": get_user_model().objects.filter(is_active=True).count(),
    }
    return render(request, "hall/home.html", context)


def hall_list(request):
    qs = Hall.objects.filter(is_active=True, is_archived=False).order_by("faculty", "building", "name")

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(faculty__icontains=q) | Q(building__icontains=q))

    category = request.GET.get("category", "").strip()
    if category:
        qs = qs.filter(category=category)

    try:
        capacity_min = int(request.GET.get("capacity_min") or 0)
        if capacity_min > 0:
            qs = qs.filter(capacity__gte=capacity_min)
    except ValueError:
        capacity_min = 0

    try:
        capacity_max = int(request.GET.get("capacity_max") or 0)
        if capacity_max > 0:
            qs = qs.filter(capacity__lte=capacity_max)
    except ValueError:
        capacity_max = 0

    try:
        rate_max = int(request.GET.get("rate_max") or 0)
        if rate_max > 0:
            qs = qs.filter(daily_rate__lte=rate_max)
    except ValueError:
        rate_max = 0

    avail_date = request.GET.get("avail_date", "").strip()
    if avail_date:
        from reservations.models import ReservationStatus
        from datetime import datetime
        try:
            d = datetime.strptime(avail_date, "%Y-%m-%d").date()
            booked_hall_ids = Reservation.objects.filter(booking_date=d).exclude(
                status__in=["CANCELLED", "REJECTED", "CLOSED"]
            ).values_list("hall_id", flat=True).distinct()
            blocked_hall_ids = HallBlock.objects.filter(
                start_date__lte=d, end_date__gte=d
            ).values_list("hall_id", flat=True).distinct()
            qs = qs.exclude(id__in=list(booked_hall_ids) + list(blocked_hall_ids))
        except ValueError:
            avail_date = ""
    else:
        avail_date = ""

    return render(request, "hall/hall_list.html", {
        "halls": qs,
        "q": q,
        "category": category,
        "categories": HallCategory.choices,
        "capacity_min": capacity_min,
        "capacity_max": capacity_max,
        "rate_max": rate_max,
        "avail_date": avail_date,
    })


@capability_required("own_bookings")
def dashboard(request):
    role = _user_role(request.user)
    if role == "VENTURES":
        return redirect("reservations:ventures_dashboard")
    if role == "FACILITY":
        return redirect("reservations:facility_dashboard")
    if role == "ADMIN" or getattr(request.user, "is_superuser", False):
        return redirect("reservations:admin_dashboard")
    if role == "STAFF":
        return redirect("hall:staff_dashboard")
    if role == "DEPARTMENT":
        return redirect("hall:department_dashboard")
    if role == "BURSARY":
        return redirect("reservations:bursary_dashboard")
    return _render_applicant_dashboard(request)



def _render_applicant_dashboard(request):
    today = timezone.localdate()
    my_qs = Reservation.objects.select_related("hall").filter(user=request.user)
    upcoming = my_qs.exclude(status__in=["CANCELLED", "REJECTED", "CLOSED"]).filter(booking_date__gte=today).count()
    pending = my_qs.filter(status__in=["PENDING", "SUBMITTED", "PAYMENT_PENDING", "APPROVED_PAYMENT", "UNDER_REVIEW", "FORWARDED", "AVAILABLE"]).count()
    halls_count = Hall.objects.filter(is_active=True, is_archived=False).count()
    unread_notifications = Notification.objects.filter(user=request.user, is_read=False).count()
    bookmarks = HallBookmark.objects.select_related("hall").filter(user=request.user).order_by("-created_at")[:6]
    trend_labels, trend_counts = [], []
    for i in range(5, -1, -1):
        day = today - timedelta(days=i)
        trend_labels.append(day.strftime("%d %b"))
        trend_counts.append(my_qs.filter(booking_date=day).count())
    usage = my_qs.values("hall__name").annotate(total=models.Count("id")).order_by("-total")[:5]
    return render(request, "hall/dashboard.html", {
        "upcoming": upcoming,
        "pending": pending,
        "halls_count": halls_count,
        "unread_notifications": unread_notifications,
        "bookmarks": bookmarks,
        "trend_labels": trend_labels,
        "trend_counts": trend_counts,
        "usage_labels": [u["hall__name"] for u in usage],
        "usage_counts": [u["total"] for u in usage],
        "can_view_reports": _user_role(request.user) in ["ADMIN", "STAFF", "VENTURES", "FACILITY"],
    })


@role_required("STAFF")
def staff_dashboard(request):
    today = timezone.localdate()
    my_qs = Reservation.objects.select_related("hall").filter(user=request.user)
    return render(request, "hall/staff_dashboard.html", {
        "upcoming": my_qs.exclude(status__in=["CANCELLED", "REJECTED", "CLOSED"]).filter(booking_date__gte=today).count(),
        "pending": my_qs.filter(status__in=["PENDING", "SUBMITTED", "PAYMENT_PENDING", "APPROVED_PAYMENT", "UNDER_REVIEW", "FORWARDED", "AVAILABLE"]).count(),
        "halls_count": Hall.objects.filter(is_active=True, is_archived=False).count(),
        "unread_notifications": Notification.objects.filter(user=request.user, is_read=False).count(),
        "can_view_reports": True,
    })


@role_required("DEPARTMENT")
def department_dashboard(request):
    today = timezone.localdate()
    my_qs = Reservation.objects.select_related("hall").filter(user=request.user)
    return render(request, "hall/department_dashboard.html", {
        "upcoming": my_qs.exclude(status__in=["CANCELLED", "REJECTED", "CLOSED"]).filter(booking_date__gte=today).count(),
        "pending": my_qs.filter(status__in=["PENDING", "SUBMITTED", "PAYMENT_PENDING", "APPROVED_PAYMENT", "UNDER_REVIEW", "FORWARDED", "AVAILABLE"]).count(),
        "halls_count": Hall.objects.filter(is_active=True, is_archived=False).count(),
        "unread_notifications": Notification.objects.filter(user=request.user, is_read=False).count(),
        "can_view_reports": True,
    })


def hall_booking_context(request, hall, form):
    bookmarked = (
        request.user.is_authenticated
        and HallBookmark.objects.filter(user=request.user, hall=hall).exists()
    )
    suggested = (
        Hall.objects.filter(is_active=True, is_archived=False)
        .exclude(id=hall.id)
        .filter(Q(faculty=hall.faculty) | Q(category=hall.category))
        .annotate(popularity=models.Count("reservations"))
        .order_by("-popularity", "-capacity")[:6]
    )
    return {
        "hall": hall,
        "form": form,
        "bookmarked": bookmarked,
        "suggested_halls": suggested,
        "hall_images": hall.gallery_images.all(),
        "cover_image": hall.cover_image,
        "hall_rules": hall.rules,
        "hall_terms": hall.terms,
    }


def hall_detail(request, pk):
    hall = get_object_or_404(Hall, pk=pk, is_active=True, is_archived=False)
    form = ReservationCreateForm()
    return render(request, "hall/hall_detail.html", hall_booking_context(request, hall, form))


def hall_block_list(request, hall_id):
    hall = get_object_or_404(Hall, pk=hall_id)
    blocks = HallBlock.objects.filter(hall=hall).values("id", "start_date", "end_date", "reason")
    return JsonResponse(list(blocks), safe=False)


@login_required
def hall_block_add(request, hall_id):
    from users.services import can
    if not can(request.user, "manage_hall_blocks"):
        return HttpResponseForbidden("Not authorized — only Facility and Admin can block halls.")
    hall = get_object_or_404(Hall, pk=hall_id)
    if request.method == "POST":
        form = HallBlockForm(request.POST)
        if form.is_valid():
            block = form.save(commit=False)
            block.hall = hall
            block.created_by = request.user
            block.save()
            create_audit_log(
                user=request.user, action=f"Blocked hall: {hall.name} ({block.start_date}–{block.end_date})",
                model_name="HallBlock", object_repr=str(block), request=request,
            )
            messages.success(request, f"Block added for {hall.name} ({block.start_date} – {block.end_date}).")
        else:
            for error in form.errors.values():
                messages.error(request, error.as_text())
    return redirect("hall:hall_manage")


@login_required
def hall_block_delete(request, hall_id, block_id):
    from users.services import can
    if not can(request.user, "manage_hall_blocks"):
        return HttpResponseForbidden("Not authorized — only Facility and Admin can manage hall blocks.")
    block = get_object_or_404(HallBlock, pk=block_id, hall_id=hall_id)
    if request.method == "POST":
        repr_str = str(block)
        block.delete()
        create_audit_log(
            user=request.user, action=f"Removed hall block", model_name="HallBlock",
            object_repr=repr_str, request=request,
        )
        messages.success(request, "Hall block removed.")
    return redirect("hall:hall_manage")


@login_required
def toggle_bookmark(request, pk):
    hall = get_object_or_404(Hall, pk=pk, is_active=True)
    obj = HallBookmark.objects.filter(user=request.user, hall=hall)
    if obj.exists():
        obj.delete()
        messages.success(request, "Hall removed from bookmarks.")
    else:
        HallBookmark.objects.create(user=request.user, hall=hall)
        messages.success(request, "Hall bookmarked.")
    return redirect("hall:hall_detail", pk=hall.pk)


@login_required
def my_bookmarks(request):
    bookmarks = HallBookmark.objects.select_related("hall").filter(user=request.user).order_by("-created_at")
    return render(request, "hall/bookmarks.html", {"bookmarks": bookmarks})


def faq_page(request):
    faqs = FAQ.objects.filter(is_active=True).order_by("-created_at")
    return render(request, "hall/faq.html", {"faqs": faqs})


def announcements_page(request):
    qs = Announcement.objects.filter(is_published=True).order_by("-created_at")
    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "hall/announcements.html", {"page_obj": page_obj})


def announcement_detail(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk, is_published=True)
    
    session_key = f"viewed_announcement_{pk}"
    if not request.session.get(session_key, False):
        Announcement.objects.filter(pk=pk).update(
            view_count=models.F('view_count') + 1,
            unique_view_count=models.F('unique_view_count') + 1
        )
        request.session[session_key] = True
    else:
        # Throttle total view count inflation for same session
        pass
        
    announcement.refresh_from_db()
    related = Announcement.objects.filter(is_published=True).exclude(pk=pk).order_by("-created_at")[:3]
    
    return render(request, "hall/announcement_detail.html", {
        "announcement": announcement,
        "related": related,
    })


def contact_page(request):
    if request.method == "POST":
        ContactMessage.objects.create(
            name=(request.POST.get("name") or "").strip(),
            email=(request.POST.get("email") or "").strip(),
            subject=(request.POST.get("subject") or "").strip(),
            message=(request.POST.get("message") or "").strip(),
        )
        messages.success(request, "Thanks for contacting LASU Hall Management. We will reply soon.")
        return redirect("hall:contact")
    return render(request, "hall/contact.html")


# ─────────────────────────────────────────────────────────────────────────────
# Hall Management (Admin / Ventures / Facility)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def hall_manage(request):
    """Overview list of all halls for staff management."""
    if not _can_manage_halls(request.user):
        return HttpResponseForbidden("You do not have permission to manage halls.")
    halls = Hall.objects.order_by("faculty", "building", "name")
    return render(request, "hall/hall_manage.html", {
        "halls": halls,
        "user_role": _user_role(request.user),
        "is_admin": _is_admin(request.user),
    })


@login_required
def hall_create(request):
    """Create a new hall. Admin, Facility, and Ventures can create halls."""
    if not _can_manage_halls(request.user):
        return HttpResponseForbidden("You do not have permission to create halls.")

    role = _user_role(request.user)
    FormClass = get_hall_form_for_role(role)
    amenities_all = Amenity.objects.filter(is_active=True)

    if request.method == "POST":
        form = FormClass(request.POST)
        if form.is_valid():
            with transaction.atomic():
                hall = form.save()

                # Sync amenities (Facility and Admin only)
                if role != "VENTURES":
                    selected_amenity_ids = request.POST.getlist("amenities")
                    for aid in selected_amenity_ids:
                        try:
                            HallAmenity.objects.get_or_create(hall=hall, amenity_id=int(aid))
                        except (ValueError, Exception):
                            pass

                # Save gallery images with MIME validation and cover selection
                import filetype
                first_image = True
                for img_file in request.FILES.getlist("images"):
                    file_head = img_file.read(2048)
                    kind = filetype.guess(file_head)
                    mime_type = kind.mime if kind else "application/octet-stream"
                    img_file.seek(0)
                    if mime_type not in ["image/jpeg", "image/png", "image/webp"]:
                        messages.warning(request, f"Skipped '{img_file.name}': only JPEG, PNG and WebP are allowed.")
                        continue
                    HallImage.objects.create(hall=hall, image=img_file, is_cover=first_image, display_order=0)
                    first_image = False

            create_audit_log(
                user=request.user, action=f"Created hall: {hall.name}",
                model_name="Hall", object_repr=str(hall),
                new_value=f"Active: {hall.is_active}, Capacity: {hall.capacity}",
                request=request,
            )
            messages.success(request, f"Hall '{hall.name}' created successfully.")
            return redirect("hall:hall_update", pk=hall.pk)
        # Show detailed errors so we can diagnose the failure
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"Field '{field}': {error}")
        if form.non_field_errors():
            for error in form.non_field_errors():
                messages.error(request, f"Form error: {error}")
    else:
        form = FormClass()

    return render(request, "hall/hall_form.html", {
        "form": form,
        "hall": None,
        "amenities_all": amenities_all,
        "user_role": role,
        "is_admin": _is_admin(request.user),
        "facility_fields": FACILITY_FIELDS,
        "ventures_fields": VENTURES_FIELDS,
        "editable_fields": get_editable_fields_for_role(role),
        "active_tab": request.GET.get("tab", "general"),
    })


@login_required
def hall_update(request, pk):
    """Edit an existing hall with role-based field permissions."""
    hall = get_object_or_404(Hall, pk=pk)
    if not _can_manage_halls(request.user):
        return HttpResponseForbidden("You do not have permission to edit this hall.")

    role = _user_role(request.user)
    FormClass = get_hall_form_for_role(role)
    amenities_all = Amenity.objects.filter(is_active=True)
    current_amenity_ids = set(hall.amenities.values_list("amenity_id", flat=True))
    hall_images = hall.gallery_images.order_by("display_order", "-uploaded_at")

    # Audit: capture old state
    old_repr = (
        f"name={hall.name}, active={hall.is_active}, capacity={hall.capacity}, "
        f"daily_rate={hall.daily_rate}, is_archived={hall.is_archived}"
    )

    # Handle soft actions (deactivate / archive / restore) — not full POST
    if request.method == "POST" and "action" in request.POST:
        action = request.POST["action"]
        if action == "deactivate" and not hall.is_archived:
            hall.is_active = False
            hall.save(update_fields=["is_active"])
            create_audit_log(
                user=request.user, action=f"Deactivated hall: {hall.name}",
                model_name="Hall", object_repr=str(hall),
                old_value=old_repr, new_value=f"is_active=False", request=request,
            )
            messages.success(request, f"Hall '{hall.name}' deactivated.")
            return redirect("hall:hall_manage")
        elif action == "archive" and role in ("FACILITY",):
            # Archive is an operational action — Facility (operational owner) and Admin only.
            # Ventures is the financial owner but does NOT control hall operational status.
            hall.is_active = False
            hall.is_archived = True
            hall.save(update_fields=["is_active", "is_archived"])
            create_audit_log(
                user=request.user, action=f"Archived hall: {hall.name}",
                model_name="Hall", object_repr=str(hall),
                old_value=old_repr, new_value="is_archived=True", request=request,
            )
            messages.success(request, f"Hall '{hall.name}' archived.")
            return redirect("hall:hall_manage")
        elif action == "restore" and role in ("ADMIN",):
            hall.is_active = True
            hall.is_archived = False
            hall.save(update_fields=["is_active", "is_archived"])
            create_audit_log(
                user=request.user, action=f"Restored hall: {hall.name}",
                model_name="Hall", object_repr=str(hall),
                old_value=old_repr, new_value="is_active=True, is_archived=False", request=request,
            )
            messages.success(request, f"Hall '{hall.name}' restored.")
            return redirect("hall:hall_manage")

    if request.method == "POST" and "action" not in request.POST:
        form = FormClass(request.POST, instance=hall)
        if form.is_valid():
            with transaction.atomic():
                hall = form.save()

                # Sync amenities (Facility and Admin only)
                if role != "VENTURES":
                    selected_amenity_ids = set(int(x) for x in request.POST.getlist("amenities") if x.isdigit())
                    HallAmenity.objects.filter(hall=hall).exclude(amenity_id__in=selected_amenity_ids).delete()
                    for aid in selected_amenity_ids - current_amenity_ids:
                        try:
                            HallAmenity.objects.get_or_create(hall=hall, amenity_id=aid)
                        except Exception:
                            pass

                # Upload new gallery images
                import filetype
                existing_count = hall.gallery_images.count()
                for img_file in request.FILES.getlist("images"):
                    file_head = img_file.read(2048)
                    kind = filetype.guess(file_head)
                    mime_type = kind.mime if kind else "application/octet-stream"
                    img_file.seek(0)
                    if mime_type not in ["image/jpeg", "image/png", "image/webp"]:
                        messages.warning(request, f"Skipped '{img_file.name}': only JPEG, PNG and WebP are allowed.")
                        continue
                    # First ever image becomes cover
                    is_first_cover = existing_count == 0 and not hall.gallery_images.filter(is_cover=True).exists()
                    HallImage.objects.create(
                        hall=hall, image=img_file,
                        is_cover=is_first_cover,
                        display_order=hall.gallery_images.count(),
                    )
                    existing_count += 1

            new_repr = (
                f"name={hall.name}, active={hall.is_active}, capacity={hall.capacity}, "
                f"daily_rate={hall.daily_rate}, is_archived={hall.is_archived}"
            )
            create_audit_log(
                user=request.user, action=f"Updated hall: {hall.name}",
                model_name="Hall", object_repr=str(hall),
                old_value=old_repr, new_value=new_repr, request=request,
            )
            messages.success(request, f"Hall '{hall.name}' updated successfully.")
            return redirect("hall:hall_update", pk=hall.pk)
        messages.error(request, "Please correct the errors below.")
    else:
        form = FormClass(instance=hall)

    audit_logs = AuditLog.objects.filter(
        model_name="Hall", object_repr__icontains=hall.name
    ).order_by("-timestamp")[:30]

    return render(request, "hall/hall_form.html", {
        "form": form,
        "hall": hall,
        "amenities_all": amenities_all,
        "current_amenity_ids": current_amenity_ids,
        "hall_images": hall_images,
        "cover_image": hall.cover_image,
        "user_role": role,
        "is_admin": _is_admin(request.user),
        "facility_fields": FACILITY_FIELDS,
        "ventures_fields": VENTURES_FIELDS,
        "editable_fields": get_editable_fields_for_role(role),
        "audit_logs": audit_logs,
        "active_tab": request.GET.get("tab", "general"),
    })


@login_required
def hall_delete(request, pk):
    """Permanent deletion — Admin only. Shows confirmation, then hard-deletes."""
    if not _is_admin(request.user):
        return HttpResponseForbidden("Only Administrators can permanently delete halls.")
    hall = get_object_or_404(Hall, pk=pk)
    if request.method == "POST":
        confirm = request.POST.get("confirm_delete", "").strip()
        if confirm != hall.name:
            messages.error(request, "Confirmation name does not match. Hall was NOT deleted.")
            return redirect("hall:hall_delete", pk=pk)
        hall_name = hall.name
        hall.delete()
        create_audit_log(
            user=request.user, action=f"Permanently deleted hall: {hall_name}",
            model_name="Hall", object_repr=hall_name, request=request,
        )
        messages.success(request, f"Hall '{hall_name}' permanently deleted.")
        return redirect("hall:hall_manage")
    return render(request, "hall/hall_delete_confirm.html", {"hall": hall})


@login_required
def hall_image_delete(request, hall_id, image_id):
    """Delete a single gallery image from a hall. Facility and Admin only."""
    if not _can_manage_hall_operations(request.user):
        return HttpResponseForbidden("Not authorized — only Facility and Admin can manage hall images.")
    img = get_object_or_404(HallImage, pk=image_id, hall_id=hall_id)
    hall = img.hall
    was_cover = img.is_cover
    if request.method == "POST":
        img.delete()
        # If deleted image was cover, auto-promote the first remaining image
        if was_cover:
            next_img = hall.gallery_images.first()
            if next_img:
                next_img.is_cover = True
                next_img.save(update_fields=["is_cover"])
        create_audit_log(
            user=request.user, action=f"Deleted image from hall: {hall.name}",
            model_name="HallImage", object_repr=str(img), request=request,
        )
        messages.success(request, "Image removed.")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"status": "ok"})
        return redirect("hall:hall_update", pk=hall_id)
    return redirect("hall:hall_manage")


@login_required
def hall_image_set_cover(request, hall_id, image_id):
    """Set a gallery image as the hall cover image. Facility and Admin only."""
    if not _can_manage_hall_operations(request.user):
        return JsonResponse({"error": "Not authorized — only Facility and Admin can manage hall images."}, status=403)
    img = get_object_or_404(HallImage, pk=image_id, hall_id=hall_id)
    img.set_as_cover()
    create_audit_log(
        user=request.user, action=f"Set cover image for hall: {img.hall.name}",
        model_name="HallImage", object_repr=str(img), request=request,
    )
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"status": "ok", "cover_id": img.pk})
    messages.success(request, "Cover image updated.")
    return redirect("hall:hall_update", pk=hall_id)


@login_required
def hall_image_reorder(request, hall_id):
    """Reorder gallery images. Accepts JSON: [{id: N, order: M}, ...]. Facility and Admin only."""
    if not _can_manage_hall_operations(request.user):
        return JsonResponse({"error": "Not authorized — only Facility and Admin can manage hall images."}, status=403)
    hall = get_object_or_404(Hall, pk=hall_id)
    try:
        data = json.loads(request.body)
        with transaction.atomic():
            for item in data:
                HallImage.objects.filter(pk=item["id"], hall=hall).update(display_order=item["order"])
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        return JsonResponse({"error": str(e)}, status=400)
    create_audit_log(
        user=request.user, action=f"Reordered images for hall: {hall.name}",
        model_name="HallImage", object_repr=str(hall), request=request,
    )
    return JsonResponse({"status": "ok"})


@login_required
def hall_image_replace(request, hall_id, image_id):
    """Replace a gallery image file while keeping its position and cover status. Facility and Admin only."""
    if not _can_manage_hall_operations(request.user):
        return HttpResponseForbidden("Not authorized — only Facility and Admin can manage hall images.")
    img = get_object_or_404(HallImage, pk=image_id, hall_id=hall_id)
    if request.method == "POST":
        new_file = request.FILES.get("image")
        if not new_file:
            messages.error(request, "No replacement image provided.")
            return redirect("hall:hall_update", pk=hall_id)
        import filetype
        file_head = new_file.read(2048)
        kind = filetype.guess(file_head)
        mime_type = kind.mime if kind else "application/octet-stream"
        new_file.seek(0)
        if mime_type not in ["image/jpeg", "image/png", "image/webp"]:
            messages.error(request, "Only JPEG, PNG, and WebP images are allowed.")
            return redirect("hall:hall_update", pk=hall_id)
        img.image = new_file
        img.save(update_fields=["image"])
        create_audit_log(
            user=request.user, action=f"Replaced image for hall: {img.hall.name}",
            model_name="HallImage", object_repr=str(img), request=request,
        )
        messages.success(request, "Image replaced successfully.")
    return redirect("hall:hall_update", pk=hall_id)


# ─────────────────────────────────────────────────────────────────────────────
# Amenity Management (Admin / Ventures / Facility)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def amenity_manage(request):
    """Amenity management page. Facility and Admin only."""
    if not _can_manage_hall_operations(request.user):
        return HttpResponseForbidden("Not authorized — only Facility and Admin can manage amenities.")
    amenities = Amenity.objects.all()
    quick_icons = [
        ("bi-wifi", "Wi-Fi"), ("bi-projector", "Projector"), ("bi-soundwave", "Sound System"),
        ("bi-thermometer-sun", "Air Conditioning"), ("bi-camera-video", "Camera"), ("bi-pc-display", "Computer"),
        ("bi-lightbulb", "Lighting"), ("bi-water", "Water Supply"), ("bi-plug", "Power Outlets"),
        ("bi-people", "Seating"), ("bi-shield-lock", "Security"), ("bi-car-front", "Parking"),
        ("bi-toilet", "Toilets"), ("bi-wheelchair", "Accessibility"), ("bi-fan", "Ventilation"),
        ("bi-camera", "CCTV"), ("bi-broadcast", "Broadcast"), ("bi-phone", "Intercom"),
        ("bi-display", "Display Screen"), ("bi-fire", "Fire Safety"), ("bi-star", "General"),
    ]
    return render(request, "hall/amenity_manage.html", {"amenities": amenities, "quick_icons": quick_icons})


@login_required
def amenity_create(request):
    """Create or update an amenity. Facility and Admin only."""
    if not _can_manage_hall_operations(request.user):
        return HttpResponseForbidden("Not authorized — only Facility and Admin can manage amenities.")
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        icon = (request.POST.get("icon") or "bi-star").strip()
        is_active = bool(request.POST.get("is_active"))
        pk = request.POST.get("pk")
        if name:
            if pk:
                amenity = get_object_or_404(Amenity, pk=int(pk))
                amenity.name = name
                amenity.icon = icon
                amenity.is_active = is_active
                amenity.save()
                messages.success(request, f"Amenity '{name}' updated.")
            else:
                if not Amenity.objects.filter(name__iexact=name).exists():
                    Amenity.objects.create(name=name, icon=icon, is_active=is_active)
                    messages.success(request, f"Amenity '{name}' created.")
                else:
                    messages.error(request, f"Amenity '{name}' already exists.")
        else:
            messages.error(request, "Name is required.")
    return redirect("hall:amenity_manage")


@login_required
def amenity_delete(request, pk):
    """Delete an amenity. Facility and Admin only."""
    if not _can_manage_hall_operations(request.user):
        return HttpResponseForbidden("Not authorized — only Facility and Admin can manage amenities.")
    amenity = get_object_or_404(Amenity, pk=pk)
    if request.method == "POST":
        name = amenity.name
        amenity.delete()
        messages.success(request, f"Amenity '{name}' deleted.")
    return redirect("hall:amenity_manage")


# ─────────────────────────────────────────────────────────────────────────────
# Communications Dashboard (Admin / Ventures only)
# ─────────────────────────────────────────────────────────────────────────────

def _can_manage_comms(user):
    from users.services import can
    return can(user, "manage_communications")


@login_required
def communications_dashboard(request):
    if not _can_manage_comms(request.user):
        return HttpResponseForbidden("You don't have permission to manage communications.")
    from notifications.models import BroadcastMessage
    broadcasts = BroadcastMessage.objects.select_related("created_by").order_by("-created_at")[:50]
    announcements = Announcement.objects.order_by("-created_at")[:50]
    return render(request, "hall/communications_dashboard.html", {
        "broadcasts": broadcasts,
        "announcements": announcements,
    })


@login_required
def broadcast_create_view(request):
    if not _can_manage_comms(request.user):
        return HttpResponseForbidden("Not authorized.")
    from notifications.models import BroadcastMessage
    from users.models import UserRole
    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        message = (request.POST.get("message") or "").strip()
        target_role = (request.POST.get("target_role") or "").strip()
        attachment = request.FILES.get("attachment")
        if not title or not message:
            messages.error(request, "Title and message are required.")
        else:
            bc = BroadcastMessage.objects.create(
                created_by=request.user, title=title, message=message, target_role=target_role,
            )
            if attachment:
                bc.attachment = attachment
                bc.save(update_fields=["attachment"])
            create_audit_log(
                user=request.user, action=f"Created broadcast: {title}",
                model_name="BroadcastMessage", object_repr=title, request=request,
            )
            messages.success(request, "Broadcast sent successfully.")
            return redirect("hall:communications_dashboard")
    return render(request, "hall/broadcast_form.html", {"user_roles": UserRole.choices})


@login_required
def broadcast_delete_view(request, pk):
    if not _can_manage_comms(request.user):
        return HttpResponseForbidden("Not authorized.")
    from notifications.models import BroadcastMessage
    bc = get_object_or_404(BroadcastMessage, pk=pk)
    if request.method == "POST":
        bc.delete()
        messages.success(request, "Broadcast deleted.")
    return redirect("hall:communications_dashboard")


@login_required
def announcement_create_view(request):
    """Create an announcement. Fixes the CKEditor silent-failure bug by accepting
    both the raw textarea value and the `content_raw` hidden field that JS syncs."""
    if not _can_manage_comms(request.user):
        return HttpResponseForbidden("Not authorized.")

    errors = {}

    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        # Accept content from the CKEditor-synced hidden field OR the textarea directly
        content = (request.POST.get("content_data") or request.POST.get("content") or "").strip()
        is_published = bool(request.POST.get("is_published"))
        attachment = request.FILES.get("attachment")
        image = request.FILES.get("image")

        if not title:
            errors["title"] = "Title is required."
        if not content:
            errors["content"] = "Content is required."

        if not errors:
            ann = Announcement.objects.create(
                title=title,
                content=content,
                is_published=is_published,
                created_by=request.user,
            )
            if attachment:
                ann.attachment = attachment
                ann.save(update_fields=["attachment"])
            if image:
                ann.image = image
                ann.save(update_fields=["image"])

            create_audit_log(
                user=request.user, action=f"Created announcement: {title}",
                model_name="Announcement", object_repr=title,
                new_value=f"published={is_published}", request=request,
            )
            messages.success(request, f"Announcement '{title}' created successfully.")
            return redirect("hall:communications_dashboard")
        else:
            for field, msg in errors.items():
                messages.error(request, msg)

    return render(request, "hall/announcement_form.html", {
        "errors": errors,
        "post_data": request.POST if request.method == "POST" else {},
        "ann": None,
    })


@login_required
def announcement_edit_view(request, pk):
    """Edit an existing announcement."""
    if not _can_manage_comms(request.user):
        return HttpResponseForbidden("Not authorized.")
    ann = get_object_or_404(Announcement, pk=pk)
    errors = {}
    old_title = ann.title

    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        content = (request.POST.get("content_data") or request.POST.get("content") or "").strip()
        is_published = bool(request.POST.get("is_published"))
        attachment = request.FILES.get("attachment")
        image = request.FILES.get("image")

        if not title:
            errors["title"] = "Title is required."
        if not content:
            errors["content"] = "Content is required."

        if not errors:
            old_state = f"title={ann.title}, published={ann.is_published}"
            ann.title = title
            ann.content = content
            ann.is_published = is_published
            ann.save(update_fields=["title", "content", "is_published", "updated_at"])
            if attachment:
                ann.attachment = attachment
                ann.save(update_fields=["attachment"])
            if image:
                ann.image = image
                ann.save(update_fields=["image"])

            create_audit_log(
                user=request.user, action=f"Edited announcement: {title}",
                model_name="Announcement", object_repr=title,
                old_value=old_state, new_value=f"title={title}, published={is_published}",
                request=request,
            )
            messages.success(request, f"Announcement '{title}' updated.")
            return redirect("hall:communications_dashboard")
        else:
            for field, msg in errors.items():
                messages.error(request, msg)

    return render(request, "hall/announcement_form.html", {
        "ann": ann,
        "errors": errors,
        "post_data": request.POST if request.method == "POST" else {},
    })


@login_required
def announcement_delete_view(request, pk):
    if not _can_manage_comms(request.user):
        return HttpResponseForbidden("Not authorized.")
    ann = get_object_or_404(Announcement, pk=pk)
    if request.method == "POST":
        title = ann.title
        ann.delete()
        create_audit_log(
            user=request.user, action=f"Deleted announcement: {title}",
            model_name="Announcement", object_repr=title, request=request,
        )
        messages.success(request, "Announcement deleted.")
    return redirect("hall:communications_dashboard")
