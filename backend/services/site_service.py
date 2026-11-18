"""
Service for managing configured destination WordPress sites.
All credentials are kept server-side and never returned to the frontend.
"""

import logging
from typing import Optional
import httpx

from core.config import settings
from core.database import SessionLocal
from models.wordpress_site import WordPressSite
import services.wordpress as wp_service

log = logging.getLogger(__name__)


def ensure_default_site() -> None:
    """Synchronize configured WordPress sites from .env into the database."""
    db = SessionLocal()
    try:
        configured_sites = settings.WORDPRESS_SITES
        if not configured_sites:
            return

        existing_sites = db.query(WordPressSite).all()
        existing_by_url = {s.url.rstrip("/").lower(): s for s in existing_sites}

        for idx, site_cfg in enumerate(configured_sites):
            norm_url = site_cfg["url"].rstrip("/").lower()
            if norm_url in existing_by_url:
                site = existing_by_url[norm_url]
                # Update configured values
                site.name = site_cfg["name"]
                site.username = site_cfg["username"]
                if site_cfg.get("app_password"):
                    site.app_password = site_cfg["app_password"]
                if idx == 0 and not any(s.is_default for s in existing_sites):
                    site.is_default = True
            else:
                new_site = WordPressSite(
                    name=site_cfg["name"],
                    url=site_cfg["url"].rstrip("/"),
                    username=site_cfg["username"],
                    app_password=site_cfg["app_password"],
                    is_default=site_cfg.get("is_default", idx == 0),
                )
                db.add(new_site)
                existing_by_url[norm_url] = new_site

        # Remove duplicate records if any exact duplicate URLs exist
        all_sites = db.query(WordPressSite).order_by(WordPressSite.id.asc()).all()
        seen_urls = set()
        for s in all_sites:
            u = s.url.rstrip("/").lower()
            if u in seen_urls:
                db.delete(s)
            else:
                seen_urls.add(u)

        db.commit()
    except Exception as exc:
        log.warning("Could not synchronize WordPress sites from environment: %s", exc)
        db.rollback()
    finally:
        db.close()


def list_sites() -> list[dict]:
    """Return all configured WordPress sites with credentials masked."""
    ensure_default_site()
    db = SessionLocal()
    try:
        sites = db.query(WordPressSite).order_by(WordPressSite.id.asc()).all()
        return [site.to_safe_dict() for site in sites]
    finally:
        db.close()


def get_site(site_id: int) -> Optional[WordPressSite]:
    """Fetch a WordPress site with credentials (server-side only)."""
    ensure_default_site()
    db = SessionLocal()
    try:
        site = db.query(WordPressSite).filter(WordPressSite.id == site_id).first()
        if site:
            db.expunge(site)
        return site
    finally:
        db.close()


def get_default_site() -> Optional[WordPressSite]:
    """Return default configured site or first site."""
    ensure_default_site()
    db = SessionLocal()
    try:
        site = db.query(WordPressSite).filter(WordPressSite.is_default == True).first()
        if not site:
            site = db.query(WordPressSite).order_by(WordPressSite.id.asc()).first()
        if site:
            db.expunge(site)
        return site
    finally:
        db.close()


def save_site(
    name: str,
    url: str,
    username: str,
    app_password: str,
    is_default: bool = False,
    site_id: Optional[int] = None,
) -> dict:
    """Add or update a WordPress site configuration."""
    db = SessionLocal()
    try:
        clean_url = url.strip().rstrip("/")
        if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
            clean_url = f"https://{clean_url}"

        if site_id:
            site = db.query(WordPressSite).filter(WordPressSite.id == site_id).first()
            if not site:
                raise ValueError(f"Site ID {site_id} not found")
            site.name = name.strip()
            site.url = clean_url
            site.username = username.strip()
            if app_password and app_password.strip():
                site.app_password = app_password.strip()
            if is_default:
                db.query(WordPressSite).update({"is_default": False})
                site.is_default = True
        else:
            if is_default:
                db.query(WordPressSite).update({"is_default": False})
            site = WordPressSite(
                name=name.strip(),
                url=clean_url,
                username=username.strip(),
                app_password=app_password.strip(),
                is_default=is_default,
            )
            db.add(site)

        db.commit()
        db.refresh(site)
        return site.to_safe_dict()
    finally:
        db.close()


def delete_site(site_id: int) -> bool:
    """Delete a WordPress site configuration."""
    db = SessionLocal()
    try:
        site = db.query(WordPressSite).filter(WordPressSite.id == site_id).first()
        if not site:
            return False
        db.delete(site)
        db.commit()
        return True
    finally:
        db.close()


async def test_connection(site: WordPressSite) -> dict:
    """Verify live authentication against the specified WordPress site."""
    if not site.url or not site.username or not site.app_password:
        return {"success": False, "error": "Missing URL or credentials."}

    endpoint = f"{site.url.rstrip('/')}/wp-json/wp/v2/users/me"
    auth = (site.username, site.app_password)

    try:
        resp = await wp_service._wp_request("GET", endpoint, auth=auth, timeout=15.0)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "success": True,
                "user_id": data.get("id"),
                "name": data.get("name"),
                "slug": data.get("slug"),
            }
        elif resp.status_code in (401, 403):
            err_msg = f"WordPress authentication failed (HTTP {resp.status_code}). Check username and Application Password."
            try:
                err_data = resp.json()
                if err_data.get("message"):
                    err_msg = f"WordPress authentication rejected (HTTP {resp.status_code}): {err_data.get('message')}"
            except Exception:
                pass
            return {
                "success": False,
                "error": err_msg,
                "status_code": resp.status_code,
            }
        else:
            return {
                "success": False,
                "error": f"WordPress returned HTTP {resp.status_code}.",
                "status_code": resp.status_code,
            }
    except Exception as exc:
        log.error("Site connection test failed for %s: %s", site.url, exc)
        return {"success": False, "error": f"Could not reach WordPress: {exc}"}
