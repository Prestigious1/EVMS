from django.test import TestCase

from hall.models import Hall, HallBlock


class HallManagementTestCase(TestCase):
    def setUp(self):
        self.hall = Hall.objects.create(
            name="Test Hall",
            category="SEMINAR",
            capacity=50,
            faculty="Science",
            building="Lab Block",
            daily_rate=1500,
            owner_department="VENTURES",
            rules="No food inside.",
            terms="Clean up after use.",
        )

    def test_hall_str(self):
        self.assertEqual(str(self.hall), "Test Hall")

    def test_hall_block_api(self):
        from django.urls import reverse
        url = reverse("hall:hall_block_list", kwargs={"hall_id": self.hall.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)


class HallBlockModelTestCase(TestCase):
    def setUp(self):
        self.hall = Hall.objects.create(
            name="Block Hall 2",
            category="LECTURE",
            capacity=200,
            faculty="Arts",
            building="Main",
            daily_rate=1000,
        )

    def test_block_str(self):
        block = HallBlock.objects.create(
            hall=self.hall,
            start_date="2026-08-01",
            end_date="2026-08-03",
        )
        self.assertIn("Block Hall 2", str(block))
