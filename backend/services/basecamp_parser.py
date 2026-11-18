"""
Basecamp instruction parser.

Parses the HTML body of a Basecamp message (client instructions) to extract
structured requirements for article processing.

NO AI is used here — all parsing is deterministic regex/HTML pattern matching.

Extracted fields:
  - category       : primary category name (from instructions)
  - extra_categories: additional categories (including Featured)
  - author         : author name/slug (from instructions)
  - image_directive: { source, url, caption } — specific image requirement
  - authority_links: [ { url, anchor_text } ] — authority links with URLs
  - seo_requirements: { focus_keyphrase, seo_title, meta_description, slug, synonyms }
  - raw_html       : original instruction HTML
  - raw_text       : stripped plain text version
"""

import logging
import re
from html import unescape
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def strip_html(html: str) -> str:
    """Strip all HTML tags and decode entities, returning plain text."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_links_from_html(html: str) -> list[dict]:
    """
    Extract all <a href="..."> links from an HTML string.

    Returns a list of dicts: { url, anchor_text }
    """
    if not html:
        return []
    links = []
    pattern = re.compile(
        r'<a\b[^>]*\bhref\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(html):
        url = match.group(1).strip()
        anchor = strip_html(match.group(2)).strip()
        if url and not url.startswith("mailto:") and not url.startswith("#"):
            links.append({"url": url, "anchor_text": anchor or url})
    return links


# ---------------------------------------------------------------------------
# HTML line splitter helper
# ---------------------------------------------------------------------------

def _split_html_into_lines(html: str) -> list[str]:
    """
    Split HTML into logical lines by breaking on block-level tags.
    Returns a list of plain-text lines (HTML tags stripped).
    """
    if not html:
        return []
    # Insert newlines before/after block-level tags
    block_tags = r'</?(?:p|div|h[1-6]|li|br|ul|ol|blockquote|section|article)\b[^>]*>'
    text = re.sub(block_tags, '\n', html, flags=re.IGNORECASE)
    text = unescape(text)
    # Strip remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    return lines


# ---------------------------------------------------------------------------
# Category parsing
# ---------------------------------------------------------------------------

# Labels that appear before a category name in a structured instruction block
# These are the ONLY patterns that should trigger category extraction
_CATEGORY_LABEL_PATTERNS = [
    # "Name of category: Chicago" (structured HBM instruction block)
    r"^\s*Name\s+of\s+categor(?:y|ies)\s*[:\-]\s*(.+)$",
    # "CAT: Chicago"
    r"^\s*CAT\s*[:\-]\s*(.+)$",
    # "Primary Category: Chicago"
    r"^\s*Primary\s+Categor(?:y|ies)\s*[:\-]\s*(.+)$",
    # "Place in category (selected): Chicago"
    r"^\s*Place\s+in\s+(?:the\s+)?categor(?:y|ies)(?:\s+(?:or\s+categories\s+)?selected)?\s*[:\-]\s*(.+)$",
    # Standard "Category: Chicago" or "Categories: Chicago" ONLY as a standalone line
    r"^\s*Categor(?:y|ies)\s*[:\-]\s*(.+)$",
]

# Words/phrases that cannot be a valid category name
_CATEGORY_INVALID_VALUES = (
    "tag", "slug", "url", "http", "www.", "place in", "usually", "select",
    "featured category", "primary category", "subject category",
    "n/a", "none", "tbd", "to be determined",
)


def _is_category_boilerplate(text: str) -> bool:
    """Check if a string looks like instruction boilerplate rather than an actual category name."""
    if not text:
        return True
    lower = text.lower().strip()
    if len(text) > 50:
        return True
    # Reject if it starts with known non-category values
    for bad in _CATEGORY_INVALID_VALUES:
        if lower.startswith(bad) or lower == bad:
            return True
    boilerplate_phrases = (
        "usually all new articles",
        "subject category is usually",
        "place in category",
        "place in categories",
        "or categories selected",
        "selected.",
        "guideline",
        "instruction",
        "tag slug",
        "url of",
    )
    return any(bp in lower for bp in boilerplate_phrases)


def parse_category(text: str, html: str = "") -> dict:
    """
    Extract category requirements from instruction text or HTML.

    Returns:
        {
            "primary": str | None,       # the main category (non-Featured)
            "featured": bool,            # whether Featured category is required
            "all": list[str],            # all categories mentioned
        }

    Examples handled:
      - "CAT: Chicago"
      - "Category: Home Business"
      - "Categories: Featured, Home Business"
      - "Place in category or categories selected: Chicago"
      - "Place in category: Small Business"
    """
    result = {"primary": None, "featured": False, "all": []}

    lines = _split_html_into_lines(html) if html else text.split("\n")
    if not lines:
        lines = [text]

    for line in lines:
        # Only use the strict label patterns — no fallback inline match
        for pattern in _CATEGORY_LABEL_PATTERNS:
            m = re.match(pattern, line.strip(), re.IGNORECASE)
            if m:
                raw = m.group(1).strip()
                # Reject if contains URL markers or is clearly boilerplate
                if re.search(r'https?://', raw) or re.search(r'\bslug\b', raw, re.IGNORECASE):
                    break
                # Take value after last colon if nested (e.g. "selected: Chicago")
                if ":" in raw and not re.search(r'https?://', raw):
                    raw = raw.split(":")[-1].strip()

                parts = re.split(r"[,&+]|\band\b", raw, flags=re.IGNORECASE)
                for p in parts:
                    cat_name = p.strip().strip("\"'").rstrip(".").strip()
                    if not cat_name or _is_category_boilerplate(cat_name):
                        continue
                    if cat_name.lower() == "featured":
                        result["featured"] = True
                        if "Featured" not in result["all"]:
                            result["all"].append("Featured")
                    else:
                        if not result["primary"]:
                            result["primary"] = cat_name
                        if cat_name not in result["all"]:
                            result["all"].append(cat_name)
                break  # only match first pattern per line

    # Check if "Featured" is mentioned anywhere in instructions
    if re.search(r"\bfeatured\b", (text or "") + " " + (html or ""), re.IGNORECASE):
        result["featured"] = True
        if "Featured" not in result["all"]:
            result["all"].append("Featured")

    return result


# ---------------------------------------------------------------------------
# Author parsing
# ---------------------------------------------------------------------------

def parse_author(text: str, html: str = "") -> Optional[str]:
    """
    Extract author requirement from instruction text or HTML.

    Handles patterns like:
      - "AUTHOR: Home Office Editor"
      - "Author: John Smith"
      - "Written by Jane Doe"
      - "Set author to John Smith"
      - "Assign to: Mary Johnson"
      - "Byline: Alex Taylor"
    """
    lines = _split_html_into_lines(html) if html else text.split("\n")
    if not lines:
        lines = [text]

    patterns = [
        r"^\s*AUTHOR\s*[:\-]\s*(.+)$",
        r"^\s*Written\s+by\s*[:\-]?\s*(.+)$",
        r"^\s*Assign(?:ed)?\s+(?:to)?\s*[:\-]\s*(.+)$",
        r"^\s*Byline\s*[:\-]\s*(.+)$",
        r"^\s*Author\s*Name\s*[:\-]\s*(.+)$",
        r"\bauthor\s*[:\-]\s*(.+)",
    ]

    for line in lines:
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                name = match.group(1).strip().strip("\"'").rstrip(".").strip()
                if 2 <= len(name) <= 60 and "<" not in name and not _is_category_boilerplate(name):
                    return name

    return None


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Image directive parsing
# ---------------------------------------------------------------------------

_PROVIDER_URL_MAP = [
    ("dreamstime.com", "dreamstime"),
    ("depositphotos.com", "depositphotos"),
    ("pexels.com", "pexels"),
    ("unsplash.com", "unsplash"),
    ("elements.envato.com", "envato"),
    ("graphicriver.net", "envato"),
    ("envato.com", "envato"),
    ("magnific.ai", "magnific"),
]

_EXPLICIT_PROVIDER_PATTERNS = [
    (
        r"\bsource\s+(?:(?:an?|the|relevant|stock)\s+)*images?\s+from\s+dreamstime\b"
        r"|\bsource\s+from\s+dreamstime\b"
        r"|\b(?:image\s+)?provider\s*[:\-]\s*dreamstime\b"
        r"|\bimage\s*[:\-]\s*dreamstime\b"
        r"|\b(?:must\s+)?use\s+dreamstime\b",
        "dreamstime",
    ),
    (
        r"\bsource\s+(?:(?:an?|the|relevant|stock)\s+)*images?\s+from\s+deposit\s*photos\b"
        r"|\bsource\s+from\s+deposit\s*photos\b"
        r"|\b(?:image\s+)?provider\s*[:\-]\s*deposit\s*photos\b"
        r"|\bimage\s*[:\-]\s*deposit\s*photos\b"
        r"|\b(?:must\s+)?use\s+deposit\s*photos\b",
        "depositphotos",
    ),
    (
        r"\bsource\s+(?:(?:an?|the|relevant|stock)\s+)*images?\s+from\s+pexels\b"
        r"|\bsource\s+from\s+pexels\b"
        r"|\b(?:image\s+)?provider\s*[:\-]\s*pexels\b"
        r"|\bimage\s*[:\-]\s*pexels\b"
        r"|\b(?:must\s+)?use\s+pexels\b",
        "pexels",
    ),
    (
        r"\bsource\s+(?:(?:an?|the|relevant|stock)\s+)*images?\s+from\s+unsplash\b"
        r"|\bsource\s+from\s+unsplash\b"
        r"|\b(?:image\s+)?provider\s*[:\-]\s*unsplash\b"
        r"|\bimage\s*[:\-]\s*unsplash\b"
        r"|\b(?:must\s+)?use\s+unsplash\b",
        "unsplash",
    ),
    (
        r"\bsource\s+(?:(?:an?|the|relevant|stock)\s+)*images?\s+from\s+(?:envato|graphicriver)\b"
        r"|\bsource\s+from\s+(?:envato|graphicriver)\b"
        r"|\b(?:image\s+)?provider\s*[:\-]\s*(?:envato|graphicriver)\b"
        r"|\bimage\s*[:\-]\s*(?:envato|graphicriver)\b"
        r"|\b(?:must\s+)?use\s+(?:envato|graphicriver)\b",
        "envato",
    ),
    (
        r"\bsource\s+(?:(?:an?|the|relevant|stock)\s+)*images?\s+from\s+magnific\b"
        r"|\bsource\s+from\s+magnific\b"
        r"|\b(?:image\s+)?provider\s*[:\-]\s*magnific\b"
        r"|\bimage\s*[:\-]\s*magnific\b"
        r"|\b(?:must\s+)?use\s+magnific\b",
        "magnific",
    ),
    (
        r"\bsource\s+(?:(?:an?|the|relevant|stock)\s+)*images?\s+from\s+calamari\b"
        r"|\bsource\s+from\s+calamari\b"
        r"|\b(?:image\s+)?provider\s*[:\-]\s*calamari\b"
        r"|\bimage\s*[:\-]\s*calamari\b"
        r"|\b(?:must\s+)?use\s+calamari\b",
        "calamari",
    ),
]


def parse_image_directive(text: str, html: str) -> dict:
    """
    Parse the image requirement from instructions.

    Returns:
        {
            "source": str | None,              # provider name or specific URL type
            "required_provider": str | None,   # client-specified provider that MUST be used
            "image_requirement": str | None,   # "included" | "choice" | "explicit" | None
            "url": str | None,                 # specific image URL if provided
            "caption": str | None,             # caption text if provided
            "pexels_id": str | None,           # Pexels photo ID if mentioned
            "prevent_duplicates": bool,        # True if client says "not sourced before"
            "allow_ai_generation": bool,       # True if client allows AI generation
        }

    Priority order:
        1. DOCX embedded image (handled by article_processor)
        2. Client-specified provider or explicit image URL (MUST be obeyed)
        3. User-selected provider from dashboard
        4. AI generation (Magnific) if allowed
    """
    result = {
        "source": None,
        "required_provider": None,
        "image_requirement": None,
        "url": None,
        "caption": None,
        "pexels_id": None,
        "prevent_duplicates": False,
        "allow_ai_generation": False,
        "replace_images": False,
        "image_action": None,
        "caption_requirement": None,
    }

    if not text and not html:
        return result

    # Check for duplicate prevention instruction
    if re.search(
        r"\b(?:not\s+sourced\s+(?:before|previously)|never\s+sourced\s+(?:before|previously)|be\s+sure\s+.*?\bnot\s+sourced\s+(?:before|previously)|no\s+duplicates?)\b",
        text,
        re.IGNORECASE,
    ):
        result["prevent_duplicates"] = True

    # Check for AI generation directive
    if re.search(r"\b(?:allow\s+ai\s+generation|ai\s+generated|ai\s+image|generate\s+with\s+magnific)\b", text, re.IGNORECASE):
        result["allow_ai_generation"] = True

    # Caption extraction (caption instruction only, NOT a provider requirement)
    clean_caption_text = re.sub(r"<[^>]+>", " ", text)
    if re.search(r"\bhyperlink\s+(?:once\s+)?in\s+(?:the\s+)?caption\b", clean_caption_text, re.IGNORECASE):
        result["caption_requirement"] = "Hyperlink once in the caption"
        result["caption"] = "Hyperlink once in the caption"

    caption_match = re.search(
        r"\bcaption\s*[:\-]\s*([^\n\r]+)",
        clean_caption_text,
        re.IGNORECASE,
    )
    if caption_match:
        result["caption"] = " ".join(caption_match.group(1).split())
    elif not result.get("caption"):
        cap_fallback = re.search(
            r"(?:hyperlink\s+(?:once\s+)?in\s+(?:the\s+)?caption|caption\s*[:\-])\s*([^\n\r]+)",
            clean_caption_text,
            re.IGNORECASE,
        )
        if cap_fallback:
            result["caption"] = " ".join(cap_fallback.group(0).split())

    # Rule 1: "IMAGE: Included" -> IMAGE REQUIREMENT: INCLUDED; use existing image
    if re.search(
        r"\bimage[s]?\s*:\s*included\b|\bimage[s]?\s*(?:is|are)?\s*included\b|\buse\s+(?:the\s+)?existing\s+image[s]?\b",
        text,
        re.IGNORECASE,
    ):
        result["source"] = "included"
        result["image_requirement"] = "included"
        result["required_provider"] = None
        result["replace_images"] = False
        result["image_action"] = "use_existing"
        log.info("Parsed image directive: IMAGE: Included (use existing image)")
        return result

    # Rule 2: "IMAGE: REPLACE IMAGES from a platform of your choice" -> NO client provider required; replace images
    is_replace = bool(re.search(r"\breplace\s+images?\b", text, re.IGNORECASE))
    is_choice = bool(re.search(
        r"\b(?:replace\s+images?\s+(?:from\s+a\s+)?)?platform\s+of\s+(?:your\s+)?choice\b|\bprovider\s+of\s+(?:your\s+)?choice\b|\bany\s+platform\b",
        text,
        re.IGNORECASE,
    ))

    if is_replace:
        result["replace_images"] = True
        result["image_action"] = "replace"

    if is_choice:
        result["source"] = None
        result["image_requirement"] = "choice"
        result["required_provider"] = None
        result["replace_images"] = True
        result["image_action"] = "replace"
        log.info("Parsed image directive: Platform of choice (no client required provider, replace images)")
        return result

    # 1. Check for specific provider URLs in HTML links (exclude caption links)
    links = extract_links_from_html(html)
    for link in links:
        url_lower = link["url"].lower()
        anchor = (link.get("anchor_text") or "").strip()

        # If link is part of caption instruction, do not treat as asset URL
        is_caption = False
        if re.search(rf"(?:hyperlink\s+(?:once\s+)?in\s+(?:the\s+)?caption|caption\s*[:\-]).*?{re.escape(link['url'])}", html or "", re.IGNORECASE | re.DOTALL):
            is_caption = True
        elif anchor and re.search(rf"(?:hyperlink\s+(?:once\s+)?in\s+(?:the\s+)?caption|caption\s*[:\-]).*?{re.escape(anchor)}", text or "", re.IGNORECASE):
            is_caption = True

        if is_caption:
            if not result.get("caption") and anchor:
                result["caption"] = anchor
            continue

        for domain, provider_id in _PROVIDER_URL_MAP:
            if domain in url_lower:
                result["source"] = provider_id
                result["required_provider"] = provider_id
                result["image_requirement"] = "explicit"
                result["url"] = link["url"]
                if anchor and not result.get("caption"):
                    result["caption"] = anchor

                if provider_id == "pexels":
                    pid_match = re.search(r"/photo/[^/]+-(\d+)/?$", link["url"])
                    if pid_match:
                        result["pexels_id"] = pid_match.group(1)

                log.info("Parsed %s image directive URL: %r", provider_id, result["url"])
                return result

    # 2. Check plain text for asset URLs (excluding caption text)
    text_without_caption = re.sub(
        r"(?:hyperlink\s+(?:once\s+)?in\s+(?:the\s+)?caption|caption\s*[:\-]).*$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    for domain, provider_id in _PROVIDER_URL_MAP:
        url_match = re.search(rf"https?://[^\s]*{re.escape(domain)}[^\s/]+/[^\s]+", text_without_caption, re.IGNORECASE)
        if url_match:
            found_url = url_match.group(0).rstrip(".,;)")
            result["source"] = provider_id
            result["required_provider"] = provider_id
            result["image_requirement"] = "explicit"
            result["url"] = found_url

            if provider_id == "pexels":
                pid_match = re.search(r"/photo/[^/]+-(\d+)/?$", found_url)
                if pid_match:
                    result["pexels_id"] = pid_match.group(1)

            log.info("Parsed %s image directive URL from text: %r", provider_id, found_url)
            return result

    # 3. Check plain text for explicit provider directives (e.g. "Source a relevant image from Dreamstime")
    for pattern, provider_id in _EXPLICIT_PROVIDER_PATTERNS:
        if re.search(pattern, text_without_caption, re.IGNORECASE):
            result["source"] = provider_id
            result["required_provider"] = provider_id
            result["image_requirement"] = "explicit"
            log.info("Parsed client-required provider directive: %s", provider_id)
            return result

    return result


# ---------------------------------------------------------------------------
# Authority link parsing
# ---------------------------------------------------------------------------

def parse_authority_links(text: str, html: str) -> list[dict]:
    """
    Extract authority link requirements from instructions.

    Returns a list of dicts: { url, anchor_text, required }
    where required=True means the URL was explicitly provided.

    Never fabricates URLs — only returns URLs that are literally in the source.
    """
    authority_links = []

    # Look for "authority link" section in text
    auth_section_match = re.search(
        r"(?:authority\s+link|external\s+link|outbound\s+link)[s]?\s*[:\-]?\s*(.*?)(?=\n\n|\Z)",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    # Extract all real URLs from the authority link section (no fabrication)
    links = extract_links_from_html(html)
    for link in links:
        url_lower = link["url"].lower()
        # Skip internal links, WordPress admin, Basecamp links
        is_internal = any(d in url_lower for d in (
            "basecampapi.com",
            "basecamp.com",
            "espialsolutions.com",
            "homebusinessmag.com",
        ))
        if not is_internal:
            # Only include links that are in or near authority link text
            # or are clearly authority/reference links (not image links)
            if auth_section_match:
                section = auth_section_match.group(0).lower()
                if link["url"].lower() in section or any(
                    word in section for word in ("authority", "external", "outbound", "link")
                ):
                    authority_links.append({
                        "url": link["url"],
                        "anchor_text": link["anchor_text"],
                        "required": True,
                    })

    # If no section found, scan for any explicitly provided authority URL patterns in text
    if not authority_links:
        # Look for patterns like "Use: https://..." or "Link to: ..."
        url_after_directive = re.findall(
            r"(?:use|link\s+to|authority[:\s]+|external[:\s]+)\s*(https?://[^\s<>\"]+)",
            text,
            re.IGNORECASE,
        )
        for url in url_after_directive:
            url = url.rstrip(".,;)")
            authority_links.append({
                "url": url,
                "anchor_text": "",
                "required": True,
            })

    return authority_links


# ---------------------------------------------------------------------------
# SEO requirement parsing
# ---------------------------------------------------------------------------

def parse_seo_requirements(text: str) -> dict:
    """
    Parse SEO-related instructions from plain text.

    Returns:
        {
            "has_seo_instructions": bool,
            "focus_keyphrase": str | None,
            "seo_title": str | None,
            "meta_description": str | None,
            "slug": str | None,
            "synonyms": list[str],
            "raw_rules": list[str],
        }
    """
    result = {
        "has_seo_instructions": False,
        "focus_keyphrase": None,
        "seo_title": None,
        "meta_description": None,
        "slug": None,
        "synonyms": [],
        "raw_rules": [],
    }

    seo_terms = (
        "yoast", "seo", "focus keyphrase", "focus keyword", "meta description",
        "seo title", "slug", "keyphrase", "keyword density",
    )
    has_seo = any(term in text.lower() for term in seo_terms)
    result["has_seo_instructions"] = has_seo

    field_patterns = {
        "focus_keyphrase": re.compile(
            r"\b(?:focus\s+keyphrase|focus\s+keyword|target\s+keyword|primary\s+keyword)"
            r"\b\s*(?::|is|should\s+be|=)\s*(.+?)(?:[;\n]|$)",
            re.IGNORECASE,
        ),
        "seo_title": re.compile(
            r"\b(?:seo\s+title|title\s+tag)\b\s*(?::|is|should\s+be|=)\s*(.+?)(?:[;\n]|$)",
            re.IGNORECASE,
        ),
        "meta_description": re.compile(
            r"\bmeta\s+description\b\s*(?::|is|should\s+be|=)\s*(.+?)(?:[;\n]|$)",
            re.IGNORECASE,
        ),
        "slug": re.compile(
            r"\b(?:url\s+slug|post\s+slug|slug)\b\s*(?::|is|should\s+be|=)\s*(.+?)(?:[;\n]|$)",
            re.IGNORECASE,
        ),
    }

    # Maximum field lengths — anything longer is boilerplate, not a real value
    _MAX_FIELD_LENGTHS = {
        "focus_keyphrase": 80,
        "seo_title": 70,
        "meta_description": 200,
        "slug": 100,
    }

    for field, pattern in field_patterns.items():
        match = pattern.search(text)
        if match:
            value = match.group(1).strip().strip("\"'")
            max_len = _MAX_FIELD_LENGTHS.get(field, 200)
            if len(value) <= max_len:
                result[field] = value
            else:
                log.debug("SEO field %r value too long (%d chars) — ignoring", field, len(value))

    # Keyphrase synonyms
    syn_match = re.search(
        r"\b(?:keyphrase\s+synonyms|keyword\s+synonyms|synonyms)\s*[:\-]\s*(.+?)(?:\n|$)",
        text,
        re.IGNORECASE,
    )
    if syn_match:
        raw_syn = syn_match.group(1)
        if len(raw_syn) <= 150:
            result["synonyms"] = [
                s.strip().strip("\"'")
                for s in re.split(r"[,;]", raw_syn)
                if s.strip()
            ]

    # Raw SEO rule sentences
    rule_keywords = (
        "keyword density", "heading", "internal link", "external link",
        "readability", "yoast", "seo requirement", "meta description",
        "focus keyword", "focus keyphrase", "seo title", "url slug",
        "keyphrase", "synonym",
    )
    result["raw_rules"] = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text)
        if any(kw in sentence.lower() for kw in rule_keywords)
    ]

    return result


# ---------------------------------------------------------------------------
# Main parser entry point
# ---------------------------------------------------------------------------

def parse_instructions(html: str) -> dict:
    """
    Parse a full Basecamp message HTML body and return structured article requirements.

    Parameters
    ----------
    html : str
        The raw HTML body of the Basecamp message (client instructions).

    Returns
    -------
    dict with keys:
        raw_html         : original HTML
        raw_text         : stripped plain text
        category         : { primary, featured, all }
        author           : str | None
        image_directive  : { source, url, caption, pexels_id }
        authority_links  : list[{ url, anchor_text, required }]
        seo              : { has_seo_instructions, focus_keyphrase, ... }
        all_links        : list[{ url, anchor_text }]  — every hyperlink in instructions
    """
    if not html:
        return _empty_result(html)

    text = strip_html(html)

    category = parse_category(text, html)
    author = parse_author(text, html)
    image_directive = parse_image_directive(text, html)
    authority_links = parse_authority_links(text, html)
    seo = parse_seo_requirements(text)
    all_links = extract_links_from_html(html)

    log.info(
        "Parsed Basecamp instructions — category=%r author=%r image=%r auth_links=%d",
        category.get("primary"),
        author,
        image_directive.get("source"),
        len(authority_links),
    )

    return {
        "raw_html": html,
        "raw_text": text,
        "category": category,
        "author": author,
        "image_directive": image_directive,
        "authority_links": authority_links,
        "seo": seo,
        "all_links": all_links,
    }


def _empty_result(html: str) -> dict:
    return {
        "raw_html": html or "",
        "raw_text": "",
        "category": {"primary": None, "featured": False, "all": []},
        "author": None,
        "image_directive": {
            "source": None,
            "url": None,
            "caption": None,
            "pexels_id": None,
            "required_provider": None,
            "image_requirement": None,
            "prevent_duplicates": False,
            "allow_ai_generation": False,
            "replace_images": False,
            "image_action": None,
            "caption_requirement": None,
        },
        "authority_links": [],
        "seo": {
            "has_seo_instructions": False,
            "focus_keyphrase": None,
            "seo_title": None,
            "meta_description": None,
            "slug": None,
            "synonyms": [],
            "raw_rules": [],
        },
        "all_links": [],
    }
