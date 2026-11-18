import unittest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
db_path = os.path.join(BACKEND_DIR, "hbm_automation.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

from main import app

class TestPhase1ArticleSelectionAPI(unittest.TestCase):
    """
    Unit tests for Phase 1 backend message counting and filtering:
    - Verifies message listing returns exact filtered count.
    - Verifies date filtering properly narrows message results.
    - Verifies total count updates dynamically based on query parameters.
    """

    def setUp(self):
        from api.routes.auth import get_current_employee
        from models.employee import Employee
        mock_emp = Employee(id=1, email="admin@espialsolutions.com", full_name="Admin", role="admin")
        app.dependency_overrides[get_current_employee] = lambda: mock_emp
        self.client = TestClient(app)
        self.sample_messages = [
            {
                "id": 101,
                "subject": "5 Corporate Gifts That Leave a Lasting Impression",
                "created_at": "2026-10-12T10:00:00Z",
                "author": "Client A",
                "attachment_count": 1,
            },
            {
                "id": 102,
                "subject": "How to Improve Office Efficiency Without Extra Effort",
                "created_at": "2026-10-12T14:30:00Z",
                "author": "Client B",
                "attachment_count": 1,
            },
            {
                "id": 103,
                "subject": "Running a Property Management Business From Home",
                "created_at": "2026-10-13T09:15:00Z",
                "author": "Client C",
                "attachment_count": 1,
            },
            {
                "id": 104,
                "subject": "5 Essential Strategies for Thriving as a Remote Entrepreneur",
                "created_at": "2026-10-14T11:45:00Z",
                "author": "Client D",
                "attachment_count": 1,
            },
        ]

    def tearDown(self):
        from api.routes.auth import get_current_employee
        app.dependency_overrides.pop(get_current_employee, None)

    @patch("services.basecamp.get_messages", new_callable=AsyncMock)
    def test_list_messages_total_count_without_filter(self, mock_get_messages):
        mock_get_messages.return_value = self.sample_messages

        response = self.client.get("/api/basecamp/projects/12345/messages")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("messages", data)
        self.assertIn("count", data)
        self.assertEqual(data["count"], 4)
        self.assertEqual(len(data["messages"]), 4)

    @patch("services.basecamp.get_messages", new_callable=AsyncMock)
    def test_list_messages_filtered_by_date(self, mock_get_messages):
        mock_get_messages.return_value = self.sample_messages

        response = self.client.get("/api/basecamp/projects/12345/messages?date=2026-10-12")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("messages", data)
        self.assertIn("count", data)
        # Exactly 2 messages on 2026-10-12
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["messages"]), 2)
        self.assertEqual(data["messages"][0]["id"], 101)
        self.assertEqual(data["messages"][1]["id"], 102)

    @patch("services.basecamp.get_messages", new_callable=AsyncMock)
    def test_list_messages_empty_date_filter_result(self, mock_get_messages):
        mock_get_messages.return_value = self.sample_messages

        response = self.client.get("/api/basecamp/projects/12345/messages?date=2026-10-20")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("messages", data)
        self.assertIn("count", data)
        self.assertEqual(data["count"], 0)
        self.assertEqual(len(data["messages"]), 0)


if __name__ == "__main__":
    unittest.main()
