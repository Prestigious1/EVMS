from django.contrib import admin
from django.contrib.admin.widgets import AdminTextareaWidget
from django.db import models

from core.models import ActivityLog, Announcement, AuditLog, ContactMessage, FAQ

try:
    from django_ckeditor_5.widgets import CKEditor5Widget
except Exception:  # pragma: no cover
    CKEditor5Widget = AdminTextareaWidget


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "role", "action", "affected_object", "ip_address")
    list_filter = ("role", "timestamp")
    search_fields = ("user__email", "action", "affected_object", "new_value", "previous_value")
    readonly_fields = ("timestamp", "user", "role", "action", "affected_object", "previous_value", "new_value", "ip_address")



@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "model_name", "action")
    list_filter = ("model_name", "timestamp")
    search_fields = ("user__email", "action", "model_name")


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ("question", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("question", "answer")
    formfield_overrides = {
        models.TextField: {"widget": CKEditor5Widget(config_name="extends")},
    }


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("subject", "name", "email", "created_at")
    search_fields = ("name", "email", "subject", "message")
    readonly_fields = ("name", "email", "subject", "message", "created_at")
    formfield_overrides = {
        models.TextField: {"widget": CKEditor5Widget(config_name="extends")},
    }

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # If admin_reply was added/changed, create a Notification for the user
        if change and "admin_reply" in form.changed_data and obj.admin_reply:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            # Try to find a user with the same email
            try:
                user = User.objects.get(email=obj.email)
                from notifications.models import Notification
                Notification.objects.create(
                    user=user,
                    title=f"Reply to: {obj.subject}",
                    message=obj.admin_reply,
                )
            except User.DoesNotExist:
                pass  # No user found with this email, skip notification


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "is_published", "created_at")
    list_filter = ("is_published", "created_at")
    search_fields = ("title", "content")
    formfield_overrides = {
        models.TextField: {"widget": CKEditor5Widget(config_name="extends")},
    }
