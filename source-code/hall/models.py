from django.conf import settings
from django.db import models, transaction


def hall_image_path(instance, filename):
    return f"halls/{instance.hall_id}/{filename}"


class HallCategory(models.TextChoices):
    LECTURE = "LECTURE", "Lecture Hall"
    CONFERENCE = "CONFERENCE", "Conference Hall"
    SEMINAR = "SEMINAR", "Seminar Room"
    SOCIAL_EVENT = "SOCIAL_EVENT", "Social Event Hall"
    MULTIPURPOSE = "MULTIPURPOSE", "Multipurpose Hall"
    OUTDOOR = "OUTDOOR", "Outdoor Space"


class DepartmentChoices(models.TextChoices):
    VENTURES = "VENTURES", "Ventures"
    FACILITY = "FACILITY", "Facility"


class Hall(models.Model):
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=30, choices=HallCategory.choices, default=HallCategory.MULTIPURPOSE)
    capacity = models.PositiveIntegerField(default=0)

    faculty = models.CharField(max_length=200)
    building = models.CharField(max_length=200)
    location_description = models.CharField(max_length=255, blank=True)

    description = models.TextField(blank=True)

    daily_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    extra_hour_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    security_deposit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    is_archived = models.BooleanField(
        default=False,
        help_text="Archived halls are hidden from public listing and require admin to restore."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    owner_department = models.CharField(
        max_length=30,
        choices=DepartmentChoices.choices,
        blank=True,
        help_text="Department responsible for operational management",
    )
    rules = models.TextField(blank=True, help_text="Usage rules and terms displayed to applicants before booking")
    terms = models.TextField(blank=True, help_text="Terms and conditions for booking this hall")

    class Meta:
        ordering = ["faculty", "building", "name"]

    def __str__(self) -> str:
        return self.name

    @property
    def cover_image(self):
        """Returns the designated cover image, falling back to the first gallery image."""
        img = self.gallery_images.filter(is_cover=True).first()
        if img:
            return img
        return self.gallery_images.first()

    @property
    def status_label(self):
        if self.is_archived:
            return "Archived"
        if not self.is_active:
            return "Inactive"
        return "Active"

    @property
    def status_badge_class(self):
        if self.is_archived:
            return "text-bg-secondary"
        if not self.is_active:
            return "text-bg-warning"
        return "text-bg-success"


class HallImage(models.Model):
    hall = models.ForeignKey(Hall, on_delete=models.CASCADE, related_name="gallery_images")
    image = models.ImageField(upload_to=hall_image_path)
    is_cover = models.BooleanField(
        default=False,
        help_text="Only one image per hall can be the cover. Setting this removes cover from all others."
    )
    display_order = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_order", "-uploaded_at"]

    def __str__(self) -> str:
        cover_marker = " [COVER]" if self.is_cover else ""
        return f"Image for {self.hall.name}{cover_marker}"

    def set_as_cover(self):
        """Atomically designate this image as the hall cover, clearing others."""
        with transaction.atomic():
            HallImage.objects.select_for_update().filter(
                hall=self.hall, is_cover=True
            ).exclude(pk=self.pk).update(is_cover=False)
            self.is_cover = True
            self.save(update_fields=["is_cover"])

    def save(self, *args, **kwargs):
        # Enforce single cover constraint on save
        if self.is_cover:
            with transaction.atomic():
                HallImage.objects.filter(
                    hall_id=self.hall_id, is_cover=True
                ).exclude(pk=self.pk).update(is_cover=False)
        super().save(*args, **kwargs)


class Amenity(models.Model):
    name = models.CharField(max_length=150, unique=True)
    icon = models.CharField(
        max_length=100, blank=True, default="bi-star",
        help_text="Bootstrap icon class, e.g. bi-wifi, bi-projector, bi-soundwave"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Amenities"

    def __str__(self) -> str:
        return self.name


class HallAmenity(models.Model):
    hall = models.ForeignKey(Hall, on_delete=models.CASCADE, related_name="amenities")
    amenity = models.ForeignKey(Amenity, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("hall", "amenity")
        verbose_name_plural = "Hall Amenities"

    def __str__(self) -> str:
        return f"{self.hall.name} - {self.amenity.name}"


class HallBookmark(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    hall = models.ForeignKey(Hall, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "hall")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user} bookmarked {self.hall}"


class HallBlock(models.Model):
    hall = models.ForeignKey(Hall, on_delete=models.CASCADE, related_name="blocks")
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]

    def clean(self) -> None:
        if self.end_date < self.start_date:
            from django.core.exceptions import ValidationError
            raise ValidationError("end_date must be greater than or equal to start_date.")

    def __str__(self) -> str:
        return f"Block for {self.hall.name}: {self.start_date} - {self.end_date}"
