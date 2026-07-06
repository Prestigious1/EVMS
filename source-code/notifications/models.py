from django.conf import settings
from django.db import models


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(max_length=50, blank=True)
    link = models.URLField(max_length=500, blank=True, null=True, help_text="Optional link to action or details")
    priority = models.CharField(max_length=20, default='normal')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user} - {self.title}"


class BroadcastMessage(models.Model):
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=200)
    message = models.TextField()
    attachment = models.FileField(upload_to="broadcasts/attachments/", max_length=500, blank=True, null=True, help_text="Optional file attachment")
    link = models.URLField(max_length=500, blank=True, null=True, help_text="Optional link to action or details")
    target_role = models.CharField(max_length=20, blank=True, help_text="Optional role filter (e.g., STUDENT). Leave blank for all users.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title
