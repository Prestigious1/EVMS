from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Reset transactional and workflow data while preserving halls, announcements, and user accounts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Required to actually perform the reset.",
        )

    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError("This command is destructive. Re-run with --confirm to proceed.")

        self.stdout.write(self.style.WARNING("Resetting EVMS project data..."))

        with transaction.atomic():
            self._clear_project_data()

        self.stdout.write(self.style.SUCCESS("Project data reset complete."))

    def _clear_project_data(self):
        preserved_models = {
            "core": {"Announcement"},
            "hall": {"Hall", "HallImage", "Amenity", "HallAmenity"},
            "users": {"User"},
        }

        apps_to_clear = [
            "core",
            "hall",
            "notifications",
            "payments",
            "reservations",
            "users",
        ]

        for app_label in apps_to_clear:
            config = apps.get_app_config(app_label)
            for model in config.get_models():
                if model.__name__ in preserved_models.get(app_label, set()):
                    continue

                if model._meta.proxy:
                    continue

                count = model.objects.count()
                if count:
                    model.objects.all().delete()
                    self.stdout.write(self.style.WARNING(f"Deleted {count} rows from {model._meta.label}"))

        # Remove any remaining session and audit-style records that are not tied to preserved models.
        for app_label in ["admin", "sessions"]:
            try:
                config = apps.get_app_config(app_label)
            except LookupError:
                continue
            for model in config.get_models():
                if model._meta.proxy:
                    continue
                count = model.objects.count()
                if count:
                    model.objects.all().delete()
                    self.stdout.write(self.style.WARNING(f"Deleted {count} rows from {model._meta.label}"))
