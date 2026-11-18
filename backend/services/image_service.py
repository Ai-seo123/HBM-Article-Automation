"""
Image service — handles image acquisition, provider orchestration, and processing per requirements.

Priority Order:
  PRIORITY 1 — IMAGE ALREADY EXISTS
    - DOCX embedded images
    - Article attachments
    - Explicit image URL in Basecamp instructions
    - Existing image supplied by client
    If a valid image already exists:
    -> use that image
    -> do NOT search another provider
    -> do NOT generate a new image
    -> preserve source/credit information.

  PRIORITY 2 — CLIENT-SPECIFIED PROVIDER
    If Basecamp instructions explicitly require a provider (Dreamstime, Deposit Photos, Pexels, Unsplash, Envato, Magnific, Calamari):
    -> that provider MUST be used.
    -> Do not silently switch providers.
    -> Do not use AI generation as a replacement.
    -> If provider is unavailable, report image acquisition as unavailable (IMAGE SOURCE UNAVAILABLE).

  PRIORITY 3 — USER-SELECTED PROVIDER
    If no image exists and client instructions do not specify a provider:
    -> use the image provider selected in dashboard.
    Search queries:
      - Primary: article title
      - Secondary: focus keyphrase + main topic
      - Fallback: 3-5 important topic terms
    Rank results (semantic relevance, orientation, clean asset, duplicates).

  PRIORITY 4 — AI GENERATION
    If:
      - no image exists
      - client did not specify a stock provider
      - workflow allows AI generation
    then use Magnific Image Generation API.

Image requirements:
  - Width: 1000px, aspect ratio 1000×667 px banner
  - Clean asset: No watermarks, no provider logos, no screenshots
  - Metadata: alt text, title attribute, caption, source URL, provider name
  - Attribution stored separately from image pixels
"""

import io
import logging
import os
import re
from typing import Optional

import httpx
from PIL import Image

from core.config import settings
import services.envato as envato_service
import services.image_providers as image_providers

log = logging.getLogger(__name__)

TARGET_WIDTH = 1000
TARGET_HEIGHT = 667


# ---------------------------------------------------------------------------
# Image Resizing (1000×667 px without distortion)
# ---------------------------------------------------------------------------

def resize_image(image_bytes: bytes, content_type: str) -> bytes:
    """
    Resize image to exactly 1000×667 px and optimize for web delivery (target <= 100 KB).
    Scales to cover dimensions without distortion, center-crops to 1000×667,
    and applies high-quality encoding to preserve visual quality, details, and colors.
    Avoids recompression if image is already 1000x667 and <= 100 KB.
    Does NOT degrade quality below 70 or use aggressive chroma subsampling.
    """
    if not image_bytes:
        return image_bytes

    try:
        img = Image.open(io.BytesIO(image_bytes))
        original_w, original_h = img.size
        target_max_bytes = 100 * 1024  # 102,400 bytes

        # Check if already compliant to avoid repeated recompression
        is_jpeg = content_type in ("image/jpeg", "image/jpg") or getattr(img, "format", "") == "JPEG"
        if original_w == TARGET_WIDTH and original_h == TARGET_HEIGHT and len(image_bytes) <= target_max_bytes and is_jpeg:
            log.info(
                "Stock image is already exactly 1000x667 px and <= 100 KB (%.1f KB) — preserving original bytes without recompression",
                len(image_bytes) / 1024,
            )
            return image_bytes

        # Convert to RGB (handles RGBA, P modes, etc.)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Calculate scale to cover the target dimensions without distortion
        scale_w = TARGET_WIDTH / original_w
        scale_h = TARGET_HEIGHT / original_h
        scale = max(scale_w, scale_h)

        new_w = int(round(original_w * scale))
        new_h = int(round(original_h * scale))

        resample_filter = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)
        img = img.resize((new_w, new_h), resample_filter)

        # Center crop to exactly TARGET_WIDTH x TARGET_HEIGHT without stretching
        left = max(0, (new_w - TARGET_WIDTH) // 2)
        top = max(0, (new_h - TARGET_HEIGHT) // 2)
        img = img.crop((left, top, left + TARGET_WIDTH, top + TARGET_HEIGHT))

        # Enforce exact dimensions
        if img.size != (TARGET_WIDTH, TARGET_HEIGHT):
            img = img.resize((TARGET_WIDTH, TARGET_HEIGHT), resample_filter)

        # High-quality resize & encoding strategy:
        # Target <= 100 KB while preserving visual details, sharpness, and true colors.
        # Strict quality floor: never drop below quality 70; never use aggressive chroma subsampling.
        output = io.BytesIO()
        best_bytes = None
        best_q = 85

        for q in (85, 82, 80, 78, 75, 72, 70):
            output = io.BytesIO()
            img.save(output, format="JPEG", quality=q, optimize=True, progressive=True)
            candidate = output.getvalue()
            best_bytes = candidate
            best_q = q
            if len(candidate) <= target_max_bytes:
                break

        final_size_kb = len(best_bytes) / 1024
        if len(best_bytes) > target_max_bytes:
            log.info(
                "Image visual quality preserved at quality %d (%.1f KB). Prioritizing visual quality over aggressive compression below quality floor.",
                best_q, final_size_kb,
            )
        else:
            log.info(
                "Image resized and optimized to 1000x667 at quality %d (%.1f KB, target <= 100 KB)",
                best_q, final_size_kb,
            )

        return best_bytes

    except Exception as exc:
        log.warning("Image resize standard pipeline failed: %s — attempting robust fallback", exc)
        try:
            target_max_bytes = 100 * 1024
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            resample_filter = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)
            img = img.resize((TARGET_WIDTH, TARGET_HEIGHT), resample_filter)
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=80, optimize=True, progressive=True)
            candidate = out.getvalue()
            if len(candidate) <= target_max_bytes:
                return candidate
            for q in (75, 70):
                out = io.BytesIO()
                img.save(out, format="JPEG", quality=q, optimize=True, progressive=True)
                if len(out.getvalue()) <= target_max_bytes:
                    return out.getvalue()
            return out.getvalue()
        except Exception as fallback_exc:
            log.error("Image resize fallback failed: %s", fallback_exc)
            return image_bytes


def optimize_docx_image(image_bytes: bytes, max_width: int = 700) -> bytes:
    """
    Optimize an image present in the source DOCX document:
    - Keep DOCX-embedded images unchanged in content except for the required maximum width of 700 px.
    - Preserves original aspect ratio without distortion or unwanted cropping.
    - Do not repeatedly recompress an already compressed image.
    - Target <= 100 KB (102,400 bytes) without visible quality degradation.
    """
    if not image_bytes:
        return image_bytes

    try:
        img = Image.open(io.BytesIO(image_bytes))
        orig_w, orig_h = img.size
        target_max_bytes = 100 * 1024  # 100 KB

        # Check if already compliant: width <= 700px and size <= 100 KB
        # Do not recompress already compressed compliant images!
        if orig_w <= max_width and len(image_bytes) <= target_max_bytes:
            log.info(
                "DOCX image is already compliant (%dx%d, %.1f KB <= 100 KB) — preserving original bytes without recompression",
                orig_w, orig_h, len(image_bytes) / 1024,
            )
            return image_bytes

        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        resample_filter = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)

        # Scale down proportionally ONLY if width exceeds max_width (700px), strictly preserving aspect ratio
        if orig_w > max_width:
            scale = max_width / orig_w
            new_w = max_width
            new_h = max(1, int(round(orig_h * scale)))
            img = img.resize((new_w, new_h), resample_filter)
            log.info(
                "Scaled DOCX image proportionally from %dx%d to %dx%d (max %dpx, aspect preserved)",
                orig_w, orig_h, new_w, new_h, max_width,
            )

        # Progressive quality search with floor at 70 (never aggressively degrade or use subsampling=2)
        best_bytes = None
        best_q = 85
        for q in (85, 82, 80, 78, 75, 72, 70):
            output = io.BytesIO()
            img.save(output, format="JPEG", quality=q, optimize=True, progressive=True)
            candidate = output.getvalue()
            best_bytes = candidate
            best_q = q
            if len(candidate) <= target_max_bytes:
                break

        final_size_kb = len(best_bytes) / 1024
        if len(best_bytes) > target_max_bytes:
            log.info(
                "DOCX image visual quality preserved at quality %d (%.1f KB). Prioritizing visual quality over aggressive compression below quality floor.",
                best_q, final_size_kb,
            )

        return best_bytes or image_bytes
    except Exception as exc:
        log.warning("DOCX image optimization failed: %s — using original bytes", exc)
        return image_bytes


def optimize_inline_image(image_bytes: bytes, min_width: int = 700, max_width: int = 700) -> bytes:
    """
    Optimize inline DOCX image:
    Ensures inline images do not exceed max_width (700 px) wide proportionally without distortion,
    and compressed to <= 100 KB.
    """
    return optimize_docx_image(image_bytes, max_width=max_width)


# ---------------------------------------------------------------------------
# Provider Listing & Search Delegation
# ---------------------------------------------------------------------------

async def list_providers(force_refresh: bool = False) -> list[dict]:
    """
    Return all 7 supported image provider platforms and their real-time verified status.
    Statuses: LIVE, CONFIGURED, NOT_CONFIGURED, UNAVAILABLE, ERROR.
    """
    raw_providers = await image_providers.list_all_providers(force_refresh=force_refresh)
    # Include 'available' boolean for frontend backward-compatibility
    for p in raw_providers:
        p["available"] = (p["status"] == "LIVE")
    return raw_providers


async def search_provider(provider: str, query: str, limit: int = 12) -> dict:
    """
    Search real images from a configured provider.
    Never fabricates fake images.
    """
    return await image_providers.search_provider_images(provider_id=provider, query=query, limit=limit)


# ---------------------------------------------------------------------------
# Direct Image Fetchers (Pexels / Envato / Generic URL)
# ---------------------------------------------------------------------------

async def _fetch_clean_image_from_url(url: str, provider: str = "generic") -> Optional[dict]:
    """
    Download a clean image from a direct URL.
    Verifies that the URL is a direct media asset (not an item HTML page),
    is not a watermarked preview, and contains valid image bytes via PIL inspection.
    """
    if not url:
        return None

    # Reject item page URLs (Requirement 5)
    u_low = url.lower()
    if any(page_marker in u_low for page_marker in ["/item/", ".html", "photodune.net/item"]):
        log.warning("Rejecting item page URL used as image download source: %r", url)
        return None

    if image_providers.is_watermarked_asset(url):
        log.warning("Rejecting watermarked preview image URL: %r", url)
        return None

    log.info("Downloading clean image from URL: %r (provider=%s)", url, provider)
    headers = {"User-Agent": "HBM Article Automation"}
    if "envato" in url.lower() and getattr(settings, "ENVATO_API_TOKEN", ""):
        headers["Authorization"] = f"Bearer {settings.ENVATO_API_TOKEN}"
    elif "pexels" in url.lower() and getattr(settings, "PEXELS_API_KEY", ""):
        headers["Authorization"] = settings.PEXELS_API_KEY

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].lower()
            image_bytes = resp.content

            # Validate MIME type and byte presence (Requirement 6)
            if not content_type.startswith("image/") or not image_bytes:
                log.warning("URL did not return valid image content type (%s, %d bytes): %r", content_type, len(image_bytes), url)
                return None

            # Reject HTML error pages disguised as image responses (Requirement 6)
            if image_bytes.startswith(b"<!DOCTYPE") or image_bytes.startswith(b"<html") or b"<body" in image_bytes[:500]:
                log.warning("URL returned an HTML document instead of an image: %r", url)
                return None

            # Validate actual image bytes integrity using PIL (Requirement 6)
            try:
                probe_img = Image.open(io.BytesIO(image_bytes))
                probe_img.verify()
            except Exception as probe_err:
                log.warning("Downloaded asset failed image byte verification: %s (%r)", probe_err, url)
                return None

            log.info("Downloaded verified clean image: %d bytes, MIME %s from %s", len(image_bytes), content_type, url[:80])
            return {
                "image_bytes": image_bytes,
                "content_type": content_type,
                "source_url": url,
            }
    except Exception as exc:
        log.warning("Image download from URL failed: %s (%r)", exc, url)
        return None


async def _fetch_pexels_photo(url: str) -> Optional[dict]:
    """Download large clean photo from Pexels via photo ID or page URL."""
    if not url:
        return None

    # Check if URL has Pexels photo ID
    pid_match = re.search(r"/photo/[^/]+-(\d+)/?$", url)
    pexels_key = getattr(settings, "PEXELS_API_KEY", "")
    target_image_url = url
    alt_text = ""
    photographer = ""

    if pid_match and pexels_key:
        photo_id = pid_match.group(1)
        api_url = f"https://api.pexels.com/v1/photos/{photo_id}"
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(api_url, headers={"Authorization": pexels_key})
                if resp.status_code == 200:
                    data = resp.json()
                    src = data.get("src", {})
                    target_image_url = (
                        src.get("large2x")
                        or src.get("large")
                        or src.get("original")
                        or url
                    )
                    alt_text = data.get("alt", "") or ""
                    photographer = data.get("photographer", "") or ""
        except Exception as exc:
            log.warning("Pexels API lookup failed: %s — falling back to URL download", exc)

    dl = await _fetch_clean_image_from_url(target_image_url, provider="pexels")
    if not dl:
        return None

    caption = f"Photo by {photographer} on Pexels" if photographer else "Photo via Pexels"
    return {
        "image_bytes": dl["image_bytes"],
        "content_type": dl["content_type"],
        "source_url": url,
        "alt_text": alt_text,
        "caption": caption,
        "source": "pexels",
        "provider": "Pexels",
    }


# ---------------------------------------------------------------------------
# Main Image Acquisition Pipeline
# ---------------------------------------------------------------------------

def is_explicit_replacement_directive(
    instructions_text: Optional[str] = None,
    image_directive: Optional[dict] = None,
) -> bool:
    """
    Dynamically detect whether client instructions explicitly command replacing
    the existing image in the DOCX.

    Matches instructions such as:
      - "IMAGE: REPLACE image from a platform of your choice. Be sure image was not sourced before. Hyperlink image to the source ONCE in the caption."
      - "REPLACE image..." / "REPLACE images..."
      - "platform of your choice" / "provider of your choice"
      - or image_directive structured fields: replace_images=True, image_action="replace", image_requirement="choice".
    """
    if image_directive:
        if image_directive.get("replace_images"):
            return True
        if image_directive.get("image_action") == "replace":
            return True
        if image_directive.get("image_requirement") == "choice":
            return True

    text = (instructions_text or "").strip()
    if not text:
        return False

    patterns = [
        r"\breplace\s+images?\b",
        r"\bimage\s*:\s*replace\b",
        r"\b(?:replace\s+images?\s+(?:from\s+a\s+)?)?platform\s+of\s+(?:your\s+)?choice\b",
        r"\bprovider\s+of\s+(?:your\s+)?choice\b",
    ]
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    return False


async def acquire_featured_image(
    embedded_images: list[dict],
    image_directive: dict,
    article_title: str,
    article_content: str,
    client_instructions_plain: str,
    selected_image_data: Optional[dict] = None,
    image_provider_override: Optional[str] = None,
    focus_keyphrase: Optional[str] = None,
    allow_ai_generation_workflow: bool = False,
) -> dict:
    """
    Acquire the featured image following the exact priority order from requirements:

    PRIORITY 1 — IMAGE ALREADY EXISTS
      Check:
        - DOCX embedded images (preserved ONLY when instructions do not request replacement)
        - Article attachments
        - Explicit image URL in Basecamp instructions
        - Existing image supplied by client
      If a valid image already exists and replacement is not requested:
      -> use that image
      -> do NOT search another provider
      -> do NOT generate a new image
      -> preserve source/credit information.

    PRIORITY 2 — CLIENT-SPECIFIED PROVIDER
      If Basecamp instructions explicitly require a provider:
      -> that provider MUST be used.
      -> Do not silently switch providers.
      -> Do not use AI generation as a replacement.
      -> If provider is unavailable, report image acquisition as unavailable.

    PRIORITY 3 — USER-SELECTED PROVIDER
      If no image exists and client instructions do not specify a provider:
      -> use the image provider selected in dashboard.
      Search using article title, focus keyphrase, topic terms. Rank results.

    PRIORITY 4 — AI GENERATION
      If no image exists, no client stock provider specified, and AI allowed:
      -> use Magnific Image Generation API.

    Returns:
        dict with status ("PASSED" | "FAILED"), image_bytes, content_type,
        filename, source_url, source, provider, alt_text, image_title, caption, error.
    """
    should_replace = is_explicit_replacement_directive(client_instructions_plain, image_directive)
    enforce_duplicate_check = image_directive.get("prevent_duplicates", False) or should_replace
    allow_ai = allow_ai_generation_workflow or image_directive.get("allow_ai_generation", False)

    # ── EXPLICIT REPLACEMENT DIRECTIVE ──────────────────────────────────────
    # When instructions contain explicit replacement wording (e.g. "IMAGE: REPLACE image
    # from a platform of your choice. Be sure image was not sourced before. Hyperlink image
    # to the source ONCE in the caption."):
    #   - Treat REPLACE image as an explicit command to replace existing image in DOCX.
    #   - Do NOT retain, reuse, or select DOCX image.
    #   - Search Envato and use a new, relevant, previously unused Envato image.
    #   - Do NOT use Pexels, Depositphotos, Dreamstime, Unsplash, AI, or any other source.
    #   - If no valid Envato image is available, report image sourcing failure.
    #     Do NOT fall back to original DOCX image or another provider.
    #   - Add Envato source hyperlink exactly once in image caption.
    if should_replace:
        log.info(
            "Explicit replacement directive detected ('%s') — bypassing DOCX image and sourcing exclusively from Envato",
            (client_instructions_plain or "")[:80],
        )
        status_info = await image_providers.check_provider_status("envato")
        if status_info["status"] != "LIVE":
            err_msg = f"IMAGE SOURCING FAILURE: Envato provider is {status_info['status']} ({status_info['details']}). Cannot source replacement image."
            log.error(err_msg)
            return {
                "status": "FAILED",
                "image_bytes": None,
                "content_type": None,
                "filename": None,
                "source_url": None,
                "source": "envato",
                "provider": "Envato",
                "alt_text": None,
                "image_title": None,
                "caption": None,
                "error": err_msg,
            }

        queries = image_providers.generate_search_queries(
            title=article_title,
            focus_keyphrase=focus_keyphrase,
            article_content=article_content,
        )

        query_candidates = []
        if queries.get("primary"):
            query_candidates.append(queries["primary"])
        if queries.get("secondary"):
            query_candidates.append(queries["secondary"])
        if queries.get("fallback"):
            query_candidates.append(queries["fallback"])
        for fb in queries.get("fallbacks", []):
            if fb not in query_candidates:
                query_candidates.append(fb)
        for ef in envato_service.build_fallback_queries(article_title, article_content, client_instructions_plain):
            if ef not in query_candidates:
                query_candidates.append(ef)

        query_attempts = []
        for q_text in query_candidates:
            if not q_text or not q_text.strip():
                continue
            search_res = await image_providers.search_provider_images("envato", q_text)
            results = search_res.get("results", [])
            query_attempts.append({"query": q_text, "matches": len(results)})
            if not results:
                continue

            ranked = image_providers.rank_candidates(
                candidates=results,
                query=q_text,
                focus_keyphrase=focus_keyphrase,
                enforce_duplicate_check=True,  # strictly enforce previously unused
            )

            for candidate in ranked:
                img_url = candidate.get("image_url")
                if not img_url:
                    continue

                dl = await _fetch_clean_image_from_url(img_url, provider="envato")
                if dl:
                    resized = resize_image(dl["image_bytes"], dl["content_type"])
                    ext = dl["content_type"].split("/")[-1] if "/" in dl["content_type"] else "jpg"
                    cid = candidate.get("id") or "asset"
                    source_url = candidate.get("source_url") or img_url
                    # Add the Envato source hyperlink exactly once in the image caption: envato.com linking to asset URL
                    caption = f'<a href="{source_url}" target="_blank" rel="noopener">envato.com</a>'
                    alt_text = focus_keyphrase.strip() if focus_keyphrase and focus_keyphrase.strip() else (candidate.get("title") or article_title[:125])

                    return {
                        "status": "PASSED",
                        "image_bytes": resized,
                        "content_type": dl["content_type"],
                        "filename": f"envato-{cid}.{ext}",
                        "source_url": source_url,
                        "source": "envato",
                        "provider": "Envato",
                        "alt_text": alt_text,
                        "image_title": article_title[:60],
                        "caption": caption,
                        "caption_requirement": "Hyperlink image to the source ONCE in the caption",
                        "error": None,
                    }

        total_raw = sum(qa.get("matches", 0) for qa in query_attempts)
        err_details = f"Queries attempted: {', '.join(repr(qa['query']) for qa in query_attempts[:5])}"
        if total_raw == 0:
            err_msg = f"IMAGE SOURCING FAILURE: Envato returned 0 results for explicit replacement directive. {err_details}."
        else:
            err_msg = f"IMAGE SOURCING FAILURE: Envato returned {total_raw} items for explicit replacement directive, but none passed unwatermarked and unused image validation. {err_details}."

        log.error(err_msg)
        return {
            "status": "FAILED",
            "image_bytes": None,
            "content_type": None,
            "filename": None,
            "source_url": None,
            "source": "envato",
            "provider": "Envato",
            "alt_text": None,
            "image_title": None,
            "caption": None,
            "error": err_msg,
        }

    # ── Priority 0: Direct User Selection or Upload from Dashboard UI ───────
    if selected_image_data and selected_image_data.get("raw_image_base64"):
        raw_b64 = selected_image_data["raw_image_base64"]
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]
        try:
            import base64
            img_bytes = base64.b64decode(raw_b64)
            c_type = selected_image_data.get("content_type", "image/jpeg")
            resized = resize_image(img_bytes, c_type)
            src_label = selected_image_data.get("source") or "uploaded_image"
            provider_label = selected_image_data.get("provider") or (
                "DOCX Embedded Image" if src_label == "docx" else "Uploaded Image"
            )
            ext = c_type.split("/")[-1] if "/" in c_type else "jpg"
            fn = selected_image_data.get("filename") or f"featured-image.{ext}"
            return {
                "status": "PASSED",
                "image_bytes": resized,
                "content_type": c_type,
                "filename": fn,
                "source_url": selected_image_data.get("source_url") or "",
                "source": src_label,
                "provider": provider_label,
                "alt_text": selected_image_data.get("alt_text") or focus_keyphrase or article_title[:125],
                "image_title": article_title[:60],
                "caption": selected_image_data.get("caption") or f"Photo via {provider_label}",
                "error": None,
            }
        except Exception as exc:
            log.warning("Processing raw_image_base64 failed: %s — continuing priority waterfall", exc)

    if selected_image_data and selected_image_data.get("image_url"):
        img_url = selected_image_data["image_url"]
        log.info("Processing user-selected image from dashboard: %r", img_url)

        if image_providers.is_watermarked_asset(img_url, selected_image_data):
            return {
                "status": "FAILED",
                "image_bytes": None,
                "content_type": None,
                "filename": None,
                "source_url": None,
                "source": "selected_image",
                "provider": "Selected Image",
                "alt_text": None,
                "image_title": None,
                "caption": None,
                "error": "The selected image is a watermarked preview. Only legitimate clean assets are allowed.",
            }

        dl = await _fetch_clean_image_from_url(img_url, provider=selected_image_data.get("source", "selected"))
        if dl:
            resized = resize_image(dl["image_bytes"], dl["content_type"])
            ext = dl["content_type"].split("/")[-1] if "/" in dl["content_type"] else "jpg"
            src_label = selected_image_data.get("source") or "selected_image"
            provider_label = selected_image_data.get("provider") or src_label.title()
            return {
                "status": "PASSED",
                "image_bytes": resized,
                "content_type": dl["content_type"],
                "filename": f"featured-image.{ext}",
                "source_url": selected_image_data.get("source_url") or img_url,
                "source": src_label,
                "provider": provider_label,
                "alt_text": selected_image_data.get("title") or article_title[:125],
                "image_title": article_title[:60],
                "caption": selected_image_data.get("caption") or f"Photo via {provider_label}",
                "error": None,
            }
        log.warning("User-selected image download failed — continuing priority waterfall")

    has_required_provider = bool(image_directive.get("required_provider"))
    directive_url = image_directive.get("url")
    directive_source = image_directive.get("source")

    # ── PRIORITY 1: IMAGE ALREADY EXISTS ────────────────────────────────────
    # 1. DOCX embedded images
    # If an image already exists inside the source DOCX/article, preserve and upload that image
    # ONLY when the instructions do NOT request replacement.
    if embedded_images and not should_replace:
        first_img = embedded_images[0]
        raw_bytes = first_img.get("content", b"")
        content_type = first_img.get("content_type", "image/jpeg")
        filename = first_img.get("filename", "article-image.jpg")
        alt_text = first_img.get("alt_text", "") or article_title[:125]

        if raw_bytes and len(raw_bytes) > 500:
            log.info("Priority 1 Match: Preserving and uploading embedded DOCX image '%s'", filename)
            optimized = optimize_docx_image(raw_bytes, max_width=700)
            ext = content_type.split("/")[-1] if "/" in content_type else "jpg"
            return {
                "status": "PASSED",
                "image_bytes": optimized,
                "content_type": content_type,
                "filename": f"article-image.{ext}",
                "source_url": "",
                "source": "docx",
                "provider": "DOCX Embedded Image",
                "alt_text": alt_text,
                "image_title": article_title[:60],
                "caption": "",
                "caption_requirement": image_directive.get("caption_requirement"),
                "error": None,
            }

    # 2. Explicit image URL in Basecamp instructions
    if directive_url:
        log.info("Priority 1 Match: Explicit image URL provided in Basecamp instructions: %r", directive_url)

        if image_providers.is_watermarked_asset(directive_url):
            log.warning("Explicit image URL in instructions contains watermark marker: %r", directive_url)
            return {
                "status": "FAILED",
                "image_bytes": None,
                "content_type": None,
                "filename": None,
                "source_url": directive_url,
                "source": directive_source or "instruction_url",
                "provider": (directive_source or "Instructions").title(),
                "alt_text": None,
                "image_title": None,
                "caption": None,
                "error": "The image specified in Basecamp instructions is a watermarked preview. Watermarked previews are strictly rejected.",
            }

        # Handle Pexels URL
        if directive_source == "pexels" or "pexels.com" in directive_url:
            pexels_res = await _fetch_pexels_photo(directive_url)
            if pexels_res:
                resized = resize_image(pexels_res["image_bytes"], pexels_res["content_type"])
                ext = pexels_res["content_type"].split("/")[-1] if "/" in pexels_res["content_type"] else "jpg"
                caption = image_directive.get("caption") or pexels_res.get("caption") or "Photo via Pexels"
                return {
                    "status": "PASSED",
                    "image_bytes": resized,
                    "content_type": pexels_res["content_type"],
                    "filename": f"pexels-image.{ext}",
                    "source_url": pexels_res["source_url"],
                    "source": "pexels",
                    "provider": "Pexels",
                    "alt_text": pexels_res.get("alt_text") or article_title[:125],
                    "image_title": article_title[:60],
                    "caption": caption,
                    "error": None,
                }

        # Handle general URL
        dl = await _fetch_clean_image_from_url(directive_url, provider=directive_source or "generic")
        if dl:
            resized = resize_image(dl["image_bytes"], dl["content_type"])
            ext = dl["content_type"].split("/")[-1] if "/" in dl["content_type"] else "jpg"
            caption = image_directive.get("caption") or ""
            return {
                "status": "PASSED",
                "image_bytes": resized,
                "content_type": dl["content_type"],
                "filename": f"instruction-image.{ext}",
                "source_url": directive_url,
                "source": directive_source or "instruction_url",
                "provider": (directive_source or "Instructions").title(),
                "alt_text": article_title[:125],
                "image_title": article_title[:60],
                "caption": caption,
                "error": None,
            }

    # ── PRIORITY 2: CLIENT-SPECIFIED PROVIDER ────────────────────────────────
    required_provider = image_directive.get("required_provider")
    if required_provider:
        req_id = required_provider.lower().strip()
        log.info("Priority 2 Requirement: Client instructions explicitly specified provider '%s'", req_id)

        # Check real-time provider status
        status_info = await image_providers.check_provider_status(req_id)
        if status_info["status"] != "LIVE":
            log.warning("Client-required provider '%s' is %s: %s", req_id, status_info["status"], status_info["details"])
            return {
                "status": "FAILED",
                "image_bytes": None,
                "content_type": None,
                "filename": None,
                "source_url": None,
                "source": req_id,
                "provider": status_info["name"],
                "alt_text": None,
                "image_title": None,
                "caption": None,
                "error": f"IMAGE SOURCE UNAVAILABLE: Client required provider '{status_info['name']}' is {status_info['status']} ({status_info['details']}).",
            }

        # Search the required provider
        queries = image_providers.generate_search_queries(
            title=article_title,
            focus_keyphrase=focus_keyphrase,
            article_content=article_content,
        )

        query_candidates = []
        if queries.get("primary"):
            query_candidates.append(queries["primary"])
        if queries.get("secondary"):
            query_candidates.append(queries["secondary"])
        if queries.get("fallback"):
            query_candidates.append(queries["fallback"])
        for fb in queries.get("fallbacks", []):
            if fb not in query_candidates:
                query_candidates.append(fb)
        if req_id == "envato":
            for ef in envato_service.build_fallback_queries(article_title, article_content, client_instructions_plain):
                if ef not in query_candidates:
                    query_candidates.append(ef)

        query_attempts = []
        for q_text in query_candidates:
            if not q_text or not q_text.strip():
                continue
            search_res = await image_providers.search_provider_images(req_id, q_text)
            results = search_res.get("results", [])
            query_attempts.append({"query": q_text, "matches": len(results)})
            if not results:
                continue

            ranked = image_providers.rank_candidates(
                candidates=results,
                query=q_text,
                focus_keyphrase=focus_keyphrase,
                enforce_duplicate_check=enforce_duplicate_check,
            )

            for candidate in ranked:
                img_url = candidate.get("image_url")
                if not img_url:
                    continue

                dl = await _fetch_clean_image_from_url(img_url, provider=req_id)
                if dl:
                    resized = resize_image(dl["image_bytes"], dl["content_type"])
                    ext = dl["content_type"].split("/")[-1] if "/" in dl["content_type"] else "jpg"
                    cid = candidate.get("id") or "asset"
                    source_url = candidate.get("source_url") or img_url
                    if req_id == "envato" or "envato" in status_info.get("name", "").lower():
                        caption = f'<a href="{source_url}" target="_blank" rel="noopener">envato.com</a>'
                    else:
                        caption = candidate.get("caption") or f"Photo via {status_info['name']}"
                        if candidate.get("photographer"):
                            caption = f"Photo by {candidate['photographer']} on {status_info['name']}"

                    if image_directive.get("caption") and not re.search(
                        r"\bhyperlink\s+(?:once\s+)?in\s+(?:the\s+)?caption\b",
                        image_directive.get("caption", ""),
                        re.IGNORECASE,
                    ):
                        caption = image_directive["caption"]

                    return {
                        "status": "PASSED",
                        "image_bytes": resized,
                        "content_type": dl["content_type"],
                        "filename": f"{req_id}-{cid}.{ext}",
                        "source_url": candidate.get("source_url") or img_url,
                        "source": req_id,
                        "provider": status_info["name"],
                        "alt_text": candidate.get("title") or article_title[:125],
                        "image_title": article_title[:60],
                        "caption": caption,
                        "caption_requirement": image_directive.get("caption_requirement") or image_directive.get("caption"),
                        "error": None,
                    }

        total_raw = sum(qa.get("matches", 0) for qa in query_attempts)
        err_details = f"Queries attempted: {', '.join(repr(qa['query']) for qa in query_attempts[:5])}"
        if total_raw == 0:
            spec_err = f"IMAGE SOURCE UNAVAILABLE: Client required provider '{status_info['name']}' returned 0 results. {err_details}."
        else:
            spec_err = f"IMAGE SOURCE UNAVAILABLE: Client required provider '{status_info['name']}' returned {total_raw} items, but none passed unwatermarked image validation. {err_details}."

        return {
            "status": "FAILED",
            "image_bytes": None,
            "content_type": None,
            "filename": None,
            "source_url": None,
            "source": req_id,
            "provider": status_info["name"],
            "alt_text": None,
            "image_title": None,
            "caption": None,
            "error": spec_err,
        }

    # ── PRIORITY 3: USER-SELECTED PROVIDER ──────────────────────────────────
    active_provider = (image_provider_override or "envato").lower().strip()
    log.info("Priority 3: Searching user-selected provider '%s'", active_provider)

    status_info = await image_providers.check_provider_status(active_provider)

    if status_info["status"] == "LIVE":
        queries = image_providers.generate_search_queries(
            title=article_title,
            focus_keyphrase=focus_keyphrase,
            article_content=article_content,
        )

        query_candidates = []
        if queries.get("primary"):
            query_candidates.append(queries["primary"])
        if queries.get("secondary"):
            query_candidates.append(queries["secondary"])
        if queries.get("fallback"):
            query_candidates.append(queries["fallback"])
        for fb in queries.get("fallbacks", []):
            if fb not in query_candidates:
                query_candidates.append(fb)
        if active_provider == "envato":
            for ef in envato_service.build_fallback_queries(article_title, article_content, client_instructions_plain):
                if ef not in query_candidates:
                    query_candidates.append(ef)

        query_attempts = []
        for q_text in query_candidates:
            if not q_text or not q_text.strip():
                continue
            search_res = await image_providers.search_provider_images(active_provider, q_text)
            results = search_res.get("results", [])
            query_attempts.append({"query": q_text, "matches": len(results)})
            if not results:
                continue

            ranked = image_providers.rank_candidates(
                candidates=results,
                query=q_text,
                focus_keyphrase=focus_keyphrase,
                enforce_duplicate_check=enforce_duplicate_check,
            )

            for candidate in ranked:
                img_url = candidate.get("image_url")
                if not img_url:
                    continue

                dl = await _fetch_clean_image_from_url(img_url, provider=active_provider)
                if dl:
                    resized = resize_image(dl["image_bytes"], dl["content_type"])
                    ext = dl["content_type"].split("/")[-1] if "/" in dl["content_type"] else "jpg"
                    cid = candidate.get("id") or "asset"
                    source_url = candidate.get("source_url") or img_url
                    if active_provider == "envato" or "envato" in status_info.get("name", "").lower():
                        caption = f'<a href="{source_url}" target="_blank" rel="noopener">envato.com</a>'
                    else:
                        caption = candidate.get("caption") or f"Photo via {status_info['name']}"
                        if candidate.get("photographer"):
                            caption = f"Photo by {candidate['photographer']} on {status_info['name']}"

                    if image_directive.get("caption") and not re.search(
                        r"\bhyperlink\s+(?:once\s+)?in\s+(?:the\s+)?caption\b",
                        image_directive.get("caption", ""),
                        re.IGNORECASE,
                    ):
                        caption = image_directive["caption"]

                    return {
                        "status": "PASSED",
                        "image_bytes": resized,
                        "content_type": dl["content_type"],
                        "filename": f"{active_provider}-{cid}.{ext}",
                        "source_url": candidate.get("source_url") or img_url,
                        "source": active_provider,
                        "provider": status_info["name"],
                        "alt_text": candidate.get("title") or article_title[:125],
                        "image_title": article_title[:60],
                        "caption": caption,
                        "caption_requirement": image_directive.get("caption_requirement") or image_directive.get("caption"),
                        "error": None,
                    }

        # If live provider search across all queries yielded no clean asset
        if not allow_ai:
            total_raw = sum(qa.get("matches", 0) for qa in query_attempts)
            err_details = f"Queries attempted: {', '.join(repr(qa['query']) for qa in query_attempts[:6])}"
            if total_raw == 0:
                spec_err = f"IMAGE SOURCE UNAVAILABLE: Provider '{status_info['name']}' returned 0 results. {err_details}."
            else:
                spec_err = f"IMAGE SOURCE UNAVAILABLE: Provider '{status_info['name']}' returned {total_raw} raw items, but none passed unwatermarked image validation. {err_details}."

            return {
                "status": "FAILED",
                "image_bytes": None,
                "content_type": None,
                "filename": None,
                "source_url": None,
                "source": active_provider,
                "provider": status_info["name"],
                "alt_text": None,
                "image_title": None,
                "caption": None,
                "error": spec_err,
            }

    # ── PRIORITY 4: AI GENERATION ───────────────────────────────────────────
    if allow_ai:
        log.info("Priority 4: Attempting Magnific AI image generation")
        ai_res = await image_providers.generate_ai_image(
            article_title=article_title,
            article_context=article_content[:1000],
        )
        if ai_res.get("status") == "PASSED" and ai_res.get("image_bytes"):
            resized = resize_image(ai_res["image_bytes"], ai_res.get("content_type", "image/jpeg"))
            return {
                "status": "PASSED",
                "image_bytes": resized,
                "content_type": ai_res.get("content_type", "image/jpeg"),
                "filename": "magnific-generated.jpg",
                "source_url": ai_res.get("source_url", ""),
                "source": "magnific",
                "provider": "Magnific",
                "alt_text": article_title[:125],
                "image_title": article_title[:60],
                "caption": "AI generated via Magnific",
                "error": None,
            }
        else:
            return {
                "status": "FAILED",
                "image_bytes": None,
                "content_type": None,
                "filename": None,
                "source_url": None,
                "source": "magnific",
                "provider": "Magnific",
                "alt_text": None,
                "image_title": None,
                "caption": None,
                "error": ai_res.get("error") or "IMAGE SOURCE UNAVAILABLE: Magnific AI generation failed or is unavailable.",
            }

    # If provider is not live and AI is not enabled
    return {
        "status": "FAILED",
        "image_bytes": None,
        "content_type": None,
        "filename": None,
        "source_url": None,
        "source": active_provider,
        "provider": status_info["name"],
        "alt_text": None,
        "image_title": None,
        "caption": None,
        "error": f"IMAGE SOURCE UNAVAILABLE: Selected provider '{status_info['name']}' is {status_info['status']} ({status_info['details']}).",
    }
