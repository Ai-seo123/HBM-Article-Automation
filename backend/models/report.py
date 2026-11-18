from datetime import datetime, timezone
import json
from sqlalchemy import Integer, String, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowReport(Base):
    __tablename__ = "workflow_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String, index=True, nullable=False)  # YYYY-MM-DD
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        index=True,
    )

    # Basecamp information
    article_title: Mapped[str] = mapped_column(String, nullable=False, index=True)
    filename: Mapped[str | None] = mapped_column(String, nullable=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    project_name: Mapped[str | None] = mapped_column(String, nullable=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attachment_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Workflow outcome
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)  # completed, duplicate, error, warning

    # Destination WordPress info
    wordpress_site_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wordpress_site_name: Mapped[str | None] = mapped_column(String, nullable=True)
    wordpress_site_url: Mapped[str | None] = mapped_column(String, nullable=True)
    wordpress_post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    draft_url: Mapped[str | None] = mapped_column(String, nullable=True)
    edit_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # Metadata fields
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    primary_category: Mapped[str | None] = mapped_column(String, nullable=True)
    all_categories: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    focus_keyphrase: Mapped[str | None] = mapped_column(String, nullable=True)
    image_source: Mapped[str | None] = mapped_column(String, nullable=True)
    image_source_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # Detailed QA breakdown
    qa_status: Mapped[str | None] = mapped_column(String, nullable=True)  # PASSED, WARNING, FAILED
    qa_checklist: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string

    # Detailed stages & debug info (never containing OAuth tokens or passwords)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string

    def to_dict(self) -> dict:
        def _parse_json(val, default):
            if not val:
                return default
            if isinstance(val, (dict, list)):
                return val
            try:
                return json.loads(val)
            except Exception:
                return default

        return {
            "id": self.id,
            "date": self.date,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "article_title": self.article_title,
            "filename": self.filename,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "message_id": self.message_id,
            "attachment_id": self.attachment_id,
            "status": self.status,
            "wordpress_site_id": self.wordpress_site_id,
            "wordpress_site_name": self.wordpress_site_name,
            "wordpress_site_url": self.wordpress_site_url,
            "wordpress_post_id": self.wordpress_post_id,
            "draft_url": self.draft_url,
            "edit_url": self.edit_url,
            "author": self.author,
            "primary_category": self.primary_category,
            "all_categories": _parse_json(self.all_categories, []),
            "focus_keyphrase": self.focus_keyphrase,
            "image_source": self.image_source,
            "image_source_url": self.image_source_url,
            "qa_status": self.qa_status,
            "qa_checklist": _parse_json(self.qa_checklist, {}),
            "details": _parse_json(self.details, {}),
        }

    def __repr__(self) -> str:
        return f"<WorkflowReport id={self.id} date={self.date!r} status={self.status!r} article={self.article_title!r}>"
