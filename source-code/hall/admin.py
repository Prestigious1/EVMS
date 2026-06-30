from django.contrib import admin
from django.contrib.admin.widgets import AdminTextareaWidget
from django.db import models

from hall.models import Amenity, Hall, HallAmenity, HallBookmark, HallImage, HallBlock

try:
    from django_ckeditor_5.widgets import CKEditor5Widget
except Exception:  # pragma: no cover - safe fallback
    CKEditor5Widget = AdminTextareaWidget


class HallImageInline(admin.TabularInline):
    model = HallImage
    extra = 1


class HallAmenityInline(admin.TabularInline):
    model = HallAmenity
    extra = 1
    autocomplete_fields = ["amenity"]


@admin.register(Hall)
class HallAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "capacity", "faculty", "building", "daily_rate", "is_active")
    list_filter = ("category", "faculty", "is_active", "owner_department")
    search_fields = ("name", "faculty", "building", "location_description")
    fieldsets = (
        (None, {"fields": ("name", "category", "capacity", "faculty", "building", "location_description")}),
        ("Content", {"fields": ("description",)}),
        ("Management", {"fields": ("owner_department",)}),
        ("Terms", {"fields": ("rules", "terms")}),
        ("Pricing & Status", {"fields": ("daily_rate", "extra_hour_charge", "security_deposit", "is_active")}),
    )
    inlines = [HallImageInline, HallAmenityInline]
    formfield_overrides = {
        models.TextField: {"widget": CKEditor5Widget(config_name="extends")},
    }


@admin.register(Amenity)
class AmenityAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(HallBookmark)
class HallBookmarkAdmin(admin.ModelAdmin):
    list_display = ("user", "hall", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__email", "hall__name")


@admin.register(HallBlock)
class HallBlockAdmin(admin.ModelAdmin):
    list_display = ("hall", "start_date", "end_date", "reason", "created_by", "created_at")
    list_filter = ("start_date", "end_date", "created_by")
    search_fields = ("hall__name", "reason")
