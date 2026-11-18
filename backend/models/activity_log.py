from datetime import datetime, timezone
import json
from typing import Optional, Any, Dict
from sqlalchemy import Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ActivityLog(Base):
    """
    Immutable audit log entry for employee and workflow actions.
    Persisted across server restarts and Render persistent storage.
    """
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    employee_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    employee_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    employee_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="success", index=True)

    project_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    project_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    message_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    article_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    post_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    author_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    author_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    site_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    site_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        index=True,
    )

    # Relationships
    employee = relationship("Employee", foreign_keys=[employee_id])

    def to_dict(self) -> Dict[str, Any]:
        """Convert log entry to safe API representation."""
        parsed_details = None
        if self.details:
            try:
                parsed_details = json.loads(self.details)
            except Exception:
                parsed_details = self.details

        return {
            "id": self.id,
            "session_id": self.session_id,
            "employee_id": self.employee_id,
            "employee_name": self.employee_name or (self.employee.full_name if self.employee else None),
            "employee_email": self.employee_email or (self.employee.email if self.employee else None),
            "action": self.action,
            "status": self.status,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "message_id": self.message_id,
            "article_title": self.article_title,
            "post_id": self.post_id,
            "author_id": self.author_id,
            "author_name": self.author_name,
            "site_id": self.site_id,
            "site_name": self.site_name,
            "details": parsed_details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<ActivityLog id={self.id} action={self.action!r} status={self.status!r} emp={self.employee_id}>"

