import unittest
from unittest.mock import AsyncMock, patch
import os
import sys

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.article_processor as ap
from models.wordpress_site import WordPressSite


class TestPauseResumeWorkflow(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session_id = "test_p123_m456_a789"
        self.test_session_data = {
            "session_id": self.session_id,
            "project_id": 123,
            "project_name": "Test Project",
            "message_id": 456,
            "attachment_id": "789",
            "site_id": 1,
            "article_title": "Effective Leadership Tactics for Growing Organizations",
            "article_text": "Leadership requires steady focus and communication.",
            "article_html": "<h2>Leadership</h2><p>Leadership requires steady focus and communication.</p>",
            "article_content": "<h2>Leadership</h2><p>Leadership requires steady focus and communication.</p>",
            "category_info": {"primary": "Management", "all": ["Management"]},
            "author_name": "Richard Henderson",
            "image_directive": {},
            "client_instructions_plain": "Use Management category.",
            "client_instructions_html": "<p>Use Management category.</p>",
            "parsed_seo": {},
            "docx_hyperlinks": [],
            "authority_links": [],
            "embedded_images": [],
            "seo_fields": {
                "focus_keyphrase": "Effective Leadership Tactics",
                "seo_title": "Effective Leadership Tactics for Growing Organizations",
                "slug": "effective-leadership-tactics",
                "meta_description": "Learn effective leadership tactics with this comprehensive business guide to optimize operations, empower teams, and drive sustainable growth.",
                "excerpt": "Learn effective leadership tactics with this comprehensive business guide to optimize operations, empower teams, and drive sustainable growth.",
            },
            "ai_result": {
                "title": "Effective Leadership Tactics for Growing Organizations",
                "content": "<h2>Leadership</h2><p>Leadership requires steady focus and communication.</p>",
                "focus_keyphrase": "Effective Leadership Tactics",
                "seo_title": "Effective Leadership Tactics for Growing Organizations",
                "slug": "effective-leadership-tactics",
                "meta_description": "Learn effective leadership tactics with this comprehensive business guide to optimize operations, empower teams, and drive sustainable growth.",
                "excerpt": "Learn effective leadership tactics with this comprehensive business guide to optimize operations, empower teams, and drive sustainable growth.",
                "docx_hyperlinks": [],
                "authority_links": [],
            },
            "duplicate_status_dict": {"status": "PASSED"},
            "unchecked_wp": False,
            "doc_result": {
                "filename": "Leadership_Tactics.docx",
                "character_count": 1250,
            },
            "stages": ["[DOCX] Extracted successfully", "[SEO] Generated metadata"],
        }

    def tearDown(self):
        ap._clear_workflow_session(self.session_id)

    def test_session_persistence_roundtrip(self):
        """Verify workflow session can be saved, loaded, and cleared."""
        ap._save_workflow_session(self.session_id, self.test_session_data)
        loaded = ap._load_workflow_session(self.session_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["article_title"], self.test_session_data["article_title"])
        self.assertEqual(loaded["seo_fields"]["focus_keyphrase"], "Effective Leadership Tactics")

        ap._clear_workflow_session(self.session_id)
        cleared = ap._load_workflow_session(self.session_id)
        self.assertIsNone(cleared)

    @patch("services.site_service.get_site")
    @patch("services.image_service.acquire_featured_image")
    @patch("services.wordpress.upload_media")
    @patch("services.wordpress.create_draft")
    @patch("services.wordpress.verify_draft")
    @patch("services.yoast.analyze")
    @patch("services.report_service.save_report")
    async def test_resume_from_featured_image_approval(
        self,
        mock_save_report,
        mock_yoast_analyze,
        mock_verify_draft,
        mock_create_draft,
        mock_upload_media,
        mock_acquire_image,
        mock_get_site,
    ):
        """Verify resuming from approve_image finishes draft creation and strictly enforces 140-155 meta description."""
        ap._save_workflow_session(self.session_id, self.test_session_data)

        # Mock site
        mock_site = WordPressSite(
            id=1,
            name="Espial Test Site",
            url="https://espialsolutions.com",
            username="webdev",
            app_password="test-password",
            is_default=True,
        )
        mock_get_site.return_value = mock_site

        # Mock image
        mock_acquire_image.return_value = {
            "status": "PASSED",
            "image_bytes": b"mock_jpeg_bytes",
            "content_type": "image/jpeg",
            "filename": "featured-image.jpg",
            "source_url": "https://envato.com/photo/123",
            "source": "envato",
            "provider": "Envato",
            "alt_text": "Effective Leadership Tactics",
            "image_title": "Effective Leadership Tactics",
            "caption": "Photo via Envato",
            "error": None,
        }

        mock_upload_media.return_value = {"status": "success", "media_id": 9988}
        mock_create_draft.return_value = {
            "status": "success",
            "post_id": 26213,
            "edit_url": "https://espialsolutions.com/wp-admin/post.php?post=26213&action=edit",
        }
        mock_verify_draft.return_value = {"status": "PASSED", "verified": True}
        mock_yoast_analyze.return_value = {"status": "PASSED", "data": {"seo": {"results": []}}}
        mock_save_report.return_value = 1

        import base64
        from PIL import Image
        import io
        img = Image.new("RGB", (800, 600), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        fake_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        custom_content = "<h2>Leadership</h2><p>Leadership requires <a href='https://homebusinessmag.com/leadership/'>steady team focus</a> and communication.</p>"
        res = await ap.process(
            project_id=123,
            message_id=456,
            attachment_id="789",
            site_id=1,
            session_id=self.session_id,
            resume_action="approve_image",
            selected_image_data={
                "source": "upload",
                "provider": "Uploaded Image",
                "filename": "hero.jpg",
                "content_type": "image/jpeg",
                "raw_image_base64": fake_b64,
            },
            custom_content=custom_content,
        )

        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["destination"]["post_id"], 26213)
        self.assertIn("wp-admin/post.php?post=26213&action=edit", res["destination"]["edit_url"])
        self.assertIn("steady team focus", res["ai_result"]["content"])

        # Verify meta description length was strictly checked and falls into 140-155
        meta_desc = res["ai_result"]["meta_description"]
        self.assertTrue(140 <= len(meta_desc) <= 155, f"Meta description len {len(meta_desc)} not in 140-155: '{meta_desc}'")

        # Session should be cleaned up after completion
        self.assertIsNone(ap._load_workflow_session(self.session_id))

    @patch("services.site_service.get_site")
    @patch("services.wordpress.upload_media")
    @patch("services.wordpress.create_draft")
    @patch("services.wordpress.verify_draft")
    @patch("services.yoast.analyze")
    @patch("services.report_service.save_report")
    async def test_resume_from_uploaded_image_creates_single_draft(
        self,
        mock_save_report,
        mock_yoast_analyze,
        mock_verify_draft,
        mock_create_draft,
        mock_upload_media,
        mock_get_site,
    ):
        """Verify resuming with user-uploaded image creates exactly one draft on espialsolutions.com."""
        ap._save_workflow_session(self.session_id, self.test_session_data)

        # Mock site
        mock_site = WordPressSite(
            id=1,
            name="Espial Test Site",
            url="https://espialsolutions.com",
            username="webdev",
            app_password="test-password",
            is_default=True,
        )
        mock_get_site.return_value = mock_site

        mock_upload_media.return_value = {"status": "success", "media_id": 9989}
        mock_create_draft.return_value = {
            "status": "success",
            "post_id": 26214,
            "edit_url": "https://espialsolutions.com/wp-admin/post.php?post=26214&action=edit",
        }
        mock_verify_draft.return_value = {"status": "PASSED", "verified": True}
        mock_yoast_analyze.return_value = {"status": "PASSED", "data": {"seo": {"results": []}}}
        mock_save_report.return_value = 1

        import base64
        from PIL import Image
        import io
        img = Image.new("RGB", (800, 600), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        fake_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        uploaded_image_data = {
            "source": "upload",
            "provider": "Custom Upload",
            "filename": "my_uploaded_hero.jpg",
            "content_type": "image/jpeg",
            "raw_image_base64": fake_b64,
            "credit_text": "Image uploaded by user",
        }

        res = await ap.process(
            project_id=123,
            message_id=456,
            attachment_id="789",
            site_id=1,
            session_id=self.session_id,
            resume_action="approve_image",
            selected_image_data=uploaded_image_data,
        )

        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["destination"]["post_id"], 26214)
        self.assertIn("https://espialsolutions.com/wp-admin/post.php?post=26214&action=edit", res["destination"]["edit_url"])
        self.assertEqual(res["destination"]["status"], "draft")

        # Verify create_draft called exactly ONCE
        self.assertEqual(mock_create_draft.call_count, 1)

        # Verify session is cleaned up
        self.assertIsNone(ap._load_workflow_session(self.session_id))

        # Re-running with the same session_id must now fail (no duplicate draft)
        retry_res = await ap.process(
            project_id=123,
            message_id=456,
            attachment_id="789",
            site_id=1,
            session_id=self.session_id,
            resume_action="approve_image",
            selected_image_data=uploaded_image_data,
        )
        self.assertEqual(retry_res["status"], "error")
        self.assertIn("cannot be resumed", retry_res["error"])
        # create_draft count is STILL 1
        self.assertEqual(mock_create_draft.call_count, 1)


if __name__ == "__main__":
    unittest.main()
