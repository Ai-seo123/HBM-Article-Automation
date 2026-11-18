import os
import sys
import unittest

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.seo_optimizer as seo_optimizer
import services.article_processor as article_processor


class TestHeadingQAChecks(unittest.TestCase):
    """
    Regression and unit tests for dynamic heading preservation, Title Case,
    and hierarchy QA checks across diverse article HTML structures.
    """

    def setUp(self):
        self.mock_seo = {
            "focus_keyphrase": "Reduce Hiring Risk",
            "seo_title": "Reduce Hiring Risk: Complete Guide",
            "meta_description": "Learn how to reduce hiring risk with effective screening.",
            "slug": "reduce-hiring-risk",
            "excerpt": "Learn how to reduce hiring risk with effective screening.",
        }
        self.dummy_draft_res = {"title": "How Canadian SMBs Can Reduce Hiring Risk"}
        self.dummy_yoast_res = {
            "status": "PASSED",
            "data": {
                "seo": {
                    "results": [
                        {"id": "internalLinks", "score": 9, "text": "Internal links: Good job!"},
                        {"id": "externalLinks", "score": 9, "text": "Outbound links: Good job!"},
                    ]
                }
            },
        }
        self.dummy_dup_res = {"status": "PASSED"}
        self.dummy_img_res = {"status": "PASSED", "image_bytes": b"fake_bytes" * 100, "source": "envato"}
        self.dummy_img_meta = {"alt_text": "Reduce Hiring Risk Banner", "caption": "", "image_title": "Banner"}

    def test_h2_and_h3_clean_headings(self):
        """Articles with clean H2 and H3 headings in Title Case should PASS all 3 heading checks."""
        html = (
            "<h2>Why Hiring Risk Matters for Canadian SMBs</h2>\n"
            "<p>Hiring mistakes cost businesses time and resources.</p>\n"
            "<h2>A Practical Background Screening Process</h2>\n"
            "<p>Consistency is key for operations.</p>\n"
            "<h3>Step 1: Identity and Credential Verification</h3>\n"
            "<p>Verify background and identity.</p>\n"
            "<h3>Step 2: Employment History Review</h3>\n"
            "<p>Confirm prior work experience.</p>\n"
        )
        qa = article_processor._build_qa_checklist(
            article_title="How Canadian SMBs Can Reduce Hiring Risk",
            article_content=html,
            docx_hyperlinks=[],
            category_info={"primary": "Human Resources"},
            author_name="Business Editor",
            seo_fields=self.mock_seo,
            image_result=self.dummy_img_res,
            image_meta=self.dummy_img_meta,
            draft_res=self.dummy_draft_res,
            yoast_res=self.dummy_yoast_res,
            duplicate_res=self.dummy_dup_res,
            source_html=html,
        )

        ci = qa["content_integrity"]
        self.assertEqual(ci["headings_preserved"]["status"], "PASS")
        self.assertIn("4 subheading(s) preserved and formatted", ci["headings_preserved"]["detail"])
        self.assertIn("H2: 2, H3: 2", ci["headings_preserved"]["detail"])

        self.assertEqual(ci["title_case_headings"]["status"], "PASS")
        self.assertIn("All 4 subheading(s) verified in Title Case", ci["title_case_headings"]["detail"])

        self.assertEqual(ci["heading_hierarchy"]["status"], "PASS")
        self.assertIn("Logical hierarchy verified", ci["heading_hierarchy"]["detail"])

    def test_h2_only_no_h3_headings(self):
        """Articles with H2 headings only (no H3) should PASS with valid H2 breakdown."""
        html = (
            "<h2>When to Hand off the Bookkeeping</h2>\n"
            "<p>Managing properties from home requires good records.</p>\n"
            "<h2>Evaluating Your Financial Workflows</h2>\n"
            "<p>Property managers need structured reporting.</p>\n"
        )
        qa = article_processor._build_qa_checklist(
            article_title="Running a Property Management Business From Home",
            article_content=html,
            docx_hyperlinks=[],
            category_info={"primary": "Management"},
            author_name="Finance Editor",
            seo_fields=self.mock_seo,
            image_result=self.dummy_img_res,
            image_meta=self.dummy_img_meta,
            draft_res=self.dummy_draft_res,
            yoast_res=self.dummy_yoast_res,
            duplicate_res=self.dummy_dup_res,
            source_html=html,
        )

        ci = qa["content_integrity"]
        self.assertEqual(ci["headings_preserved"]["status"], "PASS")
        self.assertIn("H2: 2", ci["headings_preserved"]["detail"])
        self.assertEqual(ci["title_case_headings"]["status"], "PASS")
        self.assertEqual(ci["heading_hierarchy"]["status"], "PASS")
        self.assertIn("2 H2", ci["heading_hierarchy"]["detail"])

    def test_no_headings_plain_or_bold_paragraphs(self):
        """Articles with no heading tags (plain text or bold paragraphs) should return NOT APPLICABLE."""
        html = (
            "<p>No matter the circumstances, getting keys to your place is worth celebrating.</p>\n"
            "<p><strong>1) Separate Essential Expenses from Lifestyle Upgrades</strong></p>\n"
            "<p>Start by separating true household essentials from purchases that can wait.</p>\n"
            "<p><strong>2) Consider All Your Fixed Costs</strong></p>\n"
            "<p>Your housing expense does not end with your mortgage payment.</p>\n"
        )
        qa = article_processor._build_qa_checklist(
            article_title="The First-Year Household Budget",
            article_content=html,
            docx_hyperlinks=[],
            category_info={"primary": "Credit"},
            author_name="Finance Editor",
            seo_fields=self.mock_seo,
            image_result=self.dummy_img_res,
            image_meta=self.dummy_img_meta,
            draft_res=self.dummy_draft_res,
            yoast_res=self.dummy_yoast_res,
            duplicate_res=self.dummy_dup_res,
            source_html=html,
        )

        ci = qa["content_integrity"]
        self.assertEqual(ci["headings_preserved"]["status"], "NOT APPLICABLE")
        self.assertIn("No subheadings in source document or article content", ci["headings_preserved"]["detail"])
        self.assertEqual(ci["title_case_headings"]["status"], "NOT APPLICABLE")
        self.assertEqual(ci["heading_hierarchy"]["status"], "NOT APPLICABLE")

    def test_source_headings_dropped_in_draft(self):
        """If source DOCX had headings but final draft content dropped them, headings_preserved must FAIL."""
        source_html = "<h2>Why Hiring Risk Matters</h2><p>Text</p><h2>Background Process</h2><p>Text</p>"
        draft_html = "<p>Text without any headings at all.</p>"

        qa = article_processor._build_qa_checklist(
            article_title="How Canadian SMBs Can Reduce Hiring Risk",
            article_content=draft_html,
            docx_hyperlinks=[],
            category_info={"primary": "Human Resources"},
            author_name="Business Editor",
            seo_fields=self.mock_seo,
            image_result=self.dummy_img_res,
            image_meta=self.dummy_img_meta,
            draft_res=self.dummy_draft_res,
            yoast_res=self.dummy_yoast_res,
            duplicate_res=self.dummy_dup_res,
            source_html=source_html,
        )

        ci = qa["content_integrity"]
        self.assertEqual(ci["headings_preserved"]["status"], "FAIL")
        self.assertIn("Subheadings present in source document", ci["headings_preserved"]["detail"])
        self.assertIn("dropped or missing", ci["headings_preserved"]["detail"])

    def test_malformed_mismatched_heading_tags(self):
        """Mismatched heading tags like <h2>...</h3> must be detected as FAIL."""
        html = "<h2>Why Hiring Risk Matters</h3><p>Some text.</p>"

        qa = article_processor._build_qa_checklist(
            article_title="How Canadian SMBs Can Reduce Hiring Risk",
            article_content=html,
            docx_hyperlinks=[],
            category_info={"primary": "Human Resources"},
            author_name="Business Editor",
            seo_fields=self.mock_seo,
            image_result=self.dummy_img_res,
            image_meta=self.dummy_img_meta,
            draft_res=self.dummy_draft_res,
            yoast_res=self.dummy_yoast_res,
            duplicate_res=self.dummy_dup_res,
            source_html=html,
        )

        ci = qa["content_integrity"]
        self.assertEqual(ci["headings_preserved"]["status"], "FAIL")
        self.assertIn("Malformed heading markup detected", ci["headings_preserved"]["detail"])
        self.assertIn("Mismatched heading tags", ci["headings_preserved"]["detail"])

    def test_malformed_unclosed_inner_tag(self):
        """Unclosed inline tags inside headings (e.g. <a href='...'> without </a>) must be detected as FAIL."""
        html = "<h2>A <a href='https://example.com'>Unclosed Link</h2><p>Paragraph text.</p>"

        qa = article_processor._build_qa_checklist(
            article_title="Test Title",
            article_content=html,
            docx_hyperlinks=[],
            category_info={"primary": "Business"},
            author_name="Author",
            seo_fields=self.mock_seo,
            image_result=self.dummy_img_res,
            image_meta=self.dummy_img_meta,
            draft_res=self.dummy_draft_res,
            yoast_res=self.dummy_yoast_res,
            duplicate_res=self.dummy_dup_res,
            source_html=html,
        )

        ci = qa["content_integrity"]
        self.assertEqual(ci["headings_preserved"]["status"], "FAIL")
        self.assertIn("Unclosed <a> link tag inside <h2>", ci["headings_preserved"]["detail"])

    def test_non_title_case_headings_detected(self):
        """Headings not in Title Case must be flagged with details of non-conforming items."""
        html = (
            "<h2>why hiring risk matters for canadian smbs</h2>\n"
            "<p>Paragraph text.</p>\n"
            "<h2>a practical background screening process</h2>\n"
            "<p>Paragraph text.</p>\n"
        )
        qa = article_processor._build_qa_checklist(
            article_title="How Canadian SMBs Can Reduce Hiring Risk",
            article_content=html,
            docx_hyperlinks=[],
            category_info={"primary": "Human Resources"},
            author_name="Business Editor",
            seo_fields=self.mock_seo,
            image_result=self.dummy_img_res,
            image_meta=self.dummy_img_meta,
            draft_res=self.dummy_draft_res,
            yoast_res=self.dummy_yoast_res,
            duplicate_res=self.dummy_dup_res,
            source_html=html,
        )

        ci = qa["content_integrity"]
        self.assertIn(ci["title_case_headings"]["status"], ("WARNING", "FAIL"))
        self.assertIn("not in Title Case", ci["title_case_headings"]["detail"])

    def test_heading_hierarchy_duplicate_body_h1(self):
        """Body content containing <h1> must FAIL the heading_hierarchy check."""
        html = (
            "<h1>Duplicate Post Title</h1>\n"
            "<p>Paragraph text.</p>\n"
            "<h2>Subheading Level 2</h2>\n"
        )
        qa = article_processor._build_qa_checklist(
            article_title="Duplicate Post Title",
            article_content=html,
            docx_hyperlinks=[],
            category_info={"primary": "Business"},
            author_name="Author",
            seo_fields=self.mock_seo,
            image_result=self.dummy_img_res,
            image_meta=self.dummy_img_meta,
            draft_res=self.dummy_draft_res,
            yoast_res=self.dummy_yoast_res,
            duplicate_res=self.dummy_dup_res,
            source_html=html,
        )

        ci = qa["content_integrity"]
        self.assertEqual(ci["heading_hierarchy"]["status"], "FAIL")
        self.assertIn("Body content contains 1 <h1> tag(s)", ci["heading_hierarchy"]["detail"])

    def test_heading_hierarchy_h3_before_h2(self):
        """Subheading sequence starting with H3 before any H2 must FAIL heading_hierarchy."""
        html = (
            "<h3>Early Subheading Starting at H3</h3>\n"
            "<p>Paragraph text.</p>\n"
            "<h2>Later H2 Subheading</h2>\n"
        )
        qa = article_processor._build_qa_checklist(
            article_title="Test Title",
            article_content=html,
            docx_hyperlinks=[],
            category_info={"primary": "Business"},
            author_name="Author",
            seo_fields=self.mock_seo,
            image_result=self.dummy_img_res,
            image_meta=self.dummy_img_meta,
            draft_res=self.dummy_draft_res,
            yoast_res=self.dummy_yoast_res,
            duplicate_res=self.dummy_dup_res,
            source_html=html,
        )

        ci = qa["content_integrity"]
        self.assertEqual(ci["heading_hierarchy"]["status"], "FAIL")
        self.assertIn("starts with <h3> before any <h2>", ci["heading_hierarchy"]["detail"])

    def test_heading_hierarchy_skipped_level_h2_to_h4(self):
        """Jumping from H2 directly to H4 without an H3 must FAIL heading_hierarchy."""
        html = (
            "<h2>First H2 Subheading</h2>\n"
            "<p>Paragraph text.</p>\n"
            "<h4>Skipped Direct to H4</h4>\n"
        )
        qa = article_processor._build_qa_checklist(
            article_title="Test Title",
            article_content=html,
            docx_hyperlinks=[],
            category_info={"primary": "Business"},
            author_name="Author",
            seo_fields=self.mock_seo,
            image_result=self.dummy_img_res,
            image_meta=self.dummy_img_meta,
            draft_res=self.dummy_draft_res,
            yoast_res=self.dummy_yoast_res,
            duplicate_res=self.dummy_dup_res,
            source_html=html,
        )

        ci = qa["content_integrity"]
        self.assertEqual(ci["heading_hierarchy"]["status"], "FAIL")
        self.assertIn("skips level: <h2> jumps directly to <h4>", ci["heading_hierarchy"]["detail"])

    def test_format_headings_title_case_correction(self):
        """format_headings_title_case must format text to Title Case and repair mismatched closing tags."""
        html = "<h2>why hiring risk matters for canadian smbs</h3><p>text</p><h3>step 1: background checks</h2>"
        formatted, changes = seo_optimizer.format_headings_title_case(html)

        self.assertIn("<h2>Why Hiring Risk Matters for Canadian SMBs</h2>", formatted)
        self.assertIn("<h3>Step 1: Background Checks</h3>", formatted)
        self.assertNotIn("</h3>", formatted[:50])

    def test_to_title_case_rules(self):
        """Verify Title Case rules: numbered lists, hyphenated words, acronyms, and punctuation breaks."""
        self.assertEqual(
            seo_optimizer.to_title_case("1. establish dedicated working hours"),
            "1. Establish Dedicated Working Hours",
        )
        self.assertEqual(
            seo_optimizer.to_title_case("step 2: practical background screening process"),
            "Step 2: Practical Background Screening Process",
        )
        self.assertEqual(
            seo_optimizer.to_title_case("running a business from home? here's when to hand off the bookkeeping"),
            "Running a Business from Home? Here's When to Hand off the Bookkeeping",
        )
        self.assertEqual(
            seo_optimizer.to_title_case("cost-effective tools and step-by-step guidance"),
            "Cost-Effective Tools and Step-by-Step Guidance",
        )
        self.assertEqual(
            seo_optimizer.to_title_case("how canadian smbs can reduce hiring risk"),
            "How Canadian SMBs Can Reduce Hiring Risk",
        )


if __name__ == "__main__":
    unittest.main()
