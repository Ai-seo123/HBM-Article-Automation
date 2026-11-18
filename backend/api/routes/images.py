"""
API routes for image providers and multi-platform image search.
"""

from fastapi import APIRouter, Query, HTTPException
import services.image_service as image_service

router = APIRouter(prefix="/api/images", tags=["images"])


@router.get("/providers", summary="List supported image provider platforms")
async def get_providers(refresh: bool = Query(False, description="Force refresh provider health status")):
    """List all supported platforms with dynamic availability and verification status."""
    return {"providers": await image_service.list_providers(force_refresh=refresh)}


@router.get("/search", summary="Search images from a provider")
async def search_images(
    provider: str = Query("envato", description="Provider id (envato, pexels, etc.)"),
    query: str = Query(..., description="Search query / article title"),
):
    """Search images on the chosen provider and return real results."""
    result = await image_service.search_provider(provider=provider, query=query)
    return result
