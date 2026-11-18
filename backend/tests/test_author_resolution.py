import os
import sys
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
db_path = os.path.join(BACKEND_DIR, "hbm_automation.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

from core.config import settings
import services.wordpress as wp_service
import services.article_processor as article_processor


class TestAuthorResolution(unittest.IsolatedAsyncioTestCase):
    """
    Test suite for WordPress author assignment and resolution:
    - Never creates new WordPress users automatically.
    - Reuses the approved existing WordPress user (pratiksha_dev, ID: 4).
    - Preserves requested author display name ('Management Editor') separately.
    """

    def setUp(self):
        self.mock_users = [
            {"id": 4, "username": "pratiksha_dev", "name": "pratiksha_dev", "slug": "pratiksha_dev", "roles": ["administrator"]},
            {"id": 1, "username": "webdev", "name": "webdev", "slug": "webdev", "roles": ["administrator"]},
        ]
        self.auth = ("webdev", "password123")
        self.site_url = "https://espialsolutions.com"

    @patch("services.wordpress._wp_request")
    async def test_management_editor_reuses_approved_user(self, mock_wp_req):
        """
        When Basecamp specifies AUTHOR: Management Editor, the automation must
        reuse the approved user 'pratiksha_dev' (ID: 4) and NEVER send a POST request
        to create a new user.
        """
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = self.mock_users
        mock_wp_req.return_value = mock_resp

        author_id = await wp_service._resolve_author_id("Management Editor", self.auth, self.site_url)

        # Assert correct approved user ID is reused
        self.assertEqual(author_id, 4)

        # Assert only GET request was sent to list users, NEVER a POST request to create users
        self.assertEqual(mock_wp_req.call_count, 1)
        args, kwargs = mock_wp_req.call_args
        method, url = args[0], args[1]
        self.assertEqual(method, "GET")
        self.assertIn("/wp-json/wp/v2/users", url)

        # Confirm no POST was ever attempted
        for call in mock_wp_req.call_args_list:
            called_method = call[0][0]
            self.assertNotEqual(called_method, "POST", "A POST request to create a user was detected!")

    @patch("services.wordpress._wp_request")
    async def test_no_user_creation_even_on_arbitrary_editorial_names(self, mock_wp_req):
        """
        Various editorial bylines ('Technology Editor', 'Legal Editor', 'Marketing Editor')
        must all resolve to approved user pratiksha_dev without sending any POST creation calls.
        """
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = self.mock_users
        mock_wp_req.return_value = mock_resp

        for editorial_author in ["Technology Editor", "Legal Editor", "Marketing Editor", "Home Office Editor"]:
            mock_wp_req.reset_mock()
            author_id = await wp_service._resolve_author_id(editorial_author, self.auth, self.site_url)
            self.assertEqual(author_id, 4)
            for call in mock_wp_req.call_args_list:
                self.assertEqual(call[0][0], "GET")

    @patch("services.wordpress._wp_request")
    async def test_exact_match_existing_user(self, mock_wp_req):
        """
        If author_name matches an existing WordPress user account directly,
        that specific user account's ID must be returned.
        """
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = self.mock_users
        mock_wp_req.return_value = mock_resp

        # Direct match for webdev
        author_id_webdev = await wp_service._resolve_author_id("webdev", self.auth, self.site_url)
        self.assertEqual(author_id_webdev, 1)

        # Direct match for pratiksha_dev
        author_id_pratiksha = await wp_service._resolve_author_id("pratiksha_dev", self.auth, self.site_url)
        self.assertEqual(author_id_pratiksha, 4)

    @patch("services.wordpress._wp_request")
    async def test_fallback_to_authenticated_user_if_default_not_found(self, mock_wp_req):
        """
        If the configured default author is not present in the WordPress users list,
        it should fall back to the authenticated API user (webdev, ID: 1) without creating any user.
        """
        only_webdev = [
            {"id": 1, "username": "webdev", "name": "webdev", "slug": "webdev", "roles": ["administrator"]}
        ]
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = only_webdev
        mock_wp_req.return_value = mock_resp

        with patch.object(settings, "WORDPRESS_DEFAULT_AUTHOR", "non_existent_author"):
            author_id = await wp_service._resolve_author_id("Management Editor", self.auth, self.site_url)
            self.assertEqual(author_id, 1)

    @patch("services.wordpress._wp_request")
    async def test_create_draft_assigns_approved_user_id(self, mock_wp_req):
        """
        When create_draft is called with author_name='Management Editor':
        - post payload['author'] must be set to 4 (pratiksha_dev).
        - No user-creation POST request is sent.
        """
        def wp_side_effect(method, url, **kwargs):
            resp = MagicMock(spec=httpx.Response)
            if method == "GET" and "/wp-json/wp/v2/users" in url:
                resp.status_code = 200
                resp.json.return_value = self.mock_users
                return resp
            elif method == "GET" and "/wp-json/wp/v2/categories" in url:
                resp.status_code = 200
                resp.json.return_value = [{"id": 10, "name": "Management"}]
                return resp
            elif method == "POST" and "/wp-json/wp/v2/posts" in url:
                resp.status_code = 201
                resp.json.return_value = {
                    "id": 99999,
                    "status": "draft",
                    "title": {"rendered": "Test Article"},
                    "author": kwargs.get("json", {}).get("author"),
                    "link": "https://espialsolutions.com/?p=99999",
                }
                return resp
            resp.status_code = 404
            return resp

        mock_wp_req.side_effect = wp_side_effect

        draft_res = await wp_service.create_draft(
            title="Management Best Practices",
            content="<p>Article content about management.</p>",
            metadata={
                "author_name": "Management Editor",
                "category_primary": "Management",
            },
            site_url=self.site_url,
            username="webdev",
            app_password="test_password"
        )

        self.assertEqual(draft_res.get("status"), "success")
        self.assertEqual(draft_res.get("author"), 4)

        # Check post creation payload
        post_calls = [c for c in mock_wp_req.call_args_list if c[0][0] == "POST" and "/posts" in c[0][1]]
        self.assertEqual(len(post_calls), 1)
        post_payload = post_calls[0][1].get("json", {})
        self.assertEqual(post_payload.get("author"), 4)

        # Ensure NO user-creation POST calls were ever made
        user_post_calls = [c for c in mock_wp_req.call_args_list if c[0][0] == "POST" and "/users" in c[0][1]]
        self.assertEqual(len(user_post_calls), 0, "A user-creation POST request was made!")

    def test_qa_checklist_preserves_editorial_author_display_name(self):
        """
        The 28-point QA checklist and destination reporting must preserve the
        editorial author display name ('Management Editor') independently of the
        WordPress user ID (4).
        """
        qa = article_processor._build_qa_checklist(
            article_title="Management Best Practices",
            article_content="<h2>Key Strategy</h2><p>Article content.</p>",
            docx_hyperlinks=[],
            category_info={"primary": "Management"},
            author_name="Management Editor",
            seo_fields={"focus_keyphrase": "Management Best Practices", "seo_title": "Guide", "meta_description": "Meta", "slug": "slug"},
            image_result={"image_bytes": b"dummy" * 1000},
            image_meta={},
            draft_res={"title": "Management Best Practices", "status": "success", "author": 4},
            yoast_res={"status": "PASSED"},
            duplicate_res={"status": "PASSED"},
        )

        author_qa = qa["wordpress"]["author_assigned"]
        self.assertEqual(author_qa["status"], "PASS")
        self.assertEqual(author_qa["detail"], "Management Editor")


if __name__ == "__main__":
    unittest.main()
