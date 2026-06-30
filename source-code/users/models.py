from django.contrib.auth.models import AbstractUser
from django.db import models


class UserRole(models.TextChoices):
    ADMIN = "ADMIN", "Admin"
    STAFF = "STAFF", "Staff"
    STUDENT = "STUDENT", "Student"
    EXTERNAL = "EXTERNAL", "External"
    DEPARTMENT = "DEPARTMENT", "Department"
    VENTURES = "VENTURES", "Ventures"
    FACILITY = "FACILITY", "Facility"
    BURSARY = "BURSARY", "Bursary"


class User(AbstractUser):
    # Keep username for compatibility with Django admin; enforce unique email too.
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=30, blank=True)
    role = models.CharField(max_length=20, choices=UserRole.choices, default=UserRole.EXTERNAL)
    department = models.CharField(max_length=200, blank=True)
    profile_image = models.ImageField(upload_to="users/profiles/", blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    is_blocked = models.BooleanField(default=False, help_text="Blocked users cannot make reservations.")

    def __str__(self) -> str:
        return self.get_username() or self.email

    def save(self, *args, **kwargs):
        # Automatically assign the ADMIN role if the user is a superuser
        if self.is_superuser and self.role != UserRole.ADMIN:
            self.role = UserRole.ADMIN
        super().save(*args, **kwargs)


class RoleCapability(models.Model):
    role = models.CharField(max_length=20, choices=UserRole.choices)
    capability = models.CharField(max_length=50)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = ("role", "capability")

    def __str__(self) -> str:
        return f"{self.role} - {self.capability}"


from django.conf import settings

class LoginLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="login_logs",
    )
    ip_address = models.GenericIPAddressField()
    user_agent = models.CharField(max_length=255, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        return f"Login: {self.user} at {self.timestamp}"
