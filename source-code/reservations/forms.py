from django import forms

from reservations.models import DocumentType, Reservation, ReservationPurpose

# ---------------------------------------------------------------------------
# Configurable file upload limits (easy to change without touching code paths)
# ---------------------------------------------------------------------------
ALLOWED_FILE_EXTENSIONS: set[str] = {"pdf", "docx", "png", "jpg", "jpeg"}
MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB

import filetype


class MultipleFileInput(forms.ClearableFileInput):
    """File input that allows multiple files to be selected."""
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """
    A FileField that correctly handles multiple simultaneous file uploads.

    Django's built-in FileField only handles a single file.  This subclass:
      - uses MultipleFileInput so the browser sends multiple files under the
        same field name;
      - overrides clean() to call getlist() on request.FILES instead of get(),
        so all uploaded files are returned as a list;
      - returns [] (not an error) when no files are selected and required=False.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("required", False)
        super().__init__(*args, **kwargs)
        # Ensure the widget supports multiple selection
        if not isinstance(self.widget, MultipleFileInput):
            self.widget = MultipleFileInput(attrs=getattr(self.widget, "attrs", {}))

    def clean(self, data, initial=None):
        # When the form is bound, `data` here is the value from FILES.get(name),
        # which is only the *first* file.  We intentionally bypass this path and
        # let clean_documents() pull the full list via self.files.getlist().
        # Here we just do the "required" guard and return the raw data untouched
        # so that clean_documents() receives it.
        if not data and not initial:
            if self.required:
                raise forms.ValidationError(self.error_messages["required"], code="required")
            return []
        # Return data as-is; the real multi-file processing happens in clean_documents
        return data


class ReservationCreateForm(forms.ModelForm):
    """
    Streamlined booking application form.
    Removed: duration_type, facilities (priced add-ons), coupon_code.
    Cost is now manually assigned by Ventures after submission.
    """

    booking_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    start_time = forms.TimeField(
        widget=forms.TimeInput(format="%H:%M", attrs={"type": "time", "class": "form-control"})
    )
    end_time = forms.TimeField(
        widget=forms.TimeInput(format="%H:%M", attrs={"type": "time", "class": "form-control"})
    )
    documents = MultipleFileField(
        required=False,
        widget=MultipleFileInput(attrs={"class": "form-control", "multiple": True}),
        help_text=(
            f"Upload supporting documents (optional) — "
            f"{', '.join(sorted(ALLOWED_FILE_EXTENSIONS)).upper()}. "
            f"Max {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB each."
        ),
    )
    coupon_code = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter coupon code (optional)"}
        ),
    )

    class Meta:
        model = Reservation
        fields = [
            "event_name",
            "purpose",
            "attendees_count",
            "booking_date",
            "start_time",
            "end_time",
            "notes",
            "coupon_code",
        ]

    purpose = forms.ChoiceField(
        choices=ReservationPurpose.choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["event_name"].widget.attrs.update(
            {"class": "form-control", "placeholder": "e.g., CSC101 Lecture"}
        )
        self.fields["attendees_count"].widget.attrs.update(
            {"class": "form-control", "min": "0"}
        )
        self.fields["notes"].widget.attrs.update(
            {
                "class": "form-control",
                "rows": "3",
                "placeholder": "Any additional notes for the reviewers (optional)",
            }
        )

    def clean_booking_date(self):
        from django.utils import timezone

        booking_date = self.cleaned_data.get("booking_date")
        if booking_date and booking_date < timezone.now().date():
            raise forms.ValidationError("You cannot book a hall for a past date.")
        return booking_date

    def clean_documents(self):
        # Always pull the full list directly from the raw FILES dict so we get
        # every file uploaded under the "documents" key, not just the first one.
        files = self.files.getlist("documents") if self.files else []

        # Strip out empty / falsy entries (browser may send an empty entry when
        # the user leaves the file input blank)
        files = [f for f in files if f]

        if not files:
            # Completely fine — the field is optional
            return []

        cleaned = []
        for f in files:
            # ── Extension check ──────────────────────────────────────────────
            ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
            if ext not in ALLOWED_FILE_EXTENSIONS:
                raise forms.ValidationError(
                    f"Unsupported file type: '{f.name}'. "
                    f"Allowed: {', '.join(sorted(ALLOWED_FILE_EXTENSIONS)).upper()}"
                )

            # ── Size check ───────────────────────────────────────────────────
            if f.size > MAX_FILE_SIZE_BYTES:
                raise forms.ValidationError(
                    f"'{f.name}' is too large "
                    f"(max {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB)."
                )

            # ── MIME type validation (graceful) ──────────────────────────────
            # Only reject if filetype *can* detect the MIME and it clearly
            # doesn't match the declared extension.  If filetype returns None
            # (common for DOCX, which is a ZIP-based format) we trust the
            # extension check above.
            try:
                file_head = f.read(2048)
                kind = filetype.guess(file_head)
                f.seek(0)

                if kind is not None:
                    mime_map = {
                        "pdf":  ["application/pdf"],
                        "docx": [
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            "application/zip",   # some tools report zip for docx
                        ],
                        "png":  ["image/png"],
                        "jpg":  ["image/jpeg"],
                        "jpeg": ["image/jpeg"],
                    }
                    allowed_mimes = mime_map.get(ext, [])
                    if allowed_mimes and kind.mime not in allowed_mimes:
                        raise forms.ValidationError(
                            f"Content of '{f.name}' does not match extension "
                            f"'.{ext}' (detected: {kind.mime})."
                        )
            except forms.ValidationError:
                raise
            except Exception:
                # Never block an upload because of a MIME detection failure
                try:
                    f.seek(0)
                except Exception:
                    pass

            cleaned.append(f)

        return cleaned


# ---------------------------------------------------------------------------
from reservations.models import InternalReservation  # noqa: E402


class InternalReservationForm(forms.ModelForm):
    booking_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    start_time = forms.TimeField(
        widget=forms.TimeInput(format="%H:%M", attrs={"type": "time", "class": "form-control"})
    )
    end_time = forms.TimeField(
        widget=forms.TimeInput(format="%H:%M", attrs={"type": "time", "class": "form-control"})
    )

    class Meta:
        model = InternalReservation
        fields = [
            "hall",
            "requesting_department",
            "event_name",
            "purpose",
            "organizer_name",
            "organizer_phone",
            "attendees_count",
            "booking_date",
            "start_time",
            "end_time",
            "is_recurring",
            "notes",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name not in ["booking_date", "start_time", "end_time", "is_recurring"]:
                field.widget.attrs["class"] = "form-control"
            if field_name == "purpose":
                field.widget.attrs["class"] = "form-select"
            if field_name == "hall":
                field.widget.attrs["class"] = "form-select"
        self.fields["is_recurring"].widget.attrs["class"] = "form-check-input"
        self.fields["notes"].widget.attrs["rows"] = "3"
