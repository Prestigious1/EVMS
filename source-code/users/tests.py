from django.test import TestCase
from django.urls import reverse

from users.models import RoleCapability, User, UserRole


class UserAuthTestCase(TestCase):
    def test_registration_assigns_student_for_lasu_email(self):
        response = self.client.post(
            reverse("users:register"),
            {
                "username": "newstudent",
                "email": "newstudent@lasu.edu.ng",
                "password": "StrongPass123!",
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="newstudent@lasu.edu.ng")
        self.assertEqual(user.role, UserRole.STUDENT)

    def test_registration_assigns_external_for_non_lasu_email(self):
        response = self.client.post(
            reverse("users:register"),
            {
                "username": "external",
                "email": "external@example.com",
                "password": "StrongPass123!",
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="external@example.com")
        self.assertEqual(user.role, UserRole.EXTERNAL)

    def test_login_records_login_log(self):
        user = User.objects.create_user(
            username="tester",
            email="tester@lasu.edu.ng",
            password="testpass123",
            role=UserRole.STUDENT,
        )
        response = self.client.post(
            reverse("users:login"),
            {"email": "tester@lasu.edu.ng", "password": "testpass123"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(user.login_logs.count(), 1)


class RoleCapabilityTestCase(TestCase):
    def test_can_helper(self):
        from users.services import can
        admin = User.objects.create_user(
            username="admin",
            email="admin@lasu.edu.ng",
            password="testpass123",
            role=UserRole.ADMIN,
        )
        staff = User.objects.create_user(
            username="staff",
            email="staff@lasu.edu.ng",
            password="testpass123",
            role=UserRole.STAFF,
        )
        self.assertTrue(can(admin, "manage_halls"))
        self.assertFalse(can(staff, "ventures_workflow"))

        RoleCapability.objects.create(role=UserRole.STAFF, capability="view_reports")
        self.assertTrue(can(staff, "view_reports"))
