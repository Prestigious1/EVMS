"""
Management command: seed_demo_data
====================================
Creates demo users for every EVMS role, sample halls, and reservations
covering all workflow states so that each role's dashboard is populated.

Usage:
    python manage.py seed_demo_data
    python manage.py seed_demo_data --reset   # deletes existing demo data first

Demo Accounts:
    Super Admin     → admin@evms.lasu.ng    / Admin@1234      (username: admin_demo)
    Ventures        → ventures@evms.lasu.ng / Ventures@1234   (username: ventures_demo)
    Facility        → facility@evms.lasu.ng / Facility@1234   (username: facility_demo)
    Staff           → staff@lasu.edu.ng     / Staff@1234      (username: staff_demo)
    Student         → student@lasu.edu.ng   / Student@1234    (username: student_demo)
    External Client → external@gmail.com    / External@1234   (username: external_demo)
"""
from datetime import date, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction


class Command(BaseCommand):
    help = "Seed demo users, halls, and sample reservations for all workflow states."

    DEMO_USERS = [
        {
            "username": "admin_demo",
            "email": "admin@evms.lasu.ng",
            "password": "Admin@1234",
            "role": "ADMIN",
            "first_name": "System",
            "last_name": "Administrator",
            "phone_number": "08012345678",
            "is_staff": True,
            "is_superuser": True,
        },
        {
            "username": "ventures_demo",
            "email": "ventures@evms.lasu.ng",
            "password": "Ventures@1234",
            "role": "VENTURES",
            "first_name": "Chidi",
            "last_name": "Okafor",
            "phone_number": "08023456789",
            "department": "LASU Ventures",
        },
        {
            "username": "facility_demo",
            "email": "facility@evms.lasu.ng",
            "password": "Facility@1234",
            "role": "FACILITY",
            "first_name": "Amaka",
            "last_name": "Nwosu",
            "phone_number": "08034567890",
            "department": "Facility Management",
        },
        {
            "username": "staff_demo",
            "email": "staff@lasu.edu.ng",
            "password": "Staff@1234",
            "role": "STAFF",
            "first_name": "Babatunde",
            "last_name": "Adeyemi",
            "phone_number": "08045678901",
            "department": "Academic Affairs",
        },
        {
            "username": "student_demo",
            "email": "student@lasu.edu.ng",
            "password": "Student@1234",
            "role": "STUDENT",
            "first_name": "Ngozi",
            "last_name": "Eze",
            "phone_number": "08056789012",
            "department": "Computer Science",
        },
        {
            "username": "external_demo",
            "email": "external@gmail.com",
            "password": "External@1234",
            "role": "EXTERNAL",
            "first_name": "Tunde",
            "last_name": "Balogun",
            "phone_number": "08067890123",
            "department": "",
        },
    ]

    DEMO_HALLS = [
        {
            "name": "Great Hall Auditorium",
            "category": "MULTIPURPOSE",
            "capacity": 2000,
            "faculty": "Central Administration",
            "building": "Main Campus",
            "location_description": "Ground floor, Main Campus Centre",
            "description": "LASU's premier event venue, equipped with state-of-the-art audio-visual systems. Suitable for convocations, large conferences and cultural events.",
            "daily_rate": Decimal("250000.00"),
            "extra_hour_charge": Decimal("25000.00"),
            "security_deposit": Decimal("50000.00"),
            "owner_department": "VENTURES",
            "rules": "No open flames. All events must end by 10 PM. Venue must be left in original condition.",
            "terms": "Full payment required 48 hours before event. Cancellations within 24 hours forfeit 50% of deposit.",
        },
        {
            "name": "Faculty of Science Conference Room",
            "category": "CONFERENCE",
            "capacity": 150,
            "faculty": "Faculty of Science",
            "building": "Science Complex Block A",
            "location_description": "First floor, Room SC-101",
            "description": "A modern conference facility with projector, whiteboard and video conferencing setup. Ideal for academic seminars, workshops and departmental meetings.",
            "daily_rate": Decimal("45000.00"),
            "extra_hour_charge": Decimal("8000.00"),
            "security_deposit": Decimal("10000.00"),
            "owner_department": "FACILITY",
            "rules": "No food or drinks. Equipment must be returned after use.",
            "terms": "Booking confirmed only after payment of security deposit.",
        },
        {
            "name": "Engineering Seminar Room 3",
            "category": "SEMINAR",
            "capacity": 80,
            "faculty": "Faculty of Engineering",
            "building": "Engineering Complex",
            "location_description": "Second floor, Room ENG-SR3",
            "description": "Well-equipped seminar room with AC, projector, and tiered seating. Popular for student thesis defences and small workshops.",
            "daily_rate": Decimal("20000.00"),
            "extra_hour_charge": Decimal("4000.00"),
            "security_deposit": Decimal("5000.00"),
            "owner_department": "FACILITY",
            "rules": "Strictly academic use. Maximum 80 persons.",
            "terms": "Bookings must be made at least 3 working days in advance.",
        },
        {
            "name": "LASU Recreation Arena",
            "category": "OUTDOOR",
            "capacity": 5000,
            "faculty": "Student Affairs",
            "building": "Sports Complex",
            "location_description": "Adjacent to the Main Library, Sports Complex",
            "description": "A spacious outdoor arena suitable for sports days, cultural festivals, exhibitions and large outdoor gatherings.",
            "daily_rate": Decimal("180000.00"),
            "extra_hour_charge": Decimal("20000.00"),
            "security_deposit": Decimal("40000.00"),
            "owner_department": "VENTURES",
            "rules": "Tent/canopy erection requires additional permit. No permanent structures.",
            "terms": "Weather-related cancellations may be rescheduled once at no extra cost.",
        },
        {
            "name": "Senate Chamber",
            "category": "CONFERENCE",
            "capacity": 300,
            "faculty": "Central Administration",
            "building": "Senate Building",
            "location_description": "Ground floor, Senate Building",
            "description": "The prestigious Senate Chamber, used for formal academic ceremonies, high-level conferences and special university events.",
            "daily_rate": Decimal("120000.00"),
            "extra_hour_charge": Decimal("15000.00"),
            "security_deposit": Decimal("30000.00"),
            "owner_department": "VENTURES",
            "rules": "Formal attire required. No banners without prior approval.",
            "terms": "Only available for LASU-affiliated events. External bookings subject to Senate approval.",
        },
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all demo data and recreate from scratch.",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("\n=== EVMS Demo Data Seeder ===\n"))

        # Step 1: Seed capabilities first
        self.stdout.write("  [1/6] Seeding role capabilities...")
        from django.core.management import call_command
        call_command("seed_capabilities", verbosity=0)
        self.stdout.write(self.style.SUCCESS("        ✔ Capabilities seeded"))

        # Step 2: Optionally reset demo data
        if options["reset"]:
            self._delete_demo_data()

        # Step 3: Create demo users
        self.stdout.write("  [2/6] Creating demo users...")
        users = self._create_demo_users()

        # Step 4: Create halls
        self.stdout.write("  [3/6] Creating demo halls...")
        halls = self._create_demo_halls()

        # Step 5: Create reservations across all statuses
        self.stdout.write("  [4/6] Creating sample reservations...")
        self._create_sample_reservations(users, halls)

        # Step 6: Create announcements and FAQs
        self.stdout.write("  [5/6] Creating announcements and FAQs...")
        self._create_announcements_and_faqs(users)

        # Step 7: Create amenities
        self.stdout.write("  [6/6] Creating amenities...")
        self._create_amenities(halls)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== Seeding complete! ===\n"))
        self._print_credentials()

    def _delete_demo_data(self):
        from users.models import User
        demo_usernames = [u["username"] for u in self.DEMO_USERS]
        deleted, _ = User.objects.filter(username__in=demo_usernames).delete()
        self.stdout.write(self.style.WARNING(f"  [!] Deleted {deleted} demo records"))

    def _create_demo_users(self):
        from users.models import User
        created_users = {}
        for spec in self.DEMO_USERS:
            username = spec["username"]
            email = spec["email"]
            user = User.objects.filter(email=email).first() or User.objects.filter(username=username).first()
            if user:
                # Update role and username in case it changed
                user.username = username
                user.role = spec["role"]
                user.is_verified = True
                user.save(update_fields=["username", "role", "is_verified"])
                self.stdout.write(f"        ~ {username} already exists, updated role → {spec['role']}")
            else:
                user = User(
                    username=username,
                    email=spec["email"],
                    role=spec["role"],
                    first_name=spec.get("first_name", ""),
                    last_name=spec.get("last_name", ""),
                    phone_number=spec.get("phone_number", ""),
                    department=spec.get("department", ""),
                    is_verified=True,
                    is_staff=spec.get("is_staff", False),
                    is_superuser=spec.get("is_superuser", False),
                )
                user.set_password(spec["password"])
                user.save()
                self.stdout.write(self.style.SUCCESS(f"        + Created {username} ({spec['role']})"))
            created_users[spec["role"]] = user
        # If multiple users share a role (like STUDENT + EXTERNAL both separate), track by username too
        created_users["STUDENT"] = User.objects.get(username="student_demo")
        created_users["EXTERNAL"] = User.objects.get(username="external_demo")
        return created_users

    def _create_demo_halls(self):
        from hall.models import Hall
        halls = []
        for spec in self.DEMO_HALLS:
            hall = Hall.objects.filter(name=spec["name"]).first()
            if not hall:
                hall = Hall.objects.create(
                    name=spec["name"],
                    category=spec["category"],
                    capacity=spec["capacity"],
                    faculty=spec["faculty"],
                    building=spec["building"],
                    location_description=spec.get("location_description", ""),
                    description=spec.get("description", ""),
                    daily_rate=spec["daily_rate"],
                    extra_hour_charge=spec["extra_hour_charge"],
                    security_deposit=spec["security_deposit"],
                    owner_department=spec.get("owner_department", ""),
                    rules=spec.get("rules", ""),
                    terms=spec.get("terms", ""),
                    is_active=True,
                )
                self.stdout.write(self.style.SUCCESS(f"        + Hall: {hall.name}"))
            else:
                self.stdout.write(f"        ~ Hall exists: {hall.name}")
            halls.append(hall)
        return halls

    def _create_amenities(self, halls):
        from hall.models import Amenity, HallAmenity
        amenity_names = [
            "Air Conditioning", "Projector", "Microphone & PA System",
            "WiFi", "Whiteboard", "Tables & Chairs", "Stage",
            "Backstage Room", "Green Room", "Generator Backup",
            "CCTV Security", "Parking Space", "Disabled Access",
            "Video Conferencing", "Lighting Rig",
        ]
        amenities = []
        for name in amenity_names:
            amenity, _ = Amenity.objects.get_or_create(name=name, defaults={"is_active": True})
            amenities.append(amenity)

        import random
        random.seed(42)
        for hall in halls:
            selected = random.sample(amenities, min(6, len(amenities)))
            for amenity in selected:
                HallAmenity.objects.get_or_create(hall=hall, amenity=amenity)
        self.stdout.write(self.style.SUCCESS(f"        + Amenities assigned to {len(halls)} halls"))

    @transaction.atomic
    def _create_sample_reservations(self, users, halls):
        from reservations.models import (
            Reservation, ReservationStatus, ReservationPurpose,
            BookingStatusHistory, BookingLog, ReservationMessage,
            HallInspection, InspectionResult, DamageReport, Penalty,
        )
        from payments.models import Payment, PaymentStatus, PaymentMethod, PaymentProvider

        today = timezone.localdate()
        student = users["STUDENT"]
        external = users["EXTERNAL"]
        ventures = users["VENTURES"]
        facility = users["FACILITY"]
        admin = users["ADMIN"]

        hall_main = halls[0]      # Great Hall
        hall_conf = halls[1]      # Conference Room
        hall_sem = halls[2]       # Seminar Room
        hall_arena = halls[3]     # Recreation Arena
        hall_senate = halls[4]    # Senate Chamber

        # Helper to generate a unique booking reference
        import uuid
        def ref():
            return f"LASU-DEMO-{uuid.uuid4().hex[:8].upper()}"

        def log_transition(reservation, from_s, to_s, actor, notes=""):
            BookingStatusHistory.objects.get_or_create(
                reservation=reservation,
                previous_status=from_s,
                new_status=to_s,
                defaults={"changed_by": actor, "notes": notes},
            )
            BookingLog.objects.create(
                reservation=reservation,
                actor=actor,
                action=f"Status changed: {from_s} → {to_s}",
                details=notes,
            )

        reservations_spec = [
            # ── 1. SUBMITTED ─────────────────────────────────────────────────
            {
                "user": student, "hall": hall_main,
                "event_name": "LASU Tech Summit 2026",
                "purpose": ReservationPurpose.EVENT,
                "attendees_count": 800,
                "booking_date": today + timedelta(days=30),
                "start_time": time(9, 0), "end_time": time(17, 0),
                "status": ReservationStatus.SUBMITTED,
                "notes": "Annual technology summit organized by Computer Science students.",
                "total_cost": Decimal("250000"),
            },
            # ── 2. UNDER_REVIEW ───────────────────────────────────────────────
            {
                "user": external, "hall": hall_senate,
                "event_name": "Nigerian Bar Association Annual Dinner",
                "purpose": ReservationPurpose.EVENT,
                "attendees_count": 250,
                "booking_date": today + timedelta(days=45),
                "start_time": time(18, 0), "end_time": time(23, 0),
                "status": ReservationStatus.UNDER_REVIEW,
                "notes": "Formal black-tie dinner event.",
                "total_cost": Decimal("120000"),
            },
            # ── 3. FORWARDED ──────────────────────────────────────────────────
            {
                "user": student, "hall": hall_arena,
                "event_name": "Faculty of Arts Cultural Festival",
                "purpose": ReservationPurpose.EVENT,
                "attendees_count": 2000,
                "booking_date": today + timedelta(days=20),
                "start_time": time(10, 0), "end_time": time(20, 0),
                "status": ReservationStatus.FORWARDED,
                "notes": "Annual cultural display by all Arts departments.",
                "total_cost": Decimal("180000"),
            },
            # ── 4. AVAILABLE ──────────────────────────────────────────────────
            {
                "user": external, "hall": hall_conf,
                "event_name": "Corporate Strategy Workshop",
                "purpose": ReservationPurpose.WORKSHOP,
                "attendees_count": 100,
                "booking_date": today + timedelta(days=15),
                "start_time": time(8, 0), "end_time": time(16, 0),
                "status": ReservationStatus.AVAILABLE,
                "notes": "Two-day strategy workshop for corporate team.",
                "total_cost": Decimal("45000"),
            },
            # ── 5. APPROVED_PAYMENT ───────────────────────────────────────────
            {
                "user": student, "hall": hall_sem,
                "event_name": "PhD Thesis Defence — Adeyemi O.",
                "purpose": ReservationPurpose.LECTURE,
                "attendees_count": 50,
                "booking_date": today + timedelta(days=10),
                "start_time": time(10, 0), "end_time": time(13, 0),
                "status": ReservationStatus.APPROVED_PAYMENT,
                "notes": "Doctoral thesis defence in Computer Engineering.",
                "total_cost": Decimal("20000"),
            },
            # ── 6. PENDING (Payment Initiated) ────────────────────────────────
            {
                "user": external, "hall": hall_conf,
                "event_name": "NGO Annual General Meeting",
                "purpose": ReservationPurpose.MEETING,
                "attendees_count": 80,
                "booking_date": today + timedelta(days=7),
                "start_time": time(9, 0), "end_time": time(15, 0),
                "status": ReservationStatus.PENDING,
                "notes": "AGM for registered charity organisation.",
                "total_cost": Decimal("45000"),
            },
            # ── 7. PAID ───────────────────────────────────────────────────────
            {
                "user": student, "hall": hall_main,
                "event_name": "Mass Communication Convocation Dinner",
                "purpose": ReservationPurpose.GRADUATION,
                "attendees_count": 600,
                "booking_date": today + timedelta(days=5),
                "start_time": time(18, 0), "end_time": time(22, 0),
                "status": ReservationStatus.PAID,
                "notes": "Annual dinner for graduating Mass Com students.",
                "total_cost": Decimal("250000"),
            },
            # ── 8. CONFIRMED ──────────────────────────────────────────────────
            {
                "user": external, "hall": hall_senate,
                "event_name": "Lagos State Budget Presentation 2026",
                "purpose": ReservationPurpose.MEETING,
                "attendees_count": 280,
                "booking_date": today + timedelta(days=3),
                "start_time": time(10, 0), "end_time": time(14, 0),
                "status": ReservationStatus.CONFIRMED,
                "notes": "Official government budget presentation ceremony.",
                "total_cost": Decimal("120000"),
            },
            # ── 9. COMPLETED ──────────────────────────────────────────────────
            {
                "user": student, "hall": hall_sem,
                "event_name": "Robotics Workshop — Dept. of Electrical Eng.",
                "purpose": ReservationPurpose.WORKSHOP,
                "attendees_count": 60,
                "booking_date": today - timedelta(days=10),
                "start_time": time(9, 0), "end_time": time(17, 0),
                "status": ReservationStatus.COMPLETED,
                "notes": "Hands-on robotics workshop with external trainer.",
                "total_cost": Decimal("20000"),
            },
            # ── 10. INSPECTION_PENDING ────────────────────────────────────────
            {
                "user": external, "hall": hall_arena,
                "event_name": "Inter-University Sports Day 2026",
                "purpose": ReservationPurpose.SPORTS,
                "attendees_count": 3000,
                "booking_date": today - timedelta(days=5),
                "start_time": time(8, 0), "end_time": time(18, 0),
                "status": ReservationStatus.INSPECTION_PENDING,
                "notes": "Annual sports day — multiple universities attending.",
                "total_cost": Decimal("180000"),
            },
            # ── 11. DAMAGE_REPORTED ───────────────────────────────────────────
            {
                "user": external, "hall": hall_conf,
                "event_name": "Product Launch — TechCorp Nigeria",
                "purpose": ReservationPurpose.EXHIBITION,
                "attendees_count": 120,
                "booking_date": today - timedelta(days=15),
                "start_time": time(10, 0), "end_time": time(18, 0),
                "status": ReservationStatus.DAMAGE_REPORTED,
                "notes": "Product launch event — projector and chairs damaged post-event.",
                "total_cost": Decimal("45000"),
            },
            # ── 12. CLOSED ────────────────────────────────────────────────────
            {
                "user": student, "hall": hall_main,
                "event_name": "LASU Annual Convocation 2025",
                "purpose": ReservationPurpose.GRADUATION,
                "attendees_count": 1800,
                "booking_date": today - timedelta(days=60),
                "start_time": time(9, 0), "end_time": time(17, 0),
                "status": ReservationStatus.CLOSED,
                "notes": "Annual convocation ceremony, fully resolved.",
                "total_cost": Decimal("250000"),
            },
        ]

        created_reservations = []
        for spec in reservations_spec:
            booking_ref = ref()
            # Check if a same-name demo reservation exists
            existing = Reservation.objects.filter(
                event_name=spec["event_name"], user=spec["user"]
            ).first()
            if existing:
                self.stdout.write(f"        ~ Reservation exists: {spec['event_name'][:40]}")
                created_reservations.append(existing)
                continue

            r = Reservation.objects.create(
                user=spec["user"],
                hall=spec["hall"],
                event_name=spec["event_name"],
                purpose=spec["purpose"],
                attendees_count=spec["attendees_count"],
                booking_date=spec["booking_date"],
                start_time=spec["start_time"],
                end_time=spec["end_time"],
                status=spec["status"],
                notes=spec.get("notes", ""),
                total_cost=spec.get("total_cost", Decimal("0")),
                booking_reference=booking_ref,
            )
            created_reservations.append(r)
            self.stdout.write(self.style.SUCCESS(
                f"        + [{r.status:20s}] {r.event_name[:40]}"
            ))

            # Add status history transitions based on status
            status_flow = self._status_flow_for(r.status)
            prev = None
            for st in status_flow:
                if prev:
                    actor = ventures if st in ["UNDER_REVIEW", "FORWARDED", "APPROVED_PAYMENT", "CONFIRMED"] else facility
                    log_transition(r, prev, st, actor)
                prev = st

            # Add an internal message from ventures
            ReservationMessage.objects.create(
                reservation=r,
                sender=ventures,
                content=f"Application received. Ref: {r.booking_reference}. Reviewing your submission.",
                is_staff_note=False,
            )

        # ── Extra data for COMPLETED reservation ──────────────────────────────
        completed = next((r for r in created_reservations if r.status == "COMPLETED"), None)
        if completed:
            HallInspection.objects.get_or_create(
                reservation=completed,
                defaults={
                    "inspector": facility,
                    "result": InspectionResult.PASSED,
                    "notes": "Hall returned in good condition. No damage observed.",
                    "inspected_at": timezone.now() - timedelta(days=9),
                },
            )
            Payment.objects.get_or_create(
                reservation=completed,
                defaults={
                    "user": completed.user,
                    "amount": completed.total_cost,
                    "status": PaymentStatus.PAID,
                    "payment_method": PaymentMethod.TRANSFER,
                    "provider": PaymentProvider.PAYSTACK,
                    "transaction_reference": f"TRF-{completed.booking_reference[-8:]}",
                },
            )

        # ── Extra data for DAMAGE_REPORTED reservation ─────────────────────
        damaged = next((r for r in created_reservations if r.status == "DAMAGE_REPORTED"), None)
        if damaged:
            HallInspection.objects.get_or_create(
                reservation=damaged,
                defaults={
                    "inspector": facility,
                    "result": InspectionResult.DAMAGE_REPORTED,
                    "notes": "Two ceiling projectors cracked. 8 chairs with torn fabric. Estimated repair ₦85,000.",
                    "inspected_at": timezone.now() - timedelta(days=14),
                },
            )
            damage_report, _ = DamageReport.objects.get_or_create(
                reservation=damaged,
                defaults={
                    "user": damaged.user,
                    "description": "Ceiling projector damaged (x2). Chair upholstery torn (x8). Estimated cost ₦85,000.",
                    "amount": Decimal("85000"),
                    "is_paid": False,
                    "is_forgiven": False,
                },
            )
            Penalty.objects.get_or_create(
                reservation=damaged,
                title="Hall Damage Penalty",
                defaults={
                    "user": damaged.user,
                    "description": "Penalty for damage to projection equipment and seating during TechCorp Nigeria event.",
                    "amount": Decimal("85000"),
                    "is_paid": False,
                    "is_forgiven": False,
                },
            )

        # ── Extra data for PAID reservation ──────────────────────────────────
        paid_r = next((r for r in created_reservations if r.status == "PAID"), None)
        if paid_r:
            Payment.objects.get_or_create(
                reservation=paid_r,
                defaults={
                    "user": paid_r.user,
                    "amount": paid_r.total_cost,
                    "status": PaymentStatus.PAID,
                    "payment_method": PaymentMethod.CARD,
                    "provider": PaymentProvider.PAYSTACK,
                    "transaction_reference": f"PSTK-{paid_r.booking_reference[-8:]}",
                },
            )

        # ── Extra data for INSPECTION_PENDING reservation ─────────────────────
        inspection_r = next((r for r in created_reservations if r.status == "INSPECTION_PENDING"), None)
        if inspection_r:
            ReservationMessage.objects.get_or_create(
                reservation=inspection_r,
                sender=facility,
                defaults={
                    "content": "Event has concluded. Facility team will inspect the arena within 24 hours.",
                    "is_staff_note": False,
                },
            )

        # ── Extra data for CLOSED reservation ──────────────────────────────
        closed_r = next((r for r in created_reservations if r.status == "CLOSED"), None)
        if closed_r:
            HallInspection.objects.get_or_create(
                reservation=closed_r,
                defaults={
                    "inspector": facility,
                    "result": InspectionResult.PASSED,
                    "notes": "All clear. Hall cleaned and re-set after convocation.",
                    "inspected_at": timezone.now() - timedelta(days=58),
                },
            )
            Payment.objects.get_or_create(
                reservation=closed_r,
                defaults={
                    "user": closed_r.user,
                    "amount": closed_r.total_cost,
                    "status": PaymentStatus.PAID,
                    "payment_method": PaymentMethod.TRANSFER,
                    "provider": PaymentProvider.PAYSTACK,
                    "transaction_reference": f"TRF-{closed_r.booking_reference[-8:]}",
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f"        ✔ {len(created_reservations)} reservations ready"
        ))

    def _status_flow_for(self, final_status):
        """Return the chain of statuses that lead to this final status."""
        flows = {
            "SUBMITTED": ["SUBMITTED"],
            "UNDER_REVIEW": ["SUBMITTED", "UNDER_REVIEW"],
            "FORWARDED": ["SUBMITTED", "UNDER_REVIEW", "FORWARDED"],
            "AVAILABLE": ["SUBMITTED", "UNDER_REVIEW", "FORWARDED", "AVAILABLE"],
            "APPROVED_PAYMENT": ["SUBMITTED", "UNDER_REVIEW", "FORWARDED", "AVAILABLE", "APPROVED_PAYMENT"],
            "PENDING": ["SUBMITTED", "UNDER_REVIEW", "FORWARDED", "AVAILABLE", "APPROVED_PAYMENT", "PENDING"],
            "PAID": ["SUBMITTED", "UNDER_REVIEW", "FORWARDED", "AVAILABLE", "APPROVED_PAYMENT", "PAID"],
            "CONFIRMED": ["SUBMITTED", "UNDER_REVIEW", "FORWARDED", "AVAILABLE", "APPROVED_PAYMENT", "PAID", "CONFIRMED"],
            "COMPLETED": ["SUBMITTED", "UNDER_REVIEW", "FORWARDED", "AVAILABLE", "APPROVED_PAYMENT", "PAID", "CONFIRMED", "COMPLETED"],
            "INSPECTION_PENDING": ["SUBMITTED", "UNDER_REVIEW", "FORWARDED", "AVAILABLE", "APPROVED_PAYMENT", "PAID", "CONFIRMED", "COMPLETED", "INSPECTION_PENDING"],
            "DAMAGE_REPORTED": ["SUBMITTED", "UNDER_REVIEW", "FORWARDED", "AVAILABLE", "APPROVED_PAYMENT", "PAID", "CONFIRMED", "COMPLETED", "INSPECTION_PENDING", "DAMAGE_REPORTED"],
            "CLOSED": ["SUBMITTED", "UNDER_REVIEW", "FORWARDED", "AVAILABLE", "APPROVED_PAYMENT", "PAID", "CONFIRMED", "COMPLETED", "INSPECTION_PENDING", "CLOSED"],
        }
        return flows.get(final_status, [final_status])

    def _create_announcements_and_faqs(self, users):
        from core.models import Announcement, FAQ
        admin = users["ADMIN"]

        announcements = [
            {
                "title": "EVMS System Now Fully Operational",
                "content": "The LASU Electronic Venue Management System is now live. All venue bookings must be made through this portal. Paper-based requests will no longer be accepted from 1 July 2026.",
                "is_published": True,
            },
            {
                "title": "Great Hall Auditorium — Maintenance Notice",
                "content": "The Great Hall Auditorium will undergo routine maintenance from July 1–3, 2026. No bookings will be accepted for these dates. We apologise for any inconvenience.",
                "is_published": True,
            },
            {
                "title": "New: Online Payment Integration Live",
                "content": "Applicants can now pay reservation fees securely online via Paystack. Card and bank transfer options are available. Contact ventures@lasu.edu.ng for payment issues.",
                "is_published": True,
            },
        ]
        for spec in announcements:
            Announcement.objects.get_or_create(
                title=spec["title"],
                defaults={
                    "content": spec["content"],
                    "is_published": spec["is_published"],
                },
            )

        faqs = [
            {
                "question": "How do I book a hall?",
                "answer": "Browse the Halls directory, select your preferred venue, and click 'Book This Hall'. Complete the booking form and submit. Your request will be reviewed by LASU Ventures within 2-3 working days.",
            },
            {
                "question": "What documents do I need to submit?",
                "answer": "You must upload an Authorization Letter and a copy of your ID. For external bookings, a company registration certificate may also be required.",
            },
            {
                "question": "How long does approval take?",
                "answer": "Standard approvals take 3-5 working days. Urgent requests may be expedited by contacting LASU Ventures directly at ventures@lasu.edu.ng.",
            },
            {
                "question": "Can I cancel a booking?",
                "answer": "Yes, you can cancel from your dashboard up until 48 hours before the event. Cancellations within 24 hours may forfeit the security deposit per the hall's terms.",
            },
            {
                "question": "What happens if I damage the hall?",
                "answer": "Facility Management will conduct a post-event inspection. If damage is reported, a damage report and associated penalty will be raised. You must pay any outstanding penalty before making future bookings.",
            },
            {
                "question": "How do I pay for my booking?",
                "answer": "Once LASU Ventures approves your application and sets the total cost, you will receive a payment link via email and in-app notification. Payment is processed securely through Paystack.",
            },
        ]
        for spec in faqs:
            FAQ.objects.get_or_create(
                question=spec["question"],
                defaults={"answer": spec["answer"], "is_active": True},
            )

        self.stdout.write(self.style.SUCCESS(
            f"        ✔ {len(announcements)} announcements, {len(faqs)} FAQs ready"
        ))

    def _print_credentials(self):
        rows = [
            ("Super Admin",       "admin@evms.lasu.ng",    "admin_demo",    "Admin@1234",    "/reservations/admin-dashboard/"),
            ("Ventures Officer",  "ventures@evms.lasu.ng", "ventures_demo", "Ventures@1234", "/reservations/ventures/"),
            ("Facility Manager",  "facility@evms.lasu.ng", "facility_demo", "Facility@1234", "/reservations/facility/"),
            ("Staff",             "staff@lasu.edu.ng",     "staff_demo",    "Staff@1234",    "/staff-dashboard/"),
            ("Student",           "student@lasu.edu.ng",   "student_demo",  "Student@1234",  "/dashboard/"),
            ("External Client",   "external@gmail.com",    "external_demo", "External@1234", "/dashboard/"),
        ]
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("  ┌─────────────────────────────────────────────────────────────────────────────────────┐"))
        self.stdout.write(self.style.MIGRATE_HEADING("  │                         EVMS DEMO CREDENTIALS                                      │"))
        self.stdout.write(self.style.MIGRATE_HEADING("  ├───────────────────┬────────────────────────────┬──────────────┬──────────────────────┤"))
        self.stdout.write(self.style.MIGRATE_HEADING("  │ Role              │ Email                      │ Password     │ Dashboard            │"))
        self.stdout.write(self.style.MIGRATE_HEADING("  ├───────────────────┼────────────────────────────┼──────────────┼──────────────────────┤"))
        for role, email, username, password, dashboard in rows:
            self.stdout.write(
                f"  │ {role:<17s} │ {email:<26s} │ {password:<12s} │ {dashboard:<20s} │"
            )
        self.stdout.write(self.style.MIGRATE_HEADING("  └───────────────────┴────────────────────────────┴──────────────┴──────────────────────┘"))
        self.stdout.write("")
        self.stdout.write(f"  Login URL: http://127.0.0.1:8000/users/login/")
        self.stdout.write(f"  Admin:     http://127.0.0.1:8000/admin/")
        self.stdout.write("")
