from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ArticleBase(BaseModel):
    title: str
    slug: str
    status: str = "pending"
    source: str | None = None
    source_id: str | None = None
    wordpress_url: str | None = None


class ArticleCreate(ArticleBase):
    """Schema for creating a new article (request body)."""
    pass


class ArticleResponse(ArticleBase):
    """Schema for returning an article from the API (includes DB-generated fields)."""
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
