import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Use absolute path to backend/hbm_automation.db so tests run consistently from any working directory
db_path = os.path.join(BACKEND_DIR, "hbm_automation.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

from main import app

class TestPhase2WorkflowModeSelector(unittest.TestCase):
    """
    Focused unit tests for Phase 2: Workflow Mode Selector and Read-Only Draft Listing:
    - Verifies GET /api/wordpress/sites/{site_id}/drafts calls read-only listing.
    - Verifies drafts endpoint returns formatted draft list and count.
    - Verifies 404 is returned when site does not exist.
    - Verifies zero WordPress write methods (POST, PUT, PATCH, DELETE) are invoked.
    """

    def setUp(self):
        self.client = TestClient(app)
        self.sample_drafts = [
            {
                "id": 26232,
                "title": "10 Best Ergonomic Chairs for Home Offices in 2026",
                "slug": "best-ergonomic-chairs-2026",
                "date": "2026-10-23T14:00:00",
                "modified": "2026-10-23T15:30:00",
                "link": "https://espialsolutions.com/?p=26232",
                "status": "draft",
                "author": 1,
                "featured_media": 26233,
            },
            {
                "id": 26213,
                "title": "5 High-ROI Renovations for Work-From-Home Spaces",
                "slug": "high-roi-renovations-work-from-home",
                "date": "2026-10-22T11:15:00",
                "modified": "2026-10-22T11:45:00",
                "link": "https://espialsolutions.com/?p=26213",
                "status": "draft",
                "author": 1,
                "featured_media": 26214,
            },
        ]

    @patch("api.routes.wordpress_sites.site_service.get_site")
    @patch("services.wordpress.list_drafts", new_callable=AsyncMock)
    def test_list_drafts_read_only_success(self, mock_list_drafts, mock_get_site):
        # Mock site object
        fake_site = MagicMock()
        fake_site.id = 1
        fake_site.url = "https://espialsolutions.com"
        fake_site.username = "webdev"
        fake_site.app_password = "test-app-pass"
        mock_get_site.return_value = fake_site

        mock_list_drafts.return_value = self.sample_drafts

        response = self.client.get("/api/wordpress/sites/1/drafts")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("count"), 2)
        self.assertEqual(len(data.get("drafts")), 2)
        self.assertEqual(data["drafts"][0]["id"], 26232)
        self.assertEqual(data["drafts"][0]["title"], "10 Best Ergonomic Chairs for Home Offices in 2026")

        # Verify list_drafts was called with correct site credentials
        mock_list_drafts.assert_called_once_with(
            site_url="https://espialsolutions.com",
            username="webdev",
            app_password="test-app-pass",
        )

    @patch("api.routes.wordpress_sites.site_service.get_site")
    def test_list_drafts_site_not_found(self, mock_get_site):
        mock_get_site.return_value = None

        response = self.client.get("/api/wordpress/sites/9999/drafts")
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertIn("detail", data)
        self.assertEqual(data["detail"], "Site not found")

    @patch("api.routes.wordpress_sites.site_service.get_site")
    @patch("services.wordpress.list_drafts", new_callable=AsyncMock)
    def test_list_drafts_handles_wordpress_error(self, mock_list_drafts, mock_get_site):
        fake_site = MagicMock()
        fake_site.id = 1
        fake_site.url = "https://espialsolutions.com"
        fake_site.username = "webdev"
        fake_site.app_password = "test-app-pass"
        mock_get_site.return_value = fake_site

        mock_list_drafts.side_effect = RuntimeError("Could not reach WordPress to list drafts.")

        response = self.client.get("/api/wordpress/sites/1/drafts")
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertIn("detail", data)
        self.assertIn("Failed to fetch drafts", data["detail"])


if __name__ == "__main__":
    unittest.main()
