"""
Real image provider integration and status verification service.

Supported providers:
  1. Envato
  2. Magnific (AI Generation)
  3. Dreamstime
  4. Unsplash
  5. Deposit Photos
  6. Pexels
  7. Calamari

All credentials are kept strictly server-side.
Status tracking: LIVE, CONFIGURED, NOT_CONFIGURED, UNAVAILABLE, ERROR.
Never fake an API integration or return fake assets.
"""

import asyncio
from datetime import datetime, timezone
import io
from html import unescape
import logging
import os
import re
import time
from typing import Any, Optional

import httpx

from core.config import settings
from core.database import SessionLocal
from models.report import WorkflowReport
import services.envato as envato_service

log = logging.getLogger(__name__)

# Provider status cache: { provider_id: { "status": ..., "details": ..., "checked_at": ... } }
_STATUS_CACHE: dict[str, dict[str, Any]] = {}
CACHE_TTL_SECONDS = 60

# Provider definitions
PROVIDERS_CONFIG = [
    {
        "id": "envato",
        "name": "Envato",
        "type": "stock",
        "env_key": "ENVATO_API_TOKEN",
        "attribution_template": "GraphicRiver / Envato",
    },
    {
        "id": "magnific",
        "name": "Magnific",
        "type": "ai_generation",
        "env_key": "MAGNIFIC_API_KEY",
        "attribution_template": "AI generated via Magnific",
    },
    {
        "id": "dreamstime",
        "name": "Dreamstime",
        "type": "stock",
        "env_key": "DREAMSTIME_API_KEY",
        "attribution_template": "Dreamstime",
    },
    {
        "id": "unsplash",
        "name": "Unsplash",
        "type": "stock",
        "env_key": "UNSPLASH_ACCESS_KEY",
        "attribution_template": "Unsplash",
    },
    {
        "id": "depositphotos",
        "name": "Deposit Photos",
        "type": "stock",
        "env_key": "DEPOSITPHOTOS_API_KEY",
        "attribution_template": "Depositphotos",
    },
    {
        "id": "pexels",
        "name": "Pexels",
        "type": "stock",
        "env_key": "PEXELS_API_KEY",
        "attribution_template": "Pexels",
    },
    {
        "id": "calamari",
        "name": "Calamari",
        "type": "stock",
        "env_key": "CALAMARI_API_KEY",
        "attribution_template": "Calamari",
    },
]

# Common watermark and preview marker tokens to reject
WATERMARK_MARKERS = [
    "watermark",
    "watermarked",
    "watermarks/",
    "mark=",
    "wm_",
    "_wm",
    "watermark_preview",
    "stock_watermark",
    "preview_watermark",
    "shutterstock_watermark",
    "dreamstime_watermark",
    "depositphotos_watermark",
    "comp_image",
    "watermarked_comp",
    "preview.jpg",
    "preview.png",
    "/previews/files/",
    "/preview.",
    "presentation-templates",
    "powerpoint",
    "keynote",
    "590px.jpg",
    "print-templates",
    "flyer",
    "brochure",
    "mockup",
    "demo_preview",
    "live_preview",
]


# ---------------------------------------------------------------------------
# Dynamic Status Checking
# ---------------------------------------------------------------------------

async def check_provider_status(provider_id: str, force_refresh: bool = False) -> dict:
    """
    Check real-time health and configuration status of an image provider.

    Returns:
        {
            "id": provider_id,
            "name": str,
            "status": "LIVE" | "CONFIGURED" | "NOT_CONFIGURED" | "UNAVAILABLE" | "ERROR",
            "configured": bool,
            "details": str,
        }
    """
    provider_id = (provider_id or "").lower().strip()
    cfg = next((p for p in PROVIDERS_CONFIG if p["id"] == provider_id), None)
    if not cfg:
        return {
            "id": provider_id,
            "name": provider_id.title(),
            "status": "UNAVAILABLE",
            "configured": False,
            "details": f"Unknown provider '{provider_id}'.",
        }

    # Check cache
    now = time.time()
    cached = _STATUS_CACHE.get(provider_id)
    if not force_refresh and cached and (now - cached.get("checked_at", 0) < CACHE_TTL_SECONDS):
        return {
            "id": cfg["id"],
            "name": cfg["name"],
            "status": cached["status"],
            "configured": cached["configured"],
            "details": cached["details"],
        }

    # 1. Envato
    if provider_id == "envato":
        token = getattr(settings, "ENVATO_API_TOKEN", "") or os.getenv("ENVATO_API_TOKEN", "")
        if not token:
            res = {
                "status": "NOT_CONFIGURED",
                "configured": False,
                "details": "ENVATO_API_TOKEN is not configured in backend environment.",
            }
        else:
            try:
                headers = {
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "HBM Article Automation",
                    "Accept": "application/json",
                }
                params = {
                    "term": "business",
                    "site": getattr(settings, "ENVATO_SITE", "graphicriver.net"),
                    "page_size": 1,
                }
                url = getattr(settings, "ENVATO_API_URL", "https://api.envato.com/v1/discovery/search/search/item")
                async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                    resp = await client.get(url, headers=headers, params=params)
                    if resp.status_code == 200:
                        res = {"status": "LIVE", "configured": True, "details": "Official Envato API verified and operational."}
                    elif resp.status_code in (401, 403):
                        res = {"status": "UNAVAILABLE", "configured": True, "details": f"Envato API authentication failed (HTTP {resp.status_code})."}
                    else:
                        res = {"status": "ERROR", "configured": True, "details": f"Envato API returned HTTP {resp.status_code}."}
            except Exception as exc:
                log.warning("Envato health check exception: %s", exc)
                res = {"status": "UNAVAILABLE", "configured": True, "details": f"Could not connect to Envato API: {exc}"}

    # 2. Pexels
    elif provider_id == "pexels":
        key = getattr(settings, "PEXELS_API_KEY", "") or os.getenv("PEXELS_API_KEY", "")
        if not key:
            res = {
                "status": "NOT_CONFIGURED",
                "configured": False,
                "details": "PEXELS_API_KEY is not configured in backend environment.",
            }
        else:
            try:
                headers = {"Authorization": key, "User-Agent": "HBM Article Automation"}
                base_url = getattr(settings, "PEXELS_API_URL", "https://api.pexels.com/v1").rstrip("/")
                async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                    resp = await client.get(f"{base_url}/curated?per_page=1", headers=headers)
                    if resp.status_code == 200:
                        res = {"status": "LIVE", "configured": True, "details": "Official Pexels API verified and operational."}
                    elif resp.status_code in (401, 403):
                        res = {"status": "UNAVAILABLE", "configured": True, "details": f"Pexels API authentication failed (HTTP {resp.status_code})."}
                    else:
                        res = {"status": "ERROR", "configured": True, "details": f"Pexels API returned HTTP {resp.status_code}."}
            except Exception as exc:
                log.warning("Pexels health check exception: %s", exc)
                res = {"status": "UNAVAILABLE", "configured": True, "details": f"Could not connect to Pexels API: {exc}"}

    # 3. Unsplash
    elif provider_id == "unsplash":
        key = getattr(settings, "UNSPLASH_ACCESS_KEY", "") or os.getenv("UNSPLASH_ACCESS_KEY", "")
        if not key:
            res = {
                "status": "NOT_CONFIGURED",
                "configured": False,
                "details": "UNSPLASH_ACCESS_KEY is not configured in backend environment.",
            }
        else:
            try:
                headers = {"Authorization": f"Client-ID {key}", "User-Agent": "HBM Article Automation"}
                base_url = getattr(settings, "UNSPLASH_API_URL", "https://api.unsplash.com").rstrip("/")
                async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                    resp = await client.get(f"{base_url}/photos?per_page=1", headers=headers)
                    if resp.status_code == 200:
                        res = {"status": "LIVE", "configured": True, "details": "Official Unsplash API verified and operational."}
                    elif resp.status_code in (401, 403):
                        res = {"status": "UNAVAILABLE", "configured": True, "details": f"Unsplash API authentication failed (HTTP {resp.status_code})."}
                    else:
                        res = {"status": "ERROR", "configured": True, "details": f"Unsplash API returned HTTP {resp.status_code}."}
            except Exception as exc:
                log.warning("Unsplash health check exception: %s", exc)
                res = {"status": "UNAVAILABLE", "configured": True, "details": f"Could not connect to Unsplash API: {exc}"}

    # 4. Magnific (AI Generation)
    elif provider_id == "magnific":
        key = getattr(settings, "MAGNIFIC_API_KEY", "") or os.getenv("MAGNIFIC_API_KEY", "")
        if not key:
            res = {
                "status": "NOT_CONFIGURED",
                "configured": False,
                "details": "MAGNIFIC_API_KEY is not configured in backend environment.",
            }
        else:
            api_url = getattr(settings, "MAGNIFIC_API_URL", "https://api.magnific.ai/v1").rstrip("/")
            try:
                headers = {"Authorization": f"Bearer {key}", "User-Agent": "HBM Article Automation"}
                async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                    resp = await client.get(f"{api_url}/status", headers=headers)
                    if resp.status_code in (200, 204):
                        res = {"status": "LIVE", "configured": True, "details": "Official Magnific API verified and operational."}
                    elif resp.status_code in (401, 403):
                        res = {"status": "UNAVAILABLE", "configured": True, "details": f"Magnific API authentication failed (HTTP {resp.status_code})."}
                    else:
                        res = {"status": "CONFIGURED", "configured": True, "details": f"Magnific credentials configured (HTTP {resp.status_code})."}
            except Exception as exc:
                log.warning("Magnific health check exception: %s", exc)
                res = {"status": "UNAVAILABLE", "configured": True, "details": f"Could not connect to Magnific API: {exc}"}

    # 5. Dreamstime
    elif provider_id == "dreamstime":
        key = getattr(settings, "DREAMSTIME_API_KEY", "") or os.getenv("DREAMSTIME_API_KEY", "")
        if not key:
            res = {
                "status": "NOT_CONFIGURED",
                "configured": False,
                "details": "DREAMSTIME_API_KEY is not configured in backend environment.",
            }
        else:
            api_url = getattr(settings, "DREAMSTIME_API_URL", "https://www.dreamstime.com/api/").rstrip("/")
            try:
                params = {"api_key": key}
                secret = getattr(settings, "DREAMSTIME_API_SECRET", "") or os.getenv("DREAMSTIME_API_SECRET", "")
                if secret:
                    params["api_secret"] = secret
                async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                    resp = await client.get(f"{api_url}/check", params=params)
                    if resp.status_code == 200:
                        res = {"status": "LIVE", "configured": True, "details": "Official Dreamstime API verified and operational."}
                    elif resp.status_code in (401, 403):
                        res = {"status": "UNAVAILABLE", "configured": True, "details": f"Dreamstime API unauthorized (HTTP {resp.status_code})."}
                    else:
                        res = {"status": "UNAVAILABLE", "configured": True, "details": f"Dreamstime API returned HTTP {resp.status_code}."}
            except Exception as exc:
                log.warning("Dreamstime health check exception: %s", exc)
                res = {"status": "UNAVAILABLE", "configured": True, "details": f"Could not connect to Dreamstime API: {exc}"}

    # 6. Deposit Photos
    elif provider_id == "depositphotos":
        key = getattr(settings, "DEPOSITPHOTOS_API_KEY", "") or os.getenv("DEPOSITPHOTOS_API_KEY", "")
        if not key:
            res = {
                "status": "NOT_CONFIGURED",
                "configured": False,
                "details": "DEPOSITPHOTOS_API_KEY is not configured in backend environment.",
            }
        else:
            api_url = getattr(settings, "DEPOSITPHOTOS_API_URL", "https://api.depositphotos.com").rstrip("/")
            try:
                params = {"dp_command": "getMediaData", "dp_apikey": key}
                async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                    resp = await client.get(api_url, params=params)
                    if resp.status_code == 200:
                        res = {"status": "LIVE", "configured": True, "details": "Official Depositphotos API verified and operational."}
                    elif resp.status_code in (401, 403):
                        res = {"status": "UNAVAILABLE", "configured": True, "details": f"Depositphotos API unauthorized (HTTP {resp.status_code})."}
                    else:
                        res = {"status": "UNAVAILABLE", "configured": True, "details": f"Depositphotos API returned HTTP {resp.status_code}."}
            except Exception as exc:
                log.warning("Depositphotos health check exception: %s", exc)
                res = {"status": "UNAVAILABLE", "configured": True, "details": f"Could not connect to Depositphotos API: {exc}"}

    # 7. Calamari
    elif provider_id == "calamari":
        key = getattr(settings, "CALAMARI_API_KEY", "") or os.getenv("CALAMARI_API_KEY", "")
        if not key:
            res = {
                "status": "NOT_CONFIGURED",
                "configured": False,
                "details": "CALAMARI_API_KEY is not configured in backend environment.",
            }
        else:
            api_url = (getattr(settings, "CALAMARI_API_URL", "") or os.getenv("CALAMARI_API_URL", "")).rstrip("/")
            if not api_url:
                res = {"status": "NOT_CONFIGURED", "configured": False, "details": "CALAMARI_API_URL is not configured."}
            else:
                try:
                    headers = {"Authorization": f"Bearer {key}", "User-Agent": "HBM Article Automation"}
                    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                        resp = await client.get(f"{api_url}/health", headers=headers)
                        if resp.status_code == 200:
                            res = {"status": "LIVE", "configured": True, "details": "Official Calamari API verified and operational."}
                        else:
                            res = {"status": "UNAVAILABLE", "configured": True, "details": f"Calamari API returned HTTP {resp.status_code}."}
                except Exception as exc:
                    log.warning("Calamari health check exception: %s", exc)
                    res = {"status": "UNAVAILABLE", "configured": True, "details": f"Could not connect to Calamari API: {exc}"}
    else:
        res = {"status": "UNAVAILABLE", "configured": False, "details": "Unsupported provider."}

    # Update cache
    _STATUS_CACHE[provider_id] = {
        "status": res["status"],
        "configured": res["configured"],
        "details": res["details"],
        "checked_at": now,
    }

    return {
        "id": cfg["id"],
        "name": cfg["name"],
        "status": res["status"],
        "configured": res["configured"],
        "details": res["details"],
    }


async def list_all_providers(force_refresh: bool = False) -> list[dict]:
    """Return status of all 7 supported providers dynamically."""
    tasks = [check_provider_status(p["id"], force_refresh=force_refresh) for p in PROVIDERS_CONFIG]
    results = await asyncio.gather(*tasks)
    return results


# ---------------------------------------------------------------------------
# Duplicate Prevention History Check
# ---------------------------------------------------------------------------

def is_duplicate_image(source_url: str, source_id: Optional[str] = None) -> bool:
    """
    Check if the image source URL or media ID was already used in previous workflow reports.
    """
    if not source_url and not source_id:
        return False

    try:
        with SessionLocal() as db:
            query = db.query(WorkflowReport.image_source_url).filter(
                WorkflowReport.image_source_url.isnot(None),
                WorkflowReport.image_source_url != "",
            )
            used_urls = [row[0] for row in query.all() if row[0]]

            if source_url and any(source_url.strip().lower() == u.strip().lower() for u in used_urls):
                return True

            if source_id:
                id_str = str(source_id).strip()
                if any(id_str in u for u in used_urls):
                    return True

    except Exception as exc:
        log.warning("Duplicate image check query failed: %s", exc)

    return False


# ---------------------------------------------------------------------------
# Watermark & Clean Asset Verification
# ---------------------------------------------------------------------------

def is_watermarked_asset(url_or_name: str, item_metadata: Optional[dict] = None) -> bool:
    """
    Check if the asset URL, filename, or metadata indicates a watermarked preview or demo image.
    Returns True if watermark or demo template marker is found.
    """
    target = (url_or_name or "").lower()
    if any(marker in target for marker in WATERMARK_MARKERS):
        return True

    if item_metadata:
        classification = str(item_metadata.get("classification", "")).lower()
        if any(cls_marker in classification for cls_marker in ["presentation-templates", "print-templates", "logo-templates"]):
            return True
        meta_str = str(item_metadata).lower()
        if any(marker in meta_str for marker in ["watermark", "watermarked"]):
            if any(m in target for m in ["mark=", "preview.jpg", "preview.png", "watermark", "watermarks/"]):
                return True

    return False


# ---------------------------------------------------------------------------
# Query Generation & Result Ranking
# ---------------------------------------------------------------------------

def generate_search_queries(
    title: str,
    focus_keyphrase: Optional[str] = None,
    article_content: Optional[str] = None,
) -> dict:
    """
    Generate primary query, secondary query, and fallback terms from the article title:
      - Primary query: clean article title (or main substantive clause if title has labels)
      - Key title phrases: 2-3 word topical combinations extracted directly from title
      - Fallback: contextually relevant title bigrams, trigrams, and domain visual phrases
    """
    clean_title = unescape(re.sub(r"<[^>]+>", " ", title or "")).strip()
    clean_title = re.sub(r"^\d+[\s\.\)\:\-]*", "", clean_title).strip()
    
    parts = [p.strip() for p in re.split(r"[:|?–—]|\s+-\s+", clean_title) if p.strip()]
    main_clause = clean_title
    if len(parts) > 1:
        # If the prefix is a short label (e.g. "Distributed: The Future of Distributed Leadership")
        if len(parts[0].split()) <= 2:
            main_clause = parts[1]
        else:
            main_clause = parts[0]
    elif parts:
        main_clause = parts[0]

    primary_clean = re.sub(r"[?!.,'\"]+", "", main_clause).strip() or clean_title[:80].strip()

    stop_words = {
        "a", "about", "above", "after", "again", "all", "also", "am", "an", "and", "any", "are", "as", "at",
        "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can", "could",
        "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from", "further", "had", "has",
        "have", "having", "he", "help", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just",
        "me", "more", "most", "my", "no", "nor", "not", "now", "of", "off", "on", "once", "only", "or",
        "other", "our", "ours", "out", "over", "own", "same", "she", "should", "so", "some", "such", "than",
        "that", "the", "their", "theirs", "them", "themselves", "then", "there", "these", "they", "this",
        "those", "through", "to", "too", "under", "until", "up", "very", "was", "we", "were", "what", "when",
        "where", "which", "while", "who", "whom", "why", "will", "with", "would", "you", "your", "yours",
        "essential", "strategies", "strategy", "thriving", "guide", "tips", "top", "ways", "checklist",
        "review", "draft", "article", "steps", "mastering", "future", "scale", "without", "losing",
        "running", "here", "heres", "here's", "hand", "handing", "getting", "starting", "compared",
        # Non-visual qualifiers & niche acronyms that return 0 stock photos on Envato
        "canadian", "canada", "american", "us", "usa", "uk", "australian",
        "smb", "smbs", "sme", "smes", "b2b", "b2c", "llc", "inc", "ltd", "corp",
    }

    # Extract deduplicated significant words in order across the entire title
    cleaned_full = re.sub(r"[^\w\s-]", " ", f"{primary_clean} {clean_title}".lower())
    title_words = re.findall(r"[a-z][a-z0-9-]*", cleaned_full)
    topic_terms = []
    for w in title_words:
        w_clean = w.strip("'-")
        if len(w_clean) > 2 and w_clean not in stop_words and w_clean not in topic_terms:
            topic_terms.append(w_clean)

    # N-grams from topic terms
    fallback_phrases = []

    # Consecutive bigrams across all keywords
    for i in range(len(topic_terms) - 1):
        fallback_phrases.append(f"{topic_terms[i]} {topic_terms[i+1]}")

    # Consecutive trigrams across all keywords
    for i in range(len(topic_terms) - 2):
        fallback_phrases.append(f"{topic_terms[i]} {topic_terms[i+1]} {topic_terms[i+2]}")

    # Skip-pairs
    if len(topic_terms) >= 3:
        fallback_phrases.append(f"{topic_terms[0]} {topic_terms[2]}")
    if len(topic_terms) >= 4:
        fallback_phrases.append(f"{topic_terms[0]} {topic_terms[-1]}")

    # Domain visual stock queries
    full_str = f"{clean_title} {article_content or ''}".lower()
    if any(k in full_str for k in ["hiring", "recruit", "interview", "candidate", "background check", "screening", "risk", "hr", "employee"]):
        fallback_phrases.append("hiring background checks")
        fallback_phrases.append("employee background checks")
        fallback_phrases.append("job interview hiring")
        fallback_phrases.append("business hiring")
        fallback_phrases.append("office interview")

    if any(k in full_str for k in ["bookkeep", "accounting", "tax", "finance", "cpa", "financial"]):
        fallback_phrases.append("business bookkeeping")
        fallback_phrases.append("business accounting")
        fallback_phrases.append("financial management")

    if any(k in full_str for k in ["call center", "customer support", "customer service", "coaching"]):
        fallback_phrases.append("call center customer service")
        fallback_phrases.append("customer service team")
        fallback_phrases.append("business coaching")

    if "remote" in clean_title.lower():
        fallback_phrases.append("remote business")
        fallback_phrases.append("remote work")
    if "leadership" in clean_title.lower():
        fallback_phrases.append("business leadership")

    # If title is short (2-4 words), include it in fallbacks
    if len(primary_clean.split()) <= 4 and primary_clean not in fallback_phrases:
        fallback_phrases.append(primary_clean)

    if focus_keyphrase:
        kw_clean = re.sub(r"[^\w\s-]", " ", focus_keyphrase.lower())
        kw_words = [w.strip() for w in kw_clean.split() if len(w.strip()) > 2 and w.strip() not in stop_words]
        if kw_words:
            fallback_phrases.append(" ".join(kw_words[:3]))

    # Progressive single-term fallbacks
    for tw in topic_terms:
        if tw in ("hiring", "interview", "workplace", "office", "business", "meeting", "team", "leadership"):
            fallback_phrases.append(tw)

    fallback_phrases = list(dict.fromkeys(fallback_phrases))

    secondary = ""
    if focus_keyphrase:
        secondary = focus_keyphrase.strip()

    fallback = fallback_phrases[0] if fallback_phrases else primary_clean

    return {
        "primary": primary_clean,
        "secondary": secondary,
        "fallback": fallback,
        "fallbacks": fallback_phrases,
        "topic_terms": topic_terms,
    }


def rank_candidates(
    candidates: list[dict],
    query: str,
    focus_keyphrase: Optional[str] = None,
    enforce_duplicate_check: bool = False,
) -> list[dict]:
    """
    Rank search candidates based on:
      1. Semantic relevance to query and focus keyphrase
      2. Orientation (landscape / horizontal preferred)
      3. Clean asset (no watermark indicators)
      4. Duplicate history
    """
    query_tokens = set(re.findall(r"[a-z0-9]+", (query or "").lower()))
    if focus_keyphrase:
        query_tokens.update(re.findall(r"[a-z0-9]+", focus_keyphrase.lower()))

    scored = []
    for item in candidates:
        img_url = item.get("image_url") or item.get("source_url") or ""
        item_id = str(item.get("id") or "")

        # Watermark check: reject if watermarked preview
        if is_watermarked_asset(img_url, item):
            log.info("Rejecting watermarked preview candidate: %s", img_url)
            continue

        # Duplicate check: reject or severely penalize if already used
        if is_duplicate_image(img_url, item_id):
            if enforce_duplicate_check:
                log.info("Rejecting duplicate image candidate per client directive: %s", img_url)
                continue
            score = -100.0
        else:
            score = 10.0

        # Semantic relevance
        title_text = (item.get("title") or item.get("alt") or "").lower()
        title_tokens = set(re.findall(r"[a-z0-9]+", title_text))
        overlap = len(query_tokens.intersection(title_tokens))
        score += overlap * 5.0

        # Orientation bonus: landscape
        width = item.get("width") or 0
        height = item.get("height") or 0
        if width > height and height > 0:
            score += 15.0  # Landscape preferred for 1000×667 px banner

        scored.append((score, item))

    # Sort descending by score
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored]


# ---------------------------------------------------------------------------
# Search Execution for Supported Providers
# ---------------------------------------------------------------------------

async def search_provider_images(provider_id: str, query: str, limit: int = 12) -> dict:
    """
    Search real images from a configured provider.
    Never fabricates fake results.
    """
    pid = (provider_id or "envato").lower().strip()
    status_info = await check_provider_status(pid)

    if status_info["status"] != "LIVE":
        return {
            "provider": pid,
            "status": status_info["status"],
            "results": [],
            "error": f"Provider '{status_info['name']}' is {status_info['status']}: {status_info['details']}",
        }

    # 1. Envato Search
    if pid == "envato":
        headers = {
            "Authorization": f"Bearer {settings.ENVATO_API_TOKEN}",
            "User-Agent": "HBM Article Automation",
            "Accept": "application/json",
        }
        site_pref = getattr(settings, "ENVATO_SITE", "photodune.net") or "photodune.net"
        # Prioritize photodune.net for stock photography
        sites_to_try = ["photodune.net"]
        if site_pref not in sites_to_try:
            sites_to_try.append(site_pref)

        try:
            results = []
            attempt_diag = []
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                for site in sites_to_try:
                    params = {
                        "term": query.strip(),
                        "site": site,
                        "page": 1,
                        "page_size": min(limit, 20),
                    }
                    resp = await client.get(settings.ENVATO_API_URL, headers=headers, params=params)
                    if resp.status_code != 200:
                        log.warning(
                            "Envato API query %r on site %s returned HTTP %s: %s",
                            query.strip(), site, resp.status_code, resp.text[:250],
                        )
                        attempt_diag.append(f"HTTP {resp.status_code} on {site}")
                        continue

                    matches = envato_service._extract_matches(resp.json())
                    match_ids = [m.get("id") for m in matches if m.get("id")]
                    # Safe diagnostic log without token
                    log.info(
                        "Envato API query %r on site %s: HTTP %s, %d matches found, item IDs: %s",
                        query.strip(), site, resp.status_code, len(matches), match_ids[:5],
                    )
                    attempt_diag.append(f"{len(matches)} matches on {site}")

                    for item in matches:
                        classification = str(item.get("classification", "")).lower()
                        if any(bad in classification for bad in ["presentation-templates", "print-templates", "logo-templates", "web-elements"]):
                            continue
                        img_url = envato_service._image_url(item)
                        if img_url and not is_watermarked_asset(img_url, item):
                            item_id = item.get("id")
                            item_name = item.get("name") or item.get("title") or "Envato Stock Photo"
                            canonical_url = item.get("url") or f"https://{site}/item/id/{item_id}" if item_id else ""
                            results.append({
                                "id": item_id,
                                "title": item_name,
                                "image_url": img_url,
                                "thumbnail_url": img_url,
                                "source_url": canonical_url,
                                "source": "envato",
                                "provider": "Envato",
                                "site": site,
                            })
                    if results:
                        break

                err_msg = None if results else f"Envato search for '{query}' returned 0 clean assets ({', '.join(attempt_diag)})"
                return {"provider": "envato", "status": "LIVE", "results": results, "error": err_msg}
        except Exception as exc:
            log.error("Envato search error: %s", exc)
            return {"provider": "envato", "status": "ERROR", "results": [], "error": f"Envato search failed: {exc}"}

    # 2. Pexels Search
    elif pid == "pexels":
        headers = {"Authorization": settings.PEXELS_API_KEY, "User-Agent": "HBM Article Automation"}
        params = {"query": query.strip(), "per_page": min(limit, 20), "orientation": "landscape"}
        base_url = settings.PEXELS_API_URL.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(f"{base_url}/search", headers=headers, params=params)
                resp.raise_for_status()
                data = resp.json()
                results = []
                for photo in data.get("photos", []):
                    src = photo.get("src", {})
                    img_url = src.get("large2x") or src.get("large") or src.get("original")
                    if img_url and not is_watermarked_asset(img_url):
                        results.append({
                            "id": photo.get("id"),
                            "title": photo.get("alt") or f"Pexels Photo #{photo.get('id')}",
                            "image_url": img_url,
                            "thumbnail_url": src.get("medium") or src.get("small"),
                            "source_url": photo.get("url"),
                            "photographer": photo.get("photographer"),
                            "source": "pexels",
                            "provider": "Pexels",
                            "width": photo.get("width"),
                            "height": photo.get("height"),
                        })
                return {"provider": "pexels", "status": "LIVE", "results": results, "error": None}
        except Exception as exc:
            log.error("Pexels search error: %s", exc)
            return {"provider": "pexels", "status": "ERROR", "results": [], "error": f"Pexels search failed: {exc}"}

    # 3. Unsplash Search
    elif pid == "unsplash":
        headers = {"Authorization": f"Client-ID {settings.UNSPLASH_ACCESS_KEY}", "User-Agent": "HBM Article Automation"}
        params = {"query": query.strip(), "per_page": min(limit, 20), "orientation": "landscape"}
        base_url = settings.UNSPLASH_API_URL.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(f"{base_url}/search/photos", headers=headers, params=params)
                resp.raise_for_status()
                data = resp.json()
                results = []
                for photo in data.get("results", []):
                    urls = photo.get("urls", {})
                    img_url = urls.get("regular") or urls.get("full")
                    user = photo.get("user", {})
                    photographer = user.get("name") or user.get("username")
                    if img_url and not is_watermarked_asset(img_url):
                        results.append({
                            "id": photo.get("id"),
                            "title": photo.get("description") or photo.get("alt_description") or f"Unsplash Photo #{photo.get('id')}",
                            "image_url": img_url,
                            "thumbnail_url": urls.get("small") or urls.get("thumb"),
                            "source_url": photo.get("links", {}).get("html", ""),
                            "photographer": photographer,
                            "source": "unsplash",
                            "provider": "Unsplash",
                            "width": photo.get("width"),
                            "height": photo.get("height"),
                        })
                return {"provider": "unsplash", "status": "LIVE", "results": results, "error": None}
        except Exception as exc:
            log.error("Unsplash search error: %s", exc)
            return {"provider": "unsplash", "status": "ERROR", "results": [], "error": f"Unsplash search failed: {exc}"}

    return {
        "provider": pid,
        "status": status_info["status"],
        "results": [],
        "error": f"Provider '{status_info['name']}' does not have a live search API available.",
    }


# ---------------------------------------------------------------------------
# AI Generation (Priority 4: Magnific)
# ---------------------------------------------------------------------------

async def generate_ai_image(article_title: str, article_context: str = "") -> dict:
    """
    Generate an editorial featured image using Magnific Image Generation API.

    Rules:
      - Clean editorial business photograph
      - No text overlays
      - No logos
      - No watermarks
      - No fake brands
      - 1000px output
    """
    status_info = await check_provider_status("magnific")
    if status_info["status"] != "LIVE":
        return {
            "status": "UNAVAILABLE",
            "image_bytes": None,
            "error": f"IMAGE SOURCE UNAVAILABLE: Magnific is {status_info['status']} ({status_info['details']}).",
        }

    concept = (
        f"Professional editorial business photograph illustrating {article_title[:100]}, "
        "marketing attribution, clean modern office setting, realistic photography, "
        "no text, no logos, no watermarks, high dynamic range, natural lighting"
    )

    api_url = settings.MAGNIFIC_API_URL.rstrip("/")
    headers = {
        "Authorization": f"Bearer {settings.MAGNIFIC_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "HBM Article Automation",
    }
    payload = {
        "prompt": concept,
        "aspect_ratio": "3:2",
        "width": 1000,
        "height": 667,
    }

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.post(f"{api_url}/generate", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            image_url = data.get("image_url") or data.get("output_url")
            if not image_url:
                return {
                    "status": "FAILED",
                    "image_bytes": None,
                    "error": "Magnific API returned no image URL.",
                }

            # Download generated asset
            img_resp = await client.get(image_url)
            img_resp.raise_for_status()
            return {
                "status": "PASSED",
                "image_bytes": img_resp.content,
                "content_type": img_resp.headers.get("content-type", "image/jpeg").split(";")[0],
                "source_url": image_url,
                "source": "magnific",
                "alt_text": article_title[:125],
                "caption": "AI generated via Magnific",
                "error": None,
            }
    except Exception as exc:
        log.error("Magnific generation failed: %s", exc)
        return {
            "status": "FAILED",
            "image_bytes": None,
            "error": f"Magnific AI generation failed: {exc}",
        }
