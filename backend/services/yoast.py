"""
Yoast SEO service proxy.

This service proxies analysis requests to the real Node.js Yoast sidecar.
If the sidecar process is not running, it automatically starts it in the background.
"""

import asyncio
import logging
import os
from pathlib import Path
import subprocess
import time
from typing import Optional

import httpx

from core.config import settings

log = logging.getLogger(__name__)

_REPO_SIDECAR_DIR = str(Path(__file__).resolve().parents[2] / "yoast-sidecar")
_DESKTOP_SIDECAR_DIR = r"C:\Users\admin\OneDrive - Espial Solutions LLP\Desktop\hbm-automation"


def _resolve_sidecar_dir() -> str:
    env_dir = os.getenv("YOAST_SIDECAR_DIR", "").strip()
    if env_dir and os.path.exists(env_dir):
        return env_dir
    if os.path.exists(_REPO_SIDECAR_DIR):
        return _REPO_SIDECAR_DIR
    if os.path.exists(_DESKTOP_SIDECAR_DIR):
        return _DESKTOP_SIDECAR_DIR
    return _REPO_SIDECAR_DIR


def _get_endpoints() -> list[str]:
    endpoints = []
    sidecar_url = (getattr(settings, "YOAST_SIDECAR_URL", "") or os.getenv("YOAST_SIDECAR_URL", "")).strip().rstrip("/")
    if sidecar_url:
        analyze_url = sidecar_url if sidecar_url.endswith("/analyze") else f"{sidecar_url}/analyze"
        endpoints.append(analyze_url)
    endpoints.extend([
        "http://127.0.0.1:3939/analyze",
        "http://[::1]:3939/analyze",
        "http://localhost:3939/analyze",
    ])
    return endpoints


def _get_health_endpoints() -> list[str]:
    endpoints = []
    sidecar_url = (getattr(settings, "YOAST_SIDECAR_URL", "") or os.getenv("YOAST_SIDECAR_URL", "")).strip().rstrip("/")
    if sidecar_url:
        health_url = sidecar_url if sidecar_url.endswith("/health") else f"{sidecar_url}/health"
        endpoints.append(health_url)
    endpoints.extend([
        "http://127.0.0.1:3939/health",
        "http://[::1]:3939/health",
        "http://localhost:3939/health",
    ])
    return endpoints


def is_configured() -> bool:
    return bool(settings.BCWP_SECRET)


def _ensure_sidecar_running() -> bool:
    """Ensure the Yoast sidecar Node.js process is running on port 3939."""
    if not settings.BCWP_SECRET:
        log.warning("BCWP_SECRET is not configured; cannot start Yoast sidecar.")
        return False

    # Check if already listening
    for url in _get_health_endpoints():
        try:
            httpx.get(url, timeout=0.8)
            return True
        except Exception:
            pass

    sidecar_dir = _resolve_sidecar_dir()
    if not os.path.exists(sidecar_dir):
        log.warning("Yoast sidecar directory %s does not exist.", sidecar_dir)
        return False

    log.info("Starting Yoast sidecar background process on port 3939 from %s...", sidecar_dir)
    env = os.environ.copy()
    env["BCWP_SECRET"] = settings.BCWP_SECRET
    env["PORT"] = "3939"

    # On Windows, start detached
    flags = 0
    if os.name == "nt":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

    try:
        subprocess.Popen(
            ["node", "server.js"],
            cwd=sidecar_dir,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
    except Exception as exc:
        log.error("Failed to launch Yoast sidecar process: %s", exc)
        return False

    # Wait up to 3 seconds for port 3939 to start responding
    for _ in range(6):
        time.sleep(0.5)
        for url in _get_health_endpoints():
            try:
                httpx.get(url, timeout=0.8)
                log.info("Yoast sidecar started and ready on port 3939.")
                return True
            except Exception:
                pass

    return False


async def analyze(article_content: str, seo_requirements: dict, generated_seo: dict) -> dict:
    if not is_configured():
        return {
            "status": "NOT CONFIGURED",
            "score": 0,
            "feedback": ["BCWP_SECRET is missing. Yoast sidecar not configured."],
            "data": None,
        }

    explicit_fields = seo_requirements.get("explicit_fields", {})
    keyphrase = (
        generated_seo.get("focus_keyphrase")
        or explicit_fields.get("focus_keyphrase")
        or (generated_seo.get("title") or "article")
    )
    title = (
        generated_seo.get("seo_title")
        or explicit_fields.get("seo_title")
        or generated_seo.get("title", "")
    )
    description = (
        generated_seo.get("meta_description")
        or explicit_fields.get("meta_description")
        or generated_seo.get("excerpt", "")
    )
    slug = (
        generated_seo.get("slug")
        or explicit_fields.get("slug")
        or ""
    )

    # For HBM article automation, the publication domain is homebusinessmag.com,
    # while WordPress testing takes place on a test destination (e.g., espialsolutions.com).
    # The Yoast sidecar evaluates internal vs outbound links by checking if link hostnames match the permalink domain.
    # Therefore, the permalink sent to Yoast must always use the publication domain (homebusinessmag.com).
    clean_slug = slug.strip("/") if slug else "article"
    publication_domain = "https://homebusinessmag.com"
    permalink = f"{publication_domain}/{clean_slug}/"

    # Prepare payload exactly as requested by sidecar
    payload = {
        "content": article_content,
        "keyphrase": keyphrase,
        "title": title,
        "description": description,
        "slug": slug,
        "permalink": permalink,
        "date": generated_seo.get("date") or "",
    }

    headers = {
        "X-BCWP-Secret": settings.BCWP_SECRET,
        "Content-Type": "application/json",
    }

    # Attempt request with automatic sidecar start if needed
    for attempt in range(2):
        last_error = None
        for url in _get_endpoints():
            async with httpx.AsyncClient(timeout=30) as client:
                try:
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()

                    seo_score = data.get("seo", {}).get("score", 0)

                    return {
                        "status": "PASSED",
                        "score": seo_score,
                        "feedback": [],
                        "requirements": seo_requirements,
                        "data": data,
                    }
                except httpx.HTTPStatusError as exc:
                    err_msg = str(exc.response.status_code)
                    try:
                        err_json = exc.response.json()
                        if "error" in err_json:
                            err_msg += f": {err_json['error']}"
                    except Exception:
                        pass

                    log.error("Yoast sidecar returned %s: %s", exc.response.status_code, exc.response.text)
                    return {
                        "status": "FAILED",
                        "score": 0,
                        "feedback": [f"Yoast sidecar error: {err_msg}"],
                        "data": None,
                    }
                except httpx.RequestError as exc:
                    last_error = exc
                    continue

        if attempt == 0:
            # If all endpoints failed on first attempt, ensure sidecar is started and retry
            log.info("Yoast sidecar connection failed (%s) — attempting auto-start...", last_error)
            started = _ensure_sidecar_running()
            if not started:
                break

    log.error("Failed to connect to Yoast sidecar: %s", last_error)
    return {
        "status": "FAILED",
        "score": 0,
        "feedback": [
            "Failed to connect to Yoast sidecar. "
            "Please ensure the Yoast sidecar process is running."
        ],
        "data": None,
    }
