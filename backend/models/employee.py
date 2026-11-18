from datetime import datetime, timezone
import time
from sqlalchemy import Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Employee(Base):
    """Employee user account with role-based access control (admin vs employee)."""
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    # Stored as salted PBKDF2-HMAC-SHA256 — NEVER plain text, NEVER returned in responses
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="employee")  # "admin" | "employee"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

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

    # Relationships
    sessions = relationship("EmployeeSession", back_populates="employee", cascade="all, delete-orphan")
    basecamp_token = relationship("EmployeeBasecampToken", back_populates="employee", uselist=False, cascade="all, delete-orphan")

    def to_safe_dict(self) -> dict:
        """Safe representation without password hash."""
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<Employee id={self.id} email={self.email!r} role={self.role!r}>"


class EmployeeSession(Base):
    """Server-side employee login sessions with CSRF double-submit protection."""
    __tablename__ = "employee_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # Cryptographically random token
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    csrf_token: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    employee = relationship("Employee", back_populates="sessions")

    def is_expired(self) -> bool:
        now = _utcnow()
        if self.expires_at.tzinfo is None:
            now = datetime.utcnow()
        return now >= self.expires_at


class EmployeeBasecampToken(Base):
    """
    Per-employee encrypted Basecamp OAuth credentials.
    Strictly isolated: every employee uses their own account_id and encrypted access/refresh tokens.
    Global BASECAMP_ACCOUNT_ID never overrides an employee's connected account.
    """
    __tablename__ = "employee_basecamp_tokens"

    employee_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("employees.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Employee's OWN OAuth account_id resolved from Basecamp identity endpoint
    account_id: Mapped[str] = mapped_column(String, nullable=False)
    account_name: Mapped[str] = mapped_column(String, nullable=True)

    # Stored encrypted at rest using persistent TOKEN_ENCRYPTION_KEY
    encrypted_access_token: Mapped[str] = mapped_column(String, nullable=False)
    encrypted_refresh_token: Mapped[str] = mapped_column(String, nullable=False)
    token_type: Mapped[str] = mapped_column(String, default="Bearer", nullable=True)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=True)  # Epoch seconds

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

    employee = relationship("Employee", back_populates="basecamp_token")

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return time.time() >= self.expires_at

    def to_safe_dict(self) -> dict:
        """Safe representation without decrypted access/refresh tokens."""
        return {
            "employee_id": self.employee_id,
            "account_id": self.account_id,
            "account_name": self.account_name or f"Basecamp Account {self.account_id}",
            "is_connected": True,
            "is_expired": self.is_expired(),
            "expires_at": self.expires_at,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

