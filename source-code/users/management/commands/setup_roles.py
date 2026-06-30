from django.core.management.base import BaseCommand
from users.models import RoleCapability, UserRole

class Command(BaseCommand):
    help = 'Setup default capabilities for each user role based on Chapter 3 requirements'

    def handle(self, *args, **options):
        # Define specific capabilities and access levels for each user role
        # Administrator bypasses capability checks, but we can still add for completeness.
        
        roles_capabilities = {
            UserRole.ADMIN: [
                'manage_halls', 'ventures_workflow', 'facility_workflow', 'view_reports', 'own_bookings'
            ],
            UserRole.VENTURES: [
                'manage_halls', 'ventures_workflow', 'view_reports'
            ],
            UserRole.FACILITY: [
                'manage_halls', 'facility_workflow', 'view_reports'
            ],
            UserRole.STAFF: [
                'view_reports'
            ],
            UserRole.STUDENT: [
                'own_bookings'
            ],
            UserRole.EXTERNAL: [
                'own_bookings'
            ]
        }
        
        created_count = 0
        for role, capabilities in roles_capabilities.items():
            for cap in capabilities:
                obj, created = RoleCapability.objects.get_or_create(role=role, capability=cap)
                if created:
                    created_count += 1
                    
        self.stdout.write(self.style.SUCCESS(f'Successfully set up roles and {created_count} capabilities.'))
