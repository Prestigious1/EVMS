"""
hall/forms.py
=============
Django ModelForms for Hall CRUD, HallBlock, and Amenity management.
Includes role-based forms (FacilityHallForm, VenturesHallForm, HallForm).

Ownership model (per EVMS spec):
  Facility  — operational owner: manages all physical, availability, policy AND pricing fields.
  Ventures  — financial co-owner: can view/edit pricing fields only.
  Admin     — full access to everything.
"""
from django import forms
from django.core.exceptions import ValidationError

from hall.models import Amenity, Hall, HallBlock, HallCategory


# ── Field groups per role ────────────────────────────────────────────────────

# Fields Facility can manage: full operational ownership including pricing.
# Facility is the primary hall owner; they may set and adjust all financial rates
# in addition to physical/operational attributes.
FACILITY_FIELDS = [
    "name",
    "category",
    "capacity",
    "faculty",
    "building",
    "location_description",
    "description",
    "owner_department",
    "rules",
    "terms",
    "is_active",
    # Pricing — Facility has full pricing authority as operational owner
    "daily_rate",
    "extra_hour_charge",
    "security_deposit",
]

# Fields Ventures can manage (financial co-ownership — pricing adjustment only)
VENTURES_FIELDS = [
    "daily_rate",
    "extra_hour_charge",
    "security_deposit",
]

# Admin can manage everything (FACILITY_FIELDS already includes pricing, so no duplication needed)
ADMIN_FIELDS = list(dict.fromkeys(FACILITY_FIELDS + VENTURES_FIELDS))  # deduplicated


# ── Shared widget definitions ────────────────────────────────────────────────

_COMMON_WIDGETS = {
    "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., Eko Hall"}),
    "category": forms.Select(attrs={"class": "form-select"}),
    "capacity": forms.NumberInput(attrs={"class": "form-control", "min": "0", "placeholder": "Maximum occupancy"}),
    "faculty": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., Faculty of Computing"}),
    "building": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., Block A"}),
    "location_description": forms.TextInput(attrs={
        "class": "form-control", "placeholder": "e.g., Ground Floor, opposite the library"
    }),
    "description": forms.Textarea(attrs={
        "class": "form-control", "rows": 4,
        "placeholder": "Brief description of the hall and its suitability",
    }),
    "daily_rate": forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "0.01", "placeholder": "0.00"}),
    "extra_hour_charge": forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "0.01", "placeholder": "0.00"}),
    "security_deposit": forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "0.01", "placeholder": "0.00"}),
    "owner_department": forms.Select(attrs={"class": "form-select"}),
    "rules": forms.Textarea(attrs={
        "class": "form-control", "rows": 3,
        "placeholder": "Usage rules displayed to applicants before booking",
    }),
    "terms": forms.Textarea(attrs={
        "class": "form-control", "rows": 3,
        "placeholder": "Terms and conditions for booking this hall",
    }),
    "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
}


# ── Base validation mixin ────────────────────────────────────────────────────

class HallValidationMixin:
    def clean_daily_rate(self):
        value = self.cleaned_data.get("daily_rate")
        if value is not None and value < 0:
            raise ValidationError("Daily rate cannot be negative.")
        return value

    def clean_security_deposit(self):
        value = self.cleaned_data.get("security_deposit")
        if value is not None and value < 0:
            raise ValidationError("Security deposit cannot be negative.")
        return value

    def clean_extra_hour_charge(self):
        value = self.cleaned_data.get("extra_hour_charge")
        if value is not None and value < 0:
            raise ValidationError("Extra hour charge cannot be negative.")
        return value

    def clean_capacity(self):
        value = self.cleaned_data.get("capacity")
        if value is not None and value < 0:
            raise ValidationError("Capacity cannot be negative.")
        return value


# ── Role-specific forms ──────────────────────────────────────────────────────

class HallForm(HallValidationMixin, forms.ModelForm):
    """Full Admin form — all fields editable."""

    class Meta:
        model = Hall
        fields = ADMIN_FIELDS
        widgets = _COMMON_WIDGETS


class FacilityHallForm(HallValidationMixin, forms.ModelForm):
    """Facility form — full operational ownership: physical + pricing fields.

    Facility is the operational owner of halls and has authority to set/adjust
    all pricing in addition to physical and operational attributes.
    """

    class Meta:
        model = Hall
        fields = FACILITY_FIELDS
        widgets = _COMMON_WIDGETS


class VenturesHallForm(HallValidationMixin, forms.ModelForm):
    """Ventures form — financial co-ownership: pricing fields only.

    Ventures participates in pricing and financial operations but does not own
    hall operations. Operational/physical fields are not editable by Ventures.
    """

    class Meta:
        model = Hall
        fields = VENTURES_FIELDS
        widgets = _COMMON_WIDGETS


def get_hall_form_for_role(role: str) -> type:
    """Return the appropriate HallForm class based on user role."""
    if role == "VENTURES":
        return VenturesHallForm
    if role == "FACILITY":
        return FacilityHallForm
    return HallForm  # ADMIN and any other privileged role


def get_editable_fields_for_role(role: str) -> list[str]:
    """Return the list of field names this role is allowed to edit."""
    if role == "VENTURES":
        return VENTURES_FIELDS
    if role == "FACILITY":
        return FACILITY_FIELDS
    return ADMIN_FIELDS


# ── Other forms ──────────────────────────────────────────────────────────────

class HallBlockForm(forms.ModelForm):
    """Form for blocking a hall on a date range."""

    class Meta:
        model = HallBlock
        fields = ["start_date", "end_date", "reason"]
        widgets = {
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "end_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "reason": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "e.g., Maintenance, University Event"
            }),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and end < start:
            raise ValidationError("End date must be on or after the start date.")
        return cleaned


class AmenityForm(forms.ModelForm):
    """Form for creating/editing amenities."""

    class Meta:
        model = Amenity
        fields = ["name", "icon", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., Air Conditioning"}),
            "icon": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., bi-thermometer-sun"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
