"""
Tests for the Featured Image Approval Gate session persistence subsystem.

Covers:
  - Directory auto-creation (Windows mkdir)
  - JSON save / load / clear roundtrip
  - Atomic write (tmp → final rename) on Windows
  - Corrupt / truncated session handling
  - Missing required fields validation
  - Session ID determinism and uniqueness
  - Save failure → returns False (not silently ignored)
  - Resume path receives clear error when session missing / corrupt
  - _ensure_sessions_dir re-creates directory if removed mid-run
  - Stale .tmp file cleanup on next save
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# ── path setup ─────────────────────────────────────────────────────────────
import sys
BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))


class TestSessionPersistence(unittest.TestCase):
    """Tests that use a real temporary directory (no mocking of filesystem)."""

    def setUp(self):
        # Fresh isolated temp dir for every test
        self.tmp_dir = tempfile.mkdtemp(prefix="hbm_session_test_")
        # Patch the SESSIONS_DIR used by the module
        import services.article_processor as proc
        self._proc = proc
        self._orig_sessions_dir = proc.SESSIONS_DIR
        proc.SESSIONS_DIR = self.tmp_dir

    def tearDown(self):
        self._proc.SESSIONS_DIR = self._orig_sessions_dir
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # ── helpers ────────────────────────────────────────────────────────────

    def _minimal_payload(self, session_id="test_sess_001"):
        """Return a session payload that satisfies all required fields."""
        return {
            "session_id": session_id,
            "project_id": 1,
            "message_id": 2,
            "attachment_id": "att1",
            "site_id": 3,
            "article_title": "Test Article",
            "article_text": "body text",
            "article_html": "<p>body</p>",
            "article_content": "<p>body</p>",
            "category_info": {"primary": "Business"},
            "author_name": "Richard Henderson",
            "image_directive": {},
            "client_instructions_plain": "",
            "client_instructions_html": "",
            "parsed_seo": {},
            "docx_hyperlinks": [],
            "authority_links": [],
            "embedded_images": [],
            "seo_fields": {
                "focus_keyphrase": "test article tips",
                "meta_description": "A " * 70 + "meta description.",  # >140 chars
                "slug": "test-article",
            },
            "ai_result": {"title": "Test Article", "content": "<p>body</p>"},
            "duplicate_status_dict": {"status": "no_duplicate"},
            "unchecked_wp": False,
            "doc_result": {"filename": "test.docx", "character_count": 500},
            "stages": ["Step 1 done.", "Step 2 done."],
        }

    # ── directory creation ─────────────────────────────────────────────────

    def test_ensure_sessions_dir_creates_missing_directory(self):
        """_ensure_sessions_dir must create the directory if removed."""
        proc = self._proc
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        self.assertFalse(os.path.isdir(self.tmp_dir))
        result = proc._ensure_sessions_dir()
        self.assertTrue(result, "_ensure_sessions_dir should return True on success")
        self.assertTrue(os.path.isdir(self.tmp_dir), "Directory must exist after _ensure_sessions_dir")

    def test_ensure_sessions_dir_nested_parents(self):
        """_ensure_sessions_dir must create nested parent directories (parents=True)."""
        proc = self._proc
        nested = os.path.join(self.tmp_dir, "a", "b", "c", "sessions")
        orig = proc.SESSIONS_DIR
        proc.SESSIONS_DIR = nested
        try:
            self.assertFalse(os.path.isdir(nested))
            result = proc._ensure_sessions_dir()
            self.assertTrue(result)
            self.assertTrue(os.path.isdir(nested))
        finally:
            proc.SESSIONS_DIR = orig

    def test_ensure_sessions_dir_idempotent(self):
        """Calling _ensure_sessions_dir twice must not raise."""
        proc = self._proc
        self.assertTrue(proc._ensure_sessions_dir())
        self.assertTrue(proc._ensure_sessions_dir())

    # ── save / load / clear roundtrip ──────────────────────────────────────

    def test_save_load_roundtrip(self):
        proc = self._proc
        payload = self._minimal_payload()
        session_id = "roundtrip_001"
        payload["session_id"] = session_id
        saved = proc._save_workflow_session(session_id, payload)
        self.assertTrue(saved, "_save_workflow_session must return True on success")
        loaded = proc._load_workflow_session(session_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["session_id"], session_id)
        self.assertEqual(loaded["project_id"], 1)
        self.assertEqual(loaded["article_title"], "Test Article")
        self.assertListEqual(loaded["stages"], ["Step 1 done.", "Step 2 done."])

    def test_load_returns_none_when_not_exists(self):
        proc = self._proc
        result = proc._load_workflow_session("nonexistent_session")
        self.assertIsNone(result)

    def test_clear_removes_session_file(self):
        proc = self._proc
        sid = "clear_test_001"
        proc._save_workflow_session(sid, self._minimal_payload(sid))
        path = os.path.join(self.tmp_dir, f"{sid}.json")
        self.assertTrue(os.path.isfile(path))
        proc._clear_workflow_session(sid)
        self.assertFalse(os.path.isfile(path), "clear must remove the .json file")

    def test_clear_removes_stale_tmp_file(self):
        """_clear_workflow_session must also remove any leftover .tmp file."""
        proc = self._proc
        sid = "clear_tmp_test_001"
        tmp_path = os.path.join(self.tmp_dir, f"{sid}.json.tmp")
        with open(tmp_path, "w") as f:
            f.write("stale tmp content")
        proc._clear_workflow_session(sid)
        self.assertFalse(os.path.isfile(tmp_path), "clear must remove stale .tmp file")

    def test_clear_nonexistent_session_does_not_raise(self):
        proc = self._proc
        proc._clear_workflow_session("does_not_exist")  # must not raise

    # ── atomic write Windows safety ────────────────────────────────────────

    def test_no_stale_tmp_after_successful_save(self):
        """After a successful save, no .tmp file should remain."""
        proc = self._proc
        sid = "atomic_001"
        proc._save_workflow_session(sid, self._minimal_payload(sid))
        tmp = os.path.join(self.tmp_dir, f"{sid}.json.tmp")
        self.assertFalse(os.path.isfile(tmp), ".tmp file must be removed after successful save")

    def test_stale_tmp_cleaned_before_next_save(self):
        """If a stale .tmp exists from a prior crash, it should be replaced cleanly."""
        proc = self._proc
        sid = "stale_tmp_001"
        # Simulate a crash by leaving a stale .tmp
        stale = os.path.join(self.tmp_dir, f"{sid}.json.tmp")
        with open(stale, "w") as f:
            f.write("crashed partial content")
        # Next save should succeed despite stale .tmp
        result = proc._save_workflow_session(sid, self._minimal_payload(sid))
        self.assertTrue(result)
        self.assertFalse(os.path.isfile(stale), "Stale .tmp must be gone after new save")
        # And the .json should be the new correct content
        loaded = proc._load_workflow_session(sid)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["project_id"], 1)

    def test_overwrite_existing_session(self):
        """Saving to the same session_id twice must overwrite, not corrupt."""
        proc = self._proc
        sid = "overwrite_001"
        payload1 = self._minimal_payload(sid)
        payload2 = self._minimal_payload(sid)
        payload2["project_id"] = 999
        proc._save_workflow_session(sid, payload1)
        proc._save_workflow_session(sid, payload2)
        loaded = proc._load_workflow_session(sid)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["project_id"], 999, "Overwrite must save new data")

    # ── corrupt / incomplete session handling ──────────────────────────────

    def test_load_discards_invalid_json(self):
        """A corrupt (non-JSON) session file must return None and be deleted."""
        proc = self._proc
        sid = "corrupt_json_001"
        path = os.path.join(self.tmp_dir, f"{sid}.json")
        with open(path, "w") as f:
            f.write("{this is not valid json!!")
        result = proc._load_workflow_session(sid)
        self.assertIsNone(result, "Corrupted JSON must return None")
        self.assertFalse(os.path.isfile(path), "Corrupted file must be deleted on load")

    def test_load_discards_session_missing_required_fields(self):
        """A session missing required fields must return None and be deleted."""
        proc = self._proc
        sid = "missing_fields_001"
        path = os.path.join(self.tmp_dir, f"{sid}.json")
        incomplete = {"session_id": sid, "project_id": 1}  # many fields missing
        with open(path, "w") as f:
            json.dump(incomplete, f)
        result = proc._load_workflow_session(sid)
        self.assertIsNone(result, "Session missing required fields must return None")
        self.assertFalse(os.path.isfile(path), "Incomplete session file must be deleted")

    def test_load_accepts_session_with_all_required_fields(self):
        """A complete valid session must be loaded successfully."""
        proc = self._proc
        sid = "complete_001"
        payload = self._minimal_payload(sid)
        proc._save_workflow_session(sid, payload)
        result = proc._load_workflow_session(sid)
        self.assertIsNotNone(result)

    # ── save failure → returns False ───────────────────────────────────────

    def test_save_returns_false_when_dir_not_creatable(self):
        """When _ensure_sessions_dir fails, _save_workflow_session must return False."""
        proc = self._proc
        with patch.object(proc, "_ensure_sessions_dir", return_value=False):
            result = proc._save_workflow_session("fail_001", self._minimal_payload("fail_001"))
        self.assertFalse(result, "save must return False when directory cannot be created")

    def test_save_returns_false_on_write_error(self):
        """When the file write itself fails, save must return False."""
        proc = self._proc
        sid = "write_fail_001"
        original_open = open

        def bad_open(path, mode="r", **kwargs):
            if "tmp" in str(path) and "w" in mode:
                raise PermissionError("Simulated write permission error")
            return original_open(path, mode, **kwargs)

        import builtins
        with patch("builtins.open", side_effect=bad_open):
            result = proc._save_workflow_session(sid, self._minimal_payload(sid))
        self.assertFalse(result, "save must return False when file write raises PermissionError")

    # ── session ID determinism and uniqueness ──────────────────────────────

    def test_session_id_deterministic(self):
        proc = self._proc
        id1 = proc._get_workflow_session_id(11, 22, "att-abc")
        id2 = proc._get_workflow_session_id(11, 22, "att-abc")
        self.assertEqual(id1, id2, "Same inputs must produce same session_id")

    def test_session_id_unique_per_attachment(self):
        proc = self._proc
        id1 = proc._get_workflow_session_id(11, 22, "att-a")
        id2 = proc._get_workflow_session_id(11, 22, "att-b")
        self.assertNotEqual(id1, id2)

    def test_session_id_unique_per_message(self):
        proc = self._proc
        id1 = proc._get_workflow_session_id(11, 22, "att-x")
        id2 = proc._get_workflow_session_id(11, 99, "att-x")
        self.assertNotEqual(id1, id2)

    def test_session_id_unique_per_project(self):
        proc = self._proc
        id1 = proc._get_workflow_session_id(11, 22, "att-x")
        id2 = proc._get_workflow_session_id(99, 22, "att-x")
        self.assertNotEqual(id1, id2)

    def test_session_id_sanitizes_special_chars(self):
        """Attachment IDs with special chars must produce a filesystem-safe session ID."""
        proc = self._proc
        sid = proc._get_workflow_session_id(1, 2, "att/with spaces&special=chars?")
        # Must only contain word chars, hyphens, and underscores
        import re
        self.assertRegex(sid, r'^[a-zA-Z0-9_\-]+$',
                         "Session ID must be filesystem-safe")

    def test_session_id_compact_for_long_basecamp_tokens(self):
        """Long Basecamp signed global IDs (>150 chars) must produce a compact safe session ID (<70 chars)."""
        proc = self._proc
        long_att_id = 'BAh7BkkiC19yYWlscwY6BkVUewdJIglkYXRhBjsAVEkiLmdpZDovL2JjMy9BdHRhY2htZW50LzkwMzM5MzQ4MT9leHBpcmVzX2luBjsAVEkiCHB1cgY7AFRJIg9hdHRhY2hhYmxlBjsAVA==--0cf7cd0ba4d2536a6ca9c272eb61bc75ea2472ea'
        sid = proc._get_workflow_session_id(38026531, 10394280629, long_att_id)
        self.assertLess(len(sid), 70, f"Session ID must stay compact (<70 chars), got {len(sid)}")
        saved = proc._save_workflow_session(sid, self._minimal_payload(sid))
        self.assertTrue(saved, "Must successfully save session with long Basecamp attachment token")
        loaded = proc._load_workflow_session(sid)
        self.assertIsNotNone(loaded)
        proc._clear_workflow_session(sid)

    # ── save / load large payload (embedded images) ────────────────────────

    def test_save_load_with_base64_image_data(self):
        """Sessions containing base64 image data must roundtrip correctly."""
        import base64
        proc = self._proc
        sid = "image_payload_001"
        payload = self._minimal_payload(sid)
        # Simulate a serialized embedded image (binary already converted to b64)
        fake_b64 = base64.b64encode(b"\xff\xd8\xff" + b"\x00" * 512).decode("ascii")
        payload["embedded_images"] = [{
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "content_b64": fake_b64,
            "alt_text": "test photo",
        }]
        saved = proc._save_workflow_session(sid, payload)
        self.assertTrue(saved)
        loaded = proc._load_workflow_session(sid)
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded["embedded_images"]), 1)
        self.assertEqual(loaded["embedded_images"][0]["content_b64"], fake_b64)

    # ── directory re-created mid-run ───────────────────────────────────────

    def test_save_recreates_dir_if_removed_mid_run(self):
        """If the sessions dir is deleted between server start and a save, save must recover."""
        proc = self._proc
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        self.assertFalse(os.path.isdir(self.tmp_dir))
        sid = "recreate_dir_001"
        result = proc._save_workflow_session(sid, self._minimal_payload(sid))
        self.assertTrue(result, "save must succeed by recreating the missing directory")
        self.assertTrue(os.path.isdir(self.tmp_dir))
        loaded = proc._load_workflow_session(sid)
        self.assertIsNotNone(loaded)


class TestSessionRequiredFields(unittest.TestCase):
    """Verify _SESSION_REQUIRED_FIELDS contains the expected keys."""

    def test_required_fields_set_exists(self):
        import services.article_processor as proc
        self.assertTrue(
            hasattr(proc, "_SESSION_REQUIRED_FIELDS"),
            "_SESSION_REQUIRED_FIELDS constant must be defined",
        )

    def test_required_fields_covers_critical_keys(self):
        import services.article_processor as proc
        for key in ("session_id", "article_title", "seo_fields", "ai_result",
                    "doc_result", "duplicate_status_dict", "article_content"):
            self.assertIn(key, proc._SESSION_REQUIRED_FIELDS,
                f"'{key}' must be in _SESSION_REQUIRED_FIELDS")


class TestResumeErrorMessages(unittest.TestCase):
    """Verify that resume with bad/missing session produces clear errors."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="hbm_resume_test_")
        import services.article_processor as proc
        self._proc = proc
        self._orig_dir = proc.SESSIONS_DIR
        proc.SESSIONS_DIR = self.tmp_dir

    def tearDown(self):
        self._proc.SESSIONS_DIR = self._orig_dir
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_resume_no_session_id_returns_error(self):
        """If session_id is missing and cannot be derived, error is clear."""
        proc = self._proc
        # _get_workflow_session_id always returns a string, so we test the
        # no-file-found path
        import asyncio
        from unittest.mock import MagicMock, patch, AsyncMock

        with patch("services.site_service.get_site", return_value=None), \
             patch("services.site_service.get_default_site", return_value=None):
            result = asyncio.run(proc.process(
                project_id=1,
                message_id=2,
                attachment_id="att1",
                session_id="does_not_exist_xyz",
                resume_action="approve_image",
            ))
        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result.get("error", "").lower() + result.get("stages", [""])[-1].lower(),
                      "Error message must mention session not found")

    def test_resume_with_corrupt_session_returns_error(self):
        """Resume with a corrupt JSON session file must return a clear error."""
        proc = self._proc
        sid = "corrupt_resume_001"
        path = os.path.join(self.tmp_dir, f"{sid}.json")
        with open(path, "w") as f:
            f.write("not json at all")

        import asyncio
        result = asyncio.run(proc.process(
            project_id=1,
            message_id=2,
            attachment_id="att1",
            session_id=sid,
            resume_action="approve_image",
        ))
        self.assertEqual(result["status"], "error")
        error_text = result.get("error", "")
        # Should mention corruption or re-run
        self.assertTrue(
            "corrupt" in error_text.lower() or "re-run" in error_text.lower() or "begin" in error_text.lower(),
            f"Error must be specific about corrupt/discarded session. Got: {error_text!r}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

