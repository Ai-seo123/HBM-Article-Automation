import os
import sys
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
db_path = os.path.join(BACKEND_DIR, "hbm_automation.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

import services.article_processor as ap


class TestMerged28PointQAChecklist(unittest.TestCase):
    """
    Regression and functional test suite for the preserved 28-point HBM QA checklist
    enhanced with new authoritative QA requirements.
    """

    def setUp(self):
        self.article_title = "Effective Team Delegation Strategies for Remote Small Businesses"
        self.article_content = (
            "<h2>Why Delegation Matters for Remote Teams</h2>\n"
            "<p>Delegation empowers team members to take ownership of key operational tasks.</p>\n"
            "<h2>Five Core Delegation Frameworks</h2>\n"
            "<p>First, define outcomes clearly. For more guidance on operations, visit "
            '<a href="https://homebusinessmag.com/management/delegation-guide/">remote team management</a> '
            "to understand team accountability. You can also review "
            '<a href="https://homebusinessmag.com/operations/small-business-scaling/">small business scaling</a> '
            "for sustained operational efficiency.</p>\n"
            "<p>According to established leadership research, background due diligence is vital. See "
            '<a href="https://www.forbes.com/leadership/effective-delegation/">effective team delegation</a> '
            "for leadership benchmarks.</p>\n"
            "<ul><li>Define objectives</li><li>Assign owners</li></ul>\n"
            "<p>In summary, strong delegation ensures resilient business growth.</p>"
        )
        self.docx_hyperlinks = [
            {"url": "https://www.forbes.com/leadership/effective-delegation/", "text": "effective team delegation"}
        ]
        self.category_info = {"primary": "Management", "featured": True, "all": ["Management", "Leadership"]}
        self.author_name = "Richard Henderson"
        self.seo_fields = {
            "focus_keyphrase": "Effective Team Delegation",
            "seo_title": "Effective Team Delegation Guide for Remote Businesses",
            "meta_description": "Master effective team delegation with this essential guide for remote small businesses. Learn actionable frameworks to empower team members and drive growth.",
            "excerpt": "Master effective team delegation with this essential guide for remote small businesses. Learn actionable frameworks to empower team members and drive growth.",
            "slug": "effective-team-delegation-remote-businesses",
            "synonyms": "team management, delegation frameworks",
        }
        self.image_result = {
            "status": "PASSED",
            "source": "envato",
            "source_url": "https://elements.envato.com/photo-12345",
            "image_bytes": b"x" * (75 * 1024),  # 75 KB
        }
        self.image_meta = {
            "alt_text": "Team collaborating on remote delegation strategy",
            "image_title": "Effective Team Delegation",
            "caption": "Photo via elements.envato.com",
        }
        self.draft_res = {"status": "success", "post_id": 26170, "title": self.article_title}
        self.yoast_res = {"status": "PASSED"}
        self.duplicate_res = {"status": "PASSED", "data": {"duplicate": False}}
        self.source_text = (
            "Effective Team Delegation Strategies for Remote Small Businesses\n\n"
            "Delegation empowers team members to take ownership of key operational tasks.\n\n"
            "First, define outcomes clearly to understand team accountability.\n\n"
            "In summary, strong delegation ensures resilient business growth."
        )
        self.doc_result = {
            "filename": "team_delegation.docx",
            "byte_size": 28450,
            "character_count": len(self.source_text),
            "extracted_text": self.source_text,
            "embedded_images": [],
        }

    def test_all_28_original_keys_present_in_checklist(self):
        """Verify that every single one of the 28 original keys is present in the checklist output."""
        qa = ap._build_qa_checklist(
            article_title=self.article_title,
            article_content=self.article_content,
            docx_hyperlinks=self.docx_hyperlinks,
            category_info=self.category_info,
            author_name=self.author_name,
            seo_fields=self.seo_fields,
            image_result=self.image_result,
            image_meta=self.image_meta,
            draft_res=self.draft_res,
            yoast_res=self.yoast_res,
            duplicate_res=self.duplicate_res,
            source_html=self.article_content,
            source_text=self.source_text,
            doc_result=self.doc_result,
        )

        all_28_keys = [
            "instructions_followed",
            "title_exact",
            "content_unchanged",
            "headings_preserved",
            "formatting_preserved",
            "final_spot_check",
            "hyperlinks_preserved",
            "no_search_engine_links",
            "approved_authority_links",
            "image_dimensions",
            "source_platform",
            "source_url_present",
            "alt_text_present",
            "image_title_present",
            "caption_present",
            "primary_category",
            "featured_category",
            "additional_categories",
            "author_assigned",
            "focus_keyphrase",
            "seo_title",
            "meta_description",
            "excerpt",
            "slug",
            "synonyms",
            "yoast_check",
            "duplicate_check",
            "draft_status",
        ]

        found_keys = {}
        for section_name, items in qa.items():
            if isinstance(items, dict):
                for k, v in items.items():
                    found_keys[k] = v

        for req_key in all_28_keys:
            self.assertIn(
                req_key,
                found_keys,
                f"Missing required original check key: '{req_key}' from checklist output!",
            )

    def test_internal_link_anchor_words_rule(self):
        """Internal links must use 3-5 consecutive words from the text."""
        # 3 words ('remote team management') and 3 words ('small business scaling') -> PASS
        qa = ap._build_qa_checklist(
            article_title=self.article_title,
            article_content=self.article_content,
            docx_hyperlinks=self.docx_hyperlinks,
            category_info=self.category_info,
            author_name=self.author_name,
            seo_fields=self.seo_fields,
            image_result=self.image_result,
            image_meta=self.image_meta,
            draft_res=self.draft_res,
            yoast_res=self.yoast_res,
            duplicate_res=self.duplicate_res,
        )
        self.assertEqual(qa["links"]["internal_link_anchor_words"]["status"], "PASS")

        # Bad anchor (1 word: 'here') -> FAIL
        bad_html = self.article_content.replace('remote team management', 'here')
        qa_bad = ap._build_qa_checklist(
            article_title=self.article_title,
            article_content=bad_html,
            docx_hyperlinks=self.docx_hyperlinks,
            category_info=self.category_info,
            author_name=self.author_name,
            seo_fields=self.seo_fields,
            image_result=self.image_result,
            image_meta=self.image_meta,
            draft_res=self.draft_res,
            yoast_res=self.yoast_res,
            duplicate_res=self.duplicate_res,
        )
        self.assertEqual(qa_bad["links"]["internal_link_anchor_words"]["status"], "FAIL")

    def test_authority_link_anchor_words_rule(self):
        """Authority links must use 3-4 consecutive words."""
        # 3 words ('effective team delegation') -> PASS
        qa = ap._build_qa_checklist(
            article_title=self.article_title,
            article_content=self.article_content,
            docx_hyperlinks=self.docx_hyperlinks,
            category_info=self.category_info,
            author_name=self.author_name,
            seo_fields=self.seo_fields,
            image_result=self.image_result,
            image_meta=self.image_meta,
            draft_res=self.draft_res,
            yoast_res=self.yoast_res,
            duplicate_res=self.duplicate_res,
        )
        self.assertEqual(qa["links"]["authority_link_anchor_words"]["status"], "PASS")

    def test_prohibited_author_check(self):
        """Author must never be Naveen Shukla, webdev, or admin."""
        # Safe author
        qa_safe = ap._build_qa_checklist(
            article_title=self.article_title,
            article_content=self.article_content,
            docx_hyperlinks=self.docx_hyperlinks,
            category_info=self.category_info,
            author_name="Richard Henderson",
            seo_fields=self.seo_fields,
            image_result=self.image_result,
            image_meta=self.image_meta,
            draft_res=self.draft_res,
            yoast_res=self.yoast_res,
            duplicate_res=self.duplicate_res,
        )
        self.assertEqual(qa_safe["wordpress"]["prohibited_author_check"]["status"], "PASS")

        # Prohibited author
        qa_prohibited = ap._build_qa_checklist(
            article_title=self.article_title,
            article_content=self.article_content,
            docx_hyperlinks=self.docx_hyperlinks,
            category_info=self.category_info,
            author_name="Naveen Shukla",
            seo_fields=self.seo_fields,
            image_result=self.image_result,
            image_meta=self.image_meta,
            draft_res=self.draft_res,
            yoast_res=self.yoast_res,
            duplicate_res=self.duplicate_res,
        )
        self.assertEqual(qa_prohibited["wordpress"]["prohibited_author_check"]["status"], "FAIL")

    def test_featured_image_size_under_100kb(self):
        """Featured image must be <= 100 KB (102,400 bytes)."""
        # 75 KB -> PASS
        qa_pass = ap._build_qa_checklist(
            article_title=self.article_title,
            article_content=self.article_content,
            docx_hyperlinks=self.docx_hyperlinks,
            category_info=self.category_info,
            author_name=self.author_name,
            seo_fields=self.seo_fields,
            image_result={"image_bytes": b"x" * (80 * 1024), "source": "envato"},
            image_meta=self.image_meta,
            draft_res=self.draft_res,
            yoast_res=self.yoast_res,
            duplicate_res=self.duplicate_res,
        )
        self.assertEqual(qa_pass["images"]["image_size_under_100kb"]["status"], "PASS")

        # 120 KB -> FAIL
        qa_fail = ap._build_qa_checklist(
            article_title=self.article_title,
            article_content=self.article_content,
            docx_hyperlinks=self.docx_hyperlinks,
            category_info=self.category_info,
            author_name=self.author_name,
            seo_fields=self.seo_fields,
            image_result={"image_bytes": b"x" * (120 * 1024), "source": "envato"},
            image_meta=self.image_meta,
            draft_res=self.draft_res,
            yoast_res=self.yoast_res,
            duplicate_res=self.duplicate_res,
        )
        self.assertEqual(qa_fail["images"]["image_size_under_100kb"]["status"], "FAIL")

    def test_meta_description_length_confirmed_range(self):
        """Meta description must be between 140 and 155 characters."""
        # 151 characters -> PASS
        valid_desc = "Master effective team delegation with this essential guide for remote businesses. Learn actionable frameworks to empower team members and drive growth."
        self.assertTrue(140 <= len(valid_desc) <= 155)

        seo = dict(self.seo_fields, meta_description=valid_desc, excerpt=valid_desc)
        qa = ap._build_qa_checklist(
            article_title=self.article_title,
            article_content=self.article_content,
            docx_hyperlinks=self.docx_hyperlinks,
            category_info=self.category_info,
            author_name=self.author_name,
            seo_fields=seo,
            image_result=self.image_result,
            image_meta=self.image_meta,
            draft_res=self.draft_res,
            yoast_res=self.yoast_res,
            duplicate_res=self.duplicate_res,
        )
        self.assertEqual(qa["seo"]["meta_description"]["status"], "PASS")

        # Too short (50 characters) -> WARNING
        short_desc = "Short meta description that is under the 140 limit"
        seo_short = dict(self.seo_fields, meta_description=short_desc, excerpt=short_desc)
        qa_short = ap._build_qa_checklist(
            article_title=self.article_title,
            article_content=self.article_content,
            docx_hyperlinks=self.docx_hyperlinks,
            category_info=self.category_info,
            author_name=self.author_name,
            seo_fields=seo_short,
            image_result=self.image_result,
            image_meta=self.image_meta,
            draft_res=self.draft_res,
            yoast_res=self.yoast_res,
            duplicate_res=self.duplicate_res,
        )
        self.assertEqual(qa_short["seo"]["meta_description"]["status"], "WARNING")

    def test_zero_duplicate_keys_across_all_sections(self):
        """Verify that no check key is duplicated across any section in the checklist."""
        qa = ap._build_qa_checklist(
            article_title=self.article_title,
            article_content=self.article_content,
            docx_hyperlinks=self.docx_hyperlinks,
            category_info=self.category_info,
            author_name=self.author_name,
            seo_fields=self.seo_fields,
            image_result=self.image_result,
            image_meta=self.image_meta,
            draft_res=self.draft_res,
            yoast_res=self.yoast_res,
            duplicate_res=self.duplicate_res,
            source_html=self.article_content,
            source_text=self.source_text,
            doc_result=self.doc_result,
        )

        all_seen_keys = []
        for sec_name, sec_items in qa.items():
            if isinstance(sec_items, dict):
                for k in sec_items.keys():
                    self.assertNotIn(
                        k,
                        all_seen_keys,
                        f"Duplicate check key '{k}' detected in section '{sec_name}'!",
                    )
                    all_seen_keys.append(k)

        # Confirm exact total distinct check count is 57
        self.assertEqual(len(all_seen_keys), 57, f"Expected 57 unique checks, found {len(all_seen_keys)}")

    def test_all_12_new_qa_requirements_present_and_executed(self):
        """Verify that every one of the 12 newly added QA requirements is present and evaluated."""
        qa = ap._build_qa_checklist(
            article_title=self.article_title,
            article_content=self.article_content,
            docx_hyperlinks=self.docx_hyperlinks,
            category_info=self.category_info,
            author_name=self.author_name,
            seo_fields=self.seo_fields,
            image_result=self.image_result,
            image_meta=self.image_meta,
            draft_res=self.draft_res,
            yoast_res=self.yoast_res,
            duplicate_res=self.duplicate_res,
            source_html=self.article_content,
            source_text=self.source_text,
            doc_result=self.doc_result,
        )

        new_12_requirements = {
            "headings_are_bold": "content_integrity",
            "stray_client_comments_in_html": "content_integrity",
            "empty_elements_check": "content_integrity",
            "internal_link_anchor_words": "links",
            "authority_link_anchor_words": "links",
            "live_http_link_status": "links",
            "prohibited_author_check": "wordpress",
            "author_box_requested": "wordpress",
            "tags_check": "wordpress",
            "meta_title_differs_from_title": "seo",
            "slug_suffix_duplicate_check": "seo",
            "read_only_qa_guarantee": "workflow_guarantees",
        }

        for req_key, expected_sec in new_12_requirements.items():
            self.assertIn(
                expected_sec,
                qa,
                f"Missing expected section '{expected_sec}' for new requirement '{req_key}'",
            )
            self.assertIn(
                req_key,
                qa[expected_sec],
                f"Missing new requirement key '{req_key}' in section '{expected_sec}'",
            )
            item = qa[expected_sec][req_key]
            self.assertIn(
                item.get("status"),
                ["PASS", "FAIL", "WARNING", "NOT APPLICABLE"],
                f"Invalid status '{item.get('status')}' for check '{req_key}'",
            )
            self.assertIsNotNone(item.get("evidence"), f"Check '{req_key}' must provide non-null evidence!")

    def test_stray_client_comments_detection(self):
        """Editorial comments (TODO, NOTE, etc.) must trigger FAIL."""
        content_with_comment = self.article_content + "<p>TODO: check pricing details before publish</p>"
        qa = ap._build_qa_checklist(
            article_title=self.article_title,
            article_content=content_with_comment,
            docx_hyperlinks=self.docx_hyperlinks,
            category_info=self.category_info,
            author_name=self.author_name,
            seo_fields=self.seo_fields,
            image_result=self.image_result,
            image_meta=self.image_meta,
            draft_res=self.draft_res,
            yoast_res=self.yoast_res,
            duplicate_res=self.duplicate_res,
        )
        self.assertEqual(qa["content_integrity"]["stray_client_comments_in_html"]["status"], "FAIL")

    def test_slug_suffix_duplicate_detection(self):
        """Auto-incremented duplicate slug suffix (-2, -3) must trigger FAIL."""
        seo = dict(self.seo_fields, slug="effective-team-delegation-2")
        qa = ap._build_qa_checklist(
            article_title=self.article_title,
            article_content=self.article_content,
            docx_hyperlinks=self.docx_hyperlinks,
            category_info=self.category_info,
            author_name=self.author_name,
            seo_fields=seo,
            image_result=self.image_result,
            image_meta=self.image_meta,
            draft_res=self.draft_res,
            yoast_res=self.yoast_res,
            duplicate_res=self.duplicate_res,
        )
        self.assertEqual(qa["seo"]["slug_suffix_duplicate_check"]["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
