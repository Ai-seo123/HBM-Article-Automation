"""
Gemini AI service — SEO-only processing.

Security:
  - GEMINI_API_KEY is read from environment variables only.
  - The key is NEVER returned to the frontend or logged.

Gemini's role is STRICTLY LIMITED to:
  1. Generating SEO metadata (focus keyphrase, SEO title, meta description, slug, synonyms)
  2. Generating image metadata (alt text, title, caption)

Gemini MUST NOT:
  - Rewrite, summarise, or modify article content
  - Invent hyperlinks or URLs
  - Remove or add article content
  - Change article structure

Content preservation is handled by the document extraction layer (documents.py).
"""

import json
import logging
import re
from typing import Any, Optional

from core.config import settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration check
# ---------------------------------------------------------------------------

def is_configured() -> bool:
    """Return True if the Gemini API key is present."""
    return bool(settings.GEMINI_API_KEY)


# ---------------------------------------------------------------------------
# HTML stripping helper
# ---------------------------------------------------------------------------

def _strip_html(html: str) -> str:
    """Minimal HTML tag removal."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------

def _repair_truncated_json(text: str) -> str:
    """
    Attempt to repair a truncated JSON string by closing any open strings
    and objects/arrays.

    This handles the specific case where Gemini cuts off mid-string due to
    token limits. Strategy:
      1. Find the last complete key-value pair.
      2. Close any open string (add a closing quote if needed).
      3. Close any open objects/arrays.
    """
    text = text.strip()
    if not text:
        return text

    # Count open braces to determine how many closing braces we need
    depth = 0
    in_string = False
    escape_next = False
    last_safe_pos = 0  # position of last successfully closed value

    i = 0
    while i < len(text):
        ch = text[i]
        if escape_next:
            escape_next = False
        elif ch == '\\':
            escape_next = True
        elif ch == '"' and not escape_next:
            in_string = not in_string
            if not in_string:
                last_safe_pos = i
        elif not in_string:
            if ch in ('{', '['):
                depth += 1
            elif ch in ('}', ']'):
                depth -= 1
                last_safe_pos = i
        i += 1

    # If we're inside an unterminated string, close it
    if in_string:
        text = text + '"'

    # Close any open objects
    text = text + ('}' * max(0, depth))

    return text


def _extract_json_from_text(text: str) -> dict:
    """
    Try to parse JSON from the response text.
    Handles: markdown fences, truncated responses, extra text wrapping.
    Falls back to regex field extraction if JSON parsing completely fails.
    """
    text = text.strip()

    # Strip markdown fences
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()

    # Pass 1: try as-is
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        pass

    # Pass 2: extract the outermost {...} block
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate, strict=False)
        except json.JSONDecodeError:
            pass

        # Pass 3: try to repair the extracted block (truncation recovery)
        repaired = _repair_truncated_json(candidate)
        try:
            result = json.loads(repaired, strict=False)
            log.warning(
                "Gemini returned truncated JSON — repaired successfully. "
                "Consider increasing max_output_tokens."
            )
            return result
        except json.JSONDecodeError as exc:
            log.warning("JSON repair failed: %s", exc)

    # Pass 4: try to repair the full text
    repaired_full = _repair_truncated_json(text)
    try:
        return json.loads(repaired_full, strict=False)
    except json.JSONDecodeError as exc:
        log.warning("JSON repair on full text failed: %s", exc)

    # Pass 5: Field-by-field regex extraction (last resort — handles malformed JSON)
    log.warning("Attempting field-by-field regex extraction from Gemini response")
    extracted = {}
    fields = ["focus_keyphrase", "seo_title", "meta_description", "slug", "synonyms", "excerpt",
              "alt_text", "image_title", "caption"]
    for field in fields:
        # Match: "field_name": "value" or "field_name": value
        pattern = rf'["\']?{re.escape(field)}["\']?\s*:\s*["\']([^"\'{{}}]+)["\']'
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            extracted[field] = m.group(1).strip()
        else:
            # Try without quotes on value
            pattern2 = rf'["\']?{re.escape(field)}["\']?\s*:\s*([^,\n\r{{}}]+)'
            m2 = re.search(pattern2, text, re.IGNORECASE)
            if m2:
                extracted[field] = m2.group(1).strip().strip('"\'')

    if extracted:
        log.warning("Recovered %d fields via regex extraction: %s", len(extracted), list(extracted.keys()))
        return extracted

    log.error("Gemini response is not valid JSON (all repair attempts failed): %s", exc if 'exc' in dir() else "unknown")
    raise ValueError(f"Gemini response is not valid JSON: {text[:200]}") from (exc if 'exc' in dir() else None)



# ---------------------------------------------------------------------------
# Gemini model helper
# ---------------------------------------------------------------------------

def _get_model():
    """Configure and return the Gemini GenerativeModel."""
    try:
        import google.generativeai as genai
    except ImportError as exc:
        raise RuntimeError(
            "google-generativeai is not installed. "
            "Add it to requirements.txt and reinstall."
        ) from exc

    genai.configure(api_key=settings.GEMINI_API_KEY)
    return genai.GenerativeModel(settings.GEMINI_MODEL)


async def _call_gemini(prompt: str, expect_json: bool = True) -> str:
    """
    Send a prompt to Gemini and return the raw text response.

    Notes on token limits:
    - SEO fields (keyphrase + title + desc + slug + synonyms + excerpt) fit easily in 512 tokens.
    - We use 1024 as a safe ceiling with headroom for verbose models.
    - We do NOT use response_mime_type="application/json" because some Gemini
      versions truncate JSON responses mid-string when the mime type forces
      strict serialisation. Plain text + manual parsing is more robust.
    """
    if not is_configured():
        raise RuntimeError(
            "Gemini API key is not configured. "
            "Set GEMINI_API_KEY in backend/.env to enable AI processing."
        )

    try:
        import google.generativeai as genai
        model = _get_model()
        config_kwargs: dict[str, Any] = {
            "temperature": 0.2,
            "max_output_tokens": 800,  # Enough for all 6 short SEO fields
        }
        # NOTE: We intentionally do NOT set response_mime_type="application/json".
        # That setting can cause Gemini to truncate mid-string on some model versions.
        # We parse JSON manually from the plain text response instead.

        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(**config_kwargs),
        )
    except Exception as exc:
        error_str = str(exc)
        log.error("Gemini API error: %s", type(exc).__name__)
        if "quota" in error_str.lower() or "rate" in error_str.lower() or "429" in error_str:
            raise RuntimeError(
                "Gemini API rate limit or quota exceeded. Please try again later."
            ) from exc
        if "timeout" in error_str.lower() or "deadline" in error_str.lower():
            raise RuntimeError("Gemini API request timed out. Please try again.") from exc
        if "api_key" in error_str.lower() or "invalid" in error_str.lower() or "403" in error_str:
            raise RuntimeError(
                "Gemini API key is invalid or lacks permissions. Check GEMINI_API_KEY."
            ) from exc
        raise RuntimeError(f"Gemini API error: {type(exc).__name__}. Please try again.") from exc

    try:
        raw_text = response.text
    except Exception:
        raise ValueError(
            "Gemini returned an empty or blocked response. "
            "The article may have triggered a content filter."
        )

    if not raw_text or not raw_text.strip():
        raise ValueError("Gemini returned an empty response.")

    log.info("Gemini raw response length: %d chars", len(raw_text))
    return raw_text


# ---------------------------------------------------------------------------
# SEO generation
# ---------------------------------------------------------------------------

def _sanitize_for_prompt(s: str, max_len: int) -> str:
    """Sanitize a string for safe embedding inside a Gemini prompt / JSON string."""
    # Replace typographic dashes with standard hyphen
    s = s.replace('\u2011', '-').replace('\u2012', '-').replace('\u2013', '-').replace('\u2014', '--')
    # Replace curly/smart quotes
    s = s.replace('\u201c', '"').replace('\u201d', '"').replace('\u2018', "'").replace('\u2019', "'")
    # Replace non-breaking space
    s = s.replace('\u00a0', ' ')
    # Strip remaining non-ASCII
    s = re.sub(r'[^\x20-\x7E]', ' ', s)
    # Escape JSON-breaking chars
    s = s.replace('\\', ' ').replace('"', "'").replace('\n', ' ').strip()
    return s[:max_len]


def _build_seo_prompt(
    article_title: str,
    client_instructions_plain: str,
    parsed_seo: dict,
) -> str:
    """
    Build a compact prompt asking Gemini to act as a Yoast SEO expert.

    Key design decisions:
    - We do NOT include article body text in the prompt — it causes token bloat
      and risks special characters (quotes, braces) breaking JSON parsing.
    - All fields have hard character limits stated in the prompt to prevent
      Gemini from writing long values that could truncate.
    - We ask for plain JSON with no markdown fences.
    """
    # IMPORTANT: Prompt is kept very short so Gemini's entire response fits in 800 tokens.
    # The "client notes" is intentionally excluded from the core prompt — it's the boilerplate
    # HBM posting guide, not article-specific instructions. Only the title is needed.

    safe_title = _sanitize_for_prompt(article_title, 120)

    # Build short overrides section only if explicit values exist
    overrides_parts: list[str] = []
    for field in ("focus_keyphrase", "seo_title", "meta_description", "slug"):
        val = parsed_seo.get(field)
        if val and len(str(val)) < 160:
            overrides_parts.append(f'{field}="{val}"')
    overrides_note = ("Use: " + ", ".join(overrides_parts) + ".\n") if overrides_parts else ""

def _build_seo_prompt(
    article_title: str,
    client_instructions_plain: str,
    parsed_seo: dict,
) -> str:
    """
    Build a compact prompt asking Gemini to act as a Yoast SEO expert.
    Enforces:
    - Focus keyphrase directly from original title, preserving exact phrase including filler words.
    - SEO title begins with exact focus keyphrase and remains as close as possible to original title.
    - Meta description naturally includes exact focus keyphrase preserving wording and order.
    - Only the slug removes unnecessary filler words while keeping meaningful words.
    """
    safe_title = _sanitize_for_prompt(article_title, 120)

    overrides_parts: list[str] = []
    for field in ("focus_keyphrase", "seo_title", "meta_description", "slug"):
        val = parsed_seo.get(field)
        if val and len(str(val)) < 160:
            overrides_parts.append(f'{field}="{val}"')
    overrides_note = ("Use: " + ", ".join(overrides_parts) + ".\n") if overrides_parts else ""

    return f"""Yoast SEO expert. Generate SEO metadata JSON for this article title.

Title: {safe_title}
{overrides_note}
CRITICAL REQUIREMENTS:
- "focus_keyphrase": EXACT phrase extracted directly from the title (2 to 4 words), preserving the exact selected words including any filler words (e.g. for, in, to, of, the). Do NOT remove filler words from the keyphrase.
- "seo_title": Must begin with that exact focus keyphrase and remain as close as possible to the original article title (max 60 chars). Do NOT rewrite with generic words.
- "meta_description": 140-155 characters naturally including the exact focus keyphrase, preserving its wording and order. Must be strictly between 140 and 155 characters.
- "slug": Short lowercase hyphen-separated slug containing the focus keyphrase with unnecessary filler words (for, the, a, of, to, in) removed. Only the slug may remove filler words.
- "synonyms": 1-2 relevant synonyms.
- "excerpt": Exact copy of meta description.

Respond with ONLY this JSON object, no other text:
{{"focus_keyphrase":"exact phrase from title with filler words preserved","seo_title":"keyphrase at start keeping original title","meta_description":"140-155 characters naturally with exact keyphrase","slug":"clean-slug-no-filler-words","synonyms":"synonym1, synonym2","excerpt":"140-155 characters naturally with exact keyphrase"}}"""


def extract_title_keyphrase(title: str) -> str:
    """
    Extract the focus keyphrase directly from the original article H1/title:
    - Preserves the exact selected phrase, INCLUDING its filler words.
    - Does NOT strip filler words (e.g. for, to, in, of, the).
    - Preserves exact substring matching the title.
    """
    if not title:
        return "business growth"

    clean_t = re.sub(r'[\u2011\u2012\u2013\u2014]', '-', title).strip()
    # Check if title has a colon or em-dash separator
    sections = [s.strip() for s in re.split(r'[:|–—]', clean_t) if s.strip()]
    target_section = sections[0] if sections else clean_t

    words = target_section.split()
    if not words:
        words = clean_t.split()
    if not words:
        return "business growth"

    # Only strip a leading list number like "5 Corporate Gifts..." or "How to ..."
    start_idx = 0
    if words and (words[0].isdigit() or re.match(r'^\d+[a-z]?$', words[0], re.IGNORECASE)):
        start_idx = 1
    elif len(words) >= 3 and words[0].lower() == "how" and words[1].lower() == "to":
        start_idx = 2

    candidate_words = words[start_idx:] if len(words) > start_idx else words
    # Take 2-4 contiguous words directly from the title preserving all filler words
    if len(candidate_words) >= 4:
        phrase_words = candidate_words[:4]
    elif len(candidate_words) >= 2:
        phrase_words = candidate_words
    else:
        phrase_words = words[:4]

    phrase = " ".join(phrase_words).strip(" ,.-–—:;\"'?")
    return phrase if phrase else "business growth"


def build_clean_slug(title: str, focus_keyphrase: str) -> str:
    """
    Generate a clean slug:
    - Only the slug may remove unnecessary filler words (for, the, a, of, to, in, with, by).
    - Keeps the focus keyphrase's meaningful words in the slug.
    """
    filler_words = {'for', 'the', 'a', 'an', 'of', 'in', 'on', 'at', 'to', 'with', 'by', 'is', 'are', 'was', 'were'}

    kp_clean = (focus_keyphrase or "").lower()
    kp_clean = re.sub(r'[\u2011\u2012\u2013\u2014]', '-', kp_clean)
    kp_words = [w for w in re.sub(r'[^a-z0-9\s-]', ' ', kp_clean).split() if w]

    # Meaningful words of the focus keyphrase with filler words removed
    meaningful_kp_words = [w for w in kp_words if w not in filler_words]
    if not meaningful_kp_words:
        meaningful_kp_words = kp_words

    clean_t = re.sub(r'[\u2011\u2012\u2013\u2014]', '-', title).lower()
    clean_t = re.sub(r'[^a-z0-9\s-]', ' ', clean_t)
    title_words = [w for w in clean_t.split() if w and w not in filler_words]

    # Combine keyphrase meaningful words with context words
    chosen = list(meaningful_kp_words)
    for w in title_words:
        if w not in chosen and len(chosen) < 7:
            chosen.append(w)

    slug = "-".join(chosen)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if len(slug) > 80:
        slug = slug[:80].rsplit("-", 1)[0]
    return slug


async def generate_seo(
    article_title: str,
    article_text_plain: str,  # kept in signature for backwards compat, not used in prompt
    client_instructions_html: str,
    parsed_seo: dict,
) -> dict:
    """
    Use Gemini as a Yoast SEO expert to generate ONLY SEO metadata.
    Enforces all strict client requirements:
    - Focus keyphrase <= 4 words, directly from original title
    - SEO title places focus keyphrase at the beginning
    - Slug removes filler words while retaining keyphrase
    - Meta description strictly compliant and synced with excerpt

    Returns
    -------
    dict with keys: focus_keyphrase, seo_title, meta_description, slug, synonyms, excerpt
    """
    plain_instructions = _strip_html(client_instructions_html)
    prompt = _build_seo_prompt(
        article_title=article_title,
        client_instructions_plain=plain_instructions,
        parsed_seo=parsed_seo,
    )

    log.info("Sending SEO generation request to Gemini (title=%r)", article_title)
    log.info("Prompt length: %d chars", len(prompt))

    raw_text = await _call_gemini(prompt, expect_json=False)
    log.info("Gemini SEO response received (%d chars): %.200s", len(raw_text), raw_text)

    parsed = _extract_json_from_text(raw_text)

    seo_fields = {
        "focus_keyphrase": str(parsed.get("focus_keyphrase", "")).strip()[:60],
        "seo_title":       str(parsed.get("seo_title", "")).strip()[:60],
        "meta_description":str(parsed.get("meta_description", "")).strip()[:160],
        "slug":            str(parsed.get("slug", "")).strip()[:80],
        "synonyms":        str(parsed.get("synonyms", "")).strip()[:100],
        "excerpt":         str(parsed.get("excerpt", "")).strip()[:200],
    }

    # Overwrite with explicit fields from instructions (highest priority)
    for field in ("focus_keyphrase", "seo_title", "meta_description", "slug"):
        explicit = parsed_seo.get(field)
        if explicit:
            seo_fields[field] = str(explicit).strip()
            log.info("SEO field %r overridden from instructions: %r", field, explicit)

    if parsed_seo.get("synonyms"):
        seo_fields["synonyms"] = ", ".join(parsed_seo["synonyms"])[:100]

    # ── Strict Client Requirements Validation ──────────────────────────────
    # 1. Focus Keyphrase: Must be extracted directly from title, preserving exact selected phrase including filler words
    kp = seo_fields.get("focus_keyphrase", "").strip()
    title_lower = article_title.lower()

    if not kp or kp.lower() not in title_lower:
        fallback_kp = extract_title_keyphrase(article_title)
        log.info("Focus keyphrase extracted directly from title preserving filler words: %r", fallback_kp)
        kp = fallback_kp
        seo_fields["focus_keyphrase"] = kp
    else:
        # Match exact casing and wording from article_title
        m = re.search(re.escape(kp), article_title, re.IGNORECASE)
        if m:
            kp = m.group(0)
            seo_fields["focus_keyphrase"] = kp

    # 2. SEO Title: Must begin with that exact focus keyphrase and remain as close as possible to the original article title
    st = seo_fields.get("seo_title", "").strip()
    if not st or not st.lower().startswith(kp.lower()):
        clean_title = re.sub(r'[\u2011\u2012\u2013\u2014]', '-', article_title).strip()
        if clean_title.lower().startswith(kp.lower()):
            st = clean_title
        else:
            pattern = re.compile(re.escape(kp), re.IGNORECASE)
            rest_title = pattern.sub("", clean_title).strip(" :-–—")
            if rest_title:
                st = f"{kp}: {rest_title}"
            else:
                st = clean_title
    if not st.lower().startswith(kp.lower()):
        st = f"{kp}: {st}"
    seo_fields["seo_title"] = st[:60]

    # 3. Slug: Only the slug may remove unnecessary filler words, keeping meaningful words
    seo_fields["slug"] = build_clean_slug(article_title, kp)
    log.info("Optimized slug with filler words stripped: %r", seo_fields["slug"])

    # 4. Meta Description: Natural inclusion of keyphrase, strictly 140-155 characters
    try:
        from services.seo_optimizer import optimize_meta_description
        seo_fields["meta_description"] = optimize_meta_description(
            seo_fields["meta_description"],
            seo_fields["focus_keyphrase"],
            article_title,
        )
    except Exception as exc:
        log.warning("optimize_meta_description in gemini.py encountered warning: %s", exc)

    # 5. Excerpt: MUST match meta_description exactly
    seo_fields["excerpt"] = seo_fields["meta_description"]

    # 6. Synonyms fallback
    if not seo_fields["synonyms"] and kp:
        seo_fields["synonyms"] = kp

    log.info(
        "SEO generation complete: keyphrase=%r seo_title=%r slug=%r meta=%r",
        seo_fields["focus_keyphrase"],
        seo_fields["seo_title"],
        seo_fields["slug"],
        seo_fields["meta_description"][:50] if seo_fields["meta_description"] else "",
    )
    return seo_fields


# ---------------------------------------------------------------------------
# Image metadata generation
# ---------------------------------------------------------------------------

def ensure_exact_keyphrase_alt_text(
    alt_text: Optional[str],
    focus_keyphrase: str,
    article_title: str = "",
) -> str:
    """
    Validate and enforce that the featured image Alt Text exactly equals
    the article's final Focus Keyphrase string, character-for-character.

    Requirements:
    - Set the image Alt Text to the exact Focus Keyphrase string, character-for-character.
    - Alt Text must contain ONLY the Focus Keyphrase.
    - Do not append descriptive context, extra words, punctuation, or text generated from the article.
    - Do not change the capitalization, word order, spelling, or spacing of the Focus Keyphrase.
    - If focus_keyphrase is empty or missing, fallback gracefully to article title or alt_text.
    """
    if focus_keyphrase and focus_keyphrase.strip():
        return focus_keyphrase.strip()
    return (alt_text or article_title or "Featured Image")[:125].strip()


async def generate_image_metadata(
    article_title: str,
    image_context: str = "",
    focus_keyphrase: str = "",
) -> dict:
    """
    Use Gemini to generate image SEO metadata ONLY.

    Requirements:
    - Alt text: Must contain ONLY the exact focus keyphrase character-for-character.
      Example: Focus Keyphrase = Modern Office Interior Design -> Alt text = Modern Office Interior Design
    - Title: concise, professional (max 50 chars).
    - Caption: informative caption or credit (max 90 chars).

    Returns
    -------
    dict with keys: alt_text, image_title, caption
    """
    # Sanitize title to avoid JSON-breaking chars
    safe_t = re.sub(r'[\u2011\u2012\u2013\u2014]', '-', article_title)
    safe_t = re.sub(r'[^\x20-\x7E]', ' ', safe_t).strip()[:100]
    safe_kp = (focus_keyphrase or "").strip()

    clean_title = re.sub(r'[\u2011\u2012\u2013\u2014]', '-', article_title)
    clean_title = re.sub(r'[^\x20-\x7E]', ' ', clean_title).strip()

    prompt = f"""Generate image SEO metadata for the featured image of this article.
CRITICAL ALT TEXT REQUIREMENT:
The "alt_text" field MUST contain ONLY the exact focus keyphrase character-for-character: "{safe_kp}".
Do NOT append descriptive context, extra words, or punctuation.
Example: Focus Keyphrase = Modern Office Interior Design -> Alt text = Modern Office Interior Design

Respond with ONLY this JSON:
{{"alt_text":"{safe_kp}","image_title":"max 50 char title","caption":"max 90 char caption"}}

Article title: {safe_t}
Focus keyphrase: {safe_kp}"""

    log.info("Generating image metadata for title: %r (keyphrase: %r)", article_title, focus_keyphrase)

    try:
        raw_text = await _call_gemini(prompt, expect_json=True)
        parsed = _extract_json_from_text(raw_text)
        alt = str(parsed.get("alt_text", "")).strip()
        title = str(parsed.get("image_title", "")).strip()[:60]
        caption = str(parsed.get("caption", "")).strip()[:100]

        # Enforce exact focus keyphrase character-for-character, casing, and word order with no extra text
        alt = ensure_exact_keyphrase_alt_text(alt, focus_keyphrase=safe_kp, article_title=clean_title)

        if not title:
            words = clean_title.split()
            title = ' '.join(words[:6])[:55]
        if not caption:
            caption = f"Featured image for: {clean_title}"[:90]

        return {"alt_text": alt, "image_title": title, "caption": caption}
    except Exception as exc:
        log.warning("Image metadata generation failed: %s — using fallback", exc)
        fallback_alt = ensure_exact_keyphrase_alt_text("", focus_keyphrase=safe_kp, article_title=clean_title)
        words = clean_title.split()
        return {
            "alt_text": fallback_alt,
            "image_title": ' '.join(words[:6])[:55],
            "caption": f"Featured image for: {clean_title}"[:90],
        }


# ---------------------------------------------------------------------------
# Legacy compatibility — kept to avoid breaking imports in article_processor.py
# (will be replaced in next step)
# ---------------------------------------------------------------------------

def extract_client_seo_requirements(client_instructions: str) -> dict:
    """
    Extract only SEO requirements explicitly present in client instructions.
    Kept for backwards compatibility — new code should use basecamp_parser.parse_seo_requirements.
    """
    instructions = _strip_html(client_instructions)
    requirements = {
        "source_text": instructions,
        "explicit_fields": {},
        "other_rules": [],
    }

    _SEO_FIELD_PATTERNS = {
        "focus_keyphrase": re.compile(
            r"\b(?:focus\s+keyphrase|focus\s+keyword|target\s+keyword|primary\s+keyword)"
            r"\b\s*(?::|is|should\s+be)\s*(.+?)(?:[.;\n]|$)",
            re.IGNORECASE,
        ),
        "seo_title": re.compile(
            r"\b(?:seo\s+title|title\s+tag)\b\s*(?::|is|should\s+be)\s*(.+?)(?:[.;\n]|$)",
            re.IGNORECASE,
        ),
        "meta_description": re.compile(
            r"\bmeta\s+description\b\s*(?::|is|should\s+be)\s*(.+?)(?:[.;\n]|$)",
            re.IGNORECASE,
        ),
        "slug": re.compile(
            r"\b(?:url\s+slug|post\s+slug|slug)\b\s*(?::|is|should\s+be)\s*(.+?)(?:[.;\n]|$)",
            re.IGNORECASE,
        ),
    }

    for field, pattern in _SEO_FIELD_PATTERNS.items():
        match = pattern.search(instructions)
        if match:
            requirements["explicit_fields"][field] = match.group(1).strip()

    rule_terms = (
        "keyword density", "heading", "internal link", "external link",
        "readability", "yoast", "seo requirement", "meta description",
        "focus keyword", "focus keyphrase", "seo title", "url slug",
    )
    requirements["other_rules"] = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", instructions)
        if any(term in sentence.lower() for term in rule_terms)
    ]
    return requirements


async def process_article(
    article_text: str,
    client_instructions: str,
) -> dict:
    """
    Legacy entry point — kept for backwards compatibility.
    Now only generates SEO fields; content is preserved from DOCX.

    NOTE: This is the OLD interface. The new pipeline in article_processor.py
    calls generate_seo() and generate_image_metadata() directly.
    """
    if not is_configured():
        raise RuntimeError(
            "Gemini API key is not configured. "
            "Set GEMINI_API_KEY in backend/.env to enable AI processing."
        )

    if not article_text or not article_text.strip():
        raise ValueError("Article text is empty — cannot send to Gemini.")

    import services.basecamp_parser as bp
    parsed_instructions = bp.parse_instructions(client_instructions)
    parsed_seo = parsed_instructions.get("seo", {})

    # Extract title from first line of text
    first_line = article_text.strip().split("\n")[0].strip()
    article_title = first_line[:200] if first_line else "Article"

    seo_fields = await generate_seo(
        article_title=article_title,
        article_text_plain=article_text,
        client_instructions_html=client_instructions,
        parsed_seo=parsed_seo,
    )

    return {
        "title": article_title,
        "content": article_text,  # plain text as fallback
        "client_seo_requirements": extract_client_seo_requirements(client_instructions),
        "focus_keyphrase": seo_fields.get("focus_keyphrase", ""),
        "seo_title": seo_fields.get("seo_title", ""),
        "slug": seo_fields.get("slug", ""),
        "meta_description": seo_fields.get("meta_description", ""),
        "excerpt": seo_fields.get("excerpt", ""),
        "synonyms": seo_fields.get("synonyms", ""),
    }
