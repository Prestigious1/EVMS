from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from users.models import User, RoleCapability, LoginLog


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "LASU Hall System",
            {
                "fields": (
                    "phone_number",
                    "role",
                    "department",
                    "profile_image",
                    "is_verified",
                    "is_blocked",
                )
            },
        ),
    )
    list_display = ("username", "email", "role", "department", "is_verified", "is_blocked", "is_staff", "is_superuser")
    list_filter = ("role", "is_verified", "is_blocked", "is_staff", "is_superuser", "is_active")
    search_fields = ("username", "email", "phone_number", "department")


@admin.register(RoleCapability)
class RoleCapabilityAdmin(admin.ModelAdmin):
    list_display = ("role", "capability", "description")
    list_filter = ("role",)
    search_fields = ("capability", "description")


@admin.register(LoginLog)
class LoginLogAdmin(admin.ModelAdmin):
    list_display = ("user", "ip_address", "timestamp")
    list_filter = ("timestamp",)
    search_fields = ("user__username", "user__email", "ip_address")
    readonly_fields = ("user", "ip_address", "user_agent", "timestamp")
