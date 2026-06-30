from django.contrib import admin
from django.contrib.admin.widgets import AdminTextareaWidget
from django.db import models

from notifications.models import BroadcastMessage, Notification

try:
    from django_ckeditor_5.widgets import CKEditor5Widget
except Exception:  # pragma: no cover
    CKEditor5Widget = AdminTextareaWidget


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "title", "is_read", "created_at")
    list_filter = ("is_read", "created_at")
    search_fields = ("user__email", "title", "message")
    formfield_overrides = {models.TextField: {"widget": CKEditor5Widget(config_name="extends")}}


@admin.register(BroadcastMessage)
class BroadcastMessageAdmin(admin.ModelAdmin):
    list_display = ("title", "target_role", "created_by", "created_at")
    list_filter = ("target_role", "created_at")
    search_fields = ("title", "message")
    formfield_overrides = {models.TextField: {"widget": CKEditor5Widget(config_name="extends")}}
