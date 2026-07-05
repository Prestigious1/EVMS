from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Rich audit trail — records who did what, when, from where, and what changed."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    role = models.CharField(max_length=30, blank=True)
    department = models.CharField(max_length=200, blank=True, help_text="Department of the acting user")
    action = models.CharField(max_length=255)
    model_name = models.CharField(max_length=120)
    object_repr = models.CharField(max_length=255, blank=True)
    affected_module = models.CharField(max_length=100, blank=True, help_text="App/module where action occurred")
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    reason = models.TextField(blank=True, help_text="Reason for the action if provided")
    comments = models.TextField(blank=True, help_text="Additional context or comments")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    browser = models.CharField(max_length=200, blank=True, help_text="Browser used by the actor")
    os_info = models.CharField(max_length=200, blank=True, help_text="Operating system of the actor")
    request_id = models.CharField(max_length=64, blank=True, help_text="Unique ID for the HTTP request")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["user", "timestamp"]),
            models.Index(fields=["model_name", "timestamp"]),
            models.Index(fields=["action", "timestamp"]),
            models.Index(fields=["affected_module", "timestamp"]),
        ]

    def __str__(self) -> str:
        return f"{self.timestamp} | {self.model_name} | {self.action}"


class ActivityLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    role = models.CharField(max_length=50, blank=True)
    action = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    affected_object = models.CharField(max_length=255, blank=True)
    previous_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp} - {self.user} - {self.action}"


class FAQ(models.Model):
    question = models.CharField(max_length=255)
    answer = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.question


class ContactMessage(models.Model):
    name = models.CharField(max_length=120)
    email = models.EmailField()
    subject = models.CharField(max_length=200)
    message = models.TextField()
    admin_reply = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.subject} - {self.email}"


class Announcement(models.Model):
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=50, blank=True, default='General')
    content = models.TextField()
    image = models.ImageField(upload_to="announcements/images/", blank=True, null=True)
    video = models.FileField(upload_to="announcements/videos/", blank=True, null=True)
    attachment = models.FileField(
        upload_to="announcements/attachments/", blank=True, null=True,
        help_text="Optional file attachment"
    )
    is_published = models.BooleanField(default=True)
    view_count = models.PositiveIntegerField(default=0)
    unique_view_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="announcements"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class AcademicPeriod(models.Model):
    """Represents an academic session or semester for report date-range presets."""

    class PeriodType(models.TextChoices):
        SESSION  = "SESSION",  "Academic Session"
        SEMESTER = "SEMESTER", "Semester"

    name       = models.CharField(max_length=100, help_text="e.g. '2025/2026 Session' or 'Second Semester 2025'")
    period_type = models.CharField(max_length=20, choices=PeriodType.choices, default=PeriodType.SESSION)
    start_date = models.DateField()
    end_date   = models.DateField()
    is_current = models.BooleanField(default=False, help_text="Mark the active period for default filter selection")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self) -> str:
        return f"{self.name} ({self.start_date} — {self.end_date})"

    def save(self, *args, **kwargs):
        # Ensure only one current period per type
        if self.is_current:
            AcademicPeriod.objects.filter(
                period_type=self.period_type, is_current=True
            ).exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)
