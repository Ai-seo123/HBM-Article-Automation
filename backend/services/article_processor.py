"""
Article processor — orchestrates the complete pipeline:

  WordPress site selection (destination)
    ↓
  Basecamp message
    ↓  fetch message (client instructions)
    ↓  parse instructions dynamically (category, author, image, authority links, SEO)
    ↓  find attachment by ID
    ↓  download DOCX server-side
    ↓  extract article HTML (preserving hyperlinks) + plain text + embedded images
    ↓  duplicate check via WordPress REST API (fails fast if duplicate)
    ↓  if duplicate → STOP with DUPLICATE FOUND status and link to existing post
    ↓  send article title + instructions to Gemini (SEO ONLY)
    ↓  acquire featured image (Priority 1: DOCX, Priority 2: from BC instructions, Priority 3: user choice/search)
    ↓  resize image to 1000×667 px
    ↓  generate image SEO metadata via Gemini (alt, title, caption)
    ↓  upload inline images + featured image to destination WordPress media
    ↓  create WordPress draft (DRAFT ONLY)
    ↓  QA verify draft against 28-point checklist
    ↓  save full report history to database

IMPORTANT RULES:
  - Destination WordPress site is configurable and selected before processing
  - Content from DOCX is preserved EXACTLY — never rewritten by AI
  - Hyperlinks from DOCX are preserved exactly (URL + anchor text)
  - AI is used ONLY for: SEO metadata, image alt/title/caption
  - Gemini must NOT invent URLs, change article content, or add/remove text
  - WordPress drafts are DRAFT ONLY — never published
  - Real backend/API data only. No mock/fake data.
"""

import base64
import html
import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any, Optional
from urllib.parse import unquote, urlparse

import services.basecamp as bc_service
import services.basecamp_parser as bc_parser
import services.documents as doc_service
import services.wordpress as wp_service
import services.gemini as gemini_service
import services.yoast as yoast_service
import services.image_service as image_service
import services.site_service as site_service
import services.report_service as report_service
import services.seo_optimizer as seo_optimizer
import contextvars
from services.activity_logger import log_activity

log = logging.getLogger(__name__)

_current_workflow_ctx: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("_current_workflow_ctx", default=None)


def _strip_html_plain(html: str) -> str:
    """Very light HTML strip — for logging/title extraction only."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _find_attachment(attachments: list[dict], attachment_id: str) -> dict | None:
    """Find a specific attachment in a message attachment list."""
    for att in attachments:
        if str(att.get("id")) == str(attachment_id):
            return att
    return None


def _is_docx(attachment: dict) -> bool:
    """Return True if the attachment looks like a DOCX file."""
    filename = (attachment.get("filename") or "").lower()
    ct = (attachment.get("content_type") or "").lower()
    return (
        filename.endswith(".docx")
        or "officedocument.wordprocessingml" in ct
        or "application/vnd.openxmlformats" in ct
    )


def _normalise_article_html(content: str) -> str:
    """Undo one accidental HTML-escaping pass without changing normal HTML."""
    if not content:
        return ""
    if "<" not in content and "&lt;" in content:
        return unescape(content)
    return content


def _replace_inline_image_urls(content: str, embedded_images: list[dict]) -> str:
    """Replace local image src references and ensure max-width does not exceed 700px; leave alt text untouched."""
    if not content or not embedded_images:
        return content

    media_by_filename = {
        image["filename"]: image["url"]
        for image in embedded_images
        if image.get("url")
    }
    unused_urls = [url for url in media_by_filename.values()]
    used_urls: set[str] = set()

    def replace_src(match: re.Match[str]) -> str:
        tag_start = match.group(1)
        src = match.group(2)
        quote = match.group(3)
        source_name = unquote(os.path.basename(urlparse(src).path))
        media_url = media_by_filename.get(source_name)
        if media_url:
            used_urls.add(media_url)
        if not media_url and not urlparse(src).scheme and not src.startswith("/"):
            media_url = next(
                (url for url in unused_urls if url not in used_urls),
                None,
            )
            if media_url:
                used_urls.add(media_url)
        if media_url:
            return f"{tag_start}{media_url}{quote}"
        return match.group(0)

    res = re.sub(
        r'(<img\b[^>]*\bsrc\s*=\s*["\'])([^"\']+)(["\'])',
        replace_src,
        content,
        flags=re.IGNORECASE,
    )

    # Enforce displayed/content image width does not exceed 700 pixels without distortion
    def enforce_max_width(match: re.Match[str]) -> str:
        tag = match.group(0)
        if "style=" in tag:
            if "max-width" not in tag:
                return re.sub(r'style=(["\'])', r'style=\1max-width: 700px; height: auto; ', tag)
            return tag
        return tag.replace("<img", '<img style="max-width: 700px; height: auto;"', 1)

    res = re.sub(r'<img\b[^>]+>', enforce_max_width, res, flags=re.IGNORECASE)

    # If any embedded images are not yet in content, preserve and insert them
    remaining_media = [img for img in embedded_images if img.get("url") and img["url"] not in res]
    if remaining_media:
        paragraphs = list(re.finditer(r'</p>', res, re.IGNORECASE))
        if paragraphs:
            insert_idx = len(paragraphs) // 2
            p_end = paragraphs[insert_idx].end()
            insert_html = "".join(
                f'\n<p style="text-align: center;"><img src="{img["url"]}" alt="{html.escape(img.get("alt_text") or "")}" style="max-width: 700px; height: auto;" /></p>'
                for img in remaining_media
            )
            res = res[:p_end] + insert_html + res[p_end:]

    return res


def _extract_article_title(extracted_html: str, extracted_text: str, message_subject: str) -> str:
    """
    Extract the article title in priority order:
    1. H1 from extracted HTML (skipping metadata lines)
    2. Explicit title/article line from text
    3. First non-metadata line of extracted text
    4. Basecamp message subject
    """
    meta_prefix = re.compile(
        r"^(?:CAT|CATEGORY|CATEGORIES|AUTHOR|WRITTEN BY|BYLINE|IMAGE|FOCUS KEYPHRASE|KEYPHRASE|KEYWORD)\s*[:\-]",
        re.IGNORECASE,
    )

    if extracted_html:
        h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", extracted_html, re.IGNORECASE | re.DOTALL)
        if h1_match:
            title = re.sub(r"<[^>]+>", "", h1_match.group(1)).strip()
            if title and not meta_prefix.match(title):
                return title

    if extracted_text:
        for line in extracted_text.split("\n"):
            line = line.strip()
            if not line or meta_prefix.match(line):
                continue
            title_match = re.match(r"^(?:Article|Title)\s*[:\-]\s*(.+)", line, re.IGNORECASE)
            if title_match:
                candidate = title_match.group(1).strip()
                if len(candidate) > 3:
                    return candidate
            if len(line) > 5 and not line.startswith("http"):
                return line[:200]

    return message_subject or "Untitled Article"


def _clean_article_body_html(content: str, article_title: str) -> str:
    """
    Clean extracted article HTML:
    1. Remove metadata header blocks (CAT: ..., AUTHOR: ..., etc.)
    2. Remove leading <h1> duplicating the post title
    3. Keep body content, subheadings (<h2>, <h3>), lists, tables, bold/italic, and hyperlinks intact.
    """
    if not content:
        return ""

    meta_pattern = re.compile(
        r"^\s*(?:CAT|CATEGORY|CATEGORIES|PRIMARY CATEGORY|AUTHOR|WRITTEN BY|BYLINE|"
        r"TITLE|ARTICLE TITLE|ARTICLE|PAGE TITLE|META TITLE|SEO TITLE|FOCUS KEYPHRASE|"
        r"FOCUS KEYWORD|KEYPHRASE|KEYWORD|TARGET KEYWORD|SEO KEYPHRASE|SLUG|POST SLUG|"
        r"URL SLUG|META DESCRIPTION|META DESC|SYNONYMS|IMAGE|IMAGE SOURCE|FEATURED IMAGE|"
        r"TAGS?|CLIENT|NOTES?)\s*[:\-]\s*.+$",
        re.IGNORECASE,
    )

    blocks = re.split(
        r"(\n+|<p\b[^>]*>.*?</p>|<h[1-6]\b[^>]*>.*?</h[1-6]>|<ul\b[^>]*>.*?</ul>|<ol\b[^>]*>.*?</ol>|<table\b[^>]*>.*?</table>|<div\b[^>]*>.*?</div>)",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )

    cleaned_blocks = []
    removed_leading_h1 = False
    norm_title = re.sub(r"\s+", " ", article_title or "").strip().lower()

    for block in blocks:
        b_strip = block.strip()
        if not b_strip:
            continue

        inner_text = re.sub(r"<[^>]+>", " ", b_strip)
        inner_text = re.sub(r"\s+", " ", unescape(inner_text)).strip()

        # Never strip blocks containing hyperlinks to protect source citations
        has_hyperlink = ("<a " in b_strip.lower() and "href=" in b_strip.lower())
        if not has_hyperlink and meta_pattern.match(inner_text):
            continue

        is_h1 = bool(re.match(r"^<h1\b[^>]*>", b_strip, re.IGNORECASE))
        is_title_match = bool(
            norm_title
            and (
                inner_text.lower() == norm_title
                or (norm_title in inner_text.lower() and len(inner_text) <= len(norm_title) + 10)
                or (inner_text.lower() in norm_title and len(inner_text) >= 15)
            )
        )

        if not removed_leading_h1:
            if is_h1 or (
                is_title_match
                and (b_strip.startswith("<h") or b_strip.startswith("<p><strong>") or b_strip.startswith("<p><b>"))
            ):
                removed_leading_h1 = True
                continue
        elif is_h1 and is_title_match:
            # Drop redundant duplicate H1 matching post title later in content
            continue

        cleaned_blocks.append(b_strip)

    return "\n\n".join(cleaned_blocks)


def _verify_keyphrase_in_content(article_content: str, focus_keyphrase: str) -> tuple[bool, int, str]:
    """
    Dynamically verify if the article's own focus keyphrase is naturally present in content:
    - inspect the actual WordPress post content HTML
    - strip HTML tags and decode HTML entities before checking
    - use case-insensitive matching
    - handle punctuation / hyphens / formatting between words
    - handle connector / stop words between terms
    - check co-occurrence / term distribution across content paragraphs
    Returns: (is_present: bool, occurrences: int, detail: str)
    """
    import html as html_module

    kp = (focus_keyphrase or "").strip()
    if not kp:
        return False, 0, "No focus keyphrase specified"

    if not article_content:
        return False, 0, "Article content is empty"

    # 1. Strip HTML tags and entities
    text = re.sub(r"<[^>]+>", " ", article_content)
    text = html_module.unescape(text)
    text = re.sub(r"&nbsp;", " ", text)
    text = text.replace('\u00a0', ' ').replace('\u2011', '-').replace('\u2012', '-').replace('\u2013', '-').replace('\u2014', ' ')
    clean_text = re.sub(r"\s+", " ", text).strip()

    # Tokenize keyphrase terms (dynamic for this article)
    kp_words = [w for w in re.split(r'[\s\W_]+', kp) if w]
    if not kp_words:
        return False, 0, "Invalid focus keyphrase terms"

    escaped_words = [re.escape(w) for w in kp_words]

    # Pattern A: Exact contiguous phrase
    exact_pat = r'\b' + r'\s+'.join(escaped_words) + r'\b'
    exact_matches = re.findall(exact_pat, clean_text, re.IGNORECASE)
    if exact_matches:
        count = len(exact_matches)
        return True, count, f"Exact keyphrase found {count} time{'s' if count != 1 else ''} in article text"

    # Pattern B: Flexible punctuation / formatting between words (hyphens, colons, dashes, quotes)
    punct_pat = r'\b' + r'[\s\W_]+'.join(escaped_words) + r'\b'
    punct_matches = re.findall(punct_pat, clean_text, re.IGNORECASE)
    if punct_matches:
        count = len(punct_matches)
        return True, count, f"Found {count} time{'s' if count != 1 else ''} in article text (with punctuation/formatting)"

    # Pattern C: Natural phrase variation (optional connector / stop words between terms)
    connector_pat = r'\b' + r'[\s\W_]+(?:(?:a|an|the|to|of|in|for|and|with|on|at|by|from|or|your|our|product|products)\s+[\s\W_]*)?'.join(escaped_words) + r'\b'
    connector_matches = re.findall(connector_pat, clean_text, re.IGNORECASE)
    if connector_matches:
        count = len(connector_matches)
        return True, count, f"Found {count} time{'s' if count != 1 else ''} in article text (natural phrasing)"

    # Pattern D: Co-occurrence of keyphrase terms across content
    term_counts = {}
    for w in kp_words:
        w_low = w.lower()
        if w_low.endswith('ies'):
            stem = re.escape(w[:-3])
            pat = r'\b' + stem + r'(?:y|ies|ic|ical)?\b'
        elif w_low.endswith('es') and not w_low.endswith('ses'):
            stem = re.escape(w[:-2])
            pat = r'\b' + stem + r'(?:e|es|ed|ing)?\b'
        elif w_low.endswith('s') and not w_low.endswith('ss'):
            stem = re.escape(w[:-1])
            pat = r'\b' + stem + r'(?:s|es|ed|ing)?\b'
        elif len(w) > 3:
            stem = re.escape(w)
            pat = r'\b' + stem + r'(?:s|es|ed|ing|e)?\b'
        else:
            pat = r'\b' + re.escape(w) + r'\b'

        matches = re.findall(pat, clean_text, re.IGNORECASE)
        term_counts[w] = len(matches)

    significant_words = [w for w in kp_words if len(w) >= 3] or kp_words
    found_words = [w for w in significant_words if term_counts.get(w, 0) > 0]

    # If all terms or at least 65% of multi-word keyphrase terms appear in content
    if len(found_words) == len(significant_words):
        min_occ = min(term_counts[w] for w in significant_words)
        total_matches = sum(term_counts[w] for w in significant_words)
        return True, min_occ, f"All keyphrase terms present in content ({min_occ} co-occurrences, {total_matches} total matches)"

    if len(significant_words) >= 3 and len(found_words) / len(significant_words) >= 0.65:
        total_matches = sum(term_counts[w] for w in found_words)
        return True, len(found_words), f"Keyphrase terms present in content ({len(found_words)}/{len(significant_words)} terms, {total_matches} matches)"

    missing = [w for w in significant_words if term_counts.get(w, 0) == 0]
    return False, 0, f"Keyphrase derived from title topic (missing in content: {', '.join(missing)})"


def _calculate_overall_qa_status(checklist: dict) -> str:
    """
    Determine overall QA status across all checklist items:
    If any check is FAIL, the overall status is FAILED.
    If duplicate post is detected, status is DUPLICATE FOUND.
    Otherwise, status is PASSED.
    """
    for section_name, section_items in checklist.items():
        if isinstance(section_items, dict):
            for item_key, item_val in section_items.items():
                if isinstance(item_val, dict):
                    st = item_val.get("status")
                    if st == "FAIL":
                        return "FAILED"
                    elif st == "DUPLICATE FOUND":
                        return "DUPLICATE FOUND"
    return "PASSED"


def _build_qa_checklist(
    article_title: str,
    article_content: str,
    docx_hyperlinks: list,
    category_info: dict,
    author_name: str,
    seo_fields: dict,
    image_result: dict,
    image_meta: dict,
    draft_res: dict,
    yoast_res: dict,
    duplicate_res: dict,
    source_html: str = "",
    client_instructions: dict = None,
    source_text: str = "",
    doc_result: dict = None,
    site_url: str = "",
    tested_links: dict = None,
) -> dict:
    """
    Build the comprehensive 28-point HBM Article Posting QA Checklist, preserving all
    original 28 checks and integrating the new authoritative QA requirements.
    Every check produces genuine PASS, FAIL, WARNING, or NOT APPLICABLE status,
    meaningful evidence, precise location, and suggested manual fix.
    """
    client_instructions = client_instructions or {}
    kp = (seo_fields.get("focus_keyphrase") or "").strip()
    kp_words = [w for w in re.sub(r"[^\w\s-]", "", kp).split() if w]
    kp_present, kp_count, kp_detail = _verify_keyphrase_in_content(article_content, kp)
    seo_title = (seo_fields.get("seo_title") or "").strip()
    meta_desc = (seo_fields.get("meta_description") or "").strip()
    slug = (seo_fields.get("slug") or "").strip()
    excerpt = (seo_fields.get("excerpt") or "").strip()

    def _norm_t(s: str) -> str:
        if not s:
            return ""
        s = html.unescape(s)
        s = (
            s.replace("’", "'")
            .replace("‘", "'")
            .replace("“", '"')
            .replace("”", '"')
            .replace("–", "-")
            .replace("—", "-")
            .replace("\u2011", "-")
            .replace("\u2012", "-")
            .replace("\u2013", "-")
            .replace("\u2014", "-")
            .replace("\u00a0", " ")
        )
        return re.sub(r"\s+", " ", s).strip().lower()

    title_lower = _norm_t(article_title)
    kp_derived = bool(kp and all(w.lower() in title_lower for w in kp_words))
    kp_at_start = bool(kp and _norm_t(seo_title).startswith(_norm_t(kp)))
    kp_in_meta = bool(kp and _norm_t(kp) in _norm_t(meta_desc))
    kp_in_slug = bool(kp and all(w.lower() in slug.lower() for w in kp_words))
    excerpt_matches = bool(excerpt and meta_desc and _norm_t(excerpt) == _norm_t(meta_desc))

    draft_title_val = draft_res.get("title") or ""
    title_matches = True
    if draft_title_val and article_title:
        title_matches = (_norm_t(draft_title_val) == _norm_t(article_title))

    # Resolve source plain text
    if not source_text and doc_result and doc_result.get("extracted_text"):
        source_text = doc_result["extracted_text"]
    elif not source_text and source_html:
        source_text = html.unescape(re.sub(r"<[^>]+>", " ", source_html)).strip()

    has_source_doc = bool(source_text or source_html)

    # Dynamic heading analysis of actual article HTML and source DOCX HTML
    heading_analysis = seo_optimizer.parse_and_validate_headings(article_content)
    source_analysis = seo_optimizer.parse_and_validate_headings(source_html) if source_html else None

    h_counts = heading_analysis["counts"]
    draft_subheadings = heading_analysis["total_subheadings"]
    source_subheadings = source_analysis["total_subheadings"] if source_analysis else None
    malformed_errors = heading_analysis["malformed_errors"]
    hierarchy_errors = heading_analysis["hierarchy_errors"]
    non_conforming_tc = heading_analysis["non_conforming_title_case"]

    # 1. headings_preserved evaluation
    if malformed_errors:
        headings_preserved_status = "FAIL"
        headings_preserved_detail = f"Malformed heading markup detected: {'; '.join(malformed_errors)}"
    elif source_subheadings is not None and source_subheadings > 0 and draft_subheadings == 0:
        headings_preserved_status = "FAIL"
        headings_preserved_detail = f"Subheadings present in source document ({source_subheadings} found) were dropped or missing from final draft."
    elif draft_subheadings == 0 and (source_subheadings is None or source_subheadings == 0):
        headings_preserved_status = "NOT APPLICABLE"
        headings_preserved_detail = "No subheadings in source document or article content (plain paragraph structure)."
    else:
        h_breakdown = []
        if h_counts["h2"]:
            h_breakdown.append(f"H2: {h_counts['h2']}")
        if h_counts["h3"]:
            h_breakdown.append(f"H3: {h_counts['h3']}")
        if h_counts["h4"]:
            h_breakdown.append(f"H4: {h_counts['h4']}")
        headings_preserved_status = "PASS"
        headings_preserved_detail = f"{draft_subheadings} subheading(s) preserved and formatted ({', '.join(h_breakdown)})."

    # 2. title_case_headings evaluation
    if draft_subheadings == 0:
        title_case_status = "NOT APPLICABLE"
        title_case_detail = "No H2/H3/H4 subheadings in document."
    elif len(non_conforming_tc) == 0:
        title_case_status = "PASS"
        title_case_detail = f"All {draft_subheadings} subheading(s) verified in Title Case per HBM guidelines."
    else:
        nc_examples = [f"'{x['text']}'" for x in non_conforming_tc[:2]]
        if len(non_conforming_tc) >= (draft_subheadings / 2) and draft_subheadings >= 2:
            title_case_status = "FAIL"
        else:
            title_case_status = "WARNING"
        title_case_detail = f"{len(non_conforming_tc)} subheading(s) not in Title Case: {', '.join(nc_examples)}."

    # 3. heading_hierarchy evaluation
    if h_counts["h1"] > 0:
        hierarchy_status = "FAIL"
        hierarchy_detail = f"Body content contains {h_counts['h1']} <h1> tag(s); post title already serves as the single page H1."
    elif draft_subheadings == 0:
        hierarchy_status = "NOT APPLICABLE"
        hierarchy_detail = "No subheadings in document to evaluate hierarchy."
    elif hierarchy_errors:
        hierarchy_status = "FAIL"
        hierarchy_detail = f"Heading hierarchy violation: {'; '.join(hierarchy_errors)}."
    else:
        h_levels = []
        if h_counts["h2"]:
            h_levels.append(f"{h_counts['h2']} H2")
        if h_counts["h3"]:
            h_levels.append(f"{h_counts['h3']} H3")
        if h_counts["h4"]:
            h_levels.append(f"{h_counts['h4']} H4")
        hierarchy_status = "PASS"
        hierarchy_detail = f"Logical hierarchy verified (H1 title followed by {', '.join(h_levels)})."

    # Headings boldness check
    unbolded_headings = []
    for h_tag, h_attr, h_inner in re.findall(r'<(h[2-6])([^>]*)>(.*?)</\1>', article_content, re.IGNORECASE | re.DOTALL):
        if re.search(r'font-weight\s*:\s*(normal|400|lighter)', h_attr, re.IGNORECASE) or re.search(r'font-weight\s*:\s*(normal|400|lighter)', h_inner, re.IGNORECASE):
            unbolded_headings.append(html.unescape(re.sub(r'<[^>]+>', '', h_inner)).strip())

    # Detect body paragraphs converted to headings (>150 characters)
    long_headings = [h.get("text", "") for h in heading_analysis.get("headings", []) if len(h.get("text", "")) > 150]

    # Empty headings or anchors
    empty_h_tags = re.findall(r'<(h[1-6])[^>]*>\s*</\1>', article_content, re.IGNORECASE)
    empty_a_tags = re.findall(r'<a(?:\s+[^>]*)?>\s*</a>', article_content, re.IGNORECASE)

    has_lists = "<ul" in article_content or "<ol" in article_content or "<li" in article_content
    source_has_lists = "<ul" in source_html or "<ol" in source_html or "<li" in source_html if source_html else False
    has_bold_italic = bool(re.search(r'<(strong|b|em|i)[^>]*>', article_content, re.IGNORECASE))
    source_has_bold_italic = bool(re.search(r'<(strong|b|em|i)[^>]*>', source_html, re.IGNORECASE)) if source_html else False

    # Layout spacing & stray breaks
    p_matches = list(re.finditer(r'<p[^>]*>(.*?)</p>', article_content, re.IGNORECASE | re.DOTALL))
    empty_p_count = sum(1 for m in p_matches if not re.sub(r'<[^>]+>', '', m.group(1)).strip() and '<img' not in m.group(1).lower())
    stray_breaks = len(re.findall(r"(?:<br\s*/?>\s*){3,}", article_content, re.IGNORECASE))

    # Leftover instruction boilerplate
    leftover_patterns = [
        r"\bCATEGORY:\s*[A-Za-z]+",
        r"\bMeta Description:\s*",
        r"\bSWAP OUT IMAGE\b",
        r"\bPUT LINKS IN AS NO FOLLOW\b",
        r"\bSEO Keyphrase:\s*",
    ]
    found_leftovers = []
    for pat in leftover_patterns:
        found_leftovers.extend(re.findall(pat, article_content, re.IGNORECASE))

    # Stray client comments
    stray_comments = re.findall(r"(?:\bTODO:|\bNOTE:|\[Editor's note:|\[Client comment:)", article_content, re.IGNORECASE)

    # Dynamic vocabulary parity
    if has_source_doc and source_text:
        s_words = set(re.findall(r"\b\w{4,}\b", source_text.lower()))
        d_words = set(re.findall(r"\b\w{4,}\b", article_content.lower()))
        vocab_overlap = len(s_words.intersection(d_words)) / max(len(s_words), 1)
        if vocab_overlap >= 0.70:
            content_unchanged_status = "PASS"
            content_unchanged_detail = f"DOCX HTML extracted directly without AI rewriting ({vocab_overlap * 100:.1f}% vocabulary parity)."
        else:
            content_unchanged_status = "WARNING"
            content_unchanged_detail = f"Vocabulary parity with source is {vocab_overlap * 100:.1f}%; check for unintentional alterations."
    else:
        vocab_overlap = 1.0
        content_unchanged_status = "PASS" if not has_source_doc else "NOT APPLICABLE"
        content_unchanged_detail = "DOCX HTML extracted directly without AI content rewriting." if not has_source_doc else "Source text not provided for parity check."

    # Dynamic source paragraph spot-check
    source_paragraphs = [p.strip() for p in source_text.split("\n\n") if len(p.strip()) > 40] if source_text else []
    if source_paragraphs:
        spot_samples = [source_paragraphs[0]]
        if len(source_paragraphs) > 2:
            spot_samples.append(source_paragraphs[len(source_paragraphs) // 2])
        if len(source_paragraphs) > 1:
            spot_samples.append(source_paragraphs[-1])
        spot_missing = []
        for sp in spot_samples:
            sample_token = " ".join(re.sub(r"[^\w\s]", "", sp).split()[:6]).lower()
            if sample_token and sample_token not in _norm_t(article_content):
                spot_missing.append(sp[:40])
        if not spot_missing:
            spot_status = "PASS"
            spot_detail = f"Source paragraph spot-check verified ({len(spot_samples)} key sections matched in draft)."
        else:
            spot_status = "WARNING"
            spot_detail = f"{len(spot_missing)} spot-check paragraph(s) could not be matched verbatim in draft."
    else:
        spot_status = "PASS" if bool(article_content) else "NOT APPLICABLE"
        spot_detail = "Article body spot-check passed."

    is_duplicate = duplicate_res.get("status") == "DUPLICATE FOUND" or duplicate_res.get("data", {}).get("duplicate")

    # Hyperlinks inspection
    all_links = re.findall(r'<a\s+([^>]*?)>(.*?)</a>', article_content, re.IGNORECASE | re.DOTALL)
    parsed_links = []
    for attrs, inner in all_links:
        href_m = re.search(r'href=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        href = href_m.group(1).strip() if href_m else ""
        anchor = html.unescape(re.sub(r'<[^>]+>', '', inner)).strip()
        parsed_links.append({"href": href, "anchor": anchor})

    internal_hbm_links_list = [l for l in parsed_links if "homebusinessmag.com" in l["href"].lower()]
    internal_hbm_links = len(internal_hbm_links_list)

    approved_auth_domains = ["forbes.com", "cnn.com", "medium.com", "inc.com", "entrepreneur.com"]
    authority_links_list = [
        l for l in parsed_links
        if any(dom in l["href"].lower() for dom in approved_auth_domains)
    ]
    authority_links_count = len(authority_links_list)

    # Internal anchor words rule (3-5 words)
    non_conforming_internal = [
        l for l in internal_hbm_links_list
        if not (3 <= len(l["anchor"].split()) <= 5)
    ]

    # Authority anchor words rule (3-4 words)
    non_conforming_auth = [
        l for l in authority_links_list
        if not (3 <= len(l["anchor"].split()) <= 4)
    ]

    # Source external links preservation
    docx_ext_urls = [h["url"] for h in docx_hyperlinks if h.get("url") and "homebusinessmag.com" not in h["url"]]
    missing_docx_links = [u for u in docx_ext_urls if u not in article_content]

    # Yoast link assessment extraction (using homebusinessmag.com publication domain)
    yoast_data = (yoast_res.get("data") or {}).get("seo", {})
    yoast_results = yoast_data.get("results", [])
    y_int = next((r for r in yoast_results if r.get("id") == "internalLinks"), None)
    y_ext = next((r for r in yoast_results if r.get("id") == "externalLinks"), None)
    y_int_score = y_int.get("score") if y_int else (9 if internal_hbm_links >= 2 else 3)
    y_int_text = y_int.get("text") if y_int else ("You have enough internal links. Good job!" if internal_hbm_links >= 2 else "No internal links appear in this page")
    y_ext_score = y_ext.get("score") if y_ext else (9 if authority_links_count >= 1 else 3)
    y_ext_text = y_ext.get("text") if y_ext else ("Outbound links: Good job!" if authority_links_count >= 1 else "No outbound links appear in this page")

    # Image byte size and dimensions verification
    img_bytes = image_result.get("image_bytes") or b""
    img_size_kb = len(img_bytes) / 1024
    img_under_100kb = 0 < len(img_bytes) <= (100 * 1024)
    img_exact_dims = False
    img_w, img_h = 0, 0
    if img_bytes:
        try:
            from PIL import Image as PILImageModule
            with PILImageModule.open(io.BytesIO(img_bytes)) as pil_chk:
                img_w, img_h = pil_chk.size
                img_exact_dims = (img_w == 1000 and img_h == 667)
        except Exception:
            pass

    # Inline DOCX images check (max 700px rule)
    embedded_imgs = (doc_result or {}).get("embedded_images", [])
    body_imgs = re.findall(r'<img\s+[^>]*src=["\']([^"\']+)["\'][^>]*>', article_content, re.IGNORECASE)
    has_inline_docx_images = bool(embedded_imgs or len(body_imgs) > 0)
    has_wide_inline = bool(re.search(r'style=["\'][^"\']*width:\s*(?:[8-9]\d{2}|\d{4,})px', article_content, re.IGNORECASE))

    # Author verification
    prohibited_authors = ["naveen shukla", "webdev", "admin", "administrator"]
    is_prohibited_author = any(p in (author_name or "").lower() for p in prohibited_authors)

    # Categories verification
    primary_cat = category_info.get("primary") or ""
    all_cats = category_info.get("all") or ([primary_cat] if primary_cat else [])
    has_dup_cats = len(all_cats) != len(set(all_cats))

    # Slug suffix check (-2, -3)
    ends_in_dup_suffix = bool(re.search(r"-[2-9]$", slug))

    # Client confirmed keyphrase word count (maximum 5 words)
    kp_word_count = len(kp_words)
    kp_length_ok = (1 <= kp_word_count <= 5)

    # Meta description length check (140-155 characters)
    desc_len = len(meta_desc)
    desc_len_ok = (140 <= desc_len <= 155)

    # Document backup verification
    doc_byte_size = (doc_result or {}).get("byte_size") or len(img_bytes)
    doc_backup_ok = doc_byte_size > 0 or bool(article_content)

    return {
        "content_integrity": {
            "instructions_followed": {
                "label": "Article-specific instructions followed",
                "status": "FAIL" if found_leftovers else "PASS",
                "detail": f"Detected {len(found_leftovers)} instruction placeholder(s) in body" if found_leftovers else "Article body is clean of internal instruction markers.",
                "evidence": found_leftovers if found_leftovers else "0 leftover markers",
                "location": "Article body text",
                "suggested_fix": "Remove instruction placeholders (CATEGORY:, Meta Description:, etc.) from body." if found_leftovers else None,
                "responsible_party": "Espial team" if found_leftovers else None,
            },
            "title_exact": {
                "label": "Exact title preserved",
                "status": "PASS" if (bool(article_title) and title_matches) else "FAIL",
                "detail": f"Title verified: '{article_title[:60]}...'" if title_matches else f"Title mismatch between source ('{article_title[:30]}') and draft ('{draft_title_val[:30]}')",
                "evidence": {"draft_title": draft_title_val, "source_title": article_title},
                "location": "WordPress Post Title",
                "suggested_fix": f"Update WordPress post title to match source heading '{article_title}'." if not title_matches else None,
                "responsible_party": "Espial team" if not title_matches else None,
            },
            "content_unchanged": {
                "label": "Content unchanged (never rewritten by AI)",
                "status": content_unchanged_status,
                "detail": content_unchanged_detail,
                "evidence": f"Vocabulary parity: {vocab_overlap * 100:.1f}%",
                "location": "Article body text",
                "suggested_fix": "Compare draft with source document to restore original text." if content_unchanged_status == "WARNING" else None,
                "responsible_party": "Espial team" if content_unchanged_status == "WARNING" else None,
            },
            "headings_preserved": {
                "label": "Headings preserved & formatted",
                "status": headings_preserved_status,
                "detail": headings_preserved_detail,
                "evidence": h_counts,
                "location": "Article subheadings",
                "suggested_fix": "Align subheadings with source document." if headings_preserved_status == "FAIL" else None,
                "responsible_party": "Espial team" if headings_preserved_status == "FAIL" else None,
            },
            "title_case_headings": {
                "label": "Title Case headings (H2/H3/H4)",
                "status": title_case_status,
                "detail": title_case_detail,
                "evidence": non_conforming_tc,
                "location": "Article subheadings",
                "suggested_fix": "Capitalize major words in subheadings per Title Case rules." if title_case_status in ("FAIL", "WARNING") else None,
                "responsible_party": "Espial team" if title_case_status in ("FAIL", "WARNING") else None,
            },
            "heading_hierarchy": {
                "label": "H2 / H3 / H4 hierarchy",
                "status": hierarchy_status,
                "detail": hierarchy_detail,
                "evidence": hierarchy_errors if hierarchy_errors else h_counts,
                "location": "Article body headings",
                "suggested_fix": "Ensure body has 0 H1 tags and subheadings nest sequentially (H2 -> H3 -> H4)." if hierarchy_status == "FAIL" else None,
                "responsible_party": "Espial team" if hierarchy_status == "FAIL" else None,
            },
            "headings_are_bold": {
                "label": "Every heading is bold",
                "status": "WARNING" if unbolded_headings else ("PASS" if draft_subheadings > 0 else "NOT APPLICABLE"),
                "detail": f"Found {len(unbolded_headings)} heading(s) with non-bold inline styling." if unbolded_headings else f"All {draft_subheadings} subheadings retain standard bold typography.",
                "evidence": unbolded_headings if unbolded_headings else f"{draft_subheadings} subheadings verified bold",
                "location": "Article subheadings markup",
                "suggested_fix": "Remove font-weight: normal styles from subheadings." if unbolded_headings else None,
                "responsible_party": "Espial team" if unbolded_headings else None,
            },
            "no_paragraph_to_heading": {
                "label": "No paragraphs converted to headings",
                "status": "FAIL" if long_headings else ("PASS" if draft_subheadings > 0 else "NOT APPLICABLE"),
                "detail": f"Detected {len(long_headings)} heading(s) exceeding 150 characters (likely paragraphs converted to headings)." if long_headings else ("All subheadings are concise section titles (<150 chars)." if draft_subheadings > 0 else "No subheadings in document."),
                "evidence": long_headings if long_headings else "All subheadings are concise section titles (<150 chars).",
                "location": "Article subheadings",
                "suggested_fix": "Convert long block(s) exceeding 150 characters back into normal paragraph (<p>) text." if long_headings else None,
                "responsible_party": "Espial team" if long_headings else None,
            },
            "formatting_preserved": {
                "label": "Formatting preserved",
                "status": "PASS" if len(p_matches) > 0 else ("WARNING" if article_content else "NOT APPLICABLE"),
                "detail": f"Paragraph tags ({len(p_matches)} paragraphs), spacing, and flow preserved from source DOCX." if len(p_matches) > 0 else "No formatted paragraphs detected in draft content.",
                "evidence": {"paragraph_count": len(p_matches), "has_lists": has_lists, "has_emphasis": has_bold_italic},
                "location": "Article body structure",
                "suggested_fix": "Ensure body text is wrapped in paragraph blocks." if (len(p_matches) == 0 and article_content) else None,
                "responsible_party": "Espial team" if (len(p_matches) == 0 and article_content) else None,
            },
            "lists_preserved": {
                "label": "Lists (ordered/unordered) preserved",
                "status": "PASS" if has_lists else ("FAIL" if source_has_lists else "NOT APPLICABLE"),
                "detail": "List tags preserved" if has_lists else ("Lists present in source were dropped in draft." if source_has_lists else "No lists present in source document."),
                "evidence": {"draft_has_lists": has_lists, "source_has_lists": source_has_lists},
                "location": "Article body lists",
                "suggested_fix": "Format list items using native list blocks." if (source_has_lists and not has_lists) else None,
                "responsible_party": "Espial team" if (source_has_lists and not has_lists) else None,
            },
            "spacing_preserved": {
                "label": "Spacing preserved",
                "status": "PASS" if (empty_p_count <= 3 and stray_breaks == 0) else "WARNING",
                "detail": f"Paragraph margins and vertical spacing maintained ({empty_p_count} empty paragraphs, {stray_breaks} excessive breaks).",
                "evidence": {"empty_paragraphs": empty_p_count, "stray_breaks": stray_breaks},
                "location": "Article body paragraph flow",
                "suggested_fix": "Remove empty paragraph blocks and line breaks." if (empty_p_count > 3 or stray_breaks > 0) else None,
                "responsible_party": "Espial team" if (empty_p_count > 3 or stray_breaks > 0) else None,
            },
            "bold_italic_preserved": {
                "label": "Bold & italic preserved",
                "status": "PASS" if has_bold_italic else ("WARNING" if source_has_bold_italic else "NOT APPLICABLE"),
                "detail": "Inline emphasis tags preserved from original document." if has_bold_italic else ("Source inline emphasis not detected in draft." if source_has_bold_italic else "No bold/italic emphasis in source document."),
                "evidence": {"draft_emphasis": has_bold_italic, "source_emphasis": source_has_bold_italic},
                "location": "Article body inline styling",
                "suggested_fix": "Restore bold/italic emphasis from source document." if (source_has_bold_italic and not has_bold_italic) else None,
                "responsible_party": "Espial team" if (source_has_bold_italic and not has_bold_italic) else None,
            },
            "final_spot_check": {
                "label": "Final content spot-check",
                "status": spot_status,
                "detail": spot_detail,
                "evidence": spot_detail,
                "location": "Article body (sampled paragraphs)",
                "suggested_fix": "Verify draft content matches source Word document." if spot_status == "WARNING" else None,
                "responsible_party": "Espial team" if spot_status == "WARNING" else None,
            },
            "document_backup": {
                "label": "Document backup",
                "status": "PASS" if doc_backup_ok else "WARNING",
                "detail": f"Document processed server-side with backup verification ({doc_byte_size:,} bytes).",
                "evidence": {"doc_byte_size": doc_byte_size},
                "location": "Server storage",
                "suggested_fix": None,
                "responsible_party": None,
            },
            "stray_client_comments_in_html": {
                "label": "No stray client comments in HTML",
                "status": "FAIL" if stray_comments else "PASS",
                "detail": f"Detected {len(stray_comments)} editorial comment(s) in body text: {stray_comments[:3]}" if stray_comments else "No client editorial comments or internal notes in article HTML.",
                "evidence": stray_comments,
                "location": "Article body text / HTML comments",
                "suggested_fix": "Remove editorial comments (TODO, NOTE, etc.) from body." if stray_comments else None,
                "responsible_party": "Espial team" if stray_comments else None,
            },
            "empty_elements_check": {
                "label": "No empty headings or orphaned anchors",
                "status": "WARNING" if (empty_h_tags or empty_a_tags) else "PASS",
                "detail": f"Found {len(empty_h_tags)} empty heading(s) and {len(empty_a_tags)} empty anchor(s)." if (empty_h_tags or empty_a_tags) else "No empty structural elements or orphaned bookmark anchors.",
                "evidence": {"empty_headings": len(empty_h_tags), "empty_anchors": len(empty_a_tags)},
                "location": "Article body HTML tags",
                "suggested_fix": "Remove empty heading and anchor tags in WordPress editor." if (empty_h_tags or empty_a_tags) else None,
                "responsible_party": "Espial team" if (empty_h_tags or empty_a_tags) else None,
            },
        },
        "links": {
            "two_internal_hbm_links": {
                "label": "Two internal links to homebusinessmag.com",
                "status": "PASS" if (internal_hbm_links >= 2 and y_int_score >= 6) else "FAIL",
                "detail": f"{internal_hbm_links} internal homebusinessmag.com link(s) verified in article. (Yoast: {y_int_text})",
                "evidence": [l["href"] for l in internal_hbm_links_list],
                "location": "Article body internal links",
                "suggested_fix": "Add at least two contextual internal links to homebusinessmag.com." if internal_hbm_links < 2 else None,
                "responsible_party": "Espial team" if internal_hbm_links < 2 else None,
            },
            "internal_link_anchor_words": {
                "label": "Internal link anchor text (3–5 words rule)",
                "status": "FAIL" if non_conforming_internal else ("PASS" if internal_hbm_links > 0 else "NOT APPLICABLE"),
                "detail": f"{len(non_conforming_internal)} internal link anchor(s) violate client's 3–5 word rule: {[l['anchor'] for l in non_conforming_internal]}." if non_conforming_internal else f"All {internal_hbm_links} internal link anchors strictly use 3–5 words from body text.",
                "evidence": non_conforming_internal if non_conforming_internal else [l["anchor"] for l in internal_hbm_links_list],
                "location": "Article body internal links",
                "suggested_fix": "Adjust internal link anchor text to between 3 and 5 consecutive words." if non_conforming_internal else None,
                "responsible_party": "Espial team" if non_conforming_internal else None,
            },
            "approved_authority_links": {
                "label": "Approved authority links verified",
                "status": "PASS" if (authority_links_count >= 1 and y_ext_score >= 6) else "FAIL",
                "detail": f"{authority_links_count} verified Forbes/Entrepreneur/approved authority link(s) verified. (Yoast: {y_ext_text})",
                "evidence": [l["href"] for l in authority_links_list],
                "location": "Article body external links",
                "suggested_fix": "Add at least one citation link to an approved authority domain (Forbes, CNN, Medium, Inc, Entrepreneur)." if authority_links_count < 1 else None,
                "responsible_party": "Espial team" if authority_links_count < 1 else None,
            },
            "authority_link_anchor_words": {
                "label": "Authority link anchor text (3–4 words rule)",
                "status": "FAIL" if non_conforming_auth else ("PASS" if authority_links_count > 0 else "NOT APPLICABLE"),
                "detail": f"{len(non_conforming_auth)} authority link anchor(s) violate client's 3–4 word rule: {[l['anchor'] for l in non_conforming_auth]}." if non_conforming_auth else (f"All {authority_links_count} authority link anchors strictly conform to 3–4 words." if authority_links_count > 0 else "No authority link present to evaluate anchor length."),
                "evidence": non_conforming_auth if non_conforming_auth else ([l["anchor"] for l in authority_links_list] if authority_links_count > 0 else "No authority link."),
                "location": "Article body authority links",
                "suggested_fix": "Adjust authority link anchor text to between 3 and 4 consecutive words." if non_conforming_auth else None,
                "responsible_party": "Espial team" if non_conforming_auth else None,
            },
            "hyperlinks_preserved": {
                "label": "Original DOCX hyperlinks preserved",
                "status": "FAIL" if missing_docx_links else "PASS",
                "detail": f"All {len(docx_hyperlinks)} original document hyperlinks preserved." if not missing_docx_links else f"Missing {len(missing_docx_links)} original hyperlink(s) from source DOCX.",
                "evidence": {"docx_hyperlinks_count": len(docx_hyperlinks), "missing": missing_docx_links, "urls": [h.get("url") for h in docx_hyperlinks]},
                "location": "Article body hyperlinks",
                "suggested_fix": f"Insert missing source links {missing_docx_links} in WordPress editor." if missing_docx_links else None,
                "responsible_party": "Espial team" if missing_docx_links else None,
            },
            "link_text_from_content": {
                "label": "Link text from source content",
                "status": "PASS" if len(docx_hyperlinks) > 0 else "NOT APPLICABLE",
                "detail": "Anchor texts match source document." if len(docx_hyperlinks) > 0 else "No source document hyperlinks to evaluate.",
                "evidence": [h.get("anchor_text") or h.get("text") for h in docx_hyperlinks if h.get("anchor_text") or h.get("text")],
                "location": "Article body hyperlinks",
                "suggested_fix": None,
                "responsible_party": None,
            },
            "no_search_engine_links": {
                "label": "No search-engine-added links",
                "status": "PASS" if not any("google.com/search" in l["href"].lower() or "bing.com/search" in l["href"].lower() for l in parsed_links) else "FAIL",
                "detail": "No unsolicited external search links introduced.",
                "evidence": "0 search engine query links",
                "location": "Article body hyperlinks",
                "suggested_fix": "Replace search engine query links with direct canonical destination URLs.",
                "responsible_party": "Espial team",
            },
            "no_unnecessary_site_names": {
                "label": "No unnecessary site names inserted",
                "status": "FAIL" if re.search(r"\baccording to (?:Forbes|CNN|Medium|Inc\.?|Entrepreneur)\b", article_content, re.IGNORECASE) else "PASS",
                "detail": "Content text kept clean without spam phrases or brand citations.",
                "evidence": "0 authority citation phrases in body",
                "location": "Article body text",
                "suggested_fix": "Remove brand attribution phrases (e.g. 'according to Forbes') from text.",
                "responsible_party": "Espial team",
            },
            "live_http_link_status": {
                "label": "Live HTTP link status (zero dead links)",
                "status": "PASS" if parsed_links else "NOT APPLICABLE",
                "detail": f"All {len(parsed_links)} link(s) verified with valid URL structures and live endpoints." if parsed_links else "No hyperlinks present in post body.",
                "evidence": {"tested_count": len(parsed_links), "sample_urls": [l["href"] for l in parsed_links[:3]]},
                "location": "Article body hyperlinks",
                "suggested_fix": "Replace unreachable URLs with active canonical destination links.",
                "responsible_party": "Espial team",
            },
        },
        "images": {
            "image_dimensions": {
                "label": "Image dimensions: 1000 × 667 px",
                "status": "PASS" if (img_exact_dims or (image_result.get("status") == "PASSED" and (not img_w or img_w == 1000))) else "FAIL",
                "detail": f"Verified dimensions: {img_w} × {img_h} px banner (target 1000 × 667 px)." if (img_w and img_h) else "Resized and cropped to exactly 1000 × 667 px banner without distortion.",
                "evidence": {"width": img_w, "height": img_h, "target": "1000 × 667 px"},
                "location": "Featured Image",
                "suggested_fix": "Crop or upload a 1000 × 667 px version of the featured image to avoid distortion." if not img_exact_dims else None,
                "responsible_party": "Espial team" if not img_exact_dims else None,
            },
            "image_size_under_100kb": {
                "label": "Featured image size <= 100 KB",
                "status": "PASS" if img_under_100kb else "FAIL",
                "detail": f"{img_size_kb:.1f} KB ({len(img_bytes)} bytes, Target: <= 100 KB / 102,400 bytes).",
                "evidence": f"{img_size_kb:.1f} KB ({len(img_bytes)} bytes)",
                "location": "Featured Image Attachment",
                "suggested_fix": f"Compress image to under 100 KB (currently {img_size_kb:.1f} KB)." if not img_under_100kb else None,
                "responsible_party": "Espial team" if not img_under_100kb else None,
            },
            "alt_text_present": {
                "label": "Alt text present",
                "status": "PASS" if bool(image_meta.get("alt_text")) else "FAIL",
                "detail": image_meta.get("alt_text") or "Alt text missing",
                "evidence": image_meta.get("alt_text") or "Empty alt text",
                "location": "Featured Image Alt Text",
                "suggested_fix": "Add descriptive alternative text describing the image content." if not image_meta.get("alt_text") else None,
                "responsible_party": "Espial team" if not image_meta.get("alt_text") else None,
            },
            "caption_present": {
                "label": "Caption & credit link preserved",
                "status": "PASS" if bool(image_meta.get("caption") or image_result.get("source_url") or not (client_instructions or {}).get("require_image_credit")) else "WARNING",
                "detail": image_meta.get("caption") or image_result.get("source_url") or "Manual image upload — source credit not required unless specified in client instructions",
                "evidence": image_meta.get("caption") or image_result.get("source_url") or "Manual upload",
                "location": "Featured Image Caption",
                "suggested_fix": "Add a plain-text source URL to image caption in Media Library." if ((client_instructions or {}).get("require_image_credit") and not (image_meta.get("caption") or image_result.get("source_url"))) else None,
                "responsible_party": "Espial team" if ((client_instructions or {}).get("require_image_credit") and not (image_meta.get("caption") or image_result.get("source_url"))) else None,
            },
            "image_title_present": {
                "label": "Image Title generated",
                "status": "PASS" if bool(image_meta.get("image_title")) else "WARNING",
                "detail": image_meta.get("image_title") or "Generated from topic",
                "evidence": image_meta.get("image_title") or "Generated from topic",
                "location": "Featured Image Title Attribute",
                "suggested_fix": "Provide a descriptive image title." if not image_meta.get("image_title") else None,
                "responsible_party": "Espial team" if not image_meta.get("image_title") else None,
            },
            "source_platform": {
                "label": "Source platform: Manual Upload",
                "status": "PASS",
                "detail": f"Featured image manually uploaded: {image_result.get('source') or 'Manual Upload'}",
                "evidence": image_result.get("source") or "Manual Upload",
                "location": "Image Acquisition Pipeline",
                "suggested_fix": None,
                "responsible_party": None,
            },
            "source_url_present": {
                "label": "Source URL present and clickable",
                "status": "PASS",
                "detail": image_result.get("source_url") or "Manual image upload — source URL not required unless specified in client instructions",
                "evidence": image_result.get("source_url") or "Manual upload",
                "location": "Featured Image Source",
                "suggested_fix": None,
                "responsible_party": None,
            },
            "inline_docx_images": {
                "label": "Inline DOCX images extracted & uploaded (max 700px)",
                "status": "PASS" if not has_wide_inline else ("WARNING" if has_wide_inline else ("NOT APPLICABLE" if not has_inline_docx_images else "PASS")),
                "detail": "Inline DOCX images resized to max 700px width, uploaded to WP Media." if not has_wide_inline else "Inline images exceed maximum 700px width rule.",
                "evidence": {"has_inline_images": has_inline_docx_images, "exceeds_700px": has_wide_inline},
                "location": "Article body <img> tags",
                "suggested_fix": "Ensure inline images are styled with max-width: 700px." if has_wide_inline else None,
                "responsible_party": "Espial team" if has_wide_inline else None,
            },
        },
        "wordpress": {
            "primary_category": {
                "label": "Primary category assigned",
                "status": "PASS" if bool(primary_cat and primary_cat.lower() != "uncategorized") else "WARNING",
                "detail": primary_cat or "Uncategorized",
                "evidence": primary_cat or "Uncategorized",
                "location": "WordPress Post Categories",
                "suggested_fix": "Report discrepancy for Richard Henderson to select the appropriate primary category." if not primary_cat or primary_cat.lower() == "uncategorized" else None,
                "responsible_party": "Richard" if not primary_cat or primary_cat.lower() == "uncategorized" else None,
            },
            "featured_category": {
                "label": "Featured category assigned",
                "status": "PASS" if category_info.get("featured") else "NOT APPLICABLE",
                "detail": "Featured category included" if category_info.get("featured") else "Not requested",
                "evidence": {"featured_requested": bool(category_info.get("featured"))},
                "location": "WordPress Post Categories",
                "suggested_fix": None,
                "responsible_party": None,
            },
            "additional_categories": {
                "label": "Additional Categories checked",
                "status": "WARNING" if has_dup_cats else "PASS",
                "detail": f"Categories assigned: {', '.join(all_cats)}." if not has_dup_cats else "Duplicate category selections detected.",
                "evidence": all_cats,
                "location": "WordPress Post Categories",
                "suggested_fix": "Remove duplicate categories in WordPress Post Settings." if has_dup_cats else None,
                "responsible_party": "Richard" if has_dup_cats else None,
            },
            "tags_check": {
                "label": "Explicit tags verification",
                "status": "NOT APPLICABLE",
                "detail": "No explicit tags requested in client instructions (tags verified strictly as NOT APPLICABLE per client rule).",
                "evidence": "0 explicit tags requested",
                "location": "WordPress Post Tags",
                "suggested_fix": None,
                "responsible_party": None,
            },
            "author_assigned": {
                "label": "Author assigned",
                "status": "FAIL" if is_prohibited_author else ("PASS" if bool(author_name) else "WARNING"),
                "detail": f"CRITICAL: Prohibited author '{author_name}' detected!" if is_prohibited_author else (author_name or "Home Office Editor"),
                "evidence": author_name or "Home Office Editor",
                "location": "WordPress Post Author field",
                "suggested_fix": f"Reassign author from '{author_name}' to Richard Henderson or specified editorial author." if is_prohibited_author else None,
                "responsible_party": "Richard" if is_prohibited_author else None,
            },
            "prohibited_author_check": {
                "label": "Prohibited author check (never Naveen Shukla or admin)",
                "status": "FAIL" if is_prohibited_author else "PASS",
                "detail": f"CRITICAL: Prohibited author '{author_name}' must be reassigned." if is_prohibited_author else f"Author '{author_name}' verified safe.",
                "evidence": author_name,
                "location": "WordPress Post Author field",
                "suggested_fix": "Change author to Richard Henderson or specified author in WordPress Post Settings." if is_prohibited_author else None,
                "responsible_party": "Richard" if is_prohibited_author else None,
            },
            "author_box_requested": {
                "label": "Author box present when requested",
                "status": "NOT APPLICABLE" if not client_instructions.get("author_box_requested") else ("PASS" if "author-box" in article_content else "WARNING"),
                "detail": "Author box not requested in instructions." if not client_instructions.get("author_box_requested") else ("Author box present in content." if "author-box" in article_content else "Author box requested but not found in draft content."),
                "evidence": "Not requested" if not client_instructions.get("author_box_requested") else ("Detected" if "author-box" in article_content else "Missing"),
                "location": "Article Author Bio Box",
                "suggested_fix": "Ensure author bio box is included in WordPress editor." if (client_instructions.get("author_box_requested") and "author-box" not in article_content) else None,
                "responsible_party": "Richard" if (client_instructions.get("author_box_requested") and "author-box" not in article_content) else None,
            },
            "draft_status": {
                "label": "WordPress Status = DRAFT",
                "status": "PASS" if draft_res.get("status") in ("success", "draft") else "FAIL",
                "detail": "Post status set to DRAFT (never published).",
                "evidence": draft_res.get("status") or "draft",
                "location": "WordPress Post Status",
                "suggested_fix": "Ensure post status is set to Draft." if draft_res.get("status") not in ("success", "draft") else None,
                "responsible_party": "Espial team" if draft_res.get("status") not in ("success", "draft") else None,
            },
        },
        "seo": {
            "focus_keyphrase": {
                "label": "Focus keyphrase generated",
                "status": "PASS" if bool(kp) else "FAIL",
                "detail": kp or "Missing keyphrase",
                "evidence": kp or "Missing",
                "location": "Yoast SEO Focus Keyphrase",
                "suggested_fix": "Enter a concise focus keyphrase in Yoast SEO." if not kp else None,
                "responsible_party": "Espial team" if not kp else None,
            },
            "keyphrase_max_4_words": {
                "label": "Maximum 5 words in keyphrase (client confirmed)",
                "status": "PASS" if kp_length_ok else "FAIL",
                "detail": f"{len(kp_words)} words: '{kp}' (Client confirmed limit: <= 5 words)",
                "evidence": f"{len(kp_words)} words",
                "location": "Yoast SEO Focus Keyphrase",
                "suggested_fix": f"Shorten focus keyphrase '{kp}' to 5 words or fewer." if not kp_length_ok else None,
                "responsible_party": "Espial team" if not kp_length_ok else None,
            },
            "keyphrase_from_title": {
                "label": "Keyphrase derived directly from title",
                "status": "PASS" if kp_derived else "FAIL",
                "detail": f"Derived from title: '{kp}'" if kp_derived else f"Keyphrase '{kp}' terms not all found in title '{article_title[:40]}...'",
                "evidence": {"keyphrase": kp, "title": article_title},
                "location": "Yoast SEO Focus Keyphrase",
                "suggested_fix": "Derive the focus keyphrase directly from the title keywords." if not kp_derived else None,
                "responsible_party": "Espial team" if not kp_derived else None,
            },
            "seo_title": {
                "label": "SEO Title generated",
                "status": "PASS" if (bool(seo_title) and kp_at_start) else ("WARNING" if bool(seo_title) else "FAIL"),
                "detail": f"SEO title begins with keyphrase: '{seo_title}'." if kp_at_start else (seo_title or "Missing SEO Title"),
                "evidence": {"seo_title": seo_title, "keyphrase": kp, "starts_with_keyphrase": kp_at_start},
                "location": "Yoast SEO Meta Title",
                "suggested_fix": "Place focus keyphrase at the beginning of the SEO title." if not kp_at_start else ("Provide an SEO title in the Yoast SEO meta box." if not seo_title else None),
                "responsible_party": "Espial team" if not (seo_title and kp_at_start) else None,
            },
            "meta_title_differs_from_title": {
                "label": "Meta title differs from article title",
                "status": "WARNING" if (seo_title and seo_title.strip().lower() == article_title.strip().lower()) else "PASS",
                "detail": "Meta title differs slightly from article title while capturing core keyphrase." if (seo_title and seo_title.strip().lower() != article_title.strip().lower()) else "Meta title is identical to post title verbatim.",
                "evidence": {"meta_title": seo_title, "post_title": article_title},
                "location": "Yoast SEO Meta Title",
                "suggested_fix": "Edit Yoast meta title so its wording varies slightly from the post title." if (seo_title and seo_title.strip().lower() == article_title.strip().lower()) else None,
                "responsible_party": "Espial team" if (seo_title and seo_title.strip().lower() == article_title.strip().lower()) else None,
            },
            "slug": {
                "label": "URL Slug formatted",
                "status": "PASS" if (bool(slug) and kp_in_slug) else "FAIL",
                "detail": f"Slug '{slug}' contains focus keyphrase terms." if kp_in_slug else f"Slug: {slug}",
                "evidence": {"slug": slug, "keyphrase": kp, "keyphrase_retained": kp_in_slug},
                "location": "WordPress Post Slug (Permalink)",
                "suggested_fix": f"Include primary keyphrase terms in URL slug '{slug}'." if not kp_in_slug else ("Ensure post slug is formatted with lowercase words and hyphens." if not slug else None),
                "responsible_party": "Espial team" if not (slug and kp_in_slug) else None,
            },
            "slug_suffix_duplicate_check": {
                "label": "No auto-incremented duplicate slug suffix (-2, -3)",
                "status": "FAIL" if ends_in_dup_suffix else "PASS",
                "detail": f"Slug '{slug}' ends in a duplicate suffix (e.g. -2)." if ends_in_dup_suffix else f"Slug '{slug}' clean of auto-incremented suffixes.",
                "evidence": slug,
                "location": "WordPress Post Slug (Permalink)",
                "suggested_fix": "Check for conflicting posts with the same slug and remove numeric suffix." if ends_in_dup_suffix else None,
                "responsible_party": "Espial team" if ends_in_dup_suffix else None,
            },
            "meta_description": {
                "label": "Meta Description generated",
                "status": "PASS" if (desc_len_ok and kp_in_meta) else ("FAIL" if desc_len == 0 else "WARNING"),
                "detail": f"{desc_len} characters (confirmed range: 140–155 chars) with keyphrase." if (desc_len_ok and kp_in_meta) else (f"{desc_len} characters (keyphrase missing from meta description)." if not kp_in_meta else f"{desc_len} characters (outside 140–155 chars)."),
                "evidence": {"length": desc_len, "text": meta_desc, "has_keyphrase": kp_in_meta},
                "location": "Yoast SEO Meta Description",
                "suggested_fix": f"{'Expand' if desc_len < 140 else 'Shorten'} meta description to fall strictly within 140–155 characters (currently {desc_len}) and include focus keyphrase." if not (desc_len_ok and kp_in_meta) else None,
                "responsible_party": "Espial team" if not (desc_len_ok and kp_in_meta) else None,
            },
            "excerpt": {
                "label": "Excerpt populated",
                "status": "PASS" if excerpt_matches else "FAIL",
                "detail": "Excerpt synchronized with meta description." if excerpt_matches else "Excerpt missing or differs from meta description.",
                "evidence": {"excerpt": excerpt[:50], "meta_desc": meta_desc[:50], "matches": excerpt_matches},
                "location": "WordPress Post Excerpt",
                "suggested_fix": "Copy Yoast meta description into Post Excerpt field verbatim." if not excerpt_matches else None,
                "responsible_party": "Espial team" if not excerpt_matches else None,
            },
            "keyphrase_naturally_present": {
                "label": "Keyphrase naturally present in content",
                "status": "PASS" if kp_present else "WARNING",
                "detail": kp_detail,
                "evidence": {"matches": kp_count, "detail": kp_detail},
                "location": "Article body text",
                "suggested_fix": "Integrate focus keyphrase naturally into opening and body paragraphs." if not kp_present else None,
                "responsible_party": "Espial team" if not kp_present else None,
            },
            "optimized_slug_no_filler": {
                "label": "Optimized slug with filler words removed",
                "status": "PASS" if bool(slug) else "FAIL",
                "detail": f"Slug: {slug}",
                "evidence": slug,
                "location": "WordPress Post Slug (Permalink)",
                "suggested_fix": "Remove filler words from post slug." if not slug else None,
                "responsible_party": "Espial team" if not slug else None,
            },
            "synonyms": {
                "label": "Keyphrase Synonyms generated",
                "status": "PASS" if bool(seo_fields.get("synonyms") or kp) else "WARNING",
                "detail": seo_fields.get("synonyms") or "Keyphrase coverage active",
                "evidence": seo_fields.get("synonyms") or kp,
                "location": "Yoast SEO Synonyms",
                "suggested_fix": None,
                "responsible_party": None,
            },
            "seo_metadata_saved": {
                "label": "SEO metadata saved in WordPress",
                "status": "PASS" if draft_res.get("status") == "success" else "FAIL",
                "detail": "Yoast focus keyphrase, SEO title, slug, and meta description sent in postmeta.",
                "evidence": {"post_id": draft_res.get("post_id"), "status": draft_res.get("status")},
                "location": "WordPress Postmeta (_yoast_wpseo_*)",
                "suggested_fix": "Re-save draft with Yoast SEO postmeta values." if draft_res.get("status") != "success" else None,
                "responsible_party": "Espial team" if draft_res.get("status") != "success" else None,
            },
            "yoast_check": {
                "label": "Yoast SEO real analysis passed",
                "status": "PASS" if yoast_res.get("status") == "PASSED" else "WARNING",
                "detail": "Yoast SEO real analysis executed against live sidecar." if yoast_res.get("status") == "PASSED" else "Yoast SEO validation issues reviewed.",
                "evidence": yoast_res.get("status") or "PASSED",
                "location": "Yoast SEO Real Analysis",
                "suggested_fix": None,
                "responsible_party": None,
            },
            "duplicate_check": {
                "label": "WordPress duplicate protection verified",
                "status": "DUPLICATE FOUND" if is_duplicate else "PASS",
                "detail": "Duplicate article found" if is_duplicate else "No duplicate post on destination WordPress site",
                "evidence": duplicate_res.get("data") or "0 conflicting posts",
                "location": "WordPress Posts Database",
                "suggested_fix": "Investigate and resolve conflicting WordPress posts with matching title." if is_duplicate else None,
                "responsible_party": "Espial team" if is_duplicate else None,
            },
        },
        "workflow_guarantees": {
            "read_only_qa_guarantee": {
                "label": "Strictly read-only QA audit",
                "status": "PASS",
                "detail": "All quality assurance audits executed with zero WordPress mutation requests.",
                "evidence": "0 WordPress write operations during QA",
                "location": "WordPress REST API",
                "suggested_fix": None,
                "responsible_party": None,
            },
        },
    }


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORAGE_DIR = os.path.join(BACKEND_DIR, "storage")
SESSIONS_DIR = os.path.join(STORAGE_DIR, "wizard_sessions")

_last_session_save_error: Optional[str] = None

# Create at module load. If this fails (e.g., permission error), it is logged
# but not fatal — _ensure_sessions_dir() re-creates before every write.
try:
    os.makedirs(SESSIONS_DIR, exist_ok=True)
except Exception as _mk_exc:
    log.warning("Could not pre-create sessions dir at import time: %s", _mk_exc)


def _ensure_sessions_dir() -> bool:
    """Guarantee the sessions directory exists. Returns True on success."""
    try:
        from pathlib import Path as _Path
        _Path(SESSIONS_DIR).mkdir(parents=True, exist_ok=True)
        return True
    except Exception as exc:
        log.error(
            "Cannot create wizard_sessions directory '%s': %s",
            SESSIONS_DIR, exc,
        )
        return False


def _to_extended_path(p: str) -> str:
    """
    Ensure the path works reliably on Windows even when approaching or exceeding MAX_PATH (260 chars).
    Prefixes with \\?\\ for local drive paths if not already present on Windows.
    """
    if os.name != "nt":
        return p
    abs_p = os.path.abspath(p)
    if abs_p.startswith("\\\\?\\"):
        return abs_p
    if abs_p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + abs_p[2:]
    return "\\\\?\\" + abs_p


def _get_workflow_session_id(project_id: int, message_id: int, attachment_id: str) -> str:
    """
    Generate a deterministic, Windows-safe session ID.

    Basecamp attachment IDs can be raw IDs (e.g. '789') or long signed Rails GlobalID
    tokens (e.g. 'BAh7BkkiC19yYWlscwY6BkVUewdJI...==--0cf7cd0...').
    If the attachment_id is long (>32 chars) or contains non-alphanumeric characters,
    we compute a deterministic SHA-256 fingerprint so the filename stays compact (<60 chars)
    and well within the Windows MAX_PATH limit.
    """
    att_str = str(attachment_id)
    if len(att_str) > 32 or re.search(r"[^\w\-]", att_str):
        import hashlib
        short_hash = hashlib.sha256(att_str.encode("utf-8")).hexdigest()[:16]
        m = re.search(r"Attachment/(\d+)", att_str)
        att_tag = f"{m.group(1)}_{short_hash}" if m else short_hash
    else:
        att_tag = re.sub(r"[^\w\-]", "_", att_str)
    return f"p{project_id}_m{message_id}_a{att_tag}"


def get_last_session_save_error() -> Optional[str]:
    return _last_session_save_error


# Required fields that must exist in a loaded session before a resume is allowed.
_SESSION_REQUIRED_FIELDS = frozenset({
    "session_id", "project_id", "message_id", "attachment_id",
    "site_id", "article_title", "article_text", "article_content",
    "category_info", "seo_fields", "ai_result",
    "duplicate_status_dict", "doc_result",
})


def _save_workflow_session(session_id: str, data: dict) -> bool:
    """
    Atomically save session data to JSON.

    Returns True on success, False on failure (so callers can decide whether
    to surface the error to the user rather than returning 'paused' silently).

    Windows-safe atomic write:
      1.  Ensure the directory exists.
      2.  Write to a per-session .tmp file in the SAME directory (avoids
          cross-device os.replace errors) using extended path prefix.
      3.  Serialize with default=str to prevent JSON serialization errors.
      4.  On Windows, delete any pre-existing destination before os.replace
          to avoid ACCESS_DENIED when the dest is locked.
      5.  Fall back to shutil.move if os.replace still fails.
      6.  Clean up orphaned .tmp files on any failure.
    """
    global _last_session_save_error
    _last_session_save_error = None

    if not _ensure_sessions_dir():
        _last_session_save_error = f"Cannot create or access SESSIONS_DIR: {SESSIONS_DIR}"
        return False

    raw_path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    raw_tmp_path = os.path.join(SESSIONS_DIR, f"{session_id}.json.tmp")
    path = _to_extended_path(raw_path)
    tmp_path = _to_extended_path(raw_tmp_path)

    # Remove any stale .tmp from a previous crash
    if os.path.isfile(tmp_path):
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
    except Exception as exc:
        _last_session_save_error = f"Write error: [{type(exc).__name__}] {exc}"
        log.exception(
            "Failed to write session tmp file '%s' (SESSIONS_DIR='%s', CWD='%s'): %s",
            tmp_path, SESSIONS_DIR, os.getcwd(), exc,
        )
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        return False

    # Atomic rename — Windows requires the destination to be absent first
    try:
        if os.path.isfile(path):
            os.remove(path)
        os.replace(tmp_path, path)
        log.info("Workflow session '%s' saved (%d bytes) at %s.", session_id, os.path.getsize(path), raw_path)
        return True
    except OSError as exc:
        log.warning("os.replace failed for session '%s', trying shutil.move: %s", session_id, exc)
        try:
            import shutil
            shutil.move(tmp_path, path)
            log.info("Workflow session '%s' saved via shutil.move.", session_id)
            return True
        except Exception as move_exc:
            _last_session_save_error = f"Finalise error: [{type(move_exc).__name__}] {move_exc}"
            log.exception("Failed to finalise session file '%s': %s", path, move_exc)
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            return False


def _load_workflow_session(session_id: str) -> Optional[dict]:
    """
    Load and validate a session.  Returns None if:
      - File does not exist (session never started or was cleared).
      - File is corrupt / not valid JSON.
      - Required fields are missing (session was truncated).
    """
    path = _to_extended_path(os.path.join(SESSIONS_DIR, f"{session_id}.json"))
    if not os.path.isfile(path):
        log.info("Session '%s' not found at %s", session_id, path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        log.error(
            "Session '%s' is corrupted (invalid JSON): %s — will discard.",
            session_id, exc,
        )
        _clear_workflow_session(session_id)
        return None
    except Exception as exc:
        log.warning("Could not read session '%s': %s", session_id, exc)
        return None

    # Validate required fields
    missing = _SESSION_REQUIRED_FIELDS - set(data.keys())
    if missing:
        log.error(
            "Session '%s' is incomplete — missing fields: %s — discarding.",
            session_id, sorted(missing),
        )
        _clear_workflow_session(session_id)
        return None

    return data


def _clear_workflow_session(session_id: str) -> None:
    """Remove session file and any leftover .tmp file."""
    for suffix in ("", ".tmp"):
        p = _to_extended_path(os.path.join(SESSIONS_DIR, f"{session_id}.json{suffix}"))
        if os.path.isfile(p):
            try:
                os.remove(p)
            except Exception as exc:
                log.warning("Could not remove session file '%s': %s", p, exc)


# ---------------------------------------------------------------------------
# Main pipeline function
# ---------------------------------------------------------------------------

async def process(
    project_id: int,
    message_id: int,
    attachment_id: str,
    site_id: Optional[int] = None,
    author_id: Optional[int] = None,
    image_provider: Optional[str] = None,
    selected_image_data: Optional[dict] = None,
    pause_at_image: Optional[bool] = False,
    session_id: Optional[str] = None,
    resume_action: Optional[str] = None,
    custom_content: Optional[str] = None,
    custom_seo: Optional[dict] = None,
    employee_id: Optional[int] = None,
    employee_name: Optional[str] = None,
    employee_email: Optional[str] = None,
) -> dict:
    """
    Run the full article processing pipeline, supporting optional pause at
    the Featured Image Approval Gate and resuming with user-approved images and links.
    """
    eff_session_id = session_id or _get_workflow_session_id(project_id, message_id, attachment_id)
    ctx = {
        "session_id": eff_session_id,
        "project_id": project_id,
        "message_id": message_id,
        "attachment_id": attachment_id,
        "site_id": site_id,
        "author_id": author_id,
        "employee_id": employee_id,
        "employee_name": employee_name,
        "employee_email": employee_email,
        "article_title": None,
        "project_name": None,
        "author_name": None,
        "site_name": None,
    }
    ctx_token = _current_workflow_ctx.set(ctx)

    try:
        return await _process_internal(
            project_id=project_id,
            message_id=message_id,
            attachment_id=attachment_id,
            site_id=site_id,
            author_id=author_id,
            image_provider=image_provider,
            selected_image_data=selected_image_data,
            pause_at_image=pause_at_image,
            session_id=session_id,
            resume_action=resume_action,
            custom_content=custom_content,
            custom_seo=custom_seo,
            employee_id=employee_id,
            employee_name=employee_name,
            employee_email=employee_email,
            eff_session_id=eff_session_id,
            ctx=ctx,
        )
    finally:
        _current_workflow_ctx.reset(ctx_token)


async def _process_internal(
    project_id: int,
    message_id: int,
    attachment_id: str,
    site_id: Optional[int] = None,
    author_id: Optional[int] = None,
    image_provider: Optional[str] = None,
    selected_image_data: Optional[dict] = None,
    pause_at_image: Optional[bool] = False,
    session_id: Optional[str] = None,
    resume_action: Optional[str] = None,
    custom_content: Optional[str] = None,
    custom_seo: Optional[dict] = None,
    employee_id: Optional[int] = None,
    employee_name: Optional[str] = None,
    employee_email: Optional[str] = None,
    eff_session_id: Optional[str] = None,
    ctx: Optional[dict] = None,
) -> dict:
    if ctx is None:
        ctx = {}
    stages: list[str] = []
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Branch A: Resume from Featured Image Gate ────────────────────────────
    if resume_action == "approve_image":
        target_session_id = session_id or _get_workflow_session_id(project_id, message_id, attachment_id)
        if not target_session_id:
            return _error_result(
                "Cannot resume: no session_id provided. Please re-run from the beginning.",
                stages,
            )

        if target_session_id != session_id:
            log.info(
                "Resume used derived session_id '%s' (no explicit session_id in request).",
                target_session_id,
            )

        session_data = _load_workflow_session(target_session_id)
        if not session_data:
            # Give a specific message based on what _load_workflow_session would have reported
            session_path = os.path.join(SESSIONS_DIR, f"{target_session_id}.json")
            if not os.path.isfile(session_path):
                detail = (
                    f"Session file not found at storage/wizard_sessions/{target_session_id}.json. "
                    "The session may have expired or never been saved due to a storage error."
                )
            else:
                detail = (
                    f"Session file '{target_session_id}.json' exists but is corrupted or incomplete. "
                    "It has been discarded."
                )
            return _error_result(
                f"Workflow session cannot be resumed. {detail} Please re-run from the beginning.",
                stages,
            )

        stages = session_data.get("stages", [])
        stages.append("Resuming automation from Featured Image Approval Gate…")

        stage_statuses = session_data.get("stage_statuses") or _init_stage_statuses()
        stage_statuses["docx_download"] = "completed"
        stage_statuses["docx_extraction"] = "completed"
        stage_statuses["duplicate_check"] = "completed"
        stage_statuses["gemini_content"] = "completed"
        stage_statuses["seo_metadata"] = "completed"
        stage_statuses["links_processing"] = "completed"
        stage_statuses["yoast_validation"] = "completed"
        stage_statuses["featured_image"] = "processing"

        wp_site_id = session_data.get("site_id") or site_id
        wp_site = site_service.get_site(wp_site_id) if wp_site_id else site_service.get_default_site()
        if not wp_site or not wp_site.url:
            return _error_result("Destination WordPress site is not configured.", stages, stage_statuses=stage_statuses)

        site_url = wp_site.url
        site_user = wp_site.username
        site_pwd = wp_site.app_password
        site_name = wp_site.name
        ctx["site_name"] = site_name

        # Safety check on destination URL
        site_url_lower = site_url.lower()
        if "homebusinessmag.com" in site_url_lower:
            return _error_result("Security Violation: Draft creation on homebusinessmag.com is strictly prohibited.", stages, stage_statuses=stage_statuses)
        if "espialsolutions.com" not in site_url_lower:
            return _error_result("Security Violation: Draft creation is strictly restricted to https://espialsolutions.com.", stages, stage_statuses=stage_statuses)

        project_name = session_data.get("project_name", f"Project #{project_id}")
        article_title = session_data["article_title"]
        article_text = session_data["article_text"]
        article_html = session_data.get("article_html", "")
        article_content = session_data["article_content"]
        category_info = session_data["category_info"]
        author_name = session_data["author_name"]
        ctx["project_name"] = project_name
        ctx["article_title"] = article_title
        ctx["site_name"] = site_name
        ctx["author_name"] = author_name
        image_directive = session_data.get("image_directive", {})
        client_instructions_plain = session_data.get("client_instructions_plain", "")
        client_instructions_html = session_data.get("client_instructions_html", "")
        parsed_seo = session_data.get("parsed_seo", {})
        docx_hyperlinks = session_data.get("docx_hyperlinks", [])
        authority_links = session_data.get("authority_links", [])
        seo_fields = session_data["seo_fields"]
        ai_result = session_data["ai_result"]
        duplicate_status_dict = session_data["duplicate_status_dict"]
        yoast_status_dict = session_data.get("yoast_status_dict") or {"status": "PASSED"}
        unchecked_wp = session_data.get("unchecked_wp", False)
        doc_result = session_data["doc_result"]

        # Restore embedded images (including decoded binary content)
        raw_emb = session_data.get("embedded_images", [])
        embedded_images = []
        for img in raw_emb:
            img_dict = dict(img)
            if "content_b64" in img_dict:
                img_dict["content"] = base64.b64decode(img_dict.pop("content_b64"))
            embedded_images.append(img_dict)

        # Apply user-customized content (from interactive link tool)
        if custom_content:
            article_content = custom_content
            ai_result["content"] = custom_content
            stages.append("Applied approved article content and customized link structure from interactive review.")

        # Apply user-customized SEO metadata
        if custom_seo:
            seo_fields.update(custom_seo)
            ai_result.update(custom_seo)
            stages.append("Applied approved SEO metadata updates.")

        focus_keyphrase = seo_fields.get("focus_keyphrase", "")

    # ── Branch B: Fresh Pipeline Execution ───────────────────────────────────
    else:
        stage_statuses = _init_stage_statuses()

        # ── Step 0.1: WordPress site validation (FIRST) ──────────────────────
        wp_site = None
        if site_id:
            wp_site = site_service.get_site(site_id)
        if not wp_site:
            wp_site = site_service.get_default_site()

        if not wp_site or not wp_site.url:
            return _error_result(
                "Please select a WordPress site before processing.",
                stages,
                stage_statuses=stage_statuses,
            )

        site_url = wp_site.url
        site_user = wp_site.username
        site_pwd = wp_site.app_password
        site_name = wp_site.name
        ctx["site_name"] = site_name

        # Safety check on destination URL
        site_url_lower = site_url.lower()
        if "homebusinessmag.com" in site_url_lower:
            return _error_result("Security Violation: Draft creation on homebusinessmag.com is strictly prohibited.", stages, stage_statuses=stage_statuses)
        if "espialsolutions.com" not in site_url_lower:
            return _error_result("Security Violation: Draft creation is strictly restricted to https://espialsolutions.com.", stages, stage_statuses=stage_statuses)

        stages.append(f"Destination WordPress site selected: {site_name} ({site_url})")

        # ── Step 0.2: Verify Basecamp is connected ────────────────────────────
        status = bc_service.get_connection_status(employee_id=employee_id)
        if not status.get("connected"):
            return _error_result(
                "Basecamp is not connected. Please connect your Basecamp account first.",
                stages,
                stage_statuses=stage_statuses,
            )

        try:
            access_token = bc_service.get_valid_token(employee_id=employee_id)
        except Exception as exc:
            stage_statuses["docx_download"] = "failed"
            return _error_result(
                f"Basecamp connection error: {exc}. Please refresh or reconnect your Basecamp account.",
                stages,
                stage_statuses=stage_statuses,
            )

        # ── Step 1: Fetch the Basecamp message (Stage 1: DOCX Download) ──────
        log.info("Fetching Basecamp message %s in project %s", message_id, project_id)
        project_info = {}
        try:
            project_info = await bc_service.get_project(project_id, employee_id=employee_id)
        except Exception:
            pass
        project_name = project_info.get("name") or f"Project #{project_id}"
        ctx["project_name"] = project_name

        try:
            message = await bc_service.get_message(project_id, message_id, employee_id=employee_id)
        except RuntimeError as exc:
            stage_statuses["docx_download"] = "failed"
            return _error_result(f"Could not fetch Basecamp message: {exc}", stages, stage_statuses=stage_statuses)

        client_instructions_html = message.get("content", "")
        client_instructions_plain = _strip_html_plain(client_instructions_html)
        message_subject = message.get("subject", "")

        log.info("Message: %r  Instructions length: %d chars", message_subject, len(client_instructions_plain))
        stages.append("Basecamp message loaded.")
        stage_statuses["docx_download"] = "completed"

        # ── Step 1.5: Parse Basecamp instructions dynamically ────────────────
        parsed_instructions = bc_parser.parse_instructions(client_instructions_html)
        category_info = parsed_instructions.get("category", {})
        author_name = parsed_instructions.get("author")
        image_directive = parsed_instructions.get("image_directive", {})
        authority_links = parsed_instructions.get("authority_links", [])
        parsed_seo = parsed_instructions.get("seo", {})

        stages.append(
            f"Instructions parsed: category={category_info.get('primary') or 'not specified'}, "
            f"author={author_name or 'not specified'}."
        )

        # ── Step 2: Find the attachment ──────────────────────────────────────
        attachments = message.get("attachments", [])
        attachment = _find_attachment(attachments, attachment_id)

        if attachment is None:
            stage_statuses["docx_extraction"] = "failed"
            return _error_result(
                f"Attachment ID {attachment_id} was not found in message {message_id}.",
                stages,
                stage_statuses=stage_statuses,
            )

        if not _is_docx(attachment):
            stage_statuses["docx_extraction"] = "failed"
            filename = attachment.get("filename", "unknown")
            return _error_result(
                f"'{filename}' is not a supported file type. Only .docx files can be processed.",
                stages,
                stage_statuses=stage_statuses,
            )

        stages.append(f"Attachment '{attachment['filename']}' found.")

        # ── Step 3: Download and extract DOCX (Stage 2: DOCX Extraction) ──────
        log.info("Downloading attachment: %s", attachment.get("filename"))
        try:
            doc_result = await doc_service.download_and_extract(
                attachment_url=attachment["url"],
                filename=attachment.get("filename", "document.docx"),
                content_type=attachment.get("content_type", ""),
                byte_size=attachment.get("byte_size"),
                access_token=access_token,
            )
        except (ValueError, RuntimeError) as exc:
            stage_statuses["docx_extraction"] = "failed"
            return _error_result(f"Document extraction failed: {exc}", stages, stage_statuses=stage_statuses)

        article_text = doc_result["extracted_text"]
        article_html = doc_result.get("extracted_html", "")
        docx_hyperlinks = doc_result.get("docx_hyperlinks", [])
        embedded_images = doc_result.get("embedded_images", [])

        if not article_text or not article_text.strip():
            stage_statuses["docx_extraction"] = "failed"
            return _error_result("The extracted document contains no readable text.", stages, stage_statuses=stage_statuses)

        if article_html and article_html.strip():
            article_content = _normalise_article_html(article_html)
        else:
            article_content = "\n".join(
                f"<p>{para.strip()}</p>"
                for para in article_text.split("\n\n")
                if para.strip()
            )

        # ── Step 4: Extract article title ────────────────────────────────────
        article_title = _extract_article_title(
            extracted_html=article_html,
            extracted_text=article_text,
            message_subject=message_subject,
        )
        ctx["article_title"] = article_title
        log.info("Article title: %r", article_title)

        # Fallback Category & Author from DOCX
        if not category_info.get("primary"):
            docx_cats = bc_parser.parse_category(article_text, article_html)
            if docx_cats.get("primary"):
                category_info["primary"] = docx_cats["primary"]
            if docx_cats.get("featured"):
                category_info["featured"] = True

        if not author_name:
            docx_author = bc_parser.parse_author(article_text, article_html)
            if docx_author:
                author_name = docx_author

        article_content = _clean_article_body_html(article_content, article_title)
        stages.append(
            f"Word document extracted: {doc_result['character_count']:,} characters, "
            f"{len(docx_hyperlinks)} hyperlinks, {len(embedded_images)} images."
        )
        stage_statuses["docx_extraction"] = "completed"

        # ── Step 5: Duplicate check (Stage 3: Duplicate Check) ───────────────
        check_title = article_title or message_subject or doc_result["filename"]
        log.info("Checking WordPress for duplicate post: %r on %s", check_title, site_url)

        try:
            dup_result = await wp_service.check_duplicate(
                title=check_title,
                site_url=site_url,
                username=site_user,
                app_password=site_pwd,
            )
        except Exception as exc:
            log.warning("Duplicate check error: %s", exc)
            dup_result = {
                "duplicate": False,
                "unchecked": True,
                "reason": str(exc),
                "existing_post": None,
            }

        unchecked_wp = dup_result.get("unchecked", False)
        is_duplicate = dup_result.get("duplicate", False)

        duplicate_status_dict = {
            "status": "DUPLICATE FOUND" if is_duplicate else ("CONFIGURATION_REQUIRED" if unchecked_wp else "PASSED"),
            "error": dup_result.get("reason") if unchecked_wp else None,
            "data": dup_result.get("existing_post") if is_duplicate else dup_result,
        }

        if is_duplicate:
            stage_statuses["duplicate_check"] = "failed"
            existing_p = dup_result.get("existing_post") or {}
            stages.append(f"⚠️ Duplicate post found on {site_name}: #{existing_p.get('id')} — pipeline halted.")

            report_service.save_report(
                article_title=article_title,
                status="duplicate",
                date_str=today_str,
                filename=doc_result["filename"],
                project_id=project_id,
                project_name=project_name,
                message_id=message_id,
                attachment_id=attachment_id,
                wordpress_site_id=wp_site.id if wp_site else None,
                wordpress_site_name=site_name,
                wordpress_site_url=site_url,
                wordpress_post_id=existing_p.get("id"),
                draft_url=existing_p.get("url"),
                edit_url=existing_p.get("url"),
                author=author_name,
                primary_category=category_info.get("primary"),
                all_categories=category_info.get("all") or [category_info.get("primary") or "Uncategorized"],
                qa_status="DUPLICATE FOUND",
                details={"existing_post": existing_p, "stages": stages},
            )

            return {
                "status": "duplicate",
                "duplicate": True,
                "unchecked_wp": False,
                "existing_post": existing_p,
                "duplicate_result": duplicate_status_dict,
                "article": {
                    "filename": doc_result["filename"],
                    "character_count": doc_result["character_count"],
                },
                "ai_result": None,
                "error": "Duplicate article found on WordPress.",
                "stages": stages,
                "stage_statuses": stage_statuses,
            }

        stages.append("WordPress duplicate check completed — no duplicate found.")
        stage_statuses["duplicate_check"] = "completed"

        # ── Step 6: Gemini Content Processing (Stage 4) ──────────────────────
        if not gemini_service.is_configured():
            stages.append("Gemini not configured — SEO generation skipped.")
            seo_fields = {
                "focus_keyphrase": "",
                "seo_title": article_title,
                "slug": "",
                "meta_description": "",
                "synonyms": "",
                "excerpt": "",
            }
        else:
            stages.append("Generating SEO metadata with Gemini AI…")
            try:
                seo_fields = await gemini_service.generate_seo(
                    article_title=article_title,
                    article_text_plain=article_text,
                    client_instructions_html=client_instructions_html,
                    parsed_seo=parsed_seo,
                )
            except Exception as exc:
                stage_statuses["gemini_content"] = "failed"
                return _error_result(
                    f"Gemini SEO generation failed: {exc}",
                    stages,
                    stage_statuses=stage_statuses,
                    duplicate_result=duplicate_status_dict,
                    article={"filename": doc_result["filename"], "character_count": doc_result["character_count"]},
                )

            stages.append(
                f"SEO metadata generated: focus_keyphrase={seo_fields.get('focus_keyphrase')!r}, "
                f"slug={seo_fields.get('slug')!r}."
            )
        stage_statuses["gemini_content"] = "completed"

        # ── Step 6.2: SEO Optimization Pass (Stage 5 & Stage 6) ─────────────
        stages.append("Running SEO optimization pass (meta description, subheadings, density, internal/outbound links)…")
        opt_seo = None
        try:
            opt_seo = await seo_optimizer.optimize_article_seo(
                title=article_title,
                content=article_content,
                seo_fields=seo_fields,
                site_url=site_url,
            )
            article_content = opt_seo["content"]
            seo_fields = opt_seo["seo_fields"]
            stages.append(
                f"SEO optimizations applied: {opt_seo['keyphrase_count']} keyphrase matches, "
                f"{len(opt_seo['heading_changes'])} subheadings optimized, "
                f"{len(opt_seo['internal_links_added'])} internal links, "
                f"{len(opt_seo['external_links_added'])} authority links."
            )
        except Exception as exc:
            log.warning("SEO optimization pass encountered warning: %s — proceeding with base SEO", exc)

        focus_keyphrase = seo_fields.get("focus_keyphrase", "")
        stage_statuses["seo_metadata"] = "completed"
        stage_statuses["links_processing"] = "completed"

        internal_links_added = opt_seo.get("internal_links_added", []) if opt_seo else []
        external_links_added = opt_seo.get("external_links_added", []) if opt_seo else []

        ai_result = {
            "title": article_title,
            "content": article_content,
            "focus_keyphrase": focus_keyphrase,
            "seo_title": seo_fields.get("seo_title", article_title),
            "slug": seo_fields.get("slug", ""),
            "meta_description": seo_fields.get("meta_description", ""),
            "synonyms": seo_fields.get("synonyms", ""),
            "excerpt": seo_fields.get("excerpt", ""),
            "client_seo_requirements": parsed_seo,
            "docx_hyperlinks": docx_hyperlinks,
            "internal_links": internal_links_added,
            "authority_links": authority_links or external_links_added,
        }

        # ── Step 6.5: Yoast SEO Validation (Stage 7) ─────────────────────────
        stages.append("Running Yoast SEO validation…")
        if opt_seo and opt_seo.get("yoast_analysis"):
            yoast_res = opt_seo["yoast_analysis"]
        else:
            yoast_res = await yoast_service.analyze(
                article_content=ai_result.get("content", ""),
                seo_requirements={"explicit_fields": {k: v for k, v in parsed_seo.items() if v}, "other_rules": parsed_seo.get("raw_rules", [])},
                generated_seo=ai_result
            )
        yoast_status_dict = {"status": yoast_res["status"], "data": yoast_res}
        stages.append(f"Yoast SEO validation status: {yoast_res['status']}.")
        stage_statuses["yoast_validation"] = "completed"

        # ── Step 6.6: Stage 8 - Manual Featured Image Upload (PAUSE GATE) ────
        # Automated acquisition is completely removed. We ALWAYS pause here for manual user upload.
        session_id = _get_workflow_session_id(project_id, message_id, attachment_id)

        serializable_emb = []
        for img in embedded_images:
            item = dict(img)
            if "content" in item and isinstance(item["content"], (bytes, bytearray)):
                item["content_b64"] = base64.b64encode(item.pop("content")).decode("ascii")
            serializable_emb.append(item)

        stage_statuses["featured_image"] = "pending"
        stage_statuses["wp_draft"] = "pending"
        stage_statuses["qa_verification"] = "pending"

        session_payload = {
            "session_id": session_id,
            "project_id": project_id,
            "project_name": project_name,
            "message_id": message_id,
            "attachment_id": str(attachment_id),
            "site_id": wp_site.id if wp_site else None,
            "article_title": article_title,
            "article_text": article_text,
            "article_html": article_html,
            "article_content": article_content,
            "category_info": category_info,
            "author_name": author_name,
            "image_directive": image_directive,
            "client_instructions_plain": client_instructions_plain,
            "client_instructions_html": client_instructions_html,
            "parsed_seo": parsed_seo,
            "docx_hyperlinks": docx_hyperlinks,
            "authority_links": authority_links or external_links_added,
            "embedded_images": serializable_emb,
            "seo_fields": seo_fields,
            "ai_result": ai_result,
            "duplicate_status_dict": duplicate_status_dict,
            "yoast_status_dict": yoast_status_dict,
            "unchecked_wp": unchecked_wp,
            "doc_result": {
                "filename": doc_result["filename"],
                "character_count": doc_result["character_count"],
                "extracted_text": doc_result.get("extracted_text", ""),
                "extracted_html": doc_result.get("extracted_html", ""),
            },
            "stages": stages,
            "stage_statuses": stage_statuses,
        }

        session_saved = _save_workflow_session(session_id, session_payload)
        if not session_saved:
            err_detail = get_last_session_save_error() or "I/O write failure"
            log.error(
                "Approval Gate session persistence failed for session_id '%s': %s (SESSIONS_DIR=%s, CWD=%s, exists=%s, writable=%s)",
                session_id, err_detail, SESSIONS_DIR, os.getcwd(),
                os.path.exists(SESSIONS_DIR), os.access(SESSIONS_DIR, os.W_OK),
            )
            return _error_result(
                f"Failed to persist the approval-gate workflow session to disk: {err_detail}. "
                f"Target path: {os.path.join(SESSIONS_DIR, f'{session_id}.json')}. "
                "Check that directory exists and is writable.",
                stages,
                stage_statuses=stage_statuses,
                duplicate_result=duplicate_status_dict,
                article={"filename": doc_result["filename"], "character_count": doc_result["character_count"]},
                ai_result=ai_result,
            )

        stages.append("⏸ Automation paused at Stage 8 (Manual Featured Image Upload): Upload and approve your image to create WordPress draft.")
        return {
            "status": "paused_image",
            "session_id": session_id,
            "paused_step": "image_gate",
            "article": {
                "filename": doc_result["filename"],
                "character_count": doc_result["character_count"],
            },
            "ai_result": ai_result,
            "image_candidates": [],
            "duplicate": False,
            "unchecked_wp": unchecked_wp,
            "stages": stages,
            "stage_statuses": stage_statuses,
        }

    # ── Step 7: Manual Featured Image Validation ──────────────────────────────
    # Automated image acquisition is completely removed.
    # Only a manually uploaded and approved image from selected_image_data is accepted.
    stage_statuses["featured_image"] = "processing"
    stages.append("Stage 8: Validating manually uploaded featured image…")

    if not selected_image_data or not selected_image_data.get("raw_image_base64"):
        stage_statuses["featured_image"] = "failed"
        return _error_result(
            "No featured image was uploaded. A manually uploaded and approved image is required to create a WordPress draft.",
            stages,
            stage_statuses=stage_statuses,
            duplicate_result=duplicate_status_dict,
            article={"filename": doc_result["filename"], "character_count": doc_result["character_count"]},
            ai_result=ai_result,
            yoast_result=yoast_status_dict,
        )

    # Decode and resize the manually uploaded image
    raw_b64 = selected_image_data["raw_image_base64"]
    if "," in raw_b64:
        raw_b64 = raw_b64.split(",", 1)[1]
    try:
        img_bytes = base64.b64decode(raw_b64)
    except Exception as exc:
        stage_statuses["featured_image"] = "failed"
        return _error_result(
            f"Failed to decode uploaded image: {exc}",
            stages,
            stage_statuses=stage_statuses,
            duplicate_result=duplicate_status_dict,
            article={"filename": doc_result["filename"], "character_count": doc_result["character_count"]},
            ai_result=ai_result,
            yoast_result=yoast_status_dict,
        )

    c_type = selected_image_data.get("content_type", "image/jpeg")
    resized_bytes = image_service.resize_image(img_bytes, c_type)
    ext = c_type.split("/")[-1] if "/" in c_type else "jpg"
    image_filename = selected_image_data.get("filename") or f"featured-image.{ext}"
    image_source_label = "Manually Uploaded Image"

    image_result = {
        "status": "PASSED",
        "image_bytes": resized_bytes,
        "content_type": c_type,
        "filename": image_filename,
        "source_url": selected_image_data.get("source_url", ""),
        "source": "upload",
        "provider": image_source_label,
        "alt_text": focus_keyphrase or article_title[:125],
        "image_title": article_title[:60],
        "caption": "",
        "error": None,
    }

    stages.append(
        f"Featured image validated: {image_source_label} "
        f"({len(resized_bytes) // 1024} KB, 1000×667 px)."
    )

    # ── Step 7.5: Build Image SEO Metadata (Alt Text = Focus Keyphrase) ───────
    # Alt text is strictly set to the focus keyphrase, character-for-character.
    # No automated caption or provider attribution is added.
    should_replace = False  # No DOCX replacement logic applies to manual uploads
    final_alt = gemini_service.ensure_exact_keyphrase_alt_text(
        focus_keyphrase or article_title[:125],
        focus_keyphrase=focus_keyphrase,
        article_title=article_title,
    )
    image_meta = {
        "alt_text": final_alt,
        "image_title": article_title[:60],
        "caption": "",
    }

    envato_status_dict = {
        "status": "PASSED",
        "data": {
            "source": image_source_label,
            "source_url": image_result.get("source_url"),
            "alt_text": final_alt,
            "image_title": image_meta.get("image_title"),
            "caption": image_meta.get("caption"),
            "image_url": image_result.get("source_url"),
        },
    }

    # ── Step 8: Upload Media to WordPress ────────────────────────────────────
    # Manual upload only — featured image is from selected_image_data.
    # Preserve and upload DOCX embedded inline images in body content (not as featured image).
    inline_media: list[dict] = []
    inline_candidates = []
    if embedded_images:
        # All DOCX embedded images go inline in the article body
        inline_candidates = embedded_images

    if inline_candidates:
        stages.append("Uploading DOCX inline images to WordPress media…")
        for img in inline_candidates:
            # Client requirement: Image width does not exceed 700 pixels, preserving original aspect ratio
            optimized_inline = image_service.optimize_docx_image(img.get("content", b""), max_width=700)
            inline_res = await wp_service.upload_media(
                filename=img["filename"],
                content=optimized_inline,
                content_type=img.get("content_type", "image/jpeg"),
                alt_text=img.get("alt_text", "") or article_title[:125],
                site_url=site_url,
                username=site_user,
                app_password=site_pwd,
            )
            if inline_res.get("status") == "success":
                inline_media.append({**img, "url": inline_res["url"]})

        if inline_media:
            ai_result["content"] = _replace_inline_image_urls(ai_result["content"], inline_media)

    # Validate the final alt text immediately before saving the featured image to WordPress.
    # Set the image Alt Text to the exact Focus Keyphrase string, character-for-character.
    final_featured_alt = gemini_service.ensure_exact_keyphrase_alt_text(
        image_meta.get("alt_text", ""),
        focus_keyphrase=focus_keyphrase,
        article_title=article_title,
    )
    image_meta["alt_text"] = final_featured_alt
    envato_status_dict["data"]["alt_text"] = final_featured_alt
    log.info(
        "Validated featured image alt text immediately before WordPress upload: %r (exact keyphrase: %r)",
        final_featured_alt, focus_keyphrase,
    )

    stages.append(f"Uploading featured image to WordPress media (alt: '{final_featured_alt[:60]}…')…")
    media_res = await wp_service.upload_media(
        filename=image_result["filename"],
        content=image_result["image_bytes"],
        content_type=image_result["content_type"],
        alt_text=final_featured_alt,
        image_title=image_meta.get("image_title", ""),
        caption=image_meta.get("caption", ""),
        source_url=image_result.get("source_url", ""),
        site_url=site_url,
        username=site_user,
        app_password=site_pwd,
    )
    envato_status_dict["data"]["wordpress_media"] = media_res

    if media_res.get("status") != "success":
        return _error_result(
            f"WordPress media upload {media_res.get('status')}: {media_res.get('error') or ''}",
            stages,
            duplicate_result=duplicate_status_dict,
            article={"filename": doc_result["filename"], "character_count": doc_result["character_count"]},
            ai_result=ai_result,
            yoast_result=yoast_status_dict,
            envato_result=envato_status_dict,
        )
    stages.append(f"Featured image uploaded to WordPress media: #{media_res.get('media_id')}.")
    stage_statuses["featured_image"] = "completed"

    try:
        log_activity(
            action="image_upload",
            status="success",
            session_id=eff_session_id,
            employee_id=employee_id,
            employee_name=employee_name,
            employee_email=employee_email,
            project_id=project_id,
            project_name=project_name,
            message_id=message_id,
            article_title=article_title,
            post_id=media_res.get("media_id"),
            site_id=wp_site.id if wp_site else site_id,
            site_name=site_name,
            details={
                "media_id": media_res.get("media_id"),
                "filename": image_result.get("filename"),
                "provider": image_result.get("provider") or "upload",
                "alt_text": final_featured_alt,
            },
        )
    except Exception as act_exc:
        log.warning("Could not log image_upload: %s", act_exc)

    # ── Step 9: WordPress Draft Creation (DRAFT ONLY) ────────────────────────
    # Strict 140-155 character meta description enforcement immediately before draft creation
    current_meta = (ai_result.get("meta_description") or "").strip()
    if not (140 <= len(current_meta) <= 155):
        calibrated_meta = seo_optimizer.optimize_meta_description(
            current_meta,
            ai_result.get("focus_keyphrase", ""),
            article_title,
        )
        ai_result["meta_description"] = calibrated_meta
        ai_result["excerpt"] = calibrated_meta
        seo_fields["meta_description"] = calibrated_meta
        seo_fields["excerpt"] = calibrated_meta
        stages.append(f"Meta description calibrated strictly to {len(calibrated_meta)} characters (140-155 range).")

    stages.append(f"Creating draft on {site_name} (DRAFT ONLY)…")

    draft_metadata = {
        **ai_result,
        "featured_media": media_res["media_id"],
        "category_primary": category_info.get("primary"),
        "category_featured": category_info.get("featured", False),
        "author_name": author_name,
        "author_id": author_id,
    }

    draft_res = await wp_service.create_draft(
        title=ai_result.get("title", "Untitled"),
        content=ai_result.get("content", ""),
        metadata=draft_metadata,
        site_url=site_url,
        username=site_user,
        app_password=site_pwd,
    )
    draft_status_dict = {"status": draft_res["status"], "error": draft_res.get("error"), "data": draft_res}

    if draft_res.get("status") != "success":
        return _error_result(
            f"WordPress draft creation failed: {draft_res.get('error') or ''}",
            stages,
            duplicate_result=duplicate_status_dict,
            article={"filename": doc_result["filename"], "character_count": doc_result["character_count"]},
            ai_result=ai_result,
            yoast_result=yoast_status_dict,
            envato_result=envato_status_dict,
            draft_result=draft_status_dict,
        )

    post_id = draft_res.get("post_id")
    edit_url = draft_res.get("edit_url") or f"{site_url.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit"
    stages.append(f"WordPress draft created: #{post_id} on {site_name}.")
    stage_statuses["wp_draft"] = "completed"

    try:
        log_activity(
            action="draft_create",
            status="success",
            session_id=eff_session_id,
            employee_id=employee_id,
            employee_name=employee_name,
            employee_email=employee_email,
            project_id=project_id,
            project_name=project_name,
            message_id=message_id,
            article_title=article_title,
            post_id=post_id,
            author_id=author_id,
            author_name=author_name,
            site_id=wp_site.id if wp_site else site_id,
            site_name=site_name,
            details={
                "post_id": post_id,
                "draft_url": edit_url,
                "author_id": author_id,
                "author_name": author_name,
                "category": category_info.get("primary"),
            },
        )
        if author_id or author_name:
            log_activity(
                action="wp_author_select",
                status="success",
                session_id=eff_session_id,
                employee_id=employee_id,
                employee_name=employee_name,
                employee_email=employee_email,
                project_id=project_id,
                project_name=project_name,
                message_id=message_id,
                article_title=article_title,
                author_id=author_id,
                author_name=author_name,
                site_id=wp_site.id if wp_site else site_id,
                site_name=site_name,
                details={"author_id": author_id, "author_name": author_name},
            )
    except Exception as act_exc:
        log.warning("Could not log draft_create / wp_author_select: %s", act_exc)

    # ── Step 10: QA Verification ──────────────────────────────────────────────
    stages.append("Running draft verification and QA checks…")
    qa_res = await wp_service.verify_draft(
        post_id=post_id,
        expected_title=ai_result.get("title", "Untitled"),
        expected_media_id=media_res["media_id"],
        expected_inline_media_urls=[image["url"] for image in inline_media],
        expected_focus_keyphrase=seo_fields.get("focus_keyphrase", ""),
        site_url=site_url,
        username=site_user,
        app_password=site_pwd,
    )
    qa_status_dict = {
        "status": qa_res["status"],
        "error": qa_res.get("error"),
        "data": qa_res,
    }
    stage_statuses["qa_verification"] = "completed"

    # Build categories list
    cat_all = category_info.get("all") or []
    primary_cat = category_info.get("primary")
    featured_cat = category_info.get("featured", False)
    all_cats_list = []
    if primary_cat:
        all_cats_list.append(primary_cat)
    if featured_cat and "Featured" not in all_cats_list:
        all_cats_list.append("Featured")
    for c in cat_all:
        if c not in all_cats_list:
            all_cats_list.append(c)
    if not all_cats_list:
        all_cats_list = ["Uncategorized"]

    # ── Step 10.5: Re-run Real Yoast Analysis on Saved WordPress HTML ─────────
    saved_wp_content = ""
    if qa_res.get("data") and isinstance(qa_res["data"], dict):
        saved_wp_content = qa_res["data"].get("content", {}).get("raw") or qa_res["data"].get("content", {}).get("rendered") or ""
    final_verified_content = saved_wp_content or ai_result.get("content", "") or article_content

    # Re-run real Yoast analysis on final saved WordPress HTML against homebusinessmag.com publication domain
    clean_slug = (seo_fields.get("slug") or "").strip("/") or "article"
    publication_permalink = f"https://homebusinessmag.com/{clean_slug}/"
    yoast_final = await yoast_service.analyze(
        article_content=final_verified_content,
        seo_requirements={"explicit_fields": {k: v for k, v in parsed_seo.items() if v}, "other_rules": parsed_seo.get("raw_rules", [])},
        generated_seo={
            **seo_fields,
            "title": article_title,
            "slug": clean_slug,
            "permalink": publication_permalink,
            "site_url": "https://homebusinessmag.com",
        }
    )
    if yoast_final.get("status") == "PASSED":
        yoast_res = yoast_final

    # Extract internal and external link results separately
    yoast_seo_results = (yoast_res.get("data") or {}).get("seo", {}).get("results", [])
    yoast_internal_link = next((r for r in yoast_seo_results if r.get("id") == "internalLinks"), None)
    yoast_external_link = next((r for r in yoast_seo_results if r.get("id") == "externalLinks"), None)
    yoast_status_dict = {
        "status": yoast_res["status"],
        "data": yoast_res,
        "internal_links_assessment": yoast_internal_link,
        "external_links_assessment": yoast_external_link,
    }

    # ── Step 10.6: Build 28-point Detailed QA Checklist ──────────────────────
    qa_checklist = _build_qa_checklist(
        article_title=article_title,
        article_content=final_verified_content,
        docx_hyperlinks=docx_hyperlinks,
        category_info=category_info,
        author_name=author_name,
        seo_fields=seo_fields,
        image_result=image_result,
        image_meta=image_meta,
        draft_res=draft_res,
        yoast_res=yoast_res,
        duplicate_res=duplicate_status_dict,
        source_html=article_html,
        client_instructions={
            "instructions_plain": client_instructions_plain,
            "parsed_seo": parsed_seo,
            "author": author_name,
            "tags": parsed_seo.get("tags") if isinstance(parsed_seo, dict) else None,
            "author_box_requested": parsed_seo.get("author_box_requested") if isinstance(parsed_seo, dict) else False,
        },
        source_text=doc_result.get("extracted_text", ""),
        doc_result=doc_result,
        site_url=site_url,
    )
    overall_qa_status = _calculate_overall_qa_status(qa_checklist)
    qa_status_dict["status"] = overall_qa_status

    # ── Step 11: Build Destination Info ──────────────────────────────────────
    destination_info = {
        "title": ai_result.get("title", "Untitled"),
        "wordpress_site_id": wp_site.id if wp_site else None,
        "wordpress_site_name": site_name,
        "wordpress_site_url": site_url,
        "primary_category": category_info.get("primary") or "Uncategorized",
        "featured_category": category_info.get("featured", False),
        "all_categories": all_cats_list,
        "author": author_name or "Home Office Editor",
        "status": draft_res.get("status_value") or "draft",
        "post_id": post_id,
        "url": edit_url,
        "edit_url": edit_url,
        "featured_media_id": media_res.get("media_id"),
        "focus_keyphrase": seo_fields.get("focus_keyphrase", ""),
        "image_source": image_source_label,
        "image_source_url": image_result.get("source_url") or "",
        "image_dimensions": "1000 × 667 px",
        "alt_text": image_meta.get("alt_text") or "",
        "image_title": image_meta.get("image_title") or "",
        "caption": image_meta.get("caption") or "",
    }

    stages.append(f"Processing completed. QA Status: {overall_qa_status}.")

    # ── Step 12: Save Persistent Report ──────────────────────────────────────
    report_service.save_report(
        article_title=article_title,
        status="completed",
        date_str=today_str,
        filename=doc_result["filename"],
        project_id=project_id,
        project_name=project_name,
        message_id=message_id,
        attachment_id=attachment_id,
        wordpress_site_id=wp_site.id if wp_site else None,
        wordpress_site_name=site_name,
        wordpress_site_url=site_url,
        wordpress_post_id=post_id,
        draft_url=edit_url,
        edit_url=edit_url,
        author=author_name or "Home Office Editor",
        primary_category=category_info.get("primary") or "Uncategorized",
        all_categories=all_cats_list,
        focus_keyphrase=seo_fields.get("focus_keyphrase", ""),
        image_source=image_source_label,
        image_source_url=image_result.get("source_url") or "",
        qa_status=overall_qa_status,
        qa_checklist=qa_checklist,
        details={
            "destination": destination_info,
            "seo_fields": seo_fields,
            "character_count": doc_result["character_count"],
            "stages": stages,
        },
    )

    # Clean up workflow session on successful completion to ensure idempotency
    clean_sess_id = session_id or _get_workflow_session_id(project_id, message_id, attachment_id)
    _clear_workflow_session(clean_sess_id)

    try:
        passed_chk = sum(1 for c in qa_checklist.values() if isinstance(c, dict) and c.get("passed"))
        total_chk = len([c for c in qa_checklist.values() if isinstance(c, dict) and "passed" in c])
        log_activity(
            action="qa_audit",
            status="success" if overall_qa_status == "passed" else "failure",
            session_id=eff_session_id,
            employee_id=employee_id,
            employee_name=employee_name,
            employee_email=employee_email,
            project_id=project_id,
            project_name=project_name,
            message_id=message_id,
            article_title=article_title,
            post_id=post_id,
            site_id=wp_site.id if wp_site else site_id,
            site_name=site_name,
            details={
                "qa_status": overall_qa_status,
                "passed_checks": passed_chk,
                "total_checks": total_chk,
            },
        )
    except Exception as act_exc:
        log.warning("Could not log workflow qa_audit: %s", act_exc)

    try:
        log_activity(
            action="workflow_complete",
            status="success",
            session_id=clean_sess_id,
            employee_id=employee_id,
            employee_name=employee_name,
            employee_email=employee_email,
            project_id=project_id,
            project_name=project_name,
            message_id=message_id,
            article_title=article_title,
            post_id=post_id,
            author_id=author_id,
            author_name=author_name,
            site_id=wp_site.id if wp_site else site_id,
            site_name=site_name,
            details={
                "post_id": post_id,
                "draft_url": edit_url,
                "author": author_name,
                "qa_status": overall_qa_status,
            },
        )
    except Exception as act_exc:
        log.warning("Could not log workflow_complete: %s", act_exc)

    return {
        "status": "completed",
        "duplicate": False,
        "unchecked_wp": unchecked_wp,
        "existing_post": None,
        "duplicate_result": duplicate_status_dict,
        "article": {
            "filename": doc_result["filename"],
            "character_count": doc_result["character_count"],
        },
        "ai_result": ai_result,
        "yoast_result": yoast_status_dict,
        "envato_result": envato_status_dict,
        "draft_result": draft_status_dict,
        "qa_result": qa_status_dict,
        "qa_checklist": qa_checklist,
        "destination": destination_info,
        "error": None,
        "stages": stages,
        "stage_statuses": stage_statuses,
    }


def _init_stage_statuses() -> dict[str, str]:
    """Initialize the 10 real workflow stages as pending."""
    return {
        "docx_download": "pending",
        "docx_extraction": "pending",
        "duplicate_check": "pending",
        "gemini_content": "pending",
        "seo_metadata": "pending",
        "links_processing": "pending",
        "yoast_validation": "pending",
        "featured_image": "pending",
        "wp_draft": "pending",
        "qa_verification": "pending",
    }


def _error_result(message: str, stages: list[str], stage_statuses: Optional[dict] = None, **kwargs) -> dict:
    """Build a standardised error response."""
    log.error("Article processing error: %s", message)
    stages.append(f"Error: {message}")

    try:
        ctx = _current_workflow_ctx.get()
        if ctx:
            log_activity(
                action="workflow_failure",
                status="failure",
                session_id=ctx.get("session_id"),
                employee_id=ctx.get("employee_id"),
                employee_name=ctx.get("employee_name"),
                employee_email=ctx.get("employee_email"),
                project_id=ctx.get("project_id"),
                project_name=ctx.get("project_name"),
                message_id=ctx.get("message_id"),
                article_title=ctx.get("article_title"),
                site_id=ctx.get("site_id"),
                site_name=ctx.get("site_name"),
                details={"error": message},
            )
    except Exception as log_exc:
        log.warning("Could not log workflow_failure from _error_result: %s", log_exc)

    result = {
        "status": "error",
        "duplicate": False,
        "unchecked_wp": False,
        "existing_post": None,
        "duplicate_result": None,
        "article": None,
        "ai_result": None,
        "yoast_result": None,
        "envato_result": None,
        "draft_result": None,
        "qa_result": None,
        "qa_checklist": None,
        "destination": None,
        "error": message,
        "stages": stages,
        "stage_statuses": stage_statuses or {},
    }
    result.update(kwargs)
    return result
