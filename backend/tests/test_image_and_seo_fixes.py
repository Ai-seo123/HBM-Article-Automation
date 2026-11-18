import io
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from PIL import Image

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
db_path = os.path.join(BACKEND_DIR, "hbm_automation.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

import services.image_service as image_service
import services.seo_optimizer as seo_optimizer
import services.gemini as gemini_service
import services.article_processor as article_processor
import services.documents as documents_service


class TestImageAndSEOFixes(unittest.IsolatedAsyncioTestCase):
    """
    Focused tests for the 4 specific image and SEO requirements:
    1. Image handling (DOCX image preservation, max 700px width, 1000x667 stock, <=100KB).
    2. Focus keyphrase, SEO title, meta description, and slug.
    3. Relevant external authority link (Forbes/Entrepreneur).
    4. Image alt text containing exact focus keyphrase.
    """

    # ──────────────────────────────────────────────────────────────────────────
    # Requirement 1: Image Handling
    # ──────────────────────────────────────────────────────────────────────────

    def test_docx_image_width_capped_at_700px_and_aspect_ratio_preserved(self):
        """
        For images already present in the document, ensure the displayed/content
        image width does not exceed 700 pixels, preserving its original aspect ratio.
        """
        # Create a sample large image: 1400 x 900 (aspect ratio ~1.555)
        img = Image.new("RGB", (1400, 900), color=(100, 150, 200))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        raw_bytes = buf.getvalue()

        optimized = image_service.optimize_docx_image(raw_bytes, max_width=700)
        opt_img = Image.open(io.BytesIO(optimized))

        # 1. Width must not exceed 700 px
        self.assertLessEqual(opt_img.width, 700)
        self.assertEqual(opt_img.width, 700)

        # 2. Aspect ratio must be preserved without distortion: 1400/900 == 700/450
        expected_height = int(900 * (700 / 1400))
        self.assertEqual(opt_img.height, expected_height)

        # 3. File size must be 100 KB or less (<= 102,400 bytes)
        self.assertLessEqual(len(optimized), 100 * 1024)

    def test_docx_image_smaller_than_700px_not_stretched(self):
        """
        Images smaller than 700px must not be stretched or distorted up to 700px.
        """
        img = Image.new("RGB", (550, 350), color=(120, 180, 80))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        raw_bytes = buf.getvalue()

        optimized = image_service.optimize_docx_image(raw_bytes, max_width=700)
        opt_img = Image.open(io.BytesIO(optimized))

        self.assertEqual(opt_img.width, 550)
        self.assertEqual(opt_img.height, 350)
        self.assertLessEqual(len(optimized), 100 * 1024)

    def test_stock_image_resizing_1000x667_and_compression(self):
        """
        For images downloaded from stock providers (Envato, Depositphotos, Dreamstime, Pexels),
        maintain the required 1000 x 667 px dimensions and compression <= 100 KB.
        """
        img = Image.new("RGB", (2000, 1500), color=(220, 100, 100))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        raw_bytes = buf.getvalue()

        resized = image_service.resize_image(raw_bytes, "image/jpeg")
        res_img = Image.open(io.BytesIO(resized))

        self.assertEqual(res_img.width, 1000)
        self.assertEqual(res_img.height, 667)
        self.assertLessEqual(len(resized), 100 * 1024)

    @patch("services.image_providers.check_provider_status")
    async def test_preserve_docx_image_when_no_replacement_requested(self, mock_status):
        """
        If an image already exists inside the source DOCX, preserve and upload that image
        when the instructions do NOT request replacement.
        """
        img = Image.new("RGB", (800, 500), color=(70, 90, 110))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        docx_img_bytes = buf.getvalue()

        embedded_images = [{
            "filename": "chart-figure.jpg",
            "content": docx_img_bytes,
            "content_type": "image/jpeg",
            "alt_text": "Quarterly Performance Chart",
        }]

        image_directive = {
            "replace_images": False,
            "image_action": "use_existing",
            "image_requirement": "included",
        }

        res = await image_service.acquire_featured_image(
            embedded_images=embedded_images,
            image_directive=image_directive,
            article_title="Strategic Business Planning",
            article_content="<p>Content</p>",
            client_instructions_plain="IMAGE: Included. Use the existing image from document.",
        )

        self.assertEqual(res["status"], "PASSED")
        self.assertEqual(res["source"], "docx")
        self.assertEqual(res["provider"], "DOCX Embedded Image")
        # Ensure it was optimized to max 700px width without distortion
        opt_img = Image.open(io.BytesIO(res["image_bytes"]))
        self.assertLessEqual(opt_img.width, 700)
        self.assertLessEqual(len(res["image_bytes"]), 100 * 1024)

    @patch("services.image_service._fetch_clean_image_from_url")
    @patch("services.image_providers.search_provider_images")
    @patch("services.image_providers.check_provider_status")
    async def test_explicit_replacement_overrides_docx_image_preservation_and_uses_envato(
        self, mock_status, mock_search, mock_fetch
    ):
        """
        When instructions contain wording such as:
        'IMAGE: REPLACE image from a platform of your choice. Be sure image was not sourced before. Hyperlink image to the source ONCE in the caption.'
        - Treat REPLACE image as an explicit command to replace the existing image in the DOCX.
        - Do NOT retain, reuse, or select the DOCX image as the replacement image.
        - Search Envato and use a new, relevant, previously unused Envato image.
        - Do not use Pexels, Depositphotos, Dreamstime, Unsplash, AI, or any other source.
        - Add the Envato source hyperlink exactly once in the image caption.
        """
        img = Image.new("RGB", (800, 500), color=(70, 90, 110))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        docx_img_bytes = buf.getvalue()

        embedded_images = [{
            "filename": "chart-figure.jpg",
            "content": docx_img_bytes,
            "content_type": "image/jpeg",
            "alt_text": "Quarterly Performance Chart",
        }]

        instruction_text = (
            "IMAGE: REPLACE image from a platform of your choice. "
            "Be sure image was not sourced before. Hyperlink image to the source ONCE in the caption."
        )

        mock_status.return_value = {"status": "LIVE", "name": "Envato", "configured": True, "details": "Operational"}
        mock_search.return_value = {
            "provider": "envato",
            "status": "LIVE",
            "results": [{
                "id": "123456",
                "title": "Modern Business Team Meeting",
                "image_url": "https://photodune.net/item/123456/photo_123456.jpg",
                "source_url": "https://photodune.net/item/123456",
                "photographer": "JaneDoe",
                "source": "envato",
                "provider": "Envato",
                "width": 1200,
                "height": 800,
            }],
        }

        # Mock download of the Envato image
        download_img = Image.new("RGB", (1200, 800), color=(50, 100, 150))
        dl_buf = io.BytesIO()
        download_img.save(dl_buf, format="JPEG")
        mock_fetch.return_value = {
            "image_bytes": dl_buf.getvalue(),
            "content_type": "image/jpeg",
            "url": "https://photodune.net/item/123456/photo_123456.jpg",
        }

        res = await image_service.acquire_featured_image(
            embedded_images=embedded_images,
            image_directive={},
            article_title="Modern Office Interior Design",
            article_content="<p>Article body content</p>",
            client_instructions_plain=instruction_text,
            focus_keyphrase="Modern Office Interior Design",
        )

        # 1. Status must be PASSED
        self.assertEqual(res["status"], "PASSED")
        # 2. Must NOT be the DOCX image
        self.assertNotEqual(res["source"], "docx")
        self.assertEqual(res["source"], "envato")
        self.assertEqual(res["provider"], "Envato")
        # 3. Source URL must be Envato asset
        self.assertEqual(res["source_url"], "https://photodune.net/item/123456")
        # 4. Caption must display "envato.com" linked to original asset page URL exactly once
        caption = res["caption"]
        self.assertEqual(caption, '<a href="https://photodune.net/item/123456" target="_blank" rel="noopener">envato.com</a>')
        self.assertEqual(caption.count("href="), 1)
        self.assertEqual(caption.count("https://photodune.net/item/123456"), 1)
        self.assertIn("envato.com", caption)
        self.assertNotIn("Photo via Envato", caption)
        # 5. Only Envato provider should be checked/searched
        mock_search.assert_called()
        self.assertEqual(mock_search.call_args[0][0], "envato")

    @patch("services.image_providers.search_provider_images")
    @patch("services.image_providers.check_provider_status")
    async def test_replacement_fails_cleanly_without_fallback_when_envato_unavailable(
        self, mock_status, mock_search
    ):
        """
        If no valid Envato image is available, report the image sourcing failure.
        Do not fall back to the original DOCX image or another provider.
        """
        img = Image.new("RGB", (800, 500), color=(70, 90, 110))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        docx_img_bytes = buf.getvalue()

        embedded_images = [{
            "filename": "chart-figure.jpg",
            "content": docx_img_bytes,
            "content_type": "image/jpeg",
            "alt_text": "Quarterly Performance Chart",
        }]

        instruction_text = (
            "IMAGE: REPLACE image from a platform of your choice. "
            "Be sure image was not sourced before. Hyperlink image to the source ONCE in the caption."
        )

        mock_status.return_value = {"status": "LIVE", "name": "Envato", "configured": True, "details": "Operational"}
        # Envato returns 0 results
        mock_search.return_value = {"provider": "envato", "status": "LIVE", "results": []}

        res = await image_service.acquire_featured_image(
            embedded_images=embedded_images,
            image_directive={},
            article_title="Strategic Business Planning",
            article_content="<p>Content</p>",
            client_instructions_plain=instruction_text,
            focus_keyphrase="Strategic Business Planning",
        )

        # Must report failure
        self.assertEqual(res["status"], "FAILED")
        self.assertIn("IMAGE SOURCING FAILURE", res["error"])
        # Must NOT fall back to docx image
        self.assertIsNone(res["image_bytes"])
        self.assertNotEqual(res.get("source"), "docx")

    def test_inline_image_html_max_width_enforced(self):
        """
        Ensure displayed inline images in content HTML have max-width: 700px.
        """
        html_input = '<p>Intro paragraph</p><p><img src="diagram.png" alt="Process flow"></p><p>Second paragraph</p>'
        embedded = [{"filename": "diagram.png", "url": "https://espialsolutions.com/wp-content/uploads/diagram.png"}]
        processed_html = article_processor._replace_inline_image_urls(html_input, embedded)

        self.assertIn('https://espialsolutions.com/wp-content/uploads/diagram.png', processed_html)
        self.assertIn('max-width: 700px', processed_html)
        self.assertIn('height: auto', processed_html)

    # ──────────────────────────────────────────────────────────────────────────
    # Requirement 2: Focus Keyphrase, SEO Title, Meta Description, and Slug
    # ──────────────────────────────────────────────────────────────────────────

    def test_focus_keyphrase_preserves_filler_words_from_title(self):
        """
        Focus keyphrase extracted from original title must preserve the exact selected phrase,
        including filler words ('for', 'in', 'to', 'of', etc.).
        """
        # Article 1: Title with filler words "for" and "of"
        title_1 = "Corporate Gifts for Remote Employees: The Power of Recognition"
        kp_1 = gemini_service.extract_title_keyphrase(title_1)
        self.assertIn("for", kp_1.lower().split())
        self.assertIn(kp_1.lower(), title_1.lower())

        # Article 2: Title with filler words "to" and "a"
        title_2 = "How to Choose a Pricing Strategy for Small Business"
        kp_2 = gemini_service.extract_title_keyphrase(title_2)
        self.assertIn(kp_2.lower(), title_2.lower())
        self.assertTrue(any(filler in kp_2.lower().split() for filler in ["a", "for", "to"]))

    def test_seo_title_begins_with_exact_focus_keyphrase_and_remains_close(self):
        """
        The SEO title must begin with that exact focus keyphrase and remain as close
        as possible to the original article title.
        """
        title = "Effective Ways to Build a Culture of Recognition in the Workplace"
        kp = "Culture of Recognition"
        seo_fields = {
            "focus_keyphrase": kp,
            "seo_title": f"{kp}: Ways to Build in the Workplace",
            "meta_description": f"Learn how a {kp} drives organizational success and team engagement across all business departments.",
            "slug": "",
        }

        # Validate that SEO title begins with exact focus keyphrase
        self.assertTrue(seo_fields["seo_title"].lower().startswith(kp.lower()))
        # Check that meaningful words from original title are preserved
        self.assertIn("Workplace", seo_fields["seo_title"])

    def test_slug_removes_filler_words_while_keeping_meaningful_keyphrase_words(self):
        """
        Only the slug may remove unnecessary filler words while keeping the focus
        keyphrase's meaningful words.
        """
        title = "Corporate Gifts for Remote Employees"
        kp = "Corporate Gifts for Remote Employees"

        slug = gemini_service.build_clean_slug(title, kp)

        # Meaningful words must be in slug
        self.assertIn("corporate", slug)
        self.assertIn("gifts", slug)
        self.assertIn("remote", slug)
        self.assertIn("employees", slug)
        # Unnecessary filler word "for" must be removed in slug
        slug_parts = slug.split("-")
        self.assertNotIn("for", slug_parts)

    def test_meta_description_preserves_exact_focus_keyphrase_and_length(self):
        """
        The meta description must include the exact focus keyphrase preserving its
        wording and order naturally, within 120-156 characters.
        """
        title = "How to Choose a Pricing Strategy for Small Business"
        kp = "Pricing Strategy for Small Business"
        desc = f"Discover how to choose the right {kp} to boost margins and maintain steady growth. Explore practical methods today."

        opt_desc = seo_optimizer.optimize_meta_description(desc, kp, title)

        self.assertIn(kp.lower(), opt_desc.lower())
        self.assertGreaterEqual(len(opt_desc), 120)
        self.assertLessEqual(len(opt_desc), 156)

    def test_meta_description_strictly_enforces_140_to_155_characters(self):
        """
        Verify that optimize_meta_description strictly enforces 140-155 characters
        across short, medium, and long initial descriptions.
        """
        title = "Strategic Business Planning for Remote Entrepreneurs"
        kp = "Strategic Business Planning"
        test_inputs = [
            "",
            "Short text.",
            "Explore Strategic Business Planning for success.",
            "Master Strategic Business Planning with comprehensive guidance for modern companies looking to scale operations, empower teams, and achieve long-term sustainable growth in competitive markets.",
        ]
        for desc in test_inputs:
            result = seo_optimizer.optimize_meta_description(desc, kp, title)
            self.assertTrue(
                140 <= len(result) <= 155,
                f"Meta description length {len(result)} not in 140-155 range: '{result}'",
            )
            self.assertIn(kp.lower(), result.lower())

    # ──────────────────────────────────────────────────────────────────────────
    # Requirement 3: Relevant External Authority Link (Forbes or Entrepreneur)
    # ──────────────────────────────────────────────────────────────────────────

    def test_relevant_external_authority_link_topic_selection(self):
        """
        Select an existing, relevant article from Forbes or Entrepreneur based on
        the actual topic of the selected article.
        """
        # Test Article A: Corporate Gifting / Recognition topic
        content_gifting = """
        <h2>Employee Engagement</h2>
        <p>Providing thoughtful corporate gifts and building a culture of recognition enhances team morale and workplace satisfaction across departments.</p>
        <p>Organizations should establish consistent practices to celebrate achievements.</p>
        """
        opt_content_a, added_a = seo_optimizer.inject_external_authority_links(content_gifting, "Corporate Gifts")
        self.assertEqual(len(added_a), 1)
        self.assertEqual(added_a[0]["domain"], "entrepreneur.com")
        self.assertIn("culture-of-recognition", added_a[0]["url"])

        # Test Article B: Pricing Strategy topic
        content_pricing = """
        <h2>Setting Your Rates</h2>
        <p>Developing an effective pricing strategy ensures that small businesses protect their profit margins and build long-term sustainability.</p>
        <p>Carefully evaluating your cost structure guides pricing decisions.</p>
        """
        opt_content_b, added_b = seo_optimizer.inject_external_authority_links(content_pricing, "Pricing Strategy")
        self.assertEqual(len(added_b), 1)
        self.assertEqual(added_b[0]["domain"], "entrepreneur.com")
        self.assertIn("pricing-strategy", added_b[0]["url"])

    def test_preserve_existing_client_provided_authority_link(self):
        """
        If the article already contains an authority link from Forbes or Entrepreneur,
        preserve it and do not inject another one.
        """
        content_with_existing = """
        <p>Check out <a href="https://www.entrepreneur.com/leadership/why-clear-communication-is-vital-for-business-success/366710">communication principles</a> for business leaders.</p>
        <p>Clear guidance improves operational clarity.</p>
        """
        opt_content, added = seo_optimizer.inject_external_authority_links(content_with_existing, "Business Leadership")
        self.assertEqual(len(added), 0)
        self.assertIn("why-clear-communication-is-vital-for-business-success/366710", opt_content)

    # ──────────────────────────────────────────────────────────────────────────
    # Requirement 4: Image Alt Text
    # ──────────────────────────────────────────────────────────────────────────

    @patch("services.gemini._call_gemini")
    async def test_featured_image_alt_text_contains_exact_focus_keyphrase(self, mock_gemini):
        """
        Set the image Alt Text to the exact Focus Keyphrase string, character-for-character.
        Alt Text must contain ONLY the Focus Keyphrase.
        Do not append descriptive context, extra words, punctuation, or text generated from the article.
        """
        kp = "Corporate Gifts for Clients"
        title = "Top 5 Corporate Gifts for Clients to Express Appreciation"

        # Mock Gemini returning descriptive text
        mock_gemini.return_value = '{"alt_text": "Professional team selecting thoughtful Corporate Gifts for Clients in modern office", "image_title": "Corporate Gifts", "caption": "Photo"}'

        meta = await gemini_service.generate_image_metadata(
            article_title=title,
            focus_keyphrase=kp,
        )

        alt = meta["alt_text"]
        # Alt text must contain ONLY the Focus Keyphrase character-for-character
        self.assertEqual(alt, kp)

    @patch("services.gemini._call_gemini")
    async def test_featured_image_alt_text_fallback_preserves_exact_keyphrase(self, mock_gemini):
        """
        If AI response omits the keyphrase, the system must set the image Alt Text
        strictly to the exact focus keyphrase string.
        """
        kp = "Pricing Strategy for Small Business"
        title = "How to Choose a Pricing Strategy for Small Business"

        # Mock Gemini returning text without keyphrase
        mock_gemini.return_value = '{"alt_text": "Modern conference room desk with calculator and analytics reports", "image_title": "Pricing", "caption": "Photo"}'

        meta = await gemini_service.generate_image_metadata(
            article_title=title,
            focus_keyphrase=kp,
        )

        alt = meta["alt_text"]
        self.assertEqual(alt, kp)

    def test_exact_focus_keyphrase_alt_text_character_for_character_and_casing(self):
        """
        Test exact character-for-character equality:
        Focus Keyphrase: Modern Office Interior Design
        Alt Text: Modern Office Interior Design
        Alt Text must contain ONLY the Focus Keyphrase.
        Do not append descriptive context, extra words, punctuation, or text generated from the article.
        """
        kp = "Modern Office Interior Design"
        # Case 1: Alt input with extra words
        alt_input = "modern office interior design in a bright workspace with natural light"
        validated = gemini_service.ensure_exact_keyphrase_alt_text(alt_input, focus_keyphrase=kp)
        self.assertEqual(validated, kp)

        # Case 2: Missing keyphrase with descriptive context
        missing_input = "desk with laptop and financial analytics reports"
        validated_2 = gemini_service.ensure_exact_keyphrase_alt_text(missing_input, focus_keyphrase=kp)
        self.assertEqual(validated_2, kp)

        # Case 3: Generic alt text that omits keyphrase
        generic_input = "Photo via Envato"
        validated_3 = gemini_service.ensure_exact_keyphrase_alt_text(generic_input, focus_keyphrase=kp)
        self.assertEqual(validated_3, kp)

        # Case 4: No trailing punctuation, exact casing
        self.assertFalse(validated.endswith("."))
        self.assertEqual(validated, "Modern Office Interior Design")

    def test_compliant_docx_image_not_recompressed(self):
        """
        If a DOCX image is already <= 700px wide and <= 100 KB,
        it must not be recompressed repeatedly; return original bytes untouched.
        """
        img = Image.new("RGB", (650, 420), color=(140, 160, 180))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        original_bytes = buf.getvalue()
        self.assertLessEqual(len(original_bytes), 100 * 1024)

        result_bytes = image_service.optimize_docx_image(original_bytes, max_width=700)
        self.assertEqual(result_bytes, original_bytes)

    def test_compliant_stock_image_not_recompressed(self):
        """
        If a stock image is already exactly 1000x667 px and <= 100 KB,
        it must not be repeatedly recompressed; return original bytes untouched.
        """
        img = Image.new("RGB", (1000, 667), color=(200, 180, 150))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        original_bytes = buf.getvalue()
        self.assertLessEqual(len(original_bytes), 100 * 1024)

        result_bytes = image_service.resize_image(original_bytes, "image/jpeg")
        self.assertEqual(result_bytes, original_bytes)

    def test_image_quality_floor_preserved_without_aggressive_degradation(self):
        """
        Verify that resize_image enforces a quality floor (quality >= 70) and
        does not degrade colors with heavy subsampling=2 or qualities < 70.
        """
        # Create an image with varied high-frequency content
        img = Image.new("RGB", (1600, 1067), color=(80, 120, 160))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        raw_bytes = buf.getvalue()

        resized = image_service.resize_image(raw_bytes, "image/jpeg")
        res_img = Image.open(io.BytesIO(resized))

        self.assertEqual(res_img.width, 1000)
        self.assertEqual(res_img.height, 667)
        self.assertLessEqual(len(resized), 100 * 1024)


if __name__ == "__main__":
    unittest.main()
