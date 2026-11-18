"""
Envato image service.

This service searches for and downloads a featured image from Envato Elements
based on the article context.
"""

import io
import logging
import re
from html import unescape
from typing import Iterable, Optional

import httpx
from PIL import Image

from core.config import settings

log = logging.getLogger(__name__)

def is_configured() -> bool:
    return bool(settings.ENVATO_API_TOKEN and settings.ENVATO_API_URL)


def build_query(title: str, article_content: str, client_instructions: str) -> str:
    """
    Build a concise search query directly from the article title.
    Focuses on the substantive core topic of the title.
    """
    clean_title = unescape(re.sub(r"<[^>]+>", " ", title or "")).strip()
    clean_title = re.sub(r"^\d+[\s\.\)\:\-]*", "", clean_title).strip()
    parts = [p.strip() for p in re.split(r"[:|–—]|\s+-\s+", clean_title) if p.strip()]
    if len(parts) > 1 and len(parts[0].split()) <= 2:
        clause = parts[1]
    elif parts:
        clause = parts[0]
    else:
        clause = clean_title
    clause = re.sub(r"^\d+[\s\.\)]*", "", clause).strip()
    return clause or clean_title[:80].strip()


def build_fallback_queries(
    title: str,
    article_content: str,
    client_instructions: str,
) -> list[str]:
    """
    Build concise, deterministic topic queries derived from the article title.
    Generates clean topic pairs, trigrams, and domain visual keywords, avoiding
    non-visual qualifiers and corporate acronyms that yield 0 stock photo results.
    """
    def clean(value: str) -> str:
        value = unescape(re.sub(r"<[^>]+>", " ", value or ""))
        return " ".join(value.split())

    title = clean(title)
    content = clean(article_content)

    clean_title = re.sub(r"^\d+[\s\.\)\:\-]*", "", title).strip()
    parts = [p.strip() for p in re.split(r"[:|?–—]|\s+-\s+", clean_title) if p.strip()]
    main_clause = clean_title
    if len(parts) > 1 and len(parts[0].split()) <= 2:
        main_clause = parts[1]
    elif parts:
        main_clause = parts[0]

    main_clause = re.sub(r"[?!.,'\"]+", "", main_clause).strip()

    # Filter out stop words, generic verbs, and geographic / corporate abbreviations
    stop_words = {
        "a", "about", "above", "after", "again", "all", "allowing", "also", "am", "an", "and",
        "any", "are", "as", "at", "audience", "be", "because", "been", "before", "being",
        "below", "between", "both", "businesses", "but", "by", "can", "carefully", "changing",
        "content", "could", "create", "did", "do", "does", "doing", "down", "during", "each",
        "few", "for", "from", "further", "had", "has", "have", "having", "he", "help", "how",
        "i", "if", "in", "into", "is", "it", "its", "itself", "just", "make", "me", "more",
        "most", "my", "no", "nor", "not", "now", "of", "off", "on", "once", "only", "online",
        "or", "other", "our", "ours", "out", "over", "own", "owners", "remain", "same", "she",
        "should", "small", "so", "some", "such", "than", "that", "the", "their", "theirs",
        "them", "themselves", "then", "there", "these", "they", "this", "those", "through",
        "time", "to", "too", "tools", "under", "until", "up", "useful", "using", "very",
        "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why",
        "will", "with", "would", "you", "your", "yours", "steps", "guide", "tips", "top",
        "best", "ways", "how", "review", "draft", "article", "checklist", "essential",
        "strategies", "strategy", "thriving", "mastering", "future", "scale", "without", "losing",
        "running", "here", "heres", "here's", "hand", "handing", "getting", "starting", "compared",
        # Non-visual qualifiers & niche acronyms that return 0 stock photos on Envato
        "canadian", "canada", "american", "us", "usa", "uk", "australian",
        "smb", "smbs", "sme", "smes", "b2b", "b2c", "llc", "inc", "ltd", "corp",
    }

    candidates: list[str] = []

    # 1. Clean substantive title clause if concise (<= 5 words)
    if main_clause and len(main_clause.split()) <= 5:
        candidates.append(main_clause)

    # 2. Extract deduplicated topic keywords in order across the entire title
    cleaned_full = re.sub(r"[^\w\s-]", " ", f"{main_clause} {title}".lower())
    title_words = re.findall(r"[a-z][a-z0-9-]*", cleaned_full)
    topic_words = []
    for w in title_words:
        w_clean = w.strip("'-")
        if len(w_clean) > 2 and w_clean not in stop_words and w_clean not in topic_words:
            topic_words.append(w_clean)

    # 3. All consecutive bigrams from topic keywords
    for i in range(len(topic_words) - 1):
        candidates.append(f"{topic_words[i]} {topic_words[i+1]}")

    # 4. All consecutive trigrams from topic keywords
    for i in range(len(topic_words) - 2):
        candidates.append(f"{topic_words[i]} {topic_words[i+1]} {topic_words[i+2]}")

    # 5. Skip-pairs (e.g. topic_words[0] + topic_words[2], topic_words[0] + topic_words[-1])
    if len(topic_words) >= 3:
        candidates.append(f"{topic_words[0]} {topic_words[2]}")
    if len(topic_words) >= 4:
        candidates.append(f"{topic_words[0]} {topic_words[-1]}")

    # 6. Domain visual stock queries based on article topic
    full_context = f"{title} {content}".lower()
    if any(k in full_context for k in ["hiring", "recruit", "interview", "candidate", "background check", "screening", "risk", "hr", "employee"]):
        candidates.append("hiring background checks")
        candidates.append("employee background checks")
        candidates.append("job interview hiring")
        candidates.append("business hiring")
        candidates.append("office interview")

    if any(k in full_context for k in ["bookkeep", "accounting", "tax", "finance", "cpa", "financial"]):
        candidates.append("business bookkeeping")
        candidates.append("business accounting")
        candidates.append("financial management")

    if any(k in full_context for k in ["call center", "customer support", "customer service", "coaching"]):
        candidates.append("call center customer service")
        candidates.append("customer service team")
        candidates.append("business coaching")

    if "remote" in full_context:
        candidates.append("remote business")
        candidates.append("remote work")

    if "leadership" in full_context or "management" in full_context:
        candidates.append("business leadership")
        candidates.append("business management")

    # 7. High-confidence core visual single nouns as progressive fallbacks
    for tw in topic_words:
        if tw in ("hiring", "interview", "workplace", "office", "business", "meeting", "team", "leadership"):
            candidates.append(tw)

    return list(dict.fromkeys(query.strip() for query in candidates if query.strip()))


def _configuration_required(reason: str) -> dict:
    return {
        "status": "CONFIGURATION_REQUIRED",
        "image_url": None,
        "image_id": None,
        "alt_text": None,
        "filename": None,
        "content_type": None,
        "image_bytes": None,
        "error": reason,
    }


def _failed(reason: str) -> dict:
    return {
        "status": "FAILED",
        "image_url": None,
        "image_id": None,
        "alt_text": None,
        "filename": None,
        "content_type": None,
        "image_bytes": None,
        "error": reason,
    }


def _extract_matches(data: dict) -> list[dict]:
    """Support Envato discovery response shapes without fabricating results."""
    matches = data.get("matches")
    if isinstance(matches, list):
        return matches
    results = data.get("results")
    if isinstance(results, list):
        return results
    return []


async def fetch_licensed_download(item_id: int) -> Optional[str]:
    """
    Attempt to obtain an official licensed download URL from Envato Buyer API:
    GET https://api.envato.com/v3/market/buyer/download?item_id={item_id}
    Returns clean download URL if token has purchase:download scope and item was purchased.
    """
    if not settings.ENVATO_API_TOKEN or not item_id:
        return None
    url = "https://api.envato.com/v3/market/buyer/download"
    headers = {
        "Authorization": f"Bearer {settings.ENVATO_API_TOKEN}",
        "User-Agent": "HBM Article Automation",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers, params={"item_id": item_id})
            if resp.status_code == 200:
                data = resp.json()
                dl_url = data.get("download_url")
                if dl_url:
                    log.info("Envato official licensed download URL obtained for item %s", item_id)
                    return dl_url
    except Exception as exc:
        log.debug("Envato buyer download lookup skipped: %s", exc)
    return None


def _image_url(item: dict) -> str:
    """
    Extract a clean, unwatermarked direct image URL for an Envato item.
    Strictly excludes watermarked preview/demo URLs and item-page HTML URLs.
    Prioritizes high-resolution clean assets (e.g. licensed download, c300, c200).
    """
    from services.image_providers import is_watermarked_asset

    # Helper: ensure candidate URL is a direct media file, never an item HTML page
    def is_usable_media_url(u: str) -> bool:
        if not u or not isinstance(u, str) or not u.startswith("http"):
            return False
        u_low = u.lower()
        if any(page_marker in u_low for page_marker in ["/item/", ".html", "photodune.net/item"]):
            return False
        return not is_watermarked_asset(u, item)

    # 1. Check if official licensed download URL is present
    if item.get("download_url") and is_usable_media_url(item["download_url"]):
        return item["download_url"]

    # 2. Extract clean candidates from image_urls, sorted by width descending
    clean_candidates_with_size: list[tuple[int, str]] = []

    # Check top-level image_urls
    top_img_urls = item.get("image_urls") or []
    if isinstance(top_img_urls, list):
        for img_obj in top_img_urls:
            if isinstance(img_obj, dict):
                u = img_obj.get("url")
                w = int(img_obj.get("width") or 0)
            else:
                u = str(img_obj)
                w = 0
            if is_usable_media_url(u):
                clean_candidates_with_size.append((w, u))

    # Check previews nested image_urls
    previews = item.get("previews") or {}
    if isinstance(previews, dict):
        for p_name, p_data in previews.items():
            if isinstance(p_data, dict):
                p_img_urls = p_data.get("image_urls") or []
                if isinstance(p_img_urls, list):
                    for img_obj in p_img_urls:
                        if isinstance(img_obj, dict):
                            u = img_obj.get("url")
                            w = int(img_obj.get("width") or 0)
                        else:
                            u = str(img_obj)
                            w = 0
                        if is_usable_media_url(u):
                            clean_candidates_with_size.append((w, u))

    # Sort candidates by width descending so highest resolution clean asset is chosen
    clean_candidates_with_size.sort(key=lambda x: x[0], reverse=True)
    for w, u in clean_candidates_with_size:
        if is_usable_media_url(u):
            return u

    # 3. Fallback to clean preview scalar fields
    fallback_candidates = []
    if isinstance(previews, dict):
        for p_name, p_data in previews.items():
            if isinstance(p_data, dict):
                for key in ("large_url", "landscape_url", "small_url", "preview_url", "thumbnail_url", "icon_url"):
                    u = p_data.get(key)
                    if is_usable_media_url(u):
                        fallback_candidates.append(u)

    for key in ("preview_url", "thumbnail_url", "thumbnail", "square_url", "icon_url"):
        u = item.get(key)
        if is_usable_media_url(u):
            fallback_candidates.append(u)

    for cand in fallback_candidates:
        if is_usable_media_url(cand):
            return cand

    return ""


async def fetch_image(query: str, fallback_queries: Iterable[str] = ()) -> dict:
    """
    Search Envato and download a clean, relevant licensed image result.
    Strictly avoids watermarked preview or demo images.
    """
    log.info("Envato image service called with query: %r", query)
    if not is_configured():
        return _configuration_required(
            "ENVATO_API_TOKEN is missing. Create an Envato API personal token "
            "and set ENVATO_API_TOKEN in backend/.env."
        )
    if not query.strip():
        return _failed("Cannot search Envato without an article topic.")

    from services.image_providers import is_watermarked_asset

    headers = {
        "Authorization": f"Bearer {settings.ENVATO_API_TOKEN}",
        "User-Agent": "HBM Article Automation",
        "Accept": "application/json",
    }
    site_pref = getattr(settings, "ENVATO_SITE", "photodune.net") or "photodune.net"
    sites_to_try = ["photodune.net"]
    if site_pref not in sites_to_try:
        sites_to_try.append(site_pref)

    attempted_queries = list(dict.fromkeys(q.strip() for q in fallback_queries if q.strip()))
    if query.strip() not in attempted_queries:
        attempted_queries.insert(0, query.strip())

    diagnostics: list[dict] = []

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for site in sites_to_try:
            for attempted_query in attempted_queries:
                params = {
                    "term": attempted_query,
                    "site": site,
                    "page": 1,
                    "page_size": 10,
                }
                log.info("Envato search query attempted: %r (site=%s)", attempted_query, site)
                try:
                    response = await client.get(settings.ENVATO_API_URL, headers=headers, params=params)
                    response.raise_for_status()
                    matches = _extract_matches(response.json())
                    match_ids = [m.get("id") for m in matches if m.get("id")]
                    # Safe diagnostic logging (no token)
                    log.info(
                        "Envato search query %r on site %s: HTTP %s, %d matches found, item IDs: %s",
                        attempted_query, site, response.status_code, len(matches), match_ids[:5],
                    )
                    diagnostics.append({
                        "query": attempted_query,
                        "site": site,
                        "status_code": response.status_code,
                        "count": len(matches),
                        "item_ids": match_ids[:5],
                    })
                except httpx.HTTPStatusError as exc:
                    log.error(
                        "Envato API error %s on query %r: %s",
                        exc.response.status_code, attempted_query, exc.response.text[:300],
                    )
                    if exc.response.status_code in (401, 403):
                        return _configuration_required(
                            "Envato rejected the API token. Check ENVATO_API_TOKEN."
                        )
                    diagnostics.append({
                        "query": attempted_query,
                        "site": site,
                        "status_code": exc.response.status_code,
                        "error": exc.response.text[:200],
                    })
                    continue
                except httpx.RequestError as exc:
                    log.error("Envato request error on query %r: %s", attempted_query, exc)
                    diagnostics.append({
                        "query": attempted_query,
                        "site": site,
                        "error": str(exc),
                    })
                    continue

                for item in matches:
                    classification = str(item.get("classification", "")).lower()
                    if any(bad in classification for bad in ["presentation-templates", "print-templates", "logo-templates"]):
                        continue

                    # Check for official licensed download first
                    item_id = item.get("id")
                    licensed_dl = await fetch_licensed_download(item_id) if item_id else None
                    if licensed_dl:
                        item["download_url"] = licensed_dl

                    image_url = _image_url(item)
                    if not image_url or is_watermarked_asset(image_url, item):
                        continue

                    log.info(
                        "Envato selected clean candidate title=%r id=%r url=%s",
                        item.get("name") or item.get("title"),
                        item_id,
                        image_url[:80],
                    )
                    try:
                        image_response = await client.get(image_url)
                        image_response.raise_for_status()
                    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                        log.error("Envato image download error for URL %s: %s", image_url[:80], exc)
                        continue

                    log.info(
                        "Envato download response: HTTP %s, Content-Type: %s, Length: %d bytes",
                        image_response.status_code,
                        image_response.headers.get("content-type"),
                        len(image_response.content),
                    )

                    content_type = image_response.headers.get("content-type", "").split(";")[0].lower()
                    image_bytes = image_response.content

                    # Validate downloaded file content and MIME type (Requirement 6)
                    if not content_type.startswith("image/") or not image_bytes:
                        log.warning("Envato downloaded asset rejected: invalid content-type %s", content_type)
                        continue

                    # Reject HTML error pages disguised as image responses
                    if image_bytes.startswith(b"<!DOCTYPE") or image_bytes.startswith(b"<html") or b"<body" in image_bytes[:500]:
                        log.warning("Envato downloaded asset rejected: content is HTML page, not an image")
                        continue

                    # Validate image bytes integrity using PIL
                    try:
                        probe_img = Image.open(io.BytesIO(image_bytes))
                        probe_img.verify()
                    except Exception as img_err:
                        log.warning("Envato image bytes verification failed: %s", img_err)
                        continue

                    filename = f"envato-{item_id or 'image'}.{content_type.split('/', 1)[-1]}"
                    return {
                        "status": "PASSED",
                        "image_url": image_url,
                        "image_id": item_id,
                        "alt_text": item.get("name") or item.get("title") or attempted_query[:120],
                        "filename": filename,
                        "content_type": content_type,
                        "image_bytes": image_bytes,
                        "diagnostics": diagnostics,
                        "error": None,
                    }

    # Specific diagnostic failure message (Requirement 9)
    total_matches = sum(d.get("count", 0) for d in diagnostics if "count" in d)
    return _failed(
        f"Envato API returned no clean downloadable image results on '{site_pref}' across attempted queries: "
        f"{', '.join(repr(q) for q in attempted_queries[:5])}. "
        f"({total_matches} raw matches found across {len(attempted_queries)} queries, but no clean assets available)."
    )
