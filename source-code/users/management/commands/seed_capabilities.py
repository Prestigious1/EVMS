"""
Management command: seed_capabilities
======================================
Idempotently seeds RoleCapability rows for all EVMS roles.

Run once after every deployment or whenever roles change:
    python manage.py seed_capabilities

Capability Matrix (per EVMS specification — Hall Ownership Restructure):
-------------------------------------------------------------------------
ADMIN:
  - Full access to all capabilities

FACILITY (Operational Owner of Halls):
  - Can Manage: Halls, Availability, Blocking, Images, Amenities, Capacity,
                Categories, Internal Reservations, Inspections, Maintenance,
                Readiness, Operational Approval, Occupancy Reports, Pricing
  - Cannot Manage: Payments, Coupons, Revenue, Refunds

VENTURES (Financial Owner of Pricing):
  - Can Manage: Halls (view/create/edit pricing only), Payments, Coupons,
                Discounts, Deposits, Revenue, Financial Approval, Refunds,
                Penalties, Invoices, Financial Reports
  - Cannot Manage: Hall Blocking, Hall Images, Hall Amenities,
                   Hall Maintenance, Operational Availability

BURSARY (Payment Verification Department):
  - Can: Verify/Reject Payments, Verify Damage Payments, View Booking Cases,
         Access Booking Communication, View Documents, Read Reports,
         View Audit History, View Financial Records, View Damage Assessments,
         Generate Verification Reports
  - Cannot: Manage Halls, Manage Coupons, Manage Users, Block Halls,
            Create Reservations (management role only)

DEPARTMENT:
  - Department Reservations, Dashboard, History

STUDENT / EXTERNAL:
  - Self-service bookings only
"""

from django.core.management.base import BaseCommand

from users.models import RoleCapability, UserRole


class Command(BaseCommand):
    help = "Seed default RoleCapability rows for all EVMS roles (idempotent)."

    # Capability matrix — aligned with EVMS specification for strict role separation.
    CAPABILITY_MATRIX: dict[str, list[str]] = {
        UserRole.ADMIN: [
            # Full access
            "own_bookings",
            "ventures_workflow",
            "facility_workflow",
            "bursary_workflow",
            "view_reports",
            "manage_users",
            "manage_halls",
            "manage_amenities",
            "manage_hall_blocks",
            "manage_images",
            "broadcast",
            "manage_payments",
            "manage_coupons",
            "manage_refunds",
            "manage_penalties",
            "view_financial_reports",
            "manage_internal_reservations",
            "manage_inspections",
            "manage_communications",
            # Bursary capabilities for Admin overlap
            "view_payment_queue",
            "verify_payments",
            "reject_payments",
            "verify_damage_payments",
            "review_payment_evidence",
            "view_booking_cases",
            "access_booking_communication",
            "view_booking_documents",
            "view_audit_history",
            "view_financial_records",
            "view_damage_assessments",
            "generate_verification_reports",
        ],
        UserRole.STAFF: [
            # Legacy role — view/assist only
            "own_bookings",
            "view_reports",
            "ventures_workflow",
        ],
        UserRole.STUDENT: [
            "own_bookings",
        ],
        UserRole.EXTERNAL: [
            "own_bookings",
        ],
        UserRole.DEPARTMENT: [
            "own_bookings",
            "view_reports",
            "view_department_reports",
        ],
        UserRole.VENTURES: [
            # Financial capabilities + hall access for pricing management.
            # Ventures can view/create halls and edit pricing, but cannot perform
            # operational actions (blocking, image management, amenity management).
            # Those are gated at the view level via _can_manage_hall_operations().
            "own_bookings",
            "ventures_workflow",
            "manage_halls",       # allows access to hall list/create/edit (pricing only)
            "manage_payments",
            "manage_coupons",
            "manage_refunds",
            "manage_penalties",
            "view_reports",
            "view_financial_reports",
            "broadcast",
            "manage_users",
            "manage_communications",
        ],
        UserRole.FACILITY: [
            # Full operational capabilities including pricing authority.
            # Facility is the operational owner of halls.
            "own_bookings",
            "facility_workflow",
            "manage_halls",
            "manage_amenities",
            "manage_hall_blocks",
            "manage_images",
            "manage_internal_reservations",
            "manage_inspections",
            "view_reports",
            "view_occupancy_reports",
        ],
        UserRole.BURSARY: [
            # Payment verification department — management role.
            # Can verify/reject payment proofs, access booking cases in payment-
            # related statuses, participate in booking communication, and view
            # read-only reports. Cannot manage halls, users, or facility operations.
            "own_bookings",              # Required by @capability_required("own_bookings") on dashboard
            "bursary_workflow",          # Gates bursary dashboard, sidebar, and actions
            "view_payment_queue",        # View pending payment verifications
            "verify_payments",           # Approve/verify booking payment proofs
            "reject_payments",           # Reject booking payment proofs
            "verify_damage_payments",    # Verify damage payment proofs
            "review_payment_evidence",   # Access payment evidence and documents
            "view_booking_cases",        # View booking case records
            "access_booking_communication",  # Participate in booking communication threads
            "view_booking_documents",    # View documents attached to bookings
            "view_reports",              # Read-only access to reports dashboard
            "view_audit_history",        # View bursary-scoped audit log
            "view_financial_records",    # Access financial records within cases
            "view_damage_assessments",   # View damage assessment data
            "generate_verification_reports",  # Generate bursary-specific reports
        ],
    }

    def handle(self, *args, **options):
        created_count = 0
        skipped_count = 0
        removed_count = 0

        # Remove any stale capabilities that are no longer in the matrix
        all_valid = {
            (role, cap)
            for role, caps in self.CAPABILITY_MATRIX.items()
            for cap in caps
        }

        for obj in RoleCapability.objects.all():
            if (obj.role, obj.capability) not in all_valid:
                self.stdout.write(
                    self.style.WARNING(f"  [-] Removing stale: {obj.role:12s} → {obj.capability}")
                )
                obj.delete()
                removed_count += 1

        # Seed all capabilities from the matrix
        for role, capabilities in self.CAPABILITY_MATRIX.items():
            for capability in capabilities:
                obj, created = RoleCapability.objects.get_or_create(
                    role=role,
                    capability=capability,
                    defaults={"description": f"Default capability for {role}"},
                )
                if created:
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"  [+] {role:12s} → {capability}")
                    )
                else:
                    skipped_count += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"seed_capabilities complete: {created_count} created, "
                f"{skipped_count} already existed, {removed_count} stale removed."
            )
        )
