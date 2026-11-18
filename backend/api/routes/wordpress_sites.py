"""
API routes for WordPress destination sites.
All credentials are handled securely server-side.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

import services.site_service as site_service

router = APIRouter(prefix="/api/wordpress/sites", tags=["wordpress-sites"])


class SiteCreateRequest(BaseModel):
    name: str = Field(..., description="Display name for the site")
    url: str = Field(..., description="WordPress URL (e.g. https://example.com)")
    username: str = Field(..., description="WordPress username")
    app_password: str = Field(..., description="WordPress Application Password")
    is_default: bool = False


class SiteUpdateRequest(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    username: Optional[str] = None
    app_password: Optional[str] = None
    is_default: Optional[bool] = None


@router.get("", summary="List all configured WordPress sites")
def list_sites():
    """List configured WordPress sites without exposing passwords."""
    return {"sites": site_service.list_sites()}


@router.post("", summary="Add a new WordPress site")
def create_site(body: SiteCreateRequest):
    """Add a new WordPress destination site."""
    try:
        site = site_service.save_site(
            name=body.name,
            url=body.url,
            username=body.username,
            app_password=body.app_password,
            is_default=body.is_default,
        )
        return {"success": True, "site": site}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{site_id}", summary="Update a WordPress site")
def update_site(site_id: int, body: SiteUpdateRequest):
    """Update an existing WordPress site."""
    site = site_service.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    try:
        updated = site_service.save_site(
            name=body.name or site.name,
            url=body.url or site.url,
            username=body.username or site.username,
            app_password=body.app_password or site.app_password,
            is_default=body.is_default if body.is_default is not None else site.is_default,
            site_id=site_id,
        )
        return {"success": True, "site": updated}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{site_id}", summary="Delete a WordPress site")
def delete_site(site_id: int):
    """Delete a WordPress site configuration."""
    success = site_service.delete_site(site_id)
    if not success:
        raise HTTPException(status_code=404, detail="Site not found")
    return {"success": True}


@router.post("/{site_id}/test", summary="Test WordPress site credentials")
async def test_site_connection(site_id: int):
    """Test live REST API connection with the stored credentials."""
    site = site_service.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    result = await site_service.test_connection(site)
    return result


@router.get("/{site_id}/drafts", summary="List existing WordPress drafts (read-only)")
async def list_site_drafts(site_id: int):
    """Fetch existing draft posts from the specified site using read-only GET."""
    site = site_service.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    try:
        import services.wordpress as wp_service
        drafts = await wp_service.list_drafts(
            site_url=site.url,
            username=site.username,
            app_password=site.app_password,
        )
        return {"success": True, "drafts": drafts, "count": len(drafts)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch drafts: {str(exc)}")



@router.get("/{site_id}/authors", summary="List WordPress authors for site")
async def list_site_authors(site_id: int):
    """Fetch available WordPress authors dynamically for the specified site."""
    site = site_service.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    try:
        import services.wordpress as wp_service
        authors = await wp_service.get_site_authors(
            site_url=site.url,
            username=site.username,
            app_password=site.app_password,
        )
        return {"success": True, "authors": authors, "count": len(authors)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch authors: {str(exc)}")
