import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Use absolute path to backend/hbm_automation.db so tests run consistently from any working directory
db_path = os.path.join(BACKEND_DIR, "hbm_automation.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

import services.wizard_service as wizard_service


class TestWizardService(unittest.TestCase):
    """
    Comprehensive tests for the 9-stage Step-by-Step Create Draft Wizard:
    - Server-side session persistence and refresh/resume capability
    - Stage 6 manual image approval gate
    - Stage 7 draft creation gate (draft status only, espialsolutions.com only)
    - Production write protection (rejects homebusinessmag.com)
    - Idempotency guard (prevents duplicate drafts on retries or concurrent requests)
    - Reset session functionality
    """

    def setUp(self):
        self.project_id = 99999
        self.message_id = 88888
        self.attachment_id = "77777"
        self.session_id = wizard_service._get_session_id(self.project_id, self.message_id, self.attachment_id)
        # Ensure clean state
        wizard_service.reset_session(self.project_id, self.message_id, self.attachment_id)

    def tearDown(self):
        wizard_service.reset_session(self.project_id, self.message_id, self.attachment_id)

    def test_session_init_and_persistence(self):
        session = wizard_service.get_or_create_session(self.project_id, self.message_id, self.attachment_id, site_id=1)
        self.assertEqual(session["session_id"], self.session_id)
        self.assertEqual(session["current_stage"], 1)
        self.assertIn("1", session["stages"])
        self.assertIn("9", session["stages"])

        filepath = wizard_service._get_session_filepath(self.session_id)
        self.assertTrue(os.path.isfile(filepath), f"Session file {filepath} should exist on disk")

    def test_refresh_resumes_exact_stage(self):
        session = wizard_service.get_or_create_session(self.project_id, self.message_id, self.attachment_id, site_id=1)
        session["current_stage"] = 4
        session["stages"]["1"]["status"] = "completed"
        session["stages"]["2"]["status"] = "completed"
        session["stages"]["3"]["status"] = "completed"
        session["shared"]["article_title"] = "Persisted Wizard Article"
        wizard_service.save_session(session)

        # Simulate browser refresh by fetching session again
        resumed = wizard_service.get_or_create_session(self.project_id, self.message_id, self.attachment_id, site_id=1)
        self.assertEqual(resumed["current_stage"], 4)
        self.assertEqual(resumed["shared"]["article_title"], "Persisted Wizard Article")
        self.assertEqual(resumed["stages"]["3"]["status"], "completed")

    @patch("services.site_service.get_site")
    @patch("services.basecamp.get_connection_status")
    @patch("services.basecamp.get_project", new_callable=AsyncMock)
    @patch("services.basecamp.get_message", new_callable=AsyncMock)
    def test_stage_1_safety_and_execution(self, mock_msg, mock_proj, mock_bc_status, mock_site):
        # 1. Test safety check: destination cannot be production
        fake_prod_site = MagicMock()
        fake_prod_site.id = 1
        fake_prod_site.url = "https://homebusinessmag.com"
        mock_site.return_value = fake_prod_site

        session = wizard_service.get_or_create_session(self.project_id, self.message_id, self.attachment_id, site_id=1)
        with self.assertRaises(ValueError) as ctx:
            import asyncio
            asyncio.run(wizard_service.execute_stage_1(session))
        self.assertIn("strictly forbidden", str(ctx.exception))

        # 2. Test valid test site
        fake_test_site = MagicMock()
        fake_test_site.id = 1
        fake_test_site.name = "Test Site"
        fake_test_site.url = "https://espialsolutions.com"
        fake_test_site.username = "webdev"
        fake_test_site.app_password = "app-pass"
        mock_site.return_value = fake_test_site

        mock_bc_status.return_value = {"connected": True}
        mock_proj.return_value = {"id": self.project_id, "name": "HBM Test Project"}
        mock_msg.return_value = {
            "id": self.message_id,
            "subject": "10 Remote Work Productivity Tips",
            "content": "<p>CATEGORY: Business Tips</p><p>AUTHOR: Richard Henderson</p>",
            "attachments": [
                {
                    "id": self.attachment_id,
                    "filename": "Remote_Work_Tips.docx",
                    "url": "https://basecamp.com/download/test.docx",
                }
            ],
        }

        import asyncio
        updated = asyncio.run(wizard_service.execute_stage_1(session))
        self.assertEqual(updated["stages"]["1"]["status"], "completed")
        self.assertEqual(updated["current_stage"], 2)
        self.assertEqual(updated["stages"]["1"]["data"]["attachment_filename"], "Remote_Work_Tips.docx")

    def test_stage_6_approval_gate_pauses_without_approval(self):
        session = wizard_service.get_or_create_session(self.project_id, self.message_id, self.attachment_id, site_id=1)
        session["current_stage"] = 6
        session["shared"]["article_title"] = "Test Article"
        session["shared"]["seo_fields"] = {"focus_keyphrase": "Test Keyphrase"}

        import asyncio
        # Run without approval action
        result = asyncio.run(wizard_service.execute_stage_6(session))
        self.assertEqual(result["stages"]["6"]["status"], "waiting_for_review")
        self.assertFalse(result["stages"]["6"]["data"]["approved"])
        self.assertEqual(result["current_stage"], 6)  # Did NOT advance to 7!

        # Run WITH explicit approval action
        approved_img = {
            "source": "envato",
            "filename": "envato_123.jpg",
            "credit_text": "Photo via envato.com",
            "source_url": "https://elements.envato.com/item/123",
        }
        approved = asyncio.run(
            wizard_service.execute_stage_6(
                session,
                action="approve_image",
                selected_image=approved_img,
            )
        )
        self.assertEqual(approved["stages"]["6"]["status"], "completed")
        self.assertTrue(approved["stages"]["6"]["data"]["approved"])
        self.assertEqual(approved["current_stage"], 7)  # Now advances to 7!
        self.assertEqual(approved["shared"]["approved_image"]["filename"], "envato_123.jpg")

    def test_stage_7_draft_creation_gate_pauses_without_action(self):
        session = wizard_service.get_or_create_session(self.project_id, self.message_id, self.attachment_id, site_id=1)
        session["current_stage"] = 7
        session["shared"]["site_url"] = "https://espialsolutions.com"

        import asyncio
        # Merely calling or navigating to stage 7 must NOT create draft
        result = asyncio.run(wizard_service.execute_stage_7(session))
        self.assertEqual(result["stages"]["7"]["status"], "waiting_for_review")
        self.assertIsNone(session.get("created_post_id"))
        self.assertEqual(result["current_stage"], 7)

    @patch("services.wordpress.upload_media", new_callable=AsyncMock)
    @patch("services.wordpress.create_draft", new_callable=AsyncMock)
    def test_stage_7_creates_draft_on_approved_action(self, mock_create, mock_upload):
        session = wizard_service.get_or_create_session(self.project_id, self.message_id, self.attachment_id, site_id=1)
        session["current_stage"] = 7
        session["shared"]["site_url"] = "https://espialsolutions.com"
        session["shared"]["site_username"] = "webdev"
        session["shared"]["site_app_password"] = "pass"
        session["shared"]["article_title"] = "Productivity Mastery"
        session["shared"]["clean_article_html"] = "<p>Clean article content.</p>"
        session["shared"]["approved_image"] = {
            "source": "envato",
            "filename": "approved.jpg",
            "credit_text": "Photo via envato.com",
            "source_url": "https://elements.envato.com",
            "content_type": "image/jpeg",
        }
        session["shared"]["seo_fields"] = {
            "focus_keyphrase": "Productivity Mastery",
            "seo_title": "Productivity Mastery Guide",
            "slug": "productivity-mastery",
            "meta_description": "Learn practical productivity mastery tips for remote workers and entrepreneurs looking to streamline operations.",
            "excerpt": "Learn practical productivity mastery tips for remote workers and entrepreneurs looking to streamline operations.",
        }

        mock_upload.return_value = {"status": "success", "media_id": 99123, "url": "https://espialsolutions.com/img.jpg"}
        mock_create.return_value = {"status": "success", "post_id": 26999, "edit_url": "https://espialsolutions.com/wp-admin/post.php?post=26999&action=edit"}

        import asyncio
        result = asyncio.run(wizard_service.execute_stage_7(session, action="create_draft"))
        self.assertEqual(result["stages"]["7"]["status"], "completed")
        self.assertEqual(result["created_post_id"], 26999)
        self.assertEqual(result["current_stage"], 8)
        mock_create.assert_called_once()

    @patch("services.wordpress.create_draft", new_callable=AsyncMock)
    def test_stage_7_idempotency_prevents_duplicate_draft(self, mock_create):
        session = wizard_service.get_or_create_session(self.project_id, self.message_id, self.attachment_id, site_id=1)
        session["current_stage"] = 7
        session["created_post_id"] = 26999  # Already created
        session["created_edit_url"] = "https://espialsolutions.com/wp-admin/post.php?post=26999&action=edit"
        session["shared"]["site_url"] = "https://espialsolutions.com"

        import asyncio
        # Retrying or concurrent call to create_draft
        result = asyncio.run(wizard_service.execute_stage_7(session, action="create_draft"))
        self.assertEqual(result["stages"]["7"]["status"], "completed")
        self.assertEqual(result["stages"]["7"]["data"]["post_id"], 26999)
        # MUST NOT have called WordPress create_draft again!
        mock_create.assert_not_called()

    def test_stage_7_production_protection(self):
        session = wizard_service.get_or_create_session(self.project_id, self.message_id, self.attachment_id, site_id=1)
        session["current_stage"] = 7
        session["shared"]["site_url"] = "https://homebusinessmag.com"
        session["shared"]["approved_image"] = {"filename": "img.jpg"}

        import asyncio
        with self.assertRaises(ValueError) as ctx:
            asyncio.run(wizard_service.execute_stage_7(session, action="create_draft"))
        self.assertIn("strictly forbidden", str(ctx.exception))

    def test_wizard_reset(self):
        session = wizard_service.get_or_create_session(self.project_id, self.message_id, self.attachment_id, site_id=1)
        filepath = wizard_service._get_session_filepath(self.session_id)
        self.assertTrue(os.path.isfile(filepath))

        success = wizard_service.reset_session(self.project_id, self.message_id, self.attachment_id)
        self.assertTrue(success)
        self.assertFalse(os.path.isfile(filepath))


class TestWizardAPIRoutes(unittest.TestCase):
    """
    Test FastAPI endpoints for Wizard:
      - GET /api/wizard/session
      - POST /api/wizard/advance
      - POST /api/wizard/reset
    """

    def setUp(self):
        from fastapi.testclient import TestClient
        from main import app
        self.client = TestClient(app)
        self.project_id = 99998
        self.message_id = 88887
        self.attachment_id = "77776"
        wizard_service.reset_session(self.project_id, self.message_id, self.attachment_id)

    def tearDown(self):
        wizard_service.reset_session(self.project_id, self.message_id, self.attachment_id)

    def test_api_get_session(self):
        resp = self.client.get(
            f"/api/wizard/session?project_id={self.project_id}&message_id={self.message_id}&attachment_id={self.attachment_id}&site_id=1"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["current_stage"], 1)
        self.assertIn("stages", data)

    @patch("services.wizard_service.advance_wizard", new_callable=AsyncMock)
    def test_api_advance_stage(self, mock_advance):
        mock_advance.return_value = {
            "session_id": "test",
            "current_stage": 2,
            "stages": {"1": {"status": "completed"}},
        }
        payload = {
            "project_id": self.project_id,
            "message_id": self.message_id,
            "attachment_id": self.attachment_id,
            "site_id": 1,
            "target_stage": 1,
        }
        resp = self.client.post("/api/wizard/advance", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["current_stage"], 2)

    def test_api_reset_session(self):
        # First ensure session exists
        self.client.get(
            f"/api/wizard/session?project_id={self.project_id}&message_id={self.message_id}&attachment_id={self.attachment_id}&site_id=1"
        )
        resp = self.client.post(
            "/api/wizard/reset",
            json={
                "project_id": self.project_id,
                "message_id": self.message_id,
                "attachment_id": self.attachment_id,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["reset"])


if __name__ == "__main__":
    unittest.main()
