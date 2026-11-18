"""
Pydantic schemas for the article processing API endpoint.
"""

from pydantic import BaseModel, Field
from typing import Optional


class ProcessRequest(BaseModel):
    """Request body for POST /api/articles/process."""
    project_id: int = Field(..., description="Basecamp project ID")
    message_id: int = Field(..., description="Basecamp message ID")
    attachment_id: str = Field(..., description="Basecamp attachment ID")
    site_id: Optional[int] = Field(None, description="Selected destination WordPress site ID")
    author_id: Optional[int] = Field(None, description="Selected WordPress author ID")
    image_provider: Optional[str] = Field(None, description="Chosen image provider (envato, pexels, etc.)")
    selected_image_data: Optional[dict] = Field(None, description="Manually selected image data from search or upload")
    pause_at_image: Optional[bool] = Field(False, description="Pause pipeline at featured-image approval gate")
    session_id: Optional[str] = Field(None, description="Session ID when resuming a paused workflow")
    resume_action: Optional[str] = Field(None, description="Action when resuming (e.g., 'approve_image')")
    custom_content: Optional[str] = Field(None, description="User-modified article content with custom links")
    custom_seo: Optional[dict] = Field(None, description="User-modified SEO fields")


class ExistingPost(BaseModel):
    """WordPress post found during duplicate check."""
    id: Optional[int] = None
    title: str = ""
    url: str = ""
    status: str = ""


class ArticleMeta(BaseModel):
    """Metadata about the processed document."""
    filename: str
    character_count: int


class AiResult(BaseModel):
    """Structured output from Gemini AI (SEO only) + preserved DOCX content."""
    title: str = ""
    content: str = ""
    client_seo_requirements: dict = Field(default_factory=dict)
    focus_keyphrase: str = ""
    seo_title: str = ""
    slug: str = ""
    meta_description: str = ""
    excerpt: str = ""
    synonyms: str = ""
    docx_hyperlinks: list = Field(default_factory=list)
    internal_links: list = Field(default_factory=list)
    authority_links: list = Field(default_factory=list)


class PipelineResult(BaseModel):
    status: str
    error: Optional[str] = None
    data: Optional[dict] = None


class DestinationInfo(BaseModel):
    """Destination WordPress post and media summary."""
    title: str = ""
    wordpress_site_id: Optional[int] = None
    wordpress_site_name: Optional[str] = None
    wordpress_site_url: Optional[str] = None
    primary_category: str = "Uncategorized"
    featured_category: bool = False
    all_categories: list[str] = Field(default_factory=list)
    author: str = "Home Office Editor"
    status: str = "draft"
    post_id: Optional[int] = None
    url: Optional[str] = None
    edit_url: Optional[str] = None
    featured_media_id: Optional[int] = None
    focus_keyphrase: Optional[str] = ""
    image_source: str = ""
    image_source_url: str = ""
    image_dimensions: str = "1000 × 667 px"
    alt_text: str = ""
    image_title: str = ""
    caption: str = ""


class ProcessResponse(BaseModel):
    """Response from POST /api/articles/process."""
    status: str = Field(
        ...,
        description="One of: completed, duplicate, error",
    )
    duplicate: bool = False
    unchecked_wp: bool = Field(
        False,
        description="True if WordPress duplicate check was skipped (not configured).",
    )
    existing_post: Optional[ExistingPost] = None
    duplicate_result: Optional[PipelineResult] = None
    article: Optional[ArticleMeta] = None
    ai_result: Optional[AiResult] = None
    yoast_result: Optional[PipelineResult] = None
    envato_result: Optional[PipelineResult] = None
    draft_result: Optional[PipelineResult] = None
    qa_result: Optional[PipelineResult] = None
    qa_checklist: Optional[dict] = Field(
        None,
        description="QA checklist of all verification items.",
    )
    destination: Optional[DestinationInfo] = Field(
        None,
        description="Destination post and category summary for the frontend.",
    )
    error: Optional[str] = None
    stages: list[str] = Field(
        default_factory=list,
        description="Step-by-step progress messages for the UI.",
    )
    session_id: Optional[str] = Field(None, description="Session ID for paused workflow")
    image_candidates: Optional[list] = Field(default_factory=list, description="Candidate images for manual approval")
    paused_step: Optional[str] = Field(None, description="Key of the paused gate, e.g. 'image_gate'")
    stage_statuses: Optional[dict[str, str]] = Field(
        default_factory=dict,
        description="Current real status of each of the 10 workflow stages: pending, processing, completed, failed.",
    )
