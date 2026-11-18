from datetime import datetime, timezone
from sqlalchemy import Integer, String, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WordPressSite(Base):
    __tablename__ = "wordpress_sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    username: Mapped[str] = mapped_column(String, nullable=False)
    # Stored server-side only — NEVER returned to the frontend
    app_password: Mapped[str] = mapped_column(String, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    def to_safe_dict(self) -> dict:
        """Return safe dictionary without exposing the app password."""
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "username": self.username,
            "is_default": self.is_default,
            "has_credentials": bool(self.app_password),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<WordPressSite id={self.id} name={self.name!r} url={self.url!r}>"
