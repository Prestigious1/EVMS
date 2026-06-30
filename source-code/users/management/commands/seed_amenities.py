"""
Management command: seed_amenities
====================================
Seeds default hall amenities into the database (idempotent).
Run after first deploy or whenever the amenity catalogue needs refreshing.

    python manage.py seed_amenities
"""

from django.core.management.base import BaseCommand

from hall.models import Amenity


DEFAULT_AMENITIES = [
    # ICT & AV
    {"name": "Wi-Fi",                "icon": "bi-wifi"},
    {"name": "Projector",            "icon": "bi-projector"},
    {"name": "Sound System",         "icon": "bi-soundwave"},
    {"name": "Display Screen",       "icon": "bi-display"},
    {"name": "Computer / Desktop",   "icon": "bi-pc-display"},
    {"name": "Broadcast Equipment",  "icon": "bi-broadcast"},
    {"name": "CCTV Surveillance",    "icon": "bi-camera"},
    {"name": "Intercom / Phone",     "icon": "bi-telephone"},
    # Comfort
    {"name": "Air Conditioning",     "icon": "bi-thermometer-sun"},
    {"name": "Ventilation / Fans",   "icon": "bi-fan"},
    {"name": "Natural Lighting",     "icon": "bi-sun"},
    {"name": "Artificial Lighting",  "icon": "bi-lightbulb"},
    {"name": "Water Supply",         "icon": "bi-droplet"},
    # Facilities
    {"name": "Power Outlets",        "icon": "bi-plug"},
    {"name": "Generator Backup",     "icon": "bi-lightning-charge"},
    {"name": "Seating",              "icon": "bi-people"},
    {"name": "Podium / Lectern",     "icon": "bi-person-raised-hand"},
    {"name": "Stage",                "icon": "bi-collection-play"},
    {"name": "Whiteboard",           "icon": "bi-easel"},
    # Amenities
    {"name": "Toilets / Restrooms",  "icon": "bi-toilet"},
    {"name": "Accessibility Ramp",   "icon": "bi-wheelchair"},
    {"name": "Parking",              "icon": "bi-car-front"},
    {"name": "Security Staff",       "icon": "bi-shield-lock"},
    {"name": "Fire Safety",          "icon": "bi-fire"},
    {"name": "First Aid",            "icon": "bi-bandaid"},
    {"name": "Catering Kitchen",     "icon": "bi-shop"},
    {"name": "Storage Room",         "icon": "bi-box-seam"},
    {"name": "Outdoor Space",        "icon": "bi-tree"},
]


class Command(BaseCommand):
    help = "Seed default amenities for the EVMS hall catalogue (idempotent)."

    def handle(self, *args, **options):
        created = 0
        skipped = 0

        for item in DEFAULT_AMENITIES:
            _, was_created = Amenity.objects.get_or_create(
                name=item["name"],
                defaults={"icon": item["icon"], "is_active": True},
            )
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"  [+] Created: {item['name']}"))
            else:
                skipped += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"seed_amenities complete: {created} created, {skipped} already existed."
            )
        )
